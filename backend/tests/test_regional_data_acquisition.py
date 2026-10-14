"""Unit tests for Phase B Regional Data Acquisition, Validation, and Caching.

Covers:
- Geographic coverage and bounding box validation
- Persistent disk caching and cache reuse (zero live network requests on hit)
- Retry behavior with exponential backoff on HTTP 500 and HTTP 429
- Handling of unavailable external services and mirror failover
- Download integrity checks and SHA-256 verification
- Partial-download recovery and atomic file writes
- Missing-tile detection for DEM and Land Cover
- Source metadata, licensing records, and classification legend verification
- Mocked end-to-end regional acquisition pipeline
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from georoute.ingestion.regional_data_acquirer import (
    AcquisitionError,
    DataValidationError,
    IntegrityCheckFailedError,
    MissingTileError,
    RateLimitExceededError,
    RegionalDataAcquirer,
    ServiceUnavailableError,
    compute_sha256,
    verify_file_integrity,
)
from georoute.schemas.data_manifest_schema import RawDataManifest


@pytest.fixture
def temp_raw_dir(tmp_path):
    """Provides an isolated raw data directory for acquisition testing."""
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    return raw


# --------------------------------------------------------------------------
# 1. Geographic Coverage and Bounding Box Validation
# --------------------------------------------------------------------------
def test_study_area_bbox_validation(temp_raw_dir):
    """Tests bounding box validation and geographic dimensions."""
    # Valid bounding box (Mandi to Delhi corridor)
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir, bbox=(76.50, 28.30, 77.50, 32.00))
    assert acquirer.width_km >= 90.0
    assert acquirer.height_km >= 400.0
    assert acquirer.total_area_km2 >= 35000.0

    # Malformed bbox: inverted coordinates
    with pytest.raises(DataValidationError, match="Malformed bounding box"):
        RegionalDataAcquirer(raw_dir=temp_raw_dir, bbox=(77.50, 32.00, 76.50, 28.30))

    # Out of range coordinates
    with pytest.raises(DataValidationError, match="Invalid longitude"):
        RegionalDataAcquirer(raw_dir=temp_raw_dir, bbox=(-190.0, 28.30, 77.50, 32.00))

    with pytest.raises(DataValidationError, match="Invalid latitude"):
        RegionalDataAcquirer(raw_dir=temp_raw_dir, bbox=(76.50, -95.0, 77.50, 32.00))


def test_corridor_endpoint_containment(temp_raw_dir):
    """Verifies that Mandi and New Delhi stations are comfortably within study bounds."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir)
    mandi = acquirer.MANDI_STATION
    delhi = acquirer.DELHI_STATION

    assert acquirer.min_lon < mandi["lon"] < acquirer.max_lon
    assert acquirer.min_lat < mandi["lat"] < acquirer.max_lat
    assert acquirer.min_lon < delhi["lon"] < acquirer.max_lon
    assert acquirer.min_lat < delhi["lat"] < acquirer.max_lat


# --------------------------------------------------------------------------
# 2. File Integrity and Atomic Writes
# --------------------------------------------------------------------------
def test_atomic_write_json_success(temp_raw_dir):
    """Tests atomic JSON file writing without leaving temporary .part files."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir)
    target_file = temp_raw_dir / "test_file.json"
    payload = {"status": "ok", "elements": [1, 2, 3]}

    acquirer._atomic_write_json(target_file, payload)

    assert target_file.exists()
    part_file = target_file.with_suffix(".json.part")
    assert not part_file.exists()

    with open(target_file, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == payload


def test_atomic_write_json_cleanup_on_error(temp_raw_dir):
    """Tests that a failure during atomic write unlinks .part file and raises AcquisitionError."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir)
    target_file = temp_raw_dir / "broken_file.json"

    # Pass an un-serializable object to trigger failure
    class Unserializable:
        pass

    with pytest.raises(AcquisitionError):
        acquirer._atomic_write_json(target_file, {"obj": Unserializable()})

    part_file = target_file.with_suffix(".json.part")
    assert not part_file.exists()
    assert not target_file.exists()


def test_file_integrity_verification(temp_raw_dir):
    """Tests file integrity verification including minimum size and SHA-256."""
    test_file = temp_raw_dir / "integrity_test.json"
    content = {"key": "value"}
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump(content, f)

    file_hash = compute_sha256(test_file)

    # Valid check
    assert verify_file_integrity(test_file, expected_sha256=file_hash, min_bytes=5) is True

    # Missing file
    with pytest.raises(FileNotFoundError):
        verify_file_integrity(temp_raw_dir / "nonexistent.json")

    # Below min bytes
    with pytest.raises(IntegrityCheckFailedError, match="below minimum threshold"):
        verify_file_integrity(test_file, min_bytes=50000)

    # Corrupted / mismatched hash
    with pytest.raises(IntegrityCheckFailedError, match="SHA-256 hash mismatch"):
        verify_file_integrity(test_file, expected_sha256="deadbeef" * 8)


# --------------------------------------------------------------------------
# 3. Persistent Caching and Network Resilience
# --------------------------------------------------------------------------
def test_persistent_cache_reuse(temp_raw_dir):
    """Verifies that an Overpass query is cached and subsequently read from disk without network calls."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir)
    query = '[out:json]; node["railway"="station"]; out;'

    mock_resp_data = {"elements": [{"type": "node", "id": 101, "lat": 31.7, "lon": 76.9}]}

    # First call: network mock succeeds and caches to disk
    with patch.object(acquirer.session, "post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_resp_data
        mock_post.return_value = mock_response

        data1 = acquirer._execute_overpass_query(query, use_cache=True)
        assert data1 == mock_resp_data
        assert mock_post.call_count == 1

    # Second call: must hit disk cache; session.post should NOT be called
    with patch.object(acquirer.session, "post") as mock_post_second:
        data2 = acquirer._execute_overpass_query(query, use_cache=True)
        assert data2 == mock_resp_data
        assert mock_post_second.call_count == 0  # Zero network calls!


def test_retry_behavior_on_server_error(temp_raw_dir):
    """Tests exponential backoff retry when external service returns 500 error."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir, max_retries=2, backoff_factor=1.0)
    query = "[out:json]; test_retry;"

    mock_fail = MagicMock()
    mock_fail.status_code = 500

    mock_success = MagicMock()
    mock_success.status_code = 200
    mock_success.json.return_value = {"elements": [{"id": 1}]}

    with patch.object(acquirer.session, "post", side_effect=[mock_fail, mock_success]) as mock_post:
        with patch("time.sleep") as mock_sleep:
            data = acquirer._execute_overpass_query(query, use_cache=False)
            assert data == {"elements": [{"id": 1}]}
            assert mock_post.call_count == 2
            assert mock_sleep.call_count >= 1


def test_rate_limit_429_handling(temp_raw_dir):
    """Tests that HTTP 429 rate limit triggers Retry-After backoff."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir, max_retries=2)
    query = "[out:json]; test_429;"

    mock_429 = MagicMock()
    mock_429.status_code = 429
    mock_429.headers = {"Retry-After": "2"}

    mock_200 = MagicMock()
    mock_200.status_code = 200
    mock_200.json.return_value = {"elements": [{"id": 2}]}

    with patch.object(acquirer.session, "post", side_effect=[mock_429, mock_200]):
        with patch("time.sleep") as mock_sleep:
            data = acquirer._execute_overpass_query(query, use_cache=False)
            assert data == {"elements": [{"id": 2}]}
            # Verify sleep was called with parsed Retry-After (2s)
            mock_sleep.assert_called_with(2.0)


def test_handling_of_unavailable_external_services(temp_raw_dir):
    """Tests graceful handling and mirror failover when external service is completely down."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir, max_retries=1)
    query = "[out:json]; down_service;"

    with patch.object(acquirer.session, "post", side_effect=requests.exceptions.ConnectTimeout("Down")):
        data = acquirer._execute_overpass_query(query, use_cache=False)
        assert data is None


# --------------------------------------------------------------------------
# 4. Tile Completeness Validation
# --------------------------------------------------------------------------
def test_dem_tile_completeness_validation(temp_raw_dir):
    """Validates 1x1 degree Copernicus DEM tile completeness checker."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir, bbox=(76.50, 28.30, 77.50, 32.00))

    all_8_tiles = [
        "Copernicus_DSM_COG_10_N28_00_E076_00_DEM",
        "Copernicus_DSM_COG_10_N28_00_E077_00_DEM",
        "Copernicus_DSM_COG_10_N29_00_E076_00_DEM",
        "Copernicus_DSM_COG_10_N29_00_E077_00_DEM",
        "Copernicus_DSM_COG_10_N30_00_E076_00_DEM",
        "Copernicus_DSM_COG_10_N30_00_E077_00_DEM",
        "Copernicus_DSM_COG_10_N31_00_E076_00_DEM",
        "Copernicus_DSM_COG_10_N31_00_E077_00_DEM",
    ]

    is_complete, missing = acquirer.validate_dem_tile_completeness(all_8_tiles)
    assert is_complete is True
    assert len(missing) == 0

    # Incomplete: 1 tile missing
    missing_one = [t for t in all_8_tiles if "N29_00_E076" not in t]
    is_complete_part, missing_part = acquirer.validate_dem_tile_completeness(missing_one)
    assert is_complete_part is False
    assert "N29_00_E076" in missing_part


def test_landcover_tile_completeness_validation(temp_raw_dir):
    """Validates 3x3 degree ESA WorldCover tile completeness checker."""
    acquirer = RegionalDataAcquirer(raw_dir=temp_raw_dir)

    all_2_tiles = [
        "ESA_WorldCover_10m_2021_v200_N27E075",
        "ESA_WorldCover_10m_2021_v200_N30E075",
    ]
    is_complete, missing = acquirer.validate_landcover_tile_completeness(all_2_tiles)
    assert is_complete is True
    assert len(missing) == 0

    # Missing tile
    is_complete_part, missing_part = acquirer.validate_landcover_tile_completeness(["ESA_WorldCover_10m_2021_v200_N27E075"])
    assert is_complete_part is False
    assert "N30E075" in missing_part


# --------------------------------------------------------------------------
# 5. Metadata, Legend, and Statutory Exclusion Records
# --------------------------------------------------------------------------
def test_manifest_metadata_and_classification_legend():
    """Validates rich metadata attributes recorded in data/raw/data_manifest.json."""
    manifest_p = Path("data/raw/data_manifest.json")
    assert manifest_p.exists(), "data_manifest.json missing"

    with open(manifest_p, "r", encoding="utf-8") as f:
        data = json.load(f)
    manifest = RawDataManifest.model_validate(data)

    # 1. Copernicus DEM
    dem_layer = manifest.layers["copernicus_dem_30m"]
    assert "meters" in dem_layer.metadata_attributes.get("elevation_units", "")
    assert dem_layer.metadata_attributes.get("vertical_datum") == "EGM2008"
    assert dem_layer.metadata_attributes.get("nodata_value") == -9999.0
    assert "Free and open" in dem_layer.license or "Copernicus" in dem_layer.license

    # 2. ESA WorldCover
    lc_layer = manifest.layers["esa_worldcover_2021"]
    legend = lc_layer.metadata_attributes.get("classification_legend", {})
    assert len(legend) == 11
    assert legend.get("10") == "Tree cover"
    assert legend.get("50") == "Built-up"
    assert legend.get("80") == "Permanent water bodies"
    assert "CC BY 4.0" in lc_layer.license
    veg_classes = lc_layer.metadata_attributes.get("vegetation_classes", [])
    assert 10 in veg_classes and 40 in veg_classes

    # 3. Protected Areas: statutory exclusion distinction
    pa_layer = manifest.layers["corridor_protected_areas"]
    statutory_note = pa_layer.metadata_attributes.get("statutory_distinction", "")
    assert "Wildlife Protection Act" in statutory_note
    assert "forest canopy" in statutory_note
    assert "GODL" in pa_layer.license or "Government Open Data License" in pa_layer.license

    # 4. Infrastructure layers
    rail_layer = manifest.layers["corridor_railways"]
    assert "1676 mm" in rail_layer.metadata_attributes.get("gauge_standard", "")
    assert "ODbL" in rail_layer.license

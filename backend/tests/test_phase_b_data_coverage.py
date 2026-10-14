"""Unit and integration tests for Phase B: Full Mandi-to-Delhi Data Coverage."""

import json
from pathlib import Path
import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import Point, box

from georoute.ingestion.regional_data_acquirer import RegionalDataAcquirer
from georoute.schemas.data_manifest_schema import RawDataManifest


@pytest.fixture
def acquirer():
    """Returns initialized RegionalDataAcquirer fixture."""
    return RegionalDataAcquirer(raw_dir=Path("data/raw"))


@pytest.fixture
def manifest():
    """Loads Phase B raw data manifest."""
    manifest_path = Path("data/raw/data_manifest.json")
    assert manifest_path.exists(), "Phase B data manifest missing at data/raw/data_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RawDataManifest.model_validate(data)


def test_corridor_study_area_definition(acquirer):
    """Verifies study area bounding box and endpoint coverage with lateral margins."""
    bbox = acquirer.study_area_bounds
    assert bbox.min_lon == 76.50
    assert bbox.min_lat == 28.30
    assert bbox.max_lon == 77.50
    assert bbox.max_lat == 32.00
    assert bbox.width_km >= 90.0
    assert bbox.height_km >= 400.0
    assert bbox.total_area_km2 >= 35000.0

    # Test Mandi Station inside bounds with margin
    mandi = acquirer.MANDI_STATION
    assert bbox.min_lon < mandi["lon"] < bbox.max_lon
    assert bbox.min_lat < mandi["lat"] < bbox.max_lat
    assert (mandi["lon"] - bbox.min_lon) >= 0.3  # >30km west margin
    assert (bbox.max_lon - mandi["lon"]) >= 0.4  # >40km east margin

    # Test New Delhi Station inside bounds with margin
    delhi = acquirer.DELHI_STATION
    assert bbox.min_lon < delhi["lon"] < bbox.max_lon
    assert bbox.min_lat < delhi["lat"] < bbox.max_lat
    assert (delhi["lon"] - bbox.min_lon) >= 0.5  # >50km west margin
    assert (delhi["lat"] - bbox.min_lat) >= 0.2  # >20km south margin


def test_data_manifest_schema_and_integrity(manifest):
    """Verifies that the generated manifest adheres strictly to RawDataManifest schema."""
    assert manifest.schema_version == "2.0.0"
    assert manifest.corridor_id == "mandi_to_new_delhi"
    assert len(manifest.layers) == 8
    assert manifest.validation_summary.get("all_layers_valid") is True
    assert manifest.validation_summary.get("both_endpoints_covered_by_dem") is True
    assert manifest.validation_summary.get("both_endpoints_covered_by_landcover") is True
    assert len(manifest.reused_local_datasets) >= 5


def test_protected_areas_corridor_coverage(manifest):
    """Validates the clipped corridor protected areas dataset."""
    entry = manifest.layers["corridor_protected_areas"]
    assert entry.validation_status == "VALID"
    assert entry.feature_or_tile_count >= 30
    assert entry.crs == "EPSG:4326"

    pa_file = Path("data/raw/vectors/corridor_protected_areas.geojson")
    assert pa_file.exists()
    gdf = gpd.read_file(pa_file)
    assert len(gdf) == entry.feature_or_tile_count
    assert gdf.crs == "EPSG:4326"
    assert gdf.geometry.is_valid.all()

    # Check that major national parks / sanctuaries are captured
    names = " ".join([str(n) for n in gdf.get("name", [])])
    assert "Shikari Devi" in names or "Kalesar" in names or "Sultanpur" in names


def test_copernicus_dem_metadata_and_endpoints(manifest):
    """Validates Copernicus DEM GLO-30 tile coverage and terminal rasters."""
    entry = manifest.layers["copernicus_dem_30m"]
    assert entry.validation_status == "VALID"
    assert entry.feature_or_tile_count == 8
    assert entry.nominal_resolution == "30m"
    assert entry.endpoint_coverage.mandi_covered is True
    assert entry.endpoint_coverage.delhi_covered is True

    # Check terminal DEMs
    mandi_dem = Path("data/raw/dem/mandi_dem_30m.tif")
    delhi_dem = Path("data/raw/dem/delhi_dem_30m.tif")
    assert mandi_dem.exists()
    assert delhi_dem.exists()

    with rasterio.open(mandi_dem) as src:
        assert src.res[0] > 0 and src.res[1] > 0
        assert src.nodata == -9999.0
        assert src.crs.to_string() == "EPSG:32643"
        # Mandi station in UTM Zone 43N: (683095.0, 3509735.0)
        assert src.bounds.left <= 683095.0 <= src.bounds.right
        assert src.bounds.bottom <= 3509735.0 <= src.bounds.top

    with rasterio.open(delhi_dem) as src:
        assert src.res[0] > 0 and src.res[1] > 0
        assert src.nodata == -9999.0
        assert src.crs.to_string() == "EPSG:32643"
        # New Delhi station in UTM Zone 43N: (716880.0, 3170240.0)
        assert src.bounds.left <= 716880.0 <= src.bounds.right
        assert src.bounds.bottom <= 3170240.0 <= src.bounds.top



def test_esa_worldcover_metadata_and_endpoints(manifest):
    """Validates ESA WorldCover 2021 v200 STAC metadata."""
    entry = manifest.layers["esa_worldcover_2021"]
    assert entry.validation_status == "VALID"
    assert entry.feature_or_tile_count == 2
    assert entry.endpoint_coverage.mandi_covered is True
    assert entry.endpoint_coverage.delhi_covered is True

    meta_file = Path("data/raw/landcover/esa_worldcover_tiles.json")
    assert meta_file.exists()
    with open(meta_file, "r", encoding="utf-8") as f:
        tiles = json.load(f)
    assert len(tiles) == 2
    item_ids = [t["item_id"] for t in tiles]
    assert any("N30E075" in tid for tid in item_ids)
    assert any("N27E075" in tid for tid in item_ids)


def test_infrastructure_and_waterways(manifest):
    """Validates acquired transport and water vector features."""
    for layer_id in ["corridor_railways", "corridor_stations", "corridor_waterways"]:
        entry = manifest.layers[layer_id]
        assert entry.validation_status == "VALID"
        assert entry.crs == "EPSG:4326"

        p = Path(entry.local_paths[0])
        assert p.exists()
        gdf = gpd.read_file(p)
        assert len(gdf) == entry.feature_or_tile_count


def test_reused_local_datasets_preservation():
    """Ensures existing fixtures in data/ remain completely unmodified."""
    assert Path("data/vector/protected_areas.geojson").exists()
    assert Path("data/dem/mandi_dem_30m.tif").exists()
    assert Path("data/dem/delhi_dem_30m.tif").exists()
    assert Path("data/cost/cost_surface_manifest.json").exists()
    assert Path("data/routes/routing_manifest.json").exists()

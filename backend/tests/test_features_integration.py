"""Integration tests for Part 2 Feature Extraction Pipeline."""

import json
from pathlib import Path
import numpy as np
import pytest
import rasterio

from georoute.features.feature_pipeline import FeaturePipeline


def test_feature_pipeline_on_real_processed_data():
    """Runs the FeaturePipeline against the actual Part 1 processed outputs."""
    processed_dir = Path("data/processed")
    if not (processed_dir / "rasters").exists():
        pytest.skip("Processed data directory not present, skipping real data integration test.")

    output_dir = Path("data/features")
    pipeline = FeaturePipeline(
        processed_dir=processed_dir,
        output_dir=output_dir,
        authoritative_pa_path=Path("data/vector/protected_areas.geojson"),
    )

    manifest = pipeline.run(region_name="mandi_terminal_5x5km")

    # 1. Manifest assertions
    assert manifest.pipeline_status == "SUCCESS"
    assert manifest.schema_version == "2.0.0"
    assert manifest.region_name == "mandi_terminal_5x5km"
    assert manifest.elapsed_seconds > 0

    # 2. Files generated on disk
    manifest_file = output_dir / "features_manifest.json"
    assert manifest_file.exists()
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest_dict = json.load(f)
    assert manifest_dict["schema_version"] == "2.0.0"

    lc_summary_file = output_dir / "landcover_summary.json"
    assert lc_summary_file.exists()

    lc_mapping_file = output_dir / "landcover_class_mapping.json"
    assert lc_mapping_file.exists()

    # Verify the 6 essential Part 2 deliverables are explicitly identified
    assert "deliverables" in manifest_dict
    delivs = manifest_dict["deliverables"]
    assert "slope_in_degrees_and_percent" in delivs
    assert delivs["slope_in_degrees_and_percent"]["why_it_matters"] == "Supplies terrain measurements for later cost modeling"

    assert "cleaned_building_and_waterway_vectors" in delivs
    assert delivs["cleaned_building_and_waterway_vectors"]["why_it_matters"] == "Provides mapped physical-feature information"

    assert "aligned_obstacle_masks" in delivs
    assert delivs["aligned_obstacle_masks"]["why_it_matters"] == "Makes features usable in the same raster grid"

    assert "classified_land_cover_raster" in delivs
    assert delivs["classified_land_cover_raster"]["why_it_matters"] == "Distinguishes land-cover types without inventing cost weights"

    assert "environmental_layers" in delivs
    assert delivs["environmental_layers"]["why_it_matters"] == "Supplies available forest, wetland, and protected-area information"

    assert "manifest_and_validation_report" in delivs
    assert delivs["manifest_and_validation_report"]["why_it_matters"] == "Lets Part 3 consume the outputs without guessing"


    # 3. Check expected rasters
    expected_rasters = [
        "slope_degrees.tif",
        "slope_percent.tif",
        "classified_landcover.tif",
        "forest_mask.tif",
        "wetland_mask.tif",
        "cropland_mask.tif",
        "builtup_mask.tif",
        "water_mask.tif",
        "building_mask.tif",
        "railway_mask.tif",
        "highway_mask.tif",
        "combined_obstacle_mask.tif",
        "protected_area_mask.tif",
        "ndvi.tif",
    ]

    raster_dir = output_dir / "rasters"
    ref_shape = None
    ref_transform = None
    ref_crs = None

    for r_name in expected_rasters:
        r_path = raster_dir / r_name
        assert r_path.exists(), f"Expected raster {r_name} missing from {raster_dir}"
        with rasterio.open(r_path) as src:
            if ref_shape is None:
                ref_shape = (src.height, src.width)
                ref_transform = src.transform
                ref_crs = src.crs
            else:
                # Rigorous co-registration verification
                assert (src.height, src.width) == ref_shape, f"{r_name} shape mismatch"
                assert src.crs == ref_crs, f"{r_name} CRS mismatch"
                assert np.allclose(
                    [src.transform.a, src.transform.b, src.transform.c, src.transform.d, src.transform.e, src.transform.f],
                    [ref_transform.a, ref_transform.b, ref_transform.c, ref_transform.d, ref_transform.e, ref_transform.f],
                    atol=1e-5,
                ), f"{r_name} transform mismatch"

    # 4. Check expected vectors
    vector_dir = output_dir / "vectors"
    expected_vectors = ["physical_obstacles.geojson", "environmental_zones.geojson"]
    for v_name in expected_vectors:
        v_path = vector_dir / v_name
        assert v_path.exists(), f"Expected vector {v_name} missing from {vector_dir}"

    # 5. Check slope calculations
    with rasterio.open(raster_dir / "slope_degrees.tif") as deg_src:
        deg_arr = deg_src.read(1)
        valid_deg = deg_arr[deg_arr != -9999.0]
        assert len(valid_deg) > 0
        assert valid_deg.min() >= 0.0
        assert valid_deg.max() <= 90.0

    with rasterio.open(raster_dir / "slope_percent.tif") as pct_src:
        pct_arr = pct_src.read(1)
        valid_pct = pct_arr[pct_arr != -9999.0]
        assert len(valid_pct) > 0
        assert valid_pct.min() >= 0.0
        # Himalayan terrain in Mandi has steep slopes (> 100%)
        assert valid_pct.max() > 50.0

    # 6. Check optical NDVI validation
    assert "optical_validation" in manifest_dict
    if "forest_ndvi" in manifest_dict["optical_validation"]:
        assert manifest_dict["optical_validation"]["forest_ndvi"]["mean"] > 0.0


def test_feature_pipeline_isolated_harness(tmp_path):
    """Verifies FeaturePipeline execution with an isolated mock environment."""
    from rasterio.transform import from_origin

    processed_dir = tmp_path / "processed"
    rasters_dir = processed_dir / "rasters"
    vectors_dir = processed_dir / "vectors"
    rasters_dir.mkdir(parents=True)
    vectors_dir.mkdir(parents=True)

    # 1. Create mock DEM (10x10, origin (1000, 2000), 10m res)
    transform = from_origin(1000.0, 2000.0, 10.0, 10.0)
    crs = "EPSG:32643"
    dem_arr = np.linspace(1000.0, 1100.0, 100, dtype=np.float32).reshape((10, 10))

    dem_path = rasters_dir / "dem_copernicus_10m_test.tif"
    with rasterio.open(
        dem_path, "w", driver="GTiff", height=10, width=10, count=1,
        dtype=np.float32, crs=crs, transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(dem_arr, 1)

    # 2. Create mock WorldCover (10x10)
    lc_arr = np.full((10, 10), 10, dtype=np.uint8)  # Forest
    lc_path = rasters_dir / "landcover_worldcover_10m_test.tif"
    with rasterio.open(
        lc_path, "w", driver="GTiff", height=10, width=10, count=1,
        dtype=np.uint8, crs=crs, transform=transform, nodata=0.0,
    ) as dst:
        dst.write(lc_arr, 1)

    output_dir = tmp_path / "features"
    pipe = FeaturePipeline(
        processed_dir=processed_dir,
        output_dir=output_dir,
        authoritative_pa_path=None,
    )

    manifest = pipe.run(region_name="mock_test")
    assert manifest.pipeline_status == "SUCCESS"
    assert (output_dir / "features_manifest.json").exists()
    assert (output_dir / "rasters" / "slope_degrees.tif").exists()
    assert (output_dir / "rasters" / "classified_landcover.tif").exists()
    assert (output_dir / "rasters" / "forest_mask.tif").exists()
    assert (output_dir / "vectors" / "physical_obstacles.geojson").exists()
    assert len(manifest.deliverables) == 6

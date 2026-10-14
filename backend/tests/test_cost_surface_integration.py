"""Integration tests for Part 3 Multi-Objective Cost Surface Generation."""

import json
from pathlib import Path
import numpy as np
import pytest
import rasterio

from georoute.cost.cost_surface_builder import CostSurfaceBuilder
from georoute.cost.cost_assumptions import CostAssumptions


def test_cost_surface_builder_on_real_features():
    """Runs CostSurfaceBuilder on the validated Part 2 features."""
    features_dir = Path("data/features")
    if not (features_dir / "rasters").exists():
        pytest.skip("data/features/rasters not found, skipping real data integration test.")

    output_dir = Path("data/cost")
    builder = CostSurfaceBuilder(features_dir=features_dir, output_dir=output_dir)
    manifest = builder.build_all(region_name="mandi_terminal_5x5km")

    # 1. Manifest assertion
    assert manifest.pipeline_status == "SUCCESS"
    assert manifest.schema_version == "3.0.0"
    assert manifest.region_name == "mandi_terminal_5x5km"
    assert manifest.elapsed_seconds > 0

    # 2. Check JSON files on disk
    manifest_path = output_dir / "cost_surface_manifest.json"
    assert manifest_path.exists()
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_dict = json.load(f)
    assert manifest_dict["schema_version"] == "3.0.0"

    summary_path = output_dir / "cost_surface_summary.json"
    assert summary_path.exists()
    assumptions_path = output_dir / "cost_assumptions.json"
    assert assumptions_path.exists()

    # 3. Check expected rasters
    expected_rasters = [
        "distance_cost.tif",
        "distance_friction.tif",
        "construction_cost.tif",
        "construction_friction.tif",
        "environmental_cost.tif",
        "environmental_friction.tif",
        "hard_constraint_mask.tif",
        "valid_data_mask.tif",
        "slope_penalty.tif",
        "landcover_penalty.tif",
        "building_penalty.tif",
        "water_crossing_penalty.tif",
        "highway_crossing_penalty.tif",
        "forest_sensitivity.tif",
        "wetland_sensitivity.tif",
        "water_sensitivity.tif",
    ]

    raster_dir = output_dir / "rasters"
    ref_shape = (565, 579)
    ref_crs = "EPSG:32643"

    for r_name in expected_rasters:
        r_path = raster_dir / r_name
        assert r_path.exists(), f"Expected raster {r_name} missing from {raster_dir}"
        with rasterio.open(r_path) as src:
            assert (src.height, src.width) == ref_shape, f"{r_name} shape mismatch"
            assert src.crs.to_string() == ref_crs, f"{r_name} CRS mismatch"
            assert pytest.approx(src.res[0], abs=1e-3) == 10.0
            assert pytest.approx(src.res[1], abs=1e-3) == 10.0

    # 4. Check mathematical properties of primary cost surfaces
    with rasterio.open(raster_dir / "distance_cost.tif") as d_src:
        d_arr = np.array(d_src.read(1), copy=True)
        valid_dist = d_arr[d_arr != -9999.0]
        assert len(valid_dist) > 0
        # All traversable distance cells must be exactly 10.0 metres
        assert np.allclose(valid_dist, 10.0)

    with rasterio.open(raster_dir / "construction_cost.tif") as c_src:
        c_arr = np.array(c_src.read(1), copy=True)
        valid_const = c_arr[c_arr != -9999.0]
        assert len(valid_const) > 0
        # Construction difficulty cost must be >= 10.0 (base distance)
        assert np.all(valid_const >= 10.0)
        # In mountainous Mandi, mean cost should be substantially higher than 10.0
        assert valid_const.mean() > 30.0

    with rasterio.open(raster_dir / "environmental_cost.tif") as e_src:
        e_arr = np.array(e_src.read(1), copy=True)
        valid_env = e_arr[e_arr != -9999.0]
        assert len(valid_env) > 0
        # Environmental proxy cost must be >= 10.0
        assert np.all(valid_env >= 10.0)

    # 5. Check diagnostic visualization
    diag_plot = output_dir / "diagnostics" / "cost_surfaces_comparison.png"
    assert diag_plot.exists()
    assert diag_plot.stat().st_size > 10000  # Non-trivial image file


def test_cost_surface_builder_isolated_harness(tmp_path):
    """Verifies CostSurfaceBuilder execution with synthetic mock feature inputs."""
    from rasterio.transform import from_origin

    features_dir = tmp_path / "features"
    rasters_dir = features_dir / "rasters"
    rasters_dir.mkdir(parents=True)

    transform = from_origin(1000.0, 2000.0, 10.0, 10.0)
    crs = "EPSG:32643"
    shape = (10, 10)

    # 1. Mock slope percent
    slope_arr = np.linspace(0.0, 50.0, 100, dtype=np.float32).reshape(shape)
    with rasterio.open(
        rasters_dir / "slope_percent.tif", "w", driver="GTiff", height=10, width=10, count=1,
        dtype=np.float32, crs=crs, transform=transform, nodata=-9999.0,
    ) as dst:
        dst.write(slope_arr, 1)

    # 2. Mock classified landcover
    lc_arr = np.full(shape, 10, dtype=np.uint8)  # Forest
    with rasterio.open(
        rasters_dir / "classified_landcover.tif", "w", driver="GTiff", height=10, width=10, count=1,
        dtype=np.uint8, crs=crs, transform=transform, nodata=0.0,
    ) as dst:
        dst.write(lc_arr, 1)

    # 3. Mock binary masks
    for mask_name in [
        "building_mask.tif",
        "water_mask.tif",
        "highway_mask.tif",
        "forest_mask.tif",
        "wetland_mask.tif",
        "protected_area_mask.tif",
    ]:
        m_arr = np.zeros(shape, dtype=np.uint8)
        if mask_name == "forest_mask.tif":
            m_arr.fill(1)
        with rasterio.open(
            rasters_dir / mask_name, "w", driver="GTiff", height=10, width=10, count=1,
            dtype=np.uint8, crs=crs, transform=transform, nodata=255.0,
        ) as dst:
            dst.write(m_arr, 1)

    output_dir = tmp_path / "cost"
    builder = CostSurfaceBuilder(features_dir=features_dir, output_dir=output_dir)
    manifest = builder.build_all(region_name="mock_test")

    assert manifest.pipeline_status == "SUCCESS"
    assert (output_dir / "cost_surface_manifest.json").exists()
    assert (output_dir / "rasters" / "distance_cost.tif").exists()
    assert (output_dir / "rasters" / "construction_cost.tif").exists()
    assert (output_dir / "rasters" / "environmental_cost.tif").exists()

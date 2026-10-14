"""End-to-end integration tests for CorridorOptimizer on real Mandi Part 3 rasters and mock grids."""

import json
from pathlib import Path
import geopandas as gpd
import numpy as np
import pytest
import rasterio

from georoute.routing.corridor_optimizer import CorridorOptimizer
from georoute.schemas.routing_manifest_schema import RoutingManifest


def test_corridor_optimizer_on_real_mandi_rasters(tmp_path):
    """Executes multi-objective corridor optimization on validated Mandi Part 3 cost rasters."""
    cost_dir = Path("data/cost")
    if not (cost_dir / "rasters" / "distance_friction.tif").exists():
        pytest.skip("Part 3 cost rasters not found on disk, skipping real data e2e test.")

    features_dir = Path("data/features")
    output_dir = tmp_path / "routes"

    optimizer = CorridorOptimizer(
        cost_dir=cost_dir,
        features_dir=features_dir,
        output_dir=output_dir,
        pyorps_scale_factor=100.0,
    )

    # Mandi station: (lon=76.9322, lat=31.7084)
    # Local destination within the 5x5km Mandi study area (row 450, col 150): (681505.0, 3507675.0) in UTM 43N
    mandi_wgs84 = (76.9322, 31.7084)
    target_utm43n = (681505.0, 3507675.0)

    manifest = optimizer.optimize_corridors(
        source_coords=mandi_wgs84,
        target_coords=target_utm43n,
        source_crs="EPSG:4326",
        target_crs="EPSG:32643",
        source_name="Mandi Station",
        target_name="Mandi Southwest Terminal",
        region_name="mandi_terminal_5x5km",
        backend="pyorps",
    )

    # 1. Manifest assertion
    assert isinstance(manifest, RoutingManifest)
    assert manifest.schema_version == "4.0.0"
    assert manifest.pipeline_status == "SUCCESS"
    assert manifest.region_name == "mandi_terminal_5x5km"
    assert manifest.num_routes == 3
    assert len(manifest.routes) == 3
    assert manifest.elapsed_seconds > 0.0

    # 2. Verify all 3 routes
    expected_objectives = [
        "shortest_distance",
        "lowest_construction_difficulty",
        "lowest_environmental_impact",
    ]

    for route, expected_obj in zip(manifest.routes, expected_objectives):
        assert route.objective == expected_obj
        assert route.status == "preliminary_candidate_corridor"
        assert route.length_km > 2.0  # Approx 2.6km distance
        assert route.length_m > 2000.0
        assert route.accumulated_cost > 0.0
        assert route.num_nodes > 100
        assert route.validation["is_valid"] is True
        assert len(route.validation["errors"]) == 0

        # Slope profile
        assert "mean_percent" in route.slope_profile
        assert "max_percent" in route.slope_profile
        assert route.slope_profile["mean_percent"] > 0.0
        assert route.slope_profile["max_percent"] > 10.0

    # In Mandi mountainous terrain, construction difficulty cost must be significantly higher than pure distance
    dist_route = manifest.routes[0]
    const_route = manifest.routes[1]
    assert const_route.accumulated_cost > dist_route.accumulated_cost

    # 3. Check exported files on disk
    assert (output_dir / "routing_manifest.json").exists()
    assert (output_dir / "route_results.json").exists()

    geojson_path = output_dir / "routes.geojson"
    assert geojson_path.exists()

    gdf = gpd.read_file(geojson_path)
    assert len(gdf) == 3
    assert gdf.crs.to_string() == "EPSG:4326"
    assert "route_id" in gdf.columns
    assert "objective" in gdf.columns
    assert "length_km" in gdf.columns
    assert not gdf.geometry.is_empty.any()
    assert gdf.geometry.is_valid.all()


def test_corridor_optimizer_isolated_harness(tmp_path):
    """Verifies CorridorOptimizer execution on a synthetic mock environment."""
    import affine
    cost_dir = tmp_path / "cost"
    rasters_dir = cost_dir / "rasters"
    rasters_dir.mkdir(parents=True)

    transform = affine.Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0)
    crs = "EPSG:32643"
    shape = (10, 10)

    # Friction rasters
    for name in ["distance_friction.tif", "construction_friction.tif", "environmental_friction.tif"]:
        arr = np.ones(shape, dtype=np.float32)
        with rasterio.open(
            rasters_dir / name, "w", driver="GTiff", height=10, width=10, count=1,
            dtype=np.float32, crs=crs, transform=transform, nodata=-9999.0,
        ) as dst:
            dst.write(arr, 1)

    # Masks
    hard_mask = np.zeros(shape, dtype=np.uint8)
    valid_mask = np.ones(shape, dtype=np.uint8)
    for name, m in [("hard_constraint_mask.tif", hard_mask), ("valid_data_mask.tif", valid_mask)]:
        with rasterio.open(
            rasters_dir / name, "w", driver="GTiff", height=10, width=10, count=1,
            dtype=np.uint8, crs=crs, transform=transform, nodata=255,
        ) as dst:
            dst.write(m, 1)

    out_dir = tmp_path / "routes"
    optimizer = CorridorOptimizer(cost_dir=cost_dir, output_dir=out_dir)

    manifest = optimizer.optimize_corridors(
        source_coords=(1015.0, 1985.0),
        target_coords=(1085.0, 1915.0),
        source_crs="EPSG:32643",
        target_crs="EPSG:32643",
        source_name="Start",
        target_name="End",
        region_name="mock_test",
        backend="pyorps",
    )

    assert manifest.pipeline_status == "SUCCESS"
    assert manifest.num_routes == 3
    assert (out_dir / "routes.geojson").exists()
    assert (out_dir / "routing_manifest.json").exists()

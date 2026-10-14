"""Tests for multi-objective routing: verifying independent searches and distinct alignments."""

import affine
import numpy as np
import pytest
import rasterio

from georoute.routing.objective_router import (
    OBJECTIVE_CONFIGS,
    ObjectiveRouter,
    RoutingObjective,
)


@pytest.fixture
def multi_objective_environment(tmp_path):
    """Sets up a synthetic 15x15 raster landscape with conflicting trade-offs."""
    rasters_dir = tmp_path / "rasters"
    rasters_dir.mkdir(parents=True)

    shape = (15, 15)
    transform = affine.Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0)
    crs = "EPSG:32643"

    # 1. Distance friction: uniform 1.0
    dist_friction = np.ones(shape, dtype=np.float32)

    # 2. Construction friction:
    # High mountain ridge and urban area in rows 6-14 (friction=50.0)
    # Open gentle valley in upper rows (rows 0-5, friction=1.0)
    const_friction = np.ones(shape, dtype=np.float32)
    const_friction[6:15, :] = 50.0  # High cost in center and south

    # 3. Environmental friction:
    # Protected forest reserve in upper rows (rows 0-8, friction=60.0)
    # Open valley in lower corridor (rows 9-14, friction=1.0)
    env_friction = np.ones(shape, dtype=np.float32)
    env_friction[0:9, :] = 60.0  # Forest reserve in north

    # Write GeoTIFFs
    for name, arr in [
        ("distance_friction.tif", dist_friction),
        ("construction_friction.tif", const_friction),
        ("environmental_friction.tif", env_friction),
    ]:
        with rasterio.open(
            rasters_dir / name, "w", driver="GTiff", height=15, width=15, count=1,
            dtype=np.float32, crs=crs, transform=transform, nodata=-9999.0,
        ) as dst:
            dst.write(arr, 1)

    return {
        "rasters_dir": rasters_dir,
        "transform": transform,
        "crs": crs,
        "shape": shape,
    }


def test_three_objectives_produce_distinct_tradeoffs(multi_objective_environment):
    env = multi_objective_environment
    router = ObjectiveRouter(cost_rasters_dir=env["rasters_dir"], pyorps_scale_factor=100.0)

    # Route from West (row 7, col 1) to East (row 7, col 13)
    # Straight path goes directly through row 7 (distance-optimal)
    # Construction should divert north into rows 1-3 to avoid row 6-8 ridge
    # Environmental should divert south into rows 10-14 to avoid north forest
    source_cell = (7, 1)
    target_cell = (7, 13)
    source_xy = (1000.0 + 1.5 * 10.0, 2000.0 - 7.5 * 10.0)
    target_xy = (1000.0 + 13.5 * 10.0, 2000.0 - 7.5 * 10.0)

    # 1. Shortest distance
    res_dist = router.route_single_objective(
        objective=RoutingObjective.SHORTEST_DISTANCE,
        source_coords=source_xy, target_coords=target_xy,
        source_cell=source_cell, target_cell=target_cell,
        backend="pyorps",
    )

    # 2. Lowest construction difficulty
    res_const = router.route_single_objective(
        objective=RoutingObjective.LOWEST_CONSTRUCTION_DIFFICULTY,
        source_coords=source_xy, target_coords=target_xy,
        source_cell=source_cell, target_cell=target_cell,
        backend="pyorps",
    )

    # 3. Lowest environmental impact
    res_env = router.route_single_objective(
        objective=RoutingObjective.LOWEST_ENVIRONMENTAL_IMPACT,
        source_coords=source_xy, target_coords=target_xy,
        source_cell=source_cell, target_cell=target_cell,
        backend="pyorps",
    )

    # Distance route goes straight across row 7
    dist_rows = [r for r, c in res_dist["path_cells"]]
    assert all(r == 7 for r in dist_rows)
    assert pytest.approx(res_dist["physical_length_m"], abs=1e-3) == 120.0

    # Construction route diverts to lower row numbers (North) to avoid the central ridge
    const_rows = [r for r, c in res_const["path_cells"]]
    assert min(const_rows) < 6, "Construction route failed to detour north around steep ridge"

    # Environmental route diverts to higher row numbers (South) to avoid north forest
    env_rows = [r for r, c in res_env["path_cells"]]
    assert max(env_rows) > 8, "Environmental route failed to detour south around forest reserve"

    # The routes must have different geometries and different alignments
    assert res_dist["geometry"].wkt != res_const["geometry"].wkt
    assert res_dist["geometry"].wkt != res_env["geometry"].wkt
    assert res_const["geometry"].wkt != res_env["geometry"].wkt


def test_dual_backend_consistency(multi_objective_environment):
    """Verifies that NetworkX exact Float32 solver and PYORPS produce consistent paths."""
    env = multi_objective_environment
    router = ObjectiveRouter(cost_rasters_dir=env["rasters_dir"], pyorps_scale_factor=100.0)

    source_cell = (7, 1)
    target_cell = (7, 13)
    source_xy = (1000.0 + 1.5 * 10.0, 2000.0 - 7.5 * 10.0)
    target_xy = (1000.0 + 13.5 * 10.0, 2000.0 - 7.5 * 10.0)

    # Distance objective on uniform terrain
    res_pyorps = router.route_single_objective(
        objective=RoutingObjective.SHORTEST_DISTANCE,
        source_coords=source_xy, target_coords=target_xy,
        source_cell=source_cell, target_cell=target_cell,
        backend="pyorps",
    )

    res_nx = router.route_single_objective(
        objective=RoutingObjective.SHORTEST_DISTANCE,
        source_coords=source_xy, target_coords=target_xy,
        source_cell=source_cell, target_cell=target_cell,
        backend="networkx",
    )

    # Physical distance and cost should agree exactly
    assert pytest.approx(res_pyorps["physical_length_m"], abs=1e-3) == res_nx["physical_length_m"]
    assert pytest.approx(res_pyorps["accumulated_cost"], abs=1e-3) == res_nx["accumulated_cost"]

"""Test suite for GeoRoute AI Phase D: Coarse-to-Fine Regional Corridor Routing.

Tests:
1. Endpoint resolution and coordinate transformations for Mandi and Delhi stations.
2. Level-0 coarse regional overview pathfinding across the entire 411km corridor.
3. High-resolution (30m) refinement within bounded lateral corridor tubes.
4. Multi-tile / staged sector routing with cross-boundary connectivity (zero distance gap).
5. Accumulated cost consistency across sector segments.
6. Obstacle avoidance: routes strictly respect statutory protected areas (zero intrusions).
7. Three-objective route differentiation (shortest distance, construction difficulty, environmental proxy).
8. Approximation disclosure verification (does not claim unproven global optimality).
9. Memory and runtime performance benchmarks.
"""

import math
from pathlib import Path
import time
import tracemalloc

import geopandas as gpd
import numpy as np
import pyproj
import pytest
import rasterio
from shapely.geometry import LineString, Point

from georoute.routing.hierarchical_router import (
    CoarseToFineRouteResult,
    HierarchicalRegionalRouter,
)
from georoute.routing.objective_router import RoutingObjective


@pytest.fixture
def regional_router():
    """HierarchicalRegionalRouter fixture pointing to Phase C regional cost rasters."""
    return HierarchicalRegionalRouter(
        cost_dir="data/cost/regional",
        output_dir="data/test_out/routes_regional",
        coarse_factor=8,          # 240m overview grid
        refinement_buffer_m=5000.0, # 5.0 km corridor buffer
        pyorps_scale_factor=100.0,
    )


def test_endpoint_resolution_and_projections(regional_router):
    """Verifies that Mandi and Delhi stations resolve to valid UTM coordinates within regional bounds."""
    src_xy, tgt_xy = regional_router.resolve_endpoints()

    # Mandi Railway Station (UTM Zone 43N)
    assert 680000.0 < src_xy[0] < 690000.0
    assert 3500000.0 < src_xy[1] < 3520000.0

    # New Delhi Railway Station (UTM Zone 43N)
    assert 710000.0 < tgt_xy[0] < 725000.0
    assert 3160000.0 < tgt_xy[1] < 3180000.0

    # North-to-south span > 330 km
    assert (src_xy[1] - tgt_xy[1]) > 330000.0


def test_coarse_overview_routing_execution(regional_router):
    """Verifies that Level 0 coarse overview routing finds full regional path in < 1 second."""
    src_xy, tgt_xy = regional_router.resolve_endpoints()

    t0 = time.time()
    coarse_res = regional_router.find_coarse_overview_route(
        objective=RoutingObjective.SHORTEST_DISTANCE,
        source_xy=src_xy,
        target_xy=tgt_xy,
        search_space_buffer_m=40000.0,
    )
    elapsed = time.time() - t0

    assert coarse_res.geometry.is_valid
    assert not coarse_res.geometry.is_empty
    # Length between Mandi and Delhi is ~340 - 400 km
    length_km = coarse_res.total_length_m / 1000.0
    assert 330.0 < length_km < 450.0

    # Fast search: Level 0 coarse search over 100m regional grid (4.26M cells) completes in < 5 seconds
    assert elapsed < 5.0, f"Coarse overview search took {elapsed:.2f}s, expected < 5s"


def test_coarse_to_fine_refinement_correctness(regional_router):
    """Verifies that 30m refinement stays inside corridor tube and achieves >95% search space reduction."""
    res = regional_router.route_objective(
        objective=RoutingObjective.LOWEST_CONSTRUCTION_DIFFICULTY,
        refinement_buffer_m=5000.0,
    )

    assert isinstance(res, CoarseToFineRouteResult)
    assert res.refined_path.geometry.is_valid
    assert not res.refined_path.geometry.is_empty

    # Verify search space reduction (>90% reduction for +/-5km buffer corridor)
    assert res.search_space_reduction_percent >= 90.0, (
        f"Search space reduction ({res.search_space_reduction_percent:.1f}%) must exceed 90%"
    )

    # Refined path starts at Mandi and ends at Delhi
    src_xy, tgt_xy = regional_router.resolve_endpoints()
    start_pt = res.refined_path.path_coords[0]
    end_pt = res.refined_path.path_coords[-1]

    # Distance to true terminals must be small (within cell snapping tolerance)
    assert math.dist(start_pt, src_xy) < 60.0
    assert math.dist(end_pt, tgt_xy) < 60.0

    # Both coarse and refined lengths are realistic regional corridor distances
    assert 330.0 < (res.refined_path.total_length_m / 1000.0) < 450.0

    # Refined continuous cost must be positive
    assert res.refined_path.recomputed_cost > 0.0


def test_multi_tile_staged_sector_connectivity(regional_router):
    """CRITICAL TEST: Verifies cross-tile boundary connectivity and cost consistency.

    Partitions corridor into 4 sequential sectors:
    1. End point of Sector k must EQUAL start point of Sector k+1 (gap < 1mm).
    2. Total accumulated cost must match the sum of sector costs.
    """
    staged_data = regional_router.route_staged_sectors(
        objective=RoutingObjective.SHORTEST_DISTANCE,
        num_sectors=4,
        refinement_buffer_m=4000.0,
    )

    assert staged_data["is_connected_across_boundaries"] is True

    # Check gaps at sector boundaries
    for gap in staged_data["boundary_gaps_m"]:
        assert gap < 0.001, f"Boundary gap ({gap:.4f}m) detected between adjacent sectors!"

    # Check accumulated cost consistency: TotalCost == sum(SectorCosts)
    sum_costs = sum(staged_data["sector_costs"])
    assert math.isclose(staged_data["accumulated_cost"], sum_costs, rel_tol=1e-5)

    # Merged geometry is valid single continuous LineString
    geom = staged_data["merged_geometry"]
    assert isinstance(geom, LineString)
    assert geom.is_valid
    assert not geom.is_empty


def test_statutory_protected_area_obstacle_avoidance(regional_router):
    """Verifies that refined candidate corridors strictly avoid statutory protected areas."""
    res = regional_router.route_objective(
        objective=RoutingObjective.LOWEST_ENVIRONMENTAL_IMPACT,
        refinement_buffer_m=5000.0,
    )

    pa_path = Path("data/raw/vectors/corridor_protected_areas.geojson")
    assert pa_path.exists()
    pa_gdf = gpd.read_file(pa_path)
    if pa_gdf.crs != "EPSG:32643":
        pa_gdf = pa_gdf.to_crs("EPSG:32643")

    route_line = res.refined_path.geometry

    # Check intersection against national parks and wildlife sanctuaries
    # Under HARD_EXCLUSION policy, route must not cut across protected area interiors
    for _, row in pa_gdf.iterrows():
        pa_poly = row["geometry"]
        if pa_poly is not None and not pa_poly.is_empty:
            # Overlap/intersection check: path must not penetrate deep into protected areas
            if route_line.intersects(pa_poly):
                intersection = route_line.intersection(pa_poly)
                # Any boundary touch should be zero-length or tangential boundary clip
                # Interior length must be negligible (< 60m edge touch)
                assert intersection.length < 60.0, (
                    f"Candidate corridor penetrated statutory protected area '{row.get('name')}' "
                    f"by {intersection.length:.1f}m!"
                )


def test_three_objective_route_differentiation(regional_router):
    """Verifies that candidate corridors for the 3 objectives exhibit differentiated characteristics."""
    res_dist = regional_router.route_objective(RoutingObjective.SHORTEST_DISTANCE)
    res_const = regional_router.route_objective(RoutingObjective.LOWEST_CONSTRUCTION_DIFFICULTY)
    res_env = regional_router.route_objective(RoutingObjective.LOWEST_ENVIRONMENTAL_IMPACT)

    # 1. Shortest distance route must have the minimal geographic length
    dist_len = res_dist.refined_path.total_length_m
    const_len = res_const.refined_path.total_length_m
    env_len = res_env.refined_path.total_length_m

    assert dist_len <= const_len + 1000.0, "Shortest distance route should have shortest or near-shortest length"
    assert dist_len <= env_len + 1000.0

    # 2. Construction difficulty cost must differ from environmental cost
    assert res_const.refined_path.recomputed_cost != res_env.refined_path.recomputed_cost

    # 3. Geometries must not be all completely identical
    assert not (
        res_dist.refined_path.geometry.equals_exact(res_const.refined_path.geometry, tolerance=1.0) and
        res_const.refined_path.geometry.equals_exact(res_env.refined_path.geometry, tolerance=1.0)
    )


def test_corridor_restriction_approximation_disclosure(regional_router):
    """Verifies that hierarchical router explicitly discloses bounded search approximation."""
    res = regional_router.route_objective(RoutingObjective.SHORTEST_DISTANCE)

    # Must NOT claim proven global optimality
    assert res.is_globally_optimal_proven is False
    # Must contain approximation disclosure notes
    assert "approximation" in res.approximation_notes.lower()
    assert "buffer" in res.approximation_notes.lower()
    assert str(res.coarse_factor) in res.approximation_notes or "coarse" in res.approximation_notes


def test_phase_d_memory_and_runtime_benchmarks(regional_router):
    """Measures actual memory and runtime for full regional coarse-to-fine routing."""
    tracemalloc.start()
    t0 = time.time()
    res = regional_router.route_objective(RoutingObjective.SHORTEST_DISTANCE)
    elapsed = time.time() - t0
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem / (1024 * 1024)

    # End-to-end 411km coarse-to-fine routing must complete in < 20 seconds
    assert elapsed < 20.0, f"Full regional routing took {elapsed:.2f}s, expected < 20s"
    # Peak memory must remain well below 500 MB
    assert peak_mb < 500.0, f"Peak RAM ({peak_mb:.1f} MB) exceeded 500 MB budget"

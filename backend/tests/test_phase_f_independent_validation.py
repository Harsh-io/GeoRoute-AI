"""Test suite for GeoRoute AI Phase F: Independent Route Validation and Failure Testing.

Tests:
1. Independent verification of candidate corridors (geometry, length, cost, NoData).
2. Endpoint snapping audit (sub-grid resolution displacement verification).
3. Independent cost recomputation exactness (<0.01% discrepancy).
4. Statutory protected area clearance (zero reserve intrusions).
5. Multi-objective trade-off verification (shortest distance, construction, environment).
6. Negative / failure testing: Infeasible endpoints inside national parks.
7. Negative / failure testing: Out-of-bounds coordinates.
8. Negative / failure testing: Missing or corrupted raster datasets.
9. Railway engineering limitations disclosure audit.
10. Performance and memory consumption budgets.
"""

import math
from pathlib import Path
import time
import tracemalloc

import geopandas as gpd
import pytest
from shapely.geometry import Point

from georoute.routing.endpoint_validator import EndpointValidationError
from georoute.routing.pyorps_adapter import InfeasibleRouteError
from georoute.routing.hierarchical_router import HierarchicalRegionalRouter
from georoute.routing.objective_router import RoutingObjective
from georoute.validation.independent_validator import IndependentRouteValidator


@pytest.fixture
def route_validator():
    """IndependentRouteValidator fixture."""
    return IndependentRouteValidator(
        rasters_dir="data/cost/regional/rasters",
        vectors_dir="data/raw/vectors",
        crs="EPSG:32643",
        snapping_tolerance_m=60.0,
    )


@pytest.fixture
def regional_router():
    """HierarchicalRegionalRouter fixture."""
    return HierarchicalRegionalRouter(
        cost_dir="data/cost/regional",
        output_dir="data/routes/regional",
        coarse_factor=8,
        refinement_buffer_m=5000.0,
        pyorps_scale_factor=100.0,
    )


# ------------------------------------------------------------------------------
# 1. Independent Corridor Verification
# ------------------------------------------------------------------------------

def test_independent_validation_all_candidate_corridors(route_validator):
    """Verifies that all candidate corridors pass decoupled independent validation."""
    geojson_path = Path("data/routes/regional/candidate_corridors.geojson")
    assert geojson_path.exists(), "candidate_corridors.geojson deliverable missing"

    summary = route_validator.validate_all_routes(geojson_path)

    assert summary.overall_status == "PASSED"
    assert summary.num_routes_validated == 3
    assert summary.all_routes_valid is True
    assert summary.all_endpoints_correct is True
    assert summary.zero_nodata_violations is True
    assert summary.zero_protected_area_intrusions is True
    assert summary.expected_tradeoffs_exhibited is True

    for r in summary.route_results:
        assert r.is_valid is True
        assert r.validation_status == "PASSED"
        assert len(r.failure_reasons) == 0


def test_endpoint_snapping_within_subgrid_tolerance(route_validator):
    """Verifies that start and destination snapping offsets are well within cell tolerance."""
    geojson_path = Path("data/routes/regional/candidate_corridors.geojson")
    summary = route_validator.validate_all_routes(geojson_path)

    for r in summary.route_results:
        # Snapping displacement must be < 30m (sub-grid pixel resolution)
        assert r.start_snapping_distance_m < 30.0, f"Start snap ({r.start_snapping_distance_m}m) exceeded 30m"
        assert r.dest_snapping_distance_m < 30.0, f"Dest snap ({r.dest_snapping_distance_m}m) exceeded 30m"
        assert r.endpoints_match_requested is True


def test_independent_cost_recomputation_exactness(route_validator):
    """Verifies that independent line-integral cost recomputation matches reported costs within <0.01%."""
    geojson_path = Path("data/routes/regional/candidate_corridors.geojson")
    summary = route_validator.validate_all_routes(geojson_path)

    for r in summary.route_results:
        assert r.cost_calculation_consistent is True
        assert r.cost_discrepancy_percent < 0.01, (
            f"Cost discrepancy ({r.cost_discrepancy_percent:.4f}%) exceeded 0.01% for {r.route_id}"
        )


def test_statutory_protected_area_clearance_and_immunity(route_validator):
    """Verifies zero penetration into statutory National Parks and Wildlife Sanctuaries."""
    geojson_path = Path("data/routes/regional/candidate_corridors.geojson")
    summary = route_validator.validate_all_routes(geojson_path)

    for r in summary.route_results:
        assert r.protected_area_intrusions_count == 0
        assert r.protected_area_penetration_length_m == 0.0
        assert r.min_clearance_to_protected_area_m > 0.0


def test_multi_objective_trade_offs_audit(route_validator):
    """Verifies that candidate corridors exhibit the expected multi-objective trade-offs."""
    geojson_path = Path("data/routes/regional/candidate_corridors.geojson")
    summary = route_validator.validate_all_routes(geojson_path)

    by_obj = {r.objective: r for r in summary.route_results}
    dist_r = by_obj["shortest_distance"]
    const_r = by_obj["lowest_construction_difficulty"]
    env_r = by_obj["lowest_environmental_impact"]

    # Shortest physical distance has absolute minimal length
    assert dist_r.independent_euclidean_length_km <= const_r.independent_euclidean_length_km + 0.1
    assert dist_r.independent_euclidean_length_km < env_r.independent_euclidean_length_km

    # Environmental detour around sensitive habitat adds distance (> 4 km detour)
    detour_km = env_r.independent_euclidean_length_km - dist_r.independent_euclidean_length_km
    assert detour_km > 3.0, f"Environmental detour ({detour_km:.2f}km) expected to be >3.0km"


# ------------------------------------------------------------------------------
# 2. Failure Case & Negative Testing
# ------------------------------------------------------------------------------

def test_failure_case_out_of_bounds_endpoints(regional_router):
    """Tests that coordinates outside the regional corridor bounding box raise EndpointValidationError."""
    # Point located far east outside UTM Zone 43N corridor
    out_of_bounds_point = (82.5, 30.0)

    with pytest.raises(EndpointValidationError) as exc_info:
        regional_router.resolve_endpoints(
            source_wgs84=out_of_bounds_point,
            target_wgs84=(77.2195, 28.6430),
        )
    assert "out of bounds" in str(exc_info.value).lower()


def test_failure_case_infeasible_endpoint_in_statutory_park(regional_router):
    """Tests that placing an endpoint deep inside a statutory National Park raises InfeasibleRouteError."""
    # Coordinates inside Kalesar National Park (impassable hard exclusion mask = 1)
    # UTM approx (735000, 3350000) -> WGS84 approx (77.58, 30.36)
    kalesar_np_wgs84 = (77.58, 30.36)

    # Coarse routing should either fail or throw InfeasibleRouteError
    with pytest.raises(InfeasibleRouteError):
        src_xy, _ = regional_router.resolve_endpoints()
        # Transform Kalesar point
        tgt_x, tgt_y = regional_router.profiler.to_utm.transform(kalesar_np_wgs84[0], kalesar_np_wgs84[1])
        regional_router.find_coarse_overview_route(
            objective=RoutingObjective.SHORTEST_DISTANCE,
            source_xy=src_xy,
            target_xy=(tgt_x, tgt_y),
            search_space_buffer_m=5000.0,
        )


def test_failure_case_missing_raster_directory():
    """Tests that an invalid or missing cost surface directory raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        HierarchicalRegionalRouter(
            cost_dir="data/non_existent_cost_dir",
            output_dir="data/test_out/fail",
        )


# ------------------------------------------------------------------------------
# 3. Governance, Engineering Limitations, & Performance Budgets
# ------------------------------------------------------------------------------

def test_railway_engineering_limitations_audit(route_validator):
    """Verifies that engineering limitations are formally disclosed in validation results."""
    geojson_path = Path("data/routes/regional/candidate_corridors.geojson")
    summary = route_validator.validate_all_routes(geojson_path)

    lims = " ".join(summary.engineering_limitations).lower()

    # Must mention gradient compliance
    assert "gradient" in lims
    # Must mention horizontal curve radius
    assert "curve" in lims or "radius" in lims
    # Must mention bridges and river crossings
    assert "bridge" in lims or "river" in lims
    # Must mention tunnels and geotechnics
    assert "tunnel" in lims
    # Must mention statutory environmental clearances
    assert "statutory" in lims or "clearance" in lims or "forest" in lims


def test_phase_f_performance_and_memory_benchmarks(regional_router):
    """Measures runtime and peak RAM for regional routing to ensure budget compliance."""
    tracemalloc.start()
    t0 = time.time()

    res = regional_router.route_objective(RoutingObjective.SHORTEST_DISTANCE)
    elapsed = time.time() - t0

    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem / (1024 * 1024)

    # Runtime for single objective coarse-to-fine search must be < 15 seconds
    assert elapsed < 15.0, f"Routing runtime ({elapsed:.2f}s) exceeded 15s budget"
    # Peak memory must remain well under 500 MB budget
    assert peak_mb < 500.0, f"Peak memory ({peak_mb:.1f} MB) exceeded 500 MB budget"

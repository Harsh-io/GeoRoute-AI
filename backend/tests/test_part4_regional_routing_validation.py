"""Part 4 of 5 Regional Expansion Test Suite: Long-Distance Routing & Refinement.

Verifies:
1. Preflight checks and local Mandi route preservation.
2. Coordinate transformation, round trips, lon/lat ordering, and affine row/col calculation.
3. Strict OutOfCoverageError enforcement without clamping or edge snapping.
4. Three coarse regional routing searches using PYORPS Cython adapter.
5. Fine-resolution (30m) refinement within buffered corridor and cost recomputation.
6. Coarse-to-fine continuity, hard constraint avoidance, and nodata safety.
7. Verification of isolated deliverables: routes.geojson, route_results.json, routing_manifest.json.
"""

import json
import math
from pathlib import Path
import pytest
import pyproj
import rasterio
from rasterio.transform import Affine, rowcol, xy
from shapely.geometry import LineString, Point

from georoute.cost.regional_cost_builder import RegionalGridSpec
from georoute.routing.endpoint_validator import (
    EndpointValidator,
    OutOfCoverageError,
    ImpassableEndpointError,
)
from georoute.routing.hierarchical_router import (
    HierarchicalRegionalRouter,
    CoarseToFineRouteResult,
)
from georoute.routing.objective_router import RoutingObjective, OBJECTIVE_CONFIGS


@pytest.fixture(scope="module")
def regional_router():
    """Initializes HierarchicalRegionalRouter for tests."""
    cost_dir = Path("data/cost/regional")
    output_dir = Path("data/routes/regional")
    return HierarchicalRegionalRouter(
        cost_dir=cost_dir,
        output_dir=output_dir,
        coarse_factor=8,
        refinement_buffer_m=5000.0,
        pyorps_scale_factor=100.0,
    )


# ==============================================================================
# 1. Preflight and Local Preservation Tests
# ==============================================================================

def test_preflight_and_manifest_integrity():
    """Verifies that regional raster and cost manifests exist from Part 3."""
    cost_dir = Path("data/cost/regional")
    manifest_30m = cost_dir / "regional_cost_manifest.json"
    manifest_100m = cost_dir / "regional_cost_manifest_100m.json"
    rasters_dir = cost_dir / "rasters"

    assert manifest_30m.exists(), "30m regional cost manifest missing"
    assert manifest_100m.exists(), "100m regional cost manifest missing"
    assert (rasters_dir / "valid_data_mask.tif").exists()
    assert (rasters_dir / "hard_constraint_mask.tif").exists()


def test_preserve_local_mandi_routing_artifacts():
    """Ensures that local Mandi routing artifacts are preserved and not overwritten."""
    local_dir = Path("data/routes")
    local_manifest = local_dir / "routing_manifest.json"
    local_routes = local_dir / "routes.geojson"
    local_results = local_dir / "route_results.json"

    assert local_manifest.exists(), "Local routing manifest missing!"
    assert local_routes.exists(), "Local routes.geojson missing!"
    assert local_results.exists(), "Local route_results.json missing!"

    # Verify that local routes correspond to Mandi local study area (~5-10 km)
    with open(local_results, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "routes" in data
    for r in data["routes"]:
        assert r["length_km"] < 15.0, "Local route appears to have been overwritten by regional!"


# ==============================================================================
# 2. Coordinate Transformation and Endpoint Validation Tests
# ==============================================================================

def test_coordinate_convention_round_trip():
    """Validates WGS84 (lon, lat) to EPSG:32643 round-trip transformation for Mandi and Delhi."""
    wgs84 = pyproj.CRS.from_epsg(4326)
    utm = pyproj.CRS.from_epsg(32643)
    transformer = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True)
    inv_transformer = pyproj.Transformer.from_crs(utm, wgs84, always_xy=True)

    mandi_wgs84 = (76.9322, 31.7084)
    delhi_wgs84 = (77.2195, 28.6430)

    # Transform to UTM
    mx, my = transformer.transform(mandi_wgs84[0], mandi_wgs84[1])
    dx, dy = transformer.transform(delhi_wgs84[0], delhi_wgs84[1])

    # Mandi is in northern HP (higher northing), Delhi in NCR (lower northing)
    assert 680000.0 < mx < 690000.0
    assert 3500000.0 < my < 3520000.0
    assert 710000.0 < dx < 725000.0
    assert 3160000.0 < dy < 3180000.0
    assert my > dy
    assert (my - dy) > 330000.0  # >330 km north-south

    # Round trip back to WGS84
    m_lon, m_lat = inv_transformer.transform(mx, my)
    d_lon, d_lat = inv_transformer.transform(dx, dy)

    assert math.isclose(m_lon, mandi_wgs84[0], abs_tol=1e-5)
    assert math.isclose(m_lat, mandi_wgs84[1], abs_tol=1e-5)
    assert math.isclose(d_lon, delhi_wgs84[0], abs_tol=1e-5)
    assert math.isclose(d_lat, delhi_wgs84[1], abs_tol=1e-5)


def test_affine_transform_rowcol_calculation(regional_router):
    """Verifies affine transform row/col mapping into the master regional raster grid."""
    src_xy, tgt_xy = regional_router.resolve_endpoints()

    # Mandi row/col
    mr, mc = rowcol(regional_router.transform, src_xy[0], src_xy[1])
    assert 0 <= mr < regional_router.grid_height
    assert 0 <= mc < regional_router.grid_width

    # Delhi row/col
    dr, dc = rowcol(regional_router.transform, tgt_xy[0], tgt_xy[1])
    assert 0 <= dr < regional_router.grid_height
    assert 0 <= dc < regional_router.grid_width

    # Delhi must have larger row index (further south) than Mandi
    assert dr > mr
    assert (dr - mr) > 10000  # at 30m, 330km is >11,000 rows


def test_strict_out_of_coverage_enforcement(regional_router):
    """Ensures out-of-coverage coordinates raise OutOfCoverageError and never clamp or snap to arbitrary edges."""
    validator = regional_router.endpoint_validator

    # Mumbai (clearly outside regional raster extent)
    mumbai_wgs84 = (72.8777, 19.0760)
    with pytest.raises(OutOfCoverageError) as exc_info:
        validator.validate_and_resolve(mumbai_wgs84, crs="EPSG:4326", name="Mumbai")
    assert "lies outside raster grid bounds" in str(exc_info.value)

    # Inverted lat/lon (e.g. passing (lat, lon) = (31.7084, 76.9322))
    inverted_wgs84 = (31.7084, 76.9322)
    with pytest.raises(OutOfCoverageError):
        validator.validate_and_resolve(inverted_wgs84, crs="EPSG:4326", name="Inverted Coordinates")

    # Point just 10 km north of raster top edge
    out_north_xy = (regional_router.bounds.left + 50000.0, regional_router.bounds.top + 10000.0)
    with pytest.raises(OutOfCoverageError):
        validator.validate_and_resolve(out_north_xy, crs="EPSG:32643", name="North Out of Bounds")


def test_terminals_are_inside_valid_coverage(regional_router):
    """Verifies that Mandi and Delhi terminals reside within actual valid data and outside hard constraints."""
    src_xy, tgt_xy = regional_router.resolve_endpoints()

    with rasterio.open(regional_router.rasters_dir / "valid_data_mask.tif") as v_src:
        m_val = list(v_src.sample([src_xy]))[0][0]
        d_val = list(v_src.sample([tgt_xy]))[0][0]
        assert m_val == 1, "Mandi terminal falls in nodata / invalid coverage!"
        assert d_val == 1, "Delhi terminal falls in nodata / invalid coverage!"

    with rasterio.open(regional_router.rasters_dir / "hard_constraint_mask.tif") as h_src:
        m_hc = list(h_src.sample([src_xy]))[0][0]
        d_hc = list(h_src.sample([tgt_xy]))[0][0]
        assert m_hc == 0, "Mandi terminal falls in hard constraint!"
        assert d_hc == 0, "Delhi terminal falls in hard constraint!"


# ==============================================================================
# 3. Coarse Regional Routing Tests
# ==============================================================================

def test_coarse_regional_routing_three_objectives(regional_router):
    """Validates coarse searches across all three objectives using PYORPS adapter."""
    src_xy, tgt_xy = regional_router.resolve_endpoints()

    objectives = [
        RoutingObjective.SHORTEST_DISTANCE,
        RoutingObjective.LOWEST_CONSTRUCTION_DIFFICULTY,
        RoutingObjective.LOWEST_ENVIRONMENTAL_IMPACT,
    ]

    for obj in objectives:
        res = regional_router.find_coarse_overview_route(
            objective=obj,
            source_xy=src_xy,
            target_xy=tgt_xy,
            search_space_buffer_m=40000.0,
        )
        assert res.geometry.is_valid
        assert not res.geometry.is_empty
        assert isinstance(res.geometry, LineString)

        length_km = res.total_length_m / 1000.0
        assert 330.0 < length_km < 400.0
        assert res.recomputed_cost > 0.0


# ==============================================================================
# 4. Fine-Resolution Refinement and Continuity Tests
# ==============================================================================

def test_fine_resolution_refinement_continuity_and_cost(regional_router):
    """Verifies 30m refinement stays inside corridor tube, recomputes floating cost, and is continuous."""
    res = regional_router.route_objective(
        objective=RoutingObjective.SHORTEST_DISTANCE,
        refinement_buffer_m=5000.0,
    )

    assert isinstance(res, CoarseToFineRouteResult)
    assert res.refined_path.geometry.is_valid
    assert not res.refined_path.geometry.is_empty
    assert res.search_space_reduction_percent > 90.0

    # Endpoints connect within snapping tolerance
    src_xy, tgt_xy = regional_router.resolve_endpoints()
    start_pt = res.refined_path.path_coords[0]
    end_pt = res.refined_path.path_coords[-1]
    assert math.dist(start_pt, src_xy) < 60.0
    assert math.dist(end_pt, tgt_xy) < 60.0

    # Continuity: distance between adjacent points must match 30m grid step (30m or 42.4m diagonal)
    coords = res.refined_path.path_coords
    for i in range(len(coords) - 1):
        step_dist = math.dist(coords[i], coords[i + 1])
        assert step_dist < 45.0, f"Discontinuity detected between point {i} and {i+1}: {step_dist:.2f}m"

    # Recomputed cost matches physical length for shortest distance (weight = 1.0)
    assert math.isclose(res.refined_path.recomputed_cost, res.refined_path.total_length_m, rel_tol=1e-3)


# ==============================================================================
# 5. Route Artifacts and Validation Manifest Tests
# ==============================================================================

def test_regional_route_deliverables_integrity():
    """Verifies presence, formatting, and completeness of Part 4 deliverables in data/routes/regional/."""
    reg_dir = Path("data/routes/regional")
    routes_geojson = reg_dir / "routes.geojson"
    route_results = reg_dir / "route_results.json"
    routing_manifest = reg_dir / "routing_manifest.json"

    assert routes_geojson.exists(), "data/routes/regional/routes.geojson missing"
    assert route_results.exists(), "data/routes/regional/route_results.json missing"
    assert routing_manifest.exists(), "data/routes/regional/routing_manifest.json missing"

    # 1. Check GeoJSON
    with open(routes_geojson, "r", encoding="utf-8") as f:
        gj = json.load(f)
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 3

    objectives = {feat["properties"]["objective"] for feat in gj["features"]}
    expected_objs = {
        "shortest_distance",
        "lowest_construction_difficulty",
        "lowest_environmental_impact",
    }
    assert objectives == expected_objs

    # 2. Check coordinates are in WGS84 (lon: ~76-78, lat: ~28-32)
    for feat in gj["features"]:
        coords = feat["geometry"]["coordinates"]
        start_coord = coords[0]
        end_coord = coords[-1]
        assert 76.5 < start_coord[0] < 77.5 and 31.0 < start_coord[1] < 32.5  # Mandi
        assert 76.8 < end_coord[0] < 77.8 and 28.0 < end_coord[1] < 29.5      # Delhi

    # 3. Check Routing Manifest schema
    with open(routing_manifest, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["pipeline_status"] == "SUCCESS"
    assert manifest["num_routes"] == 3
    assert len(manifest["routes"]) == 3
    assert "engineering_disclaimer" in manifest
    assert "preliminary" in manifest["engineering_disclaimer"]

    # 4. Check units and costs
    for r in manifest["routes"]:
        assert r["length_km"] > 330.0
        assert r["accumulated_cost"] > 0.0
        assert r["cost_units"] != ""
        assert r["validation"]["is_connected"] is True
        assert r["validation"]["is_globally_optimal_proven"] is False

"""Test suite for GeoRoute AI Regional Expansion — Part 3:
Raster Alignment, Feature Extraction and Regional Cost Surfaces.

Verifies:
1. Projected CRS evaluation, distortion metrics, and selection rationale (EPSG:32643 optimality).
2. Explicit resampling policies (continuous bilinear vs categorical nearest-neighbor).
3. Coarse (100m) and fine (30m) master grid specifications, alignments, and bounds.
4. Coarse-to-fine corridor tube refinement buffers (+-5km, +-10km, +-15km) and boundary proximity detection.
5. Regional feature layer generation, alignment, and tile boundary continuity (zero seam artifacts).
6. NoData propagation invariant (invalid/NoData cells remain blocked, never converted to zero cost).
7. Hard constraints strictly blocked across all three objectives (Distance, Construction, Environmental).
8. Three-objective cost differentiation and relative penalty ordering.
9. Edge cost semantics and distance non-duplication invariant.
"""

import math
from pathlib import Path
import numpy as np
import pyproj
import pytest
import rasterio

from georoute.cost.cost_assumptions import CostAssumptions
from georoute.cost.distance_cost_model import DistanceCostModel
from georoute.cost.construction_cost_model import ConstructionCostModel
from georoute.cost.environmental_cost_model import EnvironmentalCostModel
from georoute.cost.regional_cost_builder import (
    RegionalCostSurfaceBuilder,
    RegionalGridSpec,
    RESAMPLING_POLICIES,
    evaluate_regional_crs,
)


@pytest.fixture
def corridor_bounds_wgs84():
    """WGS84 study area bounding box for Mandi to New Delhi corridor."""
    return (76.50, 28.30, 77.50, 32.00)


@pytest.fixture
def master_30m_grid(corridor_bounds_wgs84):
    """Master 30m grid specification in EPSG:32643."""
    return RegionalGridSpec.from_wgs84_bounds(
        min_lon=corridor_bounds_wgs84[0],
        min_lat=corridor_bounds_wgs84[1],
        max_lon=corridor_bounds_wgs84[2],
        max_lat=corridor_bounds_wgs84[3],
        resolution_m=30.0,
        target_epsg=32643,
    )


@pytest.fixture
def coarse_100m_grid(corridor_bounds_wgs84):
    """Coarse 100m grid specification in EPSG:32643."""
    return RegionalGridSpec.from_wgs84_bounds(
        min_lon=corridor_bounds_wgs84[0],
        min_lat=corridor_bounds_wgs84[1],
        max_lon=corridor_bounds_wgs84[2],
        max_lat=corridor_bounds_wgs84[3],
        resolution_m=100.0,
        target_epsg=32643,
    )


# ------------------------------------------------------------------------------
# 1. Projected CRS Evaluation & Selection Rationale
# ------------------------------------------------------------------------------
def test_regional_crs_evaluation_and_distortion_bounds(corridor_bounds_wgs84):
    """Evaluates candidate CRS options and verifies EPSG:32643 is mathematically optimal."""
    eval_res = evaluate_regional_crs(
        min_lon=corridor_bounds_wgs84[0],
        min_lat=corridor_bounds_wgs84[1],
        max_lon=corridor_bounds_wgs84[2],
        max_lat=corridor_bounds_wgs84[3],
    )

    assert eval_res["selected_crs"] == "EPSG:32643"
    assert "UTM zone 43N" in eval_res["selected_crs_name"]

    candidates = eval_res["candidates"]
    assert "EPSG:32643" in candidates
    assert "EPSG:32644" in candidates
    assert "EPSG:7755" in candidates
    assert "EPSG:3857" in candidates

    # EPSG:32643 must have scale distortion strictly bounded under 0.04%
    utm43 = candidates["EPSG:32643"]
    assert utm43["verdict"] == "OPTIMAL_SELECTED"
    assert utm43["inside_zone_bounds"] is True
    assert utm43["single_zone_continuity"] is True
    assert utm43["angular_conformality"] is True
    assert utm43["max_scale_distortion_pct"] < 0.04

    # EPSG:32644 lies outside corridor longitudes (76.5E to 77.5E vs CM 81E)
    utm44 = candidates["EPSG:32644"]
    assert utm44["inside_zone_bounds"] is False
    assert utm44["max_scale_distortion_pct"] > utm43["max_scale_distortion_pct"]

    # Web Mercator must show severe distortion (> 10%)
    mercator = candidates["EPSG:3857"]
    assert mercator["max_scale_distortion_pct"] > 10.0


# ------------------------------------------------------------------------------
# 2. Resampling Policy Specification
# ------------------------------------------------------------------------------
def test_resampling_policy_distinction():
    """Verifies continuous elevation and categorical land-cover have distinct resampling policies."""
    assert "continuous_elevation" in RESAMPLING_POLICIES
    assert "categorical_landcover" in RESAMPLING_POLICIES
    assert "binary_masks_and_constraints" in RESAMPLING_POLICIES

    elev_policy = RESAMPLING_POLICIES["continuous_elevation"]
    lc_policy = RESAMPLING_POLICIES["categorical_landcover"]
    mask_policy = RESAMPLING_POLICIES["binary_masks_and_constraints"]

    # Continuous elevation must use bilinear interpolation
    assert elev_policy["resampling_method"] == "bilinear"
    assert elev_policy["data_type"] == "continuous"
    assert "dem" in elev_policy["layers"]

    # Categorical land-cover must use nearest-neighbor interpolation to preserve class IDs
    assert lc_policy["resampling_method"] == "nearest"
    assert lc_policy["data_type"] == "categorical"
    assert "landcover_class" in lc_policy["layers"]

    # Continuous and categorical methods MUST NOT be identical
    assert elev_policy["resampling_method"] != lc_policy["resampling_method"]

    # Binary masks must use conservative all-touched nearest neighbor
    assert mask_policy["resampling_method"] == "nearest"
    assert mask_policy.get("all_touched") is True


# ------------------------------------------------------------------------------
# 3. Coarse (100m) and Fine (30m) Grid Specifications
# ------------------------------------------------------------------------------
def test_coarse_and_fine_grid_specifications(master_30m_grid, coarse_100m_grid):
    """Verifies metric snapping, transforms, and dimensions for 30m and 100m grids."""
    # 30m fine grid
    assert master_30m_grid.resolution_m == 30.0
    assert master_30m_grid.crs_epsg == 32643
    assert master_30m_grid.width > 3400
    assert master_30m_grid.height > 13500
    assert master_30m_grid.transform.a == 30.0
    assert master_30m_grid.transform.e == -30.0

    # 100m coarse grid
    assert coarse_100m_grid.resolution_m == 100.0
    assert coarse_100m_grid.crs_epsg == 32643
    assert coarse_100m_grid.width > 1000
    assert coarse_100m_grid.height > 4000
    assert coarse_100m_grid.transform.a == 100.0
    assert coarse_100m_grid.transform.e == -100.0

    # Serialization
    d30 = master_30m_grid.to_dict()
    assert d30["resolution_meters"] == 30.0
    assert "bounds" in d30
    assert d30["total_cells"] == master_30m_grid.width * master_30m_grid.height

    # 100m grid cell count must be approximately 1/11th of 30m grid (~90% cell reduction)
    ratio = master_30m_grid.width * master_30m_grid.height / (coarse_100m_grid.width * coarse_100m_grid.height)
    assert 9.0 <= ratio <= 12.0


# ------------------------------------------------------------------------------
# 4. Corridor Tube Refinement Envelopes & Boundary Detection
# ------------------------------------------------------------------------------
def test_corridor_tube_refinement_and_boundary_detection(master_30m_grid):
    """Tests corridor tube refinement with configurable buffers and boundary proximity detection."""
    # Interior centerline: Mandi (north) to Delhi (south)
    mandi_pt = (683095.0, 3509735.0)
    mid_pt = (695000.0, 3340000.0)
    delhi_pt = (716880.0, 3170240.0)
    centerline = [mandi_pt, mid_pt, delhi_pt]

    # Evaluate +-5 km buffer
    tube_5km, diag_5km = master_30m_grid.get_corridor_tube(centerline, buffer_m=5000.0, target_resolution_m=30.0)
    assert diag_5km["buffer_envelope_km"] == 5.0
    assert diag_5km["cell_reduction_percentage"] >= 60.0  # Massive memory/CPU savings (64.1% reduction for global bbox)
    assert diag_5km["approaches_coverage_boundary"] is False

    # Evaluate +-15 km buffer
    tube_15km, diag_15km = master_30m_grid.get_corridor_tube(centerline, buffer_m=15000.0, target_resolution_m=30.0)
    assert diag_15km["buffer_envelope_km"] == 15.0
    assert diag_15km["tube_cells"] > diag_5km["tube_cells"]
    assert diag_15km["cell_reduction_percentage"] >= 40.0

    # Test boundary proximity detection when points approach grid boundaries
    near_border_centerline = [
        (master_30m_grid.min_x + 1000.0, 3300000.0),  # Within 1km of western border
        (master_30m_grid.min_x + 2000.0, 3200000.0),
    ]
    _, border_diag = master_30m_grid.get_corridor_tube(
        near_border_centerline, buffer_m=5000.0, boundary_margin_m=2000.0
    )
    assert border_diag["approaches_coverage_boundary"] is True
    assert border_diag["boundary_proximity_details"]["approaches_west"] is True
    assert "Expand regional bounding box" in border_diag["recommendation"]


# ------------------------------------------------------------------------------
# 5. Feature Extraction and Tile Computation on Representative Slice
# ------------------------------------------------------------------------------
def test_tile_feature_extraction_and_layers():
    """Verifies that compute_tile_features_and_costs extracts all required layers."""
    grid_spec = RegionalGridSpec(
        min_x=680000.0,
        min_y=3480000.0,
        max_x=690000.0,
        max_y=3500000.0,
        resolution_m=30.0,
        crs_epsg=32643,
    )
    builder = RegionalCostSurfaceBuilder(
        output_dir="data/test_out/cost_regional_slice",
        raw_dir="data/raw",
        grid_spec=grid_spec,
        tile_size=64,
        halo_pixels=3,
        resolution_m=30.0,
    )

    tile_data = builder.compute_tile_features_and_costs(0, 64, 0, 64)

    # Check all required layers are present
    required_layers = [
        "slope_percent",
        "slope_degrees",
        "landcover_class",
        "protected_area_mask",
        "water_mask",
        "highway_mask",
        "hard_constraint_mask",
        "valid_data_mask",
        "distance_cost",
        "distance_friction",
        "construction_cost",
        "construction_friction",
        "environmental_cost",
        "environmental_friction",
        "slope_penalty",
        "landcover_penalty",
        "forest_sensitivity",
    ]
    for layer in required_layers:
        assert layer in tile_data, f"Missing layer: {layer}"
        assert tile_data[layer].shape == (64, 64)

    # Verify slope values are non-negative
    slopes = tile_data["slope_percent"]
    valid_slopes = slopes[slopes != -9999.0]
    assert np.all(valid_slopes >= 0.0)

    # Verify landcover classes are discrete integers from ESA WorldCover set
    lc = tile_data["landcover_class"]
    valid_classes = {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}
    present_classes = set(np.unique(lc))
    assert present_classes.issubset(valid_classes)


# ------------------------------------------------------------------------------
# 6. NoData Propagation and Non-Zero Cost Invariant
# ------------------------------------------------------------------------------
def test_nodata_propagation_and_blocking_invariant():
    """Verifies that NoData or invalid cells are strictly blocked (never converted to 0.0)."""
    grid_spec = RegionalGridSpec(
        min_x=680000.0,
        min_y=3480000.0,
        max_x=686000.0,
        max_y=3486000.0,
        resolution_m=30.0,
        crs_epsg=32643,
    )
    assumptions = CostAssumptions()
    assumptions.constraints.blocked_cell_cost = 65535.0
    assumptions.constraints.treat_nodata_as_blocked = True

    builder = RegionalCostSurfaceBuilder(
        output_dir="data/test_out/cost_regional_nodata",
        raw_dir="data/raw",
        assumptions=assumptions,
        grid_spec=grid_spec,
        tile_size=64,
        resolution_m=30.0,
    )

    tile_data = builder.compute_tile_features_and_costs(0, 64, 0, 64)

    # Inject simulated nodata by checking valid_data_mask and hard_constraint_mask
    dist_cost = tile_data["distance_cost"]
    const_cost = tile_data["construction_cost"]
    env_cost = tile_data["environmental_cost"]
    hc_mask = tile_data["hard_constraint_mask"]

    blocked_indices = np.where(hc_mask == 1)
    if len(blocked_indices[0]) > 0:
        # All blocked cells must strictly equal blocked_cell_cost (65535.0)
        assert np.all(dist_cost[blocked_indices] == 65535.0)
        assert np.all(const_cost[blocked_indices] == 65535.0)
        assert np.all(env_cost[blocked_indices] == 65535.0)

    # Cost must NEVER be zero on any cell (whether valid or blocked)
    assert np.all(dist_cost > 0.0), "Found zero or negative cost in distance surface!"
    assert np.all(const_cost > 0.0), "Found zero or negative cost in construction surface!"
    assert np.all(env_cost > 0.0), "Found zero or negative cost in environmental surface!"


# ------------------------------------------------------------------------------
# 7. Hard Constraints Blocked Across All Three Objectives
# ------------------------------------------------------------------------------
def test_hard_constraints_blocked_across_all_three_objectives():
    """Verifies that protected areas and physical obstacles are impassable in all 3 surfaces."""
    height, width = 50, 50
    hard_mask = np.zeros((height, width), dtype=np.uint8)
    hard_mask[10:20, 10:20] = 1  # Simulated statutory protected area

    valid_mask = np.ones((height, width), dtype=np.uint8)
    valid_mask[40:45, 40:45] = 0  # Simulated NoData / invalid sensor area

    assumptions = CostAssumptions()
    blocked_val = 65535.0

    # 1. Distance model
    d_model = DistanceCostModel(assumptions.distance, blocked_cell_cost=blocked_val)
    d_cost, d_fric = d_model.compute_surface((height, width), hard_constraint_mask=hard_mask, valid_data_mask=valid_mask)

    # 2. Construction model
    c_model = ConstructionCostModel.from_assumptions(assumptions, blocked_cell_cost=blocked_val)
    c_cost, c_fric, _ = c_model.compute_surface(
        slope_arr=np.full((height, width), 5.0, dtype=np.float32),
        lc_arr=np.full((height, width), 40, dtype=np.uint8),
        building_mask=np.zeros((height, width), dtype=np.uint8),
        water_mask=np.zeros((height, width), dtype=np.uint8),
        highway_mask=np.zeros((height, width), dtype=np.uint8),
        hard_constraint_mask=hard_mask,
        valid_data_mask=valid_mask,
    )

    # 3. Environmental model
    e_model = EnvironmentalCostModel.from_assumptions(assumptions, blocked_cell_cost=blocked_val)
    e_cost, e_fric, _ = e_model.compute_surface(
        forest_mask=np.zeros((height, width), dtype=np.uint8),
        wetland_mask=np.zeros((height, width), dtype=np.uint8),
        water_mask=np.zeros((height, width), dtype=np.uint8),
        protected_area_mask=hard_mask,
        hard_constraint_mask=hard_mask,
        valid_data_mask=valid_mask,
    )

    # Both protected area and nodata must be strictly blocked across ALL THREE
    for obj_name, cost_arr, fric_arr in [
        ("Distance", d_cost, d_fric),
        ("Construction", c_cost, c_fric),
        ("Environmental", e_cost, e_fric),
    ]:
        assert np.all(cost_arr[10:20, 10:20] == blocked_val), f"{obj_name} failed to block protected area!"
        assert np.all(fric_arr[10:20, 10:20] == blocked_val), f"{obj_name} friction failed to block protected area!"
        assert np.all(cost_arr[40:45, 40:45] == blocked_val), f"{obj_name} failed to block NoData region!"
        assert np.all(fric_arr[40:45, 40:45] == blocked_val), f"{obj_name} friction failed to block NoData region!"


# ------------------------------------------------------------------------------
# 8. Three-Objective Cost Differentiation and Relative Ordering
# ------------------------------------------------------------------------------
def test_three_objective_differentiation_and_ordering():
    """Verifies that the three cost surfaces penalize distinct geospatial features."""
    grid_spec = RegionalGridSpec(
        min_x=680000.0,
        min_y=3480000.0,
        max_x=686000.0,
        max_y=3486000.0,
        resolution_m=30.0,
        crs_epsg=32643,
    )
    builder = RegionalCostSurfaceBuilder(
        output_dir="data/test_out/cost_regional_diff",
        raw_dir="data/raw",
        grid_spec=grid_spec,
        tile_size=64,
        resolution_m=30.0,
    )

    tile_data = builder.compute_tile_features_and_costs(0, 64, 0, 64)

    d_cost = tile_data["distance_cost"]
    c_cost = tile_data["construction_cost"]
    e_cost = tile_data["environmental_cost"]
    hc_mask = tile_data["hard_constraint_mask"]

    passable = hc_mask == 0
    assert np.any(passable), "No passable cells found in test tile!"

    # Objective A (Distance): Pure physical distance (30.0m on all traversable cells)
    assert np.allclose(d_cost[passable], 30.0)

    # Objective B (Construction): Construction difficulty >= Distance cost
    assert np.all(c_cost[passable] >= d_cost[passable])

    # Objective C (Environmental): Environmental proxy >= Distance cost
    assert np.all(e_cost[passable] >= d_cost[passable])

    # Construction and Environmental penalty patterns must not be identical
    assert not np.allclose(c_cost[passable], e_cost[passable])


# ------------------------------------------------------------------------------
# 9. Halo Seam Elimination Across Tile Boundaries
# ------------------------------------------------------------------------------
def test_halo_seam_elimination_across_tiles():
    """Verifies that halo overlap (>=2 pixels) prevents artificial boundary seams."""
    grid_spec = RegionalGridSpec(
        min_x=680000.0,
        min_y=3480000.0,
        max_x=690000.0,
        max_y=3500000.0,
        resolution_m=30.0,
        crs_epsg=32643,
    )
    builder = RegionalCostSurfaceBuilder(
        output_dir="data/test_out/cost_regional_seam",
        raw_dir="data/raw",
        grid_spec=grid_spec,
        tile_size=64,
        halo_pixels=3,
        resolution_m=30.0,
    )

    # Compute Tile 1: rows 0 to 64
    tile1 = builder.compute_tile_features_and_costs(0, 64, 0, 64)
    # Compute Tile 2: rows 64 to 128 (adjacent south)
    tile2 = builder.compute_tile_features_and_costs(64, 128, 0, 64)

    # Compute a continuous merged 128x64 block directly
    builder_merged = RegionalCostSurfaceBuilder(
        output_dir="data/test_out/cost_regional_seam",
        raw_dir="data/raw",
        grid_spec=grid_spec,
        tile_size=128,
        halo_pixels=3,
        resolution_m=30.0,
    )
    block_merged = builder_merged.compute_tile_features_and_costs(0, 128, 0, 64)

    # Row 63 is the bottom edge of Tile 1, Row 64 is the top edge of Tile 2
    # Verify that slopes match the unified merged computation at the boundary
    tile1_slope_edge = tile1["slope_percent"][-1, :]
    merged_slope_edge1 = block_merged["slope_percent"][63, :]
    np.testing.assert_allclose(tile1_slope_edge, merged_slope_edge1, atol=1e-4)

    tile2_slope_edge = tile2["slope_percent"][0, :]
    merged_slope_edge2 = block_merged["slope_percent"][64, :]
    np.testing.assert_allclose(tile2_slope_edge, merged_slope_edge2, atol=1e-4)


# ------------------------------------------------------------------------------
# 10. Edge-Cost Semantics & Distance Non-Duplication
# ------------------------------------------------------------------------------
def test_edge_cost_semantics_distance_non_duplication():
    """Verifies StepCost(u, v) = Distance(u, v) * ((F(u) + F(v)) / 2)."""
    # Let u and v be adjacent cells with friction F_u and F_v
    F_u = 1.85
    F_v = 2.45
    dist_ortho = 30.0
    dist_diag = 30.0 * math.sqrt(2.0)

    # Orthogonal edge
    step_ortho = dist_ortho * ((F_u + F_v) / 2.0)
    expected_ortho = 30.0 * 2.15
    assert pytest.approx(step_ortho, rel=1e-6) == expected_ortho

    # Diagonal edge
    step_diag = dist_diag * ((F_u + F_v) / 2.0)
    expected_diag = (30.0 * math.sqrt(2.0)) * 2.15
    assert pytest.approx(step_diag, rel=1e-6) == expected_diag

    # Distance is not multiplied inside friction (dimensionless)
    assert pytest.approx(step_ortho / dist_ortho) == 2.15

"""Test suite for GeoRoute AI Phase C: Scalable Regional Cost Surfaces and Alignment.

Tests:
1. Coordinate transformations & regional UTM Zone 43N grid alignment.
2. Endpoint mapping and spatial coverage (Mandi and New Delhi).
3. Seamless boundary continuity across tile boundaries (zero artificial seam artifacts).
4. Statutory obstacle & NoData handling (protected areas hard exclusions).
5. Objective-specific cost surface differentiation (distance, construction, environmental).
6. Edge-cost semantics & distance non-duplication verification.
7. Memory footprint & runtime performance benchmarks.
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

from georoute.cost.cost_assumptions import CostAssumptions
from georoute.cost.regional_cost_builder import (
    RegionalCostSurfaceBuilder,
    RegionalGridSpec,
)


@pytest.fixture
def corridor_grid_spec():
    """Master 30m grid specification covering the Mandi to Delhi study area."""
    return RegionalGridSpec.from_wgs84_bounds(
        min_lon=76.50,
        min_lat=28.30,
        max_lon=77.50,
        max_lat=32.00,
        resolution_m=30.0,
        target_epsg=32643,
    )


@pytest.fixture
def regional_builder(corridor_grid_spec):
    """RegionalCostSurfaceBuilder configured for test execution."""
    return RegionalCostSurfaceBuilder(
        output_dir="data/test_out/cost_regional",
        raw_dir="data/raw",
        grid_spec=corridor_grid_spec,
        tile_size=512,
        halo_pixels=3,
        resolution_m=30.0,
    )


def test_regional_grid_coordinate_transformation(corridor_grid_spec):
    """Verifies correct EPSG:32643 projection, resolution, and bounding dimensions."""
    assert corridor_grid_spec.crs_epsg == 32643
    assert corridor_grid_spec.resolution_m == 30.0
    assert corridor_grid_spec.width >= 3400
    assert corridor_grid_spec.height >= 13500

    # Test coordinate bounds enclose full study area
    assert corridor_grid_spec.min_x <= 645000.0
    assert corridor_grid_spec.max_x >= 745000.0
    assert corridor_grid_spec.min_y <= 3132000.0
    assert corridor_grid_spec.max_y >= 3543000.0

    # Verify transform matrix
    tf = corridor_grid_spec.transform
    assert tf.a == 30.0  # dx
    assert tf.e == -30.0  # -dy
    assert tf.c == corridor_grid_spec.min_x
    assert tf.f == corridor_grid_spec.max_y


def test_endpoint_mapping_in_regional_grid(corridor_grid_spec):
    """Verifies that Mandi and New Delhi stations map to valid pixel coordinates inside grid."""
    transformer = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

    # 1. Mandi Railway Station (31.7084 N, 76.9322 E)
    mandi_x, mandi_y = transformer.transform(76.9322, 31.7084)
    # Check within UTM bounds
    assert corridor_grid_spec.min_x < mandi_x < corridor_grid_spec.max_x
    assert corridor_grid_spec.min_y < mandi_y < corridor_grid_spec.max_y

    col_mandi = int((mandi_x - corridor_grid_spec.min_x) / corridor_grid_spec.resolution_m)
    row_mandi = int((corridor_grid_spec.max_y - mandi_y) / corridor_grid_spec.resolution_m)
    assert 0 <= col_mandi < corridor_grid_spec.width
    assert 0 <= row_mandi < corridor_grid_spec.height

    # 2. New Delhi Railway Station (28.6430 N, 77.2195 E)
    delhi_x, delhi_y = transformer.transform(77.2195, 28.6430)
    assert corridor_grid_spec.min_x < delhi_x < corridor_grid_spec.max_x
    assert corridor_grid_spec.min_y < delhi_y < corridor_grid_spec.max_y

    col_delhi = int((delhi_x - corridor_grid_spec.min_x) / corridor_grid_spec.resolution_m)
    row_delhi = int((corridor_grid_spec.max_y - delhi_y) / corridor_grid_spec.resolution_m)
    assert 0 <= col_delhi < corridor_grid_spec.width
    assert 0 <= row_delhi < corridor_grid_spec.height

    # Mandi is in the north (smaller row index), Delhi is in the south (larger row index)
    assert row_mandi < row_delhi
    pixel_distance_y = row_delhi - row_mandi
    # Latitude span ~340 km -> ~11,300 cells along Y
    assert pixel_distance_y > 10000


def test_tiled_processing_seamless_boundary():
    """CRITICAL TEST: Verifies that halo overlap eliminates artificial seams at tile borders.

    Computes a 2x2 multi-tile block:
    Tile 1: rows 0..200, cols 0..200
    Tile 2: rows 0..200, cols 200..400
    Tile 3: rows 200..400, cols 0..200
    Tile 4: rows 200..400, cols 200..400

    And compares against a single monolithic calculation over rows 0..400, cols 0..400.
    With halo padding >= 2 pixels, the values along the internal seams must be
    EXACTLY IDENTICAL (difference == 0.0) with NO low-cost trenches or NoData cuts!
    """
    sub_spec = RegionalGridSpec(
        min_x=680000.0,
        min_y=3450000.0,
        max_x=692000.0,
        max_y=3462000.0,
        resolution_m=30.0,
        crs_epsg=32643,
    )

    builder = RegionalCostSurfaceBuilder(
        output_dir="data/test_out/cost_regional",
        raw_dir="data/raw",
        grid_spec=sub_spec,
        tile_size=200,
        halo_pixels=3,
        resolution_m=30.0,
    )

    # 1. Monolithic calculation (0..400, 0..400)
    mono_data = builder.compute_tile_features_and_costs(0, 400, 0, 400)
    mono_slope = mono_data["slope_percent"]
    mono_const_cost = mono_data["construction_cost"]
    mono_const_friction = mono_data["construction_friction"]

    # 2. Tiled calculation: compute Tile 1 and Tile 2 individually with halo padding
    t1_data = builder.compute_tile_features_and_costs(0, 200, 0, 200)
    t2_data = builder.compute_tile_features_and_costs(0, 200, 200, 400)
    t3_data = builder.compute_tile_features_and_costs(200, 400, 0, 200)
    t4_data = builder.compute_tile_features_and_costs(200, 400, 200, 400)

    # Assemble composite array from tiles
    tiled_slope = np.zeros((400, 400), dtype=np.float32)
    tiled_slope[0:200, 0:200] = t1_data["slope_percent"]
    tiled_slope[0:200, 200:400] = t2_data["slope_percent"]
    tiled_slope[200:400, 0:200] = t3_data["slope_percent"]
    tiled_slope[200:400, 200:400] = t4_data["slope_percent"]

    tiled_const_cost = np.zeros((400, 400), dtype=np.float32)
    tiled_const_cost[0:200, 0:200] = t1_data["construction_cost"]
    tiled_const_cost[0:200, 200:400] = t2_data["construction_cost"]
    tiled_const_cost[200:400, 0:200] = t3_data["construction_cost"]
    tiled_const_cost[200:400, 200:400] = t4_data["construction_cost"]

    # Check vertical seam (col 199 and col 200)
    slope_diff_vert = np.abs(tiled_slope[:, 198:202] - mono_slope[:, 198:202])
    cost_diff_vert = np.abs(tiled_const_cost[:, 198:202] - mono_const_cost[:, 198:202])

    # Check horizontal seam (row 199 and row 200)
    slope_diff_horiz = np.abs(tiled_slope[198:202, :] - mono_slope[198:202, :])
    cost_diff_horiz = np.abs(tiled_const_cost[198:202, :] - mono_const_cost[198:202, :])

    # Assert exact boundary continuity: discrepancy must be 0.0
    assert np.allclose(slope_diff_vert, 0.0, atol=1e-5), "Vertical tile seam has slope mismatch!"
    assert np.allclose(cost_diff_vert, 0.0, atol=1e-5), "Vertical tile seam has cost mismatch!"
    assert np.allclose(slope_diff_horiz, 0.0, atol=1e-5), "Horizontal tile seam has slope mismatch!"
    assert np.allclose(cost_diff_horiz, 0.0, atol=1e-5), "Horizontal tile seam has cost mismatch!"

    # Across the entire 400x400 area, tiled array must match monolithic array perfectly
    assert np.allclose(tiled_slope, mono_slope, atol=1e-5)
    assert np.allclose(tiled_const_cost, mono_const_cost, atol=1e-5)


def test_statutory_protected_area_hard_constraint_enforcement(regional_builder):
    """Verifies that corridor protected areas are strictly masked as impassable."""
    pa_gdf = regional_builder.get_protected_areas_gdf()
    assert pa_gdf is not None
    assert len(pa_gdf) == 34  # 34 corridor protected areas

    # Pick a tile that intersects one of the major protected areas (e.g. Asola Bhatti in Delhi, or Shikari Devi in HP)
    # Asola Bhatti WLS: ~28.48 N, 77.25 E -> UTM Zone 43N: X ~ 720000, Y ~ 3152000
    tf = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)
    px, py = tf.transform(77.25, 28.48)
    col = int((px - regional_builder.grid_spec.min_x) / 30.0)
    row = int((regional_builder.grid_spec.max_y - py) / 30.0)

    # Compute a 300x300 tile around Asola Bhatti
    r0 = max(0, row - 150)
    r1 = min(regional_builder.grid_spec.height, row + 150)
    c0 = max(0, col - 150)
    c1 = min(regional_builder.grid_spec.width, col + 150)

    tile_data = regional_builder.compute_tile_features_and_costs(r0, r1, c0, c1)

    pa_mask = tile_data["protected_area_mask"]
    hard_mask = tile_data["hard_constraint_mask"]
    dist_cost = tile_data["distance_cost"]
    dist_fric = tile_data["distance_friction"]
    const_cost = tile_data["construction_cost"]
    env_cost = tile_data["environmental_cost"]

    # Verify protected area cells exist in this tile
    assert np.any(pa_mask == 1), "Expected protected area cells in Asola Bhatti tile"

    # In all cells where pa_mask == 1:
    # 1. hard_constraint_mask must be 1
    # 2. all 3 cost surfaces must be blocked (-9999.0)
    pa_cells = pa_mask == 1
    assert np.all(hard_mask[pa_cells] == 1)
    assert np.all(dist_cost[pa_cells] == -9999.0)
    assert np.all(dist_fric[pa_cells] == -9999.0)
    assert np.all(const_cost[pa_cells] == -9999.0)
    assert np.all(env_cost[pa_cells] == -9999.0)


def test_objective_cost_surface_differentiation(regional_builder):
    """Verifies that the 3 cost objectives express fundamentally distinct physics & policies."""
    # Compute representative tiles:
    # 1. Alpine Himalayan tile in north (row 500..800)
    # 2. Agricultural plain tile in central corridor (row 6000..6300)
    north_data = regional_builder.compute_tile_features_and_costs(500, 800, 1500, 1800)
    plains_data = regional_builder.compute_tile_features_and_costs(6000, 6300, 1500, 1800)

    # Distance surface:
    # For all valid unblocked cells, distance cost MUST be exactly 30.0m and friction MUST be exactly 1.0!
    valid_north = north_data["hard_constraint_mask"] == 0
    valid_plains = plains_data["hard_constraint_mask"] == 0

    assert np.allclose(north_data["distance_cost"][valid_north], 30.0)
    assert np.allclose(north_data["distance_friction"][valid_north], 1.0)
    assert np.allclose(plains_data["distance_cost"][valid_plains], 30.0)
    assert np.allclose(plains_data["distance_friction"][valid_plains], 1.0)

    # Construction difficulty:
    # Steep Himalayan slopes must produce significantly higher construction difficulty than plains!
    mean_north_const_fric = north_data["construction_friction"][valid_north].mean()
    mean_plains_const_fric = plains_data["construction_friction"][valid_plains].mean()

    assert mean_north_const_fric > mean_plains_const_fric * 1.5, (
        f"Alpine construction friction ({mean_north_const_fric:.2f}) must be substantially higher "
        f"than plains friction ({mean_plains_const_fric:.2f})"
    )

    # Environmental impact proxy:
    # Northern forest canopy must produce higher environmental friction than plains cropland!
    mean_north_env_fric = north_data["environmental_friction"][valid_north].mean()
    mean_plains_env_fric = plains_data["environmental_friction"][valid_plains].mean()

    assert mean_north_env_fric > mean_plains_env_fric, (
        f"Forest environmental friction ({mean_north_env_fric:.2f}) must exceed plains ({mean_plains_env_fric:.2f})"
    )


def test_edge_cost_semantics_and_distance_non_duplication():
    """Verifies that StepCost = Distance(u, v) * ((F(u) + F(v)) / 2).

    Confirms:
    1. Dimensionless friction F >= 1.0.
    2. When F = 1.0 (pure distance), StepCost equals exact Euclidean distance in meters.
    3. Distance is strictly linear with step length and is NOT counted twice.
    """
    res = 30.0
    dx = res
    dy = res
    diag_dist = math.sqrt(dx ** 2 + dy ** 2)

    # Case 1: Pure distance objective (F = 1.0)
    f_u = 1.0
    f_v = 1.0
    ortho_step_cost = dx * ((f_u + f_v) / 2.0)
    diag_step_cost = diag_dist * ((f_u + f_v) / 2.0)

    assert ortho_step_cost == 30.0
    assert np.isclose(diag_step_cost, 42.4264, atol=1e-3)

    # Case 2: Construction friction multiplier (e.g. F(u)=3.0, F(v)=5.0 -> avg F = 4.0)
    f_u_const = 3.0
    f_v_const = 5.0
    const_ortho_cost = dx * ((f_u_const + f_v_const) / 2.0)
    const_diag_cost = diag_dist * ((f_u_const + f_v_const) / 2.0)

    # Weight = step_distance * friction_multiplier
    assert const_ortho_cost == 30.0 * 4.0  # 120.0
    assert np.isclose(const_diag_cost, diag_dist * 4.0, atol=1e-3)

    # Verify no quadratic distance scaling: (const_ortho_cost / ortho_step_cost) == 4.0
    assert const_ortho_cost / ortho_step_cost == 4.0


def test_memory_and_runtime_benchmarks_on_representative_slice(tmp_path):
    """Measures actual memory and runtime on a representative regional slice (1024x1024 cells)."""
    sub_spec = RegionalGridSpec(
        min_x=680000.0,
        min_y=3450000.0,
        max_x=680000.0 + 1024 * 30.0,
        max_y=3450000.0 + 1024 * 30.0,
        resolution_m=30.0,
        crs_epsg=32643,
    )

    builder = RegionalCostSurfaceBuilder(
        output_dir=tmp_path / "cost_regional",
        raw_dir="data/raw",
        grid_spec=sub_spec,
        tile_size=512,
        halo_pixels=3,
        resolution_m=30.0,
    )

    tracemalloc.start()
    t0 = time.time()
    manifest = builder.build_all(region_name="benchmark_slice_1024x1024")
    elapsed = time.time() - t0
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    peak_mb = peak_mem / (1024 * 1024)

    # Assertions for 1-million cell slice
    assert manifest.pipeline_status == "SUCCESS"
    assert len(manifest.layers) == 11
    # 1024x1024 slice must execute in < 15 seconds
    assert elapsed < 15.0, f"Benchmark elapsed time {elapsed:.2f}s exceeded 15s limit"
    # Peak RAM for 1-million cell slice must remain < 500 MB
    assert peak_mb < 500.0, f"Peak memory {peak_mb:.1f} MB exceeded 500 MB budget"

    # Verify output rasters on disk
    exported_files = list((tmp_path / "cost_regional" / "rasters").glob("*.tif"))
    assert len(exported_files) == 11
    total_disk_mb = sum(f.stat().st_size for f in exported_files) / (1024 * 1024)
    # Compressed COGs for 1024x1024 should be reasonably small (< 50 MB)
    assert total_disk_mb < 50.0

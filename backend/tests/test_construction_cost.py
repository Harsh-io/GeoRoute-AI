"""Unit tests for ConstructionCostModel."""

import numpy as np
import pytest

from georoute.cost.cost_assumptions import (
    CostAssumptions,
    DistanceCostConfig,
    LandCoverPenaltyConfig,
    ObstaclePenaltyConfig,
    SlopePenaltyConfig,
)
from georoute.cost.construction_cost_model import ConstructionCostModel


def test_slope_penalty_progression():
    slope_cfg = SlopePenaltyConfig(slope_reference=20.0, power=2.0, weight=2.0, max_penalty_cap=None)
    model = ConstructionCostModel(slope_config=slope_cfg)

    # 4 sample cells: 0%, 20%, 40%, 60%
    slope_arr = np.array([[0.0, 20.0], [40.0, 60.0]], dtype=np.float32)
    p_slope = model.compute_slope_penalty(slope_arr, nodata=-9999.0)

    # Flat (0%) -> 0.0
    assert p_slope[0, 0] == 0.0
    # Reference (20%) -> (20/20)^2 = 1.0
    assert pytest.approx(p_slope[0, 1], abs=1e-5) == 1.0
    # Steep (40%) -> (40/20)^2 = 4.0 (nonlinear!)
    assert pytest.approx(p_slope[1, 0], abs=1e-5) == 4.0
    # Mountainous (60%) -> (60/20)^2 = 9.0
    assert pytest.approx(p_slope[1, 1], abs=1e-5) == 9.0


def test_slope_penalty_capping():
    slope_cfg = SlopePenaltyConfig(slope_reference=20.0, power=2.0, max_penalty_cap=5.0)
    model = ConstructionCostModel(slope_config=slope_cfg)

    slope_arr = np.array([[60.0]], dtype=np.float32)  # Raw would be 9.0
    p_slope = model.compute_slope_penalty(slope_arr)

    assert p_slope[0, 0] == 5.0  # Capped at 5.0


def test_landcover_penalty_mapping():
    model = ConstructionCostModel()

    # Grid with bare (60), grassland (30), cropland (40), forest (10), built-up (50)
    lc_arr = np.array([[60, 30], [40, 10], [50, 80]], dtype=np.uint8)
    p_lc = model.compute_landcover_penalty(lc_arr, nodata=0)

    assert p_lc[0, 0] == 0.1  # Bare
    assert p_lc[0, 1] == 0.2  # Grassland
    assert p_lc[1, 0] == 1.0  # Cropland
    assert p_lc[1, 1] == 2.5  # Forest
    assert p_lc[2, 0] == 8.0  # Built-up
    assert p_lc[2, 1] == 10.0 # Water


def test_construction_surface_synthesis():
    model = ConstructionCostModel(
        distance_config=DistanceCostConfig(base_cell_distance_m=10.0),
        blocked_cell_cost=-9999.0,
    )

    shape = (2, 2)
    # Cell (0, 0): flat grassland
    # Cell (0, 1): 20% slope forest
    # Cell (1, 0): building footprint
    # Cell (1, 1): water body with nodata slope (-9999)
    slope_arr = np.array([[0.0, 20.0], [0.0, -9999.0]], dtype=np.float32)
    lc_arr = np.array([[30, 10], [30, 80]], dtype=np.uint8)

    building_mask = np.array([[0, 0], [1, 0]], dtype=np.uint8)
    water_mask = np.array([[0, 0], [0, 1]], dtype=np.uint8)

    cost, friction, penalties = model.compute_surface(
        slope_arr=slope_arr,
        lc_arr=lc_arr,
        building_mask=building_mask,
        water_mask=water_mask,
    )

    # Cell (0, 0): flat (p_slope=0) + grassland (p_lc=0.2)
    # Friction = 1.0 + 2.0*0 + 1.0*0.2 = 1.2
    # Cost = 10.0 * 1.2 = 12.0
    assert pytest.approx(friction[0, 0], abs=1e-4) == 1.2
    assert pytest.approx(cost[0, 0], abs=1e-4) == 12.0

    # Cell (0, 1): 20% slope (p_slope=1.0) + forest (p_lc=2.5)
    # Friction = 1.0 + 2.0*1.0 + 1.0*2.5 = 5.5
    # Cost = 10.0 * 5.5 = 55.0
    assert pytest.approx(friction[0, 1], abs=1e-4) == 5.5
    assert pytest.approx(cost[0, 1], abs=1e-4) == 55.0

    # Cell (1, 0): building friction
    assert friction[1, 0] > friction[0, 0]

    # Cell (1, 1): slope nodata (-9999) -> blocked
    assert cost[1, 1] == -9999.0
    assert friction[1, 1] == -9999.0


def test_building_hard_exclusion():
    obs_cfg = ObstaclePenaltyConfig(building_hard_exclusion=True)
    model = ConstructionCostModel(obstacle_config=obs_cfg, blocked_cell_cost=-9999.0)

    slope_arr = np.zeros((2, 2), dtype=np.float32)
    lc_arr = np.full((2, 2), 30, dtype=np.uint8)
    building_mask = np.array([[0, 1], [0, 0]], dtype=np.uint8)

    cost, friction, _ = model.compute_surface(
        slope_arr=slope_arr,
        lc_arr=lc_arr,
        building_mask=building_mask,
    )

    # Cell (0, 1) has building and should be blocked
    assert cost[0, 1] == -9999.0
    assert friction[0, 1] == -9999.0
    # Other cells are traversable
    assert cost[0, 0] > 0.0

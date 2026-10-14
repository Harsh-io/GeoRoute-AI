"""Unit tests for EnvironmentalCostModel."""

import numpy as np
import pytest

from georoute.cost.cost_assumptions import (
    DistanceCostConfig,
    EnvironmentalSensitivityConfig,
)
from georoute.cost.environmental_cost_model import EnvironmentalCostModel


def test_statutory_protected_area_hard_exclusion():
    env_cfg = EnvironmentalSensitivityConfig(protected_area_policy="HARD_EXCLUSION")
    model = EnvironmentalCostModel(environmental_config=env_cfg, blocked_cell_cost=-9999.0)

    shape = (2, 2)
    forest_mask = np.ones(shape, dtype=np.uint8)  # All forest
    pa_mask = np.array([[0, 1], [0, 0]], dtype=np.uint8)  # Cell (0, 1) is National Park

    cost, friction, _ = model.compute_surface(
        forest_mask=forest_mask,
        protected_area_mask=pa_mask,
    )

    # Cell (0, 0) is ordinary forest -> traversable with soft penalty
    assert cost[0, 0] > 0.0
    assert friction[0, 0] > 1.0

    # Cell (0, 1) is statutory protected area -> BLOCKED (-9999.0)
    assert cost[0, 1] == -9999.0
    assert friction[0, 1] == -9999.0


def test_statutory_protected_area_soft_penalty():
    env_cfg = EnvironmentalSensitivityConfig(
        protected_area_policy="SOFT_PENALTY",
        protected_area_penalty=50.0,
    )
    model = EnvironmentalCostModel(environmental_config=env_cfg, blocked_cell_cost=-9999.0)

    shape = (2, 2)
    forest_mask = np.zeros(shape, dtype=np.uint8)
    pa_mask = np.array([[0, 1], [0, 0]], dtype=np.uint8)

    cost, friction, _ = model.compute_surface(
        forest_mask=forest_mask,
        protected_area_mask=pa_mask,
    )

    # In soft mode, cell (0, 1) is NOT blocked, but has friction = 1.0 + 50.0 = 51.0
    assert cost[0, 1] > 0.0
    assert pytest.approx(friction[0, 1], abs=1e-4) == 51.0


def test_ndvi_canopy_scaling():
    env_cfg = EnvironmentalSensitivityConfig(
        forest_base_penalty=2.0,
        use_ndvi_canopy_weighting=True,
    )
    model = EnvironmentalCostModel(environmental_config=env_cfg)

    # 2 forest cells: one with low NDVI (0.1), one with dense canopy (0.7)
    forest_mask = np.array([[1, 1]], dtype=np.uint8)
    ndvi_arr = np.array([[0.1, 0.7]], dtype=np.float32)

    p_forest = model.compute_forest_sensitivity(forest_mask, ndvi_arr=ndvi_arr)

    # Cell (0, 0): 2.0 * (1.0 + 0.1) = 2.2
    assert pytest.approx(p_forest[0, 0], abs=1e-4) == 2.2
    # Cell (0, 1): 2.0 * (1.0 + 0.7) = 3.4 (dense canopy receives higher sensitivity!)
    assert pytest.approx(p_forest[0, 1], abs=1e-4) == 3.4
    assert p_forest[0, 1] > p_forest[0, 0]


def test_wetland_and_water_sensitivities():
    model = EnvironmentalCostModel()
    shape = (2, 2)

    forest_mask = np.zeros(shape, dtype=np.uint8)
    wetland_mask = np.array([[1, 0], [0, 0]], dtype=np.uint8)
    water_mask = np.array([[0, 1], [0, 0]], dtype=np.uint8)

    cost, friction, sensitivities = model.compute_surface(
        forest_mask=forest_mask,
        wetland_mask=wetland_mask,
        water_mask=water_mask,
    )

    # Baseline cell (1, 1) is open land -> friction = 1.0, cost = 10.0
    assert pytest.approx(friction[1, 1], abs=1e-4) == 1.0
    assert pytest.approx(cost[1, 1], abs=1e-4) == 10.0

    # Wetland cell (0, 0)
    assert sensitivities["wetland_sensitivity"][0, 0] == 5.0
    assert friction[0, 0] > 1.0

    # Water cell (0, 1)
    assert sensitivities["water_sensitivity"][0, 1] == 4.0
    assert friction[0, 1] > 1.0

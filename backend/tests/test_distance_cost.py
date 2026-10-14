"""Unit tests for DistanceCostModel."""

import numpy as np
import pytest

from georoute.cost.cost_assumptions import DistanceCostConfig
from georoute.cost.distance_cost_model import DistanceCostModel


def test_distance_cost_traversable_cells():
    config = DistanceCostConfig(base_cell_distance_m=10.0, unit="metres")
    model = DistanceCostModel(config=config, blocked_cell_cost=-9999.0)

    shape = (10, 10)
    cost, friction = model.compute_surface(grid_shape=shape)

    assert cost.shape == shape
    assert friction.shape == shape
    # All valid cells should have exact 10.0m traversal cost
    assert np.allclose(cost, 10.0)
    # Dimensionless friction is 1.0 everywhere
    assert np.allclose(friction, 1.0)


def test_distance_cost_diagonal_vs_orthogonal():
    model = DistanceCostModel(DistanceCostConfig(base_cell_distance_m=10.0))
    ortho = model.compute_edge_distance_m(is_diagonal=False)
    diag = model.compute_edge_distance_m(is_diagonal=True)

    assert ortho == 10.0
    assert pytest.approx(diag, abs=1e-4) == 14.1421


def test_distance_cost_hard_constraints_and_unknowns():
    model = DistanceCostModel(blocked_cell_cost=-9999.0)
    shape = (5, 5)

    # Cell (1, 1) is a hard constraint
    hard_constraints = np.zeros(shape, dtype=np.uint8)
    hard_constraints[1, 1] = 1

    # Cell (3, 3) is unknown/invalid data
    valid_data = np.ones(shape, dtype=np.uint8)
    valid_data[3, 3] = 0

    cost, friction = model.compute_surface(
        grid_shape=shape,
        hard_constraint_mask=hard_constraints,
        valid_data_mask=valid_data,
    )

    # Normal cells have cost 10.0 and friction 1.0
    assert cost[0, 0] == 10.0
    assert friction[0, 0] == 1.0

    # Hard-constrained cell is blocked
    assert cost[1, 1] == -9999.0
    assert friction[1, 1] == -9999.0

    # Unknown data cell is blocked
    assert cost[3, 3] == -9999.0
    assert friction[3, 3] == -9999.0

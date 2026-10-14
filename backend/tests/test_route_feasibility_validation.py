"""Tests for RouteValidator: constraint violations, corner cutting, and recomputation."""

import numpy as np
import pytest
from shapely.geometry import LineString

from georoute.routing.route_validator import RouteValidator


@pytest.fixture
def validator():
    shape = (10, 10)
    hard_mask = np.zeros(shape, dtype=np.uint8)
    valid_mask = np.ones(shape, dtype=np.uint8)

    # Block (4, 4)
    hard_mask[4, 4] = 1
    # Unknown (8, 8)
    valid_mask[8, 8] = 0

    return RouteValidator(
        grid_shape=shape,
        cell_size_x_m=10.0,
        cell_size_y_m=10.0,
        hard_constraint_mask=hard_mask,
        valid_data_mask=valid_mask,
    )


def test_valid_route_passes(validator):
    friction = np.ones((10, 10), dtype=np.float32)
    # Straight path from (0, 0) to (0, 3): 3 orthogonal steps (30m)
    path_cells = [(0, 0), (0, 1), (0, 2), (0, 3)]
    geometry = LineString([(100.0, 200.0), (110.0, 200.0), (120.0, 200.0), (130.0, 200.0)])

    route_dict = {
        "objective": "shortest_distance",
        "path_cells": path_cells,
        "geometry": geometry,
        "physical_length_m": 30.0,
        "accumulated_cost": 30.0,
    }

    report = validator.validate_route(route_dict, friction_surface=friction)
    assert report.is_valid
    assert len(report.errors) == 0
    assert report.recomputed_length_m == 30.0
    assert report.recomputed_cost == 30.0


def test_route_intersecting_hard_constraint_fails(validator):
    friction = np.ones((10, 10), dtype=np.float32)
    # Path passing through blocked cell (4, 4)
    path_cells = [(4, 2), (4, 3), (4, 4), (4, 5)]
    geometry = LineString([(100, 200), (110, 200), (120, 200), (130, 200)])

    route_dict = {
        "objective": "shortest_distance",
        "path_cells": path_cells,
        "geometry": geometry,
        "physical_length_m": 30.0,
        "accumulated_cost": 30.0,
    }

    report = validator.validate_route(route_dict, friction_surface=friction)
    assert not report.is_valid
    assert any("hard constraint" in err for err in report.errors)


def test_diagonal_corner_cutting_fails(validator):
    shape = (10, 10)
    hard_mask = np.zeros(shape, dtype=np.uint8)
    # Squeeze corners: (1, 0) and (0, 1) are blocked
    hard_mask[1, 0] = 1
    hard_mask[0, 1] = 1

    val = RouteValidator(
        grid_shape=shape,
        cell_size_x_m=10.0,
        cell_size_y_m=10.0,
        hard_constraint_mask=hard_mask,
    )

    friction = np.ones(shape, dtype=np.float32)
    # Diagonal jump from (0, 0) to (1, 1) squeezes blocked corners
    path_cells = [(0, 0), (1, 1)]
    geometry = LineString([(100, 200), (110, 190)])

    route_dict = {
        "objective": "shortest_distance",
        "path_cells": path_cells,
        "geometry": geometry,
        "physical_length_m": 14.14,
        "accumulated_cost": 14.14,
    }

    report = val.validate_route(route_dict, friction_surface=friction)
    assert not report.is_valid
    assert any("corner-cut" in err for err in report.errors)


def test_discontinuous_step_fails(validator):
    friction = np.ones((10, 10), dtype=np.float32)
    # Teleportation jump from (0, 0) to (3, 3)
    path_cells = [(0, 0), (3, 3)]
    geometry = LineString([(100, 200), (130, 170)])

    route_dict = {
        "objective": "shortest_distance",
        "path_cells": path_cells,
        "geometry": geometry,
        "physical_length_m": 42.42,
        "accumulated_cost": 42.42,
    }

    report = validator.validate_route(route_dict, friction_surface=friction)
    assert not report.is_valid
    assert any("Discontinuous step" in err for err in report.errors)

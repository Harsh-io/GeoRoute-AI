"""Unit and integration tests for pyorps_adapter.py with real installed PYORPS 0.4.0."""

import affine
import numpy as np
import pytest
from shapely.geometry import LineString

from georoute.routing.pyorps_adapter import (
    InfeasibleRouteError,
    PyorpsAdapter,
    PyorpsRouteResult,
)


@pytest.fixture
def test_setup():
    transform = affine.Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0)
    crs = "EPSG:32643"
    shape = (10, 10)
    adapter = PyorpsAdapter(scale_factor=100.0)
    return {
        "transform": transform,
        "crs": crs,
        "shape": shape,
        "adapter": adapter,
    }


def test_quantize_friction_to_uint16(test_setup):
    adapter = test_setup["adapter"]
    shape = test_setup["shape"]

    friction = np.full(shape, 2.5, dtype=np.float32)
    hard_mask = np.zeros(shape, dtype=np.uint8)
    valid_mask = np.ones(shape, dtype=np.uint8)

    # Place a hard constraint at (3, 3)
    hard_mask[3, 3] = 1
    # Place nodata at (4, 4)
    friction[4, 4] = -9999.0
    # Place unknown at (5, 5)
    valid_mask[5, 5] = 0

    quantized = adapter.quantize_friction_to_uint16(
        friction, hard_constraint_mask=hard_mask, valid_data_mask=valid_mask
    )

    # Passable cell: 2.5 * 100 = 250
    assert quantized[0, 0] == 250
    # Blocked cells: 65535
    assert quantized[3, 3] == 65535
    assert quantized[4, 4] == 65535
    assert quantized[5, 5] == 65535


def test_pyorps_find_route_synthetic_obstacle_detour(test_setup):
    adapter = test_setup["adapter"]
    shape = test_setup["shape"]
    transform = test_setup["transform"]
    crs = test_setup["crs"]

    friction = np.ones(shape, dtype=np.float32)
    hard_mask = np.zeros(shape, dtype=np.uint8)
    # Vertical wall from row 2 to 7 in column 5
    hard_mask[2:8, 5] = 1

    quantized = adapter.quantize_friction_to_uint16(friction, hard_constraint_mask=hard_mask)

    # Route from (row 4, col 1) to (row 4, col 8)
    # Coordinates in transform:
    # row 4, col 1: x = 1000 + 1.5*10 = 1015, y = 2000 - 4.5*10 = 1955
    # row 4, col 8: x = 1000 + 8.5*10 = 1085, y = 2000 - 4.5*10 = 1955
    source_xy = (1015.0, 1955.0)
    target_xy = (1085.0, 1955.0)

    res = adapter.find_route(
        quantized_raster=quantized,
        source_coords=source_xy,
        target_coords=target_xy,
        transform=transform,
        crs=crs,
        original_friction_raster=friction,
    )

    assert isinstance(res, PyorpsRouteResult)
    assert res.geometry.is_valid
    assert not res.geometry.is_empty
    assert len(res.path_cells) > 0
    # Since there's a barrier in column 5 for rows 2-7, none of the path cells should be in that wall
    for r, c in res.path_cells:
        assert not (2 <= r <= 7 and c == 5), f"Path traversed blocked wall cell ({r}, {c})!"

    # Physical length must reflect the detour (greater than straight 70m)
    assert res.total_length_m > 70.0
    # On uniform friction=1.0, recomputed cost equals physical distance
    assert pytest.approx(res.recomputed_cost, abs=1e-3) == res.total_length_m


def test_pyorps_infeasible_route_raises(test_setup):
    adapter = test_setup["adapter"]
    shape = test_setup["shape"]
    transform = test_setup["transform"]
    crs = test_setup["crs"]

    friction = np.ones(shape, dtype=np.float32)
    hard_mask = np.zeros(shape, dtype=np.uint8)
    # Complete impenetrable wall across all rows in column 5
    hard_mask[:, 5] = 1

    quantized = adapter.quantize_friction_to_uint16(friction, hard_constraint_mask=hard_mask)

    source_xy = (1015.0, 1955.0)
    target_xy = (1085.0, 1955.0)

    with pytest.raises(InfeasibleRouteError):
        adapter.find_route(
            quantized_raster=quantized,
            source_coords=source_xy,
            target_coords=target_xy,
            transform=transform,
            crs=crs,
            original_friction_raster=friction,
        )

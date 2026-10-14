"""Unit tests for EndpointValidator in GeoRoute AI routing."""

import affine
import numpy as np
import pytest
import rasterio

from georoute.routing.endpoint_validator import (
    EndpointValidator,
    ImpassableEndpointError,
    OutOfCoverageError,
    ResolvedEndpoint,
)


@pytest.fixture
def test_grid():
    """Synthetic 10x10 grid with 10m cells in EPSG:32643."""
    transform = affine.Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0)
    grid_shape = (10, 10)
    valid_mask = np.ones(grid_shape, dtype=np.uint8)
    hard_mask = np.zeros(grid_shape, dtype=np.uint8)

    # Block cell (5, 5)
    hard_mask[5, 5] = 1
    # Mark cell (0, 0) as nodata/unknown
    valid_mask[0, 0] = 0

    return {
        "crs": "EPSG:32643",
        "transform": transform,
        "grid_shape": grid_shape,
        "valid_mask": valid_mask,
        "hard_mask": hard_mask,
    }


def test_valid_endpoint_within_bounds(test_grid):
    validator = EndpointValidator(
        raster_crs=test_grid["crs"],
        transform=test_grid["transform"],
        grid_shape=test_grid["grid_shape"],
        valid_data_mask=test_grid["valid_mask"],
        hard_constraint_mask=test_grid["hard_mask"],
    )

    # Point at row 2, col 3: center x = 1000 + 3.5*10 = 1035, y = 2000 - 2.5*10 = 1975
    resolved = validator.validate_and_resolve((1035.0, 1975.0), crs="EPSG:32643", name="PointA")

    assert resolved.row == 2
    assert resolved.col == 3
    assert not resolved.is_snapped
    assert resolved.snap_distance_m == 0.0
    assert resolved.projected_coords == (1035.0, 1975.0)


def test_out_of_coverage_endpoint_raises(test_grid):
    validator = EndpointValidator(
        raster_crs=test_grid["crs"],
        transform=test_grid["transform"],
        grid_shape=test_grid["grid_shape"],
    )

    # Coordinate far to the south
    with pytest.raises(OutOfCoverageError, match="outside raster grid bounds"):
        validator.validate_and_resolve((1050.0, 500.0), crs="EPSG:32643", name="FarSouth")


def test_blocked_cell_raises_when_snapping_disabled(test_grid):
    validator = EndpointValidator(
        raster_crs=test_grid["crs"],
        transform=test_grid["transform"],
        grid_shape=test_grid["grid_shape"],
        valid_data_mask=test_grid["valid_mask"],
        hard_constraint_mask=test_grid["hard_mask"],
        snap_to_valid=False,
    )

    # Cell (5, 5): x = 1000 + 5.5*10 = 1055, y = 2000 - 5.5*10 = 1945
    with pytest.raises(ImpassableEndpointError, match="hard constraint"):
        validator.validate_and_resolve((1055.0, 1945.0), crs="EPSG:32643", name="BlockedCenter")


def test_blocked_cell_snaps_to_nearest_valid_cell(test_grid):
    validator = EndpointValidator(
        raster_crs=test_grid["crs"],
        transform=test_grid["transform"],
        grid_shape=test_grid["grid_shape"],
        valid_data_mask=test_grid["valid_mask"],
        hard_constraint_mask=test_grid["hard_mask"],
        snap_to_valid=True,
        max_snap_radius_m=20.0,
    )

    # Cell (5, 5) is blocked; nearest neighbors are 10m away
    resolved = validator.validate_and_resolve((1055.0, 1945.0), crs="EPSG:32643", name="BlockedCenter")

    assert resolved.is_snapped
    assert 9.0 <= resolved.snap_distance_m <= 15.0
    assert (resolved.row, resolved.col) != (5, 5)
    # The snapped cell must be traversable
    assert test_grid["hard_mask"][resolved.row, resolved.col] == 0


def test_snapping_fails_if_radius_too_small(test_grid):
    validator = EndpointValidator(
        raster_crs=test_grid["crs"],
        transform=test_grid["transform"],
        grid_shape=test_grid["grid_shape"],
        valid_data_mask=test_grid["valid_mask"],
        hard_constraint_mask=test_grid["hard_mask"],
        snap_to_valid=True,
        max_snap_radius_m=5.0,  # Smaller than 10m cell spacing!
    )

    with pytest.raises(ImpassableEndpointError, match="No traversable cell found within 5.0m radius"):
        validator.validate_and_resolve((1055.0, 1945.0), crs="EPSG:32643", name="BlockedCenter")


def test_real_mandi_station_endpoint():
    """Verifies that Mandi Station (31.7084 N, 76.9322 E) resolves properly against real Part 3 rasters."""
    with rasterio.open("data/cost/rasters/hard_constraint_mask.tif") as src:
        hard_mask = src.read(1)
        transform = src.transform
        crs = src.crs
        shape = (src.height, src.width)

    with rasterio.open("data/cost/rasters/valid_data_mask.tif") as src:
        valid_mask = src.read(1)

    validator = EndpointValidator(
        raster_crs=crs,
        transform=transform,
        grid_shape=shape,
        valid_data_mask=valid_mask,
        hard_constraint_mask=hard_mask,
        snap_to_valid=False,
    )

    # Mandi Railway/Town center in WGS84
    resolved = validator.validate_and_resolve(
        (76.9322, 31.7084), crs="EPSG:4326", name="Mandi Station"
    )

    assert resolved.row == 244
    assert resolved.col == 309
    assert not resolved.is_snapped
    assert hard_mask[resolved.row, resolved.col] == 0
    assert valid_mask[resolved.row, resolved.col] == 1

    # New Delhi Station should fail with OutOfCoverageError on this local raster
    with pytest.raises(OutOfCoverageError):
        validator.validate_and_resolve(
            (77.2191, 28.6428), crs="EPSG:4326", name="New Delhi Station"
        )

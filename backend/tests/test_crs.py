"""Unit tests for CRS and grid computation utilities."""

import pytest
import pyproj
from georoute.utils.crs_utils import (
    calculate_utm_epsg,
    get_utm_crs_for_bbox,
    compute_target_raster_grid,
)


def test_calculate_utm_epsg_northern_hemisphere():
    # Munich, Germany (lon 11.58, lat 48.14) -> UTM Zone 32N (EPSG:32632)
    epsg = calculate_utm_epsg(lon=11.58, lat=48.14)
    assert epsg == 32632


def test_calculate_utm_epsg_western_hemisphere():
    # New York City, USA (lon -74.00, lat 40.71) -> UTM Zone 18N (EPSG:32618)
    epsg = calculate_utm_epsg(lon=-74.00, lat=40.71)
    assert epsg == 32618


def test_calculate_utm_epsg_southern_hemisphere():
    # Sydney, Australia (lon 151.21, lat -33.87) -> UTM Zone 56S (EPSG:32756)
    epsg = calculate_utm_epsg(lon=151.21, lat=-33.87)
    assert epsg == 32756


def test_compute_target_raster_grid():
    # 10km bbox in Bavaria
    bbox = (11.40, 48.10, 11.535, 48.19)
    target_crs = pyproj.CRS.from_epsg(32632)
    transform, width, height, bounds = compute_target_raster_grid(
        bbox_4326=bbox,
        target_crs=target_crs,
        pixel_size_meters=10.0,
    )

    # Resolution should be exactly 10.0m
    assert transform.a == 10.0
    assert transform.e == -10.0
    assert width > 900 and width < 1200
    assert height > 900 and height < 1200

    # Bounds must be multiples of 10.0
    minx, miny, maxx, maxy = bounds
    assert minx % 10.0 == 0.0
    assert miny % 10.0 == 0.0
    assert maxx % 10.0 == 0.0
    assert maxy % 10.0 == 0.0

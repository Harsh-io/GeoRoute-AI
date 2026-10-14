"""Unit tests for GeoRasterizer vector rasterization engine."""

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box, LineString, Point, Polygon

from georoute.features.rasterizer import GeoRasterizer


@pytest.fixture
def sample_grid():
    """Returns a simple 10x10 metric grid in EPSG:32643 with 10m resolution."""
    # Origin at (1000, 2000), 10 cells wide and high
    transform = from_origin(1000.0, 2000.0, 10.0, 10.0)
    crs = "EPSG:32643"
    shape = (10, 10)
    return shape, transform, crs


def test_rasterize_empty_gdf(sample_grid):
    shape, transform, crs = sample_grid
    rasterizer = GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)

    # None input
    arr_none = rasterizer.rasterize_gdf(None, value=1, fill=0)
    assert arr_none.shape == shape
    assert (arr_none == 0).all()

    # Empty GDF
    empty_gdf = gpd.GeoDataFrame(columns=["geometry"], crs=crs)
    arr_empty = rasterizer.rasterize_gdf(empty_gdf, value=1, fill=0)
    assert arr_empty.shape == shape
    assert (arr_empty == 0).all()


def test_rasterize_polygon_burn(sample_grid):
    shape, transform, crs = sample_grid
    rasterizer = GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)

    # Box covering first 2x2 cells: x from 1000 to 1020, y from 1980 to 2000
    poly = box(1000.0, 1980.0, 1020.0, 2000.0)
    gdf = gpd.GeoDataFrame([{"geometry": poly}], crs=crs)

    arr = rasterizer.rasterize_gdf(gdf, value=1, fill=0, all_touched=False)
    assert arr.shape == shape
    # Top-left 2x2 cells should be 1
    assert arr[0, 0] == 1
    assert arr[0, 1] == 1
    assert arr[1, 0] == 1
    assert arr[1, 1] == 1
    # Cells outside should be 0
    assert arr[2, 2] == 0
    assert arr[5, 5] == 0
    assert arr.sum() == 4


def test_rasterize_reprojection(sample_grid):
    shape, transform, crs = sample_grid
    rasterizer = GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)

    # Create polygon in EPSG:32643 first, then project to EPSG:4326
    poly_utm = box(1000.0, 1980.0, 1020.0, 2000.0)
    gdf_utm = gpd.GeoDataFrame([{"geometry": poly_utm}], crs=crs)
    gdf_wgs84 = gdf_utm.to_crs("EPSG:4326")

    arr = rasterizer.rasterize_gdf(gdf_wgs84, value=1, fill=0, all_touched=False)
    # Burning after automatic reproject should cover the same top-left region
    assert arr[0, 0] == 1
    assert arr.sum() >= 1


def test_rasterize_line_all_touched(sample_grid):
    shape, transform, crs = sample_grid
    rasterizer = GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)

    # Line cutting diagonally across top row: from (1000, 1995) to (1050, 1995)
    line = LineString([(1000.0, 1995.0), (1050.0, 1995.0)])
    gdf = gpd.GeoDataFrame([{"geometry": line}], crs=crs)

    arr_untouched = rasterizer.rasterize_gdf(gdf, value=1, fill=0, all_touched=False)
    arr_touched = rasterizer.rasterize_gdf(gdf, value=1, fill=0, all_touched=True)

    # Untouched might miss lines with no pixel center, touched will burn all 5 pixels
    assert arr_touched[0, 0:5].sum() == 5
    assert arr_touched.sum() == 5


def test_rasterize_with_buffer(sample_grid):
    shape, transform, crs = sample_grid
    rasterizer = GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)

    # Center point at (1050, 1950) -> row 5, col 5
    point = Point(1055.0, 1945.0)
    gdf = gpd.GeoDataFrame([{"geometry": point}], crs=crs)

    # Without buffer and all_touched=False, point burns only center or 0
    arr_buffered = rasterizer.rasterize_gdf(gdf, value=1, fill=0, buffer_meters=15.0)
    # A 15m radius circle on 10m grid should cover multiple pixels
    assert arr_buffered.sum() > 1


def test_rasterize_value_column(sample_grid):
    shape, transform, crs = sample_grid
    rasterizer = GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)

    poly1 = box(1000.0, 1990.0, 1010.0, 2000.0)  # row 0, col 0
    poly2 = box(1010.0, 1990.0, 1020.0, 2000.0)  # row 0, col 1
    gdf = gpd.GeoDataFrame([
        {"geometry": poly1, "class_val": 42},
        {"geometry": poly2, "class_val": 99},
    ], crs=crs)

    arr = rasterizer.rasterize_gdf(gdf, value_column="class_val", fill=0)
    assert arr[0, 0] == 42
    assert arr[0, 1] == 99
    assert arr[1, 1] == 0


def test_create_aligned_raster_data(sample_grid):
    shape, transform, crs = sample_grid
    rasterizer = GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)

    mask = np.ones(shape, dtype=np.uint8)
    aligned = rasterizer.create_aligned_raster_data(mask, band_name="test_mask", nodata=255.0)

    assert aligned.data.shape == (1, shape[0], shape[1])
    assert aligned.band_names == ["test_mask"]
    assert aligned.nodata == 255.0
    assert aligned.transform == transform

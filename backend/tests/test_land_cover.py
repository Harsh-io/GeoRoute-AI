"""Unit tests for Land Cover nearest-neighbor resampling and class preservation."""

import numpy as np
import pyproj
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject
from georoute.processing.alignment import AlignedRasterData, SpatialAligner


def test_nearest_neighbor_preserves_discrete_classes():
    """Verify that nearest-neighbor resampling never invents intermediate classes."""
    src_crs = "EPSG:32643"
    dst_crs = "EPSG:32643"

    src_transform = Affine(20.0, 0.0, 500000.0, 0.0, -20.0, 3500000.0)
    dst_transform = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 3500000.0)

    # Source has discrete classes: 10 (Tree cover), 50 (Built-up)
    src_data = np.array([
        [10, 10, 50, 50],
        [10, 10, 50, 50],
        [50, 50, 10, 10],
        [50, 50, 10, 10],
    ], dtype=np.uint8)

    # Destination buffer (upsampled 2x)
    dst_nearest = np.zeros((8, 8), dtype=np.uint8)
    reproject(
        source=src_data,
        destination=dst_nearest,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.nearest,
    )

    # Only original classes {10, 50} must appear in destination
    unique_nearest = set(np.unique(dst_nearest))
    assert unique_nearest.issubset({10, 50}), f"Unexpected classes found: {unique_nearest}"

    # Compare with bilinear resampling, which WOULD synthesize invalid intermediate values
    dst_bilinear = np.zeros((8, 8), dtype=np.float32)
    reproject(
        source=src_data.astype(np.float32),
        destination=dst_bilinear,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.bilinear,
    )
    unique_bilinear = set(np.unique(dst_bilinear))
    # Bilinear will synthesize intermediate values (e.g. 20.0, 30.0, 40.0)
    interpolated_classes = unique_bilinear - {10.0, 50.0}
    assert len(interpolated_classes) > 0, "Bilinear should have produced blended values"


def test_multi_layer_co_registration_audit():
    """Verify verify_multi_co_registration across optical, DEM, and land cover layers."""
    crs = pyproj.CRS.from_epsg(32643)
    transform = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 3500000.0)
    width, height = 50, 50

    optical = AlignedRasterData(
        data=np.ones((4, height, width), dtype=np.float32),
        transform=transform,
        crs=crs,
        nodata=0.0,
        band_names=["B04", "B03", "B02", "B08"],
        dtype=np.float32,
    )

    dem = AlignedRasterData(
        data=np.ones((1, height, width), dtype=np.float32) * 500.0,
        transform=transform,
        crs=crs,
        nodata=-9999.0,
        band_names=["elevation_m"],
        dtype=np.float32,
    )

    land_cover = AlignedRasterData(
        data=np.full((1, height, width), fill_value=10, dtype=np.uint8),
        transform=transform,
        crs=crs,
        nodata=0.0,
        band_names=["land_cover_class"],
        dtype=np.uint8,
    )

    layers = {
        "optical": optical,
        "dem": dem,
        "land_cover": land_cover,
    }

    assert SpatialAligner.verify_multi_co_registration(layers) is True

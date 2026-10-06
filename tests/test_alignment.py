"""Unit tests for raster co-registration and spatial alignment."""

import numpy as np
import pyproj
import pytest
import rasterio
from rasterio.transform import Affine
from georoute.processing.alignment import AlignedRasterData, SpatialAligner


def test_verify_co_registration_success():
    crs = pyproj.CRS.from_epsg(32632)
    transform = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 5000000.0)

    optical = AlignedRasterData(
        data=np.ones((4, 100, 100), dtype=np.float32),
        transform=transform,
        crs=crs,
        nodata=0.0,
        band_names=["B04", "B03", "B02", "B08"],
        dtype=np.float32,
    )

    dem = AlignedRasterData(
        data=np.ones((1, 100, 100), dtype=np.float32) * 450.0,
        transform=transform,
        crs=crs,
        nodata=-9999.0,
        band_names=["elevation_m"],
        dtype=np.float32,
    )

    # Should pass without error
    assert SpatialAligner.verify_co_registration(optical, dem) is True


def test_verify_co_registration_shape_mismatch():
    crs = pyproj.CRS.from_epsg(32632)
    transform = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 5000000.0)

    optical = AlignedRasterData(
        data=np.ones((4, 100, 100), dtype=np.float32),
        transform=transform,
        crs=crs,
        nodata=0.0,
        band_names=["B04", "B03", "B02", "B08"],
        dtype=np.float32,
    )

    dem = AlignedRasterData(
        data=np.ones((1, 120, 100), dtype=np.float32),
        transform=transform,
        crs=crs,
        nodata=-9999.0,
        band_names=["elevation_m"],
        dtype=np.float32,
    )

    with pytest.raises(AssertionError, match="Optical shape .* does not match DEM shape"):
        SpatialAligner.verify_co_registration(optical, dem)


def test_verify_co_registration_crs_mismatch():
    crs1 = pyproj.CRS.from_epsg(32632)
    crs2 = pyproj.CRS.from_epsg(4326)
    transform = Affine(10.0, 0.0, 500000.0, 0.0, -10.0, 5000000.0)

    optical = AlignedRasterData(
        data=np.ones((4, 100, 100), dtype=np.float32),
        transform=transform,
        crs=crs1,
        nodata=0.0,
        band_names=["B04", "B03", "B02", "B08"],
        dtype=np.float32,
    )

    dem = AlignedRasterData(
        data=np.ones((1, 100, 100), dtype=np.float32),
        transform=transform,
        crs=crs2,
        nodata=-9999.0,
        band_names=["elevation_m"],
        dtype=np.float32,
    )

    with pytest.raises(AssertionError, match="Optical CRS .* does not match DEM CRS"):
        SpatialAligner.verify_co_registration(optical, dem)

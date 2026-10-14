"""Unit tests for EnvironmentalExtractor."""

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box

from georoute.features.environmental_extractor import EnvironmentalExtractor
from georoute.features.rasterizer import GeoRasterizer


@pytest.fixture
def mock_rasterizer():
    # 20x20 cells of 10m x 10m
    transform = from_origin(1000.0, 2000.0, 10.0, 10.0)
    crs = "EPSG:32643"
    shape = (20, 20)
    return GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)


def test_standardize_protected_areas(mock_rasterizer):
    extractor = EnvironmentalExtractor(mock_rasterizer)

    # Box inside bounds: (1000, 1900) to (1050, 1950)
    inside_poly = box(1000.0, 1900.0, 1050.0, 1950.0)
    # Box far outside bounds: (5000, 5000) to (5100, 5100)
    outside_poly = box(5000.0, 5000.0, 5100.0, 5100.0)

    gdf = gpd.GeoDataFrame([
        {"name": "Local Sanctuary", "type": "Wildlife Sanctuary", "state": "Himachal Pradesh", "geometry": inside_poly},
        {"name": "Distant Park", "type": "National Park", "state": "Kerala", "geometry": outside_poly},
    ], crs=mock_rasterizer.target_crs)

    std = extractor.standardize_protected_areas(gdf, source_name="test_source")
    # Only inside polygon should remain
    assert len(std) == 1
    row = std.iloc[0]
    assert row["name"] == "Local Sanctuary"
    assert row["zone_type"] == "Wildlife Sanctuary"
    assert row["state"] == "Himachal Pradesh"
    assert row["source"] == "test_source"
    assert row["status"] == "statutory_exclusion"
    assert row["zone_id"] == "ENV_000001"


def test_extract_environmental_layers_and_forest_separation(mock_rasterizer):
    extractor = EnvironmentalExtractor(mock_rasterizer)

    # Protected sanctuary in top-left 5x5 cells: (1000, 1950) to (1050, 2000)
    sanctuary_poly = box(1000.0, 1950.0, 1050.0, 2000.0)
    pa_gdf = gpd.GeoDataFrame([
        {"name": "Govind Sanctuary", "type": "Wildlife Sanctuary", "geometry": sanctuary_poly}
    ], crs=mock_rasterizer.target_crs)

    # Forest mask covering top-left 10x10 cells (100 pixels)
    forest_mask = np.zeros(mock_rasterizer.target_shape, dtype=np.uint8)
    forest_mask[:10, :10] = 1

    unified_env, masks, metrics = extractor.extract_environmental_layers(
        authoritative_pa_gdf=pa_gdf,
        forest_mask=forest_mask,
    )

    assert len(unified_env) == 1
    assert "protected_area_mask" in masks
    pa_mask = masks["protected_area_mask"]

    # Top-left 5x5 cells (25 pixels) are protected
    assert pa_mask[:5, :5].sum() == 25
    assert pa_mask[10:, 10:].sum() == 0

    # Forest breakdown metrics
    breakdown = metrics["forest_breakdown"]
    assert breakdown["total_forest_pixels"] == 100
    assert breakdown["hard_exclusion_forest_pixels"] == 25
    assert breakdown["soft_friction_forest_pixels"] == 75
    assert breakdown["statutory_forest_ratio"] == 0.25


def test_extract_environmental_empty(mock_rasterizer):
    extractor = EnvironmentalExtractor(mock_rasterizer)
    unified_env, masks, metrics = extractor.extract_environmental_layers()

    assert len(unified_env) == 0
    assert (masks["protected_area_mask"] == 0).all()
    assert metrics["protected_zones_count"] == 0
    assert metrics["protected_pixel_count"] == 0

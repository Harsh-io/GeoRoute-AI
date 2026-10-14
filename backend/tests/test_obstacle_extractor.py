"""Unit tests for ObstacleExtractor."""

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box, LineString, Polygon

from georoute.features.obstacle_extractor import ObstacleExtractor
from georoute.features.rasterizer import GeoRasterizer


@pytest.fixture
def mock_rasterizer():
    """Returns a GeoRasterizer for a 20x20 grid with 10m cells at origin (1000, 2000)."""
    transform = from_origin(1000.0, 2000.0, 10.0, 10.0)
    crs = "EPSG:32643"
    shape = (20, 20)
    return GeoRasterizer(target_shape=shape, target_transform=transform, target_crs=crs)


def test_standardize_layer(mock_rasterizer):
    extractor = ObstacleExtractor(mock_rasterizer)

    # Bowtie invalid polygon to test make_valid
    invalid_poly = Polygon([(1000, 1990), (1020, 1970), (1000, 1970), (1020, 1990)])
    gdf = gpd.GeoDataFrame([{"name": "Bad Building", "geometry": invalid_poly}], crs=mock_rasterizer.target_crs)

    std = extractor.standardize_layer(gdf, obstacle_type="building", source="osm_test")
    assert len(std) == 1
    assert std.iloc[0]["obstacle_type"] == "building"
    assert std.iloc[0]["source"] == "osm_test"
    assert std.iloc[0]["name"] == "Bad Building"
    assert std.iloc[0]["obstacle_id"].startswith("OBS_BUIL_")
    assert std.geometry.iloc[0].is_valid


def test_extract_obstacles_fusion_and_masks(mock_rasterizer):
    extractor = ObstacleExtractor(mock_rasterizer)

    # 1. Building polygon covering (row 1, col 1): coords (1010, 1980) to (1020, 1990)
    bldg_poly = box(1010.0, 1980.0, 1020.0, 1990.0)
    bldgs = gpd.GeoDataFrame([{"name": "Govt Office", "geometry": bldg_poly}], crs=mock_rasterizer.target_crs)

    # 2. Waterway line covering row 5, col 0 to 4: coords (1000, 1945) to (1050, 1945)
    water_line = LineString([(1000.0, 1945.0), (1050.0, 1945.0)])
    waterways = gpd.GeoDataFrame([{"name": "Stream", "geometry": water_line}], crs=mock_rasterizer.target_crs)

    # 3. Landcover array with water (80) at bottom-right corner (row 19, col 19)
    lc = np.full(mock_rasterizer.target_shape, 10, dtype=np.uint8)  # Tree cover
    lc[19, 19] = 80  # Permanent water body

    unified_gdf, masks = extractor.extract_obstacles(
        buildings_gdf=bldgs,
        waterways_gdf=waterways,
        landcover_array=lc,
        water_class_value=80,
    )

    # Unified vector
    assert len(unified_gdf) == 2
    assert set(unified_gdf["obstacle_type"]) == {"building", "waterway"}
    assert unified_gdf["obstacle_id"].iloc[0] == "OBS_000001"
    assert unified_gdf["obstacle_id"].iloc[1] == "OBS_000002"

    # Masks
    assert "building_mask" in masks
    assert "water_mask" in masks
    assert "railway_mask" in masks
    assert "combined_obstacle_mask" in masks

    # Building mask
    assert masks["building_mask"][1, 1] == 1
    assert masks["building_mask"][0, 0] == 0

    # Water mask combines vector waterway (row 5) and raster water body (row 19, col 19)
    assert masks["water_mask"][5, 0] == 1
    assert masks["water_mask"][19, 19] == 1

    # Combined mask covers building, waterway, and water body
    assert masks["combined_obstacle_mask"][1, 1] == 1
    assert masks["combined_obstacle_mask"][5, 0] == 1
    assert masks["combined_obstacle_mask"][19, 19] == 1
    assert masks["combined_obstacle_mask"][0, 0] == 0


def test_extract_obstacles_empty(mock_rasterizer):
    extractor = ObstacleExtractor(mock_rasterizer)
    unified_gdf, masks = extractor.extract_obstacles()

    assert len(unified_gdf) == 0
    assert masks["building_mask"].shape == mock_rasterizer.target_shape
    assert (masks["building_mask"] == 0).all()
    assert (masks["combined_obstacle_mask"] == 0).all()

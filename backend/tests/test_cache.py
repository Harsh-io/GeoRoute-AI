"""Unit tests for the local data cache manager."""

import geopandas as gpd
import pytest
from shapely.geometry import Point
from georoute.data_cache.cache_manager import DataCacheManager


def test_cache_bbox_hash_stability():
    bbox1 = (76.9322, 31.7084, 76.9500, 31.7200)
    bbox2 = (76.9322, 31.7084, 76.9500, 31.7200)
    bbox3 = (76.9323, 31.7084, 76.9500, 31.7200)

    h1 = DataCacheManager.compute_bbox_hash(bbox1)
    h2 = DataCacheManager.compute_bbox_hash(bbox2)
    h3 = DataCacheManager.compute_bbox_hash(bbox3)

    assert h1 == h2
    assert h1 != h3


def test_cache_vector_layer_save_and_retrieve(tmp_path):
    cache = DataCacheManager(cache_dir=tmp_path)
    bbox = (76.90, 31.68, 76.96, 31.73)
    tags = {"railway": True}

    # Initial check should be cache miss
    assert cache.get_vector_layer("railways", bbox, tags) is None

    # Save a sample GeoDataFrame
    sample_gdf = gpd.GeoDataFrame(
        {"name": ["Mandi Station Track"], "layer_name": ["railways"]},
        geometry=[Point(76.9322, 31.7084)],
        crs="EPSG:4326",
    )
    saved_path = cache.save_vector_layer("railways", bbox, tags, sample_gdf)
    assert saved_path.exists()

    # Second check should be cache hit
    loaded_gdf = cache.get_vector_layer("railways", bbox, tags)
    assert loaded_gdf is not None
    assert len(loaded_gdf) == 1
    assert loaded_gdf.iloc[0]["name"] == "Mandi Station Track"


def test_cache_raster_path_destination(tmp_path):
    cache = DataCacheManager(cache_dir=tmp_path)
    dest = cache.get_raster_destination(
        collection="esa-worldcover",
        item_id="ESA_WorldCover_10m_2021_v200_N30E075",
        asset_name="map",
    )
    assert dest.suffix == ".tif"
    assert "esa-worldcover" in dest.name
    # File doesn't exist yet
    assert cache.get_raster_path("esa-worldcover", "ESA_WorldCover_10m_2021_v200_N30E075", "map") is None

    # Create dummy file
    dest.write_bytes(b"dummy_geotiff_bytes")
    assert cache.get_raster_path("esa-worldcover", "ESA_WorldCover_10m_2021_v200_N30E075", "map") == dest

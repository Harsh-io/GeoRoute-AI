"""Integration test verifying end-to-end pipeline execution with local fixtures."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pyproj
import pytest
from rasterio.transform import Affine
from shapely.geometry import box, LineString, Polygon
import geopandas as gpd

from georoute.config import PipelineConfig
from georoute.pipeline import GeoRoutePipeline
from georoute.processing.alignment import AlignedRasterData


def test_pipeline_execution_with_fixtures(tmp_path):
    """Verifies that GeoRoutePipeline executes all stages and generates a validated manifest."""
    config_yaml = f"""
region:
  name: "mandi_mock_test"
  bbox:
    min_lon: 76.90
    min_lat: 31.68
    max_lon: 76.95
    max_lat: 31.73
temporal:
  start_date: "2024-04-01"
  end_date: "2024-06-30"
stac:
  optical:
    bands: ["B04", "B03", "B02", "B08"]
  land_cover:
    enabled: true
vector:
  layers:
    highways:
      tags: {{"highway": true}}
    railways:
      tags: {{"railway": true}}
protected_areas:
  enabled: true
  layer_name: "environmental_zones"
  fallback_to_osm: true
processing:
  target_pixel_size_meters: 10.0
export:
  output_dir: "{str(tmp_path / 'processed').replace('\\', '/')}"
"""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(config_yaml, encoding="utf-8")

    cfg = PipelineConfig.from_yaml(cfg_file)
    pipeline = GeoRoutePipeline(config=cfg)

    # Mock STAC search responses
    mock_opt_meta = MagicMock(
        item_id="S2A_TEST_MANDI",
        datetime="2024-05-15T05:30:00Z",
        cloud_cover=1.5,
        band_urls={"B04": "mock://b04.tif", "B03": "mock://b03.tif", "B02": "mock://b02.tif", "B08": "mock://b08.tif"},
    )
    mock_dem_meta = MagicMock(
        item_ids=["COP30_TEST_MANDI"],
        asset_urls=["mock://dem.tif"],
        collection="cop-dem-glo-30",
    )
    mock_lc_meta = MagicMock(
        item_ids=["ESA_LC_TEST_MANDI"],
        asset_urls=["mock://lc.tif"],
        collection="esa-worldcover",
    )

    h, w = pipeline.grid_height, pipeline.grid_width
    t = pipeline.target_transform
    crs = pipeline.target_utm_crs

    fake_optical = AlignedRasterData(
        data=np.ones((4, h, w), dtype=np.float32),
        transform=t, crs=crs, nodata=0.0,
        band_names=["B04", "B03", "B02", "B08"], dtype=np.float32,
    )
    fake_dem = AlignedRasterData(
        data=np.full((1, h, w), fill_value=850.0, dtype=np.float32),
        transform=t, crs=crs, nodata=-9999.0,
        band_names=["elevation_m"], dtype=np.float32,
    )
    fake_lc = AlignedRasterData(
        data=np.full((1, h, w), fill_value=10, dtype=np.uint8),
        transform=t, crs=crs, nodata=0.0,
        band_names=["land_cover_class"], dtype=np.uint8,
    )

    fake_vector_gdf = gpd.GeoDataFrame(
        {"name": ["Sample Track"], "layer_name": ["railways"]},
        geometry=[LineString([(76.92, 31.70), (76.94, 31.72)])],
        crs="EPSG:4326",
    )

    with patch.object(pipeline.stac_ingestor, "search_optical_scene", return_value=mock_opt_meta), \
         patch.object(pipeline.stac_ingestor, "search_dem", return_value=mock_dem_meta), \
         patch.object(pipeline.stac_ingestor, "search_land_cover", return_value=mock_lc_meta), \
         patch.object(pipeline.aligner, "resample_and_align_optical", return_value=fake_optical), \
         patch.object(pipeline.aligner, "resample_and_align_dem", return_value=fake_dem), \
         patch.object(pipeline.aligner, "resample_and_align_land_cover", return_value=fake_lc), \
         patch.object(pipeline.vector_ingestor, "fetch_layer", return_value=fake_vector_gdf):

        summary = pipeline.execute()

    assert summary["status"] == "SUCCESS"
    assert "optical_cog" in summary["artifacts"]
    assert "dem_cog" in summary["artifacts"]
    assert "landcover_cog" in summary["artifacts"]
    assert "manifest_json" in summary["artifacts"]

    manifest_file = Path(summary["artifacts"]["manifest_json"])
    assert manifest_file.exists()

    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert manifest_data["pipeline_status"] == "SUCCESS"
    assert manifest_data["target_grid"]["width"] == w
    assert manifest_data["target_grid"]["height"] == h
    assert "optical" in manifest_data["rasters"]
    assert "dem" in manifest_data["rasters"]
    assert "land_cover" in manifest_data["rasters"]
    assert manifest_data["rasters"]["land_cover"]["resampling_method"] == "nearest"
    assert manifest_data["spatial_reference"]["target_utm_epsg"] == pipeline.utm_epsg

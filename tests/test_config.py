"""Unit tests for configuration validation."""

import pytest
from pydantic import ValidationError
from georoute.config import BBoxConfig, PipelineConfig


def test_bbox_valid():
    bbox = BBoxConfig(min_lon=10.0, min_lat=45.0, max_lon=10.5, max_lat=45.5)
    assert bbox.as_tuple == (10.0, 45.0, 10.5, 45.5)
    poly = bbox.as_polygon
    assert poly.bounds == (10.0, 45.0, 10.5, 45.5)


def test_bbox_invalid_lat_range():
    with pytest.raises(ValidationError):
        BBoxConfig(min_lon=10.0, min_lat=-95.0, max_lon=10.5, max_lat=45.5)


def test_bbox_min_greater_than_max():
    with pytest.raises(ValidationError):
        BBoxConfig(min_lon=15.0, min_lat=45.0, max_lon=10.0, max_lat=45.5)


def test_config_from_yaml(tmp_path):
    yaml_content = """
region:
  name: "test_region"
  bbox:
    min_lon: 11.0
    min_lat: 48.0
    max_lon: 11.1
    max_lat: 48.1
temporal:
  start_date: "2023-01-01"
  end_date: "2023-01-31"
stac:
  optical:
    max_cloud_cover_percent: 10.0
vector:
  layers:
    roads:
      tags:
        highway: true
"""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    cfg = PipelineConfig.from_yaml(config_file)
    assert cfg.region_name == "test_region"
    assert cfg.bbox.min_lon == 11.0
    assert cfg.temporal.start_date == "2023-01-01"
    assert cfg.stac.optical.max_cloud_cover_percent == 10.0
    assert "roads" in cfg.vector.layers

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
    # Default land cover & protected areas configs
    assert cfg.stac.land_cover.collection == "esa-worldcover"
    assert cfg.stac.land_cover.resampling_method == "nearest"
    assert cfg.protected_areas.enabled is True
    assert cfg.processing.land_cover_resampling_method == "nearest"


def test_metadata_manifest_schema(tmp_path):
    from georoute.schemas.manifest_schema import (
        MetadataManifest,
        SpatialReferenceMetadata,
        GridDefinitionMetadata,
        RasterLayerMetadata,
        VectorLayerMetadata,
        DatasetAttribution,
    )

    manifest = MetadataManifest(
        manifest_id="test_run_01",
        region_name="mandi_terminal",
        pipeline_status="SUCCESS",
        elapsed_seconds=12.34,
        spatial_reference=SpatialReferenceMetadata(
            target_crs="EPSG:32643",
            target_utm_epsg=32643,
            bounds_wgs84={"min_lon": 76.90, "min_lat": 31.68, "max_lon": 76.96, "max_lat": 31.73},
            bounds_projected={"minx": 680000.0, "miny": 3507000.0, "maxx": 686000.0, "maxy": 3513000.0},
        ),
        target_grid=GridDefinitionMetadata(
            width=600,
            height=600,
            resolution_meters=10.0,
            transform=[10.0, 0.0, 680000.0, 0.0, -10.0, 3513000.0],
        ),
        rasters={
            "land_cover": RasterLayerMetadata(
                layer_name="land_cover",
                file_path="./data/processed/rasters/landcover_10m.tif",
                source_collection="esa-worldcover",
                source_item_ids=["ESA_WorldCover_10m_2021_v200_N30E075"],
                crs="EPSG:32643",
                width=600,
                height=600,
                bands=1,
                band_names=["land_cover_class"],
                dtype="uint8",
                nodata=0.0,
                resolution_meters=10.0,
                transform=[10.0, 0.0, 680000.0, 0.0, -10.0, 3513000.0],
                bounds_projected={"minx": 680000.0, "miny": 3507000.0, "maxx": 686000.0, "maxy": 3513000.0},
                resampling_method="nearest",
            )
        },
        attributions={
            "esa_worldcover": DatasetAttribution(
                dataset_name="ESA WorldCover 10m 2021",
                source_identifier="esa-worldcover",
                license="CC-BY 4.0",
                attribution="European Space Agency (ESA) WorldCover 10m 2021",
            )
        },
    )

    out_file = tmp_path / "metadata_manifest.json"
    manifest.to_json_file(str(out_file))

    assert out_file.exists()
    import json
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["manifest_id"] == "test_run_01"
    assert data["rasters"]["land_cover"]["resampling_method"] == "nearest"
    assert data["spatial_reference"]["target_utm_epsg"] == 32643

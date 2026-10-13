"""Pydantic schema definitions for machine-readable geospatial metadata manifests."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DatasetAttribution(BaseModel):
    """Source provenance, licensing, and citation metadata."""
    dataset_name: str
    source_identifier: str
    license: str
    attribution: str
    url: Optional[str] = None
    retrieval_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class RasterLayerMetadata(BaseModel):
    """Georeferencing and grid metadata for an aligned raster layer."""
    layer_name: str
    file_path: str
    source_collection: str
    source_item_ids: List[str]
    crs: str
    width: int
    height: int
    bands: int
    band_names: List[str]
    dtype: str
    nodata: Optional[float]
    resolution_meters: float
    transform: List[float]  # 6-element Affine coefficients [a, b, c, d, e, f]
    bounds_projected: Dict[str, float]
    resampling_method: str
    coverage_percent: float = 100.0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean_value: Optional[float] = None


class VectorLayerMetadata(BaseModel):
    """Provenance and schema metadata for an aligned vector layer."""
    layer_name: str
    file_path: str
    source: str
    feature_count: int
    crs: str
    bounds_projected: Dict[str, float]
    geometry_types: List[str]
    attributes: List[str]
    sanitized: bool = True
    repaired_geometry_count: int = 0


class SpatialReferenceMetadata(BaseModel):
    """Unified coordinate reference system and study bounds."""
    input_crs: str = "EPSG:4326"
    target_crs: str
    target_utm_epsg: int
    bounds_wgs84: Dict[str, float]
    bounds_projected: Dict[str, float]


class GridDefinitionMetadata(BaseModel):
    """Master grid geometry definition to which all rasters are snapped."""
    width: int
    height: int
    resolution_meters: float
    transform: List[float]
    snapped: bool = True


class MetadataManifest(BaseModel):
    """Complete machine-readable metadata manifest for Part 1 outputs."""
    schema_version: str = "1.0.0"
    manifest_id: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    region_name: str
    pipeline_status: str  # "SUCCESS", "PARTIAL", "FAILED"
    elapsed_seconds: float
    spatial_reference: SpatialReferenceMetadata
    target_grid: GridDefinitionMetadata
    rasters: Dict[str, RasterLayerMetadata] = Field(default_factory=dict)
    vectors: Dict[str, VectorLayerMetadata] = Field(default_factory=dict)
    attributions: Dict[str, DatasetAttribution] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    def to_json_file(self, dest_path: str) -> None:
        """Serializes manifest to JSON file."""
        import json
        from pathlib import Path
        p = Path(dest_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)

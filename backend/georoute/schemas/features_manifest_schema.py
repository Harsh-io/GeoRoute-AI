"""Pydantic schema definitions for machine-readable feature extraction metadata manifests."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class FeatureRasterLayerMetadata(BaseModel):
    """Georeferencing and statistical metadata for an extracted constraint raster layer."""
    layer_name: str
    file_path: str
    crs: str
    width: int
    height: int
    bands: int
    band_names: List[str]
    dtype: str
    nodata: Optional[float]
    resolution_meters: float
    transform: List[float]
    bounds_projected: Dict[str, float]
    sha256: str
    spatial_alignment_verified: bool = True
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean_value: Optional[float] = None
    foreground_pixels: Optional[int] = None
    foreground_percentage: Optional[float] = None


class FeatureVectorLayerMetadata(BaseModel):
    """Provenance and schema metadata for an extracted constraint vector layer."""
    layer_name: str
    file_path: str
    feature_count: int
    crs: str
    bounds_projected: Dict[str, float]
    geometry_types: List[str]
    attributes: List[str]
    sha256: str


class DeliverableItem(BaseModel):
    """Specification of an architectural deliverable and its downstream purpose."""
    deliverable: str
    why_it_matters: str
    artifacts: List[str]
    status: str = "VALIDATED"


class FeaturesManifest(BaseModel):
    """Complete machine-readable metadata manifest for Part 2 feature extraction outputs."""
    schema_version: str = "2.0.0"
    manifest_id: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    region_name: str
    pipeline_status: str  # "SUCCESS", "PARTIAL", "FAILED"
    elapsed_seconds: float
    spatial_reference: Dict[str, Any]
    target_grid: Dict[str, Any]
    deliverables: Dict[str, DeliverableItem] = Field(default_factory=dict)
    rasters: Dict[str, FeatureRasterLayerMetadata] = Field(default_factory=dict)
    vectors: Dict[str, FeatureVectorLayerMetadata] = Field(default_factory=dict)
    landcover_summary: Dict[str, Any] = Field(default_factory=dict)
    optical_validation: Dict[str, Any] = Field(default_factory=dict)
    environmental_metrics: Dict[str, Any] = Field(default_factory=dict)
    slope_metrics: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


    def to_json_file(self, dest_path: Union[str, Path]) -> None:
        """Serializes manifest to JSON file."""
        p = Path(dest_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)

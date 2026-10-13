"""Pydantic schema definitions for Phase B Raw Data Manifest."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class EndpointCoverageStatus(BaseModel):
    """Validation status for start/destination endpoints against a dataset."""
    mandi_covered: bool
    delhi_covered: bool
    details: Optional[str] = None


class DataLayerManifestEntry(BaseModel):
    """Provenance, spatial characteristics, and validation status for a data layer."""
    layer_id: str
    layer_type: str  # "raster" or "vector"
    source_name: str
    provider: str
    license: str
    temporal_range: str
    nominal_resolution: str
    local_paths: List[str] = Field(default_factory=list)
    source_urls: List[str] = Field(default_factory=list)
    crs: str
    bounds_wgs84: Dict[str, float]
    feature_or_tile_count: int
    size_bytes: int = 0
    sha256_hashes: Dict[str, str] = Field(default_factory=dict)
    validation_status: str  # "VALID", "PARTIAL", "WARNING"
    endpoint_coverage: EndpointCoverageStatus
    coverage_notes: str = ""
    known_limitations_and_gaps: List[str] = Field(default_factory=list)
    metadata_attributes: Dict[str, Any] = Field(default_factory=dict)


class StudyAreaBounds(BaseModel):
    """Bounding box coordinates for corridor study area."""
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    width_km: float
    height_km: float
    total_area_km2: float


class RawDataManifest(BaseModel):
    """Complete machine-readable manifest of all Phase B acquired datasets."""
    schema_version: str = "2.0.0"
    corridor_id: str = "mandi_to_new_delhi"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    study_area: StudyAreaBounds
    endpoints: Dict[str, Any]
    layers: Dict[str, DataLayerManifestEntry] = Field(default_factory=dict)
    reused_local_datasets: List[str] = Field(default_factory=list)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
    storage_summary: Dict[str, Any] = Field(default_factory=dict)
    missing_tiles_and_gaps: List[str] = Field(default_factory=list)

    def to_json_file(self, dest_path: Union[str, Path]) -> None:
        """Serializes manifest to JSON file."""
        p = Path(dest_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2)

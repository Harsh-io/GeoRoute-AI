"""Pydantic schema definitions for machine-readable cost surface metadata manifests."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class CostLayerMetadata(BaseModel):
    """Georeferencing, statistical, and semantic metadata for a generated cost surface layer."""
    layer_name: str
    file_path: str
    objective_type: str  # "DISTANCE", "CONSTRUCTION", "ENVIRONMENTAL", "CONSTRAINT", "PENALTY"
    crs: str
    width: int
    height: int
    dtype: str
    nodata: Optional[float]
    resolution_meters: float
    transform: List[float]
    sha256: str
    spatial_alignment_verified: bool = True
    unit_or_semantics: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean_value: Optional[float] = None
    std_value: Optional[float] = None
    traversable_cells: int
    blocked_cells: int
    blocked_percentage: float


class CostSurfaceSummary(BaseModel):
    """High-level statistical summary across the three cost objectives."""
    grid_dimensions: Dict[str, int]
    resolution_meters: float
    total_cells: int
    distance_cost_stats: Dict[str, Any]
    construction_cost_stats: Dict[str, Any]
    environmental_cost_stats: Dict[str, Any]
    hard_constraints_summary: Dict[str, Any]


class CostSurfaceManifest(BaseModel):
    """Complete machine-readable metadata manifest for Part 3 cost modeling deliverables."""
    schema_version: str = "3.0.0"
    manifest_id: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    region_name: str
    pipeline_status: str  # "SUCCESS", "PARTIAL", "FAILED"
    elapsed_seconds: float
    spatial_reference: Dict[str, Any]
    target_grid: Dict[str, Any]
    cost_assumptions: Dict[str, Any]
    layers: Dict[str, CostLayerMetadata] = Field(default_factory=dict)
    summary: Dict[str, Any] = Field(default_factory=dict)
    validation_results: Dict[str, Any] = Field(default_factory=dict)
    engineering_disclaimer: str = Field(
        default=(
            "GeoRoute AI cost surfaces represent preliminary regional planning friction and "
            "dimensionless relative difficulty scores. They do NOT establish certified engineering feasibility, "
            "monetary construction budgets (INR/crores), geotechnical suitability, legal land acquisition rights, "
            "or statutory environmental clearances."
        )
    )
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    def to_json_file(self, dest_path: Union[str, Path]) -> None:
        """Serializes manifest to JSON file."""
        p = Path(dest_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)

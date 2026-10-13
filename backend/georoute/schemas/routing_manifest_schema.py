"""Pydantic v2 schema models for Part 4 multi-objective routing manifests and outputs."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class CandidateRouteSummary(BaseModel):
    """Machine-readable summary of an individual optimized railway corridor."""
    route_id: str
    objective: str
    status: str = Field(
        default="preliminary_candidate_corridor",
        description="Engineering maturity classification",
    )
    length_m: float
    length_km: float
    accumulated_cost: float
    cost_units: str
    num_nodes: int
    algorithm: str
    slope_profile: Dict[str, Any] = Field(default_factory=dict)
    landcover_distribution_percent: Dict[str, float] = Field(default_factory=dict)
    infrastructure_crossings: Dict[str, Any] = Field(default_factory=dict)
    validation: Dict[str, Any] = Field(default_factory=dict)


class RoutingManifest(BaseModel):
    """Master manifest capturing Part 4 three-objective route execution and verification."""
    schema_version: str = "4.0.0"
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    region_name: str
    pipeline_status: str  # "SUCCESS", "PARTIAL", "FAILED"
    elapsed_seconds: float
    source: Dict[str, Any]
    destination: Dict[str, Any]
    spatial_reference: Dict[str, Any]
    num_routes: int
    routes: List[CandidateRouteSummary] = Field(default_factory=list)
    engineering_disclaimer: str = Field(
        default=(
            "GeoRoute AI routes represent preliminary regional planning corridors only, "
            "not certified engineering-feasible railway alignments. They do not account for "
            "sub-surface geology, ruling railway gradients, transition curves, bridge/tunnel "
            "structural designs, or statutory environmental approvals."
        )
    )
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    def to_json_file(self, dest_path: Union[str, Path]) -> None:
        """Serializes manifest to JSON file."""
        p = Path(dest_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2)

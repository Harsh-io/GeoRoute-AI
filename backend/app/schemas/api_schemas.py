"""Pydantic request, response, error, and status schemas for the GeoRoute AI API."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class CoordinatePoint(BaseModel):
    """Geographic coordinate representation."""

    longitude: float = Field(..., description="Longitude in decimal degrees [-180.0, 180.0]")
    latitude: float = Field(..., description="Latitude in decimal degrees [-90.0, 90.0]")
    name: Optional[str] = Field(default=None, description="Human-readable label for endpoint")

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError(f"Longitude {v} must be between -180.0 and 180.0.")
        return float(v)

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError(f"Latitude {v} must be between -90.0 and 90.0.")
        return float(v)

    @property
    def as_tuple(self) -> tuple[float, float]:
        return (self.longitude, self.latitude)


class RouteGenerationRequest(BaseModel):
    """Request payload to initiate candidate railway corridor generation."""

    source: CoordinatePoint = Field(..., description="Origin endpoint coordinates")
    destination: CoordinatePoint = Field(..., description="Destination endpoint coordinates")
    source_crs: str = Field(default="EPSG:4326", description="CRS of source coordinates")
    target_crs: str = Field(default="EPSG:4326", description="CRS of destination coordinates")
    processing_mode: Literal["precomputed", "full_pipeline"] = Field(
        default="precomputed",
        description="Routing workflow mode ('precomputed' uses prepared rasters; 'full_pipeline' runs ingestion-to-routing)",
    )
    objectives: List[
        Literal["shortest_distance", "lowest_construction_difficulty", "lowest_environmental_impact"]
    ] = Field(
        default_factory=lambda: [
            "shortest_distance",
            "lowest_construction_difficulty",
            "lowest_environmental_impact",
        ],
        description="List of independent corridor objectives to optimize",
    )
    region_name: str = Field(default="mandi_corridor_study_area", description="Corridor study region identifier")
    snap_to_valid: bool = Field(default=True, description="Whether to radially snap endpoints blocked by obstacles")
    max_snap_radius_m: float = Field(default=500.0, ge=10.0, le=5000.0, description="Max radial snap distance in meters")
    backend: Literal["pyorps", "networkx"] = Field(default="pyorps", description="Routing solver backend engine")


class JobCreateResponse(BaseModel):
    """Immediate HTTP 202 response acknowledging accepted job."""

    job_id: str
    status: str = "queued"
    created_at: str
    status_url: str
    message: str = "Route generation job accepted for asynchronous processing."


class JobStatusResponse(BaseModel):
    """Detailed job status response."""

    job_id: str
    status: Literal[
        "queued",
        "validating",
        "downloading",
        "preprocessing",
        "extracting_features",
        "building_cost_surfaces",
        "routing",
        "validating_routes",
        "completed",
        "partial_success",
        "failed",
        "cancelled",
    ]
    current_stage: str
    progress_percent: Optional[float] = None
    elapsed_seconds: float
    processing_mode: str
    created_at: str
    updated_at: str
    source: Optional[Dict[str, Any]] = None
    destination: Optional[Dict[str, Any]] = None
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    result_url: Optional[str] = None
    geojson_url: Optional[str] = None


class JobResultResponse(BaseModel):
    """Complete structured routing results for a finished job."""

    job_id: str
    status: str
    region_name: str
    elapsed_seconds: float
    source: Dict[str, Any]
    destination: Dict[str, Any]
    spatial_reference: Dict[str, Any]
    num_routes: int
    routes: List[Dict[str, Any]]
    engineering_disclaimer: str
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    artifacts: Dict[str, str] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Liveness check response."""

    status: str = "healthy"
    version: str
    environment: str
    timestamp: str
    uptime_seconds: float


class ReadyResponse(BaseModel):
    """Readiness check response."""

    status: str = "ready"
    precomputed_mode_ready: bool
    full_pipeline_mode_ready: bool
    pyorps_engine_available: bool
    storage_ready: bool
    active_jobs: int
    queued_jobs: int
    details: Dict[str, Any]


class CapabilitiesResponse(BaseModel):
    """System capabilities metadata response."""

    app_version: str
    supported_objectives: List[str]
    routing_backend: str
    pyorps_version: str
    available_processing_modes: List[str]
    current_dataset_coverage: Dict[str, Any]
    engineering_disclaimer: str


class ErrorResponse(BaseModel):
    """Standardized machine-readable error payload."""

    code: str
    message: str
    details: Optional[Any] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

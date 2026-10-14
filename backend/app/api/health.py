"""Health, readiness, and capabilities API routes for GeoRoute AI."""

from datetime import datetime, timezone
import time
from fastapi import APIRouter, Request

from app.config import settings
from app.schemas.api_schemas import (
    CapabilitiesResponse,
    HealthResponse,
    ReadyResponse,
)

router = APIRouter(tags=["System & Diagnostics"])

START_TIME = time.time()


@router.get("/health", response_model=HealthResponse, summary="API process liveness check")
async def get_health() -> HealthResponse:
    """Verifies that the API service process is alive and responsive."""
    uptime = time.time() - START_TIME
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc).isoformat(),
        uptime_seconds=round(uptime, 2),
    )


@router.get("/ready", response_model=ReadyResponse, summary="Pipeline and storage readiness check")
async def get_ready(request: Request) -> ReadyResponse:
    """Checks whether the system is ready to accept and execute routing jobs."""
    # Check precomputed rasters
    cost_rasters = settings.cost_dir / "rasters"
    precomputed_ready = (
        (cost_rasters / "distance_friction.tif").exists()
        and (cost_rasters / "hard_constraint_mask.tif").exists()
        and (cost_rasters / "valid_data_mask.tif").exists()
    )

    # Check PYORPS engine
    pyorps_ready = False
    try:
        import pyorps
        pyorps_ready = hasattr(pyorps, "PathFinder")
    except ImportError:
        pass

    # Check storage writability
    storage_ready = settings.jobs_dir.exists() and settings.sqlite_db_path.parent.exists()

    # Check regional rasters readiness
    regional_rasters = settings.regional_cost_dir / "rasters"
    regional_ready = (
        (regional_rasters / "distance_friction.tif").exists()
        and (regional_rasters / "hard_constraint_mask.tif").exists()
        and (regional_rasters / "valid_data_mask.tif").exists()
    )

    job_store = getattr(request.app.state, "job_store", None)
    active_jobs = job_store.count_active_jobs() if job_store else 0
    queued_jobs = job_store.count_queued_jobs() if job_store else 0

    all_ready = precomputed_ready and pyorps_ready and storage_ready

    return ReadyResponse(
        status="ready" if all_ready else "degraded",
        precomputed_mode_ready=precomputed_ready,
        full_pipeline_mode_ready=True,
        pyorps_engine_available=pyorps_ready,
        storage_ready=storage_ready,
        active_jobs=active_jobs,
        queued_jobs=queued_jobs,
        details={
            "cost_rasters_dir": str(cost_rasters),
            "regional_rasters_dir": str(regional_rasters),
            "regional_ready": regional_ready,
            "jobs_storage_dir": str(settings.jobs_dir),
            "sqlite_db_path": str(settings.sqlite_db_path),
        },
    )


@router.get("/capabilities", response_model=CapabilitiesResponse, summary="System and coverage capabilities")
async def get_capabilities() -> CapabilitiesResponse:
    """Returns the supported objectives, backend details, and geographic coverage limitations."""
    import pyorps

    return CapabilitiesResponse(
        app_version=settings.app_version,
        supported_objectives=[
            "shortest_distance",
            "lowest_construction_difficulty",
            "lowest_environmental_impact",
        ],
        routing_backend="pyorps_cython",
        pyorps_version=getattr(pyorps, "__version__", "0.4.0"),
        available_processing_modes=["precomputed", "precomputed_regional", "full_pipeline"],
        current_dataset_coverage={
            "region_name": "mandi_terminal_5x5km",
            "coverage_type": "local_test_corridor",
            "grid_dimensions": {"width": 579, "height": 565, "resolution_meters": 10.0},
            "bounds_utm43n": {
                "crs": "EPSG:32643",
                "left": 680000.0,
                "bottom": 3506530.0,
                "right": 685790.0,
                "top": 3512180.0,
            },
            "approximate_wgs84_bounds": {
                "min_lon": 76.90,
                "min_lat": 31.68,
                "max_lon": 76.96,
                "max_lat": 31.73,
            },
            "geographic_limitation": (
                "The current local precomputed dataset covers the Mandi 5.79km x 5.65km test area. "
                "New Delhi Railway Station is 340.97km south and lies outside the local raster extent. "
                "Requests with New Delhi destination under 'precomputed' mode will be rejected with an out-of-coverage error. "
                "Use 'precomputed_regional' or 'full_pipeline' mode for Mandi-to-Delhi regional corridor planning."
            ),
            "regional_coverage": {
                "region_name": "mandi_delhi_regional_corridor",
                "coverage_type": "regional_corridor_study_area",
                "grid_dimensions": {
                    "fine_width": 3450,
                    "fine_height": 13728,
                    "fine_resolution_meters": 30.0,
                    "coarse_width": 1035,
                    "coarse_height": 4114,
                    "coarse_resolution_meters": 100.0,
                },
                "bounds_utm43n": {
                    "crs": "EPSG:32643",
                    "left": 641670.0,
                    "bottom": 3131340.0,
                    "right": 745170.0,
                    "top": 3543180.0,
                },
                "approximate_wgs84_bounds": {
                    "min_lon": 76.38,
                    "min_lat": 28.28,
                    "max_lon": 77.58,
                    "max_lat": 32.01,
                },
                "dataset_readiness": "ready",
                "coverage_span_km": "411.8 km North-South x 103.5 km East-West",
                "terminals_covered": [
                    "Mandi Railway Station (HP)",
                    "New Delhi Railway Station (Delhi NCT)",
                ],
            },
        },
        engineering_disclaimer=settings.engineering_disclaimer,
    )

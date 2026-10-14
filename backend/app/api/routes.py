"""Route generation and job tracking API routes for GeoRoute AI."""

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from app.config import settings
from app.jobs.job_executor import CapacityExceededError
from app.schemas.api_schemas import (
    ErrorResponse,
    JobCreateResponse,
    JobResultResponse,
    JobStatusResponse,
    RouteGenerationRequest,
)
from georoute.routing.endpoint_validator import (
    EndpointValidationError,
    ImpassableEndpointError,
    OutOfCoverageError,
)

router = APIRouter(tags=["Route Planning & Jobs"])


@router.post(
    "/generate-routes",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a candidate corridor generation job",
    responses={
        422: {"model": ErrorResponse, "description": "Validation or out-of-coverage error"},
        503: {"model": ErrorResponse, "description": "Server capacity exceeded"},
    },
)
async def generate_routes(request_payload: RouteGenerationRequest, request: Request) -> JobCreateResponse:
    """Validates endpoints and queues a background railway corridor optimization job."""
    orchestrator = request.app.state.orchestrator
    job_store = request.app.state.job_store
    job_executor = request.app.state.job_executor

    # Synchronous pre-flight endpoint validation
    if request_payload.processing_mode == "precomputed":
        try:
            orchestrator.pre_validate_endpoints(
                source_coords=request_payload.source.as_tuple,
                target_coords=request_payload.destination.as_tuple,
                source_crs=request_payload.source_crs,
                target_crs=request_payload.target_crs,
                snap_to_valid=request_payload.snap_to_valid,
                max_snap_radius_m=request_payload.max_snap_radius_m,
                regional=False,
            )
        except OutOfCoverageError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "OUT_OF_COVERAGE",
                    "message": str(e),
                    "coverage_note": (
                        "Requested coordinate is outside the currently loaded Mandi study area (5.79km x 5.65km). "
                        "New Delhi Railway Station is 340.97km south and requires full regional corridor datasets."
                    ),
                },
            )
        except ImpassableEndpointError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "IMPASSABLE_ENDPOINT", "message": str(e)},
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "VALIDATION_FAILED", "message": f"Pre-flight validation error: {e}"},
            )
    elif request_payload.processing_mode in ("precomputed_regional", "full_pipeline"):
        try:
            orchestrator.pre_validate_endpoints(
                source_coords=request_payload.source.as_tuple,
                target_coords=request_payload.destination.as_tuple,
                source_crs=request_payload.source_crs,
                target_crs=request_payload.target_crs,
                snap_to_valid=request_payload.snap_to_valid,
                max_snap_radius_m=request_payload.max_snap_radius_m,
                regional=True,
                region_name=request_payload.region_name,
            )
        except OutOfCoverageError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "OUT_OF_COVERAGE",
                    "message": str(e),
                    "coverage_note": (
                        "Requested coordinate is outside the active regional corridor study areas. "
                        "Supported regional corridors: "
                        "1) Mandi–Delhi (UTM 43N: [641670..745170, 3131340..3543180]), "
                        "2) Kangra–Mandi (UTM 43N: [603480..699360, 3491070..3581190])."
                    ),
                },
            )
        except ImpassableEndpointError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "IMPASSABLE_ENDPOINT", "message": str(e)},
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "VALIDATION_FAILED", "message": f"Pre-flight regional validation error: {e}"},
            )

    # Generate unique job ID
    job_id = f"job_{uuid.uuid4().hex[:12]}"

    # Persist job record in SQLite
    req_dict = request_payload.model_dump()
    job_store.create_job(job_id=job_id, request_data=req_dict, processing_mode=request_payload.processing_mode)

    # Submit to thread-pool executor
    try:
        job_executor.submit_job(job_id)
    except CapacityExceededError as e:
        job_store.fail_job(job_id, error_message=str(e), stage="queued")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "CAPACITY_EXCEEDED", "message": str(e)},
        )

    now = datetime.now(timezone.utc).isoformat()
    return JobCreateResponse(
        job_id=job_id,
        status="queued",
        created_at=now,
        status_url=f"/api/v1/jobs/{job_id}",
        message="Route generation job accepted for asynchronous processing.",
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job processing status",
    responses={404: {"model": ErrorResponse, "description": "Job not found"}},
)
async def get_job_status(job_id: str, request: Request) -> JobStatusResponse:
    """Retrieves current processing state, stage, and diagnostics for a job."""
    job_store = request.app.state.job_store
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": f"No job found with ID '{job_id}'"},
        )

    # Compute elapsed seconds
    t_start = datetime.fromisoformat(job.created_at)
    t_now = datetime.now(timezone.utc)
    elapsed = max(0.0, (t_now - t_start).total_seconds())

    result_url = f"/api/v1/jobs/{job_id}/result" if job.status in ("completed", "partial_success") else None
    geojson_url = f"/api/v1/jobs/{job_id}/routes.geojson" if job.status in ("completed", "partial_success") else None

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        current_stage=job.current_stage,
        progress_percent=job.progress_percent,
        elapsed_seconds=round(elapsed, 2),
        processing_mode=job.processing_mode,
        created_at=job.created_at,
        updated_at=job.updated_at,
        source=job.source_data,
        destination=job.destination_data,
        warnings=job.warnings,
        errors=job.errors,
        result_url=result_url,
        geojson_url=geojson_url,
    )


@router.get(
    "/jobs/{job_id}/result",
    response_model=JobResultResponse,
    summary="Get complete structured routing results",
    responses={
        404: {"model": ErrorResponse, "description": "Job not found"},
        409: {"model": ErrorResponse, "description": "Job not completed yet"},
    },
)
async def get_job_result(job_id: str, request: Request) -> JobResultResponse:
    """Returns the finished multi-objective route manifest and diagnostic metrics."""
    job_store = request.app.state.job_store
    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": f"No job found with ID '{job_id}'"},
        )

    if job.status not in ("completed", "partial_success"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "JOB_NOT_READY",
                "message": f"Job '{job_id}' is in state '{job.status}' (stage: '{job.current_stage}') and has not produced results yet.",
            },
        )

    res = job.result_data or {}
    t_start = datetime.fromisoformat(job.created_at)
    t_end = datetime.fromisoformat(job.updated_at)
    elapsed = max(0.0, (t_end - t_start).total_seconds())

    return JobResultResponse(
        job_id=job.job_id,
        status=job.status,
        region_name=res.get("region_name", "unknown_region"),
        elapsed_seconds=round(elapsed, 2),
        source=res.get("source", job.source_data or {}),
        destination=res.get("destination", job.destination_data or {}),
        spatial_reference=res.get("spatial_reference", {}),
        num_routes=len(res.get("routes", [])),
        routes=res.get("routes", []),
        engineering_disclaimer=res.get("engineering_disclaimer", settings.engineering_disclaimer),
        warnings=job.warnings,
        errors=job.errors,
        artifacts=job.artifacts,
    )


@router.get(
    "/jobs/{job_id}/routes.geojson",
    summary="Download candidate corridors as standard RFC 7946 GeoJSON",
    responses={404: {"model": ErrorResponse, "description": "Routes GeoJSON not found"}},
)
async def get_routes_geojson(job_id: str) -> FileResponse:
    """Streams the WGS84 GeoJSON FeatureCollection for the job."""
    geojson_path = settings.jobs_dir / job_id / "routes.geojson"
    if not geojson_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ARTIFACT_NOT_FOUND", "message": f"GeoJSON routes artifact missing for job '{job_id}'"},
        )

    return FileResponse(
        path=str(geojson_path),
        media_type="application/geo+json",
        filename=f"{job_id}_routes.geojson",
    )


@router.post(
    "/jobs/{job_id}/cancel",
    summary="Cancel a queued or running job",
    responses={404: {"model": ErrorResponse, "description": "Job not found"}},
)
async def cancel_job(job_id: str, request: Request) -> Dict[str, Any]:
    """Requests best-effort cancellation of a processing job."""
    job_store = request.app.state.job_store
    job_executor = request.app.state.job_executor

    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": f"No job found with ID '{job_id}'"},
        )

    cancelled = job_executor.cancel_job(job_id)
    return {
        "job_id": job_id,
        "cancelled": cancelled,
        "status": "cancelled" if cancelled else job.status,
        "message": "Cancellation request registered." if cancelled else "Job is already in a terminal state.",
    }

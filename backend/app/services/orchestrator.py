"""Pipeline orchestrator bridging FastAPI background workers with GeoRoute domain modules."""

import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, Optional, Tuple

import affine
import rasterio

from app.config import settings
from app.jobs.job_store import JobStore
from georoute.routing.corridor_optimizer import CorridorOptimizer
from georoute.routing.endpoint_validator import (
    EndpointValidationError,
    EndpointValidator,
    ImpassableEndpointError,
    OutOfCoverageError,
)

logger = logging.getLogger("georoute.app.orchestrator")


class PipelineOrchestrator:
    """Coordinates execution of GeoRoute AI pipeline workflows for submitted jobs."""

    def __init__(self, job_store: JobStore):
        self.job_store = job_store
        self.cost_dir = settings.cost_dir
        self.features_dir = settings.features_dir
        self.jobs_dir = settings.jobs_dir

    def pre_validate_endpoints(
        self,
        source_coords: Tuple[float, float],
        target_coords: Tuple[float, float],
        source_crs: str = "EPSG:4326",
        target_crs: str = "EPSG:4326",
        snap_to_valid: bool = True,
        max_snap_radius_m: float = 500.0,
    ) -> Dict[str, Any]:
        """Performs fast synchronous validation of requested endpoints against current raster coverage.

        Raises:
            OutOfCoverageError: If either coordinate is outside current raster bounds.
            ImpassableEndpointError: If an endpoint is on an obstacle and cannot be snapped.
            FileNotFoundError: If required cost rasters are missing.
        """
        rasters_dir = self.cost_dir / "rasters"
        hard_mask_path = rasters_dir / "hard_constraint_mask.tif"
        valid_mask_path = rasters_dir / "valid_data_mask.tif"

        if not hard_mask_path.exists() or not valid_mask_path.exists():
            raise FileNotFoundError(f"Required cost masks missing in {rasters_dir}")

        with rasterio.open(hard_mask_path) as src:
            hard_mask = src.read(1)
            transform = src.transform
            crs = src.crs.to_string()
            shape = (src.height, src.width)
            bounds = src.bounds

        with rasterio.open(valid_mask_path) as src:
            valid_mask = src.read(1)

        validator = EndpointValidator(
            raster_crs=crs,
            transform=transform,
            grid_shape=shape,
            valid_data_mask=valid_mask,
            hard_constraint_mask=hard_mask,
            snap_to_valid=snap_to_valid,
            max_snap_radius_m=max_snap_radius_m,
        )

        res_src = validator.validate_and_resolve(source_coords, crs=source_crs, name="Source")
        res_dst = validator.validate_and_resolve(target_coords, crs=target_crs, name="Destination")

        return {
            "source": res_src.to_dict(),
            "destination": res_dst.to_dict(),
            "raster_bounds": {
                "left": bounds.left,
                "bottom": bounds.bottom,
                "right": bounds.right,
                "top": bounds.top,
                "crs": crs,
            },
        }

    def execute_job(self, job_id: str, is_cancelled_check: Optional[callable] = None) -> None:
        """Executes a queued routing job in the background."""
        logger.info(f"Starting execution of job '{job_id}'")
        job = self.job_store.get_job(job_id)
        if not job or job.status == "cancelled":
            logger.info(f"Job '{job_id}' was cancelled or not found before execution.")
            return

        req = job.request_data
        mode = req.get("processing_mode", "precomputed")
        source = req["source"]
        destination = req["destination"]
        src_coords = (source["longitude"], source["latitude"])
        dst_coords = (destination["longitude"], destination["latitude"])
        src_crs = req.get("source_crs", "EPSG:4326")
        dst_crs = req.get("target_crs", "EPSG:4326")
        snap_to_valid = req.get("snap_to_valid", True)
        max_snap_radius = req.get("max_snap_radius_m", 500.0)
        region_name = req.get("region_name", "mandi_corridor_study_area")
        backend = req.get("backend", "pyorps")

        job_out_dir = self.jobs_dir / job_id
        job_out_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Stage 1: Validation
            self.job_store.update_job_status(job_id, status="validating", current_stage="validating", progress_percent=10.0)
            if is_cancelled_check and is_cancelled_check():
                return

            validated_info = self.pre_validate_endpoints(
                source_coords=src_coords,
                target_coords=dst_coords,
                source_crs=src_crs,
                target_crs=dst_crs,
                snap_to_valid=snap_to_valid,
                max_snap_radius_m=max_snap_radius,
            )

            if mode == "precomputed":
                # Stage 2: Routing
                self.job_store.update_job_status(job_id, status="routing", current_stage="routing", progress_percent=40.0)
                if is_cancelled_check and is_cancelled_check():
                    return

                optimizer = CorridorOptimizer(
                    cost_dir=self.cost_dir,
                    features_dir=self.features_dir,
                    output_dir=job_out_dir,
                    pyorps_scale_factor=100.0,
                )

                # Execute multi-objective optimization
                manifest = optimizer.optimize_corridors(
                    source_coords=src_coords,
                    target_coords=dst_coords,
                    source_crs=src_crs,
                    target_crs=dst_crs,
                    source_name=source.get("name") or "Source",
                    target_name=destination.get("name") or "Destination",
                    region_name=region_name,
                    backend=backend,
                    connectivity=8,
                )

                # Stage 3: Validation and Result Assembly
                self.job_store.update_job_status(
                    job_id, status="validating_routes", current_stage="validating_routes", progress_percent=90.0
                )
                if is_cancelled_check and is_cancelled_check():
                    return

                results_path = job_out_dir / "route_results.json"
                geojson_path = job_out_dir / "routes.geojson"
                manifest_path = job_out_dir / "routing_manifest.json"

                result_data = {}
                if results_path.exists():
                    with open(results_path, encoding="utf-8") as f:
                        result_data = json.load(f)

                artifacts = {
                    "routes_geojson": str(geojson_path.relative_to(settings.base_data_dir.parent)),
                    "routing_manifest": str(manifest_path.relative_to(settings.base_data_dir.parent)),
                    "route_results": str(results_path.relative_to(settings.base_data_dir.parent)),
                }

                status = "completed" if manifest.pipeline_status == "SUCCESS" else (
                    "partial_success" if manifest.pipeline_status == "PARTIAL" else "failed"
                )

                self.job_store.complete_job(
                    job_id=job_id,
                    status=status,
                    result_data=result_data,
                    artifacts=artifacts,
                    warnings=manifest.warnings,
                    errors=manifest.errors,
                )
                logger.info(f"Job '{job_id}' completed successfully with status '{status}'")

            elif mode == "full_pipeline":
                # Full pipeline mode orchestration
                err_msg = (
                    "Full-pipeline mode for regional acquisition is not supported for custom ad-hoc AOIs yet. "
                    "Please use 'precomputed' mode for validated study areas."
                )
                self.job_store.fail_job(job_id, error_message=err_msg, stage="downloading")
                logger.warning(f"Job '{job_id}' failed: {err_msg}")

        except OutOfCoverageError as e:
            err_msg = f"Endpoint outside coverage: {e}"
            logger.warning(f"Job '{job_id}' out-of-coverage: {err_msg}")
            self.job_store.fail_job(job_id, error_message=err_msg, stage="validating")
        except ImpassableEndpointError as e:
            err_msg = f"Impassable endpoint: {e}"
            logger.warning(f"Job '{job_id}' impassable: {err_msg}")
            self.job_store.fail_job(job_id, error_message=err_msg, stage="validating")
        except Exception as e:
            err_msg = f"Internal pipeline execution error: {e}"
            logger.exception(f"Job '{job_id}' failed with unhandled exception")
            self.job_store.fail_job(job_id, error_message=err_msg, stage="routing")

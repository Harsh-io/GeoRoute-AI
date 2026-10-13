"""Master corridor optimization orchestrator for GeoRoute AI.

Executes the end-to-end Part 4 routing workflow:
1. Validates Part 3 input manifest and cost surface co-registration.
2. Validates and resolves geographic endpoints against the raster domain.
3. Performs three independent objective-specific route searches (PYORPS Cython / NetworkX).
4. Conducts rigorous independent feasibility and geometric checks on each candidate route.
5. Calculates detailed terrain slope profiles and thematic metrics.
6. Exports machine-readable GeoJSON, result summaries, and manifest schemas.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import affine
import geopandas as gpd
import numpy as np
import pyproj
import rasterio
from shapely.geometry import LineString

from georoute.routing.endpoint_validator import (
    EndpointValidationError,
    EndpointValidator,
    ResolvedEndpoint,
)
from georoute.routing.objective_router import (
    OBJECTIVE_CONFIGS,
    ObjectiveRouter,
    RoutingObjective,
)
from georoute.routing.route_metrics import RouteMetricsCalculator
from georoute.routing.route_validator import RouteValidator
from georoute.schemas.routing_manifest_schema import (
    CandidateRouteSummary,
    RoutingManifest,
)

logger = logging.getLogger("georoute.routing.optimizer")


class CorridorOptimizer:
    """Orchestrates multi-objective railway corridor optimization and verification."""

    def __init__(
        self,
        cost_dir: Union[str, Path] = "data/cost",
        features_dir: Optional[Union[str, Path]] = "data/features",
        output_dir: Union[str, Path] = "data/routes",
        pyorps_scale_factor: float = 100.0,
    ):
        """Initializes the corridor optimizer.

        Args:
            cost_dir: Directory containing Part 3 rasters and cost manifest.
            features_dir: Directory containing Part 2 features (for metrics).
            output_dir: Output directory for route GeoJSON and manifests.
            pyorps_scale_factor: Integer scaling factor for PYORPS Float32 quantization.
        """
        self.cost_dir = Path(cost_dir)
        self.rasters_dir = self.cost_dir / "rasters"
        self.features_dir = Path(features_dir) if features_dir else None
        self.output_dir = Path(output_dir)
        self.scale_factor = float(pyorps_scale_factor)

        self.objective_router = ObjectiveRouter(
            cost_rasters_dir=self.rasters_dir,
            pyorps_scale_factor=self.scale_factor,
        )

        # Preload spatial reference and masks
        self._load_reference_grid()
        self._load_metric_rasters()

    def _load_reference_grid(self) -> None:
        """Loads spatial reference and feasibility masks from Part 3 cost directory."""
        hard_mask_path = self.rasters_dir / "hard_constraint_mask.tif"
        if not hard_mask_path.exists():
            raise FileNotFoundError(f"Missing required hard constraint mask at: {hard_mask_path}")

        with rasterio.open(hard_mask_path) as src:
            self.hard_mask = src.read(1)
            self.transform = src.transform
            self.crs = src.crs.to_string()
            self.shape = (src.height, src.width)
            self.height, self.width = self.shape
            self.bounds = src.bounds
            self.cell_x_m = abs(float(src.transform.a))
            self.cell_y_m = abs(float(src.transform.e))

        valid_mask_path = self.rasters_dir / "valid_data_mask.tif"
        if valid_mask_path.exists():
            with rasterio.open(valid_mask_path) as src:
                self.valid_mask = src.read(1)
        else:
            self.valid_mask = np.ones(self.shape, dtype=np.uint8)

    def _load_metric_rasters(self) -> None:
        """Loads optional feature rasters for thematic route profiling."""
        slope_pct = None
        landcover = None
        water = None
        highway = None
        building = None

        if self.features_dir:
            feat_rasters = self.features_dir / "rasters"
            if feat_rasters.exists():
                s_path = feat_rasters / "slope_percent.tif"
                if s_path.exists():
                    with rasterio.open(s_path) as src:
                        slope_pct = src.read(1)

                lc_path = feat_rasters / "classified_landcover.tif"
                if lc_path.exists():
                    with rasterio.open(lc_path) as src:
                        landcover = src.read(1)

                w_path = feat_rasters / "water_mask.tif"
                if w_path.exists():
                    with rasterio.open(w_path) as src:
                        water = src.read(1)

                h_path = feat_rasters / "highway_mask.tif"
                if h_path.exists():
                    with rasterio.open(h_path) as src:
                        highway = src.read(1)

                b_path = feat_rasters / "building_mask.tif"
                if b_path.exists():
                    with rasterio.open(b_path) as src:
                        building = src.read(1)

        self.metrics_calc = RouteMetricsCalculator(
            slope_percent_raster=slope_pct,
            landcover_raster=landcover,
            water_mask=water,
            highway_mask=highway,
            building_mask=building,
        )

        self.validator = RouteValidator(
            grid_shape=self.shape,
            cell_size_x_m=self.cell_x_m,
            cell_size_y_m=self.cell_y_m,
            hard_constraint_mask=self.hard_mask,
            valid_data_mask=self.valid_mask,
        )

    def optimize_corridors(
        self,
        source_coords: Tuple[float, float],
        target_coords: Tuple[float, float],
        source_crs: str = "EPSG:4326",
        target_crs: str = "EPSG:4326",
        source_name: str = "Origin",
        target_name: str = "Destination",
        region_name: str = "mandi_terminal_5x5km",
        snap_to_valid: bool = False,
        max_snap_radius_m: float = 100.0,
        backend: str = "pyorps",
        connectivity: int = 8,
    ) -> RoutingManifest:
        """Executes three independent route optimizations between source and target.

        Args:
            source_coords: (lon, lat) or projected (x, y) coordinates.
            target_coords: (lon, lat) or projected (x, y) coordinates.
            source_crs: CRS of source coordinates (default EPSG:4326).
            target_crs: CRS of target coordinates (default EPSG:4326).
            source_name: Descriptive name for source endpoint.
            target_name: Descriptive name for target endpoint.
            region_name: Regional identifier.
            snap_to_valid: Whether to snap endpoints from blocked to nearest valid cell.
            max_snap_radius_m: Maximum search radius in metres for snapping.
            backend: 'pyorps' (default, Cython PathFinder) or 'networkx' (exact Float32 baseline).
            connectivity: 4 or 8 (default 8).

        Returns:
            RoutingManifest containing validation reports, route geometries, and metrics.
        """
        start_time = time.perf_counter()
        warnings: List[str] = []
        errors: List[str] = []

        # 1. Endpoint validation and resolution
        endpoint_val = EndpointValidator(
            raster_crs=self.crs,
            transform=self.transform,
            grid_shape=self.shape,
            valid_data_mask=self.valid_mask,
            hard_constraint_mask=self.hard_mask,
            snap_to_valid=snap_to_valid,
            max_snap_radius_m=max_snap_radius_m,
        )

        src_res: ResolvedEndpoint = endpoint_val.validate_and_resolve(
            source_coords, crs=source_crs, name=source_name
        )
        dst_res: ResolvedEndpoint = endpoint_val.validate_and_resolve(
            target_coords, crs=target_crs, name=target_name
        )

        if src_res.is_snapped:
            warnings.append(
                f"Source '{source_name}' snapped {src_res.snap_distance_m:.1f}m to cell ({src_res.row}, {src_res.col}) "
                f"due to: {src_res.snap_reason}."
            )
        if dst_res.is_snapped:
            warnings.append(
                f"Target '{target_name}' snapped {dst_res.snap_distance_m:.1f}m to cell ({dst_res.row}, {dst_res.col}) "
                f"due to: {dst_res.snap_reason}."
            )

        # 2. Execute three independent objective searches
        objectives = [
            RoutingObjective.SHORTEST_DISTANCE,
            RoutingObjective.LOWEST_CONSTRUCTION_DIFFICULTY,
            RoutingObjective.LOWEST_ENVIRONMENTAL_IMPACT,
        ]

        route_summaries: List[CandidateRouteSummary] = []
        raw_routes: List[Dict[str, Any]] = []

        for idx, obj in enumerate(objectives, start=1):
            route_id = f"route_{idx}_{obj.value}"
            try:
                r_dict = self.objective_router.route_single_objective(
                    objective=obj,
                    source_coords=src_res.projected_coords,
                    target_coords=dst_res.projected_coords,
                    source_cell=src_res.grid_cell,
                    target_cell=dst_res.grid_cell,
                    hard_constraint_mask=self.hard_mask,
                    valid_data_mask=self.valid_mask,
                    backend=backend,
                    connectivity=connectivity,
                )
                r_dict["route_id"] = route_id
                raw_routes.append(r_dict)

                # Load original friction raster for validation and exact cost recomputation
                cfg = OBJECTIVE_CONFIGS[obj]
                f_path = self.rasters_dir / cfg.friction_raster_name
                with rasterio.open(f_path) as s:
                    f_arr = s.read(1)

                val_report = self.validator.validate_route(r_dict, friction_surface=f_arr)
                if not val_report.is_valid:
                    errors.extend([f"[{route_id}] {e}" for e in val_report.errors])
                warnings.extend([f"[{route_id}] {w}" for w in val_report.warnings])

                metrics = self.metrics_calc.calculate_metrics(
                    route_id=route_id,
                    objective=obj.value,
                    path_cells=r_dict["path_cells"],
                    length_m=r_dict["physical_length_m"],
                    accumulated_cost=r_dict["accumulated_cost"],
                    cost_units=cfg.metric_units,
                    algorithm=r_dict["algorithm"],
                    execution_time_seconds=r_dict.get("execution_time_seconds", 0.0),
                )

                summary = CandidateRouteSummary(
                    route_id=route_id,
                    objective=obj.value,
                    status="preliminary_candidate_corridor",
                    length_m=metrics.length_m,
                    length_km=metrics.length_km,
                    accumulated_cost=metrics.accumulated_cost,
                    cost_units=metrics.cost_units,
                    num_nodes=metrics.cell_count,
                    algorithm=metrics.algorithm,
                    slope_profile=metrics.to_dict()["slope_profile"],
                    landcover_distribution_percent=metrics.landcover_breakdown,
                    infrastructure_crossings=metrics.crossings,
                    validation=val_report.to_dict(),
                )
                route_summaries.append(summary)

            except Exception as e:
                err_msg = f"Failed to compute route for objective '{obj.value}': {e}"
                logger.error(err_msg)
                errors.append(err_msg)

        elapsed = time.perf_counter() - start_time

        # Pipeline status
        if len(route_summaries) == 3 and not errors:
            status = "SUCCESS"
        elif len(route_summaries) > 0:
            status = "PARTIAL"
        else:
            status = "FAILED"

        manifest = RoutingManifest(
            schema_version="4.0.0",
            region_name=region_name,
            pipeline_status=status,
            elapsed_seconds=round(elapsed, 3),
            source=src_res.to_dict(),
            destination=dst_res.to_dict(),
            spatial_reference={
                "crs": self.crs,
                "resolution_meters": (self.cell_x_m, self.cell_y_m),
                "grid_shape": {"height": self.height, "width": self.width},
                "bounds": {
                    "left": self.bounds.left,
                    "bottom": self.bounds.bottom,
                    "right": self.bounds.right,
                    "top": self.bounds.top,
                },
            },
            num_routes=len(route_summaries),
            routes=route_summaries,
            warnings=warnings,
            errors=errors,
        )

        # 3. Export artifacts
        self._export_artifacts(manifest, raw_routes)

        return manifest

    def _export_artifacts(
        self,
        manifest: RoutingManifest,
        raw_routes: List[Dict[str, Any]],
    ) -> None:
        """Exports routes.geojson, route_results.json, and routing_manifest.json."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 1. Routing manifest
        manifest.to_json_file(self.output_dir / "routing_manifest.json")

        # 2. Detailed results summary
        results_path = self.output_dir / "route_results.json"
        with open(results_path, "w", encoding="utf-8") as f:
            json.dump(manifest.model_dump(mode="json"), f, indent=2)

        # 3. GeoJSON export
        if raw_routes:
            # Transform geometries to WGS84 for standard GeoJSON compliance
            wgs84 = pyproj.CRS.from_epsg(4326)
            proj_crs = pyproj.CRS.from_user_input(self.crs)
            transformer = pyproj.Transformer.from_crs(proj_crs, wgs84, always_xy=True)

            wgs84_geoms: List[LineString] = []
            records: List[Dict[str, Any]] = []

            for r, summary in zip(raw_routes, manifest.routes):
                geom = r["geometry"]
                wgs84_coords = [transformer.transform(x, y) for x, y in geom.coords]
                wgs84_line = LineString(wgs84_coords)
                wgs84_geoms.append(wgs84_line)

                records.append({
                    "route_id": summary.route_id,
                    "objective": summary.objective,
                    "status": summary.status,
                    "length_km": summary.length_km,
                    "accumulated_cost": summary.accumulated_cost,
                    "cost_units": summary.cost_units,
                    "mean_slope_pct": summary.slope_profile.get("mean_percent", 0.0),
                    "max_slope_pct": summary.slope_profile.get("max_percent", 0.0),
                    "algorithm": summary.algorithm,
                })

            gdf = gpd.GeoDataFrame(records, geometry=wgs84_geoms, crs="EPSG:4326")
            gdf.to_file(self.output_dir / "routes.geojson", driver="GeoJSON")

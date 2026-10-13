"""Objective-specific routing configurations and multi-objective execution.

Defines isolated search configurations for the three GeoRoute AI corridor objectives:
1. Shortest physical distance (unweighted, distance friction = 1.0).
2. Lowest estimated construction difficulty (slope power-law, land-cover, obstacle penalties).
3. Lowest environmental impact proxy (forest canopy NDVI-weighted, wetlands, water bodies).
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import affine
import numpy as np
import rasterio

from georoute.routing.grid_graph import build_grid_graph, solve_shortest_path
from georoute.routing.pyorps_adapter import InfeasibleRouteError, PyorpsAdapter, PyorpsRouteResult


class RoutingObjective(str, Enum):
    """The three core planning objectives for GeoRoute AI corridor routing."""
    SHORTEST_DISTANCE = "shortest_distance"
    LOWEST_CONSTRUCTION_DIFFICULTY = "lowest_construction_difficulty"
    LOWEST_ENVIRONMENTAL_IMPACT = "lowest_environmental_impact"


@dataclass
class ObjectiveConfig:
    """Configuration for a specific corridor routing objective."""
    objective: RoutingObjective
    friction_raster_name: str
    cost_raster_name: str
    metric_name: str
    metric_units: str
    description: str
    scale_factor: float = 100.0


OBJECTIVE_CONFIGS: Dict[RoutingObjective, ObjectiveConfig] = {
    RoutingObjective.SHORTEST_DISTANCE: ObjectiveConfig(
        objective=RoutingObjective.SHORTEST_DISTANCE,
        friction_raster_name="distance_friction.tif",
        cost_raster_name="distance_cost.tif",
        metric_name="physical_distance_m",
        metric_units="metres",
        description="Minimizes pure geographic travel distance while respecting shared hard constraints.",
        scale_factor=100.0,
    ),
    RoutingObjective.LOWEST_CONSTRUCTION_DIFFICULTY: ObjectiveConfig(
        objective=RoutingObjective.LOWEST_CONSTRUCTION_DIFFICULTY,
        friction_raster_name="construction_friction.tif",
        cost_raster_name="construction_cost.tif",
        metric_name="construction_difficulty_score",
        metric_units="dimensionless difficulty-weighted distance",
        description="Minimizes terrain slope penalties, land acquisition friction, and physical crossing penalties.",
        scale_factor=100.0,
    ),
    RoutingObjective.LOWEST_ENVIRONMENTAL_IMPACT: ObjectiveConfig(
        objective=RoutingObjective.LOWEST_ENVIRONMENTAL_IMPACT,
        friction_raster_name="environmental_friction.tif",
        cost_raster_name="environmental_cost.tif",
        metric_name="environmental_sensitivity_score",
        metric_units="dimensionless sensitivity-weighted distance",
        description="Minimizes traversal through dense forest canopy, wetlands, and aquatic bodies.",
        scale_factor=100.0,
    ),
}


class ObjectiveRouter:
    """Executes single-objective routing searches across candidate cost surfaces."""

    def __init__(
        self,
        cost_rasters_dir: Union[str, Path],
        pyorps_scale_factor: float = 100.0,
    ):
        """Initializes the objective router.

        Args:
            cost_rasters_dir: Directory containing Part 3 cost and friction rasters.
            pyorps_scale_factor: Scale factor used to quantize Float32 friction to UInt16.
        """
        self.rasters_dir = Path(cost_rasters_dir)
        self.scale_factor = float(pyorps_scale_factor)
        self.pyorps_adapter = PyorpsAdapter(scale_factor=self.scale_factor)

    def load_raster_data(self, filename: str) -> Tuple[np.ndarray, affine.Affine, str, Tuple[int, int]]:
        """Loads a raster array, transform, CRS, and grid shape."""
        path = self.rasters_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Required cost raster missing at: {path}")

        with rasterio.open(path) as src:
            arr = src.read(1)
            transform = src.transform
            crs = src.crs.to_string()
            shape = (src.height, src.width)
        return arr, transform, crs, shape

    def route_single_objective(
        self,
        objective: RoutingObjective,
        source_coords: Tuple[float, float],
        target_coords: Tuple[float, float],
        source_cell: Tuple[int, int],
        target_cell: Tuple[int, int],
        hard_constraint_mask: Optional[np.ndarray] = None,
        valid_data_mask: Optional[np.ndarray] = None,
        backend: str = "pyorps",
        connectivity: int = 8,
    ) -> Dict[str, Any]:
        """Executes a single objective route search.

        Args:
            objective: One of the three RoutingObjective values.
            source_coords: (x, y) projected coordinates of source in raster CRS.
            target_coords: (x, y) projected coordinates of target in raster CRS.
            source_cell: (row, col) grid cell of source.
            target_cell: (row, col) grid cell of target.
            hard_constraint_mask: Optional 2D uint8 mask (1=blocked).
            valid_data_mask: Optional 2D uint8 mask (0=unknown/nodata).
            backend: 'pyorps' (default) or 'networkx'.
            connectivity: 4 or 8 (used if backend is networkx).

        Returns:
            Dictionary containing route geometry, cells, physical length, and accumulated objective cost.
        """
        cfg = OBJECTIVE_CONFIGS[objective]

        # Load the objective's friction raster
        friction_arr, transform, crs, shape = self.load_raster_data(cfg.friction_raster_name)

        if backend.lower() == "pyorps":
            # Quantize for PYORPS
            quantized = self.pyorps_adapter.quantize_friction_to_uint16(
                friction_arr, hard_constraint_mask=hard_constraint_mask, valid_data_mask=valid_data_mask
            )

            res = self.pyorps_adapter.find_route(
                quantized_raster=quantized,
                source_coords=source_coords,
                target_coords=target_coords,
                transform=transform,
                crs=crs,
                original_friction_raster=friction_arr,
            )

            return {
                "objective": objective.value,
                "metric_name": cfg.metric_name,
                "metric_units": cfg.metric_units,
                "path_cells": res.path_cells,
                "path_coords": res.path_coords,
                "geometry": res.geometry,
                "physical_length_m": res.total_length_m,
                "accumulated_cost": res.recomputed_cost,
                "pyorps_reported_cost": res.pyorps_reported_cost,
                "algorithm": res.algorithm,
                "backend": "pyorps",
                "execution_time_seconds": res.execution_time_seconds,
            }
        else:
            # NetworkX exact Float32 baseline
            G = build_grid_graph(
                friction_arr,
                cell_size_x_m=abs(float(transform.a)),
                cell_size_y_m=abs(float(transform.e)),
                hard_constraint_mask=hard_constraint_mask,
                valid_data_mask=valid_data_mask,
                connectivity=connectivity,
            )

            res_nx = solve_shortest_path(
                G,
                source_cell=source_cell,
                target_cell=target_cell,
                transform=transform,
                algorithm="dijkstra",
            )

            return {
                "objective": objective.value,
                "metric_name": cfg.metric_name,
                "metric_units": cfg.metric_units,
                "path_cells": res_nx.path_cells,
                "path_coords": res_nx.path_coords,
                "geometry": res_nx.geometry,
                "physical_length_m": res_nx.physical_length_m,
                "accumulated_cost": res_nx.accumulated_cost,
                "pyorps_reported_cost": res_nx.accumulated_cost,
                "algorithm": "networkx_dijkstra",
                "backend": "networkx",
                "execution_time_seconds": 0.0,
            }

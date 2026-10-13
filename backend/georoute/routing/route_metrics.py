"""Route metrics calculation and terrain profiling for GeoRoute AI.

Extracts:
1. Physical route length (m and km).
2. Sampled terrain slope profile (mean, max, min, standard deviation).
3. Land-cover distribution along the route alignment.
4. Infrastructure and obstacle crossing counts (water, highway, buildings).
5. Computational timing and node counts.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np


@dataclass
class RouteMetrics:
    """Detailed physical and modeled metrics for a candidate railway corridor."""
    route_id: str
    objective: str
    length_m: float
    length_km: float
    accumulated_cost: float
    cost_units: str
    cell_count: int
    mean_slope_percent: float
    max_slope_percent: float
    min_slope_percent: float
    std_slope_percent: float
    landcover_breakdown: Dict[str, float] = field(default_factory=dict)
    crossings: Dict[str, int] = field(default_factory=dict)
    algorithm: str = "pyorps_cython"
    execution_time_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_id": self.route_id,
            "objective": self.objective,
            "length_m": round(self.length_m, 2),
            "length_km": round(self.length_km, 3),
            "accumulated_cost": round(self.accumulated_cost, 2),
            "cost_units": self.cost_units,
            "cell_count": self.cell_count,
            "slope_profile": {
                "mean_percent": round(self.mean_slope_percent, 2),
                "max_percent": round(self.max_slope_percent, 2),
                "min_percent": round(self.min_slope_percent, 2),
                "std_percent": round(self.std_slope_percent, 2),
                "sampling_note": "Sampled at 10m raster cell centers along route path",
            },
            "landcover_distribution_percent": {
                k: round(v, 2) for k, v in self.landcover_breakdown.items()
            },
            "infrastructure_crossings": self.crossings,
            "routing_metadata": {
                "algorithm": self.algorithm,
                "execution_time_seconds": round(self.execution_time_seconds, 4),
            },
        }


class RouteMetricsCalculator:
    """Calculates thematic and physical profile metrics for route cell sequences."""

    LANDCOVER_NAMES: Dict[int, str] = {
        10: "Tree cover / Forest",
        20: "Shrubland",
        30: "Grassland",
        40: "Cropland",
        50: "Built-up / Urban",
        60: "Bare / sparse vegetation",
        70: "Snow and ice",
        80: "Permanent water bodies",
        90: "Herbaceous wetland",
        95: "Mangroves",
        100: "Moss and lichen",
    }

    def __init__(
        self,
        slope_percent_raster: Optional[np.ndarray] = None,
        landcover_raster: Optional[np.ndarray] = None,
        water_mask: Optional[np.ndarray] = None,
        highway_mask: Optional[np.ndarray] = None,
        building_mask: Optional[np.ndarray] = None,
    ):
        """Initializes metrics calculator with optional feature raster stacks."""
        self.slope = slope_percent_raster[0] if slope_percent_raster is not None and slope_percent_raster.ndim == 3 else slope_percent_raster
        self.lc = landcover_raster[0] if landcover_raster is not None and landcover_raster.ndim == 3 else landcover_raster
        self.water = water_mask[0] if water_mask is not None and water_mask.ndim == 3 else water_mask
        self.highway = highway_mask[0] if highway_mask is not None and highway_mask.ndim == 3 else highway_mask
        self.building = building_mask[0] if building_mask is not None and building_mask.ndim == 3 else building_mask

    def calculate_metrics(
        self,
        route_id: str,
        objective: str,
        path_cells: List[Tuple[int, int]],
        length_m: float,
        accumulated_cost: float,
        cost_units: str,
        algorithm: str = "pyorps_cython",
        execution_time_seconds: float = 0.0,
    ) -> RouteMetrics:
        """Computes comprehensive profile metrics for a route."""
        n_cells = len(path_cells)
        if n_cells == 0:
            return RouteMetrics(
                route_id=route_id,
                objective=objective,
                length_m=0.0,
                length_km=0.0,
                accumulated_cost=accumulated_cost,
                cost_units=cost_units,
                cell_count=0,
                mean_slope_percent=0.0,
                max_slope_percent=0.0,
                min_slope_percent=0.0,
                std_slope_percent=0.0,
            )

        # 1. Slope profile
        slopes: List[float] = []
        if self.slope is not None:
            for r, c in path_cells:
                if 0 <= r < self.slope.shape[0] and 0 <= c < self.slope.shape[1]:
                    val = float(self.slope[r, c])
                    if val >= 0.0 and val != -9999.0 and not np.isnan(val):
                        slopes.append(val)

        if slopes:
            mean_slope = float(np.mean(slopes))
            max_slope = float(np.max(slopes))
            min_slope = float(np.min(slopes))
            std_slope = float(np.std(slopes))
        else:
            mean_slope = max_slope = min_slope = std_slope = 0.0

        # 2. Land-cover distribution
        lc_counts: Dict[str, int] = {}
        if self.lc is not None:
            for r, c in path_cells:
                if 0 <= r < self.lc.shape[0] and 0 <= c < self.lc.shape[1]:
                    class_id = int(self.lc[r, c])
                    name = self.LANDCOVER_NAMES.get(class_id, f"Class {class_id}")
                    lc_counts[name] = lc_counts.get(name, 0) + 1

        total_sampled_lc = sum(lc_counts.values()) or 1
        lc_breakdown = {k: (v / total_sampled_lc) * 100.0 for k, v in lc_counts.items()}

        # 3. Infrastructure crossings
        crossings: Dict[str, int] = {
            "water_crossings": 0,
            "highway_crossings": 0,
            "building_conflicts": 0,
        }
        for r, c in path_cells:
            if self.water is not None and 0 <= r < self.water.shape[0] and 0 <= c < self.water.shape[1]:
                if self.water[r, c] == 1:
                    crossings["water_crossings"] += 1
            if self.highway is not None and 0 <= r < self.highway.shape[0] and 0 <= c < self.highway.shape[1]:
                if self.highway[r, c] == 1:
                    crossings["highway_crossings"] += 1
            if self.building is not None and 0 <= r < self.building.shape[0] and 0 <= c < self.building.shape[1]:
                if self.building[r, c] == 1:
                    crossings["building_conflicts"] += 1

        return RouteMetrics(
            route_id=route_id,
            objective=objective,
            length_m=float(length_m),
            length_km=float(length_m) / 1000.0,
            accumulated_cost=float(accumulated_cost),
            cost_units=cost_units,
            cell_count=n_cells,
            mean_slope_percent=mean_slope,
            max_slope_percent=max_slope,
            min_slope_percent=min_slope,
            std_slope_percent=std_slope,
            landcover_breakdown=lc_breakdown,
            crossings=crossings,
            algorithm=algorithm,
            execution_time_seconds=execution_time_seconds,
        )

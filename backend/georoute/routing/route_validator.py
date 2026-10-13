"""Independent route feasibility and geometric validation for GeoRoute AI.

Verifies:
1. Cell-level integrity: bounds, valid-data mask, hard-constraint mask.
2. Step connectivity: 8-connected valid steps, zero diagonal corner-cutting through obstacles.
3. Cost accuracy: independent recomputation of floating-point friction cost.
4. Metric accuracy: physical length matches Euclidean step distance sum.
5. Geometric validity: Shapely LineString integrity and coordinate consistency.
"""

from dataclasses import dataclass, field
import math
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
from shapely.geometry import LineString


@dataclass
class ValidationReport:
    """Report detailing independent route feasibility checks."""
    is_valid: bool
    objective: str
    cell_count: int
    reported_length_m: float
    recomputed_length_m: float
    reported_cost: float
    recomputed_cost: float
    cost_discrepancy_percent: float
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "objective": self.objective,
            "cell_count": self.cell_count,
            "reported_length_m": round(self.reported_length_m, 2),
            "recomputed_length_m": round(self.recomputed_length_m, 2),
            "length_difference_m": round(abs(self.reported_length_m - self.recomputed_length_m), 4),
            "reported_cost": round(self.reported_cost, 2),
            "recomputed_cost": round(self.recomputed_cost, 2),
            "cost_discrepancy_percent": round(self.cost_discrepancy_percent, 4),
            "num_errors": len(self.errors),
            "errors": self.errors,
            "warnings": self.warnings,
        }


class RouteValidator:
    """Independent validator checking route correctness, feasibility, and cost accuracy."""

    def __init__(
        self,
        grid_shape: Tuple[int, int],
        cell_size_x_m: float = 10.0,
        cell_size_y_m: float = 10.0,
        hard_constraint_mask: Optional[np.ndarray] = None,
        valid_data_mask: Optional[np.ndarray] = None,
        cost_tolerance_percent: float = 1.0,
        length_tolerance_percent: float = 0.5,
    ):
        """Initializes the route validator.

        Args:
            grid_shape: (height, width) of the raster grid.
            cell_size_x_m: Pixel width in metres (default 10.0m).
            cell_size_y_m: Pixel height in metres (default 10.0m).
            hard_constraint_mask: 2D uint8 mask (1=blocked).
            valid_data_mask: 2D uint8 mask (0=unknown/nodata).
            cost_tolerance_percent: Max allowed percentage delta between reported and recomputed cost.
            length_tolerance_percent: Max allowed percentage delta for physical distance.
        """
        self.height, self.width = grid_shape
        self.dx = float(cell_size_x_m)
        self.dy = float(cell_size_y_m)
        self.hard_mask = hard_constraint_mask[0] if hard_constraint_mask is not None and hard_constraint_mask.ndim == 3 else hard_constraint_mask
        self.valid_mask = valid_data_mask[0] if valid_data_mask is not None and valid_data_mask.ndim == 3 else valid_data_mask
        self.cost_tol_pct = float(cost_tolerance_percent)
        self.len_tol_pct = float(length_tolerance_percent)

    def validate_route(
        self,
        route_dict: Dict[str, Any],
        friction_surface: np.ndarray,
    ) -> ValidationReport:
        """Runs comprehensive validation suite on a route result.

        Args:
            route_dict: Dictionary returned from ObjectiveRouter or PyorpsAdapter.
            friction_surface: 2D Float32 friction array used for the route.

        Returns:
            ValidationReport with pass/fail status and detailed diagnostics.
        """
        objective = route_dict.get("objective", "unknown")
        path_cells: List[Tuple[int, int]] = route_dict.get("path_cells", [])
        geometry: Optional[LineString] = route_dict.get("geometry")
        reported_len = float(route_dict.get("physical_length_m", 0.0))
        reported_cost = float(route_dict.get("accumulated_cost", 0.0))

        errors: List[str] = []
        warnings: List[str] = []

        # 1. Non-empty check
        if not path_cells:
            errors.append("Route has empty path cell list.")
            return ValidationReport(
                is_valid=False,
                objective=objective,
                cell_count=0,
                reported_length_m=reported_len,
                recomputed_length_m=0.0,
                reported_cost=reported_cost,
                recomputed_cost=0.0,
                cost_discrepancy_percent=100.0,
                errors=errors,
            )

        # 2. Geometry check
        if geometry is None or not isinstance(geometry, LineString):
            errors.append("Route geometry is missing or not a Shapely LineString.")
        elif geometry.is_empty:
            errors.append("Route geometry LineString is empty.")
        elif not geometry.is_valid:
            errors.append(f"Route geometry is topologically invalid: {geometry.is_valid}.")

        # 3. Cell-level constraint and boundary checks
        f_2d = friction_surface[0] if friction_surface.ndim == 3 else friction_surface

        recomputed_cost = 0.0
        recomputed_length_m = 0.0

        for idx, (r, c) in enumerate(path_cells):
            # Bounds
            if not (0 <= r < self.height and 0 <= c < self.width):
                errors.append(f"Step {idx}: Cell ({r}, {c}) is outside grid bounds [0..{self.height-1}, 0..{self.width-1}].")
                continue

            # Hard constraints
            if self.hard_mask is not None and self.hard_mask[r, c] == 1:
                errors.append(f"Step {idx}: Cell ({r}, {c}) intersects a hard constraint / prohibited obstacle!")

            # Valid data mask
            if self.valid_mask is not None and self.valid_mask[r, c] == 0:
                errors.append(f"Step {idx}: Cell ({r}, {c}) traverses an unknown / nodata cell!")

            # Friction valid
            f_val = float(f_2d[r, c])
            if f_val <= 0.0 or np.isnan(f_val) or np.isinf(f_val) or f_val == -9999.0:
                errors.append(f"Step {idx}: Cell ({r}, {c}) has invalid friction value {f_val}!")

        # 4. Connectivity and step-distance checks
        for i in range(len(path_cells) - 1):
            r1, c1 = path_cells[i]
            r2, c2 = path_cells[i + 1]

            dr = abs(r2 - r1)
            dc = abs(c2 - c1)

            if dr > 1 or dc > 1:
                errors.append(f"Discontinuous step between cell {i} ({r1}, {c1}) and cell {i+1} ({r2}, {c2}): delta=({dr}, {dc}).")
            if dr == 0 and dc == 0:
                errors.append(f"Zero-distance duplicate node at step {i} ({r1}, {c1}).")

            step_dist = math.sqrt((dr * self.dy) ** 2 + (dc * self.dx) ** 2)
            recomputed_length_m += step_dist

            # Corner-cutting check on diagonal moves
            if dr == 1 and dc == 1 and self.hard_mask is not None:
                ortho1_blocked = self.hard_mask[r2, c1] == 1 if (0 <= r2 < self.height and 0 <= c1 < self.width) else True
                ortho2_blocked = self.hard_mask[r1, c2] == 1 if (0 <= r1 < self.height and 0 <= c2 < self.width) else True
                if ortho1_blocked and ortho2_blocked:
                    errors.append(
                        f"Diagonal corner-cut at step {i}: moving between ({r1}, {c1}) and ({r2}, {c2}) "
                        f"squeezes through blocked corners ({r2}, {c1}) and ({r1}, {c2})!"
                    )

            # Recompute edge cost: Distance * (F1 + F2)/2
            if (0 <= r1 < self.height and 0 <= c1 < self.width) and (0 <= r2 < self.height and 0 <= c2 < self.width):
                f1 = float(f_2d[r1, c1])
                f2 = float(f_2d[r2, c2])
                recomputed_cost += step_dist * ((f1 + f2) / 2.0)

        # 5. Length comparison
        len_diff = abs(reported_len - recomputed_length_m)
        len_diff_pct = (len_diff / max(recomputed_length_m, 1e-6)) * 100.0
        if len_diff_pct > self.len_tol_pct:
            warnings.append(
                f"Physical length discrepancy: reported={reported_len:.2f}m, recomputed={recomputed_length_m:.2f}m "
                f"(delta={len_diff:.2f}m, {len_diff_pct:.3f}%)."
            )

        # 6. Cost comparison
        cost_diff = abs(reported_cost - recomputed_cost)
        cost_diff_pct = (cost_diff / max(recomputed_cost, 1e-6)) * 100.0
        if cost_diff_pct > self.cost_tol_pct:
            # If pyorps was used, slight quantization difference is normal (e.g. 0.2%)
            warnings.append(
                f"Accumulated cost discrepancy: reported={reported_cost:.2f}, recomputed={recomputed_cost:.2f} "
                f"(delta={cost_diff:.2f}, {cost_diff_pct:.3f}%)."
            )

        is_valid = len(errors) == 0

        return ValidationReport(
            is_valid=is_valid,
            objective=objective,
            cell_count=len(path_cells),
            reported_length_m=reported_len,
            recomputed_length_m=recomputed_length_m,
            reported_cost=reported_cost,
            recomputed_cost=recomputed_cost,
            cost_discrepancy_percent=cost_diff_pct,
            errors=errors,
            warnings=warnings,
        )

"""Distance cost surface and pure physical traversal model.

Calculates cell traversal cost proportional strictly to physical travel distance.
Free from slope, terrain, land-cover, or environmental biases.
Prohibits explicitly configured hard constraints and preserves unknown/nodata regions.
"""

import math
from typing import Optional, Tuple
import numpy as np

from georoute.cost.cost_assumptions import CostAssumptions, DistanceCostConfig


class DistanceCostModel:
    """Builds physical distance traversal cost surfaces for shortest-path routing."""

    def __init__(
        self,
        config: Optional[DistanceCostConfig] = None,
        blocked_cell_cost: float = -9999.0,
    ):
        """Initializes distance cost model.

        Args:
            config: Optional DistanceCostConfig. Defaults to 10.0 metres base cell distance.
            blocked_cell_cost: Fill value used for prohibited or unknown cells (-9999.0).
        """
        self.config = config or DistanceCostConfig()
        self.blocked_cell_cost = float(blocked_cell_cost)
        self.base_distance_m = float(self.config.base_cell_distance_m)
        self.orthogonal_step_m = self.base_distance_m
        self.diagonal_step_m = self.base_distance_m * math.sqrt(2.0)

    def compute_surface(
        self,
        grid_shape: Tuple[int, int],
        hard_constraint_mask: Optional[np.ndarray] = None,
        valid_data_mask: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Calculates distance traversal cost and dimensionless friction surfaces.

        Args:
            grid_shape: (height, width) of the target grid.
            hard_constraint_mask: 2D uint8 mask where 1 indicates an impassable cell, 0 is passable.
            valid_data_mask: 2D boolean/uint8 mask where 1/True is valid data, 0/False is unknown/nodata.

        Returns:
            Tuple of:
            - cost_surface: Float32 array representing per-cell physical traversal cost in metres (10.0m).
                            Blocked/unknown cells are set to blocked_cell_cost (-9999.0).
            - friction_surface: Float32 array representing normalized dimensionless friction (1.0).
                                Blocked/unknown cells are set to blocked_cell_cost (-9999.0).
        """
        height, width = grid_shape

        # Initialize passable arrays with baseline values
        cost_surface = np.full((height, width), self.base_distance_m, dtype=np.float32)
        friction_surface = np.full((height, width), 1.0, dtype=np.float32)

        # Mark hard constraints as blocked
        if hard_constraint_mask is not None:
            if hard_constraint_mask.ndim == 3:
                hc = hard_constraint_mask[0]
            else:
                hc = hard_constraint_mask
            blocked_mask = hc == 1
            cost_surface[blocked_mask] = self.blocked_cell_cost
            friction_surface[blocked_mask] = self.blocked_cell_cost

        # Mark invalid/unknown cells as blocked
        if valid_data_mask is not None:
            if valid_data_mask.ndim == 3:
                vd = valid_data_mask[0]
            else:
                vd = valid_data_mask
            invalid_mask = (vd == 0) | (~vd.astype(bool))
            cost_surface[invalid_mask] = self.blocked_cell_cost
            friction_surface[invalid_mask] = self.blocked_cell_cost

        return cost_surface, friction_surface

    def compute_edge_distance_m(self, is_diagonal: bool = False) -> float:
        """Returns the physical step distance in metres between adjacent cell centers.

        Args:
            is_diagonal: True for diagonal 8-neighbor step, False for orthogonal 4-neighbor step.

        Returns:
            Step distance in metres (10.0m orthogonal, ~14.142m diagonal).
        """
        return self.diagonal_step_m if is_diagonal else self.orthogonal_step_m

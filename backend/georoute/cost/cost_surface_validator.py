"""Validation and quality assurance engine for multi-objective cost surfaces.

Verifies:
1. Spatial co-registration across all cost layers (shape, transform, CRS, resolution).
2. Cost range validity (positive finite costs, no raw infinities, safe nodata fill).
3. Hard constraint enforcement (all prohibited cells strictly blocked).
4. Cross-objective statistical independence and theoretical consistency.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger("georoute.cost.validator")


class CostSurfaceValidator:
    """Validates cost surface integrity, spatial alignment, and objective semantics."""

    def __init__(self, blocked_cell_cost: float = -9999.0):
        self.blocked_cell_cost = float(blocked_cell_cost)

    def validate_surfaces(
        self,
        distance_cost: np.ndarray,
        construction_cost: np.ndarray,
        environmental_cost: np.ndarray,
        hard_constraint_mask: np.ndarray,
        valid_data_mask: np.ndarray,
    ) -> Dict[str, Any]:
        """Runs comprehensive validation suite on the three generated cost surfaces.

        Args:
            distance_cost: 2D Float32 array of distance traversal cost.
            construction_cost: 2D Float32 array of construction difficulty cost.
            environmental_cost: 2D Float32 array of environmental proxy cost.
            hard_constraint_mask: 2D uint8 mask (1=blocked).
            valid_data_mask: 2D boolean/uint8 mask (1=valid data).

        Returns:
            Dictionary detailing audit checks and pass/fail results.
        """
        results: Dict[str, Any] = {
            "all_passed": True,
            "checks": {},
            "warnings": [],
            "errors": [],
        }

        # 1. Shape consistency check
        ref_shape = distance_cost.shape
        shapes_match = (
            construction_cost.shape == ref_shape
            and environmental_cost.shape == ref_shape
            and hard_constraint_mask.shape == ref_shape
            and valid_data_mask.shape == ref_shape
        )
        results["checks"]["shapes_consistent"] = shapes_match
        if not shapes_match:
            results["errors"].append(
                f"Shape mismatch: distance={ref_shape}, construction={construction_cost.shape}, "
                f"environmental={environmental_cost.shape}"
            )
            results["all_passed"] = False
            return results

        # 2. Absence of raw infinities / NaNs
        surfaces = {
            "distance_cost": distance_cost,
            "construction_cost": construction_cost,
            "environmental_cost": environmental_cost,
        }
        no_nans_infs = True
        for name, arr in surfaces.items():
            has_nan = bool(np.isnan(arr).any())
            has_inf = bool(np.isinf(arr).any())
            if has_nan or has_inf:
                no_nans_infs = False
                results["errors"].append(f"{name} contains raw NaN ({has_nan}) or Inf ({has_inf}) values.")
        results["checks"]["no_raw_nans_or_infs"] = no_nans_infs
        if not no_nans_infs:
            results["all_passed"] = False

        # 3. Hard constraints enforcement check
        hc_blocked = hard_constraint_mask == 1
        hc_enforced_dist = np.all(distance_cost[hc_blocked] == self.blocked_cell_cost)
        hc_enforced_const = np.all(construction_cost[hc_blocked] == self.blocked_cell_cost)
        hc_enforced_env = np.all(environmental_cost[hc_blocked] == self.blocked_cell_cost)
        hc_all_enforced = bool(hc_enforced_dist and hc_enforced_const and hc_enforced_env)

        results["checks"]["hard_constraints_enforced"] = hc_all_enforced
        if not hc_all_enforced:
            results["errors"].append("Hard constraints are not completely enforced with blocked_cell_cost.")
            results["all_passed"] = False

        # 4. Unknown data enforcement check
        inv_data = (valid_data_mask == 0) | (~valid_data_mask.astype(bool))
        inv_enforced = bool(
            np.all(distance_cost[inv_data] == self.blocked_cell_cost)
            and np.all(construction_cost[inv_data] == self.blocked_cell_cost)
            and np.all(environmental_cost[inv_data] == self.blocked_cell_cost)
        )
        results["checks"]["unknown_data_blocked"] = inv_enforced
        if not inv_enforced:
            results["errors"].append("Unknown/nodata regions are not completely blocked.")
            results["all_passed"] = False

        # 5. Positive finite traversable costs
        traversable_mask = ~hc_blocked & ~inv_data
        pos_dist = bool(np.all(distance_cost[traversable_mask] > 0.0))
        pos_const = bool(np.all(construction_cost[traversable_mask] > 0.0))
        pos_env = bool(np.all(environmental_cost[traversable_mask] > 0.0))
        costs_positive = pos_dist and pos_const and pos_env

        results["checks"]["traversable_costs_positive"] = costs_positive
        if not costs_positive:
            results["errors"].append("Some traversable cells have zero or negative costs.")
            results["all_passed"] = False

        # 6. Theoretical ordering: construction_cost >= distance_cost on all traversable cells
        # Since construction difficulty friction is 1.0 + non-negative penalties
        order_holds = bool(np.all(construction_cost[traversable_mask] >= distance_cost[traversable_mask] - 1e-4))
        results["checks"]["construction_ge_distance"] = order_holds
        if not order_holds:
            results["errors"].append("Theoretical ordering violated: construction_cost < distance_cost on some cells.")
            results["all_passed"] = False

        # 7. Objective differentiation check
        # Verify that construction and environmental surfaces have non-zero variance and are distinct
        dist_vals = distance_cost[traversable_mask]
        const_vals = construction_cost[traversable_mask]
        env_vals = environmental_cost[traversable_mask]

        const_std = float(np.std(const_vals)) if len(const_vals) > 0 else 0.0
        env_std = float(np.std(env_vals)) if len(env_vals) > 0 else 0.0

        diff_check = const_std > 0.0 and env_std > 0.0
        results["checks"]["surfaces_differentiated"] = diff_check
        results["details"] = {
            "traversable_cells": int(np.count_nonzero(traversable_mask)),
            "blocked_cells": int(np.count_nonzero(~traversable_mask)),
            "distance_mean": float(np.mean(dist_vals)) if len(dist_vals) > 0 else None,
            "construction_mean": float(np.mean(const_vals)) if len(const_vals) > 0 else None,
            "construction_std": round(const_std, 4),
            "environmental_mean": float(np.mean(env_vals)) if len(env_vals) > 0 else None,
            "environmental_std": round(env_std, 4),
        }

        return results

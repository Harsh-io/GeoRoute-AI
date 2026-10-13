"""Environmental-impact proxy cost and ecological sensitivity model.

Combines statutory protected areas, forest canopy cover (optionally weighted by NDVI),
wetland habitats, and natural aquatic bodies into an environmental sensitivity score.

Strictly separates statutory legal exclusions from generic forest cover.
Explicitly labeled as an environmental sensitivity proxy, NOT an official
Environmental Impact Assessment (EIA) or regulatory biodiversity permit.
"""

from typing import Dict, Optional, Tuple, Union
import numpy as np

from georoute.cost.cost_assumptions import (
    CostAssumptions,
    DistanceCostConfig,
    EnvironmentalSensitivityConfig,
)


class EnvironmentalCostModel:
    """Constructs environmental-impact proxy cost and ecological sensitivity surfaces."""

    def __init__(
        self,
        distance_config: Optional[DistanceCostConfig] = None,
        environmental_config: Optional[EnvironmentalSensitivityConfig] = None,
        blocked_cell_cost: float = -9999.0,
    ):
        """Initializes the environmental-impact proxy model.

        Args:
            distance_config: Base physical distance settings.
            environmental_config: Environmental sensitivity parameters.
            blocked_cell_cost: Fill value used for prohibited or unknown cells (-9999.0).
        """
        self.distance = distance_config or DistanceCostConfig()
        self.env = environmental_config or EnvironmentalSensitivityConfig()
        self.blocked_cell_cost = float(blocked_cell_cost)
        self.base_distance_m = float(self.distance.base_cell_distance_m)

    @classmethod
    def from_assumptions(
        cls,
        assumptions: CostAssumptions,
        blocked_cell_cost: Optional[float] = None,
    ) -> "EnvironmentalCostModel":
        """Factory constructor instantiating from root CostAssumptions."""
        bc = blocked_cell_cost if blocked_cell_cost is not None else assumptions.constraints.blocked_cell_cost
        return cls(
            distance_config=assumptions.distance,
            environmental_config=assumptions.environmental,
            blocked_cell_cost=bc,
        )

    def compute_forest_sensitivity(
        self,
        forest_mask: np.ndarray,
        ndvi_arr: Optional[np.ndarray] = None,
        nodata_ndvi: float = -9999.0,
    ) -> np.ndarray:
        """Computes ecological sensitivity penalty for forest / tree canopy cover.

        If use_ndvi_canopy_weighting is True and valid NDVI is provided,
        scales sensitivity dynamically with canopy density: P = base_penalty * (1.0 + max(0, NDVI)).

        Args:
            forest_mask: 2D binary uint8 mask (1=tree cover / forest).
            ndvi_arr: Optional 2D float32 Sentinel-2 NDVI array.
            nodata_ndvi: NDVI raster nodata fill value.

        Returns:
            2D Float32 array of forest sensitivity penalties.
        """
        fm = forest_mask[0] if forest_mask.ndim == 3 else forest_mask
        penalty = np.zeros(fm.shape, dtype=np.float32)

        is_forest = fm == 1
        if not np.any(is_forest):
            return penalty

        base_p = float(self.env.forest_base_penalty)

        if self.env.use_ndvi_canopy_weighting and ndvi_arr is not None:
            ndvi_2d = ndvi_arr[0] if ndvi_arr.ndim == 3 else ndvi_arr
            valid_ndvi = (ndvi_2d != nodata_ndvi) & ~np.isnan(ndvi_2d) & (ndvi_2d >= -1.0) & (ndvi_2d <= 1.0)

            # Canopy multiplier: base * (1.0 + max(0, NDVI))
            canopy_mult = np.ones(fm.shape, dtype=np.float32)
            canopy_mult[valid_ndvi] = 1.0 + np.maximum(0.0, ndvi_2d[valid_ndvi])

            penalty[is_forest] = base_p * canopy_mult[is_forest]
        else:
            penalty[is_forest] = base_p

        return penalty

    def compute_surface(
        self,
        forest_mask: np.ndarray,
        wetland_mask: Optional[np.ndarray] = None,
        water_mask: Optional[np.ndarray] = None,
        protected_area_mask: Optional[np.ndarray] = None,
        ndvi_arr: Optional[np.ndarray] = None,
        hard_constraint_mask: Optional[np.ndarray] = None,
        valid_data_mask: Optional[np.ndarray] = None,
        nodata_ndvi: float = -9999.0,
    ) -> Tuple[np.ndarray, np.ndarray, Dict[str, np.ndarray]]:
        """Calculates environmental proxy traversal cost, friction, and sensitivity layers.

        Formula:
            Friction = 1.0 + w_forest*P_forest + w_wetland*P_wetland + w_water*P_water + [w_pa*P_pa if soft]
            Cost = BaseDistance_m * Friction

        Args:
            forest_mask: 2D binary uint8 tree cover mask (1=forest).
            wetland_mask: Optional 2D binary uint8 wetland mask (1=wetland).
            water_mask: Optional 2D binary uint8 aquatic body mask (1=water).
            protected_area_mask: Optional 2D binary uint8 statutory protected area mask (1=protected).
            ndvi_arr: Optional 2D Float32 Sentinel-2 NDVI array.
            hard_constraint_mask: Optional 2D binary uint8 hard constraint mask (1=blocked).
            valid_data_mask: Optional 2D boolean/uint8 valid data mask (0=unknown/blocked).
            nodata_ndvi: NDVI raster nodata fill value.

        Returns:
            Tuple of:
            - cost_surface: 2D Float32 array of environmental proxy traversal cost.
            - friction_surface: 2D Float32 array of dimensionless friction multiplier (>= 1.0).
            - intermediate_sensitivities: Dict containing Float32 sensitivity rasters:
              ('forest_sensitivity', 'wetland_sensitivity', 'water_sensitivity', 'protected_area_penalty').
        """
        shape = forest_mask.shape[-2:]
        height, width = shape

        # 1. Forest canopy sensitivity
        p_forest = self.compute_forest_sensitivity(forest_mask, ndvi_arr=ndvi_arr, nodata_ndvi=nodata_ndvi)

        # 2. Wetland sensitivity
        p_wetland = np.zeros(shape, dtype=np.float32)
        if wetland_mask is not None:
            wm = wetland_mask[0] if wetland_mask.ndim == 3 else wetland_mask
            p_wetland[wm == 1] = float(self.env.wetland_penalty)

        # 3. Aquatic body sensitivity
        p_water = np.zeros(shape, dtype=np.float32)
        if water_mask is not None:
            wat_m = water_mask[0] if water_mask.ndim == 3 else water_mask
            p_water[wat_m == 1] = float(self.env.water_penalty)

        # 4. Protected areas (soft mode penalty if policy is SOFT_PENALTY)
        p_pa = np.zeros(shape, dtype=np.float32)
        pa_is_hard_exclusion = self.env.protected_area_policy == "HARD_EXCLUSION"

        if protected_area_mask is not None:
            pam = protected_area_mask[0] if protected_area_mask.ndim == 3 else protected_area_mask
            if not pa_is_hard_exclusion:
                p_pa[pam == 1] = float(self.env.protected_area_penalty)

        # Calculate dimensionless friction factor (baseline is 1.0)
        friction = (
            1.0
            + (self.env.forest_weight * p_forest)
            + (self.env.wetland_weight * p_wetland)
            + (self.env.water_weight * p_water)
            + p_pa
        ).astype(np.float32)

        # Traversal cost = base_distance * friction
        cost = (self.base_distance_m * friction).astype(np.float32)

        # 5. Apply hard constraints and unknown-data blocking
        blocked_mask = np.zeros(shape, dtype=bool)

        # Shared hard constraints
        if hard_constraint_mask is not None:
            hcm = hard_constraint_mask[0] if hard_constraint_mask.ndim == 3 else hard_constraint_mask
            blocked_mask |= (hcm == 1)

        # Statutory protected area hard exclusion
        if pa_is_hard_exclusion and protected_area_mask is not None:
            pam = protected_area_mask[0] if protected_area_mask.ndim == 3 else protected_area_mask
            blocked_mask |= (pam == 1)

        # Master validity mask
        if valid_data_mask is not None:
            vdm = valid_data_mask[0] if valid_data_mask.ndim == 3 else valid_data_mask
            blocked_mask |= ((vdm == 0) | (~vdm.astype(bool)))

        cost[blocked_mask] = self.blocked_cell_cost
        friction[blocked_mask] = self.blocked_cell_cost

        intermediate_sensitivities = {
            "forest_sensitivity": p_forest,
            "wetland_sensitivity": p_wetland,
            "water_sensitivity": p_water,
            "protected_area_penalty": p_pa,
        }

        return cost, friction, intermediate_sensitivities

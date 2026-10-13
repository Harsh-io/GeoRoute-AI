"""Estimated construction-difficulty traversal cost model.

Combines terrain slope, land cover, building conflicts, water crossings,
and highway infrastructure crossings into an engineering difficulty score.

Explicitly labeled as a dimensionless relative difficulty score,
NOT actual monetary expenditure (rupees/crores).
"""

from typing import Dict, Optional, Tuple, Union
import numpy as np

from georoute.cost.cost_assumptions import (
    CostAssumptions,
    DistanceCostConfig,
    LandCoverPenaltyConfig,
    ObstaclePenaltyConfig,
    SlopePenaltyConfig,
)


class ConstructionCostModel:
    """Constructs estimated construction-difficulty cost and friction surfaces."""

    def __init__(
        self,
        distance_config: Optional[DistanceCostConfig] = None,
        slope_config: Optional[SlopePenaltyConfig] = None,
        landcover_config: Optional[LandCoverPenaltyConfig] = None,
        obstacle_config: Optional[ObstaclePenaltyConfig] = None,
        blocked_cell_cost: float = -9999.0,
    ):
        """Initializes the construction-difficulty model.

        Args:
            distance_config: Base distance settings.
            slope_config: Nonlinear slope penalty parameters.
            landcover_config: Land-cover class difficulty weights.
            obstacle_config: Building, water, and highway crossing settings.
            blocked_cell_cost: Fill value used for prohibited or unknown cells (-9999.0).
        """
        self.distance = distance_config or DistanceCostConfig()
        self.slope = slope_config or SlopePenaltyConfig()
        self.landcover = landcover_config or LandCoverPenaltyConfig()
        self.obstacles = obstacle_config or ObstaclePenaltyConfig()
        self.blocked_cell_cost = float(blocked_cell_cost)
        self.base_distance_m = float(self.distance.base_cell_distance_m)

    @classmethod
    def from_assumptions(
        cls,
        assumptions: CostAssumptions,
        blocked_cell_cost: Optional[float] = None,
    ) -> "ConstructionCostModel":
        """Factory constructor instantiating from root CostAssumptions."""
        bc = blocked_cell_cost if blocked_cell_cost is not None else assumptions.constraints.blocked_cell_cost
        return cls(
            distance_config=assumptions.distance,
            slope_config=assumptions.slope,
            landcover_config=assumptions.landcover,
            obstacle_config=assumptions.obstacles,
            blocked_cell_cost=bc,
        )

    def compute_slope_penalty(
        self,
        slope_arr: np.ndarray,
        nodata: float = -9999.0,
    ) -> np.ndarray:
        """Computes nonlinear normalized slope penalty: P_slope = (slope / slope_ref)^power.

        Args:
            slope_arr: 2D array of slopes (percent or degrees matching config).
            nodata: Nodata fill value in slope raster.

        Returns:
            2D Float32 array of slope penalties (0.0 on flat land, rising nonlinearly).
        """
        if slope_arr.ndim == 3:
            s_2d = slope_arr[0]
        else:
            s_2d = slope_arr

        # Identify valid positive slope cells
        valid_mask = (s_2d != nodata) & ~np.isnan(s_2d) & ~np.isinf(s_2d) & (s_2d >= 0.0)

        penalty = np.zeros(s_2d.shape, dtype=np.float32)

        # Vectorized power-law scaling
        norm_slope = np.zeros(s_2d.shape, dtype=np.float32)
        norm_slope[valid_mask] = s_2d[valid_mask] / self.slope.slope_reference

        penalty[valid_mask] = np.power(norm_slope[valid_mask], self.slope.power)

        # Optional penalty cap
        if self.slope.max_penalty_cap is not None and self.slope.max_penalty_cap > 0:
            penalty[valid_mask] = np.minimum(penalty[valid_mask], self.slope.max_penalty_cap)

        return penalty

    def compute_landcover_penalty(
        self,
        lc_arr: np.ndarray,
        nodata: float = 0.0,
    ) -> np.ndarray:
        """Maps discrete ESA WorldCover classes to relative land-cover clearing and acquisition penalties.

        Args:
            lc_arr: 2D array of discrete land cover classes.
            nodata: Discrete nodata fill value.

        Returns:
            2D Float32 array of relative land cover penalties.
        """
        if lc_arr.ndim == 3:
            lc_2d = lc_arr[0]
        else:
            lc_2d = lc_arr

        penalty = np.zeros(lc_2d.shape, dtype=np.float32)

        for class_id, class_penalty in self.landcover.class_penalties.items():
            match_mask = lc_2d == class_id
            penalty[match_mask] = float(class_penalty)

        return penalty

    def compute_surface(
        self,
        slope_arr: np.ndarray,
        lc_arr: np.ndarray,
        building_mask: Optional[np.ndarray] = None,
        water_mask: Optional[np.ndarray] = None,
        highway_mask: Optional[np.ndarray] = None,
        hard_constraint_mask: Optional[np.ndarray] = None,
        valid_data_mask: Optional[np.ndarray] = None,
        nodata_slope: float = -9999.0,
        nodata_lc: float = 0.0,
    ) -> Tuple[np.ndarray, np.ndarray, Dict[str, np.ndarray]]:
        """Calculates construction difficulty traversal cost, friction, and intermediate penalty layers.

        Formula:
            Friction = 1.0 + w_s*P_slope + w_l*P_lc + w_b*P_bldg + w_w*P_water + w_h*P_highway
            Cost = BaseDistance_m * Friction

        Args:
            slope_arr: 2D terrain slope array.
            lc_arr: 2D ESA WorldCover discrete class array.
            building_mask: Optional 2D binary uint8 building footprint mask (1=building).
            water_mask: Optional 2D binary uint8 water body / waterway mask (1=water).
            highway_mask: Optional 2D binary uint8 highway crossing mask (1=highway).
            hard_constraint_mask: Optional 2D binary uint8 hard constraint mask (1=blocked).
            valid_data_mask: Optional 2D boolean/uint8 valid data mask (0=unknown/blocked).
            nodata_slope: Slope raster nodata fill value.
            nodata_lc: Land cover raster nodata fill value.

        Returns:
            Tuple of:
            - cost_surface: 2D Float32 array of traversal difficulty cost.
            - friction_surface: 2D Float32 array of dimensionless friction multiplier (>= 1.0).
            - intermediate_penalties: Dict containing individual Float32 penalty rasters:
              ('slope_penalty', 'landcover_penalty', 'building_penalty', 'water_crossing_penalty', 'highway_crossing_penalty').
        """
        shape = slope_arr.shape[-2:]
        height, width = shape

        # 1. Slope penalty
        p_slope = self.compute_slope_penalty(slope_arr, nodata=nodata_slope)

        # 2. Land-cover penalty
        p_lc = self.compute_landcover_penalty(lc_arr, nodata=nodata_lc)

        # 3. Building conflict penalty
        p_bldg = np.zeros(shape, dtype=np.float32)
        if building_mask is not None:
            bm = building_mask[0] if building_mask.ndim == 3 else building_mask
            p_bldg[bm == 1] = float(self.obstacles.building_penalty)

        # 4. Water crossing penalty
        p_water = np.zeros(shape, dtype=np.float32)
        if water_mask is not None:
            wm = water_mask[0] if water_mask.ndim == 3 else water_mask
            p_water[wm == 1] = float(self.obstacles.water_crossing_penalty)

        # 5. Highway crossing penalty
        p_highway = np.zeros(shape, dtype=np.float32)
        if highway_mask is not None:
            hm = highway_mask[0] if highway_mask.ndim == 3 else highway_mask
            p_highway[hm == 1] = float(self.obstacles.highway_crossing_penalty)

        # Weighted combination for dimensionless friction factor
        # Base friction factor is 1.0 (free unimpeded standard flat ground)
        friction = (
            1.0
            + (self.slope.weight * p_slope)
            + (self.landcover.weight * p_lc)
            + (self.obstacles.building_weight * p_bldg)
            + (self.obstacles.water_crossing_weight * p_water)
            + (self.obstacles.highway_crossing_weight * p_highway)
        ).astype(np.float32)

        # Traversal cost = base_cell_distance * friction
        cost = (self.base_distance_m * friction).astype(np.float32)

        # 6. Apply hard constraints and unknown-data blocking
        blocked_mask = np.zeros(shape, dtype=bool)

        # Hard exclusions from constraint mask
        if hard_constraint_mask is not None:
            hcm = hard_constraint_mask[0] if hard_constraint_mask.ndim == 3 else hard_constraint_mask
            blocked_mask |= (hcm == 1)

        # Hard exclusions from buildings if building_hard_exclusion is configured
        if self.obstacles.building_hard_exclusion and building_mask is not None:
            bm = building_mask[0] if building_mask.ndim == 3 else building_mask
            blocked_mask |= (bm == 1)

        # Slope nodata / invalid
        s_2d = slope_arr[0] if slope_arr.ndim == 3 else slope_arr
        invalid_slope = (s_2d == nodata_slope) | np.isnan(s_2d) | np.isinf(s_2d) | (s_2d < 0.0)
        blocked_mask |= invalid_slope

        # Master validity mask
        if valid_data_mask is not None:
            vdm = valid_data_mask[0] if valid_data_mask.ndim == 3 else valid_data_mask
            blocked_mask |= ((vdm == 0) | (~vdm.astype(bool)))

        cost[blocked_mask] = self.blocked_cell_cost
        friction[blocked_mask] = self.blocked_cell_cost

        intermediate_penalties = {
            "slope_penalty": p_slope,
            "landcover_penalty": p_lc,
            "building_penalty": p_bldg,
            "water_crossing_penalty": p_water,
            "highway_crossing_penalty": p_highway,
        }

        return cost, friction, intermediate_penalties

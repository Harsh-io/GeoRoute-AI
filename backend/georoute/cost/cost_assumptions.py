"""Pydantic configuration models and validators for multi-objective cost surfaces.

Defines transparent, configurable assumptions for:
1. Pure distance cost modeling.
2. Estimated construction-difficulty scoring (slope, land cover, buildings, water, highways).
3. Environmental-impact proxy scoring (statutory protected areas, forest canopy, wetlands).
4. Hard-constraint exclusions and unknown-data policies.
"""

from pathlib import Path
from typing import Any, Dict, Optional, Union
import json
from pydantic import BaseModel, Field, field_validator
import yaml


class DistanceCostConfig(BaseModel):
    """Configuration for physical distance traversal cost."""
    base_cell_distance_m: float = Field(
        default=10.0,
        gt=0.0,
        description="Physical metric distance represented by an orthogonal move across a cell (metres).",
    )
    unit: str = Field(
        default="metres",
        description="Physical unit of distance measurement.",
    )


class SlopePenaltyConfig(BaseModel):
    """Configuration for terrain gradient penalty in construction difficulty modeling."""
    slope_source: str = Field(
        default="slope_percent",
        description="Source slope raster: 'slope_percent' or 'slope_degrees'.",
    )
    slope_reference: float = Field(
        default=20.0,
        gt=0.0,
        description="Reference gradient (e.g. 20.0% gradient) where penalty equals 1.0.",
    )
    power: float = Field(
        default=2.0,
        ge=1.0,
        description="Nonlinear scaling exponent for slope penalty (P_slope = (slope / slope_ref)^power).",
    )
    weight: float = Field(
        default=2.0,
        ge=0.0,
        description="Relative weight (w_s) of slope in construction difficulty formulation.",
    )
    max_penalty_cap: Optional[float] = Field(
        default=None,
        description="Optional upper threshold to cap extreme slope penalties. None leaves slopes uncapped.",
    )

    @field_validator("slope_source")
    @classmethod
    def validate_slope_source(cls, v: str) -> str:
        valid_sources = {"slope_percent", "slope_degrees"}
        if v.lower() not in valid_sources:
            raise ValueError(f"slope_source must be one of {valid_sources}, got '{v}'")
        return v.lower()


class LandCoverPenaltyConfig(BaseModel):
    """Configuration for land-cover clearing and land acquisition difficulty weights."""
    class_penalties: Dict[int, float] = Field(
        default_factory=lambda: {
            10: 2.5,   # Tree cover (Forest clearing & compensatory afforestation)
            20: 0.3,   # Shrubland
            30: 0.2,   # Grassland
            40: 1.0,   # Cropland (Agricultural land acquisition compensation)
            50: 8.0,   # Built-up (Urban resettlement & property acquisition friction)
            60: 0.1,   # Bare / sparse vegetation (Favorable acquisition, potential slope review)
            70: 15.0,  # Snow and ice (Extreme alpine construction difficulty)
            80: 10.0,  # Permanent water bodies (Bridge / viaduct foundation engineering)
            90: 6.0,   # Herbaceous wetland (Soft subsoil, deep piling required)
            95: 8.0,   # Mangroves (Ecological and estuarine foundation challenge)
            100: 2.0,  # Moss and lichen
        },
        description="Provisional relative difficulty weights for discrete ESA WorldCover classes.",
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Relative weight (w_l) of land cover in construction difficulty formulation.",
    )

    @field_validator("class_penalties")
    @classmethod
    def validate_penalties(cls, v: Dict[int, float]) -> Dict[int, float]:
        for cid, penalty in v.items():
            if penalty < 0.0:
                raise ValueError(f"Land cover penalty for class {cid} cannot be negative: {penalty}")
        return v


class ObstaclePenaltyConfig(BaseModel):
    """Configuration for physical obstacle avoidance and infrastructure crossings."""
    building_penalty: float = Field(
        default=10.0,
        ge=0.0,
        description="Penalty multiplier when traversing building footprints in soft penalty mode.",
    )
    building_weight: float = Field(
        default=1.5,
        ge=0.0,
        description="Relative weight (w_b) for building footprint friction.",
    )
    building_hard_exclusion: bool = Field(
        default=False,
        description="If True, building footprints are absolute hard exclusions (impassable).",
    )
    water_crossing_penalty: float = Field(
        default=5.0,
        ge=0.0,
        description="Structural bridging difficulty penalty when traversing water bodies or streams.",
    )
    water_crossing_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Relative weight (w_w) for water body crossings.",
    )
    highway_crossing_penalty: float = Field(
        default=2.0,
        ge=0.0,
        description="Grade-separated intersection penalty (ROB / RUB) when crossing existing highway corridors.",
    )
    highway_crossing_weight: float = Field(
        default=0.5,
        ge=0.0,
        description="Relative weight (w_h) for highway crossings.",
    )


class EnvironmentalSensitivityConfig(BaseModel):
    """Configuration for environmental impact proxy scoring."""
    protected_area_policy: str = Field(
        default="HARD_EXCLUSION",
        description="Policy for statutory protected areas: 'HARD_EXCLUSION' or 'SOFT_PENALTY'.",
    )
    protected_area_penalty: float = Field(
        default=50.0,
        ge=0.0,
        description="Severe penalty multiplier if protected_area_policy is configured as 'SOFT_PENALTY'.",
    )
    forest_base_penalty: float = Field(
        default=2.0,
        ge=0.0,
        description="Base ecological sensitivity penalty for forest / tree canopy cover.",
    )
    forest_weight: float = Field(
        default=2.0,
        ge=0.0,
        description="Relative weight (w_forest) of forest canopy in environmental proxy.",
    )
    use_ndvi_canopy_weighting: bool = Field(
        default=True,
        description="If True, scales forest sensitivity dynamically with Sentinel-2 NDVI canopy density.",
    )
    wetland_penalty: float = Field(
        default=5.0,
        ge=0.0,
        description="Ecological sensitivity penalty for herbaceous wetlands and mangroves.",
    )
    wetland_weight: float = Field(
        default=2.5,
        ge=0.0,
        description="Relative weight (w_wetland) for wetland habitats.",
    )
    water_penalty: float = Field(
        default=4.0,
        ge=0.0,
        description="Ecological sensitivity penalty for natural aquatic ecosystems.",
    )
    water_weight: float = Field(
        default=1.5,
        ge=0.0,
        description="Relative weight (w_water) for water bodies.",
    )

    @field_validator("protected_area_policy")
    @classmethod
    def validate_pa_policy(cls, v: str) -> str:
        valid_policies = {"HARD_EXCLUSION", "SOFT_PENALTY"}
        if v.upper() not in valid_policies:
            raise ValueError(f"protected_area_policy must be one of {valid_policies}, got '{v}'")
        return v.upper()


class ConstraintPolicyConfig(BaseModel):
    """Configuration for hard constraints and unknown-data handling."""
    treat_nodata_as_blocked: bool = Field(
        default=True,
        description="If True, missing/unknown data cells cannot be traversed (conservative policy).",
    )
    blocked_cell_cost: float = Field(
        default=-9999.0,
        description="Standard nodata / blocked fill value stored in cost surfaces.",
    )
    hard_constraint_binary_value: int = Field(
        default=1,
        description="Binary pixel value indicating a prohibited hard-constraint cell (1=blocked).",
    )


class CostAssumptions(BaseModel):
    """Root configuration model uniting all cost objectives, penalties, and policies."""
    model_version: str = Field(
        default="1.0.0",
        description="Version identifier for the cost assumptions model.",
    )
    distance: DistanceCostConfig = Field(default_factory=DistanceCostConfig)
    slope: SlopePenaltyConfig = Field(default_factory=SlopePenaltyConfig)
    landcover: LandCoverPenaltyConfig = Field(default_factory=LandCoverPenaltyConfig)
    obstacles: ObstaclePenaltyConfig = Field(default_factory=ObstaclePenaltyConfig)
    environmental: EnvironmentalSensitivityConfig = Field(default_factory=EnvironmentalSensitivityConfig)
    constraints: ConstraintPolicyConfig = Field(default_factory=ConstraintPolicyConfig)

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "CostAssumptions":
        """Loads and validates cost assumptions from a YAML configuration file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Cost assumptions YAML not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**(data or {}))

    def to_yaml(self, path: Union[str, Path]) -> None:
        """Serializes cost assumptions to a YAML file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)

    def to_json(self, path: Union[str, Path]) -> None:
        """Serializes cost assumptions to a JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, indent=2)

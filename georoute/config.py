"""Configuration models and loader for GeoRoute AI pipeline."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import os
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from shapely.geometry import box, Polygon


class BBoxConfig(BaseModel):
    """Bounding box in WGS84 decimal degrees."""
    min_lon: float = Field(..., description="Western longitude boundary [-180, 180]")
    min_lat: float = Field(..., description="Southern latitude boundary [-90, 90]")
    max_lon: float = Field(..., description="Eastern longitude boundary [-180, 180]")
    max_lat: float = Field(..., description="Northern latitude boundary [-90, 90]")

    @field_validator("min_lon", "max_lon")
    @classmethod
    def validate_longitude(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError(f"Longitude {v} must be in range [-180, 180].")
        return v

    @field_validator("min_lat", "max_lat")
    @classmethod
    def validate_latitude(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError(f"Latitude {v} must be in range [-90, 90].")
        return v

    def model_post_init(self, __context: Any) -> None:
        if self.min_lon >= self.max_lon:
            raise ValueError(f"min_lon ({self.min_lon}) must be less than max_lon ({self.max_lon}).")
        if self.min_lat >= self.max_lat:
            raise ValueError(f"min_lat ({self.min_lat}) must be less than max_lat ({self.max_lat}).")

    @property
    def as_tuple(self) -> Tuple[float, float, float, float]:
        """Returns bounds as (min_lon, min_lat, max_lon, max_lat)."""
        return (self.min_lon, self.min_lat, self.max_lon, self.max_lat)

    @property
    def as_polygon(self) -> Polygon:
        """Returns bounds as a Shapely Polygon."""
        return box(self.min_lon, self.min_lat, self.max_lon, self.max_lat)


class TemporalConfig(BaseModel):
    """Temporal range for satellite imagery queries."""
    start_date: str = Field(..., description="Start date in ISO format YYYY-MM-DD")
    end_date: str = Field(..., description="End date in ISO format YYYY-MM-DD")

    @property
    def date_range_string(self) -> str:
        """Returns STAC datetime query string format 'start/end'."""
        return f"{self.start_date}/{self.end_date}"


class OpticalConfig(BaseModel):
    """Configuration for Sentinel-2 optical imagery ingestion."""
    collection: str = "sentinel-2-l2a"
    max_cloud_cover_percent: float = 5.0
    target_resolution_meters: float = 10.0
    bands: List[str] = Field(default_factory=lambda: ["B04", "B03", "B02", "B08"])


class ElevationConfig(BaseModel):
    """Configuration for Digital Elevation Model ingestion."""
    collection: str = "cop-dem-glo-30"
    asset_name: str = "data"


class STACConfig(BaseModel):
    """STAC catalog endpoints and collection settings."""
    api_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    use_planetary_computer: bool = True
    optical: OpticalConfig = Field(default_factory=OpticalConfig)
    elevation: ElevationConfig = Field(default_factory=ElevationConfig)


class VectorLayerConfig(BaseModel):
    """Individual OSM layer query configuration."""
    tags: Dict[str, Any]
    description: str = ""


class VectorConfig(BaseModel):
    """Vector data query settings for OSMnx."""
    layers: Dict[str, VectorLayerConfig]
    timeout_seconds: int = 60
    max_retries: int = 3


class COGConfig(BaseModel):
    """Cloud-Optimized GeoTIFF export profile."""
    block_size: int = 256
    compression: str = "deflate"
    overview_levels: List[int] = Field(default_factory=lambda: [2, 4, 8, 16])


class ExportConfig(BaseModel):
    """Export directories and format options."""
    output_dir: Path = Path("./data/processed")
    vector_format: str = "geojson"
    cog: COGConfig = Field(default_factory=COGConfig)


class ProcessingConfig(BaseModel):
    """Geometric and resampling configurations."""
    dem_resampling_method: str = "bilinear"
    target_pixel_size_meters: float = 10.0


class PipelineConfig(BaseModel):
    """Master configuration class for GeoRoute AI Part 1."""
    region_name: str = "default_aoi"
    bbox: BBoxConfig
    temporal: TemporalConfig
    stac: STACConfig
    vector: VectorConfig
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)

    @classmethod
    def from_yaml(
        cls,
        yaml_path: str | Path,
        env_file: Optional[str | Path] = None,
    ) -> "PipelineConfig":
        """Loads configuration from a YAML file and merges environment variables.

        Args:
            yaml_path: Path to config.yaml.
            env_file: Optional path to .env file.

        Returns:
            Instantiated PipelineConfig instance.
        """
        # Load environment variables
        if env_file:
            load_dotenv(dotenv_path=env_file)
        else:
            load_dotenv()

        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Configuration file not found at: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Flatten nested region configuration into master schema
        region = data.get("region", {})
        bbox_data = region.get("bbox", {})

        config_dict = {
            "region_name": region.get("name", "unnamed_region"),
            "bbox": bbox_data,
            "temporal": data.get("temporal", {}),
            "stac": data.get("stac", {}),
            "vector": data.get("vector", {}),
            "processing": data.get("processing", {}),
            "export": data.get("export", {}),
        }

        # Override data output dir if specified in environment
        env_data_dir = os.getenv("DATA_DIR")
        if env_data_dir:
            config_dict.setdefault("export", {})["output_dir"] = Path(env_data_dir) / "processed"

        return cls(**config_dict)

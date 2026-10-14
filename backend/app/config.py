"""Configuration settings for the GeoRoute AI FastAPI application."""

import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Validated runtime configuration for the GeoRoute AI API."""

    app_name: str = "GeoRoute AI API"
    app_version: str = "1.0.0"
    environment: str = Field(default_factory=lambda: os.getenv("GEOROUTE_ENV", "development"))
    api_prefix: str = "/api/v1"

    # Server settings
    host: str = Field(default_factory=lambda: os.getenv("GEOROUTE_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("GEOROUTE_PORT", "8000")))
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            origin.strip()
            for origin in os.getenv(
                "GEOROUTE_CORS_ORIGINS",
                "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        ]
    )

    # Base storage directories
    base_data_dir: Path = Field(default_factory=lambda: Path(os.getenv("GEOROUTE_DATA_DIR", "data")))
    cost_dir: Path = Field(default_factory=lambda: Path(os.getenv("GEOROUTE_COST_DIR", "data/cost")))
    regional_cost_dir: Path = Field(default_factory=lambda: Path(os.getenv("GEOROUTE_REGIONAL_COST_DIR", "data/cost/regional")))
    regional_kangra_cost_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("GEOROUTE_REGIONAL_KANGRA_COST_DIR", "data/cost/regional_kangra"))
    )
    features_dir: Path = Field(default_factory=lambda: Path(os.getenv("GEOROUTE_FEATURES_DIR", "data/features")))
    processed_dir: Path = Field(default_factory=lambda: Path(os.getenv("GEOROUTE_PROCESSED_DIR", "data/processed")))
    jobs_dir: Path = Field(default_factory=lambda: Path(os.getenv("GEOROUTE_JOBS_DIR", "data/jobs")))
    sqlite_db_path: Path = Field(default_factory=lambda: Path(os.getenv("GEOROUTE_DB_PATH", "data/jobs/georoute_jobs.db")))

    # Job & concurrency limits
    max_active_jobs: int = Field(default_factory=lambda: int(os.getenv("GEOROUTE_MAX_ACTIVE_JOBS", "2")))
    max_queued_jobs: int = Field(default_factory=lambda: int(os.getenv("GEOROUTE_MAX_QUEUED_JOBS", "10")))
    job_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("GEOROUTE_JOB_TIMEOUT", "600.0")))
    default_snap_radius_m: float = Field(default=500.0)

    # Engineering status disclaimer
    engineering_disclaimer: str = (
        "GeoRoute AI routes represent preliminary regional planning corridors only, "
        "not certified engineering-feasible railway alignments. They do not account for "
        "sub-surface geology, ruling railway gradients, transition curves, bridge/tunnel "
        "structural designs, or statutory environmental approvals."
    )

    def get_regional_cost_dir(self, region_name: Optional[str] = None) -> Path:
        """Resolves active regional cost directory based on region identifier."""
        if region_name and "kangra" in str(region_name).lower():
            return self.regional_kangra_cost_dir
        return self.regional_cost_dir

    def ensure_directories(self) -> None:
        """Ensures that all runtime storage directories exist."""
        for d in [self.base_data_dir, self.cost_dir, self.regional_cost_dir, self.regional_kangra_cost_dir, self.features_dir, self.processed_dir, self.jobs_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self.sqlite_db_path.parent.mkdir(parents=True, exist_ok=True)


# Global singleton instance
settings = AppConfig()

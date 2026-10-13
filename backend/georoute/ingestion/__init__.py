"""Ingestion modules for vector, STAC raster, and protected areas data."""

from georoute.ingestion.protected_areas import ProtectedAreasIngestor
from georoute.ingestion.regional_data_acquirer import RegionalDataAcquirer
from georoute.ingestion.stac_raster_ingestor import (
    DEMMetadata,
    LandCoverMetadata,
    OpticalSceneMetadata,
    STACRasterIngestor,
)
from georoute.ingestion.vector_ingestor import OSMVectorIngestor

__all__ = [
    "OSMVectorIngestor",
    "STACRasterIngestor",
    "ProtectedAreasIngestor",
    "RegionalDataAcquirer",
    "OpticalSceneMetadata",
    "DEMMetadata",
    "LandCoverMetadata",
]


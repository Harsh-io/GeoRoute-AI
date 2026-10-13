"""Protected areas and environmental boundary ingestion and provenance tracking."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import geopandas as gpd
from shapely.geometry import Polygon
from georoute.config import ProtectedAreasConfig
from georoute.ingestion.vector_ingestor import OSMVectorIngestor

logger = logging.getLogger("georoute.protected_areas")


class ProtectedAreasIngestor:
    """Manages ingestion of environmental protected areas with explicit provenance documentation.

    Distinguishes authoritative environmental boundary sources from crowdsourced OSM proxies.
    Explicitly tracks layer availability and prevents fictitious boundary fabrication.
    """

    def __init__(
        self,
        config: Optional[ProtectedAreasConfig] = None,
        vector_ingestor: Optional[OSMVectorIngestor] = None,
    ):
        """Initializes the protected areas ingestor.

        Args:
            config: ProtectedAreasConfig instance.
            vector_ingestor: Optional OSMVectorIngestor instance for fallback queries.
        """
        self.config = config or ProtectedAreasConfig()
        self.vector_ingestor = vector_ingestor or OSMVectorIngestor()

    def fetch_layer(
        self,
        aoi_polygon: Polygon,
    ) -> Tuple[gpd.GeoDataFrame, Dict[str, Any]]:
        """Retrieves protected area boundaries and returns data along with provenance metadata.

        Args:
            aoi_polygon: Shapely Polygon in EPSG:4326.

        Returns:
            Tuple of (GeoDataFrame, provenance_metadata_dict).
        """
        provenance = {
            "source_type": "None",
            "source_name": "None",
            "status": "UNAVAILABLE",
            "is_authoritative": False,
            "feature_count": 0,
            "limitations": "",
            "warning": None,
        }

        if not self.config.enabled:
            logger.info("Protected areas ingestion is disabled by configuration.")
            empty_gdf = gpd.GeoDataFrame({"layer": [], "geometry": []}, geometry="geometry", crs="EPSG:4326")
            provenance["limitations"] = "Layer disabled by configuration."
            return empty_gdf, provenance

        # 1. Check for authoritative local or external file (e.g. WDPA shapefile / GeoPackage)
        if self.config.authoritative_source_path and Path(self.config.authoritative_source_path).exists():
            auth_path = Path(self.config.authoritative_source_path)
            logger.info(f"Loading authoritative protected areas from: {auth_path}")
            try:
                gdf = gpd.read_file(auth_path, mask=aoi_polygon)
                if gdf.crs is None or gdf.crs != "EPSG:4326":
                    gdf = gdf.to_crs("EPSG:4326")
                provenance.update({
                    "source_type": "Authoritative Dataset",
                    "source_name": auth_path.name,
                    "status": "AVAILABLE",
                    "is_authoritative": True,
                    "feature_count": len(gdf),
                    "limitations": "Authoritative boundary dataset loaded. Verification against local forest department records recommended.",
                })
                return gdf, provenance
            except Exception as e:
                logger.error(f"Failed to load authoritative source {auth_path}: {e}")

        # 2. Fallback to OpenStreetMap if configured
        if self.config.fallback_to_osm:
            logger.warning(
                "Authoritative protected area dataset not configured. "
                "Querying OpenStreetMap proxy tags (boundary=protected_area, leisure=nature_reserve). "
                "NOTICE: OSM data is crowdsourced and incomplete; missing areas do NOT prove absence of protected land."
            )
            osm_gdf = self.vector_ingestor.fetch_layer(
                layer_name=self.config.layer_name,
                aoi_polygon=aoi_polygon,
                tags=self.config.osm_tags,
            )

            feature_count = len(osm_gdf)
            status = "AVAILABLE" if feature_count > 0 else "EMPTY_RESULT"
            provenance.update({
                "source_type": "OpenStreetMap Crowdsourced Proxy",
                "source_name": "OpenStreetMap Overpass API (boundary=protected_area, leisure=nature_reserve)",
                "status": status,
                "is_authoritative": False,
                "feature_count": feature_count,
                "limitations": (
                    "OpenStreetMap is a volunteered geographic dataset. Missing protected boundaries "
                    "must NOT be interpreted as confirmed unprotected or obstacle-free terrain. "
                    "Authoritative statutory datasets (e.g., WDPA / MoEFCC / Wildlife Institute of India) "
                    "are required for legal compliance in construction planning."
                ),
                "warning": "Non-authoritative proxy data. Do not use for legal environmental clearance.",
            })
            return osm_gdf, provenance

        # 3. No source available
        logger.warning("No authoritative or fallback protected area source available. Layer marked UNAVAILABLE.")
        empty_gdf = gpd.GeoDataFrame({"layer": [], "geometry": []}, geometry="geometry", crs="EPSG:4326")
        provenance.update({
            "status": "UNAVAILABLE",
            "limitations": "No protected area source available or configured.",
            "warning": "Protected area layer is unavailable. Downstream corridor planning must acknowledge absence of data.",
        })
        return empty_gdf, provenance

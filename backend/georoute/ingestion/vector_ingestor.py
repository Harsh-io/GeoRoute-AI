"""Production vector data ingestion module using OSMnx and GeoPandas."""

import json
import logging
from typing import Any, Dict, Optional
import geopandas as gpd
import osmnx as ox
import requests
from shapely.geometry import Polygon
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

logger = logging.getLogger("georoute.vector_ingestor")


class OSMVectorIngestor:
    """Ingests, cleans, and standardizes OpenStreetMap vector datasets via OSMnx."""

    def __init__(
        self,
        timeout_seconds: int = 60,
        max_retries: int = 3,
        custom_overpass_endpoint: Optional[str] = None,
    ):
        """Initializes OSMnx client settings and retry parameters.

        Args:
            timeout_seconds: HTTP timeout in seconds for Overpass API requests.
            max_retries: Maximum retry attempts for transient network/rate errors.
            custom_overpass_endpoint: Optional URL for custom Overpass server.
        """
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        
        # Configure global OSMnx settings
        ox.settings.timeout = self.timeout_seconds
        ox.settings.use_cache = True
        ox.settings.log_console = False

        if custom_overpass_endpoint:
            ox.settings.overpass_endpoint = custom_overpass_endpoint
            logger.info(f"Configured custom Overpass endpoint: {custom_overpass_endpoint}")

    def _sanitize_geodataframe(
        self, gdf: gpd.GeoDataFrame, layer_name: str
    ) -> gpd.GeoDataFrame:
        """Cleans geometries, fixes topological self-intersections, and stringifies complex types.

        Args:
            gdf: Raw GeoDataFrame returned by OSMnx.
            layer_name: Identifier for the ingested layer.

        Returns:
            Sanitized, validated GeoDataFrame with uniform columns.
        """
        if gdf.empty:
            logger.warning(f"Layer '{layer_name}' is empty. Returning empty GeoDataFrame.")
            return gpd.GeoDataFrame(
                {"layer": [], "geometry": []},
                geometry="geometry",
                crs="EPSG:4326",
            )

        initial_count = len(gdf)

        # 1. Filter out null or empty geometries
        gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()

        # 2. Repair invalid geometries (e.g. bowties, self-intersecting rings)
        if not gdf.geometry.is_valid.all():
            invalid_count = (~gdf.geometry.is_valid).sum()
            logger.warning(
                f"Repairing {invalid_count} invalid geometries in layer '{layer_name}' via make_valid()."
            )
            gdf["geometry"] = gdf["geometry"].make_valid()

        # Re-filter in case make_valid resulted in empty collection
        gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()

        # 3. Ensure CRS is WGS84
        if gdf.crs is None:
            gdf.set_crs("EPSG:4326", inplace=True)
        elif gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")

        # 4. Standardize attribute types for valid GeoJSON serialization
        # OpenStreetMap attributes frequently contain unhashable lists or dictionaries
        for col in gdf.columns:
            if col == "geometry":
                continue
            sample_val = gdf[col].dropna().iloc[0] if not gdf[col].dropna().empty else None
            if isinstance(sample_val, (list, dict)):
                gdf[col] = gdf[col].apply(
                    lambda x: json.dumps(x) if isinstance(x, (list, dict)) else str(x) if x is not None else None
                )

        gdf["layer_name"] = layer_name
        logger.info(
            f"Sanitized layer '{layer_name}': {len(gdf)} valid features retained (from {initial_count})."
        )
        return gdf

    def fetch_layer(
        self,
        layer_name: str,
        aoi_polygon: Polygon,
        tags: Dict[str, Any],
    ) -> gpd.GeoDataFrame:
        """Fetches vector features for a polygon boundary and specific tags with retries.

        Args:
            layer_name: Identifier for the layer (e.g., 'highways', 'buildings').
            aoi_polygon: Shapely Polygon defining the boundary of interest in EPSG:4326.
            tags: Dictionary of OSM tags to query (e.g. {'highway': True}).

        Returns:
            GeoDataFrame containing fetched and sanitized features.
        """
        logger.info(f"Fetching vector layer '{layer_name}' with tags: {tags}")

        @retry(
            retry=retry_if_exception_type(
                (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ConnectionError, TimeoutError)
            ),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1.5, min=2, max=10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _execute_query() -> gpd.GeoDataFrame:
            try:
                # OSMnx features_from_polygon query
                raw_gdf = ox.features_from_polygon(aoi_polygon, tags=tags)
                return raw_gdf
            except ox._errors.InsufficientResponseError:
                logger.info(f"No OSM features matched tag criteria {tags} for layer '{layer_name}'.")
                return gpd.GeoDataFrame(
                    {"layer": [], "geometry": []},
                    geometry="geometry",
                    crs="EPSG:4326",
                )
            except Exception as e:
                # Catch empty response strings from Overpass
                if "No data elements in server response" in str(e):
                    logger.info(f"Empty server response for layer '{layer_name}'.")
                    return gpd.GeoDataFrame(
                        {"layer": [], "geometry": []},
                        geometry="geometry",
                        crs="EPSG:4326",
                    )
                logger.error(f"Error querying Overpass for '{layer_name}': {e}")
                raise

        try:
            raw_gdf = _execute_query()
            return self._sanitize_geodataframe(raw_gdf, layer_name)
        except Exception as e:
            logger.error(f"Failed to fetch layer '{layer_name}' after {self.max_retries} attempts: {e}")
            # Return empty GeoDataFrame to preserve pipeline execution
            return gpd.GeoDataFrame(
                {"layer": [], "geometry": []},
                geometry="geometry",
                crs="EPSG:4326",
            )

    def fetch_all(
        self,
        aoi_polygon: Polygon,
        layer_configs: Dict[str, Any],
    ) -> Dict[str, gpd.GeoDataFrame]:
        """Ingests all configured vector layers for the bounding box.

        Args:
            aoi_polygon: Shapely polygon of the area of interest in EPSG:4326.
            layer_configs: Mapping of layer name to configuration containing 'tags'.

        Returns:
            Dictionary mapping layer_name to sanitized GeoDataFrames.
        """
        vector_layers: Dict[str, gpd.GeoDataFrame] = {}

        for layer_name, cfg in layer_configs.items():
            tags = cfg.tags if hasattr(cfg, "tags") else cfg.get("tags", {})
            gdf = self.fetch_layer(
                layer_name=layer_name,
                aoi_polygon=aoi_polygon,
                tags=tags,
            )
            vector_layers[layer_name] = gdf

        return vector_layers

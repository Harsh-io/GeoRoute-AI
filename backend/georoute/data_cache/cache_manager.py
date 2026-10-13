"""Disk-backed caching manager for raw vector features and downloaded raster assets."""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import geopandas as gpd

logger = logging.getLogger("georoute.cache")


class DataCacheManager:
    """Manages disk caching for raw OSM vector layers and STAC raster tiles."""

    def __init__(self, cache_dir: Path | str = "./data/raw"):
        """Initializes cache directory.

        Args:
            cache_dir: Base directory for local cache files.
        """
        self.cache_dir = Path(cache_dir)
        self.vector_cache_dir = self.cache_dir / "vectors"
        self.raster_cache_dir = self.cache_dir / "rasters"
        self.vector_cache_dir.mkdir(parents=True, exist_ok=True)
        self.raster_cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_bbox_hash(bbox: Tuple[float, float, float, float], precision: int = 4) -> str:
        """Generates a stable hash string for a bounding box."""
        rounded = [round(c, precision) for c in bbox]
        key = f"bbox_{rounded[0]}_{rounded[1]}_{rounded[2]}_{rounded[3]}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def compute_query_hash(
        bbox: Tuple[float, float, float, float],
        tags: Dict[str, Any],
        precision: int = 4,
    ) -> str:
        """Generates a deterministic hash for an OSM query (bbox + tags)."""
        rounded = [round(c, precision) for c in bbox]
        tag_str = json.dumps(tags, sort_keys=True)
        raw_key = f"{rounded}:{tag_str}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

    # --------------------------------------------------------------------------
    # Vector Caching
    # --------------------------------------------------------------------------
    def get_vector_layer(
        self,
        layer_name: str,
        bbox: Tuple[float, float, float, float],
        tags: Dict[str, Any],
    ) -> Optional[gpd.GeoDataFrame]:
        """Retrieves a cached vector layer if present on disk."""
        query_hash = self.compute_query_hash(bbox, tags)
        cache_path = self.vector_cache_dir / f"{layer_name}_{query_hash}.geojson"

        if cache_path.exists():
            try:
                gdf = gpd.read_file(cache_path)
                logger.info(
                    f"Cache HIT: Loaded vector layer '{layer_name}' "
                    f"({len(gdf)} features) from: {cache_path.name}"
                )
                return gdf
            except Exception as e:
                logger.warning(f"Failed to read cache file {cache_path}: {e}. Refreshing.")
                return None
        return None

    def save_vector_layer(
        self,
        layer_name: str,
        bbox: Tuple[float, float, float, float],
        tags: Dict[str, Any],
        gdf: gpd.GeoDataFrame,
    ) -> Path:
        """Caches a sanitized vector layer to disk."""
        query_hash = self.compute_query_hash(bbox, tags)
        cache_path = self.vector_cache_dir / f"{layer_name}_{query_hash}.geojson"
        try:
            gdf.to_file(cache_path, driver="GeoJSON")
            logger.info(f"Cached vector layer '{layer_name}' -> {cache_path.name}")
        except Exception as e:
            logger.warning(f"Could not write cache file {cache_path}: {e}")
        return cache_path

    # --------------------------------------------------------------------------
    # Raster Tile Caching
    # --------------------------------------------------------------------------
    def get_raster_path(self, collection: str, item_id: str, asset_name: str) -> Optional[Path]:
        """Checks if a downloaded raster tile exists and is valid."""
        safe_item_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in item_id)
        candidate = self.raster_cache_dir / f"{collection}_{safe_item_id}_{asset_name}.tif"
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
        return None

    def get_raster_destination(self, collection: str, item_id: str, asset_name: str) -> Path:
        """Returns the intended path for storing a raster tile."""
        safe_item_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in item_id)
        return self.raster_cache_dir / f"{collection}_{safe_item_id}_{asset_name}.tif"

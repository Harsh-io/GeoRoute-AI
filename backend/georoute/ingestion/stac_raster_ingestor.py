"""Production STAC raster ingestion module for Sentinel-2 optical imagery and Copernicus DEM."""

from dataclasses import dataclass
import logging
import os
from typing import Dict, List, Optional, Tuple
import planetary_computer
import pystac_client
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

logger = logging.getLogger("georoute.stac_ingestor")


@dataclass
class OpticalSceneMetadata:
    """Metadata container for the selected optical satellite acquisition."""
    item_id: str
    datetime: str
    cloud_cover: float
    band_urls: Dict[str, str]
    native_crs: Optional[str] = None


@dataclass
class DEMMetadata:
    """Metadata container for digital elevation model assets covering the AOI."""
    item_ids: List[str]
    asset_urls: List[str]
    collection: str


@dataclass
class LandCoverMetadata:
    """Metadata container for land cover assets (e.g. ESA WorldCover)."""
    item_ids: List[str]
    asset_urls: List[str]
    collection: str
    year: int
    asset_name: str = "map"


class STACRasterIngestor:
    """Discovers, filters, and signs STAC assets for optical imagery and elevation models."""

    def __init__(
        self,
        api_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1",
        use_planetary_computer: bool = True,
        max_retries: int = 5,
    ):
        """Initializes STAC client with rate-limiting tolerance.

        Args:
            api_url: STAC API root endpoint URL.
            use_planetary_computer: Whether to apply SAS URL signing via planetary_computer.
            max_retries: Maximum exponential backoff retries for network/catalog calls.
        """
        self.api_url = api_url
        self.use_planetary_computer = use_planetary_computer
        self.max_retries = max_retries
        self._client: Optional[pystac_client.Client] = None

    def _get_client(self) -> pystac_client.Client:
        """Lazily instantiates and caches the STAC client."""
        if self._client is None:
            logger.info(f"Connecting to STAC endpoint: {self.api_url}")
            modifier = (
                planetary_computer.sign_inplace
                if self.use_planetary_computer
                else None
            )
            self._client = pystac_client.Client.open(
                self.api_url,
                modifier=modifier,
            )
        return self._client

    def search_optical_scene(
        self,
        bbox: Tuple[float, float, float, float],
        date_range_str: str,
        bands: List[str],
        max_cloud_cover_percent: float = 5.0,
        collection: str = "sentinel-2-l2a",
    ) -> OpticalSceneMetadata:
        """Searches Sentinel-2 L2A collection and selects the scene with minimal cloud cover.

        Args:
            bbox: Bounding box tuple (min_lon, min_lat, max_lon, max_lat).
            date_range_str: STAC temporal query string 'YYYY-MM-DD/YYYY-MM-DD'.
            bands: Desired optical band identifiers (e.g. ['B04', 'B03', 'B02', 'B08']).
            max_cloud_cover_percent: Strict cloud cover ceiling (default 5.0%).
            collection: STAC collection name (default 'sentinel-2-l2a').

        Returns:
            OpticalSceneMetadata with signed band download URLs.
        """
        client = self._get_client()

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1.5, min=2, max=15),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _execute_search(cloud_threshold: float):
            logger.info(
                f"Querying STAC optical collection '{collection}' in date range {date_range_str} "
                f"with cloud_cover < {cloud_threshold}%..."
            )
            search = client.search(
                collections=[collection],
                bbox=list(bbox),
                datetime=date_range_str,
                query={"eo:cloud_cover": {"lt": cloud_threshold}},
            )
            return list(search.items())

        # Primary search with strict user cloud threshold
        items = _execute_search(max_cloud_cover_percent)

        if not items:
            logger.warning(
                f"No Sentinel-2 scenes found with cloud cover < {max_cloud_cover_percent}%. "
                f"Relaxing cloud cover threshold to 20% to find clearest available scene."
            )
            items = _execute_search(20.0)

        if not items:
            raise RuntimeError(
                f"Unable to find any Sentinel-2 scenes for bbox {bbox} in date range {date_range_str} "
                f"even after relaxing cloud cover threshold."
            )

        # Sort items strictly by cloud cover ascending
        items_sorted = sorted(
            items, key=lambda it: it.properties.get("eo:cloud_cover", 100.0)
        )
        selected_item = items_sorted[0]
        cloud_pct = selected_item.properties.get("eo:cloud_cover", 0.0)
        acq_time = selected_item.datetime.isoformat() if selected_item.datetime else "unknown"

        logger.info(
            f"Selected Sentinel-2 scene: ID={selected_item.id} | "
            f"Acquisition={acq_time} | CloudCover={cloud_pct:.2f}%"
        )

        # Extract band asset URLs
        band_urls: Dict[str, str] = {}
        for band in bands:
            if band not in selected_item.assets:
                available = list(selected_item.assets.keys())
                raise KeyError(
                    f"Requested band '{band}' not found in item '{selected_item.id}'. Available assets: {available}"
                )
            band_urls[band] = selected_item.assets[band].href

        native_crs = None
        if "proj:epsg" in selected_item.properties:
            native_crs = f"EPSG:{selected_item.properties['proj:epsg']}"

        return OpticalSceneMetadata(
            item_id=selected_item.id,
            datetime=acq_time,
            cloud_cover=cloud_pct,
            band_urls=band_urls,
            native_crs=native_crs,
        )

    def search_dem(
        self,
        bbox: Tuple[float, float, float, float],
        collection: str = "cop-dem-glo-30",
        asset_name: str = "data",
    ) -> DEMMetadata:
        """Retrieves Digital Elevation Model tiles covering the exact bounding box.

        Args:
            bbox: Bounding box tuple (min_lon, min_lat, max_lon, max_lat).
            collection: STAC DEM collection name (default 'cop-dem-glo-30').
            asset_name: Asset identifier containing elevation raster data (default 'data').

        Returns:
            DEMMetadata containing tile IDs and signed asset URLs.
        """
        client = self._get_client()

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1.5, min=2, max=15),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _execute_dem_search():
            logger.info(f"Querying STAC DEM collection '{collection}' for bbox {bbox}...")
            search = client.search(
                collections=[collection],
                bbox=list(bbox),
            )
            return list(search.items())

        dem_items = _execute_dem_search()
        if not dem_items:
            raise RuntimeError(
                f"No DEM tiles found in collection '{collection}' covering bbox {bbox}."
            )

        item_ids: List[str] = []
        asset_urls: List[str] = []

        for item in dem_items:
            item_ids.append(item.id)
            if asset_name not in item.assets:
                raise KeyError(
                    f"Asset '{asset_name}' missing from DEM item '{item.id}'. Available: {list(item.assets.keys())}"
                )
            asset_urls.append(item.assets[asset_name].href)

        logger.info(
            f"Retrieved {len(dem_items)} DEM tile(s) from collection '{collection}': {item_ids}"
        )

        return DEMMetadata(
            item_ids=item_ids,
            asset_urls=asset_urls,
            collection=collection,
        )

    def search_land_cover(
        self,
        bbox: Tuple[float, float, float, float],
        collection: str = "esa-worldcover",
        asset_name: str = "map",
        year: int = 2021,
    ) -> LandCoverMetadata:
        """Retrieves Land Cover tiles (e.g. ESA WorldCover) covering the bounding box.

        Args:
            bbox: Bounding box tuple (min_lon, min_lat, max_lon, max_lat).
            collection: STAC collection name (default 'esa-worldcover').
            asset_name: Asset identifier containing land cover raster data (default 'map').
            year: Reference year (default 2021).

        Returns:
            LandCoverMetadata containing tile IDs and signed asset URLs.
        """
        client = self._get_client()

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1.5, min=2, max=15),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _execute_lc_search():
            logger.info(f"Querying STAC Land Cover collection '{collection}' for bbox {bbox}...")
            search = client.search(
                collections=[collection],
                bbox=list(bbox),
            )
            return list(search.items())

        lc_items = _execute_lc_search()
        if not lc_items:
            raise RuntimeError(
                f"No Land Cover tiles found in collection '{collection}' covering bbox {bbox}."
            )

        item_ids: List[str] = []
        asset_urls: List[str] = []

        for item in lc_items:
            item_ids.append(item.id)
            if asset_name not in item.assets:
                raise KeyError(
                    f"Asset '{asset_name}' missing from Land Cover item '{item.id}'. Available: {list(item.assets.keys())}"
                )
            asset_urls.append(item.assets[asset_name].href)

        logger.info(
            f"Retrieved {len(lc_items)} Land Cover tile(s) from collection '{collection}': {item_ids}"
        )

        return LandCoverMetadata(
            item_ids=item_ids,
            asset_urls=asset_urls,
            collection=collection,
            year=year,
            asset_name=asset_name,
        )

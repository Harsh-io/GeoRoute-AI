"""Spatial alignment, metric UTM reprojection, and raster co-registration module."""

from __future__ import annotations
from dataclasses import dataclass
import logging
from typing import Dict, List, Optional, Tuple
try:
    import geopandas as gpd
except Exception:
    gpd = None
import numpy as np
import pyproj
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

logger = logging.getLogger("georoute.alignment")


@dataclass
class AlignedRasterData:
    """Container for resampled, co-registered raster arrays and georeferencing metadata."""
    data: np.ndarray  # Shape: (bands, height, width) or (1, height, width)
    transform: Affine
    crs: pyproj.CRS
    nodata: Optional[float]
    band_names: List[str]
    dtype: np.dtype


class SpatialAligner:
    """Manages coordinate reprojection and pixel-grid co-registration across vector and raster assets."""

    def __init__(
        self,
        target_crs: pyproj.CRS,
        target_transform: Affine,
        width: int,
        height: int,
    ):
        """Initializes the aligner with the master metric UTM grid.

        Args:
            target_crs: Destination UTM coordinate reference system.
            target_transform: Destination Affine georeferencing transform.
            width: Raster pixel width.
            height: Raster pixel height.
        """
        self.target_crs = target_crs
        self.target_transform = target_transform
        self.width = width
        self.height = height

    # --------------------------------------------------------------------------
    # Vector Reprojection & Metric Geometry Calculation
    # --------------------------------------------------------------------------
    def reproject_vectors(
        self, vector_layers: Dict[str, gpd.GeoDataFrame]
    ) -> Dict[str, gpd.GeoDataFrame]:
        """Reprojects all vector layers to the unified metric UTM CRS and computes metric properties.

        Args:
            vector_layers: Dictionary of raw GeoDataFrames (EPSG:4326).

        Returns:
            Dictionary of reprojected GeoDataFrames in the target UTM CRS.
        """
        reprojected_layers: Dict[str, gpd.GeoDataFrame] = {}

        for name, gdf in vector_layers.items():
            if gdf.empty:
                logger.info(f"Vector layer '{name}' is empty. Preserving schema with target CRS {self.target_crs.to_epsg()}.")
                reprojected_layers[name] = gdf.to_crs(self.target_crs)
                continue

            logger.info(
                f"Reprojecting vector layer '{name}' ({len(gdf)} features) "
                f"from {gdf.crs} -> EPSG:{self.target_crs.to_epsg()}..."
            )
            reprojected_gdf = gdf.to_crs(self.target_crs).copy()

            # Calculate metric dimensions in meters
            geom_types = set(reprojected_gdf.geometry.geom_type)
            if any("Line" in gt for gt in geom_types):
                reprojected_gdf["length_m"] = reprojected_gdf.geometry.length
            if any("Polygon" in gt for gt in geom_types):
                reprojected_gdf["area_m2"] = reprojected_gdf.geometry.area

            reprojected_layers[name] = reprojected_gdf

        return reprojected_layers

    # --------------------------------------------------------------------------
    # Optical Imagery Reprojection & Stacking
    # --------------------------------------------------------------------------
    def resample_and_align_optical(
        self,
        band_urls: Dict[str, str],
        resampling: Resampling = Resampling.bilinear,
    ) -> AlignedRasterData:
        """Warps and stacks Sentinel-2 optical bands onto the exact unified UTM grid.

        Args:
            band_urls: Mapping of band name (e.g. 'B04', 'B03', 'B02', 'B08') to signed stream URL.
            resampling: Interpolation algorithm for warp (default: Resampling.bilinear).

        Returns:
            AlignedRasterData containing multi-band float32 optical array.
        """
        band_names = list(band_urls.keys())
        num_bands = len(band_names)
        stacked_array = np.zeros((num_bands, self.height, self.width), dtype=np.float32)

        gdal_env = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.vrt",
            "GDAL_HTTP_MAX_RETRY": "5",
            "GDAL_HTTP_RETRY_DELAY": "2",
            "VSI_CACHE": "TRUE",
        }

        # NOTE: _stream_and_warp is defined outside the loop so that the
        # tenacity decorator is applied once and url is passed explicitly,
        # avoiding any loop-variable closure capture bug.
        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1.5, min=2, max=10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _stream_and_warp(dst_band_array: np.ndarray, url: str) -> None:
            with rasterio.open(url) as src:
                reproject(
                    source=rasterio.band(src, 1),
                    destination=dst_band_array,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    src_nodata=src.nodata,
                    dst_transform=self.target_transform,
                    dst_crs=self.target_crs,
                    dst_nodata=0.0,
                    resampling=resampling,
                )

        with rasterio.Env(**gdal_env):
            for idx, (band_name, url) in enumerate(band_urls.items()):
                logger.info(
                    f"Warping optical band {idx + 1}/{num_bands} ('{band_name}') "
                    f"to unified UTM grid ({self.width}x{self.height} px)..."
                )
                _stream_and_warp(stacked_array[idx], url)

        return AlignedRasterData(
            data=stacked_array,
            transform=self.target_transform,
            crs=self.target_crs,
            nodata=0.0,
            band_names=band_names,
            dtype=np.float32,
        )

    # --------------------------------------------------------------------------
    # DEM Resampling & Co-Registration
    # --------------------------------------------------------------------------
    def resample_and_align_dem(
        self,
        dem_urls: List[str],
        resampling_method_name: str = "bilinear",
    ) -> AlignedRasterData:
        """Resamples 30m DEM to match the exact 10m Sentinel-2 pixel grid using bilinear/cubic interpolation.

        Args:
            dem_urls: List of signed URLs for DEM tiles covering the AOI.
            resampling_method_name: 'bilinear' or 'cubic' interpolation.

        Returns:
            AlignedRasterData containing single-band float32 elevation array.
        """
        method_map = {
            "bilinear": Resampling.bilinear,
            "cubic": Resampling.cubic,
            "lanczos": Resampling.lanczos,
            "nearest": Resampling.nearest,
        }
        resampling = method_map.get(resampling_method_name.lower(), Resampling.bilinear)
        logger.info(
            f"Resampling DEM using '{resampling_method_name}' interpolation "
            f"to match 10m Sentinel-2 pixel grid..."
        )

        dem_array = np.full((1, self.height, self.width), fill_value=-9999.0, dtype=np.float32)

        gdal_env = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.vrt",
            "GDAL_HTTP_MAX_RETRY": "5",
            "GDAL_HTTP_RETRY_DELAY": "2",
            "VSI_CACHE": "TRUE",
        }

        # NOTE: _warp_dem_tile is defined once outside the loop with dem_url as
        # an explicit positional argument. This eliminates the closure/loop-
        # variable capture bug where all tiles could share the last URL.
        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1.5, min=2, max=10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _warp_dem_tile(target_slice: np.ndarray, dem_url: str) -> None:
            """Warps a single DEM tile URL into target_slice in-place.

            Args:
                target_slice: 2-D destination array (height x width).
                dem_url: Signed URL for the specific DEM tile to read.
            """
            with rasterio.open(dem_url) as src:
                # Temporary buffer for single tile
                tile_buffer = np.full((self.height, self.width), fill_value=-9999.0, dtype=np.float32)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=tile_buffer,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    src_nodata=src.nodata,
                    dst_transform=self.target_transform,
                    dst_crs=self.target_crs,
                    dst_nodata=-9999.0,
                    resampling=resampling,
                )
                # Blend / fill non-nodata pixels into master array
                valid_mask = tile_buffer != -9999.0
                target_slice[valid_mask] = tile_buffer[valid_mask]

        with rasterio.Env(**gdal_env):
            for tile_idx, tile_url in enumerate(dem_urls):
                logger.info(f"Warping DEM tile {tile_idx + 1}/{len(dem_urls)} into target grid...")
                # Explicit URL passed — no closure risk
                _warp_dem_tile(dem_array[0], tile_url)

        valid_elevations = dem_array[0][dem_array[0] != -9999.0]
        if len(valid_elevations) > 0:
            logger.info(
                f"DEM resampled successfully: min={valid_elevations.min():.1f}m, "
                f"max={valid_elevations.max():.1f}m, "
                f"mean={valid_elevations.mean():.1f}m."
            )
        else:
            logger.warning("DEM grid contains only nodata values. Check bounding box coverage.")

        return AlignedRasterData(
            data=dem_array,
            transform=self.target_transform,
            crs=self.target_crs,
            nodata=-9999.0,
            band_names=["elevation_m"],
            dtype=np.float32,
        )

    # --------------------------------------------------------------------------
    # Land Cover Resampling & Co-Registration (Categorical: Nearest-Neighbor)
    # --------------------------------------------------------------------------
    def resample_and_align_land_cover(
        self,
        lc_urls: List[str],
        nodata_val: float = 0.0,
    ) -> AlignedRasterData:
        """Resamples Land Cover tiles onto target grid using nearest-neighbor interpolation.

        CRITICAL: Uses nearest-neighbor interpolation to strictly preserve discrete
        categorical land-cover classes (e.g. 10=Tree, 50=Built-up) without creating
        invalid fractional or intermediate classes.

        Args:
            lc_urls: List of signed URLs for land cover tiles covering the AOI.
            nodata_val: Fill value for nodata pixels (default 0.0).

        Returns:
            AlignedRasterData containing single-band categorical land-cover array.
        """
        logger.info(
            "Resampling Land Cover using 'nearest-neighbor' interpolation to preserve discrete classes..."
        )

        lc_array = np.full((1, self.height, self.width), fill_value=int(nodata_val), dtype=np.uint8)

        gdal_env = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.vrt",
            "GDAL_HTTP_MAX_RETRY": "5",
            "GDAL_HTTP_RETRY_DELAY": "2",
            "VSI_CACHE": "TRUE",
        }

        @retry(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1.5, min=2, max=10),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )
        def _warp_lc_tile(target_slice: np.ndarray, lc_url: str) -> None:
            """Warps a single Land Cover tile into target_slice in-place."""
            with rasterio.open(lc_url) as src:
                tile_buffer = np.full((self.height, self.width), fill_value=int(nodata_val), dtype=np.uint8)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=tile_buffer,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    src_nodata=src.nodata if src.nodata is not None else int(nodata_val),
                    dst_transform=self.target_transform,
                    dst_crs=self.target_crs,
                    dst_nodata=int(nodata_val),
                    resampling=Resampling.nearest,
                )
                valid_mask = tile_buffer != int(nodata_val)
                target_slice[valid_mask] = tile_buffer[valid_mask]

        with rasterio.Env(**gdal_env):
            for tile_idx, tile_url in enumerate(lc_urls):
                logger.info(f"Warping Land Cover tile {tile_idx + 1}/{len(lc_urls)} into target grid...")
                _warp_lc_tile(lc_array[0], tile_url)

        unique_classes = np.unique(lc_array[0])
        logger.info(f"Land Cover resampled successfully: Unique classes detected={unique_classes.tolist()}")

        return AlignedRasterData(
            data=lc_array,
            transform=self.target_transform,
            crs=self.target_crs,
            nodata=nodata_val,
            band_names=["land_cover_class"],
            dtype=np.uint8,
        )

    # --------------------------------------------------------------------------
    # Co-Registration Quality Verification
    # --------------------------------------------------------------------------
    @staticmethod
    def verify_co_registration(
        optical: AlignedRasterData,
        dem: AlignedRasterData,
        tolerance: float = 1e-6,
    ) -> bool:
        """Performs rigorous assertions to verify pixel-for-pixel co-registration between layers.

        Args:
            optical: Aligned optical raster data.
            dem: Aligned DEM raster data.
            tolerance: Floating point tolerance for affine matrix comparisons.

        Returns:
            True if co-registration is verified, raises AssertionError otherwise.
        """
        logger.info("Executing co-registration quality audit between Optical and DEM grids...")

        # 1. Grid shape check
        opt_shape = optical.data.shape[1:]  # (height, width)
        dem_shape = dem.data.shape[1:]
        if opt_shape != dem_shape:
            raise AssertionError(
                f"Co-registration failure: Optical shape {opt_shape} does not match DEM shape {dem_shape}."
            )

        # 2. CRS alignment check
        if optical.crs != dem.crs:
            raise AssertionError(
                f"Co-registration failure: Optical CRS ({optical.crs}) does not match DEM CRS ({dem.crs})."
            )

        # 3. Affine transform matrix check
        opt_t = list(optical.transform)[:6]
        dem_t = list(dem.transform)[:6]
        diffs = [abs(a - b) for a, b in zip(opt_t, dem_t)]
        if any(d > tolerance for d in diffs):
            raise AssertionError(
                f"Co-registration failure: Affine transforms differ. Opt={opt_t}, DEM={dem_t}"
            )

        logger.info(
            f"Co-registration PASSED: Perfect pixel alignment across {opt_shape[1]}x{opt_shape[0]} "
            f"grid at 10.0m resolution (CRS: EPSG:{optical.crs.to_epsg()})."
        )
        return True

    @classmethod
    def verify_multi_co_registration(
        cls,
        layers: Dict[str, AlignedRasterData],
        tolerance: float = 1e-6,
    ) -> bool:
        """Verifies pixel-for-pixel co-registration across any number of aligned raster layers.

        Args:
            layers: Dictionary mapping layer name to AlignedRasterData.
            tolerance: Floating point tolerance for affine matrix comparisons.

        Returns:
            True if all layers match the reference grid.
        """
        if len(layers) < 2:
            return True

        layer_names = list(layers.keys())
        ref_name = layer_names[0]
        ref_layer = layers[ref_name]

        for other_name in layer_names[1:]:
            logger.info(f"Auditing co-registration between '{ref_name}' and '{other_name}'...")
            cls.verify_co_registration(ref_layer, layers[other_name], tolerance=tolerance)

        return True

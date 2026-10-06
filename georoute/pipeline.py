"""Master orchestration pipeline for GeoRoute AI: Part 1."""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional
from georoute.config import PipelineConfig
from georoute.ingestion.stac_raster_ingestor import STACRasterIngestor
from georoute.ingestion.vector_ingestor import OSMVectorIngestor
from georoute.processing.alignment import SpatialAligner
from georoute.processing.cog_exporter import GeoDataExporter
from georoute.utils.crs_utils import compute_target_raster_grid, get_utm_crs_for_bbox
from georoute.utils.logging_config import setup_logger

logger = logging.getLogger("georoute.pipeline")


class GeoRoutePipeline:
    """Enterprise orchestrator for Data Ingestion, Metric Standardization, Co-Registration, and Export."""

    def __init__(
        self,
        config: PipelineConfig,
        custom_logger: Optional[logging.Logger] = None,
    ):
        """Initializes pipeline components and computes target spatial grids.

        Args:
            config: Validated PipelineConfig object.
            custom_logger: Optional pre-configured logger instance.
        """
        self.config = config
        self.logger = custom_logger or setup_logger(
            name="georoute",
            level="INFO",
            log_file=Path(self.config.export.output_dir) / "pipeline.log",
        )

        self.logger.info("=" * 80)
        self.logger.info(f"Initializing GeoRoute AI Pipeline: AOI='{self.config.region_name}'")
        self.logger.info(f"Bounding Box (WGS84): {self.config.bbox.as_tuple}")
        self.logger.info("=" * 80)

        # 1. Programmatically determine optimal local UTM zone
        min_lon, min_lat, max_lon, max_lat = self.config.bbox.as_tuple
        self.target_utm_crs = get_utm_crs_for_bbox(min_lon, min_lat, max_lon, max_lat)
        self.utm_epsg = self.target_utm_crs.to_epsg()
        self.logger.info(
            f"Determined optimal Metric UTM Zone: EPSG:{self.utm_epsg} ({self.target_utm_crs.name})"
        )

        # 2. Compute pixel-aligned target raster grid
        target_res = self.config.processing.target_pixel_size_meters
        (
            self.target_transform,
            self.grid_width,
            self.grid_height,
            self.snapped_bounds,
        ) = compute_target_raster_grid(
            bbox_4326=self.config.bbox.as_tuple,
            target_crs=self.target_utm_crs,
            pixel_size_meters=target_res,
        )

        self.logger.info(
            f"Defined Target 10m Grid: {self.grid_width}x{self.grid_height} pixels | "
            f"Resolution: {target_res}m | "
            f"UTM Bounds: {self.snapped_bounds}"
        )

        # 3. Instantiate sub-modules
        self.vector_ingestor = OSMVectorIngestor(
            timeout_seconds=self.config.vector.timeout_seconds,
            max_retries=self.config.vector.max_retries,
        )

        self.stac_ingestor = STACRasterIngestor(
            api_url=self.config.stac.api_url,
            use_planetary_computer=self.config.stac.use_planetary_computer,
        )

        self.aligner = SpatialAligner(
            target_crs=self.target_utm_crs,
            target_transform=self.target_transform,
            width=self.grid_width,
            height=self.grid_height,
        )

        self.exporter = GeoDataExporter(
            output_dir=self.config.export.output_dir,
            block_size=self.config.export.cog.block_size,
            compression=self.config.export.cog.compression,
            overview_levels=self.config.export.cog.overview_levels,
        )

    def execute(self) -> Dict[str, Any]:
        """Runs the complete ingestion and preprocessing pipeline end-to-end.

        Returns:
            Dictionary containing detailed execution statistics and paths to exported artifacts.
        """
        start_time = time.time()
        self.logger.info("Executing Phase 1: Vector & Raster Data Ingestion...")

        # ----------------------------------------------------------------------
        # Stage 1: Vector Data Ingestion (OSMnx)
        # ----------------------------------------------------------------------
        self.logger.info("--> [1/5] Ingesting OpenStreetMap vector features via OSMnx...")
        aoi_polygon = self.config.bbox.as_polygon
        raw_vector_layers = self.vector_ingestor.fetch_all(
            aoi_polygon=aoi_polygon,
            layer_configs=self.config.vector.layers,
        )

        # ----------------------------------------------------------------------
        # Stage 2: Vector Standardization & UTM Reprojection
        # ----------------------------------------------------------------------
        self.logger.info(f"--> [2/5] Reprojecting vector layers to EPSG:{self.utm_epsg}...")
        utm_vector_layers = self.aligner.reproject_vectors(raw_vector_layers)

        # ----------------------------------------------------------------------
        # Stage 3: STAC Catalog Search (Sentinel-2 & Copernicus DEM)
        # ----------------------------------------------------------------------
        self.logger.info("--> [3/5] Querying STAC catalog for Optical Satellite and DEM assets...")
        
        # 3a. Optical Scene Search
        optical_scene_meta = self.stac_ingestor.search_optical_scene(
            bbox=self.config.bbox.as_tuple,
            date_range_str=self.config.temporal.date_range_string,
            bands=self.config.stac.optical.bands,
            max_cloud_cover_percent=self.config.stac.optical.max_cloud_cover_percent,
            collection=self.config.stac.optical.collection,
        )

        # 3b. DEM Search
        dem_meta = self.stac_ingestor.search_dem(
            bbox=self.config.bbox.as_tuple,
            collection=self.config.stac.elevation.collection,
            asset_name=self.config.stac.elevation.asset_name,
        )

        # ----------------------------------------------------------------------
        # Stage 4: Raster Co-Registration & Resampling
        # ----------------------------------------------------------------------
        self.logger.info("--> [4/5] Warping and Co-Registering Optical & DEM Rasters to 10m Grid...")

        # 4a. Resample and align optical bands
        aligned_optical = self.aligner.resample_and_align_optical(
            band_urls=optical_scene_meta.band_urls,
        )

        # 4b. Resample 30m DEM to 10m grid using bilinear/cubic interpolation
        aligned_dem = self.aligner.resample_and_align_dem(
            dem_urls=dem_meta.asset_urls,
            resampling_method_name=self.config.processing.dem_resampling_method,
        )

        # 4c. Verify pixel-for-pixel co-registration
        self.aligner.verify_co_registration(aligned_optical, aligned_dem)

        # ----------------------------------------------------------------------
        # Stage 5: Export Standardized GeoJSON & Cloud-Optimized GeoTIFFs
        # ----------------------------------------------------------------------
        self.logger.info("--> [5/5] Exporting Standardized Vector & Raster Artifacts...")

        # 5a. Export vectors
        exported_vector_paths = self.exporter.export_vector_layers(utm_vector_layers)

        # 5b. Export Optical COG
        optical_tags = {
            "SCENE_ID": optical_scene_meta.item_id,
            "ACQUISITION_DATETIME": optical_scene_meta.datetime,
            "CLOUD_COVER_PERCENT": f"{optical_scene_meta.cloud_cover:.2f}",
            "BANDS": ",".join(aligned_optical.band_names),
        }
        optical_cog_path = self.exporter.export_cog(
            raster_data=aligned_optical,
            filename=f"optical_sentinel2_10m_{self.config.region_name}.tif",
            metadata_tags=optical_tags,
        )

        # 5c. Export DEM COG
        dem_tags = {
            "SOURCE_COLLECTION": dem_meta.collection,
            "RESAMPLING_METHOD": self.config.processing.dem_resampling_method,
            "TARGET_RESOLUTION": f"{self.config.processing.target_pixel_size_meters}m",
        }
        dem_cog_path = self.exporter.export_cog(
            raster_data=aligned_dem,
            filename=f"dem_copernicus_10m_{self.config.region_name}.tif",
            metadata_tags=dem_tags,
        )

        elapsed_time = time.time() - start_time
        self.logger.info("=" * 80)
        self.logger.info(f"Pipeline Completed Successfully in {elapsed_time:.2f} seconds!")
        self.logger.info("=" * 80)

        # Compute summary statistics
        dem_valid = aligned_dem.data[0][aligned_dem.data[0] != -9999.0]
        dem_stats = {
            "min_elevation_m": float(dem_valid.min()) if len(dem_valid) > 0 else None,
            "max_elevation_m": float(dem_valid.max()) if len(dem_valid) > 0 else None,
            "mean_elevation_m": float(dem_valid.mean()) if len(dem_valid) > 0 else None,
        }

        vector_summary = {
            name: len(gdf) for name, gdf in utm_vector_layers.items()
        }

        return {
            "status": "SUCCESS",
            "region_name": self.config.region_name,
            "elapsed_seconds": round(elapsed_time, 2),
            "utm_epsg": self.utm_epsg,
            "grid_dimensions": {"width": self.grid_width, "height": self.grid_height},
            "optical_scene": {
                "id": optical_scene_meta.item_id,
                "cloud_cover_percent": optical_scene_meta.cloud_cover,
                "datetime": optical_scene_meta.datetime,
            },
            "dem_stats": dem_stats,
            "vector_feature_counts": vector_summary,
            "artifacts": {
                "vectors": {k: str(v) for k, v in exported_vector_paths.items()},
                "optical_cog": str(optical_cog_path),
                "dem_cog": str(dem_cog_path),
            },
        }

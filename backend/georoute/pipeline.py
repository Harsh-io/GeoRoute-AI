"""Master orchestration pipeline for GeoRoute AI: Part 1."""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

from georoute.config import PipelineConfig
from georoute.data_cache.cache_manager import DataCacheManager
from georoute.ingestion.protected_areas import ProtectedAreasIngestor
from georoute.ingestion.stac_raster_ingestor import STACRasterIngestor
from georoute.ingestion.vector_ingestor import OSMVectorIngestor
from georoute.processing.alignment import AlignedRasterData, SpatialAligner
from georoute.processing.cog_exporter import GeoDataExporter
from georoute.schemas.manifest_schema import (
    DatasetAttribution,
    GridDefinitionMetadata,
    MetadataManifest,
    RasterLayerMetadata,
    SpatialReferenceMetadata,
    VectorLayerMetadata,
)
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
            f"Defined Target Metric Grid: {self.grid_width}x{self.grid_height} pixels | "
            f"Resolution: {target_res}m | "
            f"UTM Bounds: {self.snapped_bounds}"
        )

        # 3. Instantiate sub-modules
        self.cache_manager = DataCacheManager()
        self.vector_ingestor = OSMVectorIngestor(
            timeout_seconds=self.config.vector.timeout_seconds,
            max_retries=self.config.vector.max_retries,
        )
        self.protected_areas_ingestor = ProtectedAreasIngestor(
            config=self.config.protected_areas,
            vector_ingestor=self.vector_ingestor,
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
            Dictionary containing execution statistics, manifest path, and exported artifact paths.
        """
        start_time = time.time()
        self.logger.info("Executing Part 1: Data Ingestion & Geospatial Preprocessing...")
        warnings: List[str] = []
        errors: List[str] = []

        # ----------------------------------------------------------------------
        # Stage 1: Vector Data Ingestion (OSM & Protected Areas)
        # ----------------------------------------------------------------------
        self.logger.info("--> [1/5] Ingesting vector features with local cache lookup...")
        aoi_polygon = self.config.bbox.as_polygon
        bbox_tuple = self.config.bbox.as_tuple
        raw_vector_layers: Dict[str, Any] = {}

        # 1a. Ingest standard OSM layers (highways, buildings, etc.)
        for layer_name, cfg in self.config.vector.layers.items():
            tags = cfg.tags if hasattr(cfg, "tags") else cfg.get("tags", {})
            cached_gdf = self.cache_manager.get_vector_layer(layer_name, bbox_tuple, tags)
            if cached_gdf is not None:
                raw_vector_layers[layer_name] = cached_gdf
            else:
                fetched_gdf = self.vector_ingestor.fetch_layer(layer_name, aoi_polygon, tags)
                self.cache_manager.save_vector_layer(layer_name, bbox_tuple, tags, fetched_gdf)
                raw_vector_layers[layer_name] = fetched_gdf

        # 1b. Ingest Protected Areas via dedicated adapter
        pa_provenance: Dict[str, Any] = {}
        if self.config.protected_areas.enabled:
            pa_layer_name = self.config.protected_areas.layer_name
            pa_gdf, pa_provenance = self.protected_areas_ingestor.fetch_layer(aoi_polygon)
            raw_vector_layers[pa_layer_name] = pa_gdf
            if pa_provenance.get("warning"):
                warnings.append(pa_provenance["warning"])

        # ----------------------------------------------------------------------
        # Stage 2: Vector Standardization & UTM Reprojection
        # ----------------------------------------------------------------------
        self.logger.info(f"--> [2/5] Reprojecting vector layers to EPSG:{self.utm_epsg}...")
        utm_vector_layers = self.aligner.reproject_vectors(raw_vector_layers)

        # ----------------------------------------------------------------------
        # Stage 3: STAC Catalog Search (Sentinel-2, Copernicus DEM, ESA WorldCover)
        # ----------------------------------------------------------------------
        self.logger.info("--> [3/5] Querying STAC catalog for Optical, DEM, and Land Cover assets...")

        # 3a. Optical Scene Search
        optical_scene_meta = self.stac_ingestor.search_optical_scene(
            bbox=bbox_tuple,
            date_range_str=self.config.temporal.date_range_string,
            bands=self.config.stac.optical.bands,
            max_cloud_cover_percent=self.config.stac.optical.max_cloud_cover_percent,
            collection=self.config.stac.optical.collection,
        )

        # 3b. DEM Search
        dem_meta = self.stac_ingestor.search_dem(
            bbox=bbox_tuple,
            collection=self.config.stac.elevation.collection,
            asset_name=self.config.stac.elevation.asset_name,
        )

        # 3c. Land Cover Search (ESA WorldCover)
        lc_meta = None
        if self.config.stac.land_cover.enabled:
            try:
                lc_meta = self.stac_ingestor.search_land_cover(
                    bbox=bbox_tuple,
                    collection=self.config.stac.land_cover.collection,
                    asset_name=self.config.stac.land_cover.asset_name,
                    year=self.config.stac.land_cover.year,
                )
            except Exception as e:
                self.logger.warning(f"Land cover retrieval warning: {e}")
                warnings.append(f"Land cover layer unavailable: {e}")

        # ----------------------------------------------------------------------
        # Stage 4: Raster Co-Registration & Resampling
        # ----------------------------------------------------------------------
        self.logger.info("--> [4/5] Warping and Co-Registering Rasters onto Master Grid...")
        aligned_rasters: Dict[str, AlignedRasterData] = {}

        # 4a. Resample optical bands (continuous: bilinear)
        aligned_optical = self.aligner.resample_and_align_optical(
            band_urls=optical_scene_meta.band_urls,
        )
        aligned_rasters["optical"] = aligned_optical

        # 4b. Resample 30m DEM (continuous: bilinear/cubic)
        aligned_dem = self.aligner.resample_and_align_dem(
            dem_urls=dem_meta.asset_urls,
            resampling_method_name=self.config.processing.dem_resampling_method,
        )
        aligned_rasters["dem"] = aligned_dem

        # 4c. Resample Land Cover (categorical: nearest-neighbor)
        aligned_lc = None
        if lc_meta:
            aligned_lc = self.aligner.resample_and_align_land_cover(
                lc_urls=lc_meta.asset_urls,
            )
            aligned_rasters["land_cover"] = aligned_lc

        # 4d. Rigorous Multi-Layer Co-Registration Audit
        SpatialAligner.verify_multi_co_registration(aligned_rasters)

        # ----------------------------------------------------------------------
        # Stage 5: Export Standardized GeoJSON, COGs & Metadata Manifest
        # ----------------------------------------------------------------------
        self.logger.info("--> [5/5] Exporting Standardized Artifacts & Generating Metadata Manifest...")

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
            overview_resampling="average",
        )

        # 5c. Export DEM COG
        dem_tags = {
            "SOURCE_COLLECTION": dem_meta.collection,
            "RESAMPLING_METHOD": self.config.processing.dem_resampling_method,
            "TARGET_RESOLUTION": f"{self.config.processing.target_pixel_size_meters}m",
        }
        dem_cog_path = self.exporter.export_cog(
            raster_data=aligned_dem,
            filename=f"dem_copernicus_{int(self.config.processing.target_pixel_size_meters)}m_{self.config.region_name}.tif",
            metadata_tags=dem_tags,
            overview_resampling="average",
        )

        # 5d. Export Land Cover COG (if present, using nearest overview resampling)
        lc_cog_path = None
        if aligned_lc:
            lc_tags = {
                "SOURCE_COLLECTION": lc_meta.collection if lc_meta else "esa-worldcover",
                "RESAMPLING_METHOD": "nearest",
                "TARGET_RESOLUTION": f"{self.config.processing.target_pixel_size_meters}m",
            }
            lc_cog_path = self.exporter.export_cog(
                raster_data=aligned_lc,
                filename=f"landcover_worldcover_{int(self.config.processing.target_pixel_size_meters)}m_{self.config.region_name}.tif",
                metadata_tags=lc_tags,
                overview_resampling="nearest",
            )

        elapsed_time = time.time() - start_time
        self.logger.info("=" * 80)
        self.logger.info(f"Pipeline Execution Completed in {elapsed_time:.2f} seconds!")
        self.logger.info("=" * 80)

        # ----------------------------------------------------------------------
        # Stage 6: Build Machine-Readable Metadata Manifest
        # ----------------------------------------------------------------------
        manifest_path = Path(self.config.export.output_dir) / "metadata_manifest.json"

        # Bounds dicts
        bounds_wgs84 = {
            "min_lon": self.config.bbox.min_lon,
            "min_lat": self.config.bbox.min_lat,
            "max_lon": self.config.bbox.max_lon,
            "max_lat": self.config.bbox.max_lat,
        }
        bounds_projected = {
            "minx": float(self.snapped_bounds[0]),
            "miny": float(self.snapped_bounds[1]),
            "maxx": float(self.snapped_bounds[2]),
            "maxy": float(self.snapped_bounds[3]),
        }

        # Raster metadata dictionary
        raster_manifest_entries: Dict[str, RasterLayerMetadata] = {}

        # Optical entry
        raster_manifest_entries["optical"] = RasterLayerMetadata(
            layer_name="optical",
            file_path=str(optical_cog_path),
            source_collection=self.config.stac.optical.collection,
            source_item_ids=[optical_scene_meta.item_id],
            crs=f"EPSG:{self.utm_epsg}",
            width=self.grid_width,
            height=self.grid_height,
            bands=len(aligned_optical.band_names),
            band_names=aligned_optical.band_names,
            dtype=str(aligned_optical.dtype),
            nodata=aligned_optical.nodata,
            resolution_meters=self.config.processing.target_pixel_size_meters,
            transform=list(aligned_optical.transform)[:6],
            bounds_projected=bounds_projected,
            resampling_method="bilinear",
        )

        # DEM entry
        dem_valid = aligned_dem.data[0][aligned_dem.data[0] != -9999.0]
        raster_manifest_entries["dem"] = RasterLayerMetadata(
            layer_name="dem",
            file_path=str(dem_cog_path),
            source_collection=dem_meta.collection,
            source_item_ids=dem_meta.item_ids,
            crs=f"EPSG:{self.utm_epsg}",
            width=self.grid_width,
            height=self.grid_height,
            bands=1,
            band_names=aligned_dem.band_names,
            dtype=str(aligned_dem.dtype),
            nodata=aligned_dem.nodata,
            resolution_meters=self.config.processing.target_pixel_size_meters,
            transform=list(aligned_dem.transform)[:6],
            bounds_projected=bounds_projected,
            resampling_method=self.config.processing.dem_resampling_method,
            min_value=float(dem_valid.min()) if len(dem_valid) > 0 else None,
            max_value=float(dem_valid.max()) if len(dem_valid) > 0 else None,
            mean_value=float(dem_valid.mean()) if len(dem_valid) > 0 else None,
        )

        # Land Cover entry
        if aligned_lc and lc_cog_path:
            raster_manifest_entries["land_cover"] = RasterLayerMetadata(
                layer_name="land_cover",
                file_path=str(lc_cog_path),
                source_collection=lc_meta.collection if lc_meta else "esa-worldcover",
                source_item_ids=lc_meta.item_ids if lc_meta else [],
                crs=f"EPSG:{self.utm_epsg}",
                width=self.grid_width,
                height=self.grid_height,
                bands=1,
                band_names=aligned_lc.band_names,
                dtype=str(aligned_lc.dtype),
                nodata=aligned_lc.nodata,
                resolution_meters=self.config.processing.target_pixel_size_meters,
                transform=list(aligned_lc.transform)[:6],
                bounds_projected=bounds_projected,
                resampling_method="nearest",
            )

        # Vector metadata dictionary
        vector_manifest_entries: Dict[str, VectorLayerMetadata] = {}
        for name, p in exported_vector_paths.items():
            gdf = utm_vector_layers.get(name)
            geom_types = list(set(gdf.geometry.geom_type)) if gdf is not None and not gdf.empty else []
            cols = [c for c in gdf.columns if c != "geometry"] if gdf is not None else []
            vector_manifest_entries[name] = VectorLayerMetadata(
                layer_name=name,
                file_path=str(p),
                source="OpenStreetMap Overpass API" if name != self.config.protected_areas.layer_name else pa_provenance.get("source_name", "OSM"),
                feature_count=len(gdf) if gdf is not None else 0,
                crs=f"EPSG:{self.utm_epsg}",
                bounds_projected=bounds_projected,
                geometry_types=geom_types,
                attributes=cols,
                sanitized=True,
            )

        # Attribution dictionary
        attributions = {
            "sentinel_2": DatasetAttribution(
                dataset_name="Sentinel-2 L2A Harmonized Optical Imagery",
                source_identifier="sentinel-2-l2a",
                license="CC-BY 4.0 / Copernicus Open Access",
                attribution="European Space Agency / Copernicus Programme / Microsoft Planetary Computer",
                url="https://planetarycomputer.microsoft.com/dataset/sentinel-2-l2a",
            ),
            "copernicus_dem": DatasetAttribution(
                dataset_name="Copernicus 30m Global Digital Elevation Model",
                source_identifier="cop-dem-glo-30",
                license="Copernicus WorldDEM-30 Open License",
                attribution="European Space Agency / Airbus / Microsoft Planetary Computer",
                url="https://planetarycomputer.microsoft.com/dataset/cop-dem-glo-30",
            ),
            "openstreetmap": DatasetAttribution(
                dataset_name="OpenStreetMap Volunteered Geographic Vector Data",
                source_identifier="osm-overpass",
                license="Open Data Commons Open Database License (ODbL) 1.0",
                attribution="© OpenStreetMap contributors (via OSMnx & Overpass API)",
                url="https://www.openstreetmap.org/copyright",
            ),
        }
        if lc_meta:
            attributions["esa_worldcover"] = DatasetAttribution(
                dataset_name="ESA WorldCover 10m Global Land Cover",
                source_identifier="esa-worldcover",
                license="Creative Commons Attribution 4.0 International (CC-BY 4.0)",
                attribution="European Space Agency (ESA) WorldCover Project / Microsoft Planetary Computer",
                url="https://planetarycomputer.microsoft.com/dataset/esa-worldcover",
            )

        # Construct and serialize manifest
        manifest = MetadataManifest(
            manifest_id=f"manifest_{self.config.region_name}_{int(time.time())}",
            region_name=self.config.region_name,
            pipeline_status="SUCCESS",
            elapsed_seconds=round(elapsed_time, 2),
            spatial_reference=SpatialReferenceMetadata(
                input_crs="EPSG:4326",
                target_crs=f"EPSG:{self.utm_epsg}",
                target_utm_epsg=self.utm_epsg,
                bounds_wgs84=bounds_wgs84,
                bounds_projected=bounds_projected,
            ),
            target_grid=GridDefinitionMetadata(
                width=self.grid_width,
                height=self.grid_height,
                resolution_meters=self.config.processing.target_pixel_size_meters,
                transform=list(self.target_transform)[:6],
                snapped=True,
            ),
            rasters=raster_manifest_entries,
            vectors=vector_manifest_entries,
            attributions=attributions,
            warnings=warnings,
            errors=errors,
        )

        manifest.to_json_file(str(manifest_path))
        self.logger.info(f"Machine-readable metadata manifest saved: {manifest_path}")

        # Summary statistics
        dem_stats = {
            "min_elevation_m": float(dem_valid.min()) if len(dem_valid) > 0 else None,
            "max_elevation_m": float(dem_valid.max()) if len(dem_valid) > 0 else None,
            "mean_elevation_m": float(dem_valid.mean()) if len(dem_valid) > 0 else None,
        }
        vector_summary = {name: len(gdf) for name, gdf in utm_vector_layers.items()}

        artifacts_dict: Dict[str, Any] = {
            "vectors": {k: str(v) for k, v in exported_vector_paths.items()},
            "optical_cog": str(optical_cog_path),
            "dem_cog": str(dem_cog_path),
            "manifest_json": str(manifest_path),
        }
        if lc_cog_path:
            artifacts_dict["landcover_cog"] = str(lc_cog_path)

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
            "artifacts": artifacts_dict,
            "warnings": warnings,
        }

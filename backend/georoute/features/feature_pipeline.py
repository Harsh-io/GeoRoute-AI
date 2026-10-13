"""Master feature extraction pipeline for GeoRoute AI: Part 2.

Orchestrates the conversion of Part 1 validated geospatial data into clean,
classified, spatially aligned constraint layers for downstream routing:
1. Slope calculation (degrees and uncapped percent via Horn's method)
2. Land-cover classification (ESA WorldCover masks and distribution metrics)
3. Optical Sentinel-2 cross-validation (NDVI computation)
4. Physical obstacle extraction and rasterization (buildings, waterways, infrastructure)
5. Environmental and statutory protected area extraction and forest separation
6. Co-registration auditing, COG export, and features_manifest.json generation.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import Affine, array_bounds

from georoute.features.environmental_extractor import EnvironmentalExtractor
from georoute.features.land_cover_classifier import LandCoverClassifier
from georoute.features.obstacle_extractor import ObstacleExtractor
from georoute.features.rasterizer import GeoRasterizer
from georoute.features.slope_calculator import SlopeCalculator
from georoute.processing.alignment import AlignedRasterData
from georoute.processing.cog_exporter import GeoDataExporter
from georoute.schemas.features_manifest_schema import (
    DeliverableItem,
    FeatureRasterLayerMetadata,
    FeatureVectorLayerMetadata,
    FeaturesManifest,
)

logger = logging.getLogger("georoute.features.pipeline")


def compute_file_sha256(path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_json_safe(data: Any, dest_path: Path) -> None:
    """Serializes data to JSON handling numpy types safely."""
    def default_handler(obj):
        if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8, np.uint8, np.uint16, np.uint32)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float32, np.float64)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return str(obj)

    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=default_handler)



class FeaturePipeline:
    """Orchestrates Part 2 Feature Extraction and Constraint Layer Generation."""

    def __init__(
        self,
        processed_dir: Union[str, Path] = "data/processed",
        output_dir: Union[str, Path] = "data/features",
        authoritative_pa_path: Optional[Union[str, Path]] = "data/vector/protected_areas.geojson",
        custom_logger: Optional[logging.Logger] = None,
    ):
        """Initializes the feature pipeline.

        Args:
            processed_dir: Directory containing Part 1 validated outputs.
            output_dir: Destination directory for Part 2 feature deliverables.
            authoritative_pa_path: Path to authoritative protected areas dataset.
            custom_logger: Optional pre-configured logger.
        """
        self.processed_dir = Path(processed_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.authoritative_pa_path = Path(authoritative_pa_path) if authoritative_pa_path else None
        self.logger = custom_logger or logger

    def find_input_file(
        self,
        pattern: str,
        subfolder: str = "rasters",
        region_name: Optional[str] = None,
    ) -> Optional[Path]:
        """Finds the best matching file in processed subfolder, prioritizing region_name and non-mock files."""
        search_dir = self.processed_dir / subfolder
        if not search_dir.exists():
            return None

        matches = list(search_dir.glob(pattern))
        if not matches:
            return None

        # Prioritize matching region_name
        if region_name:
            region_matches = [m for m in matches if region_name.lower() in m.name.lower()]
            if region_matches:
                matches = region_matches

        # Deprioritize mock files if non-mock files exist
        non_mock = [m for m in matches if "mock" not in m.name.lower()]
        if non_mock:
            return non_mock[0]

        return matches[0]


    def run(self, region_name: str = "mandi_terminal_5x5km") -> FeaturesManifest:
        """Executes the full Part 2 feature extraction pipeline.

        Args:
            region_name: Identifier for the study area.

        Returns:
            Validated FeaturesManifest object.
        """
        start_time = time.time()
        self.logger.info("=" * 80)
        self.logger.info(f"Starting GeoRoute AI Feature Extraction Pipeline (Part 2) for AOI: '{region_name}'")
        self.logger.info(f"Input Processed Directory: {self.processed_dir}")
        self.logger.info(f"Output Features Directory: {self.output_dir}")
        self.logger.info("=" * 80)

        warnings: List[str] = []
        errors: List[str] = []

        # ----------------------------------------------------------------------
        # 1. Locate and Load Reference DEM
        # ----------------------------------------------------------------------
        dem_path = self.find_input_file("*dem*.tif", "rasters", region_name=region_name)
        if not dem_path or not dem_path.exists():
            raise FileNotFoundError(f"Required DEM raster not found in {self.processed_dir}/rasters")

        self.logger.info(f"Loading reference DEM from: {dem_path.name}")
        with rasterio.open(dem_path) as src:
            dem_data = src.read(1)
            target_shape = (src.height, src.width)
            target_transform = src.transform
            target_crs = src.crs
            dem_nodata = float(src.nodata) if src.nodata is not None else -9999.0

        dx = abs(target_transform.a)
        dy = abs(target_transform.e)
        self.logger.info(
            f"Reference grid: {target_shape[1]}x{target_shape[0]} px, CRS={target_crs}, "
            f"resolution=({dx:.1f}m, {dy:.1f}m), nodata={dem_nodata}"
        )

        rasterizer = GeoRasterizer(target_shape=target_shape, target_transform=target_transform, target_crs=target_crs)
        exporter = GeoDataExporter(output_dir=self.output_dir, compression="deflate")

        # ----------------------------------------------------------------------
        # 2. Slope Calculation
        # ----------------------------------------------------------------------
        self.logger.info("Calculating terrain slope (degrees and uncapped percent) via Horn's method...")
        slope_deg, slope_pct = SlopeCalculator.calculate(
            dem_data,
            cell_resolution=(dx, dy),
            nodata=dem_nodata,
            output_nodata=-9999.0,
        )
        slope_metrics = SlopeCalculator.compute_summary_stats(slope_deg, slope_pct, nodata=-9999.0)
        self.logger.info(
            f"Slope computed. Degrees mean={slope_metrics['slope_degrees']['mean']:.2f}°, "
            f"Percent mean={slope_metrics['slope_percent']['mean']:.2f}%, "
            f">20% slope={slope_metrics['slope_percent']['percentage_gt_20']:.2f}%"
        )

        # ----------------------------------------------------------------------
        # 3. Land Cover Feature Extraction
        # ----------------------------------------------------------------------
        lc_path = self.find_input_file("*landcover*.tif", "rasters", region_name=region_name) or self.find_input_file("*worldcover*.tif", "rasters", region_name=region_name)
        lc_classifier = LandCoverClassifier(target_shape=target_shape, cell_resolution=(dx, dy))
        lc_masks: Dict[str, np.ndarray] = {}
        lc_summary: Dict[str, Any] = {}
        lc_data: Optional[np.ndarray] = None

        if lc_path and lc_path.exists():
            self.logger.info(f"Loading ESA WorldCover raster from: {lc_path.name}")
            with rasterio.open(lc_path) as src:
                lc_data = src.read(1)
            lc_masks = lc_classifier.extract_class_masks(lc_data, nodata=0.0)
            lc_summary = lc_classifier.compute_summary(lc_data, nodata=0.0)
        else:
            warnings.append("No landcover raster found. Using empty landcover masks.")
            lc_masks = lc_classifier.extract_class_masks(np.zeros(target_shape, dtype=np.uint8), nodata=0.0)
            lc_summary = lc_classifier.compute_summary(np.zeros(target_shape, dtype=np.uint8), nodata=0.0)

        # Save landcover JSONs
        lc_summary_path = self.output_dir / "landcover_summary.json"
        dump_json_safe(lc_summary, lc_summary_path)

        lc_mapping_path = self.output_dir / "landcover_class_mapping.json"
        dump_json_safe(lc_classifier.get_class_mapping(), lc_mapping_path)



        # ----------------------------------------------------------------------
        # 4. Optical Cross-Validation (Sentinel-2 NDVI)
        # ----------------------------------------------------------------------
        optical_path = self.find_input_file("*optical*.tif", "rasters", region_name=region_name) or self.find_input_file("*sentinel2*.tif", "rasters", region_name=region_name)
        optical_validation: Dict[str, Any] = {}
        ndvi_array: Optional[np.ndarray] = None

        if optical_path and optical_path.exists() and lc_data is not None:
            self.logger.info(f"Loading Sentinel-2 optical raster for NDVI validation from: {optical_path.name}")
            with rasterio.open(optical_path) as src:
                optical_data = src.read()  # Shape: (bands, H, W)
            ndvi_array = LandCoverClassifier.compute_ndvi(optical_data, red_band_idx=0, nir_band_idx=3)
            optical_validation = lc_classifier.validate_with_optical(lc_data, optical_data)
            self.logger.info(
                f"NDVI validation complete. Plausibility passed: {optical_validation.get('plausibility_passed')}"
            )
        else:
            self.logger.warning("Optical raster not found. Skipping NDVI cross-validation.")

        # ----------------------------------------------------------------------
        # 5. Physical Obstacle Extraction
        # ----------------------------------------------------------------------
        self.logger.info("Extracting and standardizing physical obstacles...")
        v_dir = self.processed_dir / "vectors"

        def load_gdf_safe(fname: str) -> Optional[gpd.GeoDataFrame]:
            p = v_dir / fname
            if p.exists():
                try:
                    return gpd.read_file(p)
                except Exception as e:
                    self.logger.warning(f"Error loading {fname}: {e}")
            return None

        bldgs_gdf = load_gdf_safe("buildings.geojson")
        waterways_gdf = load_gdf_safe("waterways.geojson")
        railways_gdf = load_gdf_safe("railways.geojson")
        highways_gdf = load_gdf_safe("highways.geojson")

        obstacle_extractor = ObstacleExtractor(rasterizer=rasterizer)
        physical_obstacles_gdf, obstacle_masks = obstacle_extractor.extract_obstacles(
            buildings_gdf=bldgs_gdf,
            waterways_gdf=waterways_gdf,
            railways_gdf=railways_gdf,
            highways_gdf=highways_gdf,
            landcover_array=lc_data,
            water_class_value=80,
        )

        # ----------------------------------------------------------------------
        # 6. Environmental and Statutory Protected Areas
        # ----------------------------------------------------------------------
        self.logger.info("Extracting statutory protected areas and analyzing forest separation...")
        auth_pa_gdf: Optional[gpd.GeoDataFrame] = None
        if self.authoritative_pa_path and self.authoritative_pa_path.exists():
            try:
                auth_pa_gdf = gpd.read_file(self.authoritative_pa_path)
                self.logger.info(f"Loaded {len(auth_pa_gdf)} authoritative protected areas.")
            except Exception as e:
                self.logger.warning(f"Error reading authoritative protected areas: {e}")

        osm_env_gdf = load_gdf_safe("environmental_zones.geojson")
        env_extractor = EnvironmentalExtractor(rasterizer=rasterizer)
        environmental_zones_gdf, env_masks, env_metrics = env_extractor.extract_environmental_layers(
            authoritative_pa_gdf=auth_pa_gdf,
            osm_env_gdf=osm_env_gdf,
            forest_mask=lc_masks.get("forest_mask"),
        )

        # ----------------------------------------------------------------------
        # 7. Export Standardized Vectors
        # ----------------------------------------------------------------------
        self.logger.info("Exporting standardized vector layers...")
        vector_exports = exporter.export_vector_layers({
            "physical_obstacles": physical_obstacles_gdf,
            "environmental_zones": environmental_zones_gdf,
        })

        # ----------------------------------------------------------------------
        # 8. Export Cloud-Optimized GeoTIFFs (COGs)
        # ----------------------------------------------------------------------
        self.logger.info("Exporting Cloud-Optimized GeoTIFFs (COGs) for constraint layers...")
        rasters_to_export: Dict[str, AlignedRasterData] = {}

        # Continuous rasters
        rasters_to_export["slope_degrees.tif"] = AlignedRasterData(
            data=slope_deg[np.newaxis, :, :],
            transform=target_transform,
            crs=target_crs,
            nodata=-9999.0,
            band_names=["slope_degrees"],
            dtype=np.float32,
        )
        rasters_to_export["slope_percent.tif"] = AlignedRasterData(
            data=slope_pct[np.newaxis, :, :],
            transform=target_transform,
            crs=target_crs,
            nodata=-9999.0,
            band_names=["slope_percent"],
            dtype=np.float32,
        )

        if ndvi_array is not None:
            rasters_to_export["ndvi.tif"] = AlignedRasterData(
                data=ndvi_array[np.newaxis, :, :],
                transform=target_transform,
                crs=target_crs,
                nodata=-9999.0,
                band_names=["ndvi"],
                dtype=np.float32,
            )

        if lc_data is not None:
            rasters_to_export["classified_landcover.tif"] = AlignedRasterData(
                data=lc_data[np.newaxis, :, :],
                transform=target_transform,
                crs=target_crs,
                nodata=0.0,
                band_names=["classified_landcover"],
                dtype=np.uint8,
            )

        # Discrete / binary masks (uint8, nodata=255)
        binary_mask_layers = {
            "forest_mask.tif": lc_masks["forest_mask"],
            "wetland_mask.tif": lc_masks["wetland_mask"],
            "cropland_mask.tif": lc_masks["cropland_mask"],
            "builtup_mask.tif": lc_masks["builtup_mask"],
            "building_mask.tif": obstacle_masks["building_mask"],
            "water_mask.tif": obstacle_masks["water_mask"],
            "railway_mask.tif": obstacle_masks["railway_mask"],
            "highway_mask.tif": obstacle_masks["highway_mask"],
            "combined_obstacle_mask.tif": obstacle_masks["combined_obstacle_mask"],
            "protected_area_mask.tif": env_masks["protected_area_mask"],
        }

        for filename, mask_arr in binary_mask_layers.items():
            band_name = filename.replace(".tif", "")
            rasters_to_export[filename] = AlignedRasterData(
                data=mask_arr[np.newaxis, :, :],
                transform=target_transform,
                crs=target_crs,
                nodata=255.0,
                band_names=[band_name],
                dtype=np.uint8,
            )

        exported_rasters: Dict[str, Path] = {}
        for fname, r_data in rasters_to_export.items():
            exported_rasters[fname] = exporter.export_cog(r_data, filename=fname)

        # ----------------------------------------------------------------------
        # 9. Co-Registration Audit and Manifest Compilation
        # ----------------------------------------------------------------------
        self.logger.info("Performing strict co-registration and spatial alignment verification...")
        raster_manifest_entries: Dict[str, FeatureRasterLayerMetadata] = {}

        minx, miny, maxx, maxy = array_bounds(target_shape[0], target_shape[1], target_transform)
        bounds_projected = {"min_x": minx, "min_y": miny, "max_x": maxx, "max_y": maxy}

        for fname, r_path in exported_rasters.items():
            sha256_hash = compute_file_sha256(r_path)
            with rasterio.open(r_path) as src:
                # Rigorous co-registration check
                shape_match = (src.height, src.width) == target_shape
                crs_match = src.crs == target_crs
                transform_match = np.allclose(
                    [src.transform.a, src.transform.b, src.transform.c, src.transform.d, src.transform.e, src.transform.f],
                    [target_transform.a, target_transform.b, target_transform.c, target_transform.d, target_transform.e, target_transform.f],
                    atol=1e-5,
                )
                alignment_verified = shape_match and crs_match and transform_match

                band1 = src.read(1)
                nodata_v = src.nodata

                if np.issubdtype(band1.dtype, np.floating):
                    valid_pixels = band1[band1 != nodata_v] if nodata_v is not None else band1
                    min_val = float(np.min(valid_pixels)) if len(valid_pixels) > 0 else None
                    max_val = float(np.max(valid_pixels)) if len(valid_pixels) > 0 else None
                    mean_val = float(np.mean(valid_pixels)) if len(valid_pixels) > 0 else None
                    fg_pixels = None
                    fg_pct = None
                else:
                    # Discrete / binary mask
                    min_val = float(np.min(band1))
                    max_val = float(np.max(band1))
                    mean_val = float(np.mean(band1))
                    fg_pixels = int(np.count_nonzero(band1 == 1))
                    total_px = target_shape[0] * target_shape[1]
                    fg_pct = round(fg_pixels / total_px * 100.0, 4)

                layer_key = fname.replace(".tif", "")
                raster_manifest_entries[layer_key] = FeatureRasterLayerMetadata(
                    layer_name=layer_key,
                    file_path=str(r_path.relative_to(self.output_dir.parent)),
                    crs=str(src.crs),
                    width=src.width,
                    height=src.height,
                    bands=src.count,
                    band_names=list(src.descriptions) if any(src.descriptions) else [layer_key],
                    dtype=str(src.dtypes[0]),
                    nodata=float(nodata_v) if nodata_v is not None else None,
                    resolution_meters=dx,
                    transform=[src.transform.a, src.transform.b, src.transform.c, src.transform.d, src.transform.e, src.transform.f],
                    bounds_projected=bounds_projected,
                    sha256=sha256_hash,
                    spatial_alignment_verified=alignment_verified,
                    min_value=min_val,
                    max_value=max_val,
                    mean_value=mean_val,
                    foreground_pixels=fg_pixels,
                    foreground_percentage=fg_pct,
                )

        vector_manifest_entries: Dict[str, FeatureVectorLayerMetadata] = {}
        for v_name, v_path in vector_exports.items():
            v_sha = compute_file_sha256(v_path)
            v_gdf = gpd.read_file(v_path)
            v_bounds = v_gdf.total_bounds if len(v_gdf) > 0 else [minx, miny, maxx, maxy]
            geom_types = list(v_gdf.geometry.geom_type.unique()) if len(v_gdf) > 0 else []

            vector_manifest_entries[v_name] = FeatureVectorLayerMetadata(
                layer_name=v_name,
                file_path=str(v_path.relative_to(self.output_dir.parent)),
                feature_count=len(v_gdf),
                crs=str(v_gdf.crs),
                bounds_projected={
                    "min_x": float(v_bounds[0]),
                    "min_y": float(v_bounds[1]),
                    "max_x": float(v_bounds[2]),
                    "max_y": float(v_bounds[3]),
                },
                geometry_types=geom_types,
                attributes=list(v_gdf.columns),
                sha256=v_sha,
            )

        deliverables_map = {
            "slope_in_degrees_and_percent": DeliverableItem(
                deliverable="Slope in degrees and percent",
                why_it_matters="Supplies terrain measurements for later cost modeling",
                artifacts=[
                    "features/rasters/slope_degrees.tif",
                    "features/rasters/slope_percent.tif",
                ],
                status="VALIDATED",
            ),
            "cleaned_building_and_waterway_vectors": DeliverableItem(
                deliverable="Cleaned building and waterway vectors",
                why_it_matters="Provides mapped physical-feature information",
                artifacts=[
                    "features/vectors/physical_obstacles.geojson",
                ],
                status="VALIDATED",
            ),
            "aligned_obstacle_masks": DeliverableItem(
                deliverable="Aligned obstacle masks",
                why_it_matters="Makes features usable in the same raster grid",
                artifacts=[
                    "features/rasters/building_mask.tif",
                    "features/rasters/water_mask.tif",
                    "features/rasters/railway_mask.tif",
                    "features/rasters/highway_mask.tif",
                    "features/rasters/combined_obstacle_mask.tif",
                ],
                status="VALIDATED",
            ),
            "classified_land_cover_raster": DeliverableItem(
                deliverable="Classified land-cover raster",
                why_it_matters="Distinguishes land-cover types without inventing cost weights",
                artifacts=[
                    "features/rasters/classified_landcover.tif",
                    "features/landcover_summary.json",
                    "features/landcover_class_mapping.json",
                ],
                status="VALIDATED",
            ),
            "environmental_layers": DeliverableItem(
                deliverable="Environmental layers",
                why_it_matters="Supplies available forest, wetland, and protected-area information",
                artifacts=[
                    "features/rasters/forest_mask.tif",
                    "features/rasters/wetland_mask.tif",
                    "features/rasters/protected_area_mask.tif",
                    "features/vectors/environmental_zones.geojson",
                ],
                status="VALIDATED",
            ),
            "manifest_and_validation_report": DeliverableItem(
                deliverable="Manifest and validation report",
                why_it_matters="Lets Part 3 consume the outputs without guessing",
                artifacts=[
                    "features/features_manifest.json",
                ],
                status="VALIDATED",
            ),
        }

        elapsed = round(time.time() - start_time, 2)
        manifest = FeaturesManifest(
            schema_version="2.0.0",
            manifest_id=f"MANIFEST_PART2_{region_name.upper()}_{int(time.time())}",
            generated_at=datetime.now(timezone.utc).isoformat(),
            region_name=region_name,
            pipeline_status="SUCCESS",
            elapsed_seconds=elapsed,
            spatial_reference={
                "target_crs": str(target_crs),
                "resolution_meters": dx,
                "bounds_projected": bounds_projected,
            },
            target_grid={
                "width": target_shape[1],
                "height": target_shape[0],
                "resolution_meters": dx,
                "transform": [target_transform.a, target_transform.b, target_transform.c, target_transform.d, target_transform.e, target_transform.f],
            },
            deliverables=deliverables_map,
            rasters=raster_manifest_entries,
            vectors=vector_manifest_entries,
            landcover_summary=lc_summary,
            optical_validation=optical_validation,
            environmental_metrics=env_metrics,
            slope_metrics=slope_metrics,
            warnings=warnings,
            errors=errors,
        )

        manifest_path = self.output_dir / "features_manifest.json"
        manifest.to_json_file(manifest_path)
        self.logger.info(f"Machine-readable features manifest saved: {manifest_path}")
        self.logger.info(f"Part 2 Pipeline completed successfully in {elapsed} seconds.")

        return manifest


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    pipe = FeaturePipeline()
    manifest = pipe.run()
    print(f"Features Manifest Generated: {manifest.manifest_id}")

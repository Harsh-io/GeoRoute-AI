"""Cloud-Optimized GeoTIFF (COG) and standardized vector export module."""

import logging
from pathlib import Path
from typing import Dict, List, Optional
import geopandas as gpd
import rasterio
from rasterio.enums import Resampling
from georoute.processing.alignment import AlignedRasterData

logger = logging.getLogger("georoute.exporter")


class GeoDataExporter:
    """Handles standard export of aligned vector and raster assets."""

    def __init__(
        self,
        output_dir: Path,
        block_size: int = 256,
        compression: str = "deflate",
        overview_levels: Optional[List[int]] = None,
    ):
        """Initializes the export manager.

        Args:
            output_dir: Directory where final processed artifacts will be stored.
            block_size: Tile block size for COGs (256 or 512).
            compression: Compression algorithm ('deflate', 'lzw', 'zstd').
            overview_levels: Power-of-two overview decimation levels.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.block_size = block_size
        self.compression = compression
        self.overview_levels = overview_levels or [2, 4, 8, 16]

    # --------------------------------------------------------------------------
    # Vector GeoJSON Export
    # --------------------------------------------------------------------------
    def export_vector_layers(
        self,
        vector_layers: Dict[str, gpd.GeoDataFrame],
    ) -> Dict[str, Path]:
        """Exports reprojected GeoDataFrames to standardized RFC 7946 GeoJSON files.

        Args:
            vector_layers: Mapping of layer name to reprojected GeoDataFrame.

        Returns:
            Dictionary of layer names mapped to the saved GeoJSON file paths.
        """
        exported_paths: Dict[str, Path] = {}
        vector_dir = self.output_dir / "vectors"
        vector_dir.mkdir(parents=True, exist_ok=True)

        for layer_name, gdf in vector_layers.items():
            dest_file = vector_dir / f"{layer_name}.geojson"
            logger.info(
                f"Exporting vector layer '{layer_name}' ({len(gdf)} features) to: {dest_file}"
            )
            # Ensure valid GeoJSON driver write
            gdf.to_file(dest_file, driver="GeoJSON")
            exported_paths[layer_name] = dest_file

        return exported_paths

    # --------------------------------------------------------------------------
    # Raster Cloud Optimized GeoTIFF (COG) Export
    # --------------------------------------------------------------------------
    def export_cog(
        self,
        raster_data: AlignedRasterData,
        filename: str,
        metadata_tags: Optional[Dict[str, str]] = None,
    ) -> Path:
        """Writes an aligned raster array to a Cloud Optimized GeoTIFF (COG).

        Uses GDAL's native COG driver when available, with a resilient fallback
        to tiled GeoTIFF with built-in internal overviews.

        Args:
            raster_data: AlignedRasterData container holding arrays and metadata.
            filename: Destination filename (e.g. 'optical_sentinel2_10m.tif').
            metadata_tags: Optional key-value dictionary of metadata tags to embed.

        Returns:
            Path to the generated Cloud Optimized GeoTIFF.
        """
        raster_dir = self.output_dir / "rasters"
        raster_dir.mkdir(parents=True, exist_ok=True)
        dest_path = raster_dir / filename

        count, height, width = raster_data.data.shape

        logger.info(
            f"Writing Cloud-Optimized GeoTIFF: {dest_path.name} "
            f"({width}x{height} px, {count} band(s), compression={self.compression})..."
        )

        with rasterio.Env() as env:
            drivers = env.drivers()
            use_native_cog = "COG" in drivers

        if use_native_cog:
            # Native GDAL COG driver configuration
            cog_profile = {
                "driver": "COG",
                "height": height,
                "width": width,
                "count": count,
                "dtype": raster_data.dtype,
                "crs": raster_data.crs,
                "transform": raster_data.transform,
                "nodata": raster_data.nodata,
                "compress": self.compression,
                "blocksize": self.block_size,
                "overview_resampling": "average",
            }
            with rasterio.open(dest_path, "w", **cog_profile) as dst:
                for b_idx in range(count):
                    dst.write(raster_data.data[b_idx], b_idx + 1)
                    if b_idx < len(raster_data.band_names):
                        dst.set_band_description(b_idx + 1, raster_data.band_names[b_idx])
                if metadata_tags:
                    dst.update_tags(**metadata_tags)
        else:
            # Fallback: Tiled GTiff with internal overviews
            gtiff_profile = {
                "driver": "GTiff",
                "height": height,
                "width": width,
                "count": count,
                "dtype": raster_data.dtype,
                "crs": raster_data.crs,
                "transform": raster_data.transform,
                "nodata": raster_data.nodata,
                "compress": self.compression,
                "tiled": True,
                "blockxsize": self.block_size,
                "blockysize": self.block_size,
            }
            with rasterio.open(dest_path, "w", **gtiff_profile) as dst:
                for b_idx in range(count):
                    dst.write(raster_data.data[b_idx], b_idx + 1)
                    if b_idx < len(raster_data.band_names):
                        dst.set_band_description(b_idx + 1, raster_data.band_names[b_idx])
                if metadata_tags:
                    dst.update_tags(**metadata_tags)
                
                # Build internal overviews
                dst.build_overviews(self.overview_levels, Resampling.average)
                dst.update_tags(ns="rio_overview", resampling="average")

        file_size_mb = dest_path.stat().st_size / (1024 * 1024)
        logger.info(f"Successfully generated COG: {dest_path} ({file_size_mb:.2f} MB)")
        return dest_path

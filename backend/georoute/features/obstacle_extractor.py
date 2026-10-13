"""Physical obstacle extraction and standardized vector/raster layer generation.

Extracts, cleans, standardizes, and rasterizes physical obstacle features:
- Buildings (settlement footprints)
- Waterways and water bodies (rivers, streams, lakes, reservoirs)
- Existing transport infrastructure (railways, highways)

Produces:
- Standardized GeoJSON: physical_obstacles.geojson
- Binary raster masks: building_mask.tif, water_mask.tif, railway_mask.tif, combined_obstacle_mask.tif
"""

import logging
from typing import Dict, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.validation import make_valid

from georoute.features.rasterizer import GeoRasterizer

logger = logging.getLogger("georoute.features.obstacles")


class ObstacleExtractor:
    """Extracts, standardizes, and rasterizes physical obstacles into constraint layers."""

    def __init__(self, rasterizer: GeoRasterizer):
        """Initializes extractor with a reference GeoRasterizer.

        Args:
            rasterizer: Configured GeoRasterizer matching the master project grid.
        """
        self.rasterizer = rasterizer

    def standardize_layer(
        self,
        gdf: Optional[gpd.GeoDataFrame],
        obstacle_type: str,
        source: str,
    ) -> gpd.GeoDataFrame:
        """Standardizes attribute schema and validates geometries for an obstacle layer.

        Args:
            gdf: Input GeoDataFrame.
            obstacle_type: Categorical obstacle type ('building', 'waterway', 'existing_railway', 'other_infrastructure').
            source: Source identifier (e.g. 'osm_buildings', 'osm_waterways').

        Returns:
            Standardized GeoDataFrame with schema [obstacle_id, obstacle_type, source, name, geometry].
        """
        target_cols = ["obstacle_id", "obstacle_type", "source", "name", "geometry"]

        if gdf is None or len(gdf) == 0:
            return gpd.GeoDataFrame(columns=target_cols, crs=self.rasterizer.target_crs)

        working = gdf.copy()

        # Reproject to target grid CRS
        if working.crs is None:
            working = working.set_crs(self.rasterizer.target_crs)
        elif working.crs != self.rasterizer.target_crs:
            working = working.to_crs(self.rasterizer.target_crs)

        # Drop null or empty geometries
        working = working[working.geometry.notnull() & ~working.geometry.is_empty]
        if len(working) == 0:
            return gpd.GeoDataFrame(columns=target_cols, crs=self.rasterizer.target_crs)

        # Repair invalid geometries
        invalid_mask = ~working.geometry.is_valid
        if invalid_mask.any():
            working.loc[invalid_mask, "geometry"] = working.loc[invalid_mask, "geometry"].apply(make_valid)

        # Retain or construct name
        name_col = None
        for candidate in ["name", "name:en", "name:hi", "ref"]:
            if candidate in working.columns:
                name_col = candidate
                break

        names = working[name_col].astype(str) if name_col else pd.Series([""] * len(working), index=working.index)
        names = names.replace("nan", "").replace("None", "")

        # Generate unique IDs
        obstacle_ids = [f"OBS_{obstacle_type[:4].upper()}_{i + 1:06d}" for i in range(len(working))]

        result = gpd.GeoDataFrame(
            {
                "obstacle_id": obstacle_ids,
                "obstacle_type": obstacle_type,
                "source": source,
                "name": names.values,
                "geometry": working.geometry.values,
            },
            crs=self.rasterizer.target_crs,
        )

        return result

    def extract_obstacles(
        self,
        buildings_gdf: Optional[gpd.GeoDataFrame] = None,
        waterways_gdf: Optional[gpd.GeoDataFrame] = None,
        railways_gdf: Optional[gpd.GeoDataFrame] = None,
        highways_gdf: Optional[gpd.GeoDataFrame] = None,
        landcover_array: Optional[np.ndarray] = None,
        water_class_value: int = 80,
    ) -> Tuple[gpd.GeoDataFrame, Dict[str, np.ndarray]]:
        """Processes and rasterizes all physical obstacle layers.

        Args:
            buildings_gdf: OSM / cadastral buildings layer.
            waterways_gdf: OSM / hydrography waterways layer (rivers, streams, canals).
            railways_gdf: Existing railway infrastructure layer.
            highways_gdf: Existing highway / major road layer.
            landcover_array: 2D ESA WorldCover array matching the grid shape.
            water_class_value: Discrete ESA class value for permanent water bodies (default 80).

        Returns:
            Tuple of:
            - Unified physical_obstacles GeoDataFrame in target CRS.
            - Dictionary of 2D uint8 binary masks ('building_mask', 'water_mask', 'railway_mask', 'highway_mask', 'combined_obstacle_mask').
        """
        layers_to_merge: List[gpd.GeoDataFrame] = []

        # 1. Buildings (all_touched=False to preserve footprint resolution)
        std_buildings = self.standardize_layer(buildings_gdf, obstacle_type="building", source="osm_buildings")
        if len(std_buildings) > 0:
            layers_to_merge.append(std_buildings)
        building_mask = self.rasterizer.rasterize_gdf(std_buildings, value=1, fill=0, all_touched=False)

        # 2. Waterways (all_touched=True for thin linear features)
        std_waterways = self.standardize_layer(waterways_gdf, obstacle_type="waterway", source="osm_waterways")
        if len(std_waterways) > 0:
            layers_to_merge.append(std_waterways)
        waterway_mask = self.rasterizer.rasterize_gdf(std_waterways, value=1, fill=0, all_touched=True)

        # Fuse waterways with raster permanent water bodies (WorldCover class 80)
        water_mask = np.zeros(self.rasterizer.target_shape, dtype=np.uint8)
        water_mask[waterway_mask == 1] = 1
        if landcover_array is not None:
            if landcover_array.ndim == 3:
                lc_2d = landcover_array[0]
            else:
                lc_2d = landcover_array
            water_mask[lc_2d == water_class_value] = 1

        # 3. Railways (all_touched=True for tracks)
        std_railways = self.standardize_layer(railways_gdf, obstacle_type="existing_railway", source="osm_railways")
        if len(std_railways) > 0:
            layers_to_merge.append(std_railways)
        railway_mask = self.rasterizer.rasterize_gdf(std_railways, value=1, fill=0, all_touched=True)

        # 4. Highways (all_touched=True for road networks)
        std_highways = self.standardize_layer(highways_gdf, obstacle_type="other_infrastructure", source="osm_highways")
        if len(std_highways) > 0:
            layers_to_merge.append(std_highways)
        highway_mask = self.rasterizer.rasterize_gdf(std_highways, value=1, fill=0, all_touched=True)

        # 5. Unified Vector
        if layers_to_merge:
            unified_gdf = gpd.GeoDataFrame(pd.concat(layers_to_merge, ignore_index=True), crs=self.rasterizer.target_crs)
            # Re-index unique IDs deterministically
            unified_gdf["obstacle_id"] = [f"OBS_{i + 1:06d}" for i in range(len(unified_gdf))]
        else:
            unified_gdf = gpd.GeoDataFrame(
                columns=["obstacle_id", "obstacle_type", "source", "name", "geometry"],
                crs=self.rasterizer.target_crs,
            )

        # 6. Combined Obstacle Mask (union of all obstacles)
        combined_mask = np.zeros(self.rasterizer.target_shape, dtype=np.uint8)
        combined_mask[(building_mask == 1) | (water_mask == 1) | (railway_mask == 1) | (highway_mask == 1)] = 1

        masks = {
            "building_mask": building_mask,
            "water_mask": water_mask,
            "railway_mask": railway_mask,
            "highway_mask": highway_mask,
            "combined_obstacle_mask": combined_mask,
        }

        total_pixels = self.rasterizer.height * self.rasterizer.width
        logger.info(
            f"Extracted {len(unified_gdf)} physical obstacles. Pixel coverage: "
            f"Buildings: {np.count_nonzero(building_mask)} ({np.count_nonzero(building_mask)/total_pixels*100:.2f}%), "
            f"Water: {np.count_nonzero(water_mask)} ({np.count_nonzero(water_mask)/total_pixels*100:.2f}%), "
            f"Railways: {np.count_nonzero(railway_mask)} ({np.count_nonzero(railway_mask)/total_pixels*100:.2f}%), "
            f"Combined: {np.count_nonzero(combined_mask)} ({np.count_nonzero(combined_mask)/total_pixels*100:.2f}%)"
        )

        return unified_gdf, masks

"""Environmental and statutory protected area feature extraction.

Standardizes statutory protected areas (National Parks, Wildlife Sanctuaries,
Conservation Reserves) and distinguishes them from ordinary forest land-cover.

In downstream routing (Part 3):
- Statutory protected areas act as HARD EXCLUSION zones (infinite cost / forbidden).
- Ordinary forest cover acts as a SOFT COST zone (clearance & compensatory afforestation friction).

Produces:
- Standardized GeoJSON: environmental_zones.geojson
- Binary raster mask: protected_area_mask.tif
- Environmental conflict and protection metrics.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.validation import make_valid

from georoute.features.rasterizer import GeoRasterizer

logger = logging.getLogger("georoute.features.environmental")


class EnvironmentalExtractor:
    """Processes statutory conservation areas and analyzes overlap with forest cover."""

    def __init__(self, rasterizer: GeoRasterizer):
        """Initializes extractor with a reference GeoRasterizer.

        Args:
            rasterizer: Configured GeoRasterizer matching the master project grid.
        """
        self.rasterizer = rasterizer

    def standardize_protected_areas(
        self,
        gdf: Optional[gpd.GeoDataFrame],
        source_name: str = "national_protected_areas_india",
    ) -> gpd.GeoDataFrame:
        """Standardizes attribute schema and validates geometries for statutory protected areas.

        Args:
            gdf: Input GeoDataFrame (e.g. from protected_areas.geojson).
            source_name: Identifier for data provenance.

        Returns:
            Standardized GeoDataFrame with schema [zone_id, name, zone_type, state, source, status, geometry].
        """
        target_cols = ["zone_id", "name", "zone_type", "state", "source", "status", "geometry"]

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

        # Clip / spatially filter against master raster bounds
        minx, miny, maxx, maxy = self.rasterizer.bounds
        try:
            working = working.cx[minx:maxx, miny:maxy]
        except Exception as e:
            logger.debug(f"Spatial index filter on environmental zones skipped: {e}")

        if len(working) == 0:
            return gpd.GeoDataFrame(columns=target_cols, crs=self.rasterizer.target_crs)

        # Extract name
        name_col = None
        for cand in ["name", "name:en", "name:hi", "NAME"]:
            if cand in working.columns:
                name_col = cand
                break
        names = working[name_col].astype(str) if name_col else pd.Series([""] * len(working), index=working.index)
        names = names.replace("nan", "").replace("None", "")

        # Extract zone type
        type_col = None
        for cand in ["type", "zone_type", "designation", "boundary", "leisure"]:
            if cand in working.columns:
                type_col = cand
                break
        types = working[type_col].astype(str) if type_col else pd.Series(["Protected Area"] * len(working), index=working.index)
        types = types.replace("nan", "Protected Area").replace("None", "Protected Area")

        # Extract state
        state_col = "state" if "state" in working.columns else None
        states = working[state_col].astype(str) if state_col else pd.Series([""] * len(working), index=working.index)
        states = states.replace("nan", "").replace("None", "")

        zone_ids = [f"ENV_{i + 1:06d}" for i in range(len(working))]

        return gpd.GeoDataFrame(
            {
                "zone_id": zone_ids,
                "name": names.values,
                "zone_type": types.values,
                "state": states.values,
                "source": source_name,
                "status": "statutory_exclusion",
                "geometry": working.geometry.values,
            },
            crs=self.rasterizer.target_crs,
        )

    def extract_environmental_layers(
        self,
        authoritative_pa_gdf: Optional[gpd.GeoDataFrame] = None,
        osm_env_gdf: Optional[gpd.GeoDataFrame] = None,
        forest_mask: Optional[np.ndarray] = None,
    ) -> Tuple[gpd.GeoDataFrame, Dict[str, np.ndarray], Dict[str, Any]]:
        """Processes protected areas and computes raster mask and forest separation metrics.

        Args:
            authoritative_pa_gdf: Primary statutory dataset (e.g. data/vector/protected_areas.geojson).
            osm_env_gdf: Secondary OSM environmental zones.
            forest_mask: Optional 2D binary uint8 forest mask from LandCoverClassifier.

        Returns:
            Tuple of:
            - Standardized environmental_zones GeoDataFrame.
            - Dictionary of raster masks ('protected_area_mask').
            - Analysis dictionary showing statutory vs non-statutory forest breakdown.
        """
        layers_to_merge: List[gpd.GeoDataFrame] = []

        if authoritative_pa_gdf is not None and len(authoritative_pa_gdf) > 0:
            std_auth = self.standardize_protected_areas(authoritative_pa_gdf, source_name="national_protected_areas_india")
            if len(std_auth) > 0:
                layers_to_merge.append(std_auth)

        if osm_env_gdf is not None and len(osm_env_gdf) > 0:
            std_osm = self.standardize_protected_areas(osm_env_gdf, source_name="osm_environmental_zones")
            if len(std_osm) > 0:
                layers_to_merge.append(std_osm)

        if layers_to_merge:
            unified_env = gpd.GeoDataFrame(pd.concat(layers_to_merge, ignore_index=True), crs=self.rasterizer.target_crs)
            unified_env["zone_id"] = [f"ENV_{i + 1:06d}" for i in range(len(unified_env))]
        else:
            unified_env = gpd.GeoDataFrame(
                columns=["zone_id", "name", "zone_type", "state", "source", "status", "geometry"],
                crs=self.rasterizer.target_crs,
            )

        # Rasterize statutory exclusion mask (all_touched=False for polygonal reserves)
        pa_mask = self.rasterizer.rasterize_gdf(unified_env, value=1, fill=0, all_touched=False)

        total_pixels = self.rasterizer.height * self.rasterizer.width
        pa_pixel_count = int(np.count_nonzero(pa_mask == 1))
        pa_percentage = (pa_pixel_count / total_pixels * 100.0) if total_pixels > 0 else 0.0

        metrics: Dict[str, Any] = {
            "protected_zones_count": len(unified_env),
            "protected_pixel_count": pa_pixel_count,
            "protected_area_percentage": round(pa_percentage, 4),
            "protected_area_km2": round((pa_pixel_count * 100.0) / 1_000_000.0, 4),
        }

        # Forest overlap vs separation analysis
        if forest_mask is not None:
            if forest_mask.ndim == 3:
                f_mask = forest_mask[0]
            else:
                f_mask = forest_mask

            total_forest_pixels = int(np.count_nonzero(f_mask == 1))
            forest_in_pa = int(np.count_nonzero((f_mask == 1) & (pa_mask == 1)))
            forest_outside_pa = total_forest_pixels - forest_in_pa

            metrics["forest_breakdown"] = {
                "total_forest_pixels": total_forest_pixels,
                "total_forest_km2": round((total_forest_pixels * 100.0) / 1_000_000.0, 4),
                "hard_exclusion_forest_pixels": forest_in_pa,
                "hard_exclusion_forest_km2": round((forest_in_pa * 100.0) / 1_000_000.0, 4),
                "soft_friction_forest_pixels": forest_outside_pa,
                "soft_friction_forest_km2": round((forest_outside_pa * 100.0) / 1_000_000.0, 4),
                "statutory_forest_ratio": round(forest_in_pa / total_forest_pixels, 4) if total_forest_pixels > 0 else 0.0,
            }
            logger.info(
                f"Environmental analysis complete: {pa_pixel_count} protected pixels. "
                f"Forest breakdown: {forest_in_pa} hard-exclusion pixels, {forest_outside_pa} soft-friction pixels."
            )

        return unified_env, {"protected_area_mask": pa_mask}, metrics

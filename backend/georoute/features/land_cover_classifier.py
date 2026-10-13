"""Land-cover feature extraction, classification masks, and optical cross-validation.

Extracts discrete categorical masks from ESA WorldCover 10m rasters:
- Forest (Tree cover, class 10)
- Wetlands (classes 90, 95)
- Cropland (class 40)
- Built-up (class 50)
- Permanent water bodies (class 80)

Generates:
- Binary raster masks (forest_mask.tif, wetland_mask.tif, cropland_mask.tif, etc.)
- landcover_summary.json (pixel count, percentage, metric area)
- landcover_class_mapping.json (class definitions and Part 3 cost implications)
- Optical Sentinel-2 cross-validation via NDVI computation
"""

import logging
from typing import Any, Dict, Optional, Tuple, Union

import numpy as np

logger = logging.getLogger("georoute.features.landcover")

ESA_WORLDCOVER_CLASSES: Dict[int, Dict[str, str]] = {
    10: {
        "name": "Tree cover",
        "category": "forest",
        "description": "Tree canopy cover >= 10%, tree height >= 5m",
        "part3_implication": "High clearing and compensatory afforestation cost; moderate terrain and environmental sensitivity",
    },
    20: {
        "name": "Shrubland",
        "category": "vegetation",
        "description": "Woody perennial plants with persistent woody stems, height < 5m",
        "part3_implication": "Low clearing cost; standard construction difficulty",
    },
    30: {
        "name": "Grassland",
        "category": "vegetation",
        "description": "Natural herbaceous vegetation without substantial tree or shrub cover",
        "part3_implication": "Minimal clearing cost; favorable for earthwork",
    },
    40: {
        "name": "Cropland",
        "category": "agriculture",
        "description": "Cultivated agricultural land and harvested fields",
        "part3_implication": "Moderate to high agricultural land acquisition compensation",
    },
    50: {
        "name": "Built-up",
        "category": "urban",
        "description": "Urban and built-up land, residential and commercial structures",
        "part3_implication": "Very high property acquisition and resettlement cost; strict corridor avoidance preferred",
    },
    60: {
        "name": "Bare / sparse vegetation",
        "category": "bare",
        "description": "Lands with exposed soil, sand, rocks with vegetative cover < 10%",
        "part3_implication": "Zero land acquisition friction; potential geotechnical/slope stability review",
    },
    70: {
        "name": "Snow and ice",
        "category": "cryosphere",
        "description": "Perennial snowfields and glaciers",
        "part3_implication": "Extreme engineering hazard and maintenance burden; high routing friction",
    },
    80: {
        "name": "Permanent water bodies",
        "category": "water",
        "description": "Lakes, reservoirs, wide rivers, and coastal waters",
        "part3_implication": "Severe engineering constraint requiring major bridge or causeway infrastructure",
    },
    90: {
        "name": "Herbaceous wetland",
        "category": "wetland",
        "description": "Inundated or saturated marshlands and swamps",
        "part3_implication": "Strict ecological sensitivity and poor foundation soil bearing capacity",
    },
    95: {
        "name": "Mangroves",
        "category": "wetland",
        "description": "Tidal mangrove formations along estuaries",
        "part3_implication": "Statutory coastal regulation exclusion and high bridge foundation cost",
    },
    100: {
        "name": "Moss and lichen",
        "category": "tundra",
        "description": "High altitude or polar moss and lichen cover",
        "part3_implication": "Alpine fragile ecosystem friction",
    },
}


class LandCoverClassifier:
    """Extracts discrete constraint masks, summary metrics, and optical validation from land-cover data."""

    def __init__(
        self,
        target_shape: Tuple[int, int],
        cell_resolution: Tuple[float, float] = (10.0, 10.0),
    ):
        """Initializes the classifier.

        Args:
            target_shape: (height, width) of the grid.
            cell_resolution: Metric pixel sizes (dx, dy) in meters.
        """
        self.target_shape = target_shape
        self.height, self.width = target_shape
        self.dx = abs(cell_resolution[0])
        self.dy = abs(cell_resolution[1])
        self.pixel_area_m2 = self.dx * self.dy

    def extract_class_masks(
        self,
        landcover_array: np.ndarray,
        nodata: float = 0.0,
    ) -> Dict[str, np.ndarray]:
        """Extracts binary uint8 masks for key environmental and planning categories.

        Args:
            landcover_array: 2D or (1, H, W) ESA WorldCover array.
            nodata: Discrete nodata value (typically 0.0).

        Returns:
            Dictionary of 2D binary uint8 masks (1=foreground, 0=background).
        """
        if landcover_array.ndim == 3:
            lc = landcover_array[0]
        else:
            lc = landcover_array

        if lc.shape != self.target_shape:
            raise ValueError(
                f"Land cover array shape {lc.shape} does not match target shape {self.target_shape}"
            )

        # Generate standard masks
        forest_mask = np.zeros(self.target_shape, dtype=np.uint8)
        forest_mask[lc == 10] = 1

        shrubland_mask = np.zeros(self.target_shape, dtype=np.uint8)
        shrubland_mask[lc == 20] = 1

        grassland_mask = np.zeros(self.target_shape, dtype=np.uint8)
        grassland_mask[lc == 30] = 1

        cropland_mask = np.zeros(self.target_shape, dtype=np.uint8)
        cropland_mask[lc == 40] = 1

        builtup_mask = np.zeros(self.target_shape, dtype=np.uint8)
        builtup_mask[lc == 50] = 1

        bare_mask = np.zeros(self.target_shape, dtype=np.uint8)
        bare_mask[lc == 60] = 1

        water_mask = np.zeros(self.target_shape, dtype=np.uint8)
        water_mask[lc == 80] = 1

        wetland_mask = np.zeros(self.target_shape, dtype=np.uint8)
        wetland_mask[(lc == 90) | (lc == 95)] = 1

        return {
            "forest_mask": forest_mask,
            "shrubland_mask": shrubland_mask,
            "grassland_mask": grassland_mask,
            "cropland_mask": cropland_mask,
            "builtup_mask": builtup_mask,
            "bare_mask": bare_mask,
            "water_mask": water_mask,
            "wetland_mask": wetland_mask,
        }

    def compute_summary(
        self,
        landcover_array: np.ndarray,
        nodata: float = 0.0,
    ) -> Dict[str, Any]:
        """Calculates pixel counts, percentages, and ground area for all land-cover classes.

        Args:
            landcover_array: 2D or (1, H, W) ESA WorldCover array.
            nodata: Discrete nodata value.

        Returns:
            Dictionary containing dataset summary and per-class distributions.
        """
        if landcover_array.ndim == 3:
            lc = landcover_array[0]
        else:
            lc = landcover_array

        total_pixels = int(lc.size)
        nodata_mask = (lc == nodata) | np.isnan(lc)
        nodata_count = int(np.count_nonzero(nodata_mask))
        valid_count = total_pixels - nodata_count

        classes_summary: Dict[str, Any] = {}

        unique_vals, counts = np.unique(lc[~nodata_mask], return_counts=True)
        counts_dict = {int(k): int(v) for k, v in zip(unique_vals, counts)}

        for class_id, info in ESA_WORLDCOVER_CLASSES.items():
            cnt = int(counts_dict.get(class_id, 0))
            pct = float(cnt / valid_count * 100.0) if valid_count > 0 else 0.0
            area_m2 = float(cnt * self.pixel_area_m2)
            area_km2 = float(area_m2 / 1_000_000.0)

            classes_summary[str(class_id)] = {
                "class_id": int(class_id),
                "name": info["name"],
                "category": info["category"],
                "pixel_count": int(cnt),
                "percentage": round(pct, 4),
                "area_km2": round(area_km2, 4),
                "description": info["description"],
                "part3_implication": info["part3_implication"],
            }

        return {
            "total_pixels": int(total_pixels),
            "valid_pixels": int(valid_count),
            "nodata_pixels": int(nodata_count),
            "pixel_resolution_m": [float(self.dx), float(self.dy)],
            "total_area_km2": round(float((valid_count * self.pixel_area_m2) / 1_000_000.0), 4),
            "classes": classes_summary,
        }

    def get_class_mapping(self) -> Dict[str, Any]:
        """Returns the complete ESA WorldCover class mapping dictionary."""
        return {
            "source": "ESA WorldCover 10m 2021 Legend",
            "legend": {
                str(k): {
                    "id": k,
                    "name": v["name"],
                    "category": v["category"],
                    "description": v["description"],
                    "part3_implication": v["part3_implication"],
                }
                for k, v in ESA_WORLDCOVER_CLASSES.items()
            },
        }

    @staticmethod
    def compute_ndvi(
        optical_array: np.ndarray,
        red_band_idx: int = 0,
        nir_band_idx: int = 3,
        nodata_val: float = -9999.0,
    ) -> np.ndarray:
        """Computes Normalized Difference Vegetation Index (NDVI) from Sentinel-2 bands.

        Formula: (NIR - Red) / (NIR + Red)

        Args:
            optical_array: 3D array of shape (bands, height, width).
            red_band_idx: 0-indexed band index for Red (B04).
            nir_band_idx: 0-indexed band index for NIR (B08).
            nodata_val: Nodata output value for division by zero or invalid pixels.

        Returns:
            2D float32 array of NDVI values in [-1.0, 1.0].
        """
        if optical_array.ndim != 3:
            raise ValueError(f"Optical array must be 3D, got {optical_array.ndim}D")

        red = optical_array[red_band_idx].astype(np.float32)
        nir = optical_array[nir_band_idx].astype(np.float32)

        numerator = nir - red
        denominator = nir + red

        # Mask division by zero or negative denominators (unphysical)
        valid = (denominator > 1e-6) & np.isfinite(numerator) & np.isfinite(denominator)

        ndvi = np.full(red.shape, nodata_val, dtype=np.float32)
        ndvi[valid] = numerator[valid] / denominator[valid]

        # Clip valid values to physical range [-1.0, 1.0]
        ndvi[valid] = np.clip(ndvi[valid], -1.0, 1.0)
        return ndvi

    def validate_with_optical(
        self,
        landcover_array: np.ndarray,
        optical_array: np.ndarray,
        red_band_idx: int = 0,
        nir_band_idx: int = 3,
    ) -> Dict[str, Any]:
        """Cross-validates land-cover classifications against computed Sentinel-2 NDVI.

        Args:
            landcover_array: 2D ESA WorldCover array.
            optical_array: 3D Sentinel-2 optical array.
            red_band_idx: 0-indexed Red band index.
            nir_band_idx: 0-indexed NIR band index.

        Returns:
            Dictionary with NDVI statistics across land-cover classes.
        """
        if landcover_array.ndim == 3:
            lc = landcover_array[0]
        else:
            lc = landcover_array

        ndvi = self.compute_ndvi(optical_array, red_band_idx=red_band_idx, nir_band_idx=nir_band_idx)
        valid_ndvi = ndvi > -9000.0

        results: Dict[str, Any] = {}

        # 1. Forest (class 10) NDVI check
        forest_mask = (lc == 10) & valid_ndvi
        if np.count_nonzero(forest_mask) > 0:
            forest_vals = ndvi[forest_mask]
            results["forest_ndvi"] = {
                "pixel_count": int(np.count_nonzero(forest_mask)),
                "mean": round(float(np.mean(forest_vals)), 4),
                "std": round(float(np.std(forest_vals)), 4),
                "min": round(float(np.min(forest_vals)), 4),
                "max": round(float(np.max(forest_vals)), 4),
            }

        # 2. Water (class 80) NDVI check
        water_mask = (lc == 80) & valid_ndvi
        if np.count_nonzero(water_mask) > 0:
            water_vals = ndvi[water_mask]
            results["water_ndvi"] = {
                "pixel_count": int(np.count_nonzero(water_mask)),
                "mean": round(float(np.mean(water_vals)), 4),
                "std": round(float(np.std(water_vals)), 4),
                "min": round(float(np.min(water_vals)), 4),
                "max": round(float(np.max(water_vals)), 4),
            }

        # 3. Built-up (class 50) NDVI check
        urban_mask = (lc == 50) & valid_ndvi
        if np.count_nonzero(urban_mask) > 0:
            urban_vals = ndvi[urban_mask]
            results["builtup_ndvi"] = {
                "pixel_count": int(np.count_nonzero(urban_mask)),
                "mean": round(float(np.mean(urban_vals)), 4),
                "std": round(float(np.std(urban_vals)), 4),
            }

        # Plausibility check: Forest NDVI should typically be greater than Built-up/Water
        results["plausibility_passed"] = True
        if "forest_ndvi" in results and "water_ndvi" in results:
            if results["forest_ndvi"]["mean"] <= results["water_ndvi"]["mean"]:
                results["plausibility_passed"] = False
                logger.warning("Optical validation warning: Forest mean NDVI <= Water mean NDVI.")

        return results

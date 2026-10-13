"""Topographic slope and terrain gradient calculator using Horn's algorithm."""

from dataclasses import dataclass
import logging
from typing import Any, Dict, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger("georoute.slope")


@dataclass
class SlopeResult:
    """Container for computed topographic slope grids and summary metrics."""
    slope_degrees: np.ndarray  # Shape: (1, H, W) or (H, W), dtype: float32, range: 0.0 - 90.0
    slope_percent: np.ndarray  # Shape: (1, H, W) or (H, W), dtype: float32, range: 0.0 - 100%+ (uncapped)
    validity_mask: np.ndarray  # Shape: (1, H, W) or (H, W), dtype: bool, True where valid
    nodata_value: float
    cell_size_x: float
    cell_size_y: float
    summary_stats: Dict[str, Any]


class SlopeCalculator:
    """Calculates terrain slope in degrees and percent from Digital Elevation Models.

    Uses Horn's (1981) 3x3 finite-difference algorithm:
        dz/dx = ((z3 + 2*z6 + z9) - (z1 + 2*z4 + z7)) / (8 * dx)
        dz/dy = ((z7 + 2*z8 + z9) - (z1 + 2*z2 + z3)) / (8 * dy)
        rise_run = sqrt((dz/dx)^2 + (dz/dy)^2)
        slope_degrees = arctan(rise_run) * (180 / pi)
        slope_percent = rise_run * 100.0

    Adheres to strict geospatial engineering rules:
      1. Slope in percent is uncapped (slopes > 100% / > 45 deg are physically real).
      2. Nodata values (-9999.0) in any neighborhood cell invalidate the gradient.
      3. Metric cell dimensions (dx, dy) are strictly respected.
    """

    def __init__(
        self,
        cell_size_x: float = 10.0,
        cell_size_y: float = 10.0,
        nodata_val: float = -9999.0,
        replicate_edges: bool = False,
    ):
        """Initializes the slope calculator.

        Args:
            cell_size_x: Ground pixel width in meters (projected CRS units).
            cell_size_y: Ground pixel height in meters (projected CRS units).
            nodata_val: Nodata fill value used in input and output rasters.
            replicate_edges: If True, replicate 1-pixel boundary from interior.
                             If False (default), mark outer 1-pixel border as nodata.
        """
        if cell_size_x <= 0 or cell_size_y <= 0:
            raise ValueError(f"Cell sizes must be strictly positive: dx={cell_size_x}, dy={cell_size_y}")
        self.cell_size_x = float(cell_size_x)
        self.cell_size_y = float(cell_size_y)
        self.nodata_val = float(nodata_val)
        self.replicate_edges = replicate_edges

    def compute(
        self,
        dem: np.ndarray,
        cell_size_x: Optional[float] = None,
        cell_size_y: Optional[float] = None,
        nodata_val: Optional[float] = None,
    ) -> SlopeResult:
        """Computes slope in degrees and percent from a DEM array.

        Args:
            dem: 2D array (H, W) or 3D array (1, H, W) of elevations in meters.
            cell_size_x: Optional override for horizontal cell size in meters.
            cell_size_y: Optional override for vertical cell size in meters.
            nodata_val: Optional override for nodata fill value.

        Returns:
            SlopeResult containing slope_degrees, slope_percent, validity_mask, and statistics.
        """
        dx = float(cell_size_x) if cell_size_x is not None else self.cell_size_x
        dy = float(cell_size_y) if cell_size_y is not None else self.cell_size_y
        nd = float(nodata_val) if nodata_val is not None else self.nodata_val

        # Normalize input shape to 2D
        is_3d = dem.ndim == 3
        if is_3d:
            if dem.shape[0] != 1:
                raise ValueError(f"Expected single-band DEM (shape 1, H, W), got {dem.shape}")
            dem_2d = dem[0].astype(np.float32)
        elif dem.ndim == 2:
            dem_2d = dem.astype(np.float32)
        else:
            raise ValueError(f"DEM must be 2D or 3D array, got shape {dem.shape}")

        height, width = dem_2d.shape
        if height < 3 or width < 3:
            raise ValueError(f"DEM dimensions ({width}x{height}) too small for 3x3 kernel calculation")

        # Create output buffers initialized to nodata
        slope_deg_2d = np.full((height, width), fill_value=nd, dtype=np.float32)
        slope_pct_2d = np.full((height, width), fill_value=nd, dtype=np.float32)

        # Identify invalid/nodata cells in the input DEM
        invalid_dem = (
            np.isnan(dem_2d)
            | np.isinf(dem_2d)
            | (np.isclose(dem_2d, nd, atol=1e-3))
            | (dem_2d < -9000.0)  # Conservative nodata catch
        )

        # 3x3 Neighborhood slicing (interior: rows 1..H-2, cols 1..W-2)
        # Slices:
        # z1 z2 z3
        # z4 z5 z6
        # z7 z8 z9
        z1 = dem_2d[0:-2, 0:-2]
        z2 = dem_2d[0:-2, 1:-1]
        z3 = dem_2d[0:-2, 2:]
        z4 = dem_2d[1:-1, 0:-2]
        z5 = dem_2d[1:-1, 1:-1]
        z6 = dem_2d[1:-1, 2:]
        z7 = dem_2d[2:, 0:-2]
        z8 = dem_2d[2:, 1:-1]
        z9 = dem_2d[2:, 2:]

        # Neighborhood validity: center cell is valid ONLY IF all 9 cells are valid
        inv1 = invalid_dem[0:-2, 0:-2]
        inv2 = invalid_dem[0:-2, 1:-1]
        inv3 = invalid_dem[0:-2, 2:]
        inv4 = invalid_dem[1:-1, 0:-2]
        inv5 = invalid_dem[1:-1, 1:-1]
        inv6 = invalid_dem[1:-1, 2:]
        inv7 = invalid_dem[2:, 0:-2]
        inv8 = invalid_dem[2:, 1:-1]
        inv9 = invalid_dem[2:, 2:]

        any_invalid = (
            inv1 | inv2 | inv3 | inv4 | inv5 | inv6 | inv7 | inv8 | inv9
        )
        valid_mask_interior = ~any_invalid

        # Horn's finite-difference gradient formulas
        dz_dx = ((z3 + 2.0 * z6 + z9) - (z1 + 2.0 * z4 + z7)) / (8.0 * dx)
        dz_dy = ((z7 + 2.0 * z8 + z9) - (z1 + 2.0 * z2 + z3)) / (8.0 * dy)

        # Gradient magnitude (rise / run)
        rise_run = np.sqrt(dz_dx**2 + dz_dy**2)

        # Calculate slope outputs
        deg_interior = np.degrees(np.arctan(rise_run))
        pct_interior = rise_run * 100.0

        # Assign valid interior values
        target_slice_deg = slope_deg_2d[1:-1, 1:-1]
        target_slice_pct = slope_pct_2d[1:-1, 1:-1]
        target_slice_deg[valid_mask_interior] = deg_interior[valid_mask_interior]
        target_slice_pct[valid_mask_interior] = pct_interior[valid_mask_interior]

        # Optional edge replication for boundary pixels
        if self.replicate_edges:
            # Top and bottom row
            slope_deg_2d[0, :] = slope_deg_2d[1, :]
            slope_deg_2d[-1, :] = slope_deg_2d[-2, :]
            slope_pct_2d[0, :] = slope_pct_2d[1, :]
            slope_pct_2d[-1, :] = slope_pct_2d[-2, :]
            # Left and right col
            slope_deg_2d[:, 0] = slope_deg_2d[:, 1]
            slope_deg_2d[:, -1] = slope_deg_2d[:, -2]
            slope_pct_2d[:, 0] = slope_pct_2d[:, 1]
            slope_pct_2d[:, -1] = slope_pct_2d[:, -2]

        # Master validity mask
        validity_mask_2d = (slope_deg_2d != nd) & ~np.isnan(slope_deg_2d)

        # Reshape to match input rank (2D or 3D)
        if is_3d:
            slope_degrees = slope_deg_2d[np.newaxis, ...]
            slope_percent = slope_pct_2d[np.newaxis, ...]
            validity_mask = validity_mask_2d[np.newaxis, ...]
        else:
            slope_degrees = slope_deg_2d
            slope_percent = slope_pct_2d
            validity_mask = validity_mask_2d

        # Compute summary statistics on valid cells
        valid_deg = slope_deg_2d[validity_mask_2d]
        valid_pct = slope_pct_2d[validity_mask_2d]

        if len(valid_deg) > 0:
            stats = {
                "valid_pixels": int(len(valid_deg)),
                "total_pixels": int(height * width),
                "valid_coverage_percent": round(100.0 * len(valid_deg) / (height * width), 2),
                "min_degrees": round(float(valid_deg.min()), 2),
                "max_degrees": round(float(valid_deg.max()), 2),
                "mean_degrees": round(float(valid_deg.mean()), 2),
                "std_degrees": round(float(valid_deg.std()), 2),
                "min_percent": round(float(valid_pct.min()), 2),
                "max_percent": round(float(valid_pct.max()), 2),
                "mean_percent": round(float(valid_pct.mean()), 2),
                "std_percent": round(float(valid_pct.std()), 2),
                "percentage_gt_10": round(100.0 * np.count_nonzero(valid_pct > 10.0) / len(valid_pct), 2),
                "percentage_gt_20": round(100.0 * np.count_nonzero(valid_pct > 20.0) / len(valid_pct), 2),
                "percentage_gt_30": round(100.0 * np.count_nonzero(valid_pct > 30.0) / len(valid_pct), 2),
            }
        else:
            stats = {
                "valid_pixels": 0,
                "total_pixels": int(height * width),
                "valid_coverage_percent": 0.0,
                "warning": "No valid slope pixels computed in DEM grid",
            }

        logger.info(
            f"Slope computed: {stats.get('valid_coverage_percent', 0)}% coverage | "
            f"Degrees: [{stats.get('min_degrees', 'N/A')}..{stats.get('max_degrees', 'N/A')}] | "
            f"Percent: [{stats.get('min_percent', 'N/A')}..{stats.get('max_percent', 'N/A')}%]"
        )

        return SlopeResult(
            slope_degrees=slope_degrees,
            slope_percent=slope_percent,
            validity_mask=validity_mask,
            nodata_value=nd,
            cell_size_x=dx,
            cell_size_y=dy,
            summary_stats=stats,
        )

    @classmethod
    def calculate(
        cls,
        dem: np.ndarray,
        cell_resolution: Tuple[float, float] = (10.0, 10.0),
        nodata: float = -9999.0,
        output_nodata: float = -9999.0,
        replicate_edges: bool = False,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Convenience method returning (slope_degrees, slope_percent) arrays."""
        calc = cls(
            cell_size_x=cell_resolution[0],
            cell_size_y=cell_resolution[1],
            nodata_val=output_nodata,
            replicate_edges=replicate_edges,
        )
        res = calc.compute(dem, nodata_val=nodata)
        return res.slope_degrees, res.slope_percent

    @staticmethod
    def compute_summary_stats(
        slope_degrees: np.ndarray,
        slope_percent: np.ndarray,
        nodata: float = -9999.0,
    ) -> Dict[str, Any]:
        """Computes summary statistics for slope arrays."""
        val_deg = slope_degrees[slope_degrees != nodata]
        val_pct = slope_percent[slope_percent != nodata]

        if len(val_deg) == 0:
            return {"valid_pixels": 0}

        return {
            "slope_degrees": {
                "min": round(float(val_deg.min()), 2),
                "max": round(float(val_deg.max()), 2),
                "mean": round(float(val_deg.mean()), 2),
                "std": round(float(val_deg.std()), 2),
            },
            "slope_percent": {
                "min": round(float(val_pct.min()), 2),
                "max": round(float(val_pct.max()), 2),
                "mean": round(float(val_pct.mean()), 2),
                "std": round(float(val_pct.std()), 2),
                "percentage_gt_10": round(100.0 * np.count_nonzero(val_pct > 10.0) / len(val_pct), 2),
                "percentage_gt_20": round(100.0 * np.count_nonzero(val_pct > 20.0) / len(val_pct), 2),
                "percentage_gt_30": round(100.0 * np.count_nonzero(val_pct > 30.0) / len(val_pct), 2),
            },
        }


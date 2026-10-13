"""PYORPS routing adapter for GeoRoute AI.

Adapts Float32 continuous friction surfaces and constraint masks into PYORPS-compatible
UInt16 discrete integer cost rasters, executes Cython-accelerated PathFinder routing,
and normalizes returned paths into GeoRoute AI candidate geometries and metric costs.
"""

from dataclasses import dataclass
import math
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import affine
import numpy as np
import rasterio
import rasterio.transform
import pyorps
from pyorps.core.exceptions import NoPathFoundError, PyorpsError
from shapely.geometry import LineString


class InfeasibleRouteError(Exception):
    """Raised when no feasible path connects the source and target endpoints."""
    pass


@dataclass
class PyorpsRouteResult:
    """Normalized route result from PYORPS routing engine."""
    path_cells: List[Tuple[int, int]]
    path_coords: List[Tuple[float, float]]
    geometry: LineString
    total_length_m: float
    pyorps_reported_cost: float
    recomputed_cost: float
    algorithm: str = "pyorps_cython"
    execution_time_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "num_nodes": len(self.path_cells),
            "total_length_m": round(self.total_length_m, 2),
            "total_length_km": round(self.total_length_m / 1000.0, 4),
            "pyorps_reported_cost": round(self.pyorps_reported_cost, 2),
            "recomputed_cost": round(self.recomputed_cost, 2),
            "algorithm": self.algorithm,
            "execution_time_seconds": round(self.execution_time_seconds, 4),
        }


class PyorpsAdapter:
    """Adapter bridging GeoRoute AI cost surfaces with PYORPS PathFinder."""

    IMPASSABLE_UINT16 = np.iinfo(np.uint16).max  # 65535

    def __init__(self, scale_factor: float = 100.0):
        """Initializes PYORPS adapter.

        Args:
            scale_factor: Integer scaling multiplier for Float32 friction (default 100.0).
                          e.g. friction 1.0 -> 100, friction 15.95 -> 1595.
        """
        self.scale_factor = float(scale_factor)

    def quantize_friction_to_uint16(
        self,
        friction_surface: np.ndarray,
        hard_constraint_mask: Optional[np.ndarray] = None,
        valid_data_mask: Optional[np.ndarray] = None,
        nodata_val: float = -9999.0,
    ) -> np.ndarray:
        """Converts Float32 friction raster into UInt16 discrete integer cost raster for PYORPS.

        Impassable cells (hard constraints, NoData, invalid values) are mapped to 65535.
        Passable cells are mapped to round(friction * scale_factor), clamped to [1, 65534].
        """
        if friction_surface.ndim == 3:
            f_arr = friction_surface[0]
        else:
            f_arr = friction_surface

        shape = f_arr.shape
        hcm = hard_constraint_mask[0] if hard_constraint_mask is not None and hard_constraint_mask.ndim == 3 else hard_constraint_mask
        vdm = valid_data_mask[0] if valid_data_mask is not None and valid_data_mask.ndim == 3 else valid_data_mask

        # Identify impassable cells
        impassable = (f_arr == nodata_val) | np.isnan(f_arr) | np.isinf(f_arr) | (f_arr <= 0.0)
        if hcm is not None:
            impassable |= (hcm == 1)
        if vdm is not None:
            impassable |= (vdm == 0)

        # Scale traversable cells
        scaled = np.round(f_arr * self.scale_factor)
        # Clamp to valid non-impassable range [1, 65534]
        clamped = np.clip(scaled, 1.0, float(self.IMPASSABLE_UINT16 - 1))

        quantized = clamped.astype(np.uint16)
        quantized[impassable] = self.IMPASSABLE_UINT16

        return quantized

    @staticmethod
    def recompute_float_path_cost(
        path_cells: List[Tuple[int, int]],
        friction_surface: np.ndarray,
        cell_size_x_m: float = 10.0,
        cell_size_y_m: float = 10.0,
    ) -> Tuple[float, float]:
        """Recomputes true continuous floating-point cost and physical step distance.

        Formula:
            StepCost(u, v) = Distance(u, v) * ((F(u) + F(v)) / 2)
        """
        f_2d = friction_surface[0] if friction_surface.ndim == 3 else friction_surface
        total_cost = 0.0
        total_dist_m = 0.0

        for i in range(len(path_cells) - 1):
            r1, c1 = path_cells[i]
            r2, c2 = path_cells[i + 1]

            dr_m = abs(r2 - r1) * cell_size_y_m
            dc_m = abs(c2 - c1) * cell_size_x_m
            step_dist = math.sqrt(dr_m ** 2 + dc_m ** 2)

            f1 = float(f_2d[r1, c1])
            f2 = float(f_2d[r2, c2])
            avg_f = (f1 + f2) / 2.0

            total_dist_m += step_dist
            total_cost += step_dist * avg_f

        return total_cost, total_dist_m

    STEPS_8_CONNECTED = np.array([
        [0, 1], [1, 0], [0, -1], [-1, 0],
        [1, 1], [-1, -1], [1, -1], [-1, 1],
    ], dtype=np.int8)

    def find_route(
        self,
        quantized_raster: np.ndarray,
        source_coords: Tuple[float, float],
        target_coords: Tuple[float, float],
        transform: affine.Affine,
        crs: str = "EPSG:32643",
        original_friction_raster: Optional[np.ndarray] = None,
        search_space_buffer_m: Optional[float] = None,
        ignore_max_cost: bool = True,
    ) -> PyorpsRouteResult:
        """Executes shortest path search via PYORPS PathFinder on quantized raster.

        Args:
            quantized_raster: 2D UInt16 raster with 65535 as impassable cells.
            source_coords: (x, y) projected coordinates of source in crs.
            target_coords: (x, y) projected coordinates of target in crs.
            transform: Raster Affine transform.
            crs: Target CRS string (e.g. 'EPSG:32643').
            original_friction_raster: Optional 2D Float32 friction array for exact recomputation.
            search_space_buffer_m: Optional lateral search buffer in meters around endpoints.
            ignore_max_cost: Whether PYORPS should ignore max cost cells for start/target snapping.

        Returns:
            PyorpsRouteResult with LineString geometry, cells, and recomputed floating-point costs.

        Raises:
            InfeasibleRouteError: If no path connects source and target.
        """
        start_time = time.perf_counter()

        pf_kwargs: Dict[str, Any] = {
            "dataset_source": quantized_raster,
            "source_coords": source_coords,
            "target_coords": target_coords,
            "transform": transform,
            "crs": crs,
            "weight_precision": "uint16",
            "graph_api": "cython",
            "steps": self.STEPS_8_CONNECTED,
            "ignore_max_cost": ignore_max_cost,
        }
        if search_space_buffer_m is not None:
            pf_kwargs["search_space_buffer_m"] = float(search_space_buffer_m)

        try:
            pf = pyorps.PathFinder(**pf_kwargs)
            pyorps_path = pf.find_route()
        except NoPathFoundError as e:
            raise InfeasibleRouteError(f"PYORPS found no feasible path between {source_coords} and {target_coords}: {e}")
        except PyorpsError as e:
            raise InfeasibleRouteError(f"PYORPS routing error: {e}")
        except Exception as e:
            raise InfeasibleRouteError(f"Unexpected routing failure: {e}")

        elapsed = time.perf_counter() - start_time

        if pyorps_path is None or getattr(pyorps_path, "path_geometry", None) is None:
            raise InfeasibleRouteError(f"PYORPS returned empty path for endpoints {source_coords} -> {target_coords}")

        # Extract coordinates
        raw_coords = pyorps_path.path_coords
        if isinstance(raw_coords, np.ndarray):
            path_coords = [(float(pt[0]), float(pt[1])) for pt in raw_coords]
        else:
            path_coords = [(float(pt[0]), float(pt[1])) for pt in raw_coords]

        # Map geographic coordinates to exact global raster (row, col) cells
        path_cells = [
            (int(r), int(c))
            for r, c in (rasterio.transform.rowcol(transform, pt[0], pt[1]) for pt in path_coords)
        ]

        geometry = pyorps_path.path_geometry
        if not isinstance(geometry, LineString):
            geometry = LineString(path_coords)

        # Recomputed cost
        cell_x_m = abs(float(transform.a))
        cell_y_m = abs(float(transform.e))

        if original_friction_raster is not None:
            recomputed_cost, recomputed_dist = self.recompute_float_path_cost(
                path_cells, original_friction_raster, cell_size_x_m=cell_x_m, cell_size_y_m=cell_y_m
            )
        else:
            recomputed_cost = float(pyorps_path.total_cost) / self.scale_factor
            recomputed_dist = float(pyorps_path.total_length)

        return PyorpsRouteResult(
            path_cells=path_cells,
            path_coords=path_coords,
            geometry=geometry,
            total_length_m=float(recomputed_dist),
            pyorps_reported_cost=float(pyorps_path.total_cost),
            recomputed_cost=float(recomputed_cost),
            algorithm="pyorps_cython",
            execution_time_seconds=elapsed,
        )

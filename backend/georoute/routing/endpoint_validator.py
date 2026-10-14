"""Endpoint validation and coordinate-to-grid resolution for GeoRoute AI.

Transforms geographic coordinates (WGS84 or projected), checks raster bounds,
validates against hard-constraint and valid-data masks, and optionally snaps
to the nearest traversable cell within a deterministic radius.
"""

from dataclasses import dataclass
import math
from typing import Any, Dict, Optional, Tuple, Union
import affine
import numpy as np
import pyproj
import rasterio.transform


class EndpointValidationError(Exception):
    """Base exception for routing endpoint validation failures."""
    pass


class OutOfCoverageError(EndpointValidationError):
    """Raised when an endpoint falls outside the active raster spatial extent."""
    pass


class ImpassableEndpointError(EndpointValidationError):
    """Raised when an endpoint falls in a blocked, prohibited, or nodata cell."""
    pass


@dataclass
class ResolvedEndpoint:
    """Resolved and validated routing endpoint."""
    name: str
    original_coords: Tuple[float, float]
    original_crs: str
    projected_coords: Tuple[float, float]
    projected_crs: str
    row: int
    col: int
    is_snapped: bool = False
    snap_distance_m: float = 0.0
    snap_reason: Optional[str] = None

    @property
    def x(self) -> float:
        return float(self.projected_coords[0])

    @property
    def y(self) -> float:
        return float(self.projected_coords[1])

    @property
    def grid_cell(self) -> Tuple[int, int]:
        return (int(self.row), int(self.col))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": str(self.name),
            "original_coords": (float(self.original_coords[0]), float(self.original_coords[1])),
            "original_crs": str(self.original_crs),
            "projected_coords": (float(self.projected_coords[0]), float(self.projected_coords[1])),
            "projected_crs": str(self.projected_crs),
            "row": int(self.row),
            "col": int(self.col),
            "is_snapped": bool(self.is_snapped),
            "snap_distance_m": round(float(self.snap_distance_m), 2),
            "snap_reason": str(self.snap_reason) if self.snap_reason else None,
        }


class EndpointValidator:
    """Validates geographic endpoints against raster extent and feasibility masks."""

    def __init__(
        self,
        raster_crs: Union[str, pyproj.CRS],
        transform: affine.Affine,
        grid_shape: Tuple[int, int],
        valid_data_mask: Optional[np.ndarray] = None,
        hard_constraint_mask: Optional[np.ndarray] = None,
        snap_to_valid: bool = False,
        max_snap_radius_m: float = 100.0,
    ):
        """Initializes the endpoint validator.

        Args:
            raster_crs: CRS of the target routing raster (e.g. 'EPSG:32643').
            transform: Affine transform of the target routing raster.
            grid_shape: (height, width) dimensions of the target raster.
            valid_data_mask: Optional 2D array where 1 is valid data, 0 is unknown/nodata.
            hard_constraint_mask: Optional 2D array where 1 is impassable, 0 is passable.
            snap_to_valid: If True, search for nearest passable cell if initial cell is blocked.
            max_snap_radius_m: Maximum search radius in metres for snapping.
        """
        self.raster_crs = pyproj.CRS.from_user_input(raster_crs)
        self.transform = transform
        self.height, self.width = grid_shape
        self.valid_data_mask = valid_data_mask[0] if valid_data_mask is not None and valid_data_mask.ndim == 3 else valid_data_mask
        self.hard_constraint_mask = hard_constraint_mask[0] if hard_constraint_mask is not None and hard_constraint_mask.ndim == 3 else hard_constraint_mask
        self.snap_to_valid = snap_to_valid
        self.max_snap_radius_m = float(max_snap_radius_m)

        # Pixel resolution
        self.cell_x_m = abs(float(self.transform.a))
        self.cell_y_m = abs(float(self.transform.e))

    def _transform_coordinate(
        self,
        x: float,
        y: float,
        source_crs: Union[str, pyproj.CRS],
    ) -> Tuple[float, float]:
        """Projects coordinate from source_crs to target raster_crs."""
        src_crs = pyproj.CRS.from_user_input(source_crs)
        if src_crs == self.raster_crs:
            return float(x), float(y)
        transformer = pyproj.Transformer.from_crs(src_crs, self.raster_crs, always_xy=True)
        proj_x, proj_y = transformer.transform(x, y)
        return float(proj_x), float(proj_y)

    def is_cell_traversable(self, row: int, col: int) -> Tuple[bool, Optional[str]]:
        """Checks whether a grid cell is valid and traversable."""
        if not (0 <= row < self.height and 0 <= col < self.width):
            return False, "Out of raster bounds"
        if self.valid_data_mask is not None and self.valid_data_mask[row, col] == 0:
            return False, "Falls in nodata / unknown data region"
        if self.hard_constraint_mask is not None and self.hard_constraint_mask[row, col] == 1:
            return False, "Falls in hard constraint / prohibited obstacle zone"
        return True, None

    def _find_nearest_valid_cell(
        self,
        start_row: int,
        start_col: int,
    ) -> Optional[Tuple[int, int, float]]:
        """Finds closest traversable cell within max_snap_radius_m using concentric radial search.

        Returns:
            Tuple of (snapped_row, snapped_col, distance_m) or None if no cell found.
        """
        max_cells = int(math.ceil(self.max_snap_radius_m / min(self.cell_x_m, self.cell_y_m)))
        best_cand: Optional[Tuple[int, int, float]] = None
        min_dist_sq = float("inf")

        for dr in range(-max_cells, max_cells + 1):
            for dc in range(-max_cells, max_cells + 1):
                if dr == 0 and dc == 0:
                    continue
                r = start_row + dr
                c = start_col + dc
                if not (0 <= r < self.height and 0 <= c < self.width):
                    continue

                dist_m = math.sqrt((dr * self.cell_x_m) ** 2 + (dc * self.cell_y_m) ** 2)
                if dist_m > self.max_snap_radius_m:
                    continue

                traversable, _ = self.is_cell_traversable(r, c)
                if traversable:
                    if dist_m < min_dist_sq:
                        min_dist_sq = dist_m
                        best_cand = (r, c, dist_m)

        return best_cand

    def validate_and_resolve(
        self,
        coords: Union[Tuple[float, float], Any],
        crs: Union[str, pyproj.CRS] = "EPSG:4326",
        name: str = "",
    ) -> ResolvedEndpoint:
        """Validates and resolves a coordinate into a verified routing cell.

        Args:
            coords: Tuple of (x, y) / (lon, lat) or object with lat/lon or x/y.
            crs: Coordinate reference system of input coords (default EPSG:4326).
            name: Human-readable name for logging.

        Returns:
            ResolvedEndpoint containing projected coordinates, row/col index, and snapping status.

        Raises:
            OutOfCoverageError: If endpoint falls outside active raster bounding box.
            ImpassableEndpointError: If endpoint falls in prohibited cell and cannot be snapped.
        """
        # Parse coordinates
        if hasattr(coords, "lon") and hasattr(coords, "lat"):
            x, y = float(coords.lon), float(coords.lat)
        elif hasattr(coords, "x") and hasattr(coords, "y"):
            x, y = float(coords.x), float(coords.y)
        elif isinstance(coords, (tuple, list)) and len(coords) >= 2:
            x, y = float(coords[0]), float(coords[1])
        else:
            raise ValueError(f"Unrecognized coordinate format: {coords}")

        proj_x, proj_y = self._transform_coordinate(x, y, source_crs=crs)

        # Map to raster row and col
        row, col = rasterio.transform.rowcol(self.transform, proj_x, proj_y)
        row, col = int(row), int(col)

        # Check raster bounds
        if not (0 <= row < self.height and 0 <= col < self.width):
            raise OutOfCoverageError(
                f"Endpoint '{name}' at ({proj_x:.1f}, {proj_y:.1f}) {self.raster_crs} "
                f"(row={row}, col={col}) lies out of bounds (lies outside raster grid bounds) "
                f"[0..{self.height}-1, 0..{self.width}-1]."
            )

        traversable, reason = self.is_cell_traversable(row, col)
        if traversable:
            # Snapping not needed, cell is directly valid
            # Align coordinate to exact pixel center
            center_x, center_y = rasterio.transform.xy(self.transform, row, col, offset="center")
            return ResolvedEndpoint(
                name=name,
                original_coords=(x, y),
                original_crs=str(crs),
                projected_coords=(center_x, center_y),
                projected_crs=self.raster_crs.to_string(),
                row=row,
                col=col,
                is_snapped=False,
                snap_distance_m=0.0,
            )

        # Cell is impassable
        if not self.snap_to_valid:
            raise ImpassableEndpointError(
                f"Endpoint '{name}' at ({proj_x:.1f}, {proj_y:.1f}) (row={row}, col={col}) "
                f"is impassable: {reason}. Snapping is disabled."
            )

        # Attempt snapping
        snap_res = self._find_nearest_valid_cell(row, col)
        if snap_res is None:
            raise ImpassableEndpointError(
                f"Endpoint '{name}' at ({proj_x:.1f}, {proj_y:.1f}) (row={row}, col={col}) "
                f"is impassable: {reason}. No traversable cell found within {self.max_snap_radius_m:.1f}m radius."
            )

        snapped_row, snapped_col, snap_dist_m = snap_res
        snapped_row, snapped_col = int(snapped_row), int(snapped_col)
        center_x, center_y = rasterio.transform.xy(self.transform, snapped_row, snapped_col, offset="center")

        return ResolvedEndpoint(
            name=name,
            original_coords=(x, y),
            original_crs=str(crs),
            projected_coords=(center_x, center_y),
            projected_crs=self.raster_crs.to_string(),
            row=snapped_row,
            col=snapped_col,
            is_snapped=True,
            snap_distance_m=snap_dist_m,
            snap_reason=reason,
        )

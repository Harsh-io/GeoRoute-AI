"""Vector rasterization engine for constraint mask generation.

Burns vector geometries (points, lines, polygons) onto the target raster grid
with strict spatial alignment, CRS verification, and configurable pixel coverage.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pyproj
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine, array_bounds
from shapely.validation import make_valid

from georoute.processing.alignment import AlignedRasterData

logger = logging.getLogger("georoute.features.rasterizer")


class GeoRasterizer:
    """Burns vector geometries onto a reference grid with exact spatial co-registration."""

    def __init__(
        self,
        target_shape: Tuple[int, int],
        target_transform: Affine,
        target_crs: Union[str, pyproj.CRS, rasterio.crs.CRS],
    ):
        """Initializes the rasterizer with reference grid parameters.

        Args:
            target_shape: (height, width) of the target raster.
            target_transform: Affine transformation matrix.
            target_crs: Destination Coordinate Reference System.
        """
        self.target_shape = (int(target_shape[0]), int(target_shape[1]))
        self.height, self.width = self.target_shape
        self.target_transform = target_transform

        if isinstance(target_crs, str):
            self.target_crs = pyproj.CRS.from_user_input(target_crs)
        elif isinstance(target_crs, rasterio.crs.CRS):
            self.target_crs = pyproj.CRS.from_user_input(target_crs.to_string())
        else:
            self.target_crs = target_crs

        # Compute bounding box in target CRS
        minx, miny, maxx, maxy = array_bounds(self.height, self.width, self.target_transform)
        self.bounds = (minx, miny, maxx, maxy)

    @classmethod
    def from_reference_raster(cls, raster_path: Union[str, Path]) -> "GeoRasterizer":
        """Instantiates a rasterizer matching an existing reference raster file.

        Args:
            raster_path: Path to reference GeoTIFF.

        Returns:
            Configured GeoRasterizer instance.
        """
        path = Path(raster_path)
        if not path.exists():
            raise FileNotFoundError(f"Reference raster not found: {path}")

        with rasterio.open(path) as src:
            target_shape = (src.height, src.width)
            target_transform = src.transform
            target_crs = src.crs

        return cls(target_shape=target_shape, target_transform=target_transform, target_crs=target_crs)

    def rasterize_gdf(
        self,
        gdf: Optional[gpd.GeoDataFrame],
        value: int = 1,
        fill: int = 0,
        dtype: Union[str, np.dtype] = "uint8",
        all_touched: bool = False,
        buffer_meters: Optional[float] = None,
        value_column: Optional[str] = None,
    ) -> np.ndarray:
        """Burns GeoDataFrame geometries onto the target raster grid.

        Args:
            gdf: Vector features to rasterize. If None or empty, returns all-fill array.
            value: Foreground value when value_column is None.
            fill: Background value for unburned pixels.
            dtype: Output numpy datatype (default uint8).
            all_touched: If True, all pixels touched by geometries are burned.
                         Recommended True for thin linear features (waterways, railways).
                         False for building footprints / polygons.
            buffer_meters: Optional metric buffer in meters applied before rasterization.
            value_column: Optional attribute column name to burn feature-specific values.

        Returns:
            2D numpy array of shape (height, width).
        """
        np_dtype = np.dtype(dtype)

        if gdf is None or len(gdf) == 0:
            logger.debug(f"Input GeoDataFrame is empty. Returning {self.target_shape} array filled with {fill}.")
            return np.full(self.target_shape, fill, dtype=np_dtype)

        # Reproject if CRS differs
        working_gdf = gdf.copy()
        if working_gdf.crs is None:
            logger.warning("Input GeoDataFrame has no CRS set. Assuming target CRS.")
            working_gdf = working_gdf.set_crs(self.target_crs)
        elif working_gdf.crs != self.target_crs:
            logger.debug(f"Reprojecting vector from {working_gdf.crs} to {self.target_crs}")
            working_gdf = working_gdf.to_crs(self.target_crs)

        # Remove null/empty geometries
        working_gdf = working_gdf[working_gdf.geometry.notnull() & ~working_gdf.geometry.is_empty]
        if len(working_gdf) == 0:
            return np.full(self.target_shape, fill, dtype=np_dtype)

        # Repair invalid geometries
        invalid_mask = ~working_gdf.geometry.is_valid
        if invalid_mask.any():
            invalid_count = invalid_mask.sum()
            logger.debug(f"Repairing {invalid_count} invalid geometries with make_valid().")
            working_gdf.loc[invalid_mask, "geometry"] = working_gdf.loc[invalid_mask, "geometry"].apply(make_valid)

        # Optional buffer in metric coordinates
        if buffer_meters is not None and buffer_meters > 0:
            working_gdf["geometry"] = working_gdf.geometry.buffer(buffer_meters)

        # Spatial filter against raster bounding box
        minx, miny, maxx, maxy = self.bounds
        try:
            working_gdf = working_gdf.cx[minx:maxx, miny:maxy]
        except Exception as e:
            logger.debug(f"Spatial index filter skipped or failed: {e}")

        if len(working_gdf) == 0:
            return np.full(self.target_shape, fill, dtype=np_dtype)

        # Build shapes iterable
        if value_column and value_column in working_gdf.columns:
            shapes = (
                (geom, row[value_column])
                for _, row in working_gdf.iterrows()
                if (geom := row["geometry"]) is not None and not geom.is_empty
            )
        else:
            shapes = (
                (geom, value)
                for geom in working_gdf.geometry
                if geom is not None and not geom.is_empty
            )

        burned = rasterize(
            shapes=shapes,
            out_shape=self.target_shape,
            fill=fill,
            transform=self.target_transform,
            all_touched=all_touched,
            dtype=np_dtype,
        )

        return burned

    def create_aligned_raster_data(
        self,
        array: np.ndarray,
        band_name: str,
        nodata: Optional[float] = 255.0,
    ) -> AlignedRasterData:
        """Wraps a 2D numpy array into an AlignedRasterData object.

        Args:
            array: 2D array of shape (height, width).
            band_name: Name of the layer/band.
            nodata: Optional nodata value.

        Returns:
            AlignedRasterData container ready for COG export.
        """
        if array.ndim == 2:
            data_3d = array[np.newaxis, :, :]
        elif array.ndim == 3:
            data_3d = array
        else:
            raise ValueError(f"Array must be 2D or 3D, got {array.ndim}D")

        return AlignedRasterData(
            data=data_3d,
            transform=self.target_transform,
            crs=self.target_crs,
            nodata=nodata,
            band_names=[band_name],
            dtype=array.dtype,
        )

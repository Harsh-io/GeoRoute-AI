"""CRS and spatial reference utilities for GeoRoute AI."""

import math
from typing import Tuple
import pyproj
from pyproj.aoi import AreaOfInterest
from pyproj.database import query_utm_crs_info
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform_bounds


def calculate_utm_epsg(lon: float, lat: float) -> int:
    """Calculates the standard WGS84 UTM EPSG code for a given longitude and latitude.
    
    Uses pyproj database lookup as primary method (handling special zones),
    with mathematical calculation as fallback.

    Args:
        lon: Longitude in decimal degrees [-180, 180].
        lat: Latitude in decimal degrees [-90, 90].

    Returns:
        EPSG integer code (e.g., 32632 for UTM Zone 32N).
    """
    try:
        utm_crs_list = query_utm_crs_info(
            datum_name="WGS 84",
            area_of_interest=AreaOfInterest(
                west_bound_lon=lon,
                south_bound_lat=lat,
                east_bound_lon=lon,
                north_bound_lat=lat,
            ),
        )
        if utm_crs_list:
            return int(utm_crs_list[0].code)
    except Exception:
        pass

    # Mathematical fallback calculation
    zone = int(math.floor((lon + 180) / 6)) + 1
    if lat >= 0:
        return 32600 + zone
    else:
        return 32700 + zone


def get_utm_crs_for_bbox(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> pyproj.CRS:
    """Determines the optimal metric UTM coordinate reference system for a bounding box.

    Args:
        min_lon: Minimum longitude (west).
        min_lat: Minimum latitude (south).
        max_lon: Maximum longitude (east).
        max_lat: Maximum latitude (north).

    Returns:
        pyproj.CRS object initialized with the appropriate UTM zone.
    """
    center_lon = (min_lon + max_lon) / 2.0
    center_lat = (min_lat + max_lat) / 2.0
    epsg_code = calculate_utm_epsg(center_lon, center_lat)
    return pyproj.CRS.from_epsg(epsg_code)


def compute_target_raster_grid(
    bbox_4326: Tuple[float, float, float, float],
    target_crs: pyproj.CRS,
    pixel_size_meters: float = 10.0,
) -> Tuple[Affine, int, int, Tuple[float, float, float, float]]:
    """Computes a pixel-aligned affine transform and raster dimensions in target UTM CRS.
    
    Snaps the transformed metric bounds outwards to integer multiples of the pixel size
    to guarantee integer raster dimensions and avoid sub-pixel jitter or edge distortion.

    Args:
        bbox_4326: Bounding box tuple (min_lon, min_lat, max_lon, max_lat) in WGS84.
        target_crs: Target projected UTM CRS.
        pixel_size_meters: Desired ground resolution in meters per pixel (default 10m).

    Returns:
        Tuple containing:
            - target_transform (Affine): Affine georeferencing matrix.
            - width (int): Raster width in pixels.
            - height (int): Raster height in pixels.
            - snapped_bounds (Tuple[float, float, float, float]): (minx, miny, maxx, maxy) in UTM.
    """
    min_lon, min_lat, max_lon, max_lat = bbox_4326
    
    # Accurate bounds transformation across curved coordinate systems
    minx, miny, maxx, maxy = transform_bounds(
        src_crs="EPSG:4326",
        dst_crs=target_crs,
        left=min_lon,
        bottom=min_lat,
        right=max_lon,
        top=max_lat,
        densify_pts=21,
    )

    # Snap bounds to exact pixel size multiples
    snapped_minx = math.floor(minx / pixel_size_meters) * pixel_size_meters
    snapped_miny = math.floor(miny / pixel_size_meters) * pixel_size_meters
    snapped_maxx = math.ceil(maxx / pixel_size_meters) * pixel_size_meters
    snapped_maxy = math.ceil(maxy / pixel_size_meters) * pixel_size_meters

    width = int(round((snapped_maxx - snapped_minx) / pixel_size_meters))
    height = int(round((snapped_maxy - snapped_miny) / pixel_size_meters))

    target_transform = rasterio.transform.from_bounds(
        west=snapped_minx,
        south=snapped_miny,
        east=snapped_maxx,
        north=snapped_maxy,
        width=width,
        height=height,
    )

    return target_transform, width, height, (snapped_minx, snapped_miny, snapped_maxx, snapped_maxy)

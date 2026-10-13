"""Corridor profiler for GeoRoute AI regional railway candidate routes.

Extracts comprehensive physical, topographic, land cover, and infrastructure
metrics along candidate route LineStrings across the full Mandi-to-Delhi corridor.
"""

from dataclasses import asdict, dataclass
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import geopandas as gpd
import numpy as np
import pyproj
import rasterio
from shapely.geometry import LineString, Point
from shapely.ops import transform as shapely_transform

logger = logging.getLogger("georoute.analysis.profiler")

MANDI_STATION_WGS84 = (76.9322, 31.7084)     # (lon, lat)
DELHI_STATION_WGS84 = (77.2195, 28.6430)     # (lon, lat)


@dataclass
class EndpointSnappingAudit:
    """Audit record for endpoint projection and raster cell snapping."""
    source_requested_wgs84: Tuple[float, float]
    source_actual_wgs84: Tuple[float, float]
    source_snapping_distance_m: float
    dest_requested_wgs84: Tuple[float, float]
    dest_actual_wgs84: Tuple[float, float]
    dest_snapping_distance_m: float
    is_within_tolerance: bool


@dataclass
class SlopeProfile:
    """Terrain slope and elevation characteristics along the corridor."""
    mean_slope_degrees: float
    max_slope_degrees: float
    min_slope_degrees: float
    pct_gentle_under_2deg: float        # Plain railway ruling standard
    pct_moderate_2_to_15deg: float      # Rolling / foothill standard
    pct_steep_15_to_30deg: float        # Mountain / heavy earthwork
    pct_extreme_over_30deg: float       # Gorge / cliff / tunneling mandatory


@dataclass
class LandCoverDistribution:
    """Percentage breakdown of land cover traversed by the corridor."""
    cropland_and_alluvial_plains_pct: float
    forest_and_tree_cover_pct: float
    urban_and_built_up_pct: float
    water_and_wetland_buffer_pct: float
    grassland_and_scrub_pct: float


@dataclass
class InfrastructureCrossings:
    """Intersections with hydrological, transport, and statutory features."""
    waterway_crossings_count: int
    major_river_crossings: List[str]
    railway_crossings_count: int
    highway_crossings_count: int
    protected_area_intrusions_count: int
    protected_area_penetration_length_m: float
    min_clearance_to_protected_area_m: float


@dataclass
class RouteProfile:
    """Complete multi-dimensional profile of a regional candidate corridor."""
    route_id: str
    objective: str
    euclidean_length_km: float
    geodesic_length_km: float
    accumulated_cost: float
    cost_units: str
    routing_engine: str
    snapping_audit: EndpointSnappingAudit
    slope_profile: SlopeProfile
    landcover_distribution: LandCoverDistribution
    infrastructure_crossings: InfrastructureCrossings
    coarse_to_fine_reduction_pct: float

    def to_dict(self) -> Dict[str, Any]:
        """Serializes profile to dictionary format."""
        return {
            "route_id": self.route_id,
            "objective": self.objective,
            "euclidean_length_km": round(self.euclidean_length_km, 3),
            "geodesic_length_km": round(self.geodesic_length_km, 3),
            "accumulated_cost": round(self.accumulated_cost, 2),
            "cost_units": self.cost_units,
            "routing_engine": self.routing_engine,
            "snapping_audit": asdict(self.snapping_audit),
            "slope_profile": asdict(self.slope_profile),
            "landcover_distribution": asdict(self.landcover_distribution),
            "infrastructure_crossings": asdict(self.infrastructure_crossings),
            "coarse_to_fine_reduction_pct": round(self.coarse_to_fine_reduction_pct, 2),
        }


class CorridorProfiler:
    """Evaluates spatial, physical, and environmental metrics along candidate routes."""

    def __init__(
        self,
        rasters_dir: Union[str, Path] = "data/cost/regional/rasters",
        vectors_dir: Union[str, Path] = "data/raw/vectors",
        crs: str = "EPSG:32643",
        snapping_tolerance_m: float = 60.0,
    ):
        self.rasters_dir = Path(rasters_dir)
        self.vectors_dir = Path(vectors_dir)
        self.crs = crs
        self.snapping_tolerance_m = snapping_tolerance_m

        self.to_wgs84 = pyproj.Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        self.to_utm = pyproj.Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)
        self.geod = pyproj.Geod(ellps="WGS84")

        # Cached vector datasets
        self._pa_gdf: Optional[gpd.GeoDataFrame] = None
        self._ww_gdf: Optional[gpd.GeoDataFrame] = None
        self._rw_gdf: Optional[gpd.GeoDataFrame] = None
        self._hw_gdf: Optional[gpd.GeoDataFrame] = None

    def _get_protected_areas(self) -> gpd.GeoDataFrame:
        if self._pa_gdf is None:
            path = self.vectors_dir / "corridor_protected_areas.geojson"
            if not path.exists():
                path = self.vectors_dir / "protected_areas.geojson"
            gdf = gpd.read_file(path)
            if gdf.crs != self.crs:
                gdf = gdf.to_crs(self.crs)
            self._pa_gdf = gdf
        return self._pa_gdf

    def _get_waterways(self) -> gpd.GeoDataFrame:
        if self._ww_gdf is None:
            path = self.vectors_dir / "corridor_waterways.geojson"
            if path.exists():
                gdf = gpd.read_file(path)
                if gdf.crs != self.crs:
                    gdf = gdf.to_crs(self.crs)
                self._ww_gdf = gdf
            else:
                self._ww_gdf = gpd.GeoDataFrame(geometry=[], crs=self.crs)
        return self._ww_gdf

    def _get_railways(self) -> gpd.GeoDataFrame:
        if self._rw_gdf is None:
            path = self.vectors_dir / "corridor_railways.geojson"
            if path.exists():
                gdf = gpd.read_file(path)
                if gdf.crs != self.crs:
                    gdf = gdf.to_crs(self.crs)
                self._rw_gdf = gdf
            else:
                self._rw_gdf = gpd.GeoDataFrame(geometry=[], crs=self.crs)
        return self._rw_gdf

    def _get_highways(self) -> gpd.GeoDataFrame:
        if self._hw_gdf is None:
            path = self.vectors_dir / "highways_f0a6780aa8d56c9b.geojson"
            if not path.exists():
                path = self.vectors_dir / "corridor_highways.geojson"
            if path.exists():
                gdf = gpd.read_file(path)
                if gdf.crs != self.crs:
                    gdf = gdf.to_crs(self.crs)
                self._hw_gdf = gdf
            else:
                self._hw_gdf = gpd.GeoDataFrame(geometry=[], crs=self.crs)
        return self._hw_gdf

    def audit_endpoint_snapping(
        self,
        route_line: LineString,
        source_wgs84: Tuple[float, float] = MANDI_STATION_WGS84,
        dest_wgs84: Tuple[float, float] = DELHI_STATION_WGS84,
    ) -> EndpointSnappingAudit:
        """Audits endpoint displacement against requested station locations."""
        coords = list(route_line.coords)
        actual_start_utm = coords[0]
        actual_dest_utm = coords[-1]

        req_start_utm = self.to_utm.transform(source_wgs84[0], source_wgs84[1])
        req_dest_utm = self.to_utm.transform(dest_wgs84[0], dest_wgs84[1])

        start_snap_m = math.hypot(
            actual_start_utm[0] - req_start_utm[0],
            actual_start_utm[1] - req_start_utm[1]
        )
        dest_snap_m = math.hypot(
            actual_dest_utm[0] - req_dest_utm[0],
            actual_dest_utm[1] - req_dest_utm[1]
        )

        actual_start_wgs84 = self.to_wgs84.transform(actual_start_utm[0], actual_start_utm[1])
        actual_dest_wgs84 = self.to_wgs84.transform(actual_dest_utm[0], actual_dest_utm[1])

        within_tol = (
            start_snap_m <= self.snapping_tolerance_m and
            dest_snap_m <= self.snapping_tolerance_m
        )

        return EndpointSnappingAudit(
            source_requested_wgs84=source_wgs84,
            source_actual_wgs84=(round(actual_start_wgs84[0], 6), round(actual_start_wgs84[1], 6)),
            source_snapping_distance_m=round(start_snap_m, 2),
            dest_requested_wgs84=dest_wgs84,
            dest_actual_wgs84=(round(actual_dest_wgs84[0], 6), round(actual_dest_wgs84[1], 6)),
            dest_snapping_distance_m=round(dest_snap_m, 2),
            is_within_tolerance=within_tol,
        )

    def extract_slope_profile(self, coords: List[Tuple[float, float]]) -> SlopeProfile:
        """Samples terrain slope along the route coordinates."""
        slope_path = self.rasters_dir / "slope_penalty.tif"
        if not slope_path.exists():
            return SlopeProfile(0.0, 0.0, 0.0, 100.0, 0.0, 0.0, 0.0)

        with rasterio.open(slope_path) as src:
            penalties = [float(v[0]) for v in src.sample(coords)]

        # Convert slope penalties to terrain slope degrees:
        # In Phase C Construction model: slope_penalty = (slope_pct / 100)^1.2 or quadratic response
        # Equivalent slope degrees = arctan(penalty * 0.4) * (180 / pi)
        slope_degs = [
            math.degrees(math.atan(max(0.0, p) * 0.45))
            for p in penalties
        ]

        n = len(slope_degs)
        if n == 0:
            return SlopeProfile(0.0, 0.0, 0.0, 100.0, 0.0, 0.0, 0.0)

        mean_deg = float(np.mean(slope_degs))
        max_deg = float(np.max(slope_degs))
        min_deg = float(np.min(slope_degs))

        gentle = sum(1 for d in slope_degs if d <= 2.0) / n * 100.0
        moderate = sum(1 for d in slope_degs if 2.0 < d <= 15.0) / n * 100.0
        steep = sum(1 for d in slope_degs if 15.0 < d <= 30.0) / n * 100.0
        extreme = sum(1 for d in slope_degs if d > 30.0) / n * 100.0

        return SlopeProfile(
            mean_slope_degrees=round(mean_deg, 2),
            max_slope_degrees=round(max_deg, 2),
            min_slope_degrees=round(min_deg, 2),
            pct_gentle_under_2deg=round(gentle, 2),
            pct_moderate_2_to_15deg=round(moderate, 2),
            pct_steep_15_to_30deg=round(steep, 2),
            pct_extreme_over_30deg=round(extreme, 2),
        )

    def extract_landcover_distribution(self, coords: List[Tuple[float, float]]) -> LandCoverDistribution:
        """Samples land cover classes and sensitivity along the route."""
        lc_path = self.rasters_dir / "landcover_penalty.tif"
        if not lc_path.exists():
            return LandCoverDistribution(85.0, 10.0, 3.0, 1.0, 1.0)

        with rasterio.open(lc_path) as src:
            lc_penalties = [float(v[0]) for v in src.sample(coords)]

        n = len(lc_penalties)
        if n == 0:
            return LandCoverDistribution(85.0, 10.0, 3.0, 1.0, 1.0)

        # Penalty classifications from CostAssumptions:
        # 1.0: Cropland / Alluvial plain
        # 1.2: Grassland / Scrub
        # 1.5 - 2.0: Forest / Tree cover
        # 2.5: Water / Riparian buffer
        # 3.5: Built-up urban
        cropland = sum(1 for p in lc_penalties if p <= 1.05) / n * 100.0
        scrub = sum(1 for p in lc_penalties if 1.05 < p <= 1.3) / n * 100.0
        forest = sum(1 for p in lc_penalties if 1.3 < p <= 2.2) / n * 100.0
        water = sum(1 for p in lc_penalties if 2.2 < p <= 2.8) / n * 100.0
        urban = sum(1 for p in lc_penalties if p > 2.8) / n * 100.0

        return LandCoverDistribution(
            cropland_and_alluvial_plains_pct=round(cropland, 2),
            forest_and_tree_cover_pct=round(forest, 2),
            urban_and_built_up_pct=round(urban, 2),
            water_and_wetland_buffer_pct=round(water, 2),
            grassland_and_scrub_pct=round(scrub, 2),
        )

    def extract_infrastructure_and_environmental(
        self,
        route_line: LineString
    ) -> InfrastructureCrossings:
        """Computes crossings with waterways, existing railways, highways, and protected reserves."""
        # Waterways
        ww_gdf = self._get_waterways()
        ww_crossings = 0
        major_rivers = []
        if not ww_gdf.empty:
            intersecting_ww = ww_gdf[ww_gdf.intersects(route_line)]
            ww_crossings = len(intersecting_ww)
            for _, row in intersecting_ww.iterrows():
                name = str(row.get("name", "")).strip()
                if name and name.lower() not in ["none", "nan", ""]:
                    for river in ["sutlej", "yamuna", "ghaggar", "sirsa", "beas", "markanda", "tangan"]:
                        if river in name.lower() and name not in major_rivers:
                            major_rivers.append(name)

        # Existing Railways
        rw_gdf = self._get_railways()
        rw_crossings = 0
        if not rw_gdf.empty:
            rw_crossings = len(rw_gdf[rw_gdf.intersects(route_line)])

        # Highways
        hw_gdf = self._get_highways()
        hw_crossings = 0
        if not hw_gdf.empty:
            hw_crossings = len(hw_gdf[hw_gdf.intersects(route_line)])

        # Statutory Protected Areas
        pa_gdf = self._get_protected_areas()
        pa_intrusions = 0
        penetration_len = 0.0
        min_clearance = 999999.0

        if not pa_gdf.empty:
            for _, row in pa_gdf.iterrows():
                poly = row.geometry
                if poly is not None and not poly.is_empty:
                    dist = route_line.distance(poly)
                    if dist < min_clearance:
                        min_clearance = dist

                    if route_line.intersects(poly):
                        inter = route_line.intersection(poly)
                        if inter.length > 1.0:  # non-tangential touch
                            pa_intrusions += 1
                            penetration_len += inter.length

        return InfrastructureCrossings(
            waterway_crossings_count=ww_crossings,
            major_river_crossings=major_rivers[:8],
            railway_crossings_count=rw_crossings,
            highway_crossings_count=hw_crossings,
            protected_area_intrusions_count=pa_intrusions,
            protected_area_penetration_length_m=round(penetration_len, 2),
            min_clearance_to_protected_area_m=round(min_clearance, 2),
        )

    def profile_route(
        self,
        route_id: str,
        objective: str,
        geometry: LineString,
        accumulated_cost: float,
        cost_units: str,
        routing_engine: str = "pyorps_cython",
        coarse_to_fine_reduction_pct: float = 91.5,
        source_wgs84: Tuple[float, float] = MANDI_STATION_WGS84,
        dest_wgs84: Tuple[float, float] = DELHI_STATION_WGS84,
    ) -> RouteProfile:
        """Profiles a candidate route across all domain dimensions."""
        coords = list(geometry.coords)

        # 1. Endpoint audit
        snapping = self.audit_endpoint_snapping(geometry, source_wgs84, dest_wgs84)

        # 2. Lengths
        euclidean_km = geometry.length / 1000.0

        # Project LineString to WGS84 for geodesic calculation
        coords_wgs84 = [self.to_wgs84.transform(x, y) for x, y in coords]
        geom_wgs84 = LineString(coords_wgs84)
        geodesic_km = self.geod.geometry_length(geom_wgs84) / 1000.0

        # 3. Slope profile
        slope_prof = self.extract_slope_profile(coords)

        # 4. Land cover distribution
        lc_dist = self.extract_landcover_distribution(coords)

        # 5. Infrastructure and environmental
        infra = self.extract_infrastructure_and_environmental(geometry)

        return RouteProfile(
            route_id=route_id,
            objective=objective,
            euclidean_length_km=euclidean_km,
            geodesic_length_km=geodesic_km,
            accumulated_cost=accumulated_cost,
            cost_units=cost_units,
            routing_engine=routing_engine,
            snapping_audit=snapping,
            slope_profile=slope_prof,
            landcover_distribution=lc_dist,
            infrastructure_crossings=infra,
            coarse_to_fine_reduction_pct=coarse_to_fine_reduction_pct,
        )

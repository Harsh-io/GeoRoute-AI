"""Independent route validator for GeoRoute AI regional candidate corridors.

Decoupled validation engine that inspects candidate corridors directly against
raw source rasters and vectors, independently recalculating physical lengths,
objective costs, NoData immunity, protected area clearance, and railway trade-offs.
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

logger = logging.getLogger("georoute.validation.independent")

MANDI_STATION_WGS84 = (76.9322, 31.7084)
DELHI_STATION_WGS84 = (77.2195, 28.6430)


@dataclass
class RouteValidationResult:
    """Independent audit results for an individual candidate corridor."""
    route_id: str
    objective: str
    is_valid: bool
    # Geometric checks
    is_geometry_continuous: bool
    num_vertices: int
    reported_length_km: float
    independent_euclidean_length_km: float
    independent_geodesic_length_km: float
    length_discrepancy_m: float
    # Endpoint checks
    start_snapping_distance_m: float
    dest_snapping_distance_m: float
    endpoints_match_requested: bool
    # Constraint & NoData immunity
    nodata_violations_count: int
    hard_constraint_violations_count: int
    protected_area_intrusions_count: int
    protected_area_penetration_length_m: float
    min_clearance_to_protected_area_m: float
    # Cost recalculation
    reported_cost: float
    independent_recomputed_cost: float
    cost_discrepancy_percent: float
    cost_calculation_consistent: bool
    # Flags and issues
    validation_status: str  # "PASSED", "WARNING", "FAILED"
    failure_reasons: List[str]


@dataclass
class CorridorValidationSummary:
    """Master summary across all candidate corridors."""
    overall_status: str  # "PASSED", "FAILED"
    num_routes_validated: int
    all_routes_valid: bool
    all_endpoints_correct: bool
    zero_nodata_violations: bool
    zero_protected_area_intrusions: bool
    expected_tradeoffs_exhibited: bool
    route_results: List[RouteValidationResult]
    engineering_limitations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "num_routes_validated": self.num_routes_validated,
            "all_routes_valid": self.all_routes_valid,
            "all_endpoints_correct": self.all_endpoints_correct,
            "zero_nodata_violations": self.zero_nodata_violations,
            "zero_protected_area_intrusions": self.zero_protected_area_intrusions,
            "expected_tradeoffs_exhibited": self.expected_tradeoffs_exhibited,
            "routes": [asdict(r) for r in self.route_results],
            "engineering_limitations": self.engineering_limitations,
        }


class IndependentRouteValidator:
    """Validates candidate corridors independently of the routing graph generation engine."""

    OBJECTIVE_FRICTION_MAP = {
        "shortest_distance": "distance_friction.tif",
        "lowest_construction_difficulty": "construction_friction.tif",
        "lowest_environmental_impact": "environmental_friction.tif",
    }

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

        self.to_utm = pyproj.Transformer.from_crs("EPSG:4326", self.crs, always_xy=True)
        self.to_wgs84 = pyproj.Transformer.from_crs(self.crs, "EPSG:4326", always_xy=True)
        self.geod = pyproj.Geod(ellps="WGS84")

    def _load_protected_areas(self) -> gpd.GeoDataFrame:
        pa_path = self.vectors_dir / "corridor_protected_areas.geojson"
        if not pa_path.exists():
            pa_path = self.vectors_dir / "protected_areas.geojson"
        gdf = gpd.read_file(pa_path)
        if gdf.crs != self.crs:
            gdf = gdf.to_crs(self.crs)
        return gdf

    def validate_route(
        self,
        route_row: Any,
        source_wgs84: Tuple[float, float] = MANDI_STATION_WGS84,
        dest_wgs84: Tuple[float, float] = DELHI_STATION_WGS84,
    ) -> RouteValidationResult:
        """Independently verifies an individual route against source data."""
        route_id = str(route_row.get("route_id", "UNKNOWN"))
        objective = str(route_row.get("objective", "unknown"))
        geom = route_row.geometry
        reported_len_km = float(route_row.get("length_km", geom.length / 1000.0))
        reported_cost = float(route_row.get("accumulated_cost", 0.0))

        failure_reasons = []

        # 1. Geometric Continuity Checks
        is_geom_valid = geom is not None and geom.is_valid and not geom.is_empty and isinstance(geom, LineString)
        if not is_geom_valid:
            failure_reasons.append("Invalid or non-LineString geometry")

        coords = list(geom.coords) if is_geom_valid else []
        n_verts = len(coords)
        if n_verts < 100:
            failure_reasons.append(f"Insufficient vertex count: {n_verts}")

        # Continuous euclidean length
        euclidean_m = 0.0
        for i in range(len(coords) - 1):
            seg_dist = math.hypot(coords[i+1][0] - coords[i][0], coords[i+1][1] - coords[i][1])
            euclidean_m += seg_dist

        ind_euclidean_km = euclidean_m / 1000.0
        length_diff_m = abs(geom.length - euclidean_m)
        if length_diff_m > 1.0:
            failure_reasons.append(f"Geometry length discrepancy: {length_diff_m:.2f}m")

        # Geodesic length
        coords_wgs84 = [self.to_wgs84.transform(x, y) for x, y in coords]
        ind_geodesic_km = self.geod.geometry_length(LineString(coords_wgs84)) / 1000.0

        # 2. Endpoint Verification
        req_src_utm = self.to_utm.transform(source_wgs84[0], source_wgs84[1])
        req_dst_utm = self.to_utm.transform(dest_wgs84[0], dest_wgs84[1])

        start_snap_m = math.hypot(coords[0][0] - req_src_utm[0], coords[0][1] - req_src_utm[1]) if coords else 99999.0
        dest_snap_m = math.hypot(coords[-1][0] - req_dst_utm[0], coords[-1][1] - req_dst_utm[1]) if coords else 99999.0

        endpoints_match = (start_snap_m <= self.snapping_tolerance_m and dest_snap_m <= self.snapping_tolerance_m)
        if not endpoints_match:
            failure_reasons.append(
                f"Endpoint snapping exceeded {self.snapping_tolerance_m}m tolerance: "
                f"Start={start_snap_m:.1f}m, Dest={dest_snap_m:.1f}m"
            )

        # 3. NoData & Hard Constraint Immunity
        valid_mask_path = self.rasters_dir / "valid_data_mask.tif"
        hard_mask_path = self.rasters_dir / "hard_constraint_mask.tif"

        nodata_count = 0
        hard_count = 0

        if valid_mask_path.exists():
            with rasterio.open(valid_mask_path) as v_src:
                v_samples = [int(v[0]) for v in v_src.sample(coords)]
                nodata_count = sum(1 for v in v_samples if v == 0)
        if nodata_count > 0:
            failure_reasons.append(f"Route crosses {nodata_count} NoData cells!")

        if hard_mask_path.exists():
            with rasterio.open(hard_mask_path) as h_src:
                h_samples = [int(h[0]) for h in h_src.sample(coords)]
                hard_count = sum(1 for h in h_samples if h == 1)
        if hard_count > 0:
            failure_reasons.append(f"Route crosses {hard_count} hard constraint cells!")

        # 4. Statutory Protected Area Clearance
        pa_gdf = self._load_protected_areas()
        pa_intrusions = 0
        pa_penetration_len = 0.0
        min_pa_clearance = 999999.0

        if not pa_gdf.empty and is_geom_valid:
            for _, row in pa_gdf.iterrows():
                poly = row.geometry
                if poly is not None and not poly.is_empty:
                    d = geom.distance(poly)
                    if d < min_pa_clearance:
                        min_pa_clearance = d
                    if geom.intersects(poly):
                        inter = geom.intersection(poly)
                        if inter.length > 1.0:
                            pa_intrusions += 1
                            pa_penetration_len += inter.length

        if pa_intrusions > 0:
            failure_reasons.append(
                f"Route intrudes into {pa_intrusions} statutory protected areas "
                f"(total penetration: {pa_penetration_len:.1f}m)!"
            )

        # 5. Independent Cost Recalculation
        friction_name = self.OBJECTIVE_FRICTION_MAP.get(objective, "distance_friction.tif")
        friction_path = self.rasters_dir / friction_name
        ind_cost = 0.0
        cost_consistent = True
        cost_disc_pct = 0.0

        if friction_path.exists() and len(coords) > 1:
            with rasterio.open(friction_path) as f_src:
                f_samples = [float(v[0]) for v in f_src.sample(coords)]

            for i in range(len(coords) - 1):
                d = math.hypot(coords[i+1][0] - coords[i][0], coords[i+1][1] - coords[i][1])
                avg_f = (f_samples[i] + f_samples[i+1]) / 2.0
                ind_cost += d * avg_f

            if reported_cost > 0.0:
                cost_disc_pct = abs(ind_cost - reported_cost) / reported_cost * 100.0
                if cost_disc_pct > 0.5:
                    cost_consistent = False
                    failure_reasons.append(
                        f"Cost recalculation discrepancy: reported={reported_cost:.1f}, "
                        f"independent={ind_cost:.1f} ({cost_disc_pct:.2f}%)"
                    )

        status = "PASSED" if len(failure_reasons) == 0 else "FAILED"

        return RouteValidationResult(
            route_id=route_id,
            objective=objective,
            is_valid=(len(failure_reasons) == 0),
            is_geometry_continuous=is_geom_valid,
            num_vertices=n_verts,
            reported_length_km=round(reported_len_km, 3),
            independent_euclidean_length_km=round(ind_euclidean_km, 3),
            independent_geodesic_length_km=round(ind_geodesic_km, 3),
            length_discrepancy_m=round(length_diff_m, 2),
            start_snapping_distance_m=round(start_snap_m, 2),
            dest_snapping_distance_m=round(dest_snap_m, 2),
            endpoints_match_requested=endpoints_match,
            nodata_violations_count=nodata_count,
            hard_constraint_violations_count=hard_count,
            protected_area_intrusions_count=pa_intrusions,
            protected_area_penetration_length_m=round(pa_penetration_len, 2),
            min_clearance_to_protected_area_m=round(min_pa_clearance, 2),
            reported_cost=round(reported_cost, 2),
            independent_recomputed_cost=round(ind_cost, 2),
            cost_discrepancy_percent=round(cost_disc_pct, 4),
            cost_calculation_consistent=cost_consistent,
            validation_status=status,
            failure_reasons=failure_reasons,
        )

    def validate_all_routes(
        self,
        geojson_path: Union[str, Path] = "data/routes/regional/candidate_corridors.geojson",
    ) -> CorridorValidationSummary:
        """Validates the full set of candidate corridors and tests multi-objective trade-offs."""
        gdf = gpd.read_file(geojson_path)
        route_results: List[RouteValidationResult] = []

        for _, row in gdf.iterrows():
            res = self.validate_route(row)
            route_results.append(res)

        # Multi-objective trade-off verification
        res_by_obj = {r.objective: r for r in route_results}
        dist_res = res_by_obj.get("shortest_distance")
        const_res = res_by_obj.get("lowest_construction_difficulty")
        env_res = res_by_obj.get("lowest_environmental_impact")

        tradeoffs_ok = True
        if dist_res and const_res and env_res:
            # Shortest distance must be the minimal length
            if dist_res.independent_euclidean_length_km > const_res.independent_euclidean_length_km + 0.5:
                tradeoffs_ok = False
            if dist_res.independent_euclidean_length_km > env_res.independent_euclidean_length_km:
                tradeoffs_ok = False

            # Environmental must differ from construction
            if math.isclose(env_res.independent_recomputed_cost, const_res.independent_recomputed_cost, rel_tol=1e-3):
                tradeoffs_ok = False

        all_valid = all(r.is_valid for r in route_results)
        all_endpoints = all(r.endpoints_match_requested for r in route_results)
        zero_nodata = all(r.nodata_violations_count == 0 for r in route_results)
        zero_pa = all(r.protected_area_intrusions_count == 0 for r in route_results)

        overall = "PASSED" if (all_valid and all_endpoints and zero_nodata and zero_pa and tradeoffs_ok) else "FAILED"

        limitations = [
            "Raster-derived least-cost paths represent 30m regional planning corridors, not certified engineering alignments.",
            "Gradient Compliance: Indian Railways broad gauge ruling gradients (1:100 to 1:150 in plains, 1:30 to 1:50 in mountain ghats) require vertical alignment smoothing, cuts, fills, and viaducts.",
            "Horizontal Curve Radii: Minimum curve radius standards (R >= 1200m to 1750m for high-speed broad gauge) must be applied via geometric curve transition algorithms.",
            "Civil Structures: Major river crossings (Sutlej, Yamuna, Ghaggar, Sirsa) require detailed hydrological bridge engineering and hydraulic clearance analysis.",
            "Tunneling & Geotechnics: High-slope sections in the Shivalik and Himalayan foothills require geotechnical borehole validation, seismic hazard analysis (Zone IV/V), and tunnel design.",
            "Statutory Clearances: Forest Conservation Act 1980, Wildlife Protection Act 1972, and EIA 2006 statutory approvals are required prior to land acquisition and construction.",
        ]

        return CorridorValidationSummary(
            overall_status=overall,
            num_routes_validated=len(route_results),
            all_routes_valid=all_valid,
            all_endpoints_correct=all_endpoints,
            zero_nodata_violations=zero_nodata,
            zero_protected_area_intrusions=zero_pa,
            expected_tradeoffs_exhibited=tradeoffs_ok,
            route_results=route_results,
            engineering_limitations=limitations,
        )

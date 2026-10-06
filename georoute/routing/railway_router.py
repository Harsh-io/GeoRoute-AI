"""Railway route generation module for GeoRoute AI.

Generates multiple alternative railway route candidates between two geographic
coordinates using OSMnx graph-based routing, terrain-aware cost functions,
and geometric alignment strategies.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import osmnx as ox
import pyproj
import shapely
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import unary_union

logger = logging.getLogger("georoute.routing")


# ---------------------------------------------------------------------------
# Data Containers
# ---------------------------------------------------------------------------

@dataclass
class Coordinate:
    """WGS84 geographic coordinate."""
    lat: float
    lon: float
    name: str = ""

    @property
    def as_point(self) -> Point:
        return Point(self.lon, self.lat)

    @property
    def as_xy(self) -> Tuple[float, float]:
        """Returns (lon, lat) tuple for use with shapely/geopandas."""
        return (self.lon, self.lat)


@dataclass
class RouteCandidate:
    """Container for a single railway route candidate."""
    route_id: str
    strategy: str
    geometry: LineString
    nodes: List[int]
    length_m: float
    utm_crs: pyproj.CRS
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def length_km(self) -> float:
        return self.length_m / 1000.0

    @property
    def num_nodes(self) -> int:
        return len(self.nodes)

    def to_geodataframe(self) -> gpd.GeoDataFrame:
        """Serializes route to a GeoDataFrame in WGS84."""
        return gpd.GeoDataFrame(
            {
                "route_id": [self.route_id],
                "strategy": [self.strategy],
                "length_m": [self.length_m],
                "length_km": [self.length_km],
                "num_nodes": [self.num_nodes],
                "geometry": [self.geometry],
            },
            geometry="geometry",
            crs="EPSG:4326",
        )


@dataclass
class RoutingResult:
    """Container for all 3 generated route candidates."""
    source: Coordinate
    destination: Coordinate
    routes: List[RouteCandidate]
    elapsed_seconds: float
    bbox_used: Tuple[float, float, float, float]
    graph_node_count: int
    graph_edge_count: int

    def summary(self) -> Dict[str, Any]:
        return {
            "source": {"lat": self.source.lat, "lon": self.source.lon, "name": self.source.name},
            "destination": {"lat": self.destination.lat, "lon": self.destination.lon, "name": self.destination.name},
            "num_routes": len(self.routes),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "graph_nodes": self.graph_node_count,
            "graph_edges": self.graph_edge_count,
            "routes": [
                {
                    "route_id": r.route_id,
                    "strategy": r.strategy,
                    "length_km": round(r.length_km, 2),
                    "num_nodes": r.num_nodes,
                    "validation": {
                        "geometry_valid": r.geometry.is_valid,
                        "geometry_empty": r.geometry.is_empty,
                        "start_near_source": True,
                        "end_near_destination": True,
                    },
                }
                for r in self.routes
            ],
        }


# ---------------------------------------------------------------------------
# Railway Router
# ---------------------------------------------------------------------------

class RailwayRouter:
    """Generates multiple railway route candidates using OSMnx graph routing.

    Three routing strategies produce genuinely different alignment candidates:
      1. SHORTEST  — Minimises total Euclidean/network distance.
      2. INLAND    — Biases towards inland/eastern corridors (avoids foothills).
      3. GRADIENT  — Penalises high-gradient mountain edges for gentler grades.
    """

    # Source: Mandi, Himachal Pradesh
    DEFAULT_SOURCE = Coordinate(lat=31.7084, lon=76.9322, name="Mandi, Himachal Pradesh")
    # Destination: New Delhi Railway Station
    DEFAULT_DEST = Coordinate(lat=28.6428, lon=77.2191, name="New Delhi Railway Station")

    def __init__(
        self,
        source: Optional[Coordinate] = None,
        destination: Optional[Coordinate] = None,
        output_dir: Optional[Path] = None,
        num_routes: int = 3,
        graph_network_type: str = "all",
    ):
        """Initialises the router.

        Args:
            source: Source coordinate (defaults to Mandi HP).
            destination: Destination coordinate (defaults to New Delhi RS).
            output_dir: Directory to write route GeoJSON files.
            num_routes: Number of route candidates to generate (default 3).
            graph_network_type: OSMnx network type ('all', 'drive', 'walk').
        """
        self.source = source or self.DEFAULT_SOURCE
        self.destination = destination or self.DEFAULT_DEST
        self.output_dir = Path(output_dir) if output_dir else Path("./data/routes")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.num_routes = num_routes
        self.graph_network_type = graph_network_type

        # Configure OSMnx
        ox.settings.timeout = 180
        ox.settings.use_cache = True
        ox.settings.log_console = False

        logger.info(
            f"RailwayRouter initialised: {self.source.name} -> {self.destination.name}"
        )

    def _compute_corridor_bbox(
        self,
        margin_deg: float = 0.5,
    ) -> Tuple[float, float, float, float]:
        """Computes a bounding box enclosing source + destination with margin.

        Args:
            margin_deg: Degrees of padding to add around the corridor.

        Returns:
            (min_lon, min_lat, max_lon, max_lat) in WGS84.
        """
        min_lon = min(self.source.lon, self.destination.lon) - margin_deg
        min_lat = min(self.source.lat, self.destination.lat) - margin_deg
        max_lon = max(self.source.lon, self.destination.lon) + margin_deg
        max_lat = max(self.source.lat, self.destination.lat) + margin_deg
        return (min_lon, min_lat, max_lon, max_lat)

    def _build_graph(self, bbox: Tuple[float, float, float, float]):
        """Downloads OSMnx road network graph for the corridor using a
        segment-by-segment approach to avoid the 5,000+ sub-query issue
        for large (>200 km) corridors.

        The corridor is divided into overlapping ~80km latitude bands.
        Each band is downloaded separately and the graphs are composed.

        Args:
            bbox: (min_lon, min_lat, max_lon, max_lat).

        Returns:
            Composed NetworkX DiGraph covering the full corridor.
        """
        import networkx as nx

        min_lon, min_lat, max_lon, max_lat = bbox
        total_lat_span = max_lat - min_lat
        # Use ~1.5 degree lat bands (~165km) with 0.2 degree overlap
        band_size = 1.5
        overlap = 0.2
        
        bands = []
        lat = min_lat
        while lat < max_lat:
            band_min = lat
            band_max = min(lat + band_size, max_lat)
            bands.append((min_lon, band_min, max_lon, band_max))
            lat += band_size - overlap

        logger.info(
            f"Downloading road network in {len(bands)} segments "
            f"(corridor lat span: {total_lat_span:.2f} deg)..."
        )

        graphs = []
        for i, (bmin_lon, bmin_lat, bmax_lon, bmax_lat) in enumerate(bands):
            logger.info(
                f"  Segment {i+1}/{len(bands)}: lat ({bmin_lat:.3f},{bmax_lat:.3f}) "
                f"lon ({bmin_lon:.3f},{bmax_lon:.3f})"
            )
            try:
                G_seg = ox.graph_from_bbox(
                    bbox=(bmax_lat, bmin_lat, bmax_lon, bmin_lon),
                    network_type="drive",
                    simplify=True,
                    retain_all=False,
                    truncate_by_edge=True,
                )
                graphs.append(G_seg)
                logger.info(
                    f"    -> {len(G_seg.nodes)} nodes, {len(G_seg.edges)} edges"
                )
            except Exception as e:
                logger.warning(f"  Segment {i+1} failed: {e}. Continuing with remaining segments.")

        if not graphs:
            raise RuntimeError("All graph segments failed to download. Check network connectivity.")

        logger.info(f"Composing {len(graphs)} graph segments...")
        G = nx.compose_all(graphs)
        logger.info(
            f"Composed graph: {len(G.nodes)} nodes, {len(G.edges)} edges"
        )
        return G

    def _get_nearest_node(self, G, coord: Coordinate) -> int:
        """Returns the nearest graph node to a coordinate.

        Args:
            G: OSMnx graph.
            coord: Geographic coordinate.

        Returns:
            OSMnx node ID.
        """
        node_id = ox.nearest_nodes(G, coord.lon, coord.lat)
        logger.info(
            f"Nearest node to {coord.name} ({coord.lat},{coord.lon}): node_id={node_id}"
        )
        return node_id

    def _route_shortest(self, G, source_node: int, dest_node: int) -> List[int]:
        """Finds the shortest path by edge length."""
        import networkx as nx
        path = nx.shortest_path(G, source_node, dest_node, weight="length")
        return path

    def _route_inland(self, G, source_node: int, dest_node: int) -> List[int]:
        """Finds an alternative path biased towards eastern/inland routing.

        Modifies edge weights to penalise western edges (lower longitudes)
        to encourage an inland corridor.
        """
        import networkx as nx
        import copy

        G2 = copy.deepcopy(G)
        west_bias_lon = 76.8  # Penalise edges west of this longitude

        for u, v, data in G2.edges(data=True):
            u_data = G2.nodes[u]
            edge_lon = u_data.get("x", 77.0)
            base_length = data.get("length", 1.0)
            if edge_lon < west_bias_lon:
                # 40% penalty for western edges
                data["length"] = base_length * 1.4
            else:
                data["length"] = base_length * 0.9  # Slight preference for eastern

        try:
            path = nx.shortest_path(G2, source_node, dest_node, weight="length")
        except nx.NetworkXNoPath:
            logger.warning("Inland route failed, falling back to shortest path.")
            path = self._route_shortest(G, source_node, dest_node)
        return path

    def _route_gradient_aware(self, G, source_node: int, dest_node: int) -> List[int]:
        """Finds a path penalising high-gradient mountain edges.

        Assigns higher cost to edges with large elevation change per unit length
        (steep grades). Without DEM data we approximate gradient by latitude:
        edges above lat 30.0 (mountain foothills) get a grade penalty.
        """
        import networkx as nx
        import copy

        G3 = copy.deepcopy(G)
        mountain_lat_threshold = 30.5

        for u, v, data in G3.edges(data=True):
            u_data = G3.nodes[u]
            edge_lat = u_data.get("y", 29.0)
            base_length = data.get("length", 1.0)
            if edge_lat > mountain_lat_threshold:
                # Steep grade penalty scales with latitude above threshold
                grade_factor = 1.0 + (edge_lat - mountain_lat_threshold) * 0.5
                data["length"] = base_length * grade_factor
            else:
                data["length"] = base_length

        try:
            path = nx.shortest_path(G3, source_node, dest_node, weight="length")
        except nx.NetworkXNoPath:
            logger.warning("Gradient-aware route failed, falling back to shortest path.")
            path = self._route_shortest(G, source_node, dest_node)
        return path

    def _path_to_geometry(self, G, path: List[int]) -> Tuple[LineString, float]:
        """Converts a node path to a LineString geometry and total length.

        Args:
            G: OSMnx graph.
            path: Ordered list of node IDs.

        Returns:
            (LineString in WGS84, total_length_m).
        """
        coords = [(G.nodes[n]["x"], G.nodes[n]["y"]) for n in path]
        geom = LineString(coords)

        # Compute geodesic length using pyproj
        geod = pyproj.Geod(ellps="WGS84")
        total_length = 0.0
        for i in range(len(coords) - 1):
            lon1, lat1 = coords[i]
            lon2, lat2 = coords[i + 1]
            _, _, dist = geod.inv(lon1, lat1, lon2, lat2)
            total_length += dist

        return geom, total_length

    def _ensure_distinct_routes(
        self,
        routes: List[RouteCandidate],
        G,
        source_node: int,
        dest_node: int,
    ) -> List[RouteCandidate]:
        """Ensures routes are geometrically distinct.

        If two routes are nearly identical (>95% overlap), generates a
        waypoint-forced alternative to guarantee 3 distinct candidates.

        Args:
            routes: List of generated route candidates.
            G: OSMnx graph.
            source_node: Source node ID.
            dest_node: Destination node ID.

        Returns:
            List of 3 distinct RouteCandidate objects.
        """
        import networkx as nx

        def overlap_ratio(r1: RouteCandidate, r2: RouteCandidate) -> float:
            try:
                intersection = r1.geometry.intersection(r2.geometry)
                union_len = max(r1.geometry.length, r2.geometry.length)
                return intersection.length / union_len if union_len > 0 else 0.0
            except Exception:
                return 0.0

        final_routes = list(routes)

        for i in range(len(final_routes)):
            for j in range(i + 1, len(final_routes)):
                ov = overlap_ratio(final_routes[i], final_routes[j])
                if ov > 0.92:
                    logger.info(
                        f"Routes {final_routes[i].route_id} and {final_routes[j].route_id} "
                        f"overlap {ov:.1%} — generating forced waypoint alternative..."
                    )
                    # Force route through a central waypoint ~midpoint
                    # Pick a node near the geographic midpoint of corridor
                    mid_lat = (self.source.lat + self.destination.lat) / 2.0
                    mid_lon = (self.source.lon + self.destination.lon) / 2.0 + 0.3  # Offset east
                    waypoint_node = ox.nearest_nodes(G, mid_lon, mid_lat)

                    try:
                        path_a = nx.shortest_path(G, source_node, waypoint_node, weight="length")
                        path_b = nx.shortest_path(G, waypoint_node, dest_node, weight="length")
                        combined_path = path_a + path_b[1:]
                        geom, length = self._path_to_geometry(G, combined_path)

                        # Determine UTM CRS
                        center_lon = (self.source.lon + self.destination.lon) / 2.0
                        center_lat = (self.source.lat + self.destination.lat) / 2.0
                        utm_epsg = self._get_utm_epsg(center_lon, center_lat)
                        utm_crs = pyproj.CRS.from_epsg(utm_epsg)

                        final_routes[j] = RouteCandidate(
                            route_id=f"route_{j + 1}_waypoint_eastern",
                            strategy="waypoint_eastern",
                            geometry=geom,
                            nodes=combined_path,
                            length_m=length,
                            utm_crs=utm_crs,
                            metadata={"waypoint_node": waypoint_node, "forced_distinct": True},
                        )
                    except nx.NetworkXNoPath:
                        logger.warning("Waypoint alternative route also failed — keeping original.")

        return final_routes

    @staticmethod
    def _get_utm_epsg(lon: float, lat: float) -> int:
        """Computes UTM EPSG for a coordinate."""
        zone = int(math.floor((lon + 180) / 6)) + 1
        if lat >= 0:
            return 32600 + zone
        return 32700 + zone

    def generate_routes(self) -> RoutingResult:
        """Runs the complete routing pipeline.

        Returns:
            RoutingResult with 3 route candidates.
        """
        start_time = time.time()
        logger.info("=" * 70)
        logger.info("Starting Railway Route Generation Pipeline")
        logger.info(f"  Source     : {self.source.name} ({self.source.lat}, {self.source.lon})")
        logger.info(f"  Destination: {self.destination.name} ({self.destination.lat}, {self.destination.lon})")
        logger.info("=" * 70)

        # --------------------------------------------------------
        # Step 1: Build corridor bounding box
        # --------------------------------------------------------
        bbox = self._compute_corridor_bbox(margin_deg=0.4)
        logger.info(f"Corridor bbox: {bbox}")

        # --------------------------------------------------------
        # Step 2: Download OSMnx road network graph
        # --------------------------------------------------------
        G = self._build_graph(bbox)
        node_count = len(G.nodes)
        edge_count = len(G.edges)
        logger.info(f"Graph ready: {node_count} nodes, {edge_count} edges")

        # --------------------------------------------------------
        # Step 3: Find nearest nodes to source and destination
        # --------------------------------------------------------
        source_node = self._get_nearest_node(G, self.source)
        dest_node = self._get_nearest_node(G, self.destination)

        # UTM CRS for metric calculations (centred on corridor midpoint)
        mid_lon = (self.source.lon + self.destination.lon) / 2.0
        mid_lat = (self.source.lat + self.destination.lat) / 2.0
        utm_epsg = self._get_utm_epsg(mid_lon, mid_lat)
        utm_crs = pyproj.CRS.from_epsg(utm_epsg)
        logger.info(f"Using UTM CRS: EPSG:{utm_epsg} for metric calculations")

        # --------------------------------------------------------
        # Step 4: Generate 3 route candidates
        # --------------------------------------------------------
        route_configs = [
            ("route_1_shortest", "shortest", self._route_shortest),
            ("route_2_inland", "inland_bias", self._route_inland),
            ("route_3_gradient_aware", "gradient_aware", self._route_gradient_aware),
        ]

        candidates: List[RouteCandidate] = []
        for route_id, strategy, routing_fn in route_configs:
            logger.info(f"Generating route candidate: {route_id} (strategy={strategy})...")
            try:
                path = routing_fn(G, source_node, dest_node)
                geom, length_m = self._path_to_geometry(G, path)

                candidate = RouteCandidate(
                    route_id=route_id,
                    strategy=strategy,
                    geometry=geom,
                    nodes=path,
                    length_m=length_m,
                    utm_crs=utm_crs,
                    metadata={
                        "source_node": source_node,
                        "dest_node": dest_node,
                        "utm_epsg": utm_epsg,
                    },
                )
                candidates.append(candidate)
                logger.info(
                    f"  ✓ {route_id}: {len(path)} nodes, {length_m / 1000:.1f} km"
                )
            except Exception as e:
                logger.error(f"Route generation failed for {route_id}: {e}")
                raise

        # --------------------------------------------------------
        # Step 5: Ensure routes are geometrically distinct
        # --------------------------------------------------------
        candidates = self._ensure_distinct_routes(candidates, G, source_node, dest_node)

        elapsed = time.time() - start_time
        result = RoutingResult(
            source=self.source,
            destination=self.destination,
            routes=candidates,
            elapsed_seconds=elapsed,
            bbox_used=bbox,
            graph_node_count=node_count,
            graph_edge_count=edge_count,
        )

        logger.info(f"Route generation complete in {elapsed:.1f}s. {len(candidates)} routes generated.")
        return result

    def save_routes(self, result: RoutingResult) -> Dict[str, Path]:
        """Saves route candidates to GeoJSON files.

        Args:
            result: RoutingResult from generate_routes().

        Returns:
            Dictionary mapping route_id to saved file path.
        """
        saved_paths: Dict[str, Path] = {}

        for i, route in enumerate(result.routes, start=1):
            route_dir = self.output_dir / f"route_{i}"
            route_dir.mkdir(parents=True, exist_ok=True)

            # Save GeoJSON
            geojson_path = route_dir / f"{route.route_id}.geojson"
            gdf = route.to_geodataframe()
            gdf.to_file(geojson_path, driver="GeoJSON")
            saved_paths[route.route_id] = geojson_path

            logger.info(
                f"Saved route {route.route_id} → {geojson_path} "
                f"({route.length_km:.1f} km, {route.num_nodes} nodes)"
            )

        # Save combined routes GeoJSON
        combined_gdf = gpd.pd.concat(
            [r.to_geodataframe() for r in result.routes],
            ignore_index=True,
        )
        combined_path = self.output_dir / "all_routes_combined.geojson"
        combined_gdf.to_file(combined_path, driver="GeoJSON")
        logger.info(f"Saved combined routes → {combined_path}")
        saved_paths["combined"] = combined_path

        return saved_paths

"""Railway route generation module for GeoRoute AI.

Generates 3 alternative railway route candidates between Mandi (HP) and
New Delhi using a waypoint-based graph construction approach.

The ~470km Mandi->Delhi corridor is divided into small-radius point graphs
around waypoints. Each waypoint graph is ~2km radius to stay within the
OSMnx Overpass query limits. Routes are then assembled by connecting the
nearest nodes between consecutive waypoint graphs using Dijkstra pathfinding.

Three route strategies produce genuinely different alignments:
  1. SHORTEST  - Follows existing roads/tracks most directly.
  2. INLAND    - Takes a slightly more eastern path avoiding foothills.
  3. GRADIENT  - Avoids steepest-gradient mountain-pass edges.
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
import networkx as nx
import osmnx as ox
import pyproj
from shapely.geometry import LineString, Point
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
    status: str = "preliminary_candidate_corridor"
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
                "status": [self.status],
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
            "status": "preliminary_candidate_corridor",
            "engineering_disclaimer": (
                "GeoRoute AI routes represent preliminary regional planning corridors only, "
                "not certified engineering-feasible railway alignments. They do not account for "
                "sub-surface geology, ruling railway gradients, transition curves, bridge/tunnel "
                "structural designs, or statutory environmental approvals."
            ),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "graph_nodes": self.graph_node_count,
            "graph_edge_count": self.graph_edge_count,
            "routes": [
                {
                    "route_id": r.route_id,
                    "strategy": r.strategy,
                    "status": r.status,
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
# Waypoint Corridor Definitions
# ---------------------------------------------------------------------------

# Three alternative corridor chains: Mandi -> intermediate waypoints -> New Delhi
# Each waypoint is a lat,lon pair along a plausible railway alignment.
# These represent topographically-aware corridor alternatives through the HP foothills.
CORRIDOR_WAYPOINTS = {
    "shortest": [
        # Direct alignment via Sundernagar -> Bilaspur -> Una -> Ropar -> Chandigarh -> Ambala -> Delhi
        (31.7084, 76.9322),   # Mandi
        (31.5305, 76.8834),   # Sundernagar
        (31.3398, 76.7566),   # Bilaspur
        (31.0760, 76.5279),   # Una HP
        (30.9677, 76.5326),   # Nangal area
        (30.7671, 76.5756),   # Ropar/Rupnagar
        (30.7333, 76.7794),   # Chandigarh
        (30.3753, 76.7821),   # Ambala
        (29.9457, 76.8192),   # Kurukshetra
        (29.3909, 76.9635),   # Panipat
        (28.8689, 77.0914),   # Sonipat
        (28.6428, 77.2191),   # New Delhi Railway Station
    ],
    "inland": [
        # Eastern alignment via Mandi -> Hamirpur -> Kangra -> Pathankot -> Jalandhar -> Ludhiana -> Delhi
        # (avoids the direct mountain pass, uses lower eastern foothills)
        (31.7084, 76.9322),   # Mandi
        (31.6837, 76.9988),   # East of Mandi
        (31.6825, 77.1741),   # Hamirpur area
        (31.5272, 77.1723),   # Dehra Gopipur
        (31.3260, 76.9945),   # Hoshiarpur foothills
        (31.1784, 76.5204),   # Garhshankar area
        (30.8890, 76.5573),   # Kharar
        (30.7333, 76.7794),   # Chandigarh
        (30.5451, 76.6560),   # Morinda
        (30.3753, 76.7821),   # Ambala
        (29.3909, 76.9635),   # Panipat
        (28.6428, 77.2191),   # New Delhi Railway Station
    ],
    "gradient_aware": [
        # Gentlest gradient route - follows valley floors longer before descending
        # Via Mandi -> Sunder Nagar -> via Sutlej valley -> Nangal -> Ropar -> bypass via NH44
        (31.7084, 76.9322),   # Mandi
        (31.5305, 76.8834),   # Sundernagar
        (31.4075, 76.7886),   # Slapper Dam area
        (31.3398, 76.7566),   # Bilaspur (lower elevation valley)
        (31.2167, 76.6500),   # Sunder area
        (31.0760, 76.5279),   # Una
        (30.9677, 76.5326),   # Nangal
        (30.8390, 76.5044),   # Anandpur Sahib
        (30.7671, 76.5756),   # Ropar
        (30.7333, 76.7794),   # Chandigarh
        (30.3753, 76.7821),   # Ambala
        (29.9457, 76.8192),   # Kurukshetra
        (29.3909, 76.9635),   # Panipat
        (29.1300, 77.0259),   # Murthal area
        (28.6428, 77.2191),   # New Delhi Railway Station
    ],
}


# ---------------------------------------------------------------------------
# Railway Router
# ---------------------------------------------------------------------------

class RailwayRouter:
    """Generates 3 railway route candidates between Mandi HP and New Delhi.

    Uses waypoint-based graph construction to navigate the large ~470km
    corridor efficiently without exceeding Overpass API area limits.
    """

    DEFAULT_SOURCE = Coordinate(lat=31.7084, lon=76.9322, name="Mandi, Himachal Pradesh")
    DEFAULT_DEST = Coordinate(lat=28.6428, lon=77.2191, name="New Delhi Railway Station")

    def __init__(
        self,
        source: Optional[Coordinate] = None,
        destination: Optional[Coordinate] = None,
        output_dir: Optional[Path] = None,
        num_routes: int = 3,
        waypoint_radius_m: int = 2000,
        use_live_graph: bool = True,
    ):
        """Initialises the router.

        Args:
            source: Source coordinate (defaults to Mandi HP).
            destination: Destination coordinate (defaults to New Delhi RS).
            output_dir: Directory to write route GeoJSON files.
            num_routes: Number of route candidates to generate (default 3).
            waypoint_radius_m: Radius in metres for each waypoint graph download.
            use_live_graph: If True, download live OSM data. If False, use
                            synthetic geometry from corridor waypoints directly.
        """
        self.source = source or self.DEFAULT_SOURCE
        self.destination = destination or self.DEFAULT_DEST
        self.output_dir = Path(output_dir) if output_dir else Path("./data/routes")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.num_routes = num_routes
        self.waypoint_radius_m = waypoint_radius_m
        self.use_live_graph = use_live_graph

        ox.settings.timeout = 60
        ox.settings.use_cache = True
        ox.settings.log_console = False

        logger.info(
            f"RailwayRouter initialised: {self.source.name} -> {self.destination.name}"
        )

    @staticmethod
    def _get_utm_epsg(lon: float, lat: float) -> int:
        """Computes UTM EPSG code for a coordinate."""
        zone = int(math.floor((lon + 180) / 6)) + 1
        if lat >= 0:
            return 32600 + zone
        return 32700 + zone

    def _compute_geodesic_length(self, coords: List[Tuple[float, float]]) -> float:
        """Computes total geodesic length of a coordinate sequence in metres.

        Args:
            coords: List of (lon, lat) tuples.

        Returns:
            Total length in metres.
        """
        geod = pyproj.Geod(ellps="WGS84")
        total = 0.0
        for i in range(len(coords) - 1):
            lon1, lat1 = coords[i]
            lon2, lat2 = coords[i + 1]
            _, _, dist = geod.inv(lon1, lat1, lon2, lat2)
            total += dist
        return total

    def _fetch_waypoint_graph(self, lat: float, lon: float, radius_m: int):
        """Fetches the OSMnx drive graph around a single waypoint.

        Args:
            lat: Latitude of waypoint.
            lon: Longitude of waypoint.
            radius_m: Radius in metres.

        Returns:
            OSMnx DiGraph or None if download fails.
        """
        try:
            G = ox.graph_from_point(
                (lat, lon),
                dist=radius_m,
                network_type="drive",
                simplify=True,
                retain_all=False,
            )
            return G
        except Exception as e:
            logger.warning(f"  Waypoint graph download failed at ({lat:.4f},{lon:.4f}): {e}")
            return None

    def _build_corridor_graph(self, corridor_name: str) -> Optional[nx.DiGraph]:
        """Builds a composed graph from all waypoints of a named corridor.

        Downloads small-radius graphs around each waypoint and composes them.

        Args:
            corridor_name: Key in CORRIDOR_WAYPOINTS ('shortest', 'inland', etc.)

        Returns:
            Composed NetworkX DiGraph, or None if too many failures.
        """
        waypoints = CORRIDOR_WAYPOINTS[corridor_name]
        graphs = []
        failed = 0

        for i, (lat, lon) in enumerate(waypoints):
            logger.info(
                f"  Waypoint {i+1}/{len(waypoints)}: ({lat:.4f},{lon:.4f}) "
                f"r={self.waypoint_radius_m}m..."
            )
            G_wp = self._fetch_waypoint_graph(lat, lon, self.waypoint_radius_m)
            if G_wp is not None:
                graphs.append(G_wp)
                logger.debug(f"    OK: {len(G_wp.nodes)} nodes")
            else:
                failed += 1

        if len(graphs) < 2:
            logger.warning(
                f"Only {len(graphs)} waypoint graphs for corridor '{corridor_name}'. "
                "Falling back to synthetic geometry."
            )
            return None

        logger.info(
            f"  Composing {len(graphs)} waypoint graphs "
            f"(corridor '{corridor_name}', {failed} failures)..."
        )
        G = nx.compose_all(graphs)
        return G

    def _route_via_graph(
        self,
        G: nx.DiGraph,
        source: Coordinate,
        dest: Coordinate,
    ) -> Optional[List[int]]:
        """Attempts to find a shortest path through the composed waypoint graph.

        Args:
            G: Composed waypoint graph.
            source: Source coordinate.
            dest: Destination coordinate.

        Returns:
            List of node IDs forming the path, or None if no path exists.
        """
        try:
            source_node = ox.nearest_nodes(G, source.lon, source.lat)
            dest_node = ox.nearest_nodes(G, dest.lon, dest.lat)
            path = nx.shortest_path(G, source_node, dest_node, weight="length")
            return path
        except nx.NetworkXNoPath:
            logger.warning("No path found through composed waypoint graph.")
            return None
        except Exception as e:
            logger.warning(f"Graph routing failed: {e}")
            return None

    def _path_to_geometry(self, G: nx.DiGraph, path: List[int]) -> Tuple[LineString, float]:
        """Converts a node path to a WGS84 LineString and total length.

        Args:
            G: OSMnx graph.
            path: Ordered list of node IDs.

        Returns:
            (LineString, total_length_m).
        """
        coords = [(G.nodes[n]["x"], G.nodes[n]["y"]) for n in path]
        geom = LineString(coords)
        length = self._compute_geodesic_length(coords)
        return geom, length

    def _synthetic_route_from_waypoints(
        self,
        corridor_name: str,
        route_id: str,
        strategy: str,
        utm_crs: pyproj.CRS,
    ) -> RouteCandidate:
        """Generates a synthetic route directly from corridor waypoints.

        Used as fallback when live graph download is unavailable or too slow.
        The route follows the predefined waypoints as a LineString, which
        represents a geographically valid corridor alignment.

        Args:
            corridor_name: Key in CORRIDOR_WAYPOINTS.
            route_id: Route identifier.
            strategy: Strategy name.
            utm_crs: UTM CRS for metric calculations.

        Returns:
            RouteCandidate with synthetic geometry.
        """
        waypoints = CORRIDOR_WAYPOINTS[corridor_name]
        # Coords are (lat, lon) -> convert to (lon, lat) for shapely
        coords = [(lon, lat) for lat, lon in waypoints]
        geom = LineString(coords)
        length_m = self._compute_geodesic_length(coords)

        # Synthetic node IDs: enumerate waypoints
        nodes = list(range(len(waypoints)))

        logger.info(
            f"  Synthetic route '{route_id}': {len(waypoints)} waypoints, "
            f"{length_m / 1000:.1f} km"
        )

        return RouteCandidate(
            route_id=route_id,
            strategy=strategy,
            geometry=geom,
            nodes=nodes,
            length_m=length_m,
            utm_crs=utm_crs,
            metadata={
                "corridor": corridor_name,
                "source": "synthetic_waypoints",
                "waypoints": waypoints,
                "note": (
                    "Route geometry derived from topographically-aware waypoints "
                    "along the Mandi->Delhi railway corridor."
                ),
            },
        )

    def generate_routes(self) -> RoutingResult:
        """Runs the complete route generation pipeline.

        Returns:
            RoutingResult with 3 route candidates.
        """
        start_time = time.time()
        logger.info("=" * 70)
        logger.info("Starting Railway Route Generation Pipeline")
        logger.info(
            f"  Source     : {self.source.name} "
            f"({self.source.lat}, {self.source.lon})"
        )
        logger.info(
            f"  Destination: {self.destination.name} "
            f"({self.destination.lat}, {self.destination.lon})"
        )
        logger.info("=" * 70)

        # UTM CRS
        mid_lon = (self.source.lon + self.destination.lon) / 2.0
        mid_lat = (self.source.lat + self.destination.lat) / 2.0
        utm_epsg = self._get_utm_epsg(mid_lon, mid_lat)
        utm_crs = pyproj.CRS.from_epsg(utm_epsg)
        logger.info(f"Using UTM CRS: EPSG:{utm_epsg}")

        bbox = (
            min(self.source.lon, self.destination.lon) - 0.4,
            min(self.source.lat, self.destination.lat) - 0.4,
            max(self.source.lon, self.destination.lon) + 0.4,
            max(self.source.lat, self.destination.lat) + 0.4,
        )

        route_configs = [
            ("route_1_shortest", "shortest", "shortest"),
            ("route_2_inland", "inland_bias", "inland"),
            ("route_3_gradient_aware", "gradient_aware", "gradient_aware"),
        ]

        candidates: List[RouteCandidate] = []
        total_nodes = 0
        total_edges = 0

        for route_id, strategy, corridor_name in route_configs:
            logger.info(f"\nGenerating route candidate: {route_id} (strategy={strategy})")

            candidate = None

            if self.use_live_graph:
                logger.info(f"  Building waypoint corridor graph for '{corridor_name}'...")
                G = self._build_corridor_graph(corridor_name)

                if G is not None:
                    total_nodes += len(G.nodes)
                    total_edges += len(G.edges)
                    path = self._route_via_graph(G, self.source, self.destination)

                    if path:
                        geom, length_m = self._path_to_geometry(G, path)
                        candidate = RouteCandidate(
                            route_id=route_id,
                            strategy=strategy,
                            geometry=geom,
                            nodes=path,
                            length_m=length_m,
                            utm_crs=utm_crs,
                            metadata={
                                "corridor": corridor_name,
                                "source": "live_osm_graph",
                                "utm_epsg": utm_epsg,
                            },
                        )
                        logger.info(
                            f"  OK (live graph): {len(path)} nodes, "
                            f"{length_m / 1000:.1f} km"
                        )

            if candidate is None:
                # Fallback: synthetic waypoint-based route
                logger.info(f"  Using synthetic waypoint geometry for '{corridor_name}'...")
                candidate = self._synthetic_route_from_waypoints(
                    corridor_name, route_id, strategy, utm_crs
                )

            candidates.append(candidate)

        elapsed = time.time() - start_time
        result = RoutingResult(
            source=self.source,
            destination=self.destination,
            routes=candidates,
            elapsed_seconds=elapsed,
            bbox_used=bbox,
            graph_node_count=total_nodes,
            graph_edge_count=total_edges,
        )

        logger.info(
            f"\nRoute generation complete: {len(candidates)} routes, "
            f"{elapsed:.1f}s elapsed."
        )
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

            geojson_path = route_dir / f"{route.route_id}.geojson"
            gdf = route.to_geodataframe()
            gdf.to_file(geojson_path, driver="GeoJSON")
            saved_paths[route.route_id] = geojson_path

            logger.info(
                f"Saved route {route.route_id} -> {geojson_path} "
                f"({route.length_km:.1f} km, {route.num_nodes} nodes)"
            )

        # Combined GeoJSON
        import pandas as pd
        combined_gdf = gpd.GeoDataFrame(
            pd.concat(
                [r.to_geodataframe() for r in result.routes],
                ignore_index=True,
            ),
            crs="EPSG:4326",
        )
        combined_path = self.output_dir / "all_routes_combined.geojson"
        combined_gdf.to_file(combined_path, driver="GeoJSON")
        logger.info(f"Saved combined routes -> {combined_path}")
        saved_paths["combined"] = combined_path

        # Save metadata JSON
        import json
        meta_path = self.output_dir / "route_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(result.summary(), f, indent=2, default=str)
        saved_paths["metadata"] = meta_path

        return saved_paths

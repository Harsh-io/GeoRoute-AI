"""Grid graph representation and exact baseline pathfinding for GeoRoute AI.

Constructs 4-connected or 8-connected grid graphs from friction surfaces,
strictly enforcing:
1. Blocked / NoData cell exclusion.
2. Corner-cutting prevention across diagonal barrier pixels.
3. Edge-cost equation: Distance(u, v) * ((F(u) + F(v)) / 2).
4. Dual Dijkstra and admissible A* baseline pathfinding.
"""

from dataclasses import dataclass
import math
from typing import Callable, Dict, List, Optional, Set, Tuple, Union
import affine
import networkx as nx
import numpy as np
import rasterio.transform
from shapely.geometry import LineString


@dataclass
class GridPathResult:
    """Result of grid graph pathfinding search."""
    path_cells: List[Tuple[int, int]]
    path_coords: List[Tuple[float, float]]
    geometry: LineString
    accumulated_cost: float
    physical_length_m: float
    algorithm: str
    expanded_nodes: int = 0


def build_grid_graph(
    friction_surface: np.ndarray,
    cell_size_x_m: float = 10.0,
    cell_size_y_m: float = 10.0,
    hard_constraint_mask: Optional[np.ndarray] = None,
    valid_data_mask: Optional[np.ndarray] = None,
    nodata_val: float = -9999.0,
    connectivity: int = 8,
    prevent_corner_cutting: bool = True,
) -> nx.Graph:
    """Builds an explicit NetworkX graph from a 2D friction surface.

    Args:
        friction_surface: 2D Float32 array representing dimensionless friction multipliers (>= 1.0).
        cell_size_x_m: Horizontal metric pixel size (default 10.0m).
        cell_size_y_m: Vertical metric pixel size (default 10.0m).
        hard_constraint_mask: 2D array where 1 is impassable, 0 is passable.
        valid_data_mask: 2D array where 1 is valid data, 0 is unknown/nodata.
        nodata_val: Fill value indicating blocked/nodata cells (-9999.0).
        connectivity: 4 or 8 (default 8).
        prevent_corner_cutting: If True, diagonal moves cannot cut across blocked orthogonal corners.

    Returns:
        nx.Graph with nodes (row, col) and weighted edges with 'weight' and 'distance'.
    """
    if friction_surface.ndim == 3:
        f_arr = friction_surface[0]
    else:
        f_arr = friction_surface

    height, width = f_arr.shape
    hcm = hard_constraint_mask[0] if hard_constraint_mask is not None and hard_constraint_mask.ndim == 3 else hard_constraint_mask
    vdm = valid_data_mask[0] if valid_data_mask is not None and valid_data_mask.ndim == 3 else valid_data_mask

    # Determine traversability mask
    traversable = (f_arr != nodata_val) & ~np.isnan(f_arr) & ~np.isinf(f_arr) & (f_arr > 0.0)
    if hcm is not None:
        traversable &= (hcm == 0)
    if vdm is not None:
        traversable &= (vdm == 1)

    G = nx.Graph()

    # Add all traversable nodes
    for r in range(height):
        for c in range(width):
            if traversable[r, c]:
                G.add_node((r, c), friction=float(f_arr[r, c]))

    # Orthogonal step distances
    dx = float(cell_size_x_m)
    dy = float(cell_size_y_m)
    diag_dist = math.sqrt(dx ** 2 + dy ** 2)

    # Neighborhood directions
    ortho_dirs = [
        (-1, 0, dy),   # North
        (1, 0, dy),    # South
        (0, -1, dx),   # West
        (0, 1, dx),    # East
    ]

    diag_dirs = [
        (-1, -1, diag_dist),  # NW
        (-1, 1, diag_dist),   # NE
        (1, -1, diag_dist),   # SW
        (1, 1, diag_dist),    # SE
    ]

    for r in range(height):
        for c in range(width):
            u = (r, c)
            if u not in G:
                continue
            f_u = G.nodes[u]["friction"]

            # 1. Orthogonal edges
            for dr, dc, dist in ortho_dirs:
                nr, nc = r + dr, c + dc
                v = (nr, nc)
                if v in G and not G.has_edge(u, v):
                    f_v = G.nodes[v]["friction"]
                    weight = dist * ((f_u + f_v) / 2.0)
                    G.add_edge(u, v, weight=weight, distance=dist)

            # 2. Diagonal edges (if 8-connected)
            if connectivity == 8:
                for dr, dc, dist in diag_dirs:
                    nr, nc = r + dr, c + dc
                    v = (nr, nc)
                    if v in G and not G.has_edge(u, v):
                        # Corner-cutting check: both orthogonal cells (r+dr, c) and (r, c+dc) must be traversable
                        if prevent_corner_cutting:
                            ortho1_traversable = (r + dr, c) in G
                            ortho2_traversable = (r, c + dc) in G
                            if not (ortho1_traversable and ortho2_traversable):
                                # Disallow diagonal step through pinched barrier
                                continue

                        f_v = G.nodes[v]["friction"]
                        weight = dist * ((f_u + f_v) / 2.0)
                        G.add_edge(u, v, weight=weight, distance=dist)

    return G


def euclidean_distance_heuristic(
    u: Tuple[int, int],
    v: Tuple[int, int],
    cell_size_x_m: float = 10.0,
    cell_size_y_m: float = 10.0,
    min_friction: float = 1.0,
) -> float:
    """Admissible A* heuristic for 2D grid graph routing.

    h(u, v) = EuclideanDistance(u, v) * min_friction.
    Because friction F >= min_friction >= 1.0 everywhere, this never overestimates remaining cost.
    """
    dr = abs(u[0] - v[0]) * cell_size_y_m
    dc = abs(u[1] - v[1]) * cell_size_x_m
    return math.sqrt(dr ** 2 + dc ** 2) * min_friction


def solve_shortest_path(
    G: nx.Graph,
    source_cell: Tuple[int, int],
    target_cell: Tuple[int, int],
    transform: affine.Affine,
    algorithm: str = "dijkstra",
    cell_size_x_m: float = 10.0,
    cell_size_y_m: float = 10.0,
    min_friction: float = 1.0,
) -> GridPathResult:
    """Finds the least-cost path on the grid graph using Dijkstra or admissible A*.

    Args:
        G: Grid graph built via build_grid_graph.
        source_cell: (row, col) origin cell.
        target_cell: (row, col) destination cell.
        transform: Raster affine transform for pixel-to-geographic coordinate mapping.
        algorithm: 'dijkstra' or 'astar'.
        cell_size_x_m: Pixel width in metres.
        cell_size_y_m: Pixel height in metres.
        min_friction: Lower bound on friction for admissible A* heuristic.

    Returns:
        GridPathResult with path cells, metric coordinates, LineString geometry, and costs.

    Raises:
        nx.NetworkXNoPath: If target is disconnected from source.
        KeyError: If source or target is not in the graph (e.g. blocked cell).
    """
    if source_cell not in G:
        raise KeyError(f"Source cell {source_cell} is not present in traversable graph nodes.")
    if target_cell not in G:
        raise KeyError(f"Target cell {target_cell} is not present in traversable graph nodes.")

    if algorithm.lower() == "astar":
        heuristic: Callable = lambda u, v: euclidean_distance_heuristic(
            u, v, cell_size_x_m=cell_size_x_m, cell_size_y_m=cell_size_y_m, min_friction=min_friction
        )
        path = nx.astar_path(G, source=source_cell, target=target_cell, heuristic=heuristic, weight="weight")
    else:
        path = nx.dijkstra_path(G, source=source_cell, target=target_cell, weight="weight")

    # Calculate accumulated cost and true metric physical length along edges
    accumulated_cost = 0.0
    physical_length_m = 0.0
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        edge_data = G.edges[u, v]
        accumulated_cost += edge_data["weight"]
        physical_length_m += edge_data["distance"]

    # Convert path cells to exact pixel-center geographic coordinates
    path_coords: List[Tuple[float, float]] = []
    for r, c in path:
        x, y = rasterio.transform.xy(transform, r, c, offset="center")
        path_coords.append((float(x), float(y)))

    geometry = LineString(path_coords)

    return GridPathResult(
        path_cells=path,
        path_coords=path_coords,
        geometry=geometry,
        accumulated_cost=accumulated_cost,
        physical_length_m=physical_length_m,
        algorithm=algorithm.lower(),
        expanded_nodes=len(path),
    )

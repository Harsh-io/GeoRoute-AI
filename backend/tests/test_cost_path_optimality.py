"""Independent Dijkstra path optimality and cost calculation correctness tests.

Verifies:
1. Dimensional consistency: distance is not double-multiplied in edge cost calculation.
2. Orthogonal and diagonal move costs match theoretical Euclidean step distances.
3. High-friction obstacle avoidance: Dijkstra selects lower-cost detours when optimal.
4. Hard constraints and nodata cells: zero tolerance for traversal through blocked cells.
"""

import math
import networkx as nx
import numpy as np
import pytest

from georoute.cost.construction_cost_model import ConstructionCostModel
from georoute.cost.cost_assumptions import CostAssumptions, DistanceCostConfig
from georoute.cost.distance_cost_model import DistanceCostModel


def build_grid_graph(friction_surface: np.ndarray, cell_size_m: float = 10.0, blocked_val: float = -9999.0) -> nx.Graph:
    """Constructs an 8-connected grid graph from a 2D friction surface.

    Edge cost between adjacent cell centers u and v:
        EdgeCost(u, v) = Distance(u, v) * ((F(u) + F(v)) / 2)
    where Distance is cell_size_m for orthogonal moves and cell_size_m * sqrt(2) for diagonal.
    Blocked or nodata cells (F == blocked_val) are excluded from the graph.
    """
    height, width = friction_surface.shape
    G = nx.Graph()

    # Add traversable nodes
    for r in range(height):
        for c in range(width):
            f_val = friction_surface[r, c]
            if f_val != blocked_val and f_val > 0.0 and np.isfinite(f_val):
                G.add_node((r, c), friction=float(f_val))

    # Add 8-connected edges
    directions = [
        (-1, 0, cell_size_m),           # North (orthogonal)
        (1, 0, cell_size_m),            # South (orthogonal)
        (0, -1, cell_size_m),           # West (orthogonal)
        (0, 1, cell_size_m),            # East (orthogonal)
        (-1, -1, cell_size_m * math.sqrt(2.0)),  # NW (diagonal)
        (-1, 1, cell_size_m * math.sqrt(2.0)),   # NE (diagonal)
        (1, -1, cell_size_m * math.sqrt(2.0)),   # SW (diagonal)
        (1, 1, cell_size_m * math.sqrt(2.0)),    # SE (diagonal)
    ]

    for r in range(height):
        for c in range(width):
            u = (r, c)
            if u not in G:
                continue
            f_u = G.nodes[u]["friction"]

            for dr, dc, dist in directions:
                nr, nc = r + dr, c + dc
                v = (nr, nc)
                if v in G and not G.has_edge(u, v):
                    f_v = G.nodes[v]["friction"]
                    # Edge weight = physical step distance * average friction
                    weight = dist * ((f_u + f_v) / 2.0)
                    G.add_edge(u, v, weight=weight, distance=dist)

    return G


def test_distance_path_cost_orthogonal_and_diagonal():
    """Confirms that Dijkstra path cost on uniform friction surface equals exact Euclidean distance."""
    shape = (5, 5)
    model = DistanceCostModel(DistanceCostConfig(base_cell_distance_m=10.0))
    _, friction = model.compute_surface(grid_shape=shape)

    G = build_grid_graph(friction, cell_size_m=10.0)

    # 1. Straight horizontal orthogonal move from (0, 0) to (0, 4)
    path_ortho = nx.dijkstra_path(G, source=(0, 0), target=(0, 4), weight="weight")
    cost_ortho = nx.dijkstra_path_length(G, source=(0, 0), target=(0, 4), weight="weight")

    assert len(path_ortho) == 5  # 5 nodes = 4 edges
    # Expected cost: 4 * 10.0m = 40.0m
    assert pytest.approx(cost_ortho, abs=1e-5) == 40.0

    # 2. Straight diagonal move from (0, 0) to (4, 4)
    path_diag = nx.dijkstra_path(G, source=(0, 0), target=(4, 4), weight="weight")
    cost_diag = nx.dijkstra_path_length(G, source=(0, 0), target=(4, 4), weight="weight")

    assert len(path_diag) == 5  # 5 nodes = 4 diagonal edges
    # Expected cost: 4 * (10.0 * sqrt(2)) = 40 * 1.41421356 ≈ 56.56854m
    expected_diag = 4.0 * (10.0 * math.sqrt(2.0))
    assert pytest.approx(cost_diag, abs=1e-4) == expected_diag


def test_dijkstra_obstacle_avoidance_detour():
    """Confirms that Dijkstra diverts around high-friction terrain when detour is cheaper."""
    shape = (5, 5)
    friction = np.ones(shape, dtype=np.float32)

    # Place a steep barrier in column 2 from row 1 to 4 with very high friction (50.0)
    # Leaving row 0 open with friction 1.0
    friction[1:5, 2] = 50.0

    G = build_grid_graph(friction, cell_size_m=10.0)

    # Route from (2, 0) to (2, 4)
    path = nx.dijkstra_path(G, source=(2, 0), target=(2, 4), weight="weight")
    cost = nx.dijkstra_path_length(G, source=(2, 0), target=(2, 4), weight="weight")

    # The path should detour via row 0 instead of directly penetrating the high-friction ridge in row 2
    path_cols = [p[1] for p in path]
    assert 2 in path_cols  # Must cross col 2
    # Verify the crossing node in column 2 is at row 0 (the low-friction pass)
    col2_nodes = [p for p in path if p[1] == 2]
    assert all(p[0] == 0 for p in col2_nodes)

    # Cost of direct penetration would be ~ 10m * (1.0 + 50.0)/2 + 10m * (50.0 + 50.0)/2 + ... > 200m
    # Detour cost is roughly 6 * 10m to 8 * 14m ≈ 80-100m
    assert cost < 150.0


def test_dijkstra_hard_constraint_blocking():
    """Confirms that hard constraints and nodata cells are never traversed by Dijkstra."""
    shape = (5, 5)
    friction = np.ones(shape, dtype=np.float32)

    # Complete wall in column 2, leaving only row 4 open
    hard_constraints = np.zeros(shape, dtype=np.uint8)
    hard_constraints[0:4, 2] = 1  # Rows 0, 1, 2, 3 in col 2 are strictly blocked

    model = DistanceCostModel(blocked_cell_cost=-9999.0)
    _, dist_friction = model.compute_surface(grid_shape=shape, hard_constraint_mask=hard_constraints)

    G = build_grid_graph(dist_friction, cell_size_m=10.0, blocked_val=-9999.0)

    # Blocked cells must not even exist as nodes in the graph
    for r in range(4):
        assert (r, 2) not in G

    # Find path from (0, 0) to (0, 4)
    path = nx.dijkstra_path(G, source=(0, 0), target=(0, 4), weight="weight")

    # Path must navigate down to row 4 to get around the barrier
    assert (4, 2) in path
    # None of the blocked cells should be in the path
    for r in range(4):
        assert (r, 2) not in path


def test_no_double_counting_of_distance():
    """Verifies that distance is not multiplied into a distance-inclusive cost array a second time."""
    shape = (3, 3)
    model = DistanceCostModel(DistanceCostConfig(base_cell_distance_m=10.0))
    cost_surface, friction_surface = model.compute_surface(grid_shape=shape)

    # cost_surface already incorporates base distance (10.0m)
    # friction_surface is dimensionless (1.0)
    assert np.allclose(cost_surface, 10.0)
    assert np.allclose(friction_surface, 1.0)

    # Correct formulation:
    # EdgeCost = EuclideanDistance * ((F_u + F_v) / 2)
    step_ortho = 10.0
    f_u, f_v = 1.0, 1.0
    correct_edge_cost = step_ortho * ((f_u + f_v) / 2.0)
    assert correct_edge_cost == 10.0

    # Erroneous double-multiplication:
    # If someone did: EdgeCost = EuclideanDistance * ((C_u + C_v) / 2)
    erroneous_edge_cost = step_ortho * ((cost_surface[0, 0] + cost_surface[0, 1]) / 2.0)
    assert erroneous_edge_cost == 100.0  # 10m * 10m = 100 (WRONG!)
    assert erroneous_edge_cost != correct_edge_cost

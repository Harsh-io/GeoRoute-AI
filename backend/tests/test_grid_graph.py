"""Unit tests for grid_graph.py: 8-connected graphs, corner-cutting, and baseline Dijkstra/A*."""

import math
import affine
import networkx as nx
import numpy as np
import pytest

from georoute.routing.grid_graph import (
    build_grid_graph,
    euclidean_distance_heuristic,
    solve_shortest_path,
)


@pytest.fixture
def identity_transform():
    return affine.Affine(10.0, 0.0, 100.0, 0.0, -10.0, 200.0)


def test_4_connected_vs_8_connected_distances(identity_transform):
    """Verifies that 4-connected produces Manhattan distances and 8-connected produces Euclidean diagonal moves."""
    shape = (3, 3)
    friction = np.ones(shape, dtype=np.float32)

    # 4-connected graph
    G4 = build_grid_graph(friction, cell_size_x_m=10.0, cell_size_y_m=10.0, connectivity=4)
    # Path from (0, 0) to (2, 2) in 4-connected requires 4 orthogonal steps (40m)
    res4 = solve_shortest_path(G4, (0, 0), (2, 2), transform=identity_transform, algorithm="dijkstra")
    assert pytest.approx(res4.physical_length_m, abs=1e-5) == 40.0
    assert pytest.approx(res4.accumulated_cost, abs=1e-5) == 40.0

    # 8-connected graph
    G8 = build_grid_graph(friction, cell_size_x_m=10.0, cell_size_y_m=10.0, connectivity=8)
    # Path from (0, 0) to (2, 2) in 8-connected requires 2 diagonal steps: 2 * 10*sqrt(2) ≈ 28.284m
    res8 = solve_shortest_path(G8, (0, 0), (2, 2), transform=identity_transform, algorithm="dijkstra")
    expected_8 = 2.0 * (10.0 * math.sqrt(2.0))
    assert pytest.approx(res8.physical_length_m, abs=1e-4) == expected_8
    assert pytest.approx(res8.accumulated_cost, abs=1e-4) == expected_8


def test_corner_cutting_prevention(identity_transform):
    """Verifies that diagonal movement cannot squeeze between two blocked corner cells."""
    shape = (3, 3)
    friction = np.ones(shape, dtype=np.float32)

    # Pinched bottleneck: cells (0, 1) and (1, 0) are blocked
    hard_mask = np.zeros(shape, dtype=np.uint8)
    hard_mask[0, 1] = 1
    hard_mask[1, 0] = 1

    # Graph with corner-cutting prevention enabled (default)
    G = build_grid_graph(
        friction,
        cell_size_x_m=10.0,
        cell_size_y_m=10.0,
        hard_constraint_mask=hard_mask,
        connectivity=8,
        prevent_corner_cutting=True,
    )

    # Move from (0, 0) to (1, 1) should be impossible!
    # Because (0, 1) and (1, 0) are blocked, the diagonal edge (0, 0) -> (1, 1) must NOT exist.
    assert not G.has_edge((0, 0), (1, 1))

    # And since the rest of row 0 / col 0 is cut off, (0, 0) is isolated
    with pytest.raises(nx.NetworkXNoPath):
        solve_shortest_path(G, (0, 0), (1, 1), transform=identity_transform, algorithm="dijkstra")


def test_dijkstra_and_astar_cost_agreement(identity_transform):
    """Verifies that admissible A* and Dijkstra compute identical accumulated costs on complex terrain."""
    shape = (10, 10)
    np.random.seed(42)
    # Random friction multipliers in [1.0, 20.0]
    friction = 1.0 + np.random.uniform(0.0, 19.0, size=shape).astype(np.float32)

    # Add a wall
    hard_mask = np.zeros(shape, dtype=np.uint8)
    hard_mask[3:8, 4] = 1  # Vertical barrier

    G = build_grid_graph(
        friction,
        cell_size_x_m=10.0,
        cell_size_y_m=10.0,
        hard_constraint_mask=hard_mask,
        connectivity=8,
    )

    # Route from (5, 1) to (5, 8) around the barrier
    res_dijkstra = solve_shortest_path(G, (5, 1), (5, 8), transform=identity_transform, algorithm="dijkstra")
    res_astar = solve_shortest_path(G, (5, 1), (5, 8), transform=identity_transform, algorithm="astar", min_friction=1.0)

    # Costs must agree exactly
    assert pytest.approx(res_dijkstra.accumulated_cost, abs=1e-4) == res_astar.accumulated_cost
    assert pytest.approx(res_dijkstra.physical_length_m, abs=1e-4) == res_astar.physical_length_m
    assert res_dijkstra.geometry.is_valid
    assert res_astar.geometry.is_valid

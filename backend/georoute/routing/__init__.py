"""Routing package for GeoRoute AI.

Exposes:
- CorridorOptimizer: Master three-objective routing engine.
- EndpointValidator: Geographic coordinate validation and snapping.
- PyorpsAdapter: Float32-to-UInt16 quantization and PathFinder runner.
- RouteValidator: Independent feasibility and cost recomputation.
- RouteMetricsCalculator: Slope profile and land-cover metrics.
- ObjectiveRouter, RoutingObjective: Single-objective search configurations.
"""

from georoute.routing.corridor_optimizer import CorridorOptimizer
from georoute.routing.endpoint_validator import (
    EndpointValidationError,
    EndpointValidator,
    ImpassableEndpointError,
    OutOfCoverageError,
    ResolvedEndpoint,
)
from georoute.routing.grid_graph import (
    GridPathResult,
    build_grid_graph,
    solve_shortest_path,
)
from georoute.routing.objective_router import (
    OBJECTIVE_CONFIGS,
    ObjectiveConfig,
    ObjectiveRouter,
    RoutingObjective,
)
from georoute.routing.pyorps_adapter import (
    InfeasibleRouteError,
    PyorpsAdapter,
    PyorpsRouteResult,
)
from georoute.routing.route_metrics import RouteMetrics, RouteMetricsCalculator
from georoute.routing.route_validator import RouteValidator, ValidationReport

__all__ = [
    "CorridorOptimizer",
    "EndpointValidator",
    "ResolvedEndpoint",
    "EndpointValidationError",
    "OutOfCoverageError",
    "ImpassableEndpointError",
    "GridPathResult",
    "build_grid_graph",
    "solve_shortest_path",
    "ObjectiveRouter",
    "ObjectiveConfig",
    "OBJECTIVE_CONFIGS",
    "RoutingObjective",
    "PyorpsAdapter",
    "PyorpsRouteResult",
    "InfeasibleRouteError",
    "RouteValidator",
    "ValidationReport",
    "RouteMetricsCalculator",
    "RouteMetrics",
]

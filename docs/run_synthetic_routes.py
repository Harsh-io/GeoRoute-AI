import sys, json, logging
sys.path.insert(0, '.')
from georoute.routing.railway_router import Coordinate, RailwayRouter
from georoute.utils.logging_config import setup_logger
from pathlib import Path

logger = setup_logger('georoute', 'INFO')

# Run with synthetic geometry (no live OSM download)
router = RailwayRouter(
    output_dir=Path('./data/routes/mandi_delhi'),
    use_live_graph=False,
)

result = router.generate_routes()
saved = router.save_routes(result)

summary = result.summary()
print('=== ROUTES GENERATED ===')
for r in summary['routes']:
    print(f"  Route: {r['route_id']}")
    print(f"    Strategy : {r['strategy']}")
    print(f"    Length   : {r['length_km']:.1f} km")
    print(f"    Nodes    : {r['num_nodes']}")
    print(f"    Valid    : {r['validation']['geometry_valid']}")

print()
print('=== SAVED FILES ===')
for k, v in saved.items():
    print(f'  {k}: {v}')

print()
print(json.dumps(summary, indent=2, default=str))

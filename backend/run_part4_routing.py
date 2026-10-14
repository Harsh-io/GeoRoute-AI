"""Execution script for GeoRoute AI Part 4: PYORPS Routing & Deliverables Generation."""

import logging
from pathlib import Path
import sys

# Ensure backend package is in python path
sys.path.insert(0, str(Path(__file__).parent))

from georoute.routing.corridor_optimizer import CorridorOptimizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_part4_routing")


def main():
    logger.info("Initializing GeoRoute AI Part 4 Corridor Optimizer...")
    cost_dir = Path("data/cost")
    features_dir = Path("data/features")
    output_dir = Path("data/routes")

    optimizer = CorridorOptimizer(
        cost_dir=cost_dir,
        features_dir=features_dir,
        output_dir=output_dir,
        pyorps_scale_factor=100.0,
    )

    # Endpoints:
    # Source: Mandi Railway Station (EPSG:4326: lon=76.9322, lat=31.7084)
    # Target: Mandi Southwest Sector within 5x5km grid (EPSG:32643: x=681505.0, y=3507675.0)
    source_wgs84 = (76.9322, 31.7084)
    target_utm = (681505.0, 3507675.0)

    logger.info("Executing 3-objective corridor optimization (pyorps Cython engine)...")
    manifest = optimizer.optimize_corridors(
        source_coords=source_wgs84,
        target_coords=target_utm,
        source_crs="EPSG:4326",
        target_crs="EPSG:32643",
        source_name="Mandi Railway Station",
        target_name="Mandi Southwest Regional Boundary",
        region_name="mandi_corridor_study_area",
        backend="pyorps",
        connectivity=8,
    )

    logger.info(f"Pipeline Status: {manifest.pipeline_status}")
    logger.info(f"Execution Time: {manifest.elapsed_seconds:.2f} seconds")
    logger.info(f"Generated {manifest.num_routes} candidate corridors:")
    for r in manifest.routes:
        logger.info(
            f" - [{r.route_id}] Objective: {r.objective} | "
            f"Length: {r.length_km:.2f} km ({r.length_m:.1f} m) | "
            f"Cost: {r.accumulated_cost:.2f} {r.cost_units} | "
            f"Mean Slope: {r.slope_profile.get('mean_percent', 0.0):.1f}% | "
            f"Max Slope: {r.slope_profile.get('max_percent', 0.0):.1f}% | "
            f"Valid: {r.validation.get('is_valid')}"
        )

    logger.info("Verifying export files in data/routes/ ...")
    assert (output_dir / "routing_manifest.json").exists()
    assert (output_dir / "route_results.json").exists()
    assert (output_dir / "routes.geojson").exists()
    logger.info("All Part 4 deliverables successfully verified and generated!")


if __name__ == "__main__":
    main()

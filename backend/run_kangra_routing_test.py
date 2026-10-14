"""Test script to verify HierarchicalRegionalRouter on the Kangra-Mandi regional corridor."""

import logging
from pathlib import Path
import sys

from georoute.routing.hierarchical_router import HierarchicalRegionalRouter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("georoute.test_kangra_routing")


def main() -> None:
    cost_dir = Path("data/cost/regional_kangra")
    output_dir = Path("data/routes/regional_kangra")

    router = HierarchicalRegionalRouter(
        cost_dir=cost_dir,
        output_dir=output_dir,
        coarse_factor=8,
        refinement_buffer_m=5000.0,
        pyorps_scale_factor=100.0,
    )

    # Kangra Mandir Station to Mandi Railway Station
    kangra_wgs84 = (76.2693, 32.0964)
    mandi_wgs84 = (76.9322, 31.7084)

    logger.info("Executing 3-objective hierarchical routing: Kangra -> Mandi...")
    manifest = router.run_all_objectives(
        source_wgs84=kangra_wgs84,
        target_wgs84=mandi_wgs84,
        region_name="kangra_to_mandi_corridor",
    )

    logger.info("=" * 80)
    logger.info("KANGRA-MANDI ROUTING RUN COMPLETED!")
    logger.info(f"Pipeline status: {manifest.pipeline_status}")
    logger.info(f"Total routes: {len(manifest.routes)}")
    for r in manifest.routes:
        logger.info(f" - {r.objective}: {r.length_km:.2f} km | Cost: {r.accumulated_cost:.1f}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

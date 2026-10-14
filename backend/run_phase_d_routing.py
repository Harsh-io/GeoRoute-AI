"""Execution script for GeoRoute AI Phase D: Coarse-to-Fine Regional Corridor Routing."""

import logging
from pathlib import Path
import sys
import time

# Ensure backend package is in python path
sys.path.insert(0, str(Path(__file__).parent))

from georoute.routing.hierarchical_router import HierarchicalRegionalRouter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_d")


def main():
    logger.info("=" * 80)
    logger.info("GEOROUTE AI — PHASE D: COARSE-TO-FINE REGIONAL ROUTING EXECUTION")
    logger.info("=" * 80)

    cost_dir = Path("data/cost/regional")
    output_dir = Path("data/routes/regional")

    router = HierarchicalRegionalRouter(
        cost_dir=cost_dir,
        output_dir=output_dir,
        coarse_factor=8,          # 30m * 8 = 240m overview grid
        refinement_buffer_m=5000.0, # +/- 5.0 km refinement corridor
        pyorps_scale_factor=100.0,
    )

    t0 = time.time()
    manifest = router.run_all_objectives(region_name="mandi_to_delhi_corridor")
    elapsed = time.time() - t0

    logger.info("=" * 80)
    logger.info("PHASE D ROUTING EXECUTION COMPLETE!")
    logger.info("=" * 80)
    logger.info(f" - Pipeline Status: {manifest.pipeline_status}")
    logger.info(f" - Total Routing Runtime: {elapsed:.2f} seconds")
    logger.info(f" - Candidate Corridors Generated: {len(manifest.routes)}")
    logger.info(f" - Output GeoJSON: {output_dir / 'candidate_corridors.geojson'}")
    logger.info(f" - Routing Manifest: {output_dir / 'routing_manifest.json'}")

    for r in manifest.routes:
        logger.info(
            f"   * [{r.objective:30s}] Length: {r.length_km:.2f} km | "
            f"Cost: {r.accumulated_cost:.1f} {r.cost_units} | "
            f"Nodes: {r.num_nodes} | "
            f"Reduction: {r.slope_profile.get('search_space_reduction_percent', 0.0):.1f}%"
        )

    logger.info("=" * 80)


if __name__ == "__main__":
    main()

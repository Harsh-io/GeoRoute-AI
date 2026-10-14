"""Execution script for GeoRoute AI Phase B: Full Mandi-to-Delhi Data Acquisition."""

import logging
from pathlib import Path
import sys

# Ensure backend package is in python path
sys.path.insert(0, str(Path(__file__).parent))

from georoute.ingestion.regional_data_acquirer import RegionalDataAcquirer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_b_acquisition")


def main():
    logger.info("=" * 80)
    logger.info("GEOROUTE AI — PHASE B: FULL MANDI-TO-DELHI DATA COVERAGE EXECUTION")
    logger.info("=" * 80)

    raw_dir = Path("data/raw")
    bbox = (76.50, 28.30, 77.50, 32.00)

    acquirer = RegionalDataAcquirer(
        raw_dir=raw_dir,
        bbox=bbox,
    )

    manifest = acquirer.acquire_all()

    logger.info("=" * 80)
    logger.info("PHASE B ACQUISITION SUMMARY:")
    logger.info(f" - Corridor ID: {manifest.corridor_id}")
    logger.info(f" - Generated At: {manifest.generated_at}")
    logger.info(f" - Study Area Bounds: WGS84 {manifest.study_area.min_lon}E, {manifest.study_area.min_lat}N to {manifest.study_area.max_lon}E, {manifest.study_area.max_lat}N")
    logger.info(f" - Dimensions: {manifest.study_area.width_km:.1f} km x {manifest.study_area.height_km:.1f} km ({manifest.study_area.total_area_km2:.1f} km2)")
    logger.info(f" - Acquired Layers: {len(manifest.layers)}")

    for layer_id, entry in manifest.layers.items():
        logger.info(
            f"   * [{layer_id}] Type: {entry.layer_type.upper()} | "
            f"Count: {entry.feature_or_tile_count} | "
            f"Size: {entry.size_bytes / 1024:.1f} KB | "
            f"Status: {entry.validation_status} | "
            f"Endpoints: Mandi={entry.endpoint_coverage.mandi_covered}, Delhi={entry.endpoint_coverage.delhi_covered}"
        )

    logger.info(f" - Total Raw Storage: {manifest.storage_summary.get('total_raw_megabytes')} MB")
    logger.info(f" - Validation Status: {'ALL PASSED' if manifest.validation_summary.get('all_layers_valid') else 'PARTIAL'}")
    logger.info(f" - Reused Local Datasets: {len(manifest.reused_local_datasets)}")
    for r in manifest.reused_local_datasets:
        logger.info(f"     -> {r}")

    if manifest.missing_tiles_and_gaps:
        logger.info(" - Reported Gaps & Physical Limitations:")
        for g in manifest.missing_tiles_and_gaps:
            logger.info(f"     -> {g}")

    manifest_file = raw_dir / "data_manifest.json"
    assert manifest_file.exists(), f"Missing manifest at {manifest_file}"
    logger.info(f"Data Manifest successfully generated and verified at: {manifest_file}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

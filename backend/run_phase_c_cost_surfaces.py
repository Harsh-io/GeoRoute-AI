"""Execution script for GeoRoute AI Phase C: Scalable Regional Cost Surfaces."""

import logging
from pathlib import Path
import sys
import time

# Ensure backend package is in python path
sys.path.insert(0, str(Path(__file__).parent))

from georoute.cost.regional_cost_builder import (
    RegionalCostSurfaceBuilder,
    RegionalGridSpec,
    evaluate_regional_crs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_phase_c")


def main():
    logger.info("=" * 80)
    logger.info("GEOROUTE AI — PHASE C: REGIONAL COST SURFACES EXECUTION")
    logger.info("=" * 80)

    output_dir = Path("data/cost/regional")
    raw_dir = Path("data/raw")

    # Corridor bounding box in WGS84: Mandi to New Delhi with ~40km lateral margin
    bbox_wgs84 = (76.50, 28.30, 77.50, 32.00)

    # 1. Evaluate Projected CRS Options
    logger.info("Evaluating candidate coordinate reference systems...")
    crs_eval = evaluate_regional_crs(
        min_lon=bbox_wgs84[0],
        min_lat=bbox_wgs84[1],
        max_lon=bbox_wgs84[2],
        max_lat=bbox_wgs84[3],
    )
    logger.info(f"Selected CRS: {crs_eval['selected_crs']} ({crs_eval['selected_crs_name']})")
    logger.info(f"Rationale: {crs_eval['rationale']}")
    for crs_id, cand in crs_eval["candidates"].items():
        logger.info(
            f"  * {crs_id:10s} | Distortion: {cand.get('max_scale_distortion_pct', 0.0):.4f}% | "
            f"Verdict: {cand['verdict']} | {cand['name']}"
        )

    # 2. Master grid at 30m resolution in EPSG:32643
    grid_spec = RegionalGridSpec.from_wgs84_bounds(
        min_lon=bbox_wgs84[0],
        min_lat=bbox_wgs84[1],
        max_lon=bbox_wgs84[2],
        max_lat=bbox_wgs84[3],
        resolution_m=30.0,
        target_epsg=32643,
    )

    logger.info(f"Target Projected Grid: EPSG:{grid_spec.crs_epsg}")
    logger.info(f"Fine 30m Dimensions: {grid_spec.width} cols x {grid_spec.height} rows ({grid_spec.width * grid_spec.height} cells)")
    logger.info(f"Projected Extent: X=[{grid_spec.min_x:.1f}, {grid_spec.max_x:.1f}], Y=[{grid_spec.min_y:.1f}, {grid_spec.max_y:.1f}]")

    builder = RegionalCostSurfaceBuilder(
        output_dir=output_dir,
        raw_dir=raw_dir,
        grid_spec=grid_spec,
        tile_size=1024,
        halo_pixels=3,
        resolution_m=30.0,
    )

    # 3. Build Fine (30m) Cost Surfaces
    t0 = time.time()
    manifest_fine = builder.build_all(region_name="mandi_to_delhi_corridor")
    elapsed_fine = time.time() - t0

    # 4. Build Coarse (100m) Cost Surfaces
    t1 = time.time()
    manifest_coarse = builder.build_coarse_surfaces(coarse_resolution_m=100.0, region_name="mandi_to_delhi_corridor")
    elapsed_coarse = time.time() - t1

    # Calculate total disk usage
    total_disk_bytes = sum(f.stat().st_size for f in (output_dir / "rasters").glob("*.tif"))
    total_disk_mb = total_disk_bytes / (1024 * 1024)

    logger.info("=" * 80)
    logger.info("PHASE C REGIONAL COST SURFACES COMPLETE!")
    logger.info("=" * 80)
    logger.info(f" - Fine 30m Manifest: {manifest_fine.manifest_id} ({elapsed_fine:.2f}s, {manifest_fine.summary.get('peak_ram_megabytes', 0.0)} MB RAM)")
    logger.info(f" - Coarse 100m Manifest: {manifest_coarse.manifest_id} ({elapsed_coarse:.2f}s, {manifest_coarse.summary.get('peak_ram_megabytes', 0.0)} MB RAM)")
    logger.info(f" - Total Layers (Fine + Coarse): {len(manifest_fine.layers) + len(manifest_coarse.layers)}")
    logger.info(f" - Total Output Disk Storage: {total_disk_mb:.2f} MB")
    logger.info(f" - Rasters Directory: {output_dir / 'rasters'}")
    logger.info(f" - Fine Manifest: {output_dir / 'regional_cost_manifest.json'}")
    logger.info(f" - Coarse Manifest: {output_dir / 'regional_cost_manifest_100m.json'}")

    logger.info("--- Fine 30m Layer Diagnostics ---")
    for lname, meta in manifest_fine.layers.items():
        logger.info(
            f"   * [{meta.layer_name}] Obj: {meta.objective_type:13s} | "
            f"Range: [{meta.min_value}, {meta.max_value}] | "
            f"Blocked: {meta.blocked_percentage:.1f}% | "
            f"Dtype: {meta.dtype}"
        )

    logger.info("--- Coarse 100m Layer Diagnostics ---")
    for lname, meta in manifest_coarse.layers.items():
        logger.info(
            f"   * [{meta.layer_name}] Obj: {meta.objective_type:13s} | "
            f"Range: [{meta.min_value}, {meta.max_value}] | "
            f"Blocked: {meta.blocked_percentage:.1f}% | "
            f"Dtype: {meta.dtype}"
        )

    logger.info("--- Corridor Tube Refinement Benchmarks ---")
    tube_bench = manifest_fine.target_grid.get("corridor_tube_refinement_benchmark", {})
    for b_name, b_diag in tube_bench.items():
        logger.info(
            f"   * [{b_name}] Buffer: +- {b_diag['buffer_envelope_km']} km | "
            f"Cells: {b_diag['tube_cells']:,} (vs {b_diag['master_cells']:,}) | "
            f"Savings: {b_diag['cell_reduction_percentage']}% | "
            f"Approaches Boundary: {b_diag['approaches_coverage_boundary']}"
        )

    logger.info("=" * 80)


if __name__ == "__main__":
    main()


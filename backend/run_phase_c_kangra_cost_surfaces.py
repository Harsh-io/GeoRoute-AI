"""Script to generate fine (30m) and coarse (100m) regional cost surfaces for the Kangra-Mandi corridor.

Covers Kangra District (Kangra Mandir Station, Dharamshala, Palampur, Baijnath) to Mandi Railway Station.
Grid: UTM Zone 43N (EPSG:32643), 30m resolution, ~95.9km x 90.1km.
"""

import logging
from pathlib import Path
import sys
import time

from georoute.cost.regional_cost_builder import (
    RegionalCostSurfaceBuilder,
    RegionalGridSpec,
    evaluate_regional_crs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("georoute.run_kangra_cost")


def main() -> None:
    output_dir = Path("data/cost/regional_kangra")
    raw_dir = Path("data/raw")

    # Kangra-Mandi corridor bounding box in WGS84:
    # Lon: 76.10E to 77.10E, Lat: 31.55N to 32.35N
    bbox_wgs84 = (76.10, 31.55, 77.10, 32.35)

    logger.info("=" * 80)
    logger.info("BUILDING REGIONAL COST SURFACES FOR KANGRA-MANDI MOUNTAIN CORRIDOR")
    logger.info(f"WGS84 Extent: Lon {bbox_wgs84[0]}..{bbox_wgs84[2]}, Lat {bbox_wgs84[1]}..{bbox_wgs84[3]}")
    logger.info("=" * 80)

    # 1. Evaluate Projected CRS
    crs_eval = evaluate_regional_crs(
        min_lon=bbox_wgs84[0],
        min_lat=bbox_wgs84[1],
        max_lon=bbox_wgs84[2],
        max_lat=bbox_wgs84[3],
    )
    logger.info(f"Selected CRS: {crs_eval['selected_crs']} ({crs_eval['selected_crs_name']})")

    # 2. Regional Grid Spec
    grid_spec = RegionalGridSpec.from_wgs84_bounds(
        min_lon=bbox_wgs84[0],
        min_lat=bbox_wgs84[1],
        max_lon=bbox_wgs84[2],
        max_lat=bbox_wgs84[3],
        resolution_m=30.0,
        target_epsg=32643,
    )
    logger.info(f"Fine 30m Dimensions: {grid_spec.width} cols x {grid_spec.height} rows ({grid_spec.width * grid_spec.height:,} cells)")
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
    manifest_fine = builder.build_all(region_name="kangra_to_mandi_corridor")
    elapsed_fine = time.time() - t0

    # 4. Build Coarse (100m) Cost Surfaces
    t1 = time.time()
    manifest_coarse = builder.build_coarse_surfaces(coarse_resolution_m=100.0, region_name="kangra_to_mandi_corridor")
    elapsed_coarse = time.time() - t1

    total_disk_bytes = sum(f.stat().st_size for f in (output_dir / "rasters").glob("*.tif"))
    total_disk_mb = total_disk_bytes / (1024 * 1024)

    logger.info("=" * 80)
    logger.info("KANGRA-MANDI REGIONAL COST SURFACES COMPLETED!")
    logger.info(f" - Fine 30m: {manifest_fine.manifest_id} in {elapsed_fine:.2f}s")
    logger.info(f" - Coarse 100m: {manifest_coarse.manifest_id} in {elapsed_coarse:.2f}s")
    logger.info(f" - Total Disk Storage: {total_disk_mb:.2f} MB")
    logger.info(f" - Rasters Directory: {output_dir / 'rasters'}")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

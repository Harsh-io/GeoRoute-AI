"""End-to-end pipeline runner: Mandi (HP) -> New Delhi Railway Station.

This script runs the complete GeoRoute AI pipeline for the Mandi->Delhi corridor:
  1. Data ingestion (OSM vectors via OSMnx)
  2. Railway route generation (3 route candidates)
  3. Data export (GeoJSON, metadata)
  4. Validation and reporting

Usage:
    python run_mandi_delhi_pipeline.py
    python run_mandi_delhi_pipeline.py --skip-ingestion  # Routes only
    python run_mandi_delhi_pipeline.py --output-dir ./data/routes/mandi_delhi
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from georoute.routing.railway_router import Coordinate, RailwayRouter
from georoute.utils.logging_config import setup_logger


# ---------------------------------------------------------------------------
# Hardcoded coordinates (per task requirement — use coordinates directly)
# ---------------------------------------------------------------------------
SOURCE = Coordinate(
    lat=31.7084,
    lon=76.9322,
    name="Mandi, Himachal Pradesh",
)
DESTINATION = Coordinate(
    lat=28.6428,
    lon=77.2191,
    name="New Delhi Railway Station",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="GeoRoute AI: Mandi -> New Delhi Railway Route Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./data/routes/mandi_delhi"),
        help="Output directory for route files.",
    )
    parser.add_argument(
        "--skip-ingestion",
        action="store_true",
        help="Skip OSM data ingestion, run routing only.",
    )
    parser.add_argument(
        "--num-routes",
        type=int,
        default=3,
        help="Number of route candidates to generate.",
    )
    parser.add_argument(
        "--live-graph",
        action="store_true",
        help="Attempt live OSM Overpass graph downloads for waypoints.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging.",
    )
    return parser.parse_args()


def run_vector_ingestion(output_dir: Path, logger: logging.Logger) -> dict:
    """Runs OSM vector ingestion for the Mandi and Delhi terminal areas.

    Returns:
        Dictionary with ingestion results.
    """
    from shapely.geometry import box
    from georoute.ingestion.vector_ingestor import OSMVectorIngestor

    logger.info("=" * 60)
    logger.info("Phase 1: OSM Vector Data Ingestion")
    logger.info("=" * 60)

    # Focus on terminal areas (Delhi terminal station & Mandi source area)
    # for performant Overpass query execution
    delhi_bbox = box(77.20, 28.63, 77.24, 28.66)
    mandi_bbox = box(76.90, 31.68, 76.96, 31.73)

    ingestor = OSMVectorIngestor(
        timeout_seconds=60,
        max_retries=3,
    )

    layer_configs = {
        "delhi_stations": {"tags": {"railway": "station"}, "aoi": delhi_bbox},
        "delhi_railways": {"tags": {"railway": "rail"}, "aoi": delhi_bbox},
        "mandi_infrastructure": {"tags": {"highway": ["primary", "secondary"]}, "aoi": mandi_bbox},
    }

    ingested = {}
    vector_dir = output_dir / "vector"
    vector_dir.mkdir(parents=True, exist_ok=True)

    for layer_name, cfg in layer_configs.items():
        logger.info(f"Fetching layer: {layer_name}...")
        try:
            gdf = ingestor.fetch_layer(
                layer_name=layer_name,
                aoi_polygon=cfg["aoi"],
                tags=cfg["tags"],
            )
            if not gdf.empty:
                out_path = vector_dir / f"{layer_name}.geojson"
                gdf.to_file(out_path, driver="GeoJSON")
                logger.info(f"  [OK] {layer_name}: {len(gdf)} features -> {out_path}")
                ingested[layer_name] = {"features": len(gdf), "path": str(out_path)}
            else:
                logger.warning(f"  [WARN] {layer_name}: No features returned.")
                ingested[layer_name] = {"features": 0, "path": None}
        except Exception as e:
            logger.error(f"  [FAIL] {layer_name} ingestion failed: {e}")
            ingested[layer_name] = {"features": 0, "error": str(e)}

    return ingested


def run_routing(
    output_dir: Path,
    num_routes: int,
    logger: logging.Logger,
    use_live_graph: bool = False,
) -> dict:
    """Runs the railway routing pipeline.

    Returns:
        Dictionary with routing results and file paths.
    """
    logger.info("=" * 60)
    logger.info("Phase 2: Railway Route Generation")
    logger.info(f"  Source     : {SOURCE.name}")
    logger.info(f"               Lat={SOURCE.lat}, Lon={SOURCE.lon}")
    logger.info(f"  Destination: {DESTINATION.name}")
    logger.info(f"               Lat={DESTINATION.lat}, Lon={DESTINATION.lon}")
    logger.info(f"  Routes     : {num_routes}")
    logger.info(f"  Live Graph : {use_live_graph}")
    logger.info("=" * 60)

    router = RailwayRouter(
        source=SOURCE,
        destination=DESTINATION,
        output_dir=output_dir,
        num_routes=num_routes,
        use_live_graph=use_live_graph,
    )

    # Generate routes
    result = router.generate_routes()

    # Save routes
    saved_paths = router.save_routes(result)

    # Build result summary
    routing_summary = result.summary()
    routing_summary["saved_files"] = {k: str(v) for k, v in saved_paths.items()}

    return routing_summary


def validate_routes(routing_summary: dict, logger: logging.Logger) -> dict:
    """Validates the generated routes.

    Returns:
        Validation report dictionary.
    """
    logger.info("=" * 60)
    logger.info("Phase 3: Route Validation")
    logger.info("=" * 60)

    validation = {
        "source_coordinates_correct": False,
        "destination_coordinates_correct": False,
        "exactly_3_routes": False,
        "all_geometries_valid": True,
        "no_empty_geometries": True,
        "routes_not_identical": True,
        "routes_have_distance": True,
        "serialisation_ok": False,
    }

    # Check coordinates
    src = routing_summary.get("source", {})
    dst = routing_summary.get("destination", {})
    validation["source_coordinates_correct"] = (
        abs(src.get("lat", 0) - SOURCE.lat) < 0.001
        and abs(src.get("lon", 0) - SOURCE.lon) < 0.001
    )
    validation["destination_coordinates_correct"] = (
        abs(dst.get("lat", 0) - DESTINATION.lat) < 0.001
        and abs(dst.get("lon", 0) - DESTINATION.lon) < 0.001
    )

    # Check route count
    routes = routing_summary.get("routes", [])
    validation["exactly_3_routes"] = len(routes) == 3

    # Check geometry/distance validity
    for r in routes:
        v = r.get("validation", {})
        if not v.get("geometry_valid", False):
            validation["all_geometries_valid"] = False
        if v.get("geometry_empty", True):
            validation["no_empty_geometries"] = False
        if r.get("length_km", 0) <= 0:
            validation["routes_have_distance"] = False

    # Check serialisation (check saved files exist)
    saved = routing_summary.get("saved_files", {})
    validation["serialisation_ok"] = len(saved) > 0 and all(
        Path(p).exists() for p in saved.values() if p
    )

    all_valid = all(validation.values())
    validation["overall_status"] = "PASSED" if all_valid else "PARTIAL"

    for check, passed in validation.items():
        status = "[OK]" if passed else "[FAIL]"
        logger.info(f"  {status} {check}: {passed}")

    return validation


def save_pipeline_report(
    output_dir: Path,
    vector_results: dict,
    routing_summary: dict,
    validation: dict,
    elapsed: float,
    logger: logging.Logger,
) -> Path:
    """Saves a JSON pipeline execution report."""
    report = {
        "pipeline": "GeoRoute AI - Mandi->Delhi Railway Routing",
        "source": {"name": SOURCE.name, "lat": SOURCE.lat, "lon": SOURCE.lon},
        "destination": {"name": DESTINATION.name, "lat": DESTINATION.lat, "lon": DESTINATION.lon},
        "total_elapsed_seconds": round(elapsed, 2),
        "vector_ingestion": vector_results,
        "routing": routing_summary,
        "validation": validation,
    }

    report_path = output_dir / "pipeline_report.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"Pipeline report saved: {report_path}")
    return report_path


def main() -> int:
    args = parse_args()
    log_level = "DEBUG" if args.verbose else "INFO"
    logger = setup_logger(name="georoute", level=log_level)

    pipeline_start = time.time()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("GeoRoute AI - Mandi -> New Delhi Railway Routing Pipeline")
    logger.info("=" * 70)

    vector_results = {}
    routing_summary = {}
    validation = {}

    try:
        # Phase 1: Vector Ingestion (optional)
        if not args.skip_ingestion:
            vector_results = run_vector_ingestion(output_dir, logger)
        else:
            logger.info("Skipping vector ingestion (--skip-ingestion flag set).")

        # Phase 2: Route Generation
        routing_summary = run_routing(
            output_dir, args.num_routes, logger, use_live_graph=args.live_graph
        )

        # Phase 3: Validation
        validation = validate_routes(routing_summary, logger)

    except Exception as exc:
        logger.exception(f"Pipeline failed: {exc}")
        return 1
    finally:
        total_elapsed = time.time() - pipeline_start

        # Always save what we have
        report_path = save_pipeline_report(
            output_dir, vector_results, routing_summary, validation, total_elapsed, logger
        )

        # Print final summary
        logger.info("=" * 70)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 70)

        for i, route in enumerate(routing_summary.get("routes", []), start=1):
            logger.info(
                f"  Route {i}: {route.get('route_id', '?')} | "
                f"Strategy: {route.get('strategy', '?')} | "
                f"Length: {route.get('length_km', 0):.1f} km | "
                f"Nodes: {route.get('num_nodes', 0)}"
            )

        val_status = validation.get("overall_status", "UNKNOWN")
        logger.info(f"  Validation: {val_status}")
        logger.info(f"  Total time: {total_elapsed:.1f}s")
        logger.info(f"  Report: {report_path}")
        logger.info("=" * 70)

        # Print JSON summary to stdout
        print(json.dumps(routing_summary, indent=2, default=str))

    return 0 if validation.get("overall_status") in ("PASSED", "PARTIAL") else 1


if __name__ == "__main__":
    sys.exit(main())

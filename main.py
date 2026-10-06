"""GeoRoute AI: CLI Entrypoint for Data Ingestion & Preprocessing."""

import argparse
import json
import logging
import sys
from pathlib import Path
from georoute.config import PipelineConfig
from georoute.pipeline import GeoRoutePipeline
from georoute.utils.logging_config import setup_logger


def parse_args() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="GeoRoute AI: Enterprise Data Ingestion & Preprocessing Pipeline (Part 1)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config/config.yaml"),
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "-e",
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to environment variables file.",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Override output directory specified in config.yaml.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging.",
    )
    return parser.parse_args()


def main() -> int:
    """Main CLI execution routine."""
    args = parse_args()

    log_level = "DEBUG" if args.verbose else "INFO"
    logger = setup_logger(name="georoute", level=log_level)

    try:
        # Load and validate configuration
        logger.info(f"Loading pipeline configuration from: {args.config}")
        env_path = args.env if args.env.exists() else None
        config = PipelineConfig.from_yaml(yaml_path=args.config, env_file=env_path)

        # Apply output directory override if provided
        if args.output_dir:
            config.export.output_dir = args.output_dir

        # Initialize and execute pipeline
        pipeline = GeoRoutePipeline(config=config, custom_logger=logger)
        summary = pipeline.execute()

        # Print final JSON summary to stdout
        logger.info("Pipeline Execution Summary:")
        print(json.dumps(summary, indent=2))
        return 0

    except Exception as exc:
        logger.exception(f"Pipeline execution aborted due to unhandled error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Master cost surface builder and friction map orchestration pipeline (Part 3).

Transforms Part 2 feature layers into three mathematically consistent,
spatially aligned cost surfaces:
1. Distance traversal cost (pure physical travel distance)
2. Estimated construction-difficulty cost (slope, land cover, building, water, highway)
3. Environmental-impact proxy cost (statutory exclusions, forest canopy, wetlands)

Outputs:
- Cloud-Optimized GeoTIFFs (COGs) with internal overviews for all surfaces and intermediate penalty layers.
- Diagnostic comparative plots.
- Pydantic-validated cost_surface_manifest.json and cost_surface_summary.json.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import rasterio

from georoute.cost.construction_cost_model import ConstructionCostModel
from georoute.cost.cost_assumptions import CostAssumptions
from georoute.cost.cost_diagnostics import CostDiagnosticsVisualizer
from georoute.cost.cost_surface_validator import CostSurfaceValidator
from georoute.cost.distance_cost_model import DistanceCostModel
from georoute.cost.environmental_cost_model import EnvironmentalCostModel
from georoute.processing.alignment import AlignedRasterData
from georoute.processing.cog_exporter import GeoDataExporter
from georoute.schemas.cost_manifest_schema import (
    CostLayerMetadata,
    CostSurfaceManifest,
)

logger = logging.getLogger("georoute.cost.builder")


def compute_sha256(path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class CostSurfaceBuilder:
    """Orchestrates multi-objective cost surface construction, validation, and export."""

    def __init__(
        self,
        features_dir: Union[str, Path] = "data/features",
        output_dir: Union[str, Path] = "data/cost",
        assumptions: Optional[CostAssumptions] = None,
        custom_logger: Optional[logging.Logger] = None,
    ):
        """Initializes the builder.

        Args:
            features_dir: Directory containing Part 2 features and manifest.
            output_dir: Destination directory for Part 3 cost surfaces and manifests.
            assumptions: Optional CostAssumptions configuration model.
            custom_logger: Optional pre-configured logger.
        """
        self.features_dir = Path(features_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.assumptions = assumptions or CostAssumptions()
        self.logger = custom_logger or logger
        self.validator = CostSurfaceValidator(blocked_cell_cost=self.assumptions.constraints.blocked_cell_cost)
        self.diagnostics = CostDiagnosticsVisualizer(blocked_cell_cost=self.assumptions.constraints.blocked_cell_cost)

    def load_raster(self, filename: str) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Loads a raster array and its georeferencing metadata."""
        path = self.features_dir / "rasters" / filename
        if not path.exists():
            raise FileNotFoundError(f"Required Part 2 feature raster missing: {path}")

        with rasterio.open(path) as src:
            arr = src.read(1)
            meta = {
                "transform": src.transform,
                "crs": src.crs,
                "shape": (src.height, src.width),
                "nodata": src.nodata,
                "dtype": src.dtypes[0],
            }
        return arr, meta

    def build_all(
        self,
        region_name: str = "mandi_terminal_5x5km",
    ) -> CostSurfaceManifest:
        """Executes full multi-objective cost modeling pipeline.

        Args:
            region_name: AOI identifier.

        Returns:
            Validated CostSurfaceManifest.
        """
        start_time = time.time()
        self.logger.info("=" * 80)
        self.logger.info(f"Starting GeoRoute AI Cost Surface Modeling Pipeline (Part 3) for: '{region_name}'")
        self.logger.info(f"Features Directory: {self.features_dir}")
        self.logger.info(f"Cost Output Directory: {self.output_dir}")
        self.logger.info("=" * 80)

        warnings: List[str] = []
        errors: List[str] = []

        # ----------------------------------------------------------------------
        # 1. Load Feature Layers
        # ----------------------------------------------------------------------
        slope_fname = "slope_percent.tif" if self.assumptions.slope.slope_source == "slope_percent" else "slope_degrees.tif"
        self.logger.info(f"Loading terrain slope from: {slope_fname}")
        slope_arr, grid_meta = self.load_raster(slope_fname)
        grid_shape = grid_meta["shape"]
        target_transform = grid_meta["transform"]
        target_crs = grid_meta["crs"]
        dx = abs(target_transform.a)
        dy = abs(target_transform.e)

        self.logger.info(f"Loading classified land cover...")
        lc_arr, _ = self.load_raster("classified_landcover.tif")

        self.logger.info(f"Loading obstacle and environmental masks...")
        bldg_mask, _ = self.load_raster("building_mask.tif")
        water_mask, _ = self.load_raster("water_mask.tif")
        highway_mask, _ = self.load_raster("highway_mask.tif")
        forest_mask, _ = self.load_raster("forest_mask.tif")
        wetland_mask, _ = self.load_raster("wetland_mask.tif")
        pa_mask, _ = self.load_raster("protected_area_mask.tif")

        # Optional NDVI
        ndvi_path = self.features_dir / "rasters" / "ndvi.tif"
        ndvi_arr: Optional[np.ndarray] = None
        if ndvi_path.exists():
            ndvi_arr, _ = self.load_raster("ndvi.tif")

        # ----------------------------------------------------------------------
        # 2. Derive Validity and Hard Constraint Masks
        # ----------------------------------------------------------------------
        self.logger.info("Deriving master validity mask and hard constraint exclusions...")
        # Valid data: non-nodata slope and non-nodata land cover
        invalid_slope = (slope_arr == -9999.0) | np.isnan(slope_arr) | (slope_arr < 0.0)
        invalid_lc = (lc_arr == 0)
        valid_data_mask = (~invalid_slope & ~invalid_lc).astype(np.uint8)

        # Hard constraints
        hard_constraint_mask = np.zeros(grid_shape, dtype=np.uint8)

        # Statutory protected areas policy
        if self.assumptions.environmental.protected_area_policy == "HARD_EXCLUSION":
            hard_constraint_mask[pa_mask == 1] = 1

        # Buildings hard exclusion policy
        if self.assumptions.obstacles.building_hard_exclusion:
            hard_constraint_mask[bldg_mask == 1] = 1

        # Conservative unknown-data policy: unknown cells are blocked from routing
        if self.assumptions.constraints.treat_nodata_as_blocked:
            hard_constraint_mask[valid_data_mask == 0] = 1

        # ----------------------------------------------------------------------
        # 3. Model 1: Distance Cost Surface
        # ----------------------------------------------------------------------
        self.logger.info("Computing pure distance traversal cost surface...")
        dist_model = DistanceCostModel(
            config=self.assumptions.distance,
            blocked_cell_cost=self.assumptions.constraints.blocked_cell_cost,
        )
        dist_cost, dist_friction = dist_model.compute_surface(
            grid_shape=grid_shape,
            hard_constraint_mask=hard_constraint_mask,
            valid_data_mask=valid_data_mask,
        )

        # ----------------------------------------------------------------------
        # 4. Model 2: Construction Difficulty Cost Surface
        # ----------------------------------------------------------------------
        self.logger.info("Computing estimated construction-difficulty cost surface...")
        const_model = ConstructionCostModel.from_assumptions(
            self.assumptions,
            blocked_cell_cost=self.assumptions.constraints.blocked_cell_cost,
        )
        const_cost, const_friction, const_penalties = const_model.compute_surface(
            slope_arr=slope_arr,
            lc_arr=lc_arr,
            building_mask=bldg_mask,
            water_mask=water_mask,
            highway_mask=highway_mask,
            hard_constraint_mask=hard_constraint_mask,
            valid_data_mask=valid_data_mask,
            nodata_slope=-9999.0,
            nodata_lc=0.0,
        )

        # ----------------------------------------------------------------------
        # 5. Model 3: Environmental Impact Proxy Cost Surface
        # ----------------------------------------------------------------------
        self.logger.info("Computing environmental-impact proxy cost surface...")
        env_model = EnvironmentalCostModel.from_assumptions(
            self.assumptions,
            blocked_cell_cost=self.assumptions.constraints.blocked_cell_cost,
        )
        env_cost, env_friction, env_sensitivities = env_model.compute_surface(
            forest_mask=forest_mask,
            wetland_mask=wetland_mask,
            water_mask=water_mask,
            protected_area_mask=pa_mask,
            ndvi_arr=ndvi_arr,
            hard_constraint_mask=hard_constraint_mask,
            valid_data_mask=valid_data_mask,
        )

        # ----------------------------------------------------------------------
        # 6. Validate Multi-Objective Surfaces
        # ----------------------------------------------------------------------
        self.logger.info("Auditing cost surface integrity, alignment, and independence...")
        validation_res = self.validator.validate_surfaces(
            distance_cost=dist_cost,
            construction_cost=const_cost,
            environmental_cost=env_cost,
            hard_constraint_mask=hard_constraint_mask,
            valid_data_mask=valid_data_mask,
        )
        if not validation_res["all_passed"]:
            for err in validation_res["errors"]:
                self.logger.error(f"Cost surface validation error: {err}")
                errors.append(err)
        else:
            self.logger.info("All cost surface validation checks passed successfully!")

        # ----------------------------------------------------------------------
        # 7. Export Cloud-Optimized GeoTIFFs (COGs)
        # ----------------------------------------------------------------------
        self.logger.info("Exporting Cloud-Optimized GeoTIFFs for cost surfaces and penalty layers...")
        exporter = GeoDataExporter(output_dir=self.output_dir, compression="deflate")

        rasters_to_export: Dict[str, Tuple[np.ndarray, str, Optional[float], str, str]] = {
            # Primary cost surfaces
            "distance_cost.tif": (dist_cost, "distance_cost", self.assumptions.constraints.blocked_cell_cost, "float32", "DISTANCE"),
            "construction_cost.tif": (const_cost, "construction_cost", self.assumptions.constraints.blocked_cell_cost, "float32", "CONSTRUCTION"),
            "environmental_cost.tif": (env_cost, "environmental_cost", self.assumptions.constraints.blocked_cell_cost, "float32", "ENVIRONMENTAL"),
            # Friction surfaces (dimensionless multiplier)
            "distance_friction.tif": (dist_friction, "distance_friction", self.assumptions.constraints.blocked_cell_cost, "float32", "DISTANCE"),
            "construction_friction.tif": (const_friction, "construction_friction", self.assumptions.constraints.blocked_cell_cost, "float32", "CONSTRUCTION"),
            "environmental_friction.tif": (env_friction, "environmental_friction", self.assumptions.constraints.blocked_cell_cost, "float32", "ENVIRONMENTAL"),
            # Constraints and validity masks
            "hard_constraint_mask.tif": (hard_constraint_mask, "hard_constraint_mask", 255.0, "uint8", "CONSTRAINT"),
            "valid_data_mask.tif": (valid_data_mask, "valid_data_mask", 255.0, "uint8", "CONSTRAINT"),
            # Intermediate construction penalties
            "slope_penalty.tif": (const_penalties["slope_penalty"], "slope_penalty", -9999.0, "float32", "PENALTY"),
            "landcover_penalty.tif": (const_penalties["landcover_penalty"], "landcover_penalty", -9999.0, "float32", "PENALTY"),
            "building_penalty.tif": (const_penalties["building_penalty"], "building_penalty", -9999.0, "float32", "PENALTY"),
            "water_crossing_penalty.tif": (const_penalties["water_crossing_penalty"], "water_crossing_penalty", -9999.0, "float32", "PENALTY"),
            "highway_crossing_penalty.tif": (const_penalties["highway_crossing_penalty"], "highway_crossing_penalty", -9999.0, "float32", "PENALTY"),
            # Intermediate environmental sensitivities
            "forest_sensitivity.tif": (env_sensitivities["forest_sensitivity"], "forest_sensitivity", -9999.0, "float32", "PENALTY"),
            "wetland_sensitivity.tif": (env_sensitivities["wetland_sensitivity"], "wetland_sensitivity", -9999.0, "float32", "PENALTY"),
            "water_sensitivity.tif": (env_sensitivities["water_sensitivity"], "water_sensitivity", -9999.0, "float32", "PENALTY"),
        }

        exported_layers: Dict[str, CostLayerMetadata] = {}

        for fname, (arr, band_name, nodata_val, dt_str, obj_type) in rasters_to_export.items():
            aligned_obj = AlignedRasterData(
                data=arr[np.newaxis, :, :],
                transform=target_transform,
                crs=target_crs,
                nodata=nodata_val,
                band_names=[band_name],
                dtype=np.dtype(dt_str),
            )
            exported_path = exporter.export_cog(aligned_obj, filename=fname)
            sha_hash = compute_sha256(exported_path)

            # Statistics calculation
            total_cells = grid_shape[0] * grid_shape[1]
            if dt_str == "float32":
                valid_mask = (arr != nodata_val) & ~np.isnan(arr) & (arr >= 0.0)
                traversable_cells = int(np.count_nonzero(valid_mask))
                blocked_cells = total_cells - traversable_cells
                vals = arr[valid_mask]
                min_v = float(np.min(vals)) if len(vals) > 0 else None
                max_v = float(np.max(vals)) if len(vals) > 0 else None
                mean_v = float(np.mean(vals)) if len(vals) > 0 else None
                std_v = float(np.std(vals)) if len(vals) > 0 else None
            else:
                # Binary mask
                traversable_cells = int(np.count_nonzero(arr == 0))
                blocked_cells = int(np.count_nonzero(arr == 1))
                min_v = float(np.min(arr))
                max_v = float(np.max(arr))
                mean_v = float(np.mean(arr))
                std_v = float(np.std(arr))

            layer_key = fname.replace(".tif", "")
            unit_semantics = (
                "metres" if "cost" in fname and "distance" in fname
                else "dimensionless_friction_factor" if "friction" in fname
                else "relative_difficulty_score_x_10m" if "construction_cost" in fname
                else "relative_sensitivity_score_x_10m" if "environmental_cost" in fname
                else "binary_mask" if "mask" in fname
                else "penalty_component"
            )

            exported_layers[layer_key] = CostLayerMetadata(
                layer_name=layer_key,
                file_path=str(exported_path.relative_to(self.output_dir.parent)),
                objective_type=obj_type,
                crs=str(target_crs),
                width=grid_shape[1],
                height=grid_shape[0],
                dtype=dt_str,
                nodata=nodata_val,
                resolution_meters=dx,
                transform=[target_transform.a, target_transform.b, target_transform.c, target_transform.d, target_transform.e, target_transform.f],
                sha256=sha_hash,
                spatial_alignment_verified=True,
                unit_or_semantics=unit_semantics,
                min_value=min_v,
                max_value=max_v,
                mean_value=mean_v,
                std_value=std_v,
                traversable_cells=traversable_cells,
                blocked_cells=blocked_cells,
                blocked_percentage=round(blocked_cells / total_cells * 100.0, 4),
            )

        # ----------------------------------------------------------------------
        # 8. Diagnostic Visualization
        # ----------------------------------------------------------------------
        diag_dir = self.output_dir / "diagnostics"
        diag_plot_path = diag_dir / "cost_surfaces_comparison.png"
        try:
            self.diagnostics.plot_cost_surfaces_comparison(
                distance_cost=dist_cost,
                construction_cost=const_cost,
                environmental_cost=env_cost,
                hard_constraint_mask=hard_constraint_mask,
                output_path=diag_plot_path,
                region_name=region_name,
            )
            self.logger.info(f"Generated diagnostic visualization: {diag_plot_path}")
        except Exception as e:
            self.logger.warning(f"Could not generate diagnostic visualization: {e}")
            warnings.append(f"Diagnostic plot generation failed: {e}")

        # ----------------------------------------------------------------------
        # 9. Compile Manifest & High-Level Summary
        # ----------------------------------------------------------------------
        elapsed = round(time.time() - start_time, 2)
        summary_dict = {
            "region_name": region_name,
            "grid_dimensions": {"width": grid_shape[1], "height": grid_shape[0]},
            "resolution_meters": dx,
            "total_cells": grid_shape[0] * grid_shape[1],
            "distance_cost": {
                "traversable_cells": exported_layers["distance_cost"].traversable_cells,
                "traversable_cost_min": exported_layers["distance_cost"].min_value,
                "traversable_cost_max": exported_layers["distance_cost"].max_value,
                "unit": "metres per 10m cell",
            },
            "construction_cost": {
                "traversable_cells": exported_layers["construction_cost"].traversable_cells,
                "mean_cost": exported_layers["construction_cost"].mean_value,
                "std_cost": exported_layers["construction_cost"].std_value,
                "semantics": "dimensionless relative difficulty score * 10m",
            },
            "environmental_cost": {
                "traversable_cells": exported_layers["environmental_cost"].traversable_cells,
                "mean_cost": exported_layers["environmental_cost"].mean_value,
                "std_cost": exported_layers["environmental_cost"].std_value,
                "semantics": "dimensionless relative ecological sensitivity proxy * 10m",
            },
            "hard_constraints": {
                "blocked_cells": exported_layers["hard_constraint_mask"].blocked_cells,
                "blocked_percentage": exported_layers["hard_constraint_mask"].blocked_percentage,
                "policy": self.assumptions.constraints.treat_nodata_as_blocked,
            },
        }

        # Save summary JSON
        summary_path = self.output_dir / "cost_surface_summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_dict, f, indent=2)

        # Save assumptions JSON
        assumptions_path = self.output_dir / "cost_assumptions.json"
        self.assumptions.to_json(assumptions_path)

        manifest = CostSurfaceManifest(
            schema_version="3.0.0",
            manifest_id=f"MANIFEST_PART3_{region_name.upper()}_{int(time.time())}",
            generated_at=datetime.now(timezone.utc).isoformat(),
            region_name=region_name,
            pipeline_status="SUCCESS" if not errors else "FAILED",
            elapsed_seconds=elapsed,
            spatial_reference={
                "target_crs": str(target_crs),
                "resolution_meters": dx,
                "transform": [target_transform.a, target_transform.b, target_transform.c, target_transform.d, target_transform.e, target_transform.f],
            },
            target_grid={
                "width": grid_shape[1],
                "height": grid_shape[0],
                "resolution_meters": dx,
            },
            cost_assumptions=self.assumptions.model_dump(),
            layers=exported_layers,
            summary=summary_dict,
            validation_results=validation_res,
            warnings=warnings,
            errors=errors,
        )

        manifest_path = self.output_dir / "cost_surface_manifest.json"
        manifest.to_json_file(manifest_path)
        self.logger.info(f"Saved machine-readable cost surface manifest to: {manifest_path}")
        self.logger.info(f"Part 3 Pipeline completed successfully in {elapsed}s.")

        return manifest


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    builder = CostSurfaceBuilder()
    manifest = builder.build_all()
    print(f"Cost Surface Manifest generated: {manifest.manifest_id}")

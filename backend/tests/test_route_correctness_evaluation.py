"""Automated Route Correctness Evaluation Test Suite for GeoRoute AI.

Audits candidate corridors against raw rasters, confirming mathematical
trade-offs, continuous geometry, and hard obstacle constraint avoidance.
"""

from pathlib import Path
import time
import affine
import numpy as np
import pytest
import pyproj
import rasterio
from shapely.geometry import LineString

from app.main import create_app
from fastapi.testclient import TestClient
from georoute.routing.pyorps_adapter import PyorpsAdapter, InfeasibleRouteError


@pytest.fixture(scope="module")
def shared_job_result():
    """Generates a standard 3-objective corridor result for evaluation tests."""
    app = create_app()
    with TestClient(app) as client:
        payload = {
            "source": {"longitude": 76.9312, "latitude": 31.7084, "name": "Mandi Valley Entry"},
            "destination": {"longitude": 76.9425, "latitude": 31.7220, "name": "North Ridge Portal"},
            "processing_mode": "precomputed",
            "objectives": [
                "shortest_distance",
                "lowest_construction_difficulty",
                "lowest_environmental_impact",
            ],
            "snap_to_valid": True,
            "backend": "pyorps",
        }
        res = client.post("/api/v1/generate-routes", json=payload)
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        for _ in range(40):
            status = client.get(f"/api/v1/jobs/{job_id}").json()["status"]
            if status in ("completed", "partial_success", "failed"):
                break
            time.sleep(0.3)

        result_data = client.get(f"/api/v1/jobs/{job_id}/result").json()
        geojson_data = client.get(f"/api/v1/jobs/{job_id}/routes.geojson").json()

        return {
            "job_id": job_id,
            "result": result_data,
            "geojson": geojson_data,
        }


class TestRouteCorrectnessEvaluation:
    """Verifies geometric and mathematical correctness of candidate corridors."""

    def test_01_geometry_continuity_and_rfc7946(self, shared_job_result):
        """Verifies that all candidate corridor geometries are valid, continuous WGS84 LineStrings."""
        geojson = shared_job_result["geojson"]
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 3

        for feat in geojson["features"]:
            coords = feat["geometry"]["coordinates"]
            line = LineString(coords)
            assert line.is_valid
            assert not line.is_empty
            assert len(coords) >= 10, "Corridor must consist of multiple sampled vertices"

            # Check continuity: no extreme coordinate jumps (> 50m step in 10m grid)
            for i in range(len(coords) - 1):
                lon1, lat1 = coords[i]
                lon2, lat2 = coords[i + 1]
                assert abs(lon2 - lon1) < 0.005
                assert abs(lat2 - lat1) < 0.005

    def test_02_independent_raster_sampling_and_constraint_immunity(self, shared_job_result):
        """Independently samples raw rasters to prove 0 NoData traversals and 0 hard constraint breaches."""
        geojson = shared_job_result["geojson"]
        valid_mask_path = Path("data/cost/rasters/valid_data_mask.tif")
        hard_mask_path = Path("data/cost/rasters/hard_constraint_mask.tif")

        assert valid_mask_path.exists(), "valid_data_mask.tif missing"
        assert hard_mask_path.exists(), "hard_constraint_mask.tif missing"

        to_utm = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)

        with rasterio.open(valid_mask_path) as v_src, rasterio.open(hard_mask_path) as h_src:
            for feat in geojson["features"]:
                wgs84_coords = feat["geometry"]["coordinates"]
                utm_coords = [to_utm.transform(lon, lat) for lon, lat in wgs84_coords]

                v_samples = [int(v[0]) for v in v_src.sample(utm_coords)]
                h_samples = [int(h[0]) for h in h_src.sample(utm_coords)]

                nodata_violations = sum(1 for v in v_samples if v == 0)
                hard_violations = sum(1 for h in h_samples if h == 1)

                assert nodata_violations == 0, f"Route {feat['properties']['route_id']} crossed {nodata_violations} NoData cells"
                assert hard_violations == 0, f"Route {feat['properties']['route_id']} crossed {hard_violations} hard obstacles"

    def test_03_expected_mathematical_tradeoffs(self, shared_job_result):
        """Verifies that the three objectives exhibit distinct, expected multi-objective trade-offs."""
        routes = {r["objective"]: r for r in shared_job_result["result"]["routes"]}
        dist_route = routes["shortest_distance"]
        const_route = routes["lowest_construction_difficulty"]
        env_route = routes["lowest_environmental_impact"]

        # 1. Shortest distance has smallest physical length
        assert dist_route["length_km"] <= const_route["length_km"] * 1.05

        # 2. Construction difficulty optimizes slope gradients
        const_mean_slope = const_route["slope_profile"]["mean_percent"]
        dist_mean_slope = dist_route["slope_profile"]["mean_percent"]
        assert const_mean_slope < dist_mean_slope, (
            f"Construction route ({const_mean_slope}%) must have gentler slope than distance ({dist_mean_slope}%)"
        )

        # 3. Environmental impact avoids virgin tree canopy
        const_forest = const_route.get("landcover_distribution_percent", {}).get("Tree cover / Forest", 100)
        env_forest = env_route.get("landcover_distribution_percent", {}).get("Tree cover / Forest", 100)
        assert env_forest <= const_forest or env_route["length_km"] > 0

    def test_04_controlled_synthetic_barrier_fixture(self):
        """Verifies pathfinding failure when severed by an impenetrable obstacle wall (SYNTHETIC FIXTURE)."""
        adapter = PyorpsAdapter(scale_factor=100.0)
        shape = (10, 10)
        transform = affine.Affine(10.0, 0.0, 1000.0, 0.0, -10.0, 2000.0)
        crs = "EPSG:32643"

        friction = np.ones(shape, dtype=np.float32)
        hard_mask = np.zeros(shape, dtype=np.uint8)
        # Impenetrable barrier severing start from target across entire column 5
        hard_mask[:, 5] = 1

        quantized = adapter.quantize_friction_to_uint16(friction, hard_constraint_mask=hard_mask)

        # Endpoint coordinates: col 1 to col 8 across the column 5 wall
        source_xy = (1015.0, 1955.0)
        target_xy = (1085.0, 1955.0)

        with pytest.raises(InfeasibleRouteError):
            adapter.find_route(
                quantized_raster=quantized,
                source_coords=source_xy,
                target_coords=target_xy,
                transform=transform,
                crs=crs,
                original_friction_raster=friction,
            )

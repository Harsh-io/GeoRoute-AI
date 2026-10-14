"""Real API integration tests for GeoRoute AI backend service.

Validates real FastAPI endpoints, asynchronous job execution lifecycle,
result extraction, RFC 7946 GeoJSON streaming, and out-of-coverage rejections.
"""

import json
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture(scope="module")
def real_api_client():
    """Initializes a real TestClient instance running the full FastAPI application lifespan."""
    app = create_app()
    with TestClient(app) as client:
        yield client


class TestRealApiIntegration:
    """End-to-end integration test suite exercising actual backend endpoints."""

    def test_01_health_readiness_and_capabilities(self, real_api_client: TestClient):
        """Validates diagnostic endpoints (/health, /ready, /capabilities)."""
        # 1. Health
        res_health = real_api_client.get("/api/v1/health")
        assert res_health.status_code == 200
        health_data = res_health.json()
        assert health_data["status"] == "healthy"
        assert "version" in health_data
        assert health_data["uptime_seconds"] >= 0

        # 2. Readiness
        res_ready = real_api_client.get("/api/v1/ready")
        assert res_ready.status_code == 200
        ready_data = res_ready.json()
        assert ready_data["status"] == "ready"
        assert ready_data["precomputed_mode_ready"] is True
        assert ready_data["storage_ready"] is True
        assert ready_data["pyorps_engine_available"] is True

        # 3. Capabilities
        res_cap = real_api_client.get("/api/v1/capabilities")
        assert res_cap.status_code == 200
        cap_data = res_cap.json()
        assert set(cap_data["supported_objectives"]) == {
            "shortest_distance",
            "lowest_construction_difficulty",
            "lowest_environmental_impact",
        }
        assert cap_data["routing_backend"] == "pyorps_cython"
        assert "mandi" in cap_data["current_dataset_coverage"]["region_name"].lower()
        bounds = cap_data["current_dataset_coverage"]["approximate_wgs84_bounds"]
        assert bounds["min_lon"] < bounds["max_lon"]
        assert bounds["min_lat"] < bounds["max_lat"]

    def test_02_out_of_coverage_rejection_delhi(self, real_api_client: TestClient):
        """Verifies that requesting a destination at New Delhi (341km south) is rejected with HTTP 422."""
        payload = {
            "source": {"longitude": 76.9312, "latitude": 31.7084, "name": "Mandi Station"},
            "destination": {"longitude": 77.2197, "latitude": 28.6431, "name": "New Delhi Station"},
            "processing_mode": "precomputed",
        }
        res = real_api_client.post("/api/v1/generate-routes", json=payload)
        assert res.status_code == 422
        err = res.json()
        assert err["code"] == "OUT_OF_COVERAGE"
        assert "outside raster grid bounds" in err["message"].lower()
        coverage_note = err.get("details", {}).get("coverage_note", "").lower()
        assert "outside the currently loaded mandi" in coverage_note

    def test_03_valid_job_submission_and_async_lifecycle(self, real_api_client: TestClient):
        """Submits an in-coverage route generation job and polls through to completed result."""
        # Endpoints well inside the Mandi regional grid
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
            "max_snap_radius_m": 500.0,
            "backend": "pyorps",
        }

        # 1. Submit Job
        res_sub = real_api_client.post("/api/v1/generate-routes", json=payload)
        assert res_sub.status_code == 202
        sub_data = res_sub.json()
        job_id = sub_data["job_id"]
        assert job_id.startswith("job_")
        assert sub_data["status"] == "queued"

        # 2. Poll until terminal state
        terminal_status = None
        for _ in range(30):
            res_poll = real_api_client.get(f"/api/v1/jobs/{job_id}")
            assert res_poll.status_code == 200
            poll_data = res_poll.json()
            status = poll_data["status"]
            if status in ("completed", "partial_success", "failed", "cancelled"):
                terminal_status = status
                break
            time.sleep(0.4)

        assert terminal_status in ("completed", "partial_success"), f"Job did not succeed: {terminal_status}"

        # 3. Retrieve Structured Result
        res_result = real_api_client.get(f"/api/v1/jobs/{job_id}/result")
        assert res_result.status_code == 200
        result_data = res_result.json()
        assert result_data["job_id"] == job_id
        assert result_data["num_routes"] == 3
        routes = result_data["routes"]
        objectives_found = [r["objective"] for r in routes]
        assert "shortest_distance" in objectives_found
        assert "lowest_construction_difficulty" in objectives_found
        assert "lowest_environmental_impact" in objectives_found

        for r in routes:
            assert r["length_km"] > 0
            assert r["accumulated_cost"] > 0
            assert "cost_units" in r
            assert "slope_profile" in r

        # 4. Retrieve RFC 7946 GeoJSON
        res_geojson = real_api_client.get(f"/api/v1/jobs/{job_id}/routes.geojson")
        assert res_geojson.status_code == 200
        assert "geo+json" in res_geojson.headers.get("content-type", "")
        geojson_data = res_geojson.json()
        assert geojson_data["type"] == "FeatureCollection"
        assert len(geojson_data["features"]) == 3

        for feat in geojson_data["features"]:
            assert feat["type"] == "Feature"
            assert feat["geometry"]["type"] == "LineString"
            coords = feat["geometry"]["coordinates"]
            assert len(coords) >= 2
            # Validate coordinates are WGS84
            for lon, lat in coords:
                assert 76.5 <= lon <= 77.5
                assert 31.0 <= lat <= 32.5

    def test_04_job_cancellation_and_not_found(self, real_api_client: TestClient):
        """Verifies cancellation behavior and 404 on nonexistent job."""
        # Nonexistent job
        res_404 = real_api_client.get("/api/v1/jobs/job_nonexistent_999")
        assert res_404.status_code == 404
        assert res_404.json()["code"] == "JOB_NOT_FOUND"

        # Cancel nonexistent job
        res_cancel_404 = real_api_client.post("/api/v1/jobs/job_nonexistent_999/cancel")
        assert res_cancel_404.status_code == 404
        assert res_cancel_404.json()["code"] == "JOB_NOT_FOUND"

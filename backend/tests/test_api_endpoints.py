"""Integration tests for GeoRoute AI FastAPI endpoints using TestClient."""

import time
from fastapi.testclient import TestClient
import pytest

from app.main import create_app


@pytest.fixture(scope="module")
def client():
    """Provides a TestClient with initialized lifespan resources."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_root_index(client):
    """Verifies top-level index metadata."""
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "online"
    assert "version" in data
    assert data["api_prefix"] == "/api/v1"


def test_health_endpoint(client):
    """Verifies /api/v1/health returns healthy liveness."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["version"] == "1.0.0"
    assert "uptime_seconds" in data
    assert "timestamp" in data


def test_ready_endpoint(client):
    """Verifies /api/v1/ready returns readiness across components."""
    res = client.get("/api/v1/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["precomputed_mode_ready"] is True
    assert data["pyorps_engine_available"] is True
    assert data["storage_ready"] is True


def test_capabilities_endpoint(client):
    """Verifies /api/v1/capabilities documents objectives, backend, and coverage limits."""
    res = client.get("/api/v1/capabilities")
    assert res.status_code == 200
    data = res.json()
    assert "shortest_distance" in data["supported_objectives"]
    assert "lowest_construction_difficulty" in data["supported_objectives"]
    assert "lowest_environmental_impact" in data["supported_objectives"]
    assert data["routing_backend"] == "pyorps_cython"
    assert "precomputed" in data["available_processing_modes"]
    coverage = data["current_dataset_coverage"]
    assert coverage["region_name"] == "mandi_terminal_5x5km"
    assert "geographic_limitation" in coverage
    assert "preliminary regional planning corridors" in data["engineering_disclaimer"]


def test_generate_routes_out_of_coverage_rejection(client):
    """Verifies that requesting New Delhi Station (341km away) is rejected with HTTP 422."""
    payload = {
        "source": {"longitude": 76.9322, "latitude": 31.7084, "name": "Mandi Station"},
        "destination": {"longitude": 77.2195, "latitude": 28.6430, "name": "New Delhi Station"},
        "processing_mode": "precomputed",
    }
    res = client.post("/api/v1/generate-routes", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert data["code"] == "OUT_OF_COVERAGE"
    assert "outside" in data["message"].lower() or "bounds" in data["message"].lower()
    assert "coverage_note" in data["details"]


def test_generate_routes_malformed_coordinates_validation(client):
    """Verifies that out-of-range coordinates are rejected by Pydantic schema validation."""
    payload = {
        "source": {"longitude": 200.0, "latitude": 31.7084},
        "destination": {"longitude": 76.9322, "latitude": 31.7084},
    }
    res = client.post("/api/v1/generate-routes", json=payload)
    assert res.status_code == 422


def test_valid_route_generation_and_result_lifecycle(client):
    """End-to-end integration: Submits local Mandi route, polls job, verifies result & GeoJSON."""
    # Source: Mandi Railway Station (76.9322, 31.7084)
    # Destination: Southwest Mandi Sector inside 5x5km grid (approx lon=76.904, lat=31.698)
    # Target in UTM 43N is (681505.0, 3507675.0) which is lon ~76.9155, lat ~31.6898
    payload = {
        "source": {"longitude": 76.9322, "latitude": 31.7084, "name": "Mandi Station"},
        "destination": {"longitude": 76.9155, "latitude": 31.6898, "name": "Mandi Southwest Boundary"},
        "processing_mode": "precomputed",
        "objectives": ["shortest_distance", "lowest_construction_difficulty", "lowest_environmental_impact"],
        "snap_to_valid": True,
        "max_snap_radius_m": 500.0,
    }

    # 1. Submit Job
    res = client.post("/api/v1/generate-routes", json=payload)
    assert res.status_code == 202
    create_data = res.json()
    assert "job_id" in create_data
    job_id = create_data["job_id"]
    assert create_data["status"] == "queued"

    # 2. Poll Status
    max_wait_seconds = 20.0
    start = time.time()
    final_status = None

    while time.time() - start < max_wait_seconds:
        status_res = client.get(f"/api/v1/jobs/{job_id}")
        assert status_res.status_code == 200
        sdata = status_res.json()
        final_status = sdata["status"]
        if final_status in ("completed", "partial_success", "failed"):
            break
        time.sleep(0.5)

    assert final_status in ("completed", "partial_success"), f"Job did not succeed; status={final_status}"

    # 3. Fetch Full Results
    res_result = client.get(f"/api/v1/jobs/{job_id}/result")
    assert res_result.status_code == 200
    rdata = res_result.json()
    assert rdata["job_id"] == job_id
    assert rdata["num_routes"] == 3
    assert len(rdata["routes"]) == 3
    assert "preliminary regional planning corridors" in rdata["engineering_disclaimer"]

    # Verify route properties
    r1 = rdata["routes"][0]
    assert r1["objective"] == "shortest_distance"
    assert r1["length_km"] > 0.0
    assert r1["accumulated_cost"] > 0.0
    assert r1["status"] == "preliminary_candidate_corridor"

    # 4. Fetch GeoJSON
    res_geojson = client.get(f"/api/v1/jobs/{job_id}/routes.geojson")
    assert res_geojson.status_code == 200
    gdata = res_geojson.json()
    assert gdata["type"] == "FeatureCollection"
    assert len(gdata["features"]) == 3
    assert gdata["features"][0]["geometry"]["type"] == "LineString"


def test_job_not_found(client):
    """Verifies that an unknown job returns HTTP 404."""
    res = client.get("/api/v1/jobs/job_nonexistent_12345")
    assert res.status_code == 404
    data = res.json()
    assert data["code"] == "JOB_NOT_FOUND"


def test_cancel_job(client):
    """Verifies cancellation endpoint behavior."""
    # Create a job
    payload = {
        "source": {"longitude": 76.9322, "latitude": 31.7084},
        "destination": {"longitude": 76.9155, "latitude": 31.6898},
        "processing_mode": "precomputed",
    }
    create_res = client.post("/api/v1/generate-routes", json=payload)
    assert create_res.status_code == 202
    job_id = create_res.json()["job_id"]

    # Cancel job
    cancel_res = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert cancel_res.status_code == 200
    cdata = cancel_res.json()
    assert "cancelled" in cdata

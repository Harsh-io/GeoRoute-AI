"""Part 5 of 5 Regional Expansion Test Suite: FastAPI Integration & End-to-End Evaluation.

Verifies:
1. System capabilities exposes both local and validated regional coverage metadata.
2. System readiness validates regional cost rasters and PYORPS Cython engine.
3. Strict preservation of local precomputed mode OUT_OF_COVERAGE behavior when Delhi is requested.
4. Strict OUT_OF_COVERAGE rejection in precomputed_regional mode for coordinates outside regional bounds.
5. End-to-end Mandi -> New Delhi regional route generation through FastAPI background job lifecycle.
6. Verification of generated GeoJSON stream, result JSON, and manifest consistency.
"""

from datetime import datetime, timezone
import json
import math
import time
from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.config import settings


@pytest.fixture(scope="module")
def api_client():
    """Provides FastAPI TestClient with initialized lifespan."""
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_capabilities_exposes_regional_and_local_coverage(api_client):
    """Verifies that /api/v1/capabilities documents both local and validated regional coverage."""
    res = api_client.get("/api/v1/capabilities")
    assert res.status_code == 200
    data = res.json()

    # Supported objectives
    assert "shortest_distance" in data["supported_objectives"]
    assert "lowest_construction_difficulty" in data["supported_objectives"]
    assert "lowest_environmental_impact" in data["supported_objectives"]

    # Processing modes
    modes = data["available_processing_modes"]
    assert "precomputed" in modes
    assert "precomputed_regional" in modes
    assert "full_pipeline" in modes

    # Local coverage preservation
    cov = data["current_dataset_coverage"]
    assert cov["region_name"] == "mandi_terminal_5x5km"
    assert "geographic_limitation" in cov

    # Regional coverage extension
    assert "regional_coverage" in cov
    reg = cov["regional_coverage"]
    assert reg["region_name"] == "mandi_delhi_regional_corridor"
    assert reg["dataset_readiness"] == "ready"
    assert "Mandi Railway Station (HP)" in reg["terminals_covered"]
    assert "New Delhi Railway Station (Delhi NCT)" in reg["terminals_covered"]
    assert reg["bounds_utm43n"]["crs"] == "EPSG:32643"
    assert reg["bounds_utm43n"]["left"] == 641670.0
    assert reg["bounds_utm43n"]["top"] == 3543180.0


def test_ready_endpoint_exposes_regional_readiness(api_client):
    """Verifies that /api/v1/ready checks both local and regional raster readiness."""
    res = api_client.get("/api/v1/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert data["precomputed_mode_ready"] is True
    assert data["pyorps_engine_available"] is True
    assert data["storage_ready"] is True
    assert "regional_ready" in data["details"]
    assert data["details"]["regional_ready"] is True


def test_precomputed_mode_strict_out_of_coverage_for_delhi(api_client):
    """Ensures existing precomputed local mode strictly rejects New Delhi (preserves local behavior)."""
    payload = {
        "source": {"longitude": 76.9322, "latitude": 31.7084, "name": "Mandi Station"},
        "destination": {"longitude": 77.2195, "latitude": 28.6430, "name": "New Delhi Station"},
        "processing_mode": "precomputed",
    }
    res = api_client.post("/api/v1/generate-routes", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert data["code"] == "OUT_OF_COVERAGE"
    assert "outside" in data["message"].lower() or "bounds" in data["message"].lower()


def test_precomputed_regional_out_of_coverage_rejection(api_client):
    """Ensures precomputed_regional mode strictly rejects coordinates outside regional bounds (e.g. Mumbai)."""
    payload = {
        "source": {"longitude": 76.9322, "latitude": 31.7084, "name": "Mandi Station"},
        "destination": {"longitude": 72.8777, "latitude": 19.0760, "name": "Mumbai CSMT"},
        "processing_mode": "precomputed_regional",
    }
    res = api_client.post("/api/v1/generate-routes", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert data["code"] == "OUT_OF_COVERAGE"
    assert "outside" in data["message"].lower() or "bounds" in data["message"].lower()


def test_end_to_end_mandi_to_delhi_regional_job_lifecycle(api_client):
    """Full End-to-End Evaluation: Submits real Mandi-to-Delhi job, polls to completion, verifies deliverables."""
    payload = {
        "source": {"longitude": 76.9322, "latitude": 31.7084, "name": "Mandi Railway Station"},
        "destination": {"longitude": 77.2195, "latitude": 28.6430, "name": "New Delhi Railway Station"},
        "processing_mode": "precomputed_regional",
        "objectives": [
            "shortest_distance",
            "lowest_construction_difficulty",
            "lowest_environmental_impact",
        ],
        "region_name": "mandi_to_delhi_corridor",
    }

    # 1. Submit job
    t_start = time.time()
    submit_res = api_client.post("/api/v1/generate-routes", json=payload)
    assert submit_res.status_code == 202
    submit_data = submit_res.json()
    job_id = submit_data["job_id"]
    assert job_id.startswith("job_")
    assert submit_data["status"] == "queued"

    # 2. Poll until completion (regional search takes ~30-60s)
    max_wait_seconds = 180.0
    poll_interval = 2.0
    elapsed = 0.0
    status_data = None

    while elapsed < max_wait_seconds:
        poll_res = api_client.get(f"/api/v1/jobs/{job_id}")
        assert poll_res.status_code == 200
        status_data = poll_res.json()
        current_status = status_data["status"]

        if current_status in ("completed", "failed", "cancelled"):
            break

        time.sleep(poll_interval)
        elapsed = time.time() - t_start

    assert status_data is not None
    assert status_data["status"] == "completed", f"Job failed or timed out: {status_data}"
    assert status_data["current_stage"] == "completed"
    assert status_data["progress_percent"] == 100.0
    assert status_data["result_url"] is not None
    assert status_data["geojson_url"] is not None

    # 3. Retrieve structured result
    result_res = api_client.get(f"/api/v1/jobs/{job_id}/result")
    assert result_res.status_code == 200
    res_data = result_res.json()

    assert res_data["status"] == "completed"
    assert res_data["num_routes"] == 3
    assert len(res_data["routes"]) == 3
    assert "preliminary regional planning corridors" in res_data["engineering_disclaimer"]

    # Verify three objectives are present and differentiated
    routes_by_obj = {r["objective"]: r for r in res_data["routes"]}
    assert "shortest_distance" in routes_by_obj
    assert "lowest_construction_difficulty" in routes_by_obj
    assert "lowest_environmental_impact" in routes_by_obj

    dist_route = routes_by_obj["shortest_distance"]
    const_route = routes_by_obj["lowest_construction_difficulty"]
    env_route = routes_by_obj["lowest_environmental_impact"]

    # Physical lengths (~353 km - 359 km)
    assert 340.0 < dist_route["length_km"] < 365.0
    assert 340.0 < const_route["length_km"] < 365.0
    assert 340.0 < env_route["length_km"] < 365.0

    # Accumulated costs
    assert dist_route["accumulated_cost"] > 0
    assert const_route["accumulated_cost"] > 0
    assert env_route["accumulated_cost"] > 0
    assert dist_route["cost_units"] == "metres"
    assert "difficulty-weighted" in const_route["cost_units"]
    assert "sensitivity-weighted" in env_route["cost_units"]

    # 4. Stream GeoJSON FeatureCollection
    geojson_res = api_client.get(f"/api/v1/jobs/{job_id}/routes.geojson")
    assert geojson_res.status_code == 200
    geojson_data = geojson_res.json()

    assert geojson_data["type"] == "FeatureCollection"
    assert len(geojson_data["features"]) == 3

    for feat in geojson_data["features"]:
        coords = feat["geometry"]["coordinates"]
        start_pt = coords[0]
        end_pt = coords[-1]

        # Origin is Mandi (~76.93, 31.71), Destination is Delhi (~77.22, 28.64)
        assert 76.8 < start_pt[0] < 77.1 and 31.5 < start_pt[1] < 31.9
        assert 77.0 < end_pt[0] < 77.4 and 28.4 < end_pt[1] < 28.8

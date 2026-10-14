"""Integration and Endpoint Validation Tests for Kangra–Mandi Regional Corridor Routing.

Verifies:
1. Capabilities and readiness endpoints document and validate Kangra–Mandi regional coverage.
2. The user's typographical coordinate (75.4755, 31.2150) is strictly rejected as OUT_OF_COVERAGE.
3. Kangra coordinate requested under local 'precomputed' mode is strictly rejected as OUT_OF_COVERAGE.
4. Valid Kangra Mandir Station and Mandi Station endpoints pass synchronous pre-flight validation.
5. End-to-end background routing for Kangra–Mandi succeeds producing all 3 candidate corridor objectives.
6. GeoJSON artifact download and metrics validation for Kangra–Mandi corridor.
"""

from datetime import datetime, timezone
import json
import time
from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.config import settings
from georoute.routing.endpoint_validator import OutOfCoverageError


@pytest.fixture(scope="module")
def api_client():
    """Provides FastAPI TestClient with initialized lifespan."""
    app = create_app()
    with TestClient(app) as client:
        yield client


def test_capabilities_exposes_kangra_mandi_coverage(api_client):
    """Verifies that /api/v1/capabilities documents Kangra–Mandi regional coverage."""
    res = api_client.get("/api/v1/capabilities")
    assert res.status_code == 200
    data = res.json()

    cov = data["current_dataset_coverage"]
    assert "kangra_mandi_regional_coverage" in cov
    k_cov = cov["kangra_mandi_regional_coverage"]
    assert k_cov["region_name"] == "kangra_to_mandi_corridor"
    assert k_cov["dataset_readiness"] == "ready"
    assert "Kangra Mandir Railway Station (HP)" in k_cov["terminals_covered"]
    assert "Mandi Railway Station (HP)" in k_cov["terminals_covered"]
    assert k_cov["bounds_utm43n"]["crs"] == "EPSG:32643"
    assert k_cov["bounds_utm43n"]["left"] == 603480.0
    assert k_cov["bounds_utm43n"]["bottom"] == 3491070.0
    assert k_cov["bounds_utm43n"]["right"] == 699360.0
    assert k_cov["bounds_utm43n"]["top"] == 3581190.0


def test_ready_endpoint_exposes_kangra_readiness(api_client):
    """Verifies that /api/v1/ready checks Kangra regional cost rasters."""
    res = api_client.get("/api/v1/ready")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ready"
    assert "regional_kangra_ready" in data["details"]
    assert data["details"]["regional_kangra_ready"] is True


def test_typographical_coordinate_strictly_rejected_as_out_of_coverage(api_client):
    """Verifies that the erroneous typographical coordinate (75.4755, 31.2150) is strictly rejected.

    Mathematical diagnosis: The coordinate (75.4755, 31.2150) came from treating DMS
    values 75°47'55" E, 31°21' N as literal decimal numbers, displacing the point ~30.8km west.
    The system MUST strictly reject this with HTTP 422 OUT_OF_COVERAGE, never silently clamp.
    """
    payload = {
        "source": {
            "longitude": 76.9322,
            "latitude": 31.7084,
            "name": "Mandi Railway Station",
        },
        "destination": {
            "longitude": 75.4755,
            "latitude": 31.2150,
            "name": "Erroneous Decimal-DMS Point",
        },
        "processing_mode": "precomputed_regional",
        "region_name": "kangra_to_mandi_corridor",
    }
    res = api_client.post("/api/v1/generate-routes", json=payload)
    assert res.status_code == 422
    err = res.json()
    assert err["code"] == "OUT_OF_COVERAGE"
    assert "out of bounds" in err["message"].lower() or "outside" in err["message"].lower()
    assert "coverage_note" in err.get("details", {})


def test_local_mode_rejects_kangra_as_out_of_coverage(api_client):
    """Verifies that requesting Kangra in local 'precomputed' mode is strictly rejected."""
    payload = {
        "source": {
            "longitude": 76.2693,
            "latitude": 32.0964,
            "name": "Kangra Mandir Railway Station",
        },
        "destination": {
            "longitude": 76.9322,
            "latitude": 31.7084,
            "name": "Mandi Railway Station",
        },
        "processing_mode": "precomputed",
    }
    res = api_client.post("/api/v1/generate-routes", json=payload)
    assert res.status_code == 422
    err = res.json()
    assert err["code"] == "OUT_OF_COVERAGE"


def test_kangra_mandi_pre_flight_validation_succeeds(api_client):
    """Verifies that valid Kangra Mandir Station and Mandi Station pass pre-flight validation."""
    orchestrator = api_client.app.state.orchestrator
    val = orchestrator.pre_validate_endpoints(
        source_coords=(76.2693, 32.0964),
        target_coords=(76.9322, 31.7084),
        regional=True,
        region_name="kangra_to_mandi_corridor",
    )
    assert val is not None
    assert "source" in val
    assert "destination" in val
    # Kangra Mandir Station resolves inside [0..3003, 0..3195]
    src_cell = (val["source"]["row"], val["source"]["col"])
    dst_cell = (val["destination"]["row"], val["destination"]["col"])
    assert 0 <= src_cell[0] < 3004
    assert 0 <= src_cell[1] < 3196
    assert 0 <= dst_cell[0] < 3004
    assert 0 <= dst_cell[1] < 3196


def test_kangra_mandi_end_to_end_job_lifecycle(api_client):
    """Submits Kangra–Mandi routing job and verifies asynchronous completion."""
    payload = {
        "source": {
            "longitude": 76.2693,
            "latitude": 32.0964,
            "name": "Kangra Mandir Railway Station",
        },
        "destination": {
            "longitude": 76.9322,
            "latitude": 31.7084,
            "name": "Mandi Railway Station",
        },
        "processing_mode": "precomputed_regional",
        "region_name": "kangra_to_mandi_corridor",
        "objectives": [
            "shortest_distance",
            "lowest_construction_difficulty",
            "lowest_environmental_impact",
        ],
        "snap_to_valid": True,
        "max_snap_radius_m": 500.0,
        "backend": "pyorps",
    }

    # 1. Submit job
    post_res = api_client.post("/api/v1/generate-routes", json=payload)
    assert post_res.status_code == 202
    job_id = post_res.json()["job_id"]

    # 2. Poll until complete (timeout 45s)
    deadline = time.time() + 45.0
    final_status = None
    while time.time() < deadline:
        status_res = api_client.get(f"/api/v1/jobs/{job_id}")
        assert status_res.status_code == 200
        st = status_res.json()["status"]
        if st in ("completed", "failed", "cancelled"):
            final_status = st
            break
        time.sleep(1.0)

    assert final_status == "completed", f"Job failed or timed out with status: {final_status}"

    # 3. Retrieve final results
    results_res = api_client.get(f"/api/v1/jobs/{job_id}/result")
    assert results_res.status_code == 200
    res_data = results_res.json()

    assert res_data["num_routes"] == 3
    assert len(res_data["routes"]) == 3
    assert res_data["region_name"] == "kangra_to_mandi_corridor"

    objectives_found = [r["objective"] for r in res_data["routes"]]
    assert "shortest_distance" in objectives_found
    assert "lowest_construction_difficulty" in objectives_found
    assert "lowest_environmental_impact" in objectives_found

    # Validate physical length: Kangra-Mandi straight-line ~70km, path ~80-100km
    for r in res_data["routes"]:
        assert 70.0 <= r["length_km"] <= 120.0
        assert r["accumulated_cost"] > 0

    # 4. Stream GeoJSON
    geojson_res = api_client.get(f"/api/v1/jobs/{job_id}/routes.geojson")
    assert geojson_res.status_code == 200
    geojson_data = geojson_res.json()
    assert geojson_data["type"] == "FeatureCollection"
    assert len(geojson_data["features"]) == 3

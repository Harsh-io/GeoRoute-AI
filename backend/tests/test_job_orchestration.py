"""Tests for JobStore persistence, lifecycle transitions, isolation, and JobExecutor limits."""

from pathlib import Path
import pytest

from app.jobs.job_executor import CapacityExceededError, JobExecutor
from app.jobs.job_store import JobRecord, JobStore
from app.services.orchestrator import PipelineOrchestrator


def test_job_store_lifecycle_and_sqlite_recovery(tmp_path):
    """Verifies job creation, status updates, completion, and state recovery across restarts."""
    db_path = tmp_path / "test_jobs.db"
    store = JobStore(db_path=db_path)

    job_id = "test_job_101"
    req_data = {
        "source": {"longitude": 76.9322, "latitude": 31.7084},
        "destination": {"longitude": 76.9155, "latitude": 31.6898},
    }

    # 1. Create job
    rec = store.create_job(job_id=job_id, request_data=req_data)
    assert rec.status == "queued"
    assert rec.current_stage == "queued"

    # 2. Update status
    store.update_job_status(job_id=job_id, status="routing", current_stage="routing", progress_percent=50.0)
    fetched = store.get_job(job_id)
    assert fetched.status == "routing"
    assert fetched.current_stage == "routing"
    assert fetched.progress_percent == 50.0

    # 3. Complete job
    store.complete_job(
        job_id=job_id,
        status="completed",
        result_data={"num_routes": 3},
        artifacts={"routes_geojson": "data/jobs/test_job_101/routes.geojson"},
    )
    completed = store.get_job(job_id)
    assert completed.status == "completed"
    assert completed.progress_percent == 100.0
    assert completed.result_data["num_routes"] == 3

    # 4. Simulate server restart with new store instance
    restarted_store = JobStore(db_path=db_path)
    recovered = restarted_store.get_job(job_id)
    assert recovered is not None
    assert recovered.status == "completed"
    assert recovered.result_data["num_routes"] == 3
    assert "routes_geojson" in recovered.artifacts


def test_job_store_cancellation(tmp_path):
    """Verifies that a job can be cancelled and transitions to terminal cancelled state."""
    db_path = tmp_path / "test_cancel.db"
    store = JobStore(db_path=db_path)

    job_id = "job_to_cancel"
    store.create_job(job_id=job_id, request_data={"dummy": "req"})
    assert store.cancel_job(job_id) is True

    job = store.get_job(job_id)
    assert job.status == "cancelled"

    # Completed job cannot be cancelled
    done_id = "job_done"
    store.create_job(job_id=done_id, request_data={})
    store.complete_job(job_id=done_id, status="completed", result_data={}, artifacts={})
    assert store.cancel_job(done_id) is False


def test_job_executor_capacity_limit(tmp_path, monkeypatch):
    """Verifies that job executor rejects submissions when capacity is exceeded."""
    from app.config import settings
    monkeypatch.setattr(settings, "max_active_jobs", 1)
    monkeypatch.setattr(settings, "max_queued_jobs", 1)

    db_path = tmp_path / "capacity.db"
    store = JobStore(db_path=db_path)
    orchestrator = PipelineOrchestrator(job_store=store)
    executor = JobExecutor(job_store=store, orchestrator=orchestrator)

    # Artificially queue jobs
    store.create_job("j1", {})
    store.create_job("j2", {})

    # Active + Queued = 2 >= (1 + 1)
    with pytest.raises(CapacityExceededError):
        executor.submit_job("j3")

    executor.shutdown(wait=False)

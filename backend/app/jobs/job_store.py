"""SQLite-backed persistent job store for GeoRoute AI."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional


@dataclass
class JobRecord:
    """Represents a persisted job record in SQLite."""

    job_id: str
    status: str
    current_stage: str
    progress_percent: Optional[float]
    processing_mode: str
    created_at: str
    updated_at: str
    request_data: Dict[str, Any]
    source_data: Optional[Dict[str, Any]] = None
    destination_data: Optional[Dict[str, Any]] = None
    result_data: Optional[Dict[str, Any]] = None
    warnings: List[str] = None
    errors: List[str] = None
    artifacts: Dict[str, str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []
        if self.artifacts is None:
            self.artifacts = {}


class JobStore:
    """Thread-safe SQLite persistent job repository."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    current_stage TEXT NOT NULL,
                    progress_percent REAL,
                    processing_mode TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    source_json TEXT,
                    destination_json TEXT,
                    result_json TEXT,
                    warnings_json TEXT,
                    errors_json TEXT,
                    artifacts_json TEXT
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")

    def _fetch_record(self, conn: sqlite3.Connection, job_id: str) -> Optional[JobRecord]:
        cursor = conn.execute("SELECT * FROM jobs WHERE job_id = ?;", (job_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def create_job(
        self,
        job_id: str,
        request_data: Dict[str, Any],
        processing_mode: str = "precomputed",
    ) -> JobRecord:
        now = datetime.now(timezone.utc).isoformat()
        record = JobRecord(
            job_id=job_id,
            status="queued",
            current_stage="queued",
            progress_percent=0.0,
            processing_mode=processing_mode,
            created_at=now,
            updated_at=now,
            request_data=request_data,
            source_data=request_data.get("source"),
            destination_data=request_data.get("destination"),
            warnings=[],
            errors=[],
            artifacts={},
        )
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, status, current_stage, progress_percent, processing_mode,
                    created_at, updated_at, request_json, source_json, destination_json,
                    warnings_json, errors_json, artifacts_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    record.job_id,
                    record.status,
                    record.current_stage,
                    record.progress_percent,
                    record.processing_mode,
                    record.created_at,
                    record.updated_at,
                    json.dumps(record.request_data),
                    json.dumps(record.source_data) if record.source_data else None,
                    json.dumps(record.destination_data) if record.destination_data else None,
                    json.dumps(record.warnings),
                    json.dumps(record.errors),
                    json.dumps(record.artifacts),
                ),
            )
        return record

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        with self._lock, self._get_connection() as conn:
            return self._fetch_record(conn, job_id)

    def update_job_status(
        self,
        job_id: str,
        status: str,
        current_stage: str,
        progress_percent: Optional[float] = None,
        warnings: Optional[List[str]] = None,
        errors: Optional[List[str]] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            job = self._fetch_record(conn, job_id)
            if not job or job.status in ("completed", "failed", "cancelled"):
                return  # Terminal states immutable unless explicitly overridden

            new_warnings = (job.warnings or []) + (warnings or [])
            new_errors = (job.errors or []) + (errors or [])

            conn.execute(
                """
                UPDATE jobs
                SET status = ?, current_stage = ?, progress_percent = ?, updated_at = ?,
                    warnings_json = ?, errors_json = ?
                WHERE job_id = ?;
                """,
                (
                    status,
                    current_stage,
                    progress_percent if progress_percent is not None else job.progress_percent,
                    now,
                    json.dumps(new_warnings),
                    json.dumps(new_errors),
                    job_id,
                ),
            )

    def complete_job(
        self,
        job_id: str,
        status: str,
        result_data: Dict[str, Any],
        artifacts: Dict[str, str],
        warnings: Optional[List[str]] = None,
        errors: Optional[List[str]] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            job = self._fetch_record(conn, job_id)
            if not job or job.status == "cancelled":
                return

            all_warnings = (job.warnings or []) + (warnings or [])
            all_errors = (job.errors or []) + (errors or [])
            all_artifacts = {**(job.artifacts or {}), **artifacts}

            conn.execute(
                """
                UPDATE jobs
                SET status = ?, current_stage = 'completed', progress_percent = 100.0,
                    updated_at = ?, result_json = ?, warnings_json = ?, errors_json = ?,
                    artifacts_json = ?
                WHERE job_id = ?;
                """,
                (
                    status,
                    now,
                    json.dumps(result_data),
                    json.dumps(all_warnings),
                    json.dumps(all_errors),
                    json.dumps(all_artifacts),
                    job_id,
                ),
            )

    def fail_job(
        self,
        job_id: str,
        error_message: str,
        stage: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            job = self._fetch_record(conn, job_id)
            if not job or job.status == "cancelled":
                return

            all_errors = (job.errors or []) + [error_message]
            conn.execute(
                """
                UPDATE jobs
                SET status = 'failed', current_stage = ?, updated_at = ?, errors_json = ?
                WHERE job_id = ?;
                """,
                (stage or job.current_stage, now, json.dumps(all_errors), job_id),
            )

    def cancel_job(self, job_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._get_connection() as conn:
            job = self._fetch_record(conn, job_id)
            if not job or job.status in ("completed", "failed", "cancelled"):
                return False

            conn.execute(
                """
                UPDATE jobs
                SET status = 'cancelled', current_stage = 'cancelled', updated_at = ?
                WHERE job_id = ?;
                """,
                (now, job_id),
            )
            return True

    def count_active_jobs(self) -> int:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM jobs
                WHERE status IN ('validating', 'downloading', 'preprocessing',
                                 'extracting_features', 'building_cost_surfaces',
                                 'routing', 'validating_routes');
                """
            )
            return cursor.fetchone()[0]

    def count_queued_jobs(self) -> int:
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued';")
            return cursor.fetchone()[0]

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            status=row["status"],
            current_stage=row["current_stage"],
            progress_percent=row["progress_percent"],
            processing_mode=row["processing_mode"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            request_data=json.loads(row["request_json"]),
            source_data=json.loads(row["source_json"]) if row["source_json"] else None,
            destination_data=json.loads(row["destination_json"]) if row["destination_json"] else None,
            result_data=json.loads(row["result_json"]) if row["result_json"] else None,
            warnings=json.loads(row["warnings_json"]) if row["warnings_json"] else [],
            errors=json.loads(row["errors_json"]) if row["errors_json"] else [],
            artifacts=json.loads(row["artifacts_json"]) if row["artifacts_json"] else {},
        )

"""Thread-pool background job executor with bounded concurrency and cooperative cancellation."""

from concurrent.futures import ThreadPoolExecutor
import logging
import threading
from typing import Optional, Set

from app.config import settings
from app.jobs.job_store import JobStore
from app.services.orchestrator import PipelineOrchestrator

logger = logging.getLogger("georoute.app.executor")


class CapacityExceededError(Exception):
    """Raised when job queue capacity is saturated."""
    pass


class JobExecutor:
    """Manages background job scheduling and execution threads."""

    def __init__(self, job_store: JobStore, orchestrator: PipelineOrchestrator):
        self.job_store = job_store
        self.orchestrator = orchestrator
        self.max_workers = settings.max_active_jobs
        self.max_queued = settings.max_queued_jobs
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="georoute_worker_")
        self._cancelled_jobs: Set[str] = set()
        self._lock = threading.Lock()

    def submit_job(self, job_id: str) -> None:
        """Schedules a job for execution if queue capacity permits.

        Raises:
            CapacityExceededError: If queued jobs exceed configured limit.
        """
        with self._lock:
            queued_count = self.job_store.count_queued_jobs()
            active_count = self.job_store.count_active_jobs()
            if (queued_count + active_count) >= (self.max_workers + self.max_queued):
                raise CapacityExceededError(
                    f"Job capacity exceeded (active={active_count}, queued={queued_count}, limit={self.max_workers + self.max_queued})."
                )

        logger.info(f"Submitting job '{job_id}' to thread pool executor")
        self._executor.submit(self._worker_run, job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Requests cooperative cancellation of a job."""
        with self._lock:
            self._cancelled_jobs.add(job_id)
        return self.job_store.cancel_job(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        """Checks if a job has received a cancellation request."""
        with self._lock:
            return job_id in self._cancelled_jobs

    def _worker_run(self, job_id: str) -> None:
        """Worker thread entry point."""
        try:
            if self.is_cancelled(job_id):
                logger.info(f"Job '{job_id}' cancelled before execution began.")
                return

            self.orchestrator.execute_job(
                job_id=job_id,
                is_cancelled_check=lambda: self.is_cancelled(job_id),
            )
        except Exception as e:
            logger.exception(f"Unhandled error in worker thread for job '{job_id}': {e}")
            self.job_store.fail_job(job_id, error_message=f"Worker exception: {e}")
        finally:
            with self._lock:
                self._cancelled_jobs.discard(job_id)

    def shutdown(self, wait: bool = True) -> None:
        """Shuts down background executor pool."""
        logger.info("Shutting down JobExecutor thread pool...")
        self._executor.shutdown(wait=wait, cancel_futures=True)

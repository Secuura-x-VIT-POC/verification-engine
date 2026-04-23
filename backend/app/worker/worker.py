from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
import uuid

from ..db.database import SessionLocal, init_db
from ..workflow.job_queue import (
    dequeue_job,
    mark_job_done,
    mark_job_failed,
    mark_job_skipped,
    mark_stale_processing_jobs_failed,
    update_job_heartbeat,
)
from ..workflow.service import acquire_lease, mark_stale_sessions, run_worker_pipeline


LOGGER = logging.getLogger(__name__)


class JobHeartbeat:
    def __init__(self, job_id: str, worker_id: str, interval_seconds: int) -> None:
        self.job_id = job_id
        self.worker_id = worker_id
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"verification-job-heartbeat-{job_id}",
            daemon=True,
        )

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)
        return False

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            db = SessionLocal()
            try:
                if not update_job_heartbeat(db, self.job_id, self.worker_id):
                    LOGGER.warning(
                        "JOB_HEARTBEAT_REJECTED job_id=%s worker_id=%s",
                        self.job_id,
                        self.worker_id,
                    )
                    return
            except Exception:
                LOGGER.warning(
                    "JOB_HEARTBEAT_FAILED job_id=%s worker_id=%s",
                    self.job_id,
                    self.worker_id,
                    exc_info=True,
                )
                return
            finally:
                db.close()


def run_worker(
    *,
    worker_id: str | None = None,
    poll_interval_seconds: float = 2.0,
    heartbeat_interval_seconds: int = 10,
    stale_session_timeout_seconds: int = 60,
    stale_job_timeout_seconds: int = 300,
    stop_event: threading.Event | None = None,
) -> None:
    resolved_worker_id = worker_id or f"worker-{uuid.uuid4()}"
    stop = stop_event or threading.Event()
    LOGGER.info("WORKER_STARTED worker_id=%s", resolved_worker_id)

    while not stop.is_set():
        _mark_stale_work(
            stale_session_timeout_seconds=stale_session_timeout_seconds,
            stale_job_timeout_seconds=stale_job_timeout_seconds,
        )

        db = SessionLocal()
        job = None
        try:
            job = dequeue_job(db, resolved_worker_id)
            if job is None:
                db.close()
                stop.wait(poll_interval_seconds)
                continue

            LOGGER.info(
                "JOB_DEQUEUED job_id=%s session_id=%s worker_id=%s",
                job.id,
                job.session_id,
                resolved_worker_id,
            )

            if not acquire_lease(db, job.session_id, resolved_worker_id):
                mark_job_skipped(db, job.id, "Session lease could not be acquired")
                LOGGER.info(
                    "JOB_SKIPPED_LEASE_REJECTED job_id=%s session_id=%s worker_id=%s",
                    job.id,
                    job.session_id,
                    resolved_worker_id,
                )
                continue

            with JobHeartbeat(job.id, resolved_worker_id, heartbeat_interval_seconds):
                run_worker_pipeline(
                    db,
                    job.session_id,
                    resolved_worker_id,
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                )
            mark_job_done(db, job.id)
            LOGGER.info(
                "JOB_DONE job_id=%s session_id=%s worker_id=%s",
                job.id,
                job.session_id,
                resolved_worker_id,
            )
        except Exception as exc:
            LOGGER.exception("JOB_FAILED worker_id=%s", resolved_worker_id)
            try:
                if job is not None:
                    mark_job_failed(db, job.id, str(exc))
            except Exception:
                LOGGER.warning("JOB_FAILURE_MARK_FAILED worker_id=%s", resolved_worker_id, exc_info=True)
        finally:
            db.close()

    LOGGER.info("WORKER_STOPPED worker_id=%s", resolved_worker_id)


def _mark_stale_work(
    *,
    stale_session_timeout_seconds: int,
    stale_job_timeout_seconds: int,
) -> None:
    db = SessionLocal()
    try:
        abandoned_sessions = mark_stale_sessions(db, timeout_seconds=stale_session_timeout_seconds)
        failed_jobs = mark_stale_processing_jobs_failed(db, timeout_seconds=stale_job_timeout_seconds)
        if abandoned_sessions or failed_jobs:
            LOGGER.info(
                "STALE_WORK_MARKED abandoned_sessions=%s failed_jobs=%s",
                abandoned_sessions,
                failed_jobs,
            )
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the verification worker process.")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--heartbeat-interval-seconds", type=int, default=10)
    parser.add_argument("--stale-session-timeout-seconds", type=int, default=60)
    parser.add_argument("--stale-job-timeout-seconds", type=int, default=300)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    init_db()

    stop_event = threading.Event()

    def _stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    run_worker(
        worker_id=args.worker_id,
        poll_interval_seconds=args.poll_interval_seconds,
        heartbeat_interval_seconds=args.heartbeat_interval_seconds,
        stale_session_timeout_seconds=args.stale_session_timeout_seconds,
        stale_job_timeout_seconds=args.stale_job_timeout_seconds,
        stop_event=stop_event,
    )


if __name__ == "__main__":
    main()

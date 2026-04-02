from __future__ import annotations

import logging
import threading
import uuid
from contextlib import nullcontext
from typing import Callable

from ..orchestrator.orchestrator import trigger_processing
from ..trust.trust_engine import evaluate_trust
from . import repository


LOGGER = logging.getLogger(__name__)

WORKER_PHASE_EXTRACTING = "EXTRACTING"
WORKER_PHASE_GROUNDING = "GROUNDING"
WORKER_PHASE_CONNECTOR_EVAL = "CONNECTOR_EVAL"
WORKER_PHASE_TRUST_SCORING = "TRUST_SCORING"

STATE_MAP = {
    "GREEN": "VERIFIED_GREEN",
    "AMBER": "VERIFIED_AMBER",
    "RED": "VERIFIED_RED",
}


def generate_worker_id() -> str:
    return str(uuid.uuid4())


def start_verification(
    conn,
    session_id: str,
    *,
    worker_id: str | None = None,
    max_retries: int = 3,
    extraction_stage: Callable | None = None,
    grounding_stage: Callable | None = None,
    connector_stage: Callable | None = None,
    policy_loader: Callable | None = None,
    heartbeat_interval_seconds: int = 10,
) -> str:
    current_worker_id = worker_id or generate_worker_id()
    result = trigger_processing(
        conn,
        session_id,
        current_worker_id,
        max_retries=max_retries,
    )

    if result != "STARTED":
        return result

    try:
        run_worker_pipeline(
            conn,
            session_id,
            current_worker_id,
            extraction_stage=extraction_stage,
            grounding_stage=grounding_stage,
            connector_stage=connector_stage,
            policy_loader=policy_loader,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )
    except Exception:
        return "FAILED"

    return result


def run_worker_pipeline(
    conn,
    session_id: str,
    worker_id: str,
    *,
    extraction_stage: Callable | None = None,
    grounding_stage: Callable | None = None,
    connector_stage: Callable | None = None,
    policy_loader: Callable | None = None,
    heartbeat_interval_seconds: int = 10,
) -> dict:
    extraction = extraction_stage or _default_extraction_stage
    grounding = grounding_stage or _default_grounding_stage
    connector_eval = connector_stage or _default_connector_stage
    load_policy = policy_loader or _default_policy_loader

    heartbeat_runner = (
        _HeartbeatRunner(conn, session_id, worker_id, heartbeat_interval_seconds)
        if heartbeat_interval_seconds and heartbeat_interval_seconds > 0
        else nullcontext()
    )

    try:
        with heartbeat_runner:
            update_worker_phase(conn, session_id, worker_id, WORKER_PHASE_EXTRACTING)
            extraction_data = extraction(conn, session_id, worker_id)

            update_worker_phase(conn, session_id, worker_id, WORKER_PHASE_GROUNDING)
            grounded_data = grounding(conn, session_id, worker_id, extraction_data)

            update_worker_phase(conn, session_id, worker_id, WORKER_PHASE_CONNECTOR_EVAL)
            connector_responses = connector_eval(conn, session_id, worker_id, grounded_data)

            update_worker_phase(conn, session_id, worker_id, WORKER_PHASE_TRUST_SCORING)
            policy = load_policy(conn, session_id, worker_id, grounded_data)

            trust_result = evaluate_trust(policy, grounded_data, connector_responses)
            complete_processing(
                conn,
                session_id,
                trust_result["outcome"],
                trust_result["reason_codes"],
                trust_result["connector_ids"],
            )
            return trust_result
    except Exception:
        complete_processing(
            conn,
            session_id,
            "RED",
            ["WORKFLOW_EXECUTION_FAILED"],
            [],
        )
        raise


def update_worker_phase(conn, session_id: str, worker_id: str, worker_phase: str) -> None:
    repository.update_worker_phase(conn, session_id, worker_id, worker_phase)
    conn.commit()


def update_heartbeat(conn, session_id: str, worker_id: str) -> None:
    repository.update_heartbeat(conn, session_id, worker_id)
    conn.commit()


def mark_stale_sessions(conn, timeout_seconds: int = 60) -> int:
    updated_rows = repository.mark_stale_sessions(conn, timeout_seconds=timeout_seconds)
    conn.commit()
    return updated_rows


def complete_processing(
    conn,
    session_id: str,
    outcome: str,
    reason_codes: list[str],
    connector_ids: list[str],
) -> None:
    repository.complete_processing(
        conn,
        session_id,
        STATE_MAP[outcome],
        outcome,
        reason_codes,
        connector_ids,
    )
    conn.commit()


def _default_extraction_stage(conn, session_id: str, worker_id: str) -> dict:
    return {}


def _default_grounding_stage(
    conn,
    session_id: str,
    worker_id: str,
    extraction_data: dict,
) -> dict:
    return extraction_data


def _default_connector_stage(
    conn,
    session_id: str,
    worker_id: str,
    grounded_data: dict,
) -> list[dict]:
    return []


def _default_policy_loader(
    conn,
    session_id: str,
    worker_id: str,
    grounded_data: dict,
) -> dict:
    return {}


class _HeartbeatRunner:
    def __init__(
        self,
        conn,
        session_id: str,
        worker_id: str,
        interval_seconds: int,
    ) -> None:
        self.conn = conn
        self.session_id = session_id
        self.worker_id = worker_id
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"verification-heartbeat-{session_id}",
            daemon=True,
        )

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)
        return False

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                update_heartbeat(self.conn, self.session_id, self.worker_id)
            except Exception:
                LOGGER.warning(
                    "Failed to update heartbeat for session %s",
                    self.session_id,
                    exc_info=True,
                )
                return

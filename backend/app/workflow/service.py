from __future__ import annotations

import logging
import inspect
import random
import threading
import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Callable

from ..trust.trust_engine import evaluate_trust
from .failures import FailureClassification, WorkflowProcessingError, classify_failure
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


def acquire_lease(conn, session_id: str, worker_id: str) -> bool:
    acquired = repository.acquire_lease(conn, session_id, worker_id)
    if acquired:
        conn.commit()
        LOGGER.info("LEASE_ACQUIRED session_id=%s worker_id=%s", session_id, worker_id)
        return True

    _safe_rollback(conn)
    LOGGER.info("LEASE_REJECTED session_id=%s worker_id=%s", session_id, worker_id)
    return False


def call_connector_with_retry(connector_fn, payload: dict, policy: dict | None = None) -> dict:
    policy = policy or {}
    connector_id = str(policy.get("connector_id") or getattr(connector_fn, "__name__", "connector"))
    assurance_class = str(policy.get("assurance_class", "HIGH"))
    max_retries = int(policy.get("max_retries", 2))
    max_attempts = max_retries + 1

    for attempt in range(1, max_attempts + 1):
        LOGGER.info("CONNECTOR_ATTEMPT connector_id=%s attempt=%s", connector_id, attempt)
        try:
            raw_result = connector_fn(payload)
            return _normalize_connector_result(raw_result, connector_id, assurance_class)
        except Exception as exc:
            if attempt >= max_attempts:
                LOGGER.warning(
                    "CONNECTOR_TIMEOUT connector_id=%s attempts=%s error=%s",
                    connector_id,
                    attempt,
                    exc,
                )
                return {
                    "connector_id": connector_id,
                    "status": "TIMEOUT",
                    "reason_codes": ["CONNECTOR_TIMEOUT"],
                    "matched_claims": {},
                    "mismatched_claims": {},
                    "assurance_class": assurance_class,
                    "source_timestamp": datetime.now(timezone.utc).isoformat(),
                    "technical_state": "TIMEOUT",
                }

            LOGGER.info("CONNECTOR_RETRY connector_id=%s next_attempt=%s", connector_id, attempt + 1)
            time.sleep(random.uniform(0.2, 0.5))


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
    from ..orchestrator.orchestrator import trigger_processing

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
    failure_type = "unknown_processing_error"

    heartbeat_runner = (
        _HeartbeatRunner(conn, session_id, worker_id, heartbeat_interval_seconds)
        if heartbeat_interval_seconds and heartbeat_interval_seconds > 0
        else nullcontext()
    )

    try:
        with heartbeat_runner:
            update_worker_phase(conn, session_id, worker_id, WORKER_PHASE_EXTRACTING)
            failure_type = "extraction_crash"
            extraction_data = extraction(conn, session_id, worker_id)

            update_worker_phase(conn, session_id, worker_id, WORKER_PHASE_GROUNDING)
            failure_type = "extraction_crash"
            grounded_data = grounding(conn, session_id, worker_id, extraction_data)

            update_worker_phase(conn, session_id, worker_id, WORKER_PHASE_CONNECTOR_EVAL)
            policy = load_policy(conn, session_id, worker_id, grounded_data)
            failure_type = "transient_connector_error"
            connector_responses = _invoke_connector_stage(
                connector_eval,
                conn,
                session_id,
                worker_id,
                grounded_data,
                policy,
            )

            update_worker_phase(conn, session_id, worker_id, WORKER_PHASE_TRUST_SCORING)
            failure_type = "unknown_processing_error"
            trust_result = evaluate_trust(grounded_data, connector_responses, policy)
            complete_processing(
                conn,
                session_id,
                trust_result["outcome"],
                trust_result["reason_codes"],
                trust_result["connector_ids"],
            )
            return trust_result
    except Exception as exc:
        workflow_error = exc
        if not isinstance(exc, WorkflowProcessingError):
            workflow_error = WorkflowProcessingError(
                failure_type,
                message=str(exc),
            )
        handle_processing_failure(
            conn,
            session_id,
            workflow_error,
        )
        raise


def update_worker_phase(conn, session_id: str, worker_id: str, worker_phase: str) -> None:
    repository.update_worker_phase(conn, session_id, worker_id, worker_phase)
    conn.commit()


def update_heartbeat(conn, session_id: str, worker_id: str) -> bool:
    updated_rows = repository.update_heartbeat(conn, session_id, worker_id)
    conn.commit()
    if updated_rows:
        LOGGER.info("HEARTBEAT_UPDATED session_id=%s worker_id=%s", session_id, worker_id)
        return True
    return False


def mark_stale_sessions(conn, timeout_seconds: int = 60) -> int:
    updated_rows = repository.mark_stale_sessions(conn, timeout_seconds=timeout_seconds)
    conn.commit()
    if updated_rows:
        LOGGER.info("STALE_SESSION_MARKED count=%s timeout_seconds=%s", updated_rows, timeout_seconds)
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


def handle_processing_failure(
    conn,
    session_id: str,
    error: Exception,
    *,
    extra_values: dict | None = None,
    context: dict | None = None,
) -> FailureClassification:
    resolved_context = dict(context or {})
    if isinstance(error, WorkflowProcessingError):
        error_type = error.error_type
        resolved_context.update(error.context)
    else:
        error_type = "unknown_processing_error"

    classification = classify_failure(error_type, resolved_context)
    LOGGER.error(
        "PROCESSING_FAILED session_id=%s error_type=%s retriable=%s",
        session_id,
        classification.error_type,
        classification.retriable,
    )
    repository.fail_processing(
        conn,
        session_id,
        classification.state,
        classification.reason_codes,
        extra_values=extra_values,
    )
    conn.commit()
    return classification


def _safe_rollback(conn) -> None:
    rollback = getattr(conn, "rollback", None)
    if callable(rollback):
        rollback()


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
    policy: dict | None = None,
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
        if not update_heartbeat(self.conn, self.session_id, self.worker_id):
            raise RuntimeError(
                f"Failed to initialize heartbeat for session {self.session_id}"
            )
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
                if not update_heartbeat(self.conn, self.session_id, self.worker_id):
                    LOGGER.warning(
                        "Heartbeat rejected for session %s worker %s",
                        self.session_id,
                        self.worker_id,
                    )
                    return
            except Exception:
                LOGGER.warning(
                    "Failed to update heartbeat for session %s",
                    self.session_id,
                    exc_info=True,
                )
                return


def _normalize_connector_result(raw_result: dict, connector_id: str, assurance_class: str) -> dict:
    normalized = dict(raw_result)
    normalized["connector_id"] = str(raw_result.get("connector_id") or connector_id)
    normalized["assurance_class"] = str(raw_result.get("assurance_class") or assurance_class)
    normalized["reason_codes"] = list(raw_result.get("reason_codes") or [])
    normalized["matched_claims"] = dict(raw_result.get("matched_claims") or {})
    normalized["mismatched_claims"] = dict(raw_result.get("mismatched_claims") or {})
    normalized["technical_state"] = str(raw_result.get("technical_state") or "SUCCESS")
    normalized["source_timestamp"] = raw_result.get("source_timestamp") or datetime.now(timezone.utc).isoformat()

    raw_status = str(raw_result.get("status") or "").upper()
    if raw_status == "VERIFIED":
        normalized["status"] = "VERIFIED"
    elif normalized["mismatched_claims"] or raw_status in {"NOT_VERIFIED", "INVALID", "REVOKED", "MISMATCH"}:
        normalized["status"] = "MISMATCH"
    else:
        normalized["status"] = "ERROR"
        if "CONNECTOR_ERROR" not in normalized["reason_codes"]:
            normalized["reason_codes"].append("CONNECTOR_ERROR")

    return normalized


def _invoke_connector_stage(
    connector_eval,
    conn,
    session_id: str,
    worker_id: str,
    grounded_data: dict,
    policy: dict,
) -> list[dict]:
    try:
        parameter_count = len(inspect.signature(connector_eval).parameters)
    except (TypeError, ValueError):
        parameter_count = 5

    if parameter_count >= 5:
        return connector_eval(conn, session_id, worker_id, grounded_data, policy)
    return connector_eval(conn, session_id, worker_id, grounded_data)

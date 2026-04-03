import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.orchestrator.orchestrator import trigger_processing
from backend.app.db.database import Base
from backend.app.sessions.constants import SessionState
from backend.app.sessions.models import Session as SessionModel
from backend.app.workflow import repository
from backend.app.workflow.runtime import run_verification
from backend.app.workflow.state_machine import InvalidStateTransitionError, validate_transition
from backend.app.workflow.service import (
    WORKER_PHASE_CONNECTOR_EVAL,
    WORKER_PHASE_EXTRACTING,
    WORKER_PHASE_GROUNDING,
    WORKER_PHASE_TRUST_SCORING,
    acquire_lease,
    call_connector_with_retry,
    mark_stale_sessions,
    run_worker_pipeline,
    start_verification,
    update_heartbeat,
)


class StateMachineTests(unittest.TestCase):
    def test_validate_transition_allows_known_valid_transition(self):
        validate_transition(
            SessionState.UPLOADED_PENDING_REVIEW,
            SessionState.VERIFYING,
        )

    def test_validate_transition_allows_verifying_to_failed_purged(self):
        validate_transition(
            SessionState.VERIFYING,
            SessionState.FAILED_PURGED,
        )

    def test_validate_transition_rejects_invalid_transition(self):
        with self.assertRaises(InvalidStateTransitionError):
            validate_transition(
                SessionState.CREATED,
                SessionState.VERIFYING,
            )


class TriggerProcessingTests(unittest.TestCase):
    def test_trigger_processing_starts_when_lease_is_acquired(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.service.acquire_lease",
            return_value=True,
        ) as acquire_mock:
            result = trigger_processing(conn, "session-1", "worker-1")

        self.assertEqual(result, "STARTED")
        acquire_mock.assert_called_once_with(conn, "session-1", "worker-1")
        conn.rollback.assert_not_called()

    def test_trigger_processing_returns_no_op_when_lease_is_rejected(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.service.acquire_lease",
            return_value=False,
        ) as acquire_mock:
            result = trigger_processing(conn, "session-1", "worker-1")

        self.assertEqual(result, "NO_OP")
        acquire_mock.assert_called_once_with(conn, "session-1", "worker-1")
        conn.rollback.assert_not_called()

    def test_trigger_processing_does_not_retry_after_rejected_lease(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.service.acquire_lease",
            return_value=False,
        ) as acquire_mock:
            result = trigger_processing(conn, "session-1", "worker-1", max_retries=2)

        self.assertEqual(result, "NO_OP")
        acquire_mock.assert_called_once_with(conn, "session-1", "worker-1")
        conn.rollback.assert_not_called()


class LeaseServiceTests(unittest.TestCase):
    def test_acquire_lease_commits_and_logs_when_successful(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.repository.acquire_lease",
            return_value=True,
        ):
            with self.assertLogs("backend.app.workflow.service", level="INFO") as logs:
                result = acquire_lease(conn, "session-1", "worker-1")

        self.assertTrue(result)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
        self.assertTrue(any("LEASE_ACQUIRED" in entry for entry in logs.output))

    def test_acquire_lease_rolls_back_and_logs_when_rejected(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.repository.acquire_lease",
            return_value=False,
        ):
            with self.assertLogs("backend.app.workflow.service", level="INFO") as logs:
                result = acquire_lease(conn, "session-1", "worker-1")

        self.assertFalse(result)
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
        self.assertTrue(any("LEASE_REJECTED" in entry for entry in logs.output))


class WorkflowServiceTests(unittest.TestCase):
    def test_call_connector_with_retry_succeeds_on_first_try(self):
        connector_fn = MagicMock(
            return_value={
                "connector_id": "vit_registry",
                "status": "VERIFIED",
                "reason_codes": ["REGISTRY_MATCH"],
                "matched_claims": {"name": "Kanak"},
                "mismatched_claims": {},
            }
        )

        result = call_connector_with_retry(
            connector_fn,
            {"name": "Kanak"},
            {"connector_id": "vit_registry", "assurance_class": "HIGH"},
        )

        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(connector_fn.call_count, 1)

    def test_call_connector_with_retry_succeeds_after_retry(self):
        connector_fn = MagicMock(
            side_effect=[
                RuntimeError("temporary failure"),
                {
                    "connector_id": "vit_registry",
                    "status": "VERIFIED",
                    "reason_codes": ["REGISTRY_MATCH"],
                    "matched_claims": {"name": "Kanak"},
                    "mismatched_claims": {},
                },
            ]
        )

        with patch("backend.app.workflow.service.random.uniform", return_value=0.2), patch(
            "backend.app.workflow.service.time.sleep"
        ) as sleep_mock:
            result = call_connector_with_retry(
                connector_fn,
                {"name": "Kanak"},
                {"connector_id": "vit_registry", "assurance_class": "HIGH"},
            )

        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(connector_fn.call_count, 2)
        sleep_mock.assert_called_once_with(0.2)

    def test_call_connector_with_retry_returns_timeout_after_retries(self):
        connector_fn = MagicMock(side_effect=RuntimeError("connector offline"))

        with patch("backend.app.workflow.service.random.uniform", return_value=0.2), patch(
            "backend.app.workflow.service.time.sleep"
        ) as sleep_mock:
            result = call_connector_with_retry(
                connector_fn,
                {"name": "Kanak"},
                {"connector_id": "vit_registry", "assurance_class": "HIGH"},
            )

        self.assertEqual(result["status"], "TIMEOUT")
        self.assertEqual(result["assurance_class"], "HIGH")
        self.assertEqual(connector_fn.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_call_connector_with_retry_respects_retry_count(self):
        connector_fn = MagicMock(side_effect=RuntimeError("connector offline"))

        with patch("backend.app.workflow.service.random.uniform", return_value=0.3), patch(
            "backend.app.workflow.service.time.sleep"
        ) as sleep_mock:
            result = call_connector_with_retry(
                connector_fn,
                {"name": "Kanak"},
                {
                    "connector_id": "vit_registry",
                    "assurance_class": "OPTIONAL",
                    "max_retries": 1,
                },
            )

        self.assertEqual(result["status"], "TIMEOUT")
        self.assertEqual(connector_fn.call_count, 2)
        sleep_mock.assert_called_once_with(0.3)

    def test_start_verification_runs_pipeline_after_start(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.trigger_processing",
            return_value="STARTED",
        ) as trigger_mock, patch(
            "backend.app.workflow.service.run_worker_pipeline"
        ) as pipeline_mock:
            result = start_verification(
                conn,
                "session-1",
                worker_id="worker-1",
                heartbeat_interval_seconds=0,
            )

        self.assertEqual(result, "STARTED")
        trigger_mock.assert_called_once_with(
            conn,
            "session-1",
            "worker-1",
            max_retries=3,
        )
        pipeline_mock.assert_called_once()

    def test_run_worker_pipeline_advances_all_phases_and_completes(self):
        conn = MagicMock()
        extraction_data = {
            "is_unsafe": False,
            "critical_tamper_signal": False,
            "fields": [{"name": "name", "is_mandatory": True, "is_grounded": True}],
        }
        connector_responses = [
            {
                "connector_id": "vit_registry",
                "status": "VERIFIED",
                "assurance_class": "HIGH",
                "mismatched_claims": [],
            }
        ]
        policy = {
            "requires_high_assurance": True,
            "required_connectors": ["vit_registry"],
        }

        with patch("backend.app.workflow.service.update_worker_phase") as phase_mock, patch(
            "backend.app.workflow.service.complete_processing"
        ) as complete_mock:
            result = run_worker_pipeline(
                conn,
                "session-1",
                "worker-1",
                extraction_stage=lambda *_: extraction_data,
                grounding_stage=lambda *_: extraction_data,
                connector_stage=lambda *_: connector_responses,
                policy_loader=lambda *_: policy,
                heartbeat_interval_seconds=0,
            )

        self.assertEqual(result["outcome"], "GREEN")
        self.assertEqual(
            phase_mock.call_args_list,
            [
                call(conn, "session-1", "worker-1", WORKER_PHASE_EXTRACTING),
                call(conn, "session-1", "worker-1", WORKER_PHASE_GROUNDING),
                call(conn, "session-1", "worker-1", WORKER_PHASE_CONNECTOR_EVAL),
                call(conn, "session-1", "worker-1", WORKER_PHASE_TRUST_SCORING),
            ],
        )
        complete_mock.assert_called_once()
        complete_args = complete_mock.call_args.args
        self.assertEqual(complete_args[0], conn)
        self.assertEqual(complete_args[1], "session-1")
        self.assertEqual(complete_args[2], "GREEN")
        self.assertEqual(set(complete_args[3]), {"CONNECTOR_VERIFIED"})
        self.assertEqual(complete_args[4], ["vit_registry"])

    def test_run_worker_pipeline_handles_failure_when_a_stage_fails(self):
        conn = MagicMock()

        with patch("backend.app.workflow.service.handle_processing_failure") as failure_mock:
            with self.assertRaises(RuntimeError):
                run_worker_pipeline(
                    conn,
                    "session-1",
                    "worker-1",
                    extraction_stage=lambda *_: (_ for _ in ()).throw(RuntimeError("boom")),
                    heartbeat_interval_seconds=0,
                )

        failure_mock.assert_called_once()

    def test_mark_stale_sessions_commits_and_returns_updated_count(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.repository.mark_stale_sessions",
            return_value=3,
        ) as stale_mock, self.assertLogs("backend.app.workflow.service", level="INFO") as logs:
            result = mark_stale_sessions(conn, timeout_seconds=75)

        self.assertEqual(result, 3)
        stale_mock.assert_called_once_with(conn, timeout_seconds=75)
        conn.commit.assert_called_once()
        self.assertTrue(any("STALE_SESSION_MARKED" in entry for entry in logs.output))

    def test_update_heartbeat_commits_and_logs_when_worker_matches(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.repository.update_heartbeat",
            return_value=1,
        ), self.assertLogs("backend.app.workflow.service", level="INFO") as logs:
            result = update_heartbeat(conn, "session-1", "worker-1")

        self.assertTrue(result)
        conn.commit.assert_called_once()
        self.assertTrue(any("HEARTBEAT_UPDATED" in entry for entry in logs.output))

    def test_update_heartbeat_returns_false_when_worker_does_not_match(self):
        conn = MagicMock()

        with patch(
            "backend.app.workflow.service.repository.update_heartbeat",
            return_value=0,
        ):
            result = update_heartbeat(conn, "session-1", "wrong-worker")

        self.assertFalse(result)
        conn.commit.assert_called_once()


class WorkflowRepositoryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_repository_update_heartbeat_updates_only_matching_worker(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="session-1",
            user_id="user-1",
            status=SessionState.VERIFYING,
            lease_id="worker-1",
            lease_holder_id="worker-1",
        )
        db.add(session)
        db.commit()

        updated_rows = repository.update_heartbeat(db, "session-1", "worker-1")
        db.commit()
        db.refresh(session)

        self.assertEqual(updated_rows, 1)
        self.assertIsNotNone(session.heartbeat_at)
        db.close()

    def test_repository_update_heartbeat_rejects_wrong_worker(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="session-2",
            user_id="user-2",
            status=SessionState.VERIFYING,
            lease_id="worker-1",
            lease_holder_id="worker-1",
        )
        db.add(session)
        db.commit()

        updated_rows = repository.update_heartbeat(db, "session-2", "wrong-worker")
        db.commit()
        db.refresh(session)

        self.assertEqual(updated_rows, 0)
        self.assertIsNone(session.heartbeat_at)
        db.close()

    def test_repository_mark_stale_sessions_transitions_only_stale_rows(self):
        db = self.SessionLocal()
        stale_session = SessionModel(
            id="stale-session",
            user_id="user-1",
            status=SessionState.VERIFYING,
            lease_id="worker-stale",
            lease_holder_id="worker-stale",
            heartbeat_at=datetime.utcnow() - timedelta(seconds=120),
        )
        active_session = SessionModel(
            id="active-session",
            user_id="user-2",
            status=SessionState.VERIFYING,
            lease_id="worker-active",
            lease_holder_id="worker-active",
            heartbeat_at=datetime.utcnow() - timedelta(seconds=15),
        )
        db.add(stale_session)
        db.add(active_session)
        db.commit()

        updated_rows = repository.mark_stale_sessions(db, timeout_seconds=60)
        db.commit()
        db.refresh(stale_session)
        db.refresh(active_session)

        self.assertEqual(updated_rows, 1)
        self.assertEqual(stale_session.status, SessionState.ABANDONED_VERIFYING)
        self.assertIsNone(stale_session.lease_id)
        self.assertEqual(active_session.status, SessionState.VERIFYING)
        self.assertEqual(active_session.lease_id, "worker-active")
        db.close()


class WorkflowRuntimeFailureTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        self.engine.dispose()

    def test_run_verification_marks_retriable_failure_for_extraction_crash(self):
        db = self.SessionLocal()
        session = self._create_session(
            db,
            session_id="runtime-failure-1",
            status=SessionState.UPLOADED_PENDING_REVIEW,
        )

        with patch(
            "backend.app.workflow.runtime.extract_document_payload",
            side_effect=RuntimeError("boom"),
        ), self.assertLogs("backend.app.workflow.service", level="ERROR") as logs:
            result = run_verification(db, session, "worker-1")

        db.refresh(session)
        self.assertEqual(result.status, SessionState.FAILED_RETRIABLE)
        self.assertEqual(session.status, SessionState.FAILED_RETRIABLE)
        self.assertEqual(session.reason_codes, ["EXTRACTION_CRASH"])
        self.assertIsNone(session.lease_id)
        self.assertIsNone(session.lease_acquired_at)
        self.assertTrue(any("PROCESSING_FAILED" in entry for entry in logs.output))
        db.close()

    def test_run_verification_marks_failed_purged_for_required_connector_timeout(self):
        db = self.SessionLocal()
        session = self._create_session(
            db,
            session_id="runtime-failure-2",
            status=SessionState.UPLOADED_PENDING_REVIEW,
        )

        with patch(
            "backend.app.workflow.runtime.extract_document_payload",
            return_value=self._successful_extraction_payload(),
        ), patch(
            "backend.app.workflow.runtime.build_connector_responses",
            return_value=[
                {
                    "connector_id": "vit_registry",
                    "status": "TIMEOUT",
                    "reason_codes": ["CONNECTOR_TIMEOUT"],
                    "assurance_class": "HIGH",
                }
            ],
        ):
            result = run_verification(db, session, "worker-1")

        db.refresh(session)
        self.assertEqual(result.status, SessionState.FAILED_PURGED)
        self.assertEqual(session.status, SessionState.FAILED_PURGED)
        self.assertEqual(session.reason_codes, ["CONNECTOR_TIMEOUT_REQUIRED"])
        self.assertIsNone(session.lease_id)
        self.assertEqual(session.connector_payload[0]["status"], "TIMEOUT")
        self.assertEqual(session.generalized_analysis_status, "READY")
        self.assertIsNotNone(session.document_profile_payload)
        self.assertIsNotNone(session.generalized_credentials_payload)
        self.assertIsNotNone(session.verification_plan_payload)
        self.assertIsNotNone(session.verification_task_results_payload)
        self.assertIsNotNone(session.credential_verification_bundles_payload)
        self.assertIsNotNone(session.verification_execution_summary_payload)
        self.assertEqual(session.verification_execution_status, "READY")
        self.assertIsNotNone(session.credential_audits_payload)
        self.assertIsNotNone(session.verification_summary_payload)
        db.close()

    def test_run_verification_retries_from_failed_retriable_and_completes(self):
        db = self.SessionLocal()
        session = self._create_session(
            db,
            session_id="runtime-retry-1",
            status=SessionState.FAILED_RETRIABLE,
        )

        with patch(
            "backend.app.workflow.runtime.extract_document_payload",
            return_value=self._successful_extraction_payload(),
        ), patch(
            "backend.app.workflow.runtime.build_connector_responses",
            return_value=[
                {
                    "connector_id": "vit_registry",
                    "status": "VERIFIED",
                    "reason_codes": ["REGISTRY_MATCH"],
                    "assurance_class": "HIGH",
                }
            ],
        ), patch(
            "backend.app.workflow.runtime.evaluate_trust",
            return_value={
                "outcome": "GREEN",
                "reason_codes": ["CONNECTOR_VERIFIED"],
                "connector_ids": ["vit_registry"],
            },
        ), patch(
            "backend.app.workflow.runtime.generate_nonce",
            return_value="nonce-1",
        ), patch(
            "backend.app.workflow.runtime.generate_commitment",
            return_value="commitment-1",
        ), patch(
            "backend.app.workflow.runtime.generate_receipt",
            return_value={"audit_event_id": "audit-1"},
        ), patch(
            "backend.app.workflow.runtime.store_audit_bundle",
        ) as store_mock:
            result = run_verification(db, session, "worker-1")

        db.refresh(session)
        self.assertEqual(result.status, SessionState.VERIFIED_GREEN)
        self.assertEqual(session.status, SessionState.VERIFIED_GREEN)
        self.assertEqual(session.trust_outcome, "GREEN")
        self.assertEqual(session.reason_codes, ["CONNECTOR_VERIFIED"])
        self.assertEqual(session.connector_ids, ["vit_registry"])
        self.assertEqual(session.audit_receipt_id, "audit-1")
        self.assertIsNone(session.lease_id)
        self.assertIsNone(session.lease_holder_id)
        self.assertEqual(session.generalized_analysis_status, "READY")
        self.assertIsNotNone(session.document_profile_payload)
        self.assertIsNotNone(session.generalized_credentials_payload)
        self.assertIsNotNone(session.verification_plan_payload)
        self.assertIsNotNone(session.verification_task_results_payload)
        self.assertIsNotNone(session.credential_verification_bundles_payload)
        self.assertIsNotNone(session.verification_execution_summary_payload)
        self.assertEqual(session.verification_execution_status, "READY")
        self.assertIsNotNone(session.credential_audits_payload)
        self.assertIsNotNone(session.verification_summary_payload)
        store_mock.assert_called_once()
        db.close()

    def _create_session(self, db, *, session_id: str, status: str) -> SessionModel:
        file_path = self._write_document(f"{session_id}.pdf")
        session = SessionModel(
            id=session_id,
            user_id="user-1",
            status=status,
            filename=Path(file_path).name,
            file_path=file_path,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def _write_document(self, filename: str) -> str:
        path = Path(self.temp_dir.name) / filename
        path.write_bytes(b"%PDF-1.4\n%mock document\n")
        return str(path)

    @staticmethod
    def _successful_extraction_payload() -> dict:
        return {
            "view": {
                "document_type": "academic_credential",
                "used_ocr": False,
                "fields": {
                    "name": "Kanak Sharma",
                    "institution": "VIT Vellore",
                    "credential": "BTech",
                    "id": "22BCE1234",
                },
                "confidence": {
                    "name": 0.98,
                    "institution": 0.97,
                    "credential": 0.96,
                    "id": 0.95,
                },
                "bounding_boxes": {
                    "name": {"page": 1, "x0": 10, "y0": 10, "x1": 100, "y1": 20},
                    "institution": {"page": 1, "x0": 10, "y0": 25, "x1": 150, "y1": 35},
                    "credential": {"page": 1, "x0": 10, "y0": 40, "x1": 120, "y1": 50},
                    "id": {"page": 1, "x0": 10, "y0": 55, "x1": 120, "y1": 65},
                },
                "field_details": [],
                "error_message": None,
            },
            "trust_input": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "name", "is_mandatory": True, "is_grounded": True, "value": "Kanak Sharma"},
                    {"name": "institution", "is_mandatory": True, "is_grounded": True, "value": "VIT Vellore"},
                    {"name": "credential", "is_mandatory": True, "is_grounded": True, "value": "BTech"},
                    {"name": "id", "is_mandatory": True, "is_grounded": True, "value": "22BCE1234"},
                ],
            },
            "connector_input": {
                "name": "Kanak Sharma",
                "degree": "BTech",
                "institution": "VIT Vellore",
                "document_id": "22BCE1234",
            },
        }


if __name__ == "__main__":
    unittest.main()

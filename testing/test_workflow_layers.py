import os
import inspect
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
from backend.app.workflow import runtime as workflow_runtime
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

    def test_validate_transition_allows_verifying_to_pending_human_review(self):
        validate_transition(
            SessionState.VERIFYING,
            SessionState.PENDING_HUMAN_REVIEW,
        )

    def test_validate_transition_rejects_invalid_transition(self):
        with self.assertRaises(InvalidStateTransitionError):
            validate_transition(
                SessionState.CREATED,
                SessionState.VERIFYING,
            )


class TriggerProcessingTests(unittest.TestCase):
    def test_trigger_processing_enqueues_job(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.enqueue_job",
        ) as enqueue_mock:
            result = trigger_processing(conn, "session-1", "worker-1")

        self.assertEqual(result, "STARTED")
        enqueue_mock.assert_called_once_with(conn, "session-1")
        conn.rollback.assert_not_called()

    def test_trigger_processing_returns_failed_when_enqueue_fails(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.enqueue_job",
            side_effect=RuntimeError("queue unavailable"),
        ) as enqueue_mock:
            result = trigger_processing(conn, "session-1", "worker-1")

        self.assertEqual(result, "FAILED")
        enqueue_mock.assert_called_once_with(conn, "session-1")
        conn.rollback.assert_called_once()

    def test_trigger_processing_does_not_retry_after_enqueue_failure(self):
        conn = MagicMock()

        with patch(
            "backend.app.orchestrator.orchestrator.enqueue_job",
            side_effect=RuntimeError("queue unavailable"),
        ) as enqueue_mock:
            result = trigger_processing(conn, "session-1", "worker-1", max_retries=2)

        self.assertEqual(result, "FAILED")
        enqueue_mock.assert_called_once_with(conn, "session-1")
        conn.rollback.assert_called_once()


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

    def test_start_verification_enqueues_without_running_pipeline(self):
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
        pipeline_mock.assert_not_called()

    def test_run_worker_pipeline_advances_all_phases_and_completes(self):
        conn = MagicMock()
        extraction_data = {
            "is_unsafe": False,
            "critical_tamper_signal": False,
            "fields": [{"name": "name", "value": "Kanak", "confidence": 0.98, "is_mandatory": True, "is_grounded": True}],
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
        self.assertEqual(complete_args[3], [])
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

    def test_default_worker_pipeline_keeps_sensitive_payloads_in_memory(self):
        db = self.SessionLocal()
        session = self._create_session(
            db,
            session_id="runtime-failure-1",
            status=SessionState.VERIFYING,
        )
        session.lease_id = "worker-1"
        session.lease_holder_id = "worker-1"
        db.commit()

        with patch(
            "backend.app.workflow.runtime.extract_document_payload",
            return_value=self._successful_extraction_payload(),
        ), patch(
            "backend.app.agent_orchestration.service.normalize_extraction_payload",
            side_effect=lambda payload: payload,
        ), patch(
            "backend.app.workflow.runtime.build_connector_responses",
            return_value=[
                {
                    "connector_id": "vit_registry",
                    "status": "VERIFIED",
                    "assurance_class": "HIGH",
                    "matched_claims": {},
                    "mismatched_claims": {},
                }
            ],
        ), patch(
            "backend.app.workflow.service._build_completion_values",
            return_value={"document_commitment": "commitment-1", "audit_receipt_id": "audit-1"},
        ):
            result = run_worker_pipeline(
                db,
                session.id,
                "worker-1",
                heartbeat_interval_seconds=0,
            )

        db.refresh(session)
        self.assertEqual(result["outcome"], "GREEN")
        self.assertEqual(session.status, SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(session.trust_outcome, "GREEN")
        self.assertIsNone(session.extraction_payload)
        self.assertIsNone(session.connector_payload)
        db.close()

    def test_runtime_does_not_define_or_call_degree_canonicalizer(self):
        source = inspect.getsource(workflow_runtime)

        self.assertNotIn("def _normalize_degree", source)
        self.assertNotIn("_normalize_degree(", source)
        self.assertNotIn("Bachelor of Engineering", source)
        self.assertNotIn("Bachelor of Technology", source)

    def test_runtime_preserves_non_academic_credential_values(self):
        raw_result = {
            "is_successful": True,
            "page_count": 1,
            "used_ocr": False,
            "fields": {
                "candidate_name": {"value": "  Asha   Rao  ", "confidence": 0.9, "bounding_boxes": []},
                "institution": {"value": "  Example   Issuer ", "confidence": 0.8, "bounding_boxes": []},
                "credential_type": {"value": " ISO   27001 Lead Auditor ", "confidence": 0.85, "bounding_boxes": []},
                "document_id": {"value": " CERT-001 ", "confidence": 0.8, "bounding_boxes": []},
            },
            "field_candidates": [],
        }
        with patch("backend.app.workflow.runtime._load_extraction_result", return_value=raw_result), patch(
            "backend.app.workflow.runtime._resolve_page_count",
            return_value=1,
        ):
            payload = workflow_runtime.extract_document_payload(Path("demo.pdf"))

        self.assertEqual(payload["connector_input"]["degree"], "ISO 27001 Lead Auditor")
        self.assertEqual(payload["connector_input"]["credential"], "ISO 27001 Lead Auditor")
        self.assertEqual(payload["connector_input"]["issuer"], "Example Issuer")
        self.assertEqual(payload["connector_input"]["institution"], "Example Issuer")

    def test_runtime_preserves_unknown_credential_values(self):
        raw_result = {
            "is_successful": True,
            "page_count": 1,
            "used_ocr": False,
            "fields": {
                "credential_type": {"value": " Bachelor   of Science in Physics ", "confidence": 0.85, "bounding_boxes": []},
            },
            "field_candidates": [],
        }
        with patch("backend.app.workflow.runtime._load_extraction_result", return_value=raw_result), patch(
            "backend.app.workflow.runtime._resolve_page_count",
            return_value=1,
        ):
            payload = workflow_runtime.extract_document_payload(Path("demo.pdf"))

        self.assertEqual(payload["connector_input"]["degree"], "Bachelor of Science in Physics")
        self.assertNotEqual(payload["connector_input"]["degree"], "BTech")

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
                    "name": "Demo Student",
                    "institution": "Demo University",
                    "credential": "Bachelor of Technology",
                    "id": "DEMO-2024-001",
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
                "field_details": [
                    {
                        "key": "candidate-name",
                        "label": "Candidate Name",
                        "value": "Demo Student",
                        "confidence": 0.98,
                        "is_mandatory": True,
                        "is_grounded": True,
                        "bounding_boxes": [{"page": 1, "x0": 10, "y0": 10, "x1": 100, "y1": 20}],
                        "category": "person_name",
                        "requires_verification": True,
                    }
                ],
                "field_candidates": [
                    {
                        "candidate_id": "cand-name",
                        "label": "Candidate Name",
                        "category": "person_name",
                        "raw_value": "Demo Student",
                        "normalized_value": "Demo Student",
                        "source_text": "Candidate Name: Demo Student",
                        "confidence": 0.98,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 100, "y1": 20},
                        "is_pii": True,
                        "requires_verification": True,
                        "verification_reason": "Identity claim",
                    },
                    {
                        "candidate_id": "cand-institution",
                        "label": "Institution",
                        "category": "issuer",
                        "raw_value": "Demo University",
                        "normalized_value": "Demo University",
                        "source_text": "Institution: Demo University",
                        "confidence": 0.97,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 25, "x1": 150, "y1": 35},
                        "is_pii": False,
                        "requires_verification": True,
                        "verification_reason": "Issuer claim",
                    },
                    {
                        "candidate_id": "cand-credential",
                        "label": "Credential",
                        "category": "credential_title",
                        "raw_value": "Bachelor of Technology",
                        "normalized_value": "Bachelor of Technology",
                        "source_text": "Credential: Bachelor of Technology",
                        "confidence": 0.96,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 40, "x1": 120, "y1": 50},
                        "is_pii": False,
                        "requires_verification": True,
                        "verification_reason": "Academic credential",
                    },
                    {
                        "candidate_id": "cand-id",
                        "label": "Document ID",
                        "category": "registration_number",
                        "raw_value": "DEMO-2024-001",
                        "normalized_value": "DEMO-2024-001",
                        "source_text": "Document ID: DEMO-2024-001",
                        "confidence": 0.95,
                        "page": 1,
                        "bounding_box": {"page": 1, "x0": 10, "y0": 55, "x1": 120, "y1": 65},
                        "is_pii": False,
                        "requires_verification": True,
                        "verification_reason": "Academic identifier",
                    },
                ],
                "error_message": None,
            },
            "trust_input": {
                "is_unsafe": False,
                "critical_tamper_signal": False,
                "fields": [
                    {"name": "name", "is_mandatory": True, "is_grounded": True, "value": "Demo Student", "confidence": 0.98},
                    {"name": "institution", "is_mandatory": True, "is_grounded": True, "value": "Demo University", "confidence": 0.97},
                    {"name": "credential", "is_mandatory": True, "is_grounded": True, "value": "Bachelor of Technology", "confidence": 0.96},
                    {"name": "id", "is_mandatory": True, "is_grounded": True, "value": "DEMO-2024-001", "confidence": 0.95},
                ],
            },
            "connector_input": {
                "name": "Demo Student",
                "degree": "Bachelor of Technology",
                "institution": "Demo University",
                "document_id": "DEMO-2024-001",
            },
        }


if __name__ == "__main__":
    unittest.main()

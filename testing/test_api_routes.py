import os
import sys
import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.api.routes import router
from backend.app.auth.routes import get_current_user
from backend.app.db.database import Base, get_db
from backend.app.sessions.constants import SessionState
from backend.app.sessions.models import AuditReceiptRecord, Session as SessionModel
from backend.app.workflow import repository
from backend.app.workflow.runtime import is_ready_for_cleanup
from backend.app.workflow.state_machine import validate_transition


class WorkflowApiRouteTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[get_db] = self._override_get_db
        self.app.dependency_overrides[get_current_user] = lambda: "user-1"
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.engine.dispose()

    def test_status_endpoint_returns_processing_state(self):
        self._create_session(
            session_id="session-processing",
            status=SessionState.VERIFYING,
            user_id="user-1",
        )

        response = self.client.get("/session/session-processing/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "session_id": "session-processing",
                "state": SessionState.VERIFYING,
                "processing": True,
                "retriable": False,
            },
        )

    def test_result_endpoint_returns_completed_trust_result(self):
        self._create_session(
            session_id="session-complete",
            status=SessionState.VERIFIED_GREEN,
            user_id="user-1",
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            connector_ids=["vit_registry"],
        )

        response = self.client.get("/session/session-complete/result")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "session_id": "session-complete",
                "outcome": "GREEN",
                "reason_codes": ["CONNECTOR_VERIFIED"],
                "connector_ids": ["vit_registry"],
            },
        )

    def test_failed_session_returns_retriable_flag_correctly(self):
        self._create_session(
            session_id="session-failed",
            status=SessionState.FAILED_RETRIABLE,
            user_id="user-1",
            reason_codes=["EXTRACTION_CRASH"],
        )

        status_response = self.client.get("/session/session-failed/status")
        result_response = self.client.get("/session/session-failed/result")

        self.assertEqual(status_response.status_code, 200)
        self.assertTrue(status_response.json()["retriable"])
        self.assertEqual(result_response.status_code, 200)
        self.assertEqual(result_response.json()["state"], SessionState.FAILED_RETRIABLE)
        self.assertTrue(result_response.json()["retriable"])
        self.assertIsNone(result_response.json()["outcome"])

    def test_result_endpoint_returns_safe_response_before_completion(self):
        self._create_session(
            session_id="session-pending",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
        )

        response = self.client.get("/session/session-pending/result")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], SessionState.UPLOADED_PENDING_REVIEW)
        self.assertTrue("processing" in response.json())
        self.assertIsNone(response.json()["outcome"])

    def test_legacy_verify_route_returns_410_with_canonical_route(self):
        self._create_session(
            session_id="session-legacy-verify",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
        )

        response = self.client.post("/session/session-legacy-verify/verify")

        self.assertEqual(response.status_code, 410)
        self.assertIn("/api/v1/verification-sessions/session-legacy-verify/run", response.json()["detail"])

    def test_invalid_session_returns_404(self):
        response = self.client.get("/session/missing-session/status")
        self.assertEqual(response.status_code, 404)

    def test_is_ready_for_cleanup_returns_true_for_human_terminal_and_abandoned_states(self):
        verified_session = SessionModel(id="verified", user_id="user-1", status=SessionState.VERIFIED_AMBER)
        approved_session = SessionModel(id="approved", user_id="user-1", status=SessionState.HUMAN_APPROVED)
        failed_session = SessionModel(id="failed", user_id="user-1", status=SessionState.FAILED_PURGED)
        abandoned_session = SessionModel(id="abandoned", user_id="user-1", status=SessionState.ABANDONED_VERIFYING)
        active_session = SessionModel(id="active", user_id="user-1", status=SessionState.VERIFYING)

        self.assertFalse(is_ready_for_cleanup(verified_session))
        self.assertTrue(is_ready_for_cleanup(approved_session))
        self.assertTrue(is_ready_for_cleanup(failed_session))
        self.assertTrue(is_ready_for_cleanup(abandoned_session))
        self.assertFalse(is_ready_for_cleanup(active_session))

    def test_verified_green_can_move_to_pending_human_review(self):
        validate_transition(SessionState.VERIFIED_GREEN, SessionState.PENDING_HUMAN_REVIEW)

    def test_verifying_can_move_to_pending_human_review(self):
        validate_transition(SessionState.VERIFYING, SessionState.PENDING_HUMAN_REVIEW)

    def test_run_uses_single_generalized_pipeline_and_persists_sanitized_workspace(self):
        file_path = self._create_temp_pdf()
        self._create_session(
            session_id="session-run-valid",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
            file_path=file_path,
        )

        def fake_generalized_runner(db, session, *, reviewer_ref):
            self.assertEqual(reviewer_ref, "user-1")
            repository.transition_state(db, session.id, SessionState.VERIFYING, extra_values={"worker_phase": "GENERALIZED_PIPELINE"})
            db.commit()
            workspace = self._workspace_payload(session.id)
            workspace["document"]["warnings"] = [
                "PP_CHATOCR_CHAT_STAGE_DISABLED",
                {"code": "PP_CHAT_OCR_CHAT_STAGE_AUTH_FAILED", "message": "safe message"},
                "SCHEMA_INFERENCE_WARNING",
                {"message": "layout warning"},
            ]
            from backend.app.agent_orchestration.graph import _safe_code_list
            workspace["document"]["warnings"] = _safe_code_list(workspace["document"]["warnings"])
            value_box = {
                "page": 1,
                "page_number": 1,
                "x0": 10,
                "y0": 10,
                "x1": 40,
                "y1": 20,
                "bbox": [10, 10, 40, 20],
            }
            label_box = {
                "page": 1,
                "page_number": 1,
                "x0": 42,
                "y0": 10,
                "x1": 72,
                "y1": 20,
                "bbox": [42, 10, 72, 20],
            }
            full_line_box = {
                "page": 1,
                "page_number": 1,
                "x0": 8,
                "y0": 8,
                "x1": 180,
                "y1": 24,
                "bbox": [8, 8, 180, 24],
            }
            workspace["fields"] = [
                {
                    "field_id": f"field-{index}",
                    "label": f"Field {index}",
                    "extracted_value": f"masked-{index}",
                    "normalized_value": f"masked-{index}",
                    "status": "AMBER",
                    "confidence": 0.8,
                    "bounding_boxes": [full_line_box, label_box, value_box, value_box],
                    "reason_codes": ["MANUAL_REVIEW_REQUIRED"],
                    "manual_review_required": True,
                    "source_text": "RAW_OCR_TEXT_SHOULD_NOT_PERSIST",
                }
                for index in range(1, 6)
            ]
            workspace["document"]["highlights_count"] = 10
            workspace["verifiers"] = [
                {
                    "task_id": "task-generalized-no-match",
                    "field_id": "field-1",
                    "connector_id": "manual_review",
                    "status": "MANUAL_REVIEW",
                    "verification_confidence": 0.0,
                    "reason_codes": ["NO_PROVIDER_AVAILABLE", "MANUAL_REVIEW_PROVIDER_SELECTED"],
                    "audit_message": "No executable generalized provider matched; manual review required.",
                    "attempted_provider_keys": ["unknown_provider", "manual_review"],
                    "skipped_provider_keys": ["unknown_provider"],
                }
            ]
            workspace["final_verdict"] = {
                "outcome": "AMBER",
                "reason_codes": ["MANUAL_REVIEW_REQUIRED", "NO_PROVIDER_AVAILABLE", "PP_CHATOCR_CHAT_STAGE_DISABLED"],
                "connector_ids": ["manual_review"],
                "explanation": "Generalized manual review required.",
                "risk_level": "MEDIUM",
                "matching_score": 0.0,
                "visual_match_probability": 0.0,
            }
            workspace["audit"] = [
                {
                    "stage": "mocked_langgraph",
                    "message": "mocked LangGraph output consumed; generalized verification_tasks used",
                    "level": "INFO",
                    "timestamp": "2026-05-04T00:00:00+00:00",
                }
            ]
            workspace["raw_text"] = "RAW_OCR_TEXT_SHOULD_NOT_PERSIST"
            workspace["raw_gemini_response"] = {"secret": "MODEL_OUTPUT"}
            workspace["provider_raw_body"] = {"secret": "PROVIDER_BODY"}
            from backend.app.agent_orchestration.sanitization import sanitize_workspace_payload
            from backend.app.agent_orchestration.schemas import WorkspacePayload

            sanitized = sanitize_workspace_payload(WorkspacePayload.model_validate(workspace))
            repository.complete_processing(
                db,
                session.id,
                SessionState.PENDING_HUMAN_REVIEW,
                sanitized.final_verdict.outcome,
                sanitized.final_verdict.reason_codes,
                sanitized.final_verdict.connector_ids,
                extra_values={
                    "workspace_payload": sanitized.model_dump(mode="json"),
                    "verification_execution_status": "READY",
                    "generalized_analysis_status": "READY",
                },
            )
            db.commit()
            return sanitized

        with patch("backend.app.api.routes.start_verification", return_value="STARTED") as start_mock, patch(
            "backend.app.api.routes.run_generalized_verification_session",
            side_effect=fake_generalized_runner,
        ) as generalized_mock:
            response = self.client.post("/api/v1/verification-sessions/session-run-valid/run")

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.status_code, 410)
        payload = response.json()
        self.assertEqual(payload["session_id"], "session-run-valid")
        self.assertEqual(payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(payload["final_verdict"]["outcome"], "AMBER")
        self.assertEqual(
            payload["document"]["warnings"],
            ["PP_CHAT_OCR_CHAT_STAGE_AUTH_FAILED", "SCHEMA_INFERENCE_WARNING", "LAYOUT_WARNING"],
        )
        self.assertNotIn("PP_CHATOCR_CHAT_STAGE_DISABLED", payload["document"]["warnings"])
        self.assertNotIn("PP_CHATOCR_CHAT_STAGE_DISABLED", payload["final_verdict"]["reason_codes"])
        self.assertTrue(all(isinstance(item, str) for item in payload["document"]["warnings"]))
        self.assertEqual(len(payload["fields"]), 5)
        self.assertTrue(all(len(field["bounding_boxes"]) <= 2 for field in payload["fields"]))
        self.assertEqual(sum(len(field["bounding_boxes"]) for field in payload["fields"]), 10)
        self.assertFalse(any(box["bbox"] == [8.0, 8.0, 180.0, 24.0] for field in payload["fields"] for box in field["bounding_boxes"]))
        self.assertIn("MANUAL_REVIEW_PROVIDER_SELECTED", payload["verifiers"][0]["reason_codes"])
        self.assertEqual(payload["verifiers"][0]["attempted_provider_keys"], ["unknown_provider", "manual_review"])
        self.assertEqual(payload["verifiers"][0]["skipped_provider_keys"], ["unknown_provider"])
        serialized_payload = json.dumps(payload, sort_keys=True)
        self.assertNotIn("RAW_OCR_TEXT_SHOULD_NOT_PERSIST", serialized_payload)
        self.assertNotIn("raw_gemini_response", serialized_payload)
        self.assertNotIn("provider_raw_body", serialized_payload)
        start_mock.assert_not_called()
        generalized_mock.assert_called_once()

        db = self.SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == "session-run-valid").one()
            self.assertEqual(session.status, SessionState.PENDING_HUMAN_REVIEW)
            self.assertEqual(session.trust_outcome, "AMBER")
            self.assertNotEqual(session.status, session.trust_outcome)
            persisted = json.dumps(session.workspace_payload, sort_keys=True)
            self.assertIn("bounding_boxes", persisted)
            self.assertTrue(all(isinstance(item, str) for item in session.workspace_payload["document"]["warnings"]))
            self.assertFalse(any(isinstance(item, (dict, list)) for item in session.workspace_payload["document"]["warnings"]))
            self.assertNotIn("PP_CHATOCR_CHAT_STAGE_DISABLED", persisted)
            self.assertNotIn("RAW_OCR_TEXT_SHOULD_NOT_PERSIST", persisted)
            self.assertNotIn("raw_gemini_response", persisted)
            self.assertNotIn("provider_raw_body", persisted)
        finally:
            db.close()

    def test_run_endpoint_wrong_owner_returns_403(self):
        file_path = self._create_temp_pdf()
        self._create_session(
            session_id="session-run-other-user",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-2",
            file_path=file_path,
        )

        response = self.client.post("/api/v1/verification-sessions/session-run-other-user/run")

        self.assertEqual(response.status_code, 403)

    def test_run_endpoint_missing_file_path_returns_409(self):
        self._create_session(
            session_id="session-run-missing-file-path",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
        )

        response = self.client.post("/api/v1/verification-sessions/session-run-missing-file-path/run")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Upload a PDF before verification")

    def test_run_endpoint_missing_file_on_disk_returns_404(self):
        self._create_session(
            session_id="session-run-missing-file",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
            file_path=os.path.join(tempfile.gettempdir(), "secuura-missing-document.pdf"),
        )

        response = self.client.post("/api/v1/verification-sessions/session-run-missing-file/run")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Document not found on disk")

    def test_run_endpoint_cleanup_states_return_409(self):
        for state in (SessionState.PENDING_CLEANUP, SessionState.PURGE_COMPLETE, SessionState.FAILED_PURGED):
            with self.subTest(state=state):
                file_path = self._create_temp_pdf()
                session_id = f"session-run-{state.lower()}"
                self._create_session(
                    session_id=session_id,
                    status=state,
                    user_id="user-1",
                    file_path=file_path,
                )

                response = self.client.post(f"/api/v1/verification-sessions/{session_id}/run")

                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["detail"], "Session is already closed")

    def test_run_endpoint_generalized_pipeline_failed_returns_500(self):
        file_path = self._create_temp_pdf()
        self._create_session(
            session_id="session-run-start-failed",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
            file_path=file_path,
        )

        with patch("backend.app.api.routes.run_generalized_verification_session", side_effect=RuntimeError("pipeline failed")):
            response = self.client.post("/api/v1/verification-sessions/session-run-start-failed/run")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"], "Generalized verification failed")

    def test_review_decision_approve_returns_human_approved(self):
        self._create_session(
            session_id="session-review-approve",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            connector_ids=["vit_registry"],
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-approve/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "session_id": "session-review-approve",
                "status": SessionState.HUMAN_APPROVED,
                "final_decision": "APPROVED",
                "cleanup_ready": True,
                "audit_receipt_id": response.json()["audit_receipt_id"],
            },
        )
        self.assertTrue(response.json()["audit_receipt_id"])
        receipt = self._get_audit_receipt(response.json()["audit_receipt_id"])
        self.assertEqual(receipt.reviewer_decision, "APPROVED")
        self.assertIsNone(receipt.reviewer_note_hash)
        self.assertEqual(receipt.finding_counts, {"green": 1, "amber": 0, "red": 0})
        self.assertIsNotNone(receipt.approved_at)
        self.assertIsNone(receipt.rejected_at)
        self.assertIsNone(receipt.manual_review_at)

    def test_review_decision_same_final_state_is_idempotent(self):
        self._create_session(
            session_id="session-review-idempotent",
            status=SessionState.HUMAN_APPROVED,
            user_id="user-1",
            trust_outcome="GREEN",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-idempotent/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SessionState.HUMAN_APPROVED)
        self.assertEqual(response.json()["final_decision"], "APPROVED")
        self.assertTrue(response.json()["audit_receipt_id"])

    def test_review_decision_different_final_state_still_conflicts(self):
        self._create_session(
            session_id="session-review-final-conflict",
            status=SessionState.HUMAN_APPROVED,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-final-conflict/review-decision",
            json={"decision": "REJECT"},
        )

        self.assertEqual(response.status_code, 409)

    def test_review_decision_audit_failure_returns_500_not_409(self):
        self._create_session(
            session_id="session-review-audit-failure",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
        )

        with patch("backend.app.api.routes.upsert_final_review_receipt", side_effect=RuntimeError("audit db failed")):
            response = self.client.post(
                "/api/v1/verification-sessions/session-review-audit-failure/review-decision",
                json={"decision": "APPROVE"},
            )

        self.assertEqual(response.status_code, 500)

    def test_review_decision_reject_returns_human_rejected(self):
        self._create_session(
            session_id="session-review-reject",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            trust_outcome="RED",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-reject/review-decision",
            json={"decision": "REJECT"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SessionState.HUMAN_REJECTED)
        self.assertEqual(response.json()["final_decision"], "REJECTED")
        self.assertTrue(response.json()["cleanup_ready"])
        self.assertTrue(response.json()["audit_receipt_id"])
        receipt = self._get_audit_receipt(response.json()["audit_receipt_id"])
        self.assertEqual(receipt.reviewer_decision, "REJECTED")
        self.assertEqual(receipt.finding_counts, {"green": 0, "amber": 0, "red": 1})
        self.assertIsNotNone(receipt.rejected_at)
        self.assertIsNone(receipt.approved_at)
        self.assertIsNone(receipt.manual_review_at)

    def test_review_decision_manual_review_returns_manual_review_required(self):
        reviewer_note = "Needs secondary review for the uploaded credential"
        self._create_session(
            session_id="session-review-manual",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            verification_execution_summary_payload={
                "summary": {
                    "green_count": 2,
                    "amber_count": 1,
                    "red_count": 0,
                    "student_name": "Alice Rao",
                }
            },
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-manual/review-decision",
            json={"decision": "NEEDS_MANUAL_REVIEW", "reviewer_note": reviewer_note},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SessionState.MANUAL_REVIEW_REQUIRED)
        self.assertEqual(response.json()["final_decision"], "MANUAL_REVIEW_REQUIRED")
        self.assertTrue(response.json()["cleanup_ready"])
        self.assertTrue(response.json()["audit_receipt_id"])
        receipt = self._get_audit_receipt(response.json()["audit_receipt_id"])
        self.assertEqual(receipt.reviewer_decision, "MANUAL_REVIEW_REQUIRED")
        self.assertIsNotNone(receipt.reviewer_note_hash)
        self.assertNotEqual(receipt.reviewer_note_hash, reviewer_note)
        self.assertNotIn(reviewer_note, str(receipt.__dict__))
        self.assertEqual(receipt.finding_counts, {"green": 2, "amber": 1, "red": 0})
        self.assertNotIn("Alice Rao", str(receipt.finding_counts))
        self.assertIsNotNone(receipt.manual_review_at)
        self.assertIsNone(receipt.approved_at)
        self.assertIsNone(receipt.rejected_at)

    def test_review_decision_allows_verified_green_compatibility_path(self):
        self._create_session(
            session_id="session-review-verified",
            status=SessionState.VERIFIED_GREEN,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-verified/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], SessionState.HUMAN_APPROVED)
        self.assertTrue(response.json()["audit_receipt_id"])

    def test_review_decision_verifying_returns_409(self):
        self._create_session(
            session_id="session-review-verifying",
            status=SessionState.VERIFYING,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-verifying/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 409)

    def test_review_decision_uploaded_pending_review_returns_409(self):
        self._create_session(
            session_id="session-review-uploaded",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-uploaded/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 409)

    def test_review_decision_non_review_states_return_409(self):
        for state in (
            SessionState.UPLOAD_PENDING,
            SessionState.PENDING_CLEANUP,
            SessionState.PURGE_COMPLETE,
        ):
            session_id = f"session-review-{state.lower()}"
            with self.subTest(state=state):
                self._create_session(
                    session_id=session_id,
                    status=state,
                    user_id="user-1",
                )

                response = self.client.post(
                    f"/api/v1/verification-sessions/{session_id}/review-decision",
                    json={"decision": "APPROVE"},
                )

                self.assertEqual(response.status_code, 409)

    def test_review_decision_wrong_owner_returns_403(self):
        self._create_session(
            session_id="session-review-other-user",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-2",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-other-user/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 403)

    def test_review_decision_invalid_decision_returns_422(self):
        self._create_session(
            session_id="session-review-invalid",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-invalid/review-decision",
            json={"decision": "MAYBE"},
        )

        self.assertEqual(response.status_code, 422)

    def test_review_decision_updates_existing_audit_receipt(self):
        self._create_session(
            session_id="session-review-existing-audit",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            audit_receipt_id="audit-existing",
        )
        self._create_audit_receipt("audit-existing", "session-review-existing-audit")

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-existing-audit/review-decision",
            json={"decision": "APPROVE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["audit_receipt_id"], "audit-existing")
        receipt = self._get_audit_receipt("audit-existing")
        self.assertEqual(receipt.reviewer_decision, "APPROVED")
        self.assertEqual(receipt.finding_counts, {"green": 0, "amber": 0, "red": 0, "unknown": True})
        self.assertNotEqual(receipt.receipt_hash, "old-hash")

    def test_review_decision_manual_review_requires_note(self):
        self._create_session(
            session_id="session-review-manual-no-note",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
        )

        response = self.client.post(
            "/api/v1/verification-sessions/session-review-manual-no-note/review-decision",
            json={"decision": "NEEDS_MANUAL_REVIEW"},
        )

        self.assertEqual(response.status_code, 422)

    def test_workspace_reads_persisted_payload_without_rerunning_graph(self):
        workspace_payload = self._workspace_payload("session-workspace-persisted")
        self._create_session(
            session_id="session-workspace-persisted",
            status=SessionState.PENDING_HUMAN_REVIEW,
            user_id="user-1",
            workspace_payload=workspace_payload,
        )

        with patch(
            "backend.app.api.routes.build_generalized_verification_graph",
            side_effect=AssertionError("workspace GET must not run Gemini graph"),
        ):
            response = self.client.get("/api/v1/verification-sessions/session-workspace-persisted/workspace")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "session-workspace-persisted")

    def _override_get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _create_session(
        self,
        *,
        session_id: str,
        status: str,
        user_id: str,
        trust_outcome: str | None = None,
        reason_codes: list[str] | None = None,
        connector_ids: list[str] | None = None,
        file_path: str | None = None,
        workspace_payload: dict | None = None,
        verification_execution_summary_payload: dict | None = None,
        audit_receipt_id: str | None = None,
    ) -> None:
        db = self.SessionLocal()
        session = SessionModel(
            id=session_id,
            user_id=user_id,
            status=status,
            file_path=file_path,
            filename="demo.pdf" if file_path else None,
            trust_outcome=trust_outcome,
            reason_codes=reason_codes or [],
            connector_ids=connector_ids or [],
            workspace_payload=workspace_payload,
            verification_execution_summary_payload=verification_execution_summary_payload,
            audit_receipt_id=audit_receipt_id,
        )
        db.add(session)
        db.commit()
        db.close()

    def _create_audit_receipt(self, audit_event_id: str, session_id: str) -> None:
        db = self.SessionLocal()
        receipt = AuditReceiptRecord(
            audit_event_id=audit_event_id,
            session_id=session_id,
            reviewer_ref="worker-1",
            document_commitment="commitment-1",
            trust_outcome="GREEN",
            reason_codes=[],
            connector_ids=[],
            issued_at=datetime.utcnow(),
            key_version="v1",
            receipt_hash="old-hash",
        )
        db.add(receipt)
        db.commit()
        db.close()

    def _get_audit_receipt(self, audit_event_id: str) -> AuditReceiptRecord:
        db = self.SessionLocal()
        try:
            receipt = db.query(AuditReceiptRecord).filter(AuditReceiptRecord.audit_event_id == audit_event_id).first()
            self.assertIsNotNone(receipt)
            db.expunge(receipt)
            return receipt
        finally:
            db.close()

    def _create_temp_pdf(self) -> str:
        file_handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        file_handle.write(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")
        file_handle.close()
        self.addCleanup(lambda: os.path.exists(file_handle.name) and os.remove(file_handle.name))
        return file_handle.name

    def _workspace_payload(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "status": SessionState.PENDING_HUMAN_REVIEW,
            "ui_status": "Ready for human review",
            "document": {
                "filename": "demo.pdf",
                "document_type": "academic_credential",
                "page_count": 1,
                "used_ocr": False,
                "warnings": [],
                "highlights_count": 0,
            },
            "summary": {
                "total_fields": 0,
                "green_count": 0,
                "amber_count": 0,
                "red_count": 0,
                "matching_score": 0.0,
                "visual_match_probability": 0.0,
                "risk_level": "MEDIUM",
                "active_exceptions": [],
            },
            "fields": [],
            "verifiers": [],
            "final_verdict": {
                "outcome": "AMBER",
                "reason_codes": [],
                "connector_ids": [],
                "explanation": "",
                "risk_level": "MEDIUM",
                "matching_score": 0.0,
                "visual_match_probability": 0.0,
            },
            "audit": [],
            "actions": [],
        }


def test_run_uses_single_generalized_pipeline_and_persists_sanitized_workspace():
    case = WorkflowApiRouteTests(methodName="test_run_uses_single_generalized_pipeline_and_persists_sanitized_workspace")
    case.setUp()
    try:
        case.test_run_uses_single_generalized_pipeline_and_persists_sanitized_workspace()
    finally:
        case.tearDown()


if __name__ == "__main__":
    unittest.main()

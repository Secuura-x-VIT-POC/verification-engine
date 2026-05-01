import os
import sys
import tempfile
import unittest
import copy
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.schemas import (
    GeminiCredentialGroupCollection,
    GeminiDocumentUnderstanding,
    GeminiNormalizedField,
    GeminiNormalizedFieldCollection,
    VerifierResult,
)
from backend.app.auth.routes import get_current_user
from backend.app.db.database import Base, get_db
from backend.app.main import app
from backend.app.sessions.constants import SessionState
from backend.app.sessions.models import AuditEventRecord, AuditReceiptRecord, Session as SessionModel
from backend.app.trust.trust_engine import determine_field_decision


def fuse_confidence(
    *,
    extraction_confidence: float,
    ai_confidence: float,
    verification_confidence: float,
    grounding_confidence: float,
) -> float:
    return (
        (0.40 * extraction_confidence)
        + (0.25 * ai_confidence)
        + (0.25 * verification_confidence)
        + (0.10 * grounding_confidence)
    )


def _runtime_extraction_payload() -> dict:
    return {
        "view": {
            "document_type": "academic_credential",
            "page_count": 1,
            "used_ocr": False,
            "warnings": [],
            "field_details": [
                {
                    "key": "name",
                    "label": "Name",
                    "bounding_boxes": [{"page": 1, "x0": 10, "y0": 10, "x1": 40, "y1": 20}],
                },
                {
                    "key": "institution",
                    "label": "Institution",
                    "bounding_boxes": [{"page": 1, "x0": 10, "y0": 25, "x1": 50, "y1": 35}],
                },
                {
                    "key": "credential",
                    "label": "Credential",
                    "bounding_boxes": [{"page": 1, "x0": 10, "y0": 40, "x1": 55, "y1": 50}],
                },
                {
                    "key": "id",
                    "label": "Document ID",
                    "bounding_boxes": [{"page": 1, "x0": 10, "y0": 55, "x1": 45, "y1": 65}],
                },
            ],
            "confidence": {
                "name": 0.92,
                "institution": 0.93,
                "credential": 0.91,
                "id": 0.9,
            },
        },
        "trust_input": {
            "fields": [
                {"name": "name", "value": "Alice Rao", "is_mandatory": True, "is_grounded": True, "confidence": 0.92},
                {"name": "institution", "value": "VIT Vellore", "is_mandatory": True, "is_grounded": True, "confidence": 0.93},
                {"name": "credential", "value": "BTech", "is_mandatory": True, "is_grounded": True, "confidence": 0.91},
                {"name": "id", "value": "22BCE1001", "is_mandatory": True, "is_grounded": True, "confidence": 0.9},
            ],
        },
        "connector_input": {
            "name": "Alice Rao",
            "degree": "BTech",
            "institution": "VIT Vellore",
            "document_id": "22BCE1001",
        },
    }


class _FakeLlm:
    def __init__(self, response):
        self.response = response

    def invoke(self, _prompt):
        return self.response


class GeneralizedWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self._original_overrides = dict(app.dependency_overrides)
        app.dependency_overrides[get_db] = self._override_get_db
        app.dependency_overrides[get_current_user] = lambda: "user-1"
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides = self._original_overrides
        self.engine.dispose()

    def test_confidence_fusion_formula(self):
        score = fuse_confidence(
            extraction_confidence=0.8,
            ai_confidence=0.6,
            verification_confidence=1.0,
            grounding_confidence=0.5,
        )
        self.assertAlmostEqual(score, 0.77, places=3)

    def test_hard_red_override_on_verifier_mismatch(self):
        verifier = VerifierResult(
            task_id="task-1",
            field_id="name",
            connector_id="vit_registry",
            verification_confidence=0.0,
            status="MISMATCH",
            reason_codes=["CRITICAL_VERIFIER_MISMATCH"],
            audit_message="Mismatch",
            source_api="vit_registry",
            optional=False,
            high_assurance=True,
        )
        decision = determine_field_decision(
            field_id="name",
            label="Name",
            extracted_value="Alice",
            normalized_value="Alice",
            extraction_confidence=0.9,
            ai_confidence=0.9,
            grounding_confidence=1.0,
            verifier_result=verifier,
            mandatory=True,
            unsafe_or_malformed=False,
        )
        self.assertEqual(decision.status, "RED")
        self.assertIn("CRITICAL_VERIFIER_MISMATCH", decision.reason_codes)

    def test_optional_verifier_timeout_is_amber(self):
        verifier = VerifierResult(
            task_id="task-1",
            field_id="id",
            connector_id="optional_registry",
            verification_confidence=0.2,
            status="TIMEOUT",
            reason_codes=["OPTIONAL_VERIFIER_UNAVAILABLE"],
            audit_message="Timeout",
            source_api="optional_registry",
            optional=True,
            high_assurance=False,
        )
        decision = determine_field_decision(
            field_id="id",
            label="Document ID",
            extracted_value="ABC123",
            normalized_value="ABC123",
            extraction_confidence=0.9,
            ai_confidence=0.7,
            grounding_confidence=1.0,
            verifier_result=verifier,
            mandatory=False,
            unsafe_or_malformed=False,
        )
        self.assertEqual(decision.status, "AMBER")

    def test_required_high_assurance_timeout_is_red(self):
        verifier = VerifierResult(
            task_id="task-1",
            field_id="id",
            connector_id="vit_registry",
            verification_confidence=0.2,
            status="TIMEOUT",
            reason_codes=["REQUIRED_HIGH_ASSURANCE_TIMEOUT"],
            audit_message="Timeout",
            source_api="vit_registry",
            optional=False,
            high_assurance=True,
        )
        decision = determine_field_decision(
            field_id="id",
            label="Document ID",
            extracted_value="ABC123",
            normalized_value="ABC123",
            extraction_confidence=0.9,
            ai_confidence=0.7,
            grounding_confidence=1.0,
            verifier_result=verifier,
            mandatory=True,
            unsafe_or_malformed=False,
        )
        self.assertEqual(decision.status, "RED")

    def test_api_smoke_run_then_workspace_returns_stable_contract(self):
        session_id, file_path = self._create_uploaded_session("session-smoke")
        self.addCleanup(lambda: os.path.exists(file_path) and os.remove(file_path))

        with patch("backend.app.api.routes.start_verification", return_value="STARTED"), patch(
            "backend.app.agent_orchestration.graph.extract_document_payload",
            return_value=_runtime_extraction_payload(),
        ), patch(
            "backend.app.agent_orchestration.workspace._build_completion_values",
            return_value={},
        ):
            run_response = self.client.post(f"/api/v1/verification-sessions/{session_id}/run")
            workspace_response = self.client.get(f"/api/v1/verification-sessions/{session_id}/workspace")

        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(workspace_response.status_code, 200)
        payload = workspace_response.json()
        self.assertEqual(payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(
            sorted(payload.keys()),
            sorted(["session_id", "status", "ui_status", "document", "summary", "fields", "verifiers", "final_verdict", "audit", "actions"]),
        )
        self.assertIn(payload["final_verdict"]["outcome"], {"GREEN", "AMBER", "RED"})
        self.assertIn("green_count", payload["summary"])
        self.assertIn("amber_count", payload["summary"])
        self.assertIn("red_count", payload["summary"])
        self.assertIsInstance(payload["fields"], list)
        self.assertIsInstance(payload["verifiers"], list)
        action_ids = {item["action_id"] for item in payload["actions"]}
        self.assertTrue({"can_rerun", "can_manual_override", "can_export_report", "can_close"}.issubset(action_ids))

    def test_run_and_workspace_responses_are_sanitized(self):
        session_id, file_path = self._create_uploaded_session("session-sanitized")
        self.addCleanup(lambda: os.path.exists(file_path) and os.remove(file_path))
        extraction_payload = copy.deepcopy(_runtime_extraction_payload())
        extraction_payload["view"].update(
            {
                "raw_text": "RAW PDF OCR TEXT Alice Rao 22BCE1001",
                "full_ocr_text": "FULL OCR TEXT Alice Rao",
                "spatial_text_map": ["Alice Rao at x1"],
                "evidence_lines": ["Candidate Name: Alice Rao"],
                "field_candidates": [
                    {
                        "label": "Name",
                        "raw_value": "Alice Rao",
                        "normalized_value": "Alice Rao",
                        "source_text": "Candidate Name: Alice Rao",
                    }
                ],
                "generalized_analysis": {"agent_raw_output": "raw Gemini output"},
            }
        )
        extraction_payload["agent_private_notes"] = "private planner notes"
        extraction_payload["provider_raw_response"] = {"response_body": "raw provider response"}

        with patch("backend.app.api.routes.start_verification", return_value="STARTED"), patch(
            "backend.app.agent_orchestration.graph.extract_document_payload",
            return_value=extraction_payload,
        ), patch(
            "backend.app.agent_orchestration.workspace._build_completion_values",
            return_value={},
        ):
            run_response = self.client.post(f"/api/v1/verification-sessions/{session_id}/run")
            workspace_response = self.client.get(f"/api/v1/verification-sessions/{session_id}/workspace")

        self.assertEqual(run_response.status_code, 200)
        self.assertEqual(workspace_response.status_code, 200)
        for payload in (run_response.json(), workspace_response.json()):
            serialized = json.dumps(payload, sort_keys=True)
            for forbidden in {
                "raw_text",
                "full_ocr_text",
                "source_text",
                "spatial_text_map",
                "evidence_lines",
                "field_candidates",
                "generalized_analysis",
                "agent_private_notes",
                "agent_raw_output",
                "provider_raw_response",
                "response_body",
            }:
                self.assertNotIn(f'"{forbidden}"', serialized)
            for raw_value in {
                "RAW PDF OCR TEXT",
                "FULL OCR TEXT",
                "Candidate Name: Alice Rao",
                "raw Gemini output",
                "raw provider response",
                "Alice Rao",
                "22BCE1001",
            }:
                self.assertNotIn(raw_value, serialized)

            self.assertTrue(payload["fields"])
            field = payload["fields"][0]
            self.assertIn("label", field)
            self.assertIn("extraction_confidence", field)
            self.assertIn("bounding_boxes", field)
            self.assertIn("status", field)
            self.assertIn("reason_codes", field)
            self.assertIn("audit_message", field)
            for item in payload["fields"]:
                if item.get("extracted_value"):
                    self.assertIn("***", item["extracted_value"])
                if item.get("normalized_value"):
                    self.assertIn("***", item["normalized_value"])

    def test_fallback_mode_smoke_without_gemini_key(self):
        session_id, file_path = self._create_uploaded_session("session-fallback")
        self.addCleanup(lambda: os.path.exists(file_path) and os.remove(file_path))
        env = {
            "AGENT_ORCHESTRATION_ENABLED": "true",
            "AGENT_PROVIDER": "gemini",
            "GEMINI_API_KEY": "",
        }

        with patch.dict(os.environ, env, clear=False), patch(
            "backend.app.api.routes.start_verification",
            return_value="STARTED",
        ), patch(
            "backend.app.agent_orchestration.graph.extract_document_payload",
            return_value=_runtime_extraction_payload(),
        ), patch(
            "backend.app.agent_orchestration.workspace._build_completion_values",
            return_value={},
        ):
            response = self.client.post(f"/api/v1/verification-sessions/{session_id}/run")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertIn(payload["final_verdict"]["outcome"], {"GREEN", "AMBER", "RED"})
        self.assertTrue(any("fallback" in entry["message"].lower() for entry in payload["audit"]))

        db = self.SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            self.assertIsNotNone(session)
            self.assertIsNone(session.agent_run_summary_payload)
        finally:
            db.close()

    def test_api_level_critical_mismatch_forces_red(self):
        session_id, file_path = self._create_uploaded_session("session-mismatch")
        self.addCleanup(lambda: os.path.exists(file_path) and os.remove(file_path))

        mismatch_result = [
            {
                "connector_id": "vit_registry",
                "status": "MISMATCH",
                "reason_codes": ["CRITICAL_VERIFIER_MISMATCH"],
                "assurance_class": "HIGH",
            }
        ]

        with patch("backend.app.api.routes.start_verification", return_value="STARTED"), patch(
            "backend.app.agent_orchestration.graph.extract_document_payload",
            return_value=_runtime_extraction_payload(),
        ), patch(
            "backend.app.agent_orchestration.graph.build_connector_responses",
            return_value=mismatch_result,
        ), patch(
            "backend.app.agent_orchestration.workspace._build_completion_values",
            return_value={},
        ):
            response = self.client.post(f"/api/v1/verification-sessions/{session_id}/run")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(payload["final_verdict"]["outcome"], "RED")
        self.assertTrue(any(field["status"] == "RED" for field in payload["fields"]))
        reason_codes = set(payload["final_verdict"]["reason_codes"])
        self.assertTrue(reason_codes)

    def test_run_does_not_persist_workspace_summary_or_raw_text_fields(self):
        session_id, file_path = self._create_uploaded_session("session-safe-persist")
        self.addCleanup(lambda: os.path.exists(file_path) and os.remove(file_path))
        extraction_payload = _runtime_extraction_payload()
        extraction_payload["view"]["raw_text"] = "Very sensitive OCR text"

        with patch("backend.app.api.routes.start_verification", return_value="STARTED"), patch(
            "backend.app.agent_orchestration.graph.extract_document_payload",
            return_value=extraction_payload,
        ), patch(
            "backend.app.agent_orchestration.workspace._build_completion_values",
            return_value={},
        ):
            response = self.client.post(f"/api/v1/verification-sessions/{session_id}/run")

        self.assertEqual(response.status_code, 200)
        db = self.SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            self.assertIsNotNone(session)
            self.assertIsNone(session.verification_execution_summary_payload)
            self.assertIsNone(session.agent_run_summary_payload)
            self.assertIsNone(session.extraction_payload)
        finally:
            db.close()

    def test_run_and_review_decision_do_not_persist_raw_sensitive_artifacts(self):
        session_id, file_path = self._create_uploaded_session("session-privacy-regression")
        self.addCleanup(lambda: os.path.exists(file_path) and os.remove(file_path))
        extraction_payload = copy.deepcopy(_runtime_extraction_payload())
        sentinels = {
            "RAW_OCR_SENTINEL_41A",
            "RAW_PDF_TEXT_SENTINEL_41B",
            "SOURCE_TEXT_SENTINEL_41C",
            "RAW_VALUE_SENTINEL_41D",
            "NORMALIZED_PII_SENTINEL_41E",
            "FULL_GEMINI_PROMPT_SENTINEL_41F",
            "FULL_GEMINI_RESPONSE_SENTINEL_41G",
            "RAW_VERIFIER_RESPONSE_SENTINEL_41H",
            "RAW_REVIEWER_NOTE_SENTINEL_41I",
        }
        extraction_payload["view"].update(
            {
                "raw_text": " ".join(
                    [
                        "RAW_OCR_SENTINEL_41A",
                        "RAW_PDF_TEXT_SENTINEL_41B",
                        "FULL_GEMINI_PROMPT_SENTINEL_41F",
                    ]
                ),
                "field_candidates": [
                    {
                        "candidate_id": "privacy-candidate",
                        "label": "Candidate Name",
                        "raw_value": "RAW_VALUE_SENTINEL_41D",
                        "normalized_value": "NORMALIZED_PII_SENTINEL_41E",
                        "source_text": "SOURCE_TEXT_SENTINEL_41C",
                        "confidence": 0.95,
                        "page": 1,
                        "is_pii": True,
                        "requires_verification": True,
                    }
                ],
                "generalized_analysis": {
                    "agent_raw_output": "FULL_GEMINI_RESPONSE_SENTINEL_41G",
                },
            }
        )
        verifier_result = [
            {
                "connector_id": "local_mock_registry",
                "status": "VERIFIED",
                "reason_codes": ["REGISTRY_MATCHED"],
                "assurance_class": "HIGH",
                "response_body": "RAW_VERIFIER_RESPONSE_SENTINEL_41H",
                "raw_response": {"body": "RAW_VERIFIER_RESPONSE_SENTINEL_41H"},
            }
        ]
        gemini_responses = [
            _FakeLlm(
                GeminiDocumentUnderstanding(
                    document_type="academic_credential",
                    summary="FULL_GEMINI_RESPONSE_SENTINEL_41G",
                    explanation="FULL_GEMINI_RESPONSE_SENTINEL_41G",
                    grounding_confidence=0.95,
                    matching_score=0.9,
                    visual_match_probability=0.8,
                )
            ),
            _FakeLlm(
                GeminiNormalizedFieldCollection(
                    fields=[
                        GeminiNormalizedField(
                            field_id="name",
                            label="Name",
                            extracted_value="Alice Rao",
                            normalized_value="Alice Rao",
                            ai_confidence=0.99,
                            grounding_confidence=0.95,
                            mandatory=True,
                        )
                    ]
                )
            ),
            _FakeLlm(
                GeminiCredentialGroupCollection(
                    groups=[
                        {
                            "group_id": "primary-credential",
                            "label": "Primary Credential",
                            "field_ids": ["name"],
                            "connector_id": "local_mock_registry",
                            "claim_type": "identity",
                            "optional": False,
                            "high_assurance": True,
                            "explanation": "FULL_GEMINI_RESPONSE_SENTINEL_41G",
                        }
                    ]
                )
            ),
        ]
        env = {
            "AGENT_ORCHESTRATION_ENABLED": "true",
            "AGENT_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
            "GEMINI_DEMO_RAW_TEXT_ENABLED": "true",
        }

        with patch.dict(os.environ, env, clear=False), patch(
            "backend.app.api.routes.start_verification",
            return_value="STARTED",
        ), patch(
            "backend.app.agent_orchestration.graph.extract_document_payload",
            return_value=extraction_payload,
        ), patch(
            "backend.app.agent_orchestration.graph.build_connector_responses",
            return_value=verifier_result,
        ), patch(
            "backend.app.agent_orchestration.graph._build_structured_gemini_llm",
            side_effect=gemini_responses,
        ):
            run_response = self.client.post(f"/api/v1/verification-sessions/{session_id}/run")

        self.assertEqual(run_response.status_code, 200)
        run_payload = run_response.json()
        self.assertEqual(run_payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertIn(run_payload["final_verdict"]["outcome"], {"GREEN", "AMBER", "RED"})

        reviewer_note = "RAW_REVIEWER_NOTE_SENTINEL_41I should be hashed only"
        review_response = self.client.post(
            f"/api/v1/verification-sessions/{session_id}/review-decision",
            json={"decision": "NEEDS_MANUAL_REVIEW", "reviewer_note": reviewer_note},
        )

        self.assertEqual(review_response.status_code, 200)
        self.assertEqual(review_response.json()["status"], SessionState.MANUAL_REVIEW_REQUIRED)

        db = self.SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            self.assertIsNotNone(session)
            receipt = (
                db.query(AuditReceiptRecord)
                .filter(AuditReceiptRecord.session_id == session_id)
                .first()
            )
            self.assertIsNotNone(receipt)
            events = (
                db.query(AuditEventRecord)
                .filter(AuditEventRecord.session_id == session_id)
                .all()
            )

            self.assertEqual(session.status, SessionState.MANUAL_REVIEW_REQUIRED)
            self.assertIn(session.trust_outcome, {"GREEN", "AMBER", "RED"})
            self.assertIsNone(session.extraction_payload)
            self.assertIsNone(session.connector_payload)
            self.assertIsNone(session.agent_run_summary_payload)
            self.assertIsNone(session.provider_execution_traces_payload)
            self.assertIsNotNone(receipt.reviewer_note_hash)
            self.assertNotEqual(receipt.reviewer_note_hash, reviewer_note)
            self.assertIn(receipt.trust_outcome, {"GREEN", "AMBER", "RED"})
            self.assertIsInstance(receipt.finding_counts, dict)
            self.assertTrue(set(receipt.finding_counts).issuperset({"green", "amber", "red"}))
            self.assertIsInstance(receipt.reason_codes, list)

            persisted_payload = {
                "session": {
                    "status": session.status,
                    "trust_outcome": session.trust_outcome,
                    "reason_codes": session.reason_codes,
                    "connector_ids": session.connector_ids,
                    "workspace_payload": session.workspace_payload,
                    "verification_execution_summary_payload": session.verification_execution_summary_payload,
                    "agent_run_summary_payload": session.agent_run_summary_payload,
                    "provider_execution_traces_payload": session.provider_execution_traces_payload,
                    "extraction_payload": session.extraction_payload,
                    "connector_payload": session.connector_payload,
                },
                "receipt": {
                    "trust_outcome": receipt.trust_outcome,
                    "reason_codes": receipt.reason_codes,
                    "connector_ids": receipt.connector_ids,
                    "reviewer_decision": receipt.reviewer_decision,
                    "reviewer_note_hash": receipt.reviewer_note_hash,
                    "finding_counts": receipt.finding_counts,
                    "receipt_hash": receipt.receipt_hash,
                },
                "events": [event.event_data for event in events],
            }
            serialized = json.dumps(persisted_payload, sort_keys=True, default=str)
            for sentinel in sentinels:
                self.assertNotIn(sentinel, serialized)
        finally:
            db.close()

    def _assert_no_forbidden_keys(self, value, forbidden: set[str]) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                self.assertNotIn(str(key), forbidden)
                self._assert_no_forbidden_keys(nested, forbidden)
        elif isinstance(value, list):
            for nested in value:
                self._assert_no_forbidden_keys(nested, forbidden)

    def _override_get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _create_uploaded_session(self, session_id: str) -> tuple[str, str]:
        file_handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        file_handle.write(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF")
        file_handle.close()

        db = self.SessionLocal()
        try:
            session = SessionModel(
                id=session_id,
                user_id="user-1",
                status=SessionState.UPLOADED_PENDING_REVIEW,
                file_path=str(Path(file_handle.name)),
                filename="demo.pdf",
            )
            db.add(session)
            db.commit()
        finally:
            db.close()

        return session_id, file_handle.name


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.graph import build_generalized_verification_graph
from backend.app.agent_orchestration.policies import AgentRuntimePolicy
from backend.app.agent_orchestration.providers.gemini_pool import GeminiPoolInvocationError, GeminiPoolRateLimitError
from backend.app.agent_orchestration.schemas import FieldDecision, GeminiDocumentUnderstanding, VerifierResult, WorkspacePayload
from backend.app.auth.routes import get_current_user
from backend.app.db.database import Base, get_db
from backend.app.main import app
from backend.app.sessions.constants import SessionState
from backend.app.sessions.models import Session as SessionModel
from backend.app.trust.trust_engine import build_final_verdict


RAW_DEMO_FIXTURE_OCR_SECRET = "RAW_DEMO_FIXTURE_OCR_SECRET"
RAW_DEMO_FIXTURE_CREDENTIAL_VALUE = "RAW_DEMO_FIXTURE_CREDENTIAL_VALUE"
RAW_DEMO_FIXTURE_PROVIDER_BODY = "RAW_DEMO_FIXTURE_PROVIDER_BODY"
RAW_DEMO_FIXTURE_GEMINI_OUTPUT = "RAW_DEMO_FIXTURE_GEMINI_OUTPUT"
RAW_DEMO_FIXTURE_API_KEY = "RAW_DEMO_FIXTURE_API_KEY"
RAW_DEMO_FIXTURE_REVIEWER_NOTE = "RAW_DEMO_FIXTURE_REVIEWER_NOTE"
RAW_FINAL_GEMINI_PROMPT_SECRET = "RAW_FINAL_GEMINI_PROMPT_SECRET"
RAW_FINAL_OCR_TEXT_SECRET = "RAW_FINAL_OCR_TEXT_SECRET"
RAW_FINAL_PROVIDER_BODY_SECRET = "RAW_FINAL_PROVIDER_BODY_SECRET"
RAW_FINAL_CREDENTIAL_VALUE_SECRET = "RAW_FINAL_CREDENTIAL_VALUE_SECRET"
RAW_FINAL_API_KEY_SECRET = "RAW_FINAL_API_KEY_SECRET"
RAW_FINAL_REVIEWER_NOTE_SECRET = "RAW_FINAL_REVIEWER_NOTE_SECRET"


def _runtime_extraction_payload() -> dict:
    return {
        "view": {
            "document_type": "academic_credential",
            "page_count": 1,
            "used_ocr": False,
            "warnings": [],
            "field_details": [
                {"key": "name", "label": "Name", "bounding_boxes": [{"page": 1, "x0": 10, "y0": 10, "x1": 40, "y1": 20}]},
                {"key": "institution", "label": "Institution", "bounding_boxes": [{"page": 1, "x0": 10, "y0": 25, "x1": 50, "y1": 35}]},
                {"key": "credential", "label": "Credential", "bounding_boxes": [{"page": 1, "x0": 10, "y0": 40, "x1": 55, "y1": 50}]},
                {"key": "id", "label": "Document ID", "bounding_boxes": [{"page": 1, "x0": 10, "y0": 55, "x1": 45, "y1": 65}]},
            ],
            "confidence": {"name": 0.92, "institution": 0.93, "credential": 0.91, "id": 0.9},
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


def _payload_with_sentinels() -> dict:
    payload = copy.deepcopy(_runtime_extraction_payload())
    payload["view"]["raw_text"] = RAW_DEMO_FIXTURE_OCR_SECRET
    payload["view"]["generalized_analysis"] = {"agent_raw_output": RAW_DEMO_FIXTURE_GEMINI_OUTPUT}
    payload["provider_raw_response"] = {"body": RAW_DEMO_FIXTURE_PROVIDER_BODY}
    payload["api_key"] = RAW_DEMO_FIXTURE_API_KEY
    payload["reviewer_note"] = RAW_DEMO_FIXTURE_REVIEWER_NOTE
    payload["trust_input"]["fields"][0]["value"] = RAW_DEMO_FIXTURE_CREDENTIAL_VALUE
    payload["view"]["field_details"][0]["source_text"] = RAW_DEMO_FIXTURE_CREDENTIAL_VALUE
    return payload


def _payload_with_final_sentinels() -> dict:
    payload = copy.deepcopy(_runtime_extraction_payload())
    payload["view"]["raw_text"] = f"{RAW_FINAL_OCR_TEXT_SECRET} {RAW_FINAL_GEMINI_PROMPT_SECRET}"
    payload["view"]["generalized_analysis"] = {"agent_raw_output": RAW_FINAL_GEMINI_PROMPT_SECRET}
    payload["provider_raw_response"] = {"body": RAW_FINAL_PROVIDER_BODY_SECRET}
    payload["api_key"] = RAW_FINAL_API_KEY_SECRET
    payload["reviewer_note"] = RAW_FINAL_REVIEWER_NOTE_SECRET
    payload["trust_input"]["fields"][0]["value"] = RAW_FINAL_CREDENTIAL_VALUE_SECRET
    payload["view"]["field_details"][0]["source_text"] = RAW_FINAL_CREDENTIAL_VALUE_SECRET
    return payload


def _policy() -> AgentRuntimePolicy:
    return AgentRuntimePolicy(
        orchestration_enabled=True,
        provider_key="gemini",
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash",
        gemini_demo_raw_text_enabled=True,
    )


def _rate_limit(*_args, **_kwargs):
    raise GeminiPoolRateLimitError("Gemini rate limit encountered for configured key slots")


def _non_rate_limit_error(*_args, **_kwargs):
    raise GeminiPoolInvocationError("Gemini invocation failed")


class GeminiDemoResilienceGraphTests(unittest.TestCase):
    def test_demo_fixture_disabled_preserves_existing_gemini_fallback(self):
        with patch.dict(os.environ, {"GEMINI_DEMO_FIXTURE_ENABLED": "0"}, clear=False), patch(
            "backend.app.agent_orchestration.graph.invoke_gemini_balanced",
            side_effect=_rate_limit,
        ):
            state = build_generalized_verification_graph(policy=_policy()).invoke(
                {
                    "session_id": "session-fixture-disabled",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": _runtime_extraction_payload(),
                }
            )

        self.assertTrue(state["gemini_fallback_used"])
        document = GeminiDocumentUnderstanding.model_validate(state["document_understanding"])
        self.assertEqual(document.summary, "Deterministic document understanding fallback was used.")
        self.assertTrue(any("Gemini fallback applied" in item["message"] for item in state["audit_log"]))

    def test_demo_fixture_enabled_rate_limit_returns_schema_compatible_fallback(self):
        with patch.dict(os.environ, {"GEMINI_DEMO_FIXTURE_ENABLED": "1"}, clear=False), patch(
            "backend.app.agent_orchestration.graph.invoke_gemini_balanced",
            side_effect=_rate_limit,
        ):
            state = build_generalized_verification_graph(policy=_policy()).invoke(
                {
                    "session_id": "session-fixture-enabled",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": _runtime_extraction_payload(),
                }
            )

        document = GeminiDocumentUnderstanding.model_validate(state["document_understanding"])
        self.assertEqual(document.summary, "Demo fixture fallback used after Gemini rate limiting.")
        self.assertTrue(state["credential_groups"])
        self.assertTrue(state["verification_tasks"])
        self.assertTrue(state["gemini_fallback_used"])

    def test_both_gemini_keys_exhausted_does_not_crash_graph_with_fixture_enabled(self):
        with patch.dict(os.environ, {"GEMINI_DEMO_FIXTURE_ENABLED": "1"}, clear=False), patch(
            "backend.app.agent_orchestration.graph.invoke_gemini_balanced",
            side_effect=_rate_limit,
        ):
            state = build_generalized_verification_graph(policy=_policy()).invoke(
                {
                    "session_id": "session-rate-limit-graph",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": _payload_with_sentinels(),
                }
            )

        WorkspacePayload.model_validate(state["workspace_payload"])
        self.assertEqual(state["workspace_payload"]["status"], SessionState.PENDING_HUMAN_REVIEW)
        self._assert_no_sentinels(
            {
                "final_verdict": state["final_verdict"],
                "audit_log": state["audit_log"],
                "gemini_errors": state.get("gemini_errors") or [],
            }
        )

    def test_non_rate_limit_error_with_fixture_enabled_uses_deterministic_fallback_without_final_sentinel_leaks(self):
        with patch.dict(os.environ, {"GEMINI_DEMO_FIXTURE_ENABLED": "1"}, clear=False), patch(
            "backend.app.agent_orchestration.graph.invoke_gemini_balanced",
            side_effect=_non_rate_limit_error,
        ):
            with self.assertLogs("backend.app.agent_orchestration.graph", level="WARNING") as captured:
                state = build_generalized_verification_graph(policy=_policy()).invoke(
                    {
                        "session_id": "session-final-hardening",
                        "filename": "demo.pdf",
                        "file_path": "",
                        "extraction_payload": _payload_with_final_sentinels(),
                    }
                )

        document = GeminiDocumentUnderstanding.model_validate(state["document_understanding"])
        self.assertEqual(document.summary, "Deterministic document understanding fallback was used.")
        self.assertTrue(state["gemini_fallback_used"])
        self.assertTrue(any("Gemini fallback applied" in item["message"] for item in state["audit_log"]))
        self.assertFalse(any("Gemini demo fixture fallback applied" in item["message"] for item in state["audit_log"]))

        serialized = json.dumps(
            {
                "logs": captured.output,
                "gemini_errors": state.get("gemini_errors") or [],
                "audit_log": state["audit_log"],
                "final_verdict": state["final_verdict"],
            },
            default=str,
        )
        for sentinel in _FINAL_SENTINELS:
            self.assertNotIn(sentinel, serialized)

    def _assert_no_sentinels(self, value) -> None:
        serialized = json.dumps(value, default=str)
        for sentinel in _SENTINELS:
            self.assertNotIn(sentinel, serialized)


class GeminiDemoResilienceWorkflowTests(unittest.TestCase):
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

    def test_workflow_reaches_pending_human_review_when_rate_limited_with_fixture_enabled(self):
        payload = self._run_api_with_rate_limit("session-demo-rate-limit", connector_results=[])

        self.assertEqual(payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(payload["final_verdict"]["outcome"], "AMBER")
        self.assertTrue(any("fallback" in item["message"].lower() for item in payload["audit"]))

    def test_ai_only_demo_fallback_cannot_produce_green_without_verifier_evidence(self):
        payload = self._run_api_with_rate_limit("session-demo-ai-only", connector_results=[])

        self.assertEqual(payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(payload["final_verdict"]["outcome"], "AMBER")
        self.assertNotEqual(payload["final_verdict"]["outcome"], "GREEN")

    def test_valid_verifier_backed_evidence_can_still_produce_green(self):
        verifier = VerifierResult(
            task_id="task-name",
            field_id="name",
            connector_id="vit_registry",
            status="VERIFIED",
            verification_confidence=0.95,
            reason_codes=["VERIFIED_BY_PROVIDER"],
            source_api="vit_registry",
            audit_message="Verifier evidence matched this claim.",
            field_ids=["name"],
        )
        decision = FieldDecision(
            field_id="name",
            label="Name",
            extracted_value="Alice Rao",
            normalized_value="Alice Rao",
            status="GREEN",
            ai_confidence=0.95,
            extraction_confidence=0.95,
            verification_confidence=0.95,
            grounding_confidence=1.0,
            final_confidence=0.95,
            reason_codes=[],
            source_api="vit_registry",
        )

        verdict = build_final_verdict([decision], [verifier], False, [])

        self.assertEqual(verdict.outcome, "GREEN")

    def test_provider_mismatch_still_produces_red(self):
        payload = self._run_api_with_rate_limit(
            "session-demo-red",
            connector_results=[
                {
                    "connector_id": "vit_registry",
                    "field_id": "name",
                    "field_ids": ["name"],
                    "status": "MISMATCH",
                    "reason_codes": ["CRITICAL_VERIFIER_MISMATCH"],
                    "assurance_class": "HIGH",
                }
            ],
        )

        self.assertEqual(payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(payload["final_verdict"]["outcome"], "RED")

    def test_serialized_outputs_do_not_contain_demo_fixture_sentinels(self):
        payload = self._run_api_with_rate_limit("session-demo-privacy", connector_results=[])

        db = self.SessionLocal()
        try:
            session = db.query(SessionModel).filter(SessionModel.id == "session-demo-privacy").first()
            self.assertIsNotNone(session)
            serialized = json.dumps(
                {
                    "response": payload,
                    "workspace_payload": session.workspace_payload,
                    "trust_outcome": session.trust_outcome,
                    "reason_codes": session.reason_codes,
                    "connector_ids": session.connector_ids,
                },
                default=str,
            )
        finally:
            db.close()

        for sentinel in _SENTINELS:
            self.assertNotIn(sentinel, serialized)

    def _run_api_with_rate_limit(self, session_id: str, *, connector_results: list[dict], extraction_payload: dict | None = None) -> dict:
        created_session_id, file_path = self._create_uploaded_session(session_id)
        self.addCleanup(lambda: os.path.exists(file_path) and os.remove(file_path))
        env = {
            "AGENT_ORCHESTRATION_ENABLED": "true",
            "AGENT_PROVIDER": "gemini",
            "GEMINI_API_KEY": "test-key",
            "GEMINI_DEMO_FIXTURE_ENABLED": "1",
            "GEMINI_DEMO_RAW_TEXT_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "backend.app.api.routes.start_verification",
            return_value="STARTED",
        ), patch(
            "backend.app.agent_orchestration.graph.extract_document_payload",
            return_value=extraction_payload or _payload_with_sentinels(),
        ), patch(
            "backend.app.agent_orchestration.graph.invoke_gemini_balanced",
            side_effect=_rate_limit,
        ), patch(
            "backend.app.agent_orchestration.graph.build_connector_responses",
            return_value=connector_results,
        ), patch(
            "backend.app.agent_orchestration.workspace._build_completion_values",
            return_value={},
        ):
            response = self.client.post(f"/api/v1/verification-sessions/{created_session_id}/run")

        self.assertEqual(response.status_code, 200)
        return response.json()

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


_SENTINELS = {
    RAW_DEMO_FIXTURE_OCR_SECRET,
    RAW_DEMO_FIXTURE_CREDENTIAL_VALUE,
    RAW_DEMO_FIXTURE_PROVIDER_BODY,
    RAW_DEMO_FIXTURE_GEMINI_OUTPUT,
    RAW_DEMO_FIXTURE_API_KEY,
    RAW_DEMO_FIXTURE_REVIEWER_NOTE,
}

_FINAL_SENTINELS = {
    RAW_FINAL_GEMINI_PROMPT_SECRET,
    RAW_FINAL_OCR_TEXT_SECRET,
    RAW_FINAL_PROVIDER_BODY_SECRET,
    RAW_FINAL_CREDENTIAL_VALUE_SECRET,
    RAW_FINAL_API_KEY_SECRET,
    RAW_FINAL_REVIEWER_NOTE_SECRET,
}


if __name__ == "__main__":
    unittest.main()

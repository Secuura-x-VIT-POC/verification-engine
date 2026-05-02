import json
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.graph import (  # noqa: E402
    _build_workspace_payload,
    _gemini_confidence_fusion,
    _policy_verdict,
    _run_verifier_apis,
)
from backend.app.agent_orchestration.sanitization import sanitize_workspace_payload  # noqa: E402
from backend.app.agent_orchestration.schemas import WorkspacePayload  # noqa: E402
from backend.app.audit.hmac_utils import generate_nonce  # noqa: E402
from backend.app.audit.receipt_generator import generate_receipt  # noqa: E402
from backend.app.audit.service import hash_reviewer_note, store_audit_bundle, upsert_final_review_receipt  # noqa: E402
from backend.app.db.database import Base  # noqa: E402
from backend.app.sessions.constants import SessionState  # noqa: E402
from backend.app.sessions.models import AuditReceiptRecord, Session as SessionModel  # noqa: E402
from backend.app.trust.trust_engine import evaluate_trust  # noqa: E402


RAW_OCR = "RAW_PRE_PHASE7_OCR_SECRET"
RAW_CREDENTIAL = "RAW_PRE_PHASE7_CREDENTIAL_VALUE"
RAW_NORMALIZED = "RAW_PRE_PHASE7_NORMALIZED_VALUE"
RAW_PROVIDER = "RAW_PRE_PHASE7_PROVIDER_BODY"
RAW_GEMINI = "RAW_PRE_PHASE7_GEMINI_OUTPUT"
RAW_REVIEWER_NOTE = "RAW_PRE_PHASE7_REVIEWER_NOTE"


class PrePhase7IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def test_receipt_generator_returns_and_persists_safe_review_fields(self):
        note_hash = hash_reviewer_note(RAW_REVIEWER_NOTE)
        finding_counts = {"green": 0, "amber": 1, "red": 0}
        receipt = generate_receipt(
            "session-receipt",
            "reviewer-1",
            "document-commitment",
            {
                "outcome": "AMBER",
                "reason_codes": ["AI_ONLY_EVIDENCE"],
                "connector_ids": ["local_mock"],
                "finding_counts": finding_counts,
                "reviewer_decision": "MANUAL_REVIEW_REQUIRED",
                "reviewer_note_hash": note_hash,
            },
        )

        self.assertEqual(receipt["finding_counts"], finding_counts)
        self.assertEqual(receipt["reviewer_decision"], "MANUAL_REVIEW_REQUIRED")
        self.assertEqual(receipt["reviewer_note_hash"], note_hash)

        db = self.SessionLocal()
        try:
            store_audit_bundle(db, receipt, generate_nonce())
            db.commit()
            persisted = db.query(AuditReceiptRecord).filter_by(session_id="session-receipt").one()
            self.assertEqual(persisted.finding_counts, finding_counts)
            self.assertEqual(persisted.reviewer_decision, "MANUAL_REVIEW_REQUIRED")
            self.assertEqual(persisted.reviewer_note_hash, note_hash)
            self.assertNotIn(RAW_REVIEWER_NOTE, json.dumps(receipt, sort_keys=True, default=str))
        finally:
            db.close()

    def test_review_decision_counts_prefer_workspace_summary_without_execution_summary(self):
        db = self.SessionLocal()
        try:
            session = SessionModel(
                id="session-review-counts",
                user_id="user-1",
                status=SessionState.PENDING_HUMAN_REVIEW,
                trust_outcome="AMBER",
                reason_codes=["NO_PROVIDER_AVAILABLE"],
                connector_ids=["manual_review"],
                document_commitment="document-commitment",
                workspace_payload={
                    "session_id": "session-review-counts",
                    "status": SessionState.PENDING_HUMAN_REVIEW,
                    "summary": {"green_count": 2, "amber_count": 1, "red_count": 0},
                },
                verification_execution_summary_payload=None,
            )
            db.add(session)
            db.commit()

            receipt = upsert_final_review_receipt(
                db,
                session,
                reviewer_ref="reviewer-1",
                reviewer_decision="MANUAL_REVIEW_REQUIRED",
                reviewer_note=RAW_REVIEWER_NOTE,
            )
            db.commit()

            serialized = json.dumps(
                {
                    "receipt": {
                        "finding_counts": receipt.finding_counts,
                        "reviewer_decision": receipt.reviewer_decision,
                        "reviewer_note_hash": receipt.reviewer_note_hash,
                    }
                },
                sort_keys=True,
                default=str,
            )
            self.assertEqual(receipt.finding_counts, {"green": 2, "amber": 1, "red": 0})
            self.assertIsNotNone(receipt.reviewer_note_hash)
            self.assertNotIn(RAW_REVIEWER_NOTE, serialized)
        finally:
            db.close()

    def test_unknown_legacy_provider_status_becomes_amber_without_crashing(self):
        with patch(
            "backend.app.agent_orchestration.graph.build_connector_responses",
            return_value=[
                {
                    "connector_id": "legacy_provider",
                    "field_id": "field-name",
                    "status": "NOT_A_REAL_STATUS",
                    "reason_codes": [],
                    "raw_provider_body": RAW_PROVIDER,
                }
            ],
        ):
            state = self._graph_state()
            state.update(_run_verifier_apis(state))
            state.update(_gemini_confidence_fusion(state))
            state.update(_policy_verdict(state))
            state.update(_build_workspace_payload(state))

        workspace = sanitize_workspace_payload(WorkspacePayload.model_validate(state["workspace_payload"]))
        serialized = json.dumps(workspace.model_dump(mode="json"), sort_keys=True)

        self.assertEqual(workspace.status, SessionState.PENDING_HUMAN_REVIEW)
        self.assertEqual(workspace.final_verdict.outcome, "AMBER")
        self.assertIn("PROVIDER_RESULT_MALFORMED", workspace.final_verdict.reason_codes)
        self.assertTrue(any(field.manual_review_required for field in workspace.fields))
        self.assertNotIn(RAW_PROVIDER, serialized)

    def test_missing_required_claim_stays_amber_even_with_generic_legacy_verifier(self):
        result = evaluate_trust(
            {
                "fields": {"name": ""},
                "confidence": {"name": 1.0},
                "raw_text": RAW_OCR,
                "gemini_raw_response": RAW_GEMINI,
            },
            {
                "connector_id": "legacy_provider",
                "status": "VERIFIED",
                "reason_codes": ["REGISTRY_MATCH"],
                "raw_provider_body": RAW_PROVIDER,
            },
            {"required_fields": ["name"]},
        )

        finding = result["claim_findings"][0]
        serialized = json.dumps(result, sort_keys=True)
        self.assertEqual(finding["status"], "AMBER")
        self.assertTrue(finding["manual_review_required"])
        self.assertIn("REQUIRED_CLAIM_MISSING", finding["reason_codes"])
        self.assertIn("MANUAL_REVIEW_REQUIRED", finding["reason_codes"])
        self.assertFalse(finding["verifier_refs"])
        self.assertNotEqual(result["outcome"], "GREEN")
        self._assert_no_sentinels(serialized)

    def test_ai_only_valid_evidence_and_mismatch_trust_outcomes(self):
        ai_only = evaluate_trust(
            {"fields": {"name": RAW_CREDENTIAL}, "confidence": {"name": 1.0}},
            None,
            {"required_fields": ["name"]},
        )
        green = evaluate_trust(
            {"fields": {"name": "safe"}, "confidence": {"name": 1.0}},
            {
                "task_id": "task-name",
                "credential_id": "name",
                "executed_provider_key": "local_mock",
                "task_status": "SUCCEEDED",
                "audit_status": "VERIFIED",
                "outcome_color": "green",
                "confidence": 0.99,
                "reason_codes": ["PROVIDER_VERIFIED"],
                "raw_result_summary": {"raw_provider_body": RAW_PROVIDER},
            },
            {"required_fields": ["name"]},
        )
        red = evaluate_trust(
            {"fields": {"name": "safe", "id": "safe"}, "confidence": {"name": 1.0, "id": 1.0}},
            [
                {
                    "task_id": "task-name",
                    "credential_id": "name",
                    "executed_provider_key": "local_mock",
                    "task_status": "SUCCEEDED",
                    "audit_status": "VERIFIED",
                    "outcome_color": "green",
                    "confidence": 0.99,
                    "reason_codes": ["PROVIDER_VERIFIED"],
                },
                {
                    "task_id": "task-id",
                    "credential_id": "id",
                    "executed_provider_key": "local_mock",
                    "task_status": "SUCCEEDED",
                    "audit_status": "MISMATCH",
                    "outcome_color": "red",
                    "confidence": 0.1,
                    "reason_codes": ["PROVIDER_MISMATCH"],
                    "raw_result_summary": {"raw_provider_body": RAW_PROVIDER},
                },
            ],
            {"required_fields": ["name", "id"]},
        )

        self.assertEqual(ai_only["outcome"], "AMBER")
        self.assertIn("AI_ONLY_EVIDENCE", ai_only["claim_findings"][0]["reason_codes"])
        self.assertEqual(green["outcome"], "GREEN")
        self.assertTrue(green["verifier_backed_evidence"])
        self.assertEqual(red["outcome"], "RED")
        self.assertEqual(red["finding_counts"]["red"], 1)
        self._assert_no_sentinels(json.dumps({"ai": ai_only, "green": green, "red": red}, sort_keys=True))

    def test_workspace_status_and_serialized_outputs_are_privacy_safe(self):
        state = self._graph_state(
            extracted_value=RAW_CREDENTIAL,
            normalized_value=RAW_NORMALIZED,
            verifier_results=[
                {
                    "task_id": "task-name",
                    "field_id": "field-name",
                    "connector_id": "local_mock",
                    "status": "VERIFIED",
                    "verification_confidence": 0.98,
                    "reason_codes": ["PROVIDER_VERIFIED"],
                    "source_api": "local_mock",
                }
            ],
        )
        state["sanitized_extraction"]["view"]["raw_text"] = RAW_OCR
        state["sanitized_extraction"]["view"]["generalized_analysis"] = {"agent_raw_output": RAW_GEMINI}
        state.update(_gemini_confidence_fusion(state))
        state.update(_policy_verdict(state))
        state.update(_build_workspace_payload(state))

        workspace = sanitize_workspace_payload(WorkspacePayload.model_validate(state["workspace_payload"]))
        payload = workspace.model_dump(mode="json")
        serialized = json.dumps(
            {
                "workspace": payload,
                "audit": {
                    "reviewer_note_hash": hash_reviewer_note(RAW_REVIEWER_NOTE),
                    "finding_counts": {
                        "green": payload["summary"]["green_count"],
                        "amber": payload["summary"]["amber_count"],
                        "red": payload["summary"]["red_count"],
                    },
                },
            },
            sort_keys=True,
        )

        self.assertEqual(payload["status"], SessionState.PENDING_HUMAN_REVIEW)
        self.assertIn(payload["final_verdict"]["outcome"], {"GREEN", "AMBER", "RED"})
        self.assertEqual(payload["final_verdict"]["outcome"], "GREEN")
        self._assert_no_sentinels(serialized)

    def _graph_state(self, *, extracted_value="safe", normalized_value="safe", verifier_results=None):
        return {
            "session_id": "session-pre-phase7",
            "filename": "pre-phase7.pdf",
            "document_understanding": {
                "document_type": "identity_document",
                "unsafe_or_malformed": False,
                "matching_score": 0.9,
                "visual_match_probability": 0.9,
            },
            "normalized_fields": [
                {
                    "field_id": "field-name",
                    "label": "Candidate name",
                    "extracted_value": extracted_value,
                    "normalized_value": normalized_value,
                    "ai_confidence": 1.0,
                    "grounding_confidence": 1.0,
                    "mandatory": True,
                    "bounding_boxes": [{"page": 1, "x0": 1, "y0": 2, "x1": 3, "y1": 4}],
                }
            ],
            "extraction_payload": {
                "fields": {"field-name": extracted_value},
                "confidence": {"field-name": 1.0},
            },
            "sanitized_extraction": {
                "view": {
                    "document_type": "identity_document",
                    "page_count": 1,
                    "used_ocr": True,
                    "warnings": [],
                }
            },
            "verifier_results": list(verifier_results or []),
            "policy": {},
            "audit_log": [{"stage": "test", "message": f"safe audit {datetime.utcnow().isoformat()}", "timestamp": "now"}],
        }

    def _assert_no_sentinels(self, serialized: str):
        for sentinel in {
            RAW_OCR,
            RAW_CREDENTIAL,
            RAW_NORMALIZED,
            RAW_PROVIDER,
            RAW_GEMINI,
            RAW_REVIEWER_NOTE,
        }:
            self.assertNotIn(sentinel, serialized)


if __name__ == "__main__":
    unittest.main()

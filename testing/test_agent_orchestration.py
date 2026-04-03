import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.service import build_agent_pass_a_artifacts
from backend.app.api.routes import router
from backend.app.auth.routes import get_current_user
from backend.app.db.database import Base, get_db
from backend.app.inference.nvidia import NvidiaInferenceError
from backend.app.sessions.constants import SessionState
from backend.app.sessions.models import Session as SessionModel
from backend.app.verification_domain.service import (
    build_and_persist_final_analysis,
    build_and_persist_initial_analysis,
    build_credentials,
    build_document_profile,
    build_verification_plan,
)
from backend.app.workflow.runtime import run_verification


def _sample_academic_extraction_payload() -> dict:
    return {
        "document_type": "academic_credential",
        "page_count": 1,
        "used_ocr": False,
        "field_candidates": [
            {
                "candidate_id": "cand-name",
                "label": "Candidate Name",
                "category": "person_name",
                "raw_value": "Kanak Sharma",
                "normalized_value": "Kanak Sharma",
                "source_text": "Candidate Name: Kanak Sharma",
                "confidence": 0.98,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 80, "y1": 20},
                "is_pii": True,
                "requires_verification": True,
                "verification_reason": "Identity claim",
            },
            {
                "candidate_id": "cand-institution",
                "label": "Institution",
                "category": "issuer",
                "raw_value": "VIT Vellore",
                "normalized_value": "VIT Vellore",
                "source_text": "Institution: VIT Vellore",
                "confidence": 0.97,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 25, "x1": 120, "y1": 35},
                "is_pii": False,
                "requires_verification": True,
                "verification_reason": "Issuer claim",
            },
            {
                "candidate_id": "cand-credential",
                "label": "Credential",
                "category": "credential_title",
                "raw_value": "BTech",
                "normalized_value": "BTech",
                "source_text": "Credential: BTech",
                "confidence": 0.96,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 40, "x1": 90, "y1": 50},
                "is_pii": False,
                "requires_verification": True,
                "verification_reason": "Academic credential",
            },
            {
                "candidate_id": "cand-id",
                "label": "Document ID",
                "category": "registration_number",
                "raw_value": "22BCE1234",
                "normalized_value": "22BCE1234",
                "source_text": "Document ID: 22BCE1234",
                "confidence": 0.95,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 55, "x1": 90, "y1": 65},
                "is_pii": False,
                "requires_verification": True,
                "verification_reason": "Academic identifier",
            },
        ],
    }


def _sample_unknown_but_address_like_payload() -> dict:
    return {
        "document_type": "utility_document",
        "page_count": 1,
        "used_ocr": False,
        "field_candidates": [
            {
                "candidate_id": "cand-address",
                "label": "Residency Proof Number",
                "category": "address",
                "raw_value": "ADDR-42",
                "normalized_value": "ADDR-42",
                "source_text": "Residency Proof Number: ADDR-42",
                "confidence": 0.91,
                "page": 1,
                "bounding_box": {"page": 1, "x0": 10, "y0": 10, "x1": 120, "y1": 20},
                "is_pii": True,
                "requires_verification": True,
                "verification_reason": "Address-like claim",
            }
        ],
    }


def _sample_connector_payload() -> list[dict]:
    return [
        {
            "connector_id": "vit_registry",
            "status": "VERIFIED",
            "reason_codes": ["REGISTRY_MATCH"],
            "matched_claims": {
                "name": "Kanak Sharma",
                "institution": "VIT Vellore",
                "degree": "BTech",
                "document_id": "22BCE1234",
            },
            "mismatched_claims": {},
            "assurance_class": "HIGH",
        }
    ]


def _sample_runtime_extraction_payload() -> dict:
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
            "field_details": [
                {
                    "key": "candidate-name",
                    "label": "Candidate Name",
                    "value": "Kanak Sharma",
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
                    "raw_value": "Kanak Sharma",
                    "normalized_value": "Kanak Sharma",
                    "source_text": "Candidate Name: Kanak Sharma",
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
                    "raw_value": "VIT Vellore",
                    "normalized_value": "VIT Vellore",
                    "source_text": "Institution: VIT Vellore",
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
                    "raw_value": "BTech",
                    "normalized_value": "BTech",
                    "source_text": "Credential: BTech",
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
                    "raw_value": "22BCE1234",
                    "normalized_value": "22BCE1234",
                    "source_text": "Document ID: 22BCE1234",
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


class AgentGraphTests(unittest.TestCase):
    def test_langgraph_deterministic_pass_a_returns_structured_outputs(self):
        extraction_payload = _sample_unknown_but_address_like_payload()
        credentials = build_credentials("session-agent-1", extraction_payload)
        verification_plan = build_verification_plan(
            "session-agent-1",
            extraction_payload,
            credentials=credentials,
        )
        document_profile = build_document_profile(
            "session-agent-1",
            extraction_payload,
            credentials=credentials,
            verification_plan=verification_plan,
        )

        artifacts = build_agent_pass_a_artifacts(
            "session-agent-1",
            extraction_payload=extraction_payload,
            document_profile=document_profile,
            credentials=credentials,
            verification_plan=verification_plan,
        )

        self.assertEqual(artifacts["run_summary"].run_status, "READY")
        self.assertEqual(
            artifacts["run_summary"].nodes_executed,
            [
                "input_normalization",
                "document_understanding",
                "credential_grouping",
                "route_recommendation",
                "explanation_synthesis",
                "output_consolidation",
            ],
        )
        self.assertGreater(len(artifacts["credential_candidates"].candidates), 0)
        self.assertGreater(len(artifacts["route_recommendations"].recommendations), 0)

    def test_nvidia_provider_selection_falls_back_to_deterministic_when_disabled(self):
        extraction_payload = _sample_academic_extraction_payload()
        credentials = build_credentials("session-agent-2", extraction_payload)
        verification_plan = build_verification_plan(
            "session-agent-2",
            extraction_payload,
            credentials=credentials,
        )
        document_profile = build_document_profile(
            "session-agent-2",
            extraction_payload,
            credentials=credentials,
            verification_plan=verification_plan,
        )

        with patch.dict(
            os.environ,
            {
                "AGENT_PROVIDER": "nvidia",
                "AGENT_EXTERNAL_PROVIDER_ENABLED": "0",
            },
            clear=False,
        ):
            artifacts = build_agent_pass_a_artifacts(
                "session-agent-2",
                extraction_payload=extraction_payload,
                document_profile=document_profile,
                credentials=credentials,
                verification_plan=verification_plan,
            )

        self.assertEqual(artifacts["run_summary"].provider_used, "deterministic")
        self.assertTrue(artifacts["run_summary"].fallback_used)
        self.assertTrue(artifacts["run_summary"].warnings)

    def test_nvidia_provider_uses_minimax_when_configured(self):
        extraction_payload = _sample_academic_extraction_payload()
        credentials = build_credentials("session-agent-nvidia", extraction_payload)
        verification_plan = build_verification_plan(
            "session-agent-nvidia",
            extraction_payload,
            credentials=credentials,
        )
        document_profile = build_document_profile(
            "session-agent-nvidia",
            extraction_payload,
            credentials=credentials,
            verification_plan=verification_plan,
        )

        with patch.dict(
            os.environ,
            {
                "AGENT_PROVIDER": "nvidia",
                "AGENT_EXTERNAL_PROVIDER_ENABLED": "1",
                "NVIDIA_API_KEY": "demo-key",
                "NVIDIA_REASONING_MODEL": "minimaxai/minimax-m2.5",
            },
            clear=False,
        ), patch(
            "backend.app.agent_orchestration.providers.nvidia.NvidiaChatClient.chat_json",
            side_effect=[
                {
                    "document_type_guess": "academic_credential",
                    "document_family_guess": "academic_document",
                    "confidence": 0.91,
                    "detected_sections": ["identity_section", "credential_section"],
                    "detected_entities": [{"label": "Candidate Name", "category": "identity", "credential_id": "cand-name"}],
                    "pii_signals": ["Candidate Name"],
                    "credential_candidates": ["candidate-cand-name"],
                    "reasoning_summary": "NVIDIA reasoning summarized the academic document conservatively.",
                    "manual_review_recommended": False,
                },
                {
                    "candidates": [
                        {
                            "candidate_id": "candidate-cand-name",
                            "label": "Candidate Name",
                            "category": "identity",
                            "source_fields": ["Candidate Name"],
                            "grouped_field_ids": ["cand-name"],
                            "grouped_values": {"Candidate Name": "Kanak Sharma"},
                            "confidence": 0.9,
                            "verification_recommended": True,
                            "verification_reason": "Identity field should be verified.",
                            "possible_verifier_keys": ["identity_db"],
                            "ambiguity_flags": [],
                        }
                    ]
                },
                {
                    "recommendations": [
                        {
                            "candidate_id": "candidate-cand-name",
                            "recommended_verifier_key": "identity_db",
                            "alternative_verifier_keys": ["manual_review"],
                            "route_reason": "Identity candidate should use the bounded identity verifier.",
                            "confidence": 0.89,
                            "manual_review_recommended": False,
                        }
                    ]
                },
                {
                    "explanations": [
                        {
                            "target_type": "document",
                            "target_id": "session-agent-nvidia",
                            "explanation_kind": "document_understanding",
                            "summary": "MiniMax returned a bounded document-understanding summary.",
                            "structured_reasons": ["academic_credential"],
                            "caution_notes": [],
                        }
                    ]
                },
            ],
        ):
            artifacts = build_agent_pass_a_artifacts(
                "session-agent-nvidia",
                extraction_payload=extraction_payload,
                document_profile=document_profile,
                credentials=credentials,
                verification_plan=verification_plan,
            )

        self.assertEqual(artifacts["run_summary"].provider_used, "nvidia")
        self.assertEqual(artifacts["run_summary"].reasoning_model_used, "minimaxai/minimax-m2.5")
        self.assertFalse(artifacts["run_summary"].fallback_used)
        self.assertGreater(len(artifacts["credential_candidates"].candidates), 0)

    def test_nvidia_runtime_failure_reruns_deterministic_provider(self):
        extraction_payload = _sample_academic_extraction_payload()
        extraction_payload["enrichment_metadata"] = {
            "pii_enrichment_used": True,
            "pii_model_used": "nvidia/gliner-pii",
        }
        credentials = build_credentials("session-agent-fallback", extraction_payload)
        verification_plan = build_verification_plan(
            "session-agent-fallback",
            extraction_payload,
            credentials=credentials,
        )
        document_profile = build_document_profile(
            "session-agent-fallback",
            extraction_payload,
            credentials=credentials,
            verification_plan=verification_plan,
        )

        with patch.dict(
            os.environ,
            {
                "AGENT_PROVIDER": "nvidia",
                "AGENT_EXTERNAL_PROVIDER_ENABLED": "1",
                "NVIDIA_API_KEY": "demo-key",
            },
            clear=False,
        ), patch(
            "backend.app.agent_orchestration.providers.nvidia.NvidiaChatClient.chat_json",
            side_effect=NvidiaInferenceError("network_error", "network down"),
        ):
            artifacts = build_agent_pass_a_artifacts(
                "session-agent-fallback",
                extraction_payload=extraction_payload,
                document_profile=document_profile,
                credentials=credentials,
                verification_plan=verification_plan,
            )

        self.assertEqual(artifacts["run_summary"].provider_used, "deterministic")
        self.assertEqual(artifacts["run_summary"].reasoning_model_used, "deterministic")
        self.assertTrue(artifacts["run_summary"].fallback_used)
        self.assertTrue(artifacts["run_summary"].pii_enrichment_used)
        self.assertEqual(artifacts["run_summary"].pii_model_used, "nvidia/gliner-pii")
        self.assertTrue(artifacts["run_summary"].warnings)


class AgentPersistenceAndApiTests(unittest.TestCase):
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

    def test_initial_analysis_persists_agent_artifacts_and_enriches_route(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="session-agent-persist",
            user_id="user-1",
            status=SessionState.VERIFYING,
            extraction_payload=_sample_unknown_but_address_like_payload(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        build_and_persist_initial_analysis(session)
        db.commit()
        db.refresh(session)

        self.assertEqual(session.agent_run_status, "READY")
        self.assertIsNotNone(session.agent_document_understanding_payload)
        self.assertIsNotNone(session.agent_credential_candidates_payload)
        self.assertIsNotNone(session.agent_route_recommendations_payload)
        self.assertIsNotNone(session.agent_run_summary_payload)
        self.assertEqual(
            session.generalized_credentials_payload["credentials"][0]["category"],
            "address",
        )
        self.assertEqual(
            session.verification_plan_payload["tasks"][0]["verifier_key"],
            "address_check",
        )
        self.assertIn(
            "agent_assisted",
            session.verification_plan_payload["tasks"][0]["input_payload"],
        )
        db.close()

    def test_final_analysis_merges_agent_explanations_into_audits(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="session-agent-final",
            user_id="user-1",
            status=SessionState.VERIFIED_GREEN,
            extraction_payload=_sample_academic_extraction_payload(),
            connector_payload=_sample_connector_payload(),
            trust_outcome="GREEN",
            reason_codes=["CONNECTOR_VERIFIED"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        build_and_persist_initial_analysis(session)
        build_and_persist_final_analysis(session)
        db.commit()
        db.refresh(session)

        first_audit = session.credential_audits_payload["audits"][0]
        self.assertIn("Agent-assisted note:", first_audit["explanation"])
        self.assertTrue(
            any(item["source"] == "agent_orchestration" for item in first_audit["evidence"])
        )
        self.assertIsNotNone(session.agent_explanations_payload)
        db.close()

    def test_agent_endpoints_return_safe_empty_payloads(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="session-agent-empty",
            user_id="user-1",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.close()

        understanding = self.client.get("/session/session-agent-empty/agent-document-understanding")
        candidates = self.client.get("/session/session-agent-empty/agent-credential-candidates")
        routes = self.client.get("/session/session-agent-empty/agent-route-recommendations")
        status = self.client.get("/session/session-agent-empty/agent-run-status")

        self.assertEqual(understanding.status_code, 200)
        self.assertEqual(understanding.json()["document_type_guess"], "unknown")
        self.assertEqual(candidates.json()["candidates"], [])
        self.assertEqual(routes.json()["recommendations"], [])
        self.assertEqual(status.json()["agent_run_status"], "NOT_STARTED")

    def _override_get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


class AgentFailureWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()
        self.engine.dispose()

    def test_agent_failure_does_not_block_verifier_execution_or_trust(self):
        db = self.SessionLocal()
        session = SessionModel(
            id="session-agent-failure",
            user_id="user-1",
            status=SessionState.UPLOADED_PENDING_REVIEW,
            filename="doc.pdf",
            file_path=self._write_document("doc.pdf"),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        with patch(
            "backend.app.workflow.runtime.extract_document_payload",
            return_value=_sample_runtime_extraction_payload(),
        ), patch(
            "backend.app.workflow.runtime.build_connector_responses",
            return_value=_sample_connector_payload(),
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
        ), patch(
            "backend.app.verification_domain.service.build_and_persist_agent_pass_a",
            side_effect=RuntimeError("agent unavailable"),
        ), patch(
            "backend.app.verification_domain.service.build_and_persist_agent_pass_b",
            side_effect=RuntimeError("agent unavailable"),
        ):
            result = run_verification(db, session, "worker-1")

        db.refresh(session)
        self.assertEqual(result.status, SessionState.VERIFIED_GREEN)
        self.assertEqual(session.verification_execution_status, "READY")
        self.assertEqual(session.agent_run_status, "FAILED")
        self.assertEqual(session.trust_outcome, "GREEN")
        db.close()

    def _write_document(self, filename: str) -> str:
        path = Path(self.temp_dir.name) / filename
        path.write_bytes(b"%PDF-1.4\n%mock document\n")
        return str(path)


if __name__ == "__main__":
    unittest.main()

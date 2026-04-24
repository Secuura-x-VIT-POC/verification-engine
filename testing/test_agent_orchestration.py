import json
import os
import sys
import unittest
from unittest.mock import patch

from pydantic import ValidationError


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.graph import (
    build_generalized_verification_graph,
    build_gemini_normalization_graph,
)
from backend.app.agent_orchestration.policies import AgentRuntimePolicy
from backend.app.agent_orchestration.schemas import FieldDecision, WorkspacePayload
from backend.app.agent_orchestration.service import normalize_extraction_payload


def _runtime_payload() -> dict:
    return {
        "view": {
            "document_type": "academic_credential",
            "fields": {"name": "Raw Name"},
            "confidence": {"name": 0.7},
        },
        "trust_input": {
            "fields": [
                {"name": "name", "value": "Raw Name", "is_mandatory": True, "is_grounded": True, "confidence": 0.7},
                {"name": "institution", "value": "", "is_mandatory": True, "is_grounded": False, "confidence": 0},
                {"name": "credential", "value": "", "is_mandatory": True, "is_grounded": False, "confidence": 0},
                {"name": "date", "value": "", "is_mandatory": False, "is_grounded": False, "confidence": 0},
                {"name": "id", "value": "", "is_mandatory": True, "is_grounded": False, "confidence": 0},
            ],
        },
        "connector_input": {"name": "Raw Name", "degree": "", "institution": "", "document_id": ""},
    }


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeLlm:
    def __init__(self, payload):
        self.payload = payload

    def invoke(self, _prompt):
        return _FakeMessage(json.dumps(self.payload))


class GeminiNormalizationTests(unittest.TestCase):
    def test_graph_accepts_strict_valid_output(self):
        llm_payload = {
            "document_type": "academic_credential",
            "fields": {
                "name": "Kanak Sharma",
                "institution": "VIT Vellore",
                "credential": "BTech",
                "date": "2024",
                "id": "22BCE1234",
            },
            "confidence": {
                "name": 0.99,
                "institution": 0.98,
                "credential": 0.97,
                "date": 0.8,
                "id": 0.96,
            },
            "connector_input": {
                "name": "Kanak Sharma",
                "degree": "BTech",
                "institution": "VIT Vellore",
                "document_id": "22BCE1234",
            },
            "ambiguities": [],
        }

        with patch(
            "backend.app.agent_orchestration.graph._build_gemini_llm",
            return_value=_FakeLlm(llm_payload),
        ):
            result = build_gemini_normalization_graph().invoke({"raw_extraction": _runtime_payload()})

        normalized = result["normalized_extraction"]
        self.assertFalse(result["fallback_used"])
        self.assertEqual(normalized["connector_input"]["institution"], "VIT Vellore")
        self.assertEqual(normalized["trust_input"]["fields"][0]["value"], "Kanak Sharma")

    def test_graph_rejects_malformed_output_and_falls_back(self):
        malformed_payload = {
            "document_type": "academic_credential",
            "fields": {
                "name": "Kanak Sharma",
                "institution": "VIT Vellore",
                "credential": "BTech",
                "date": "1899",
            },
            "confidence": {"name": 1.2},
            "connector_input": {"name": "Kanak Sharma"},
            "ambiguities": "not-a-list",
        }
        raw_payload = _runtime_payload()

        with patch(
            "backend.app.agent_orchestration.graph._build_gemini_llm",
            return_value=_FakeLlm(malformed_payload),
        ):
            result = build_gemini_normalization_graph().invoke({"raw_extraction": raw_payload})

        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["normalized_extraction"], raw_payload)
        self.assertTrue(result["validation_errors"])

    def test_service_falls_back_when_gemini_dependency_or_call_fails(self):
        raw_payload = _runtime_payload()

        with patch(
            "backend.app.agent_orchestration.graph._build_gemini_llm",
            side_effect=RuntimeError("gemini unavailable"),
        ):
            result = normalize_extraction_payload(raw_payload)

        self.assertEqual(result, raw_payload)

    def test_generalized_graph_falls_back_when_api_key_is_missing(self):
        policy = AgentRuntimePolicy(
            orchestration_enabled=True,
            provider_key="gemini",
            gemini_api_key=None,
            gemini_model="gemini-2.5-flash",
            gemini_demo_raw_text_enabled=True,
        )
        graph = build_generalized_verification_graph(policy=policy)
        state = graph.invoke(
            {
                "session_id": "session-1",
                "filename": "demo.pdf",
                "file_path": "",
                "extraction_payload": _runtime_payload() | {"view": {"document_type": "academic_credential", "page_count": 1, "used_ocr": False, "warnings": [], "field_details": []}},
            }
        )

        self.assertTrue(state["gemini_fallback_used"])
        workspace = WorkspacePayload.model_validate(state["workspace_payload"])
        self.assertEqual(workspace.session_id, "session-1")

    def test_workspace_schema_validation_rejects_invalid_status(self):
        with self.assertRaises(ValidationError):
            FieldDecision(
                field_id="name",
                label="Name",
                extracted_value="Alice",
                normalized_value="Alice",
                status="BLUE",
                ai_confidence=0.8,
                extraction_confidence=0.8,
                verification_confidence=0.8,
                grounding_confidence=0.8,
                final_confidence=0.8,
                reason_codes=[],
                source_api=None,
                audit_message="invalid",
                bounding_boxes=[],
            )


if __name__ == "__main__":
    unittest.main()

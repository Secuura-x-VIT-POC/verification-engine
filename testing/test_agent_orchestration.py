import json
import os
import sys
import unittest
from unittest.mock import patch


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.graph import build_gemini_normalization_graph
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


if __name__ == "__main__":
    unittest.main()

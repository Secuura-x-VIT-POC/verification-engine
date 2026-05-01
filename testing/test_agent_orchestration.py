import os
import sys
import unittest
from unittest.mock import patch

from pydantic import ValidationError


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.graph import build_generalized_verification_graph
from backend.app.agent_orchestration.policies import AgentRuntimePolicy
from backend.app.agent_orchestration.schemas import (
    FieldDecision,
    GeminiCredentialGroupCollection,
    GeminiDocumentUnderstanding,
    GeminiNormalizedField,
    GeminiNormalizedFieldCollection,
    SemanticNormalizedClaimCollection,
    WorkspacePayload,
)
from backend.app.agent_orchestration.semantic_normalization import normalize_claims_semantically
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


class _FakeLlm:
    def __init__(self, response):
        self.response = response

    def invoke(self, _prompt):
        return self.response


class GeminiNormalizationTests(unittest.TestCase):
    def test_generalized_graph_accepts_mocked_gemini_structured_outputs(self):
        policy = AgentRuntimePolicy(
            orchestration_enabled=True,
            provider_key="gemini",
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-flash",
            gemini_demo_raw_text_enabled=True,
        )
        responses = [
            _FakeLlm(
                GeminiDocumentUnderstanding(
                    document_type="academic_credential",
                    summary="Credential document",
                    explanation="Structured Gemini output accepted.",
                    grounding_confidence=0.9,
                    matching_score=0.8,
                    visual_match_probability=0.7,
                )
            ),
            _FakeLlm(
                GeminiNormalizedFieldCollection(
                    fields=[
                        GeminiNormalizedField(
                            field_id="name",
                            label="Name",
                            extracted_value="Kanak Sharma",
                            normalized_value="Kanak Sharma",
                            ai_confidence=0.99,
                            grounding_confidence=0.9,
                            mandatory=True,
                            verifier_hint="vit_registry",
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
                            "connector_id": "vit_registry",
                            "claim_type": "credential",
                            "optional": False,
                            "high_assurance": True,
                            "explanation": "Grouped for registry verification.",
                        }
                    ]
                )
            ),
        ]

        with patch(
            "backend.app.agent_orchestration.graph._build_structured_gemini_llm",
            side_effect=responses,
        ):
            result = build_generalized_verification_graph(policy=policy).invoke(
                {
                    "session_id": "session-1",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": _runtime_payload(),
                }
            )

        self.assertFalse(result.get("gemini_fallback_used", False))
        workspace = WorkspacePayload.model_validate(result["workspace_payload"])
        self.assertEqual(workspace.document.document_type, "academic_credential")
        self.assertEqual(workspace.fields[0].normalized_value, "Kanak Sharma")

    def test_service_falls_back_when_gemini_dependency_or_call_fails(self):
        raw_payload = _runtime_payload()

        with patch(
            "backend.app.agent_orchestration.graph._build_structured_gemini_llm",
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

    def test_semantic_normalization_deterministic_fallback_is_generic(self):
        claims = [
            {"claim_id": "degree", "label": "Degree", "value": "Bachelor of Science in Physics", "confidence": 0.8},
            {"claim_id": "certificate", "label": "Certificate", "value": "ISO 27001 Lead Auditor", "confidence": 0.7},
            {"claim_id": "identity", "label": "Identity", "value": "Asha Rao"},
            {"claim_id": "employment", "label": "Employment", "value": "Senior Analyst"},
            {"claim_id": "misc", "value": "   Unknown   Claim   "},
        ]

        normalized = normalize_claims_semantically(claims, llm=None)

        self.assertEqual(len(normalized), 5)
        self.assertEqual(normalized[0]["normalized_value"], "Bachelor of Science in Physics")
        self.assertEqual(normalized[1]["normalized_value"], "ISO 27001 Lead Auditor")
        self.assertEqual(normalized[4]["normalized_value"], "Unknown Claim")
        self.assertTrue(all(item["normalization_source"] == "deterministic_fallback" for item in normalized))
        self.assertTrue(all("raw_value" not in item or item["raw_value"] is None for item in normalized))

    def test_semantic_normalization_accepts_mocked_gemini_output(self):
        fake_llm = _FakeLlm(
            SemanticNormalizedClaimCollection(
                claims=[
                    {
                        "claim_id": "cert-1",
                        "field_id": "credential",
                        "raw_value": "ISO 27001 Lead Auditor",
                        "normalized_value": "ISO 27001 Lead Auditor",
                        "claim_type": "professional_certificate",
                        "canonical_label": "Credential",
                        "confidence": 0.91,
                        "normalization_source": "gemini",
                        "requires_verification": True,
                    }
                ]
            )
        )

        normalized = normalize_claims_semantically(
            [{"claim_id": "cert-1", "label": "Credential", "raw_value": "ISO 27001 Lead Auditor"}],
            llm=fake_llm,
        )

        self.assertEqual(normalized[0]["normalization_source"], "gemini")
        self.assertEqual(normalized[0]["claim_type"], "professional_certificate")
        self.assertNotIn("raw_value", normalized[0])

    def test_semantic_normalization_falls_back_on_malformed_gemini_output(self):
        normalized = normalize_claims_semantically(
            [{"claim_id": "generic", "label": "Claim", "value": "  Generic   Evidence  "}],
            llm=_FakeLlm("not structured"),
        )

        self.assertEqual(normalized[0]["normalization_source"], "deterministic_fallback")
        self.assertEqual(normalized[0]["normalized_value"], "Generic Evidence")


if __name__ == "__main__":
    unittest.main()

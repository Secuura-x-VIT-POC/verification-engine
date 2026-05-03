import os
import sys
import unittest
from unittest.mock import patch

from pydantic import ValidationError


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.graph import build_generalized_verification_graph
from backend.app.agent_orchestration.policies import AgentRuntimePolicy, load_agent_runtime_policy
from backend.app.agent_orchestration.schemas import (
    FieldDecision,
    GeminiCredentialGroupCollection,
    GeminiDocumentUnderstanding,
    GeminiNormalizedField,
    GeminiNormalizedFieldCollection,
    RouteRecommendation,
    SemanticNormalizedClaimCollection,
    VerificationTask,
    VerifierResult,
    WorkspacePayload,
)
from backend.app.agent_orchestration.providers.gemini_pool import GeminiPoolRateLimitError
from backend.app.agent_orchestration.providers.gemini import build_gemini_llm
from backend.app.agent_orchestration.semantic_normalization import normalize_claims_semantically
from backend.app.agent_orchestration.service import normalize_extraction_payload
from backend.app.trust.trust_engine import build_final_verdict, determine_field_decision


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


def _generic_payload(document_type: str, fields: list[dict]) -> dict:
    return {
        "view": {
            "document_type": document_type,
            "page_count": 1,
            "used_ocr": False,
            "warnings": [],
            "field_details": fields,
        },
        "trust_input": {
            "is_unsafe": False,
            "fields": [
                {
                    "name": field["key"],
                    "value": field["value"],
                    "is_mandatory": field.get("mandatory", True),
                    "is_grounded": True,
                    "confidence": field.get("confidence", 0.8),
                }
                for field in fields
            ],
        },
    }


class _FakeLlm:
    def __init__(self, response):
        self.response = response

    def invoke(self, _prompt):
        return self.response


def _gemini_balanced_graph_response(_prompt_or_messages, *, preferred_key=None, schema=None, stage_name="gemini"):
    if stage_name == "gemini_document_understanding":
        return GeminiDocumentUnderstanding(
            document_type="academic_credential",
            summary="Credential document",
            explanation="Structured Gemini output accepted.",
            grounding_confidence=0.9,
            matching_score=0.8,
            visual_match_probability=0.7,
        )
    if stage_name == "gemini_field_normalization":
        return SemanticNormalizedClaimCollection(
            claims=[
                {
                    "claim_id": "claim-name",
                    "field_id": "name",
                    "label": "Name",
                    "canonical_label": "Name",
                    "normalized_value": "Kanak Sharma",
                    "claim_type": "identity",
                    "confidence": 0.99,
                    "normalization_source": "gemini",
                    "requires_verification": True,
                }
            ]
        )
    if stage_name == "gemini_credential_grouping":
        return GeminiCredentialGroupCollection(
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
    raise AssertionError(f"Unexpected Gemini stage {stage_name}")


def _enabled_gemini_policy() -> AgentRuntimePolicy:
    return AgentRuntimePolicy(
        orchestration_enabled=True,
        provider_key="gemini",
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash",
        gemini_demo_raw_text_enabled=True,
        gemini_structured_output_enabled=True,
    )


class GeminiNormalizationTests(unittest.TestCase):
    def test_build_gemini_llm_raises_clear_error_without_key(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY_PRIMARY": "",
                "GEMINI_API_KEY": "",
                "GOOGLE_API_KEY": "",
                "GEMINI_API_KEY_SECONDARY": "",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY is not configured"):
                build_gemini_llm()

    def test_runtime_policy_treats_primary_only_gemini_key_as_configured(self):
        from backend.app.agent_orchestration.graph import _gemini_enabled

        with patch.dict(
            os.environ,
            {
                "AGENT_PROVIDER": "gemini",
                "GEMINI_API_KEY_PRIMARY": "primary-only-key",
                "GEMINI_API_KEY": "",
                "GOOGLE_API_KEY": "",
                "GEMINI_API_KEY_SECONDARY": "",
            },
            clear=False,
        ):
            policy = load_agent_runtime_policy()

        self.assertTrue(policy.gemini_primary_configured)
        self.assertFalse(policy.gemini_secondary_configured)
        self.assertTrue(policy.gemini_configured)
        self.assertTrue(_gemini_enabled(policy))
        self.assertNotEqual(policy.gemini_api_key, "primary-only-key")

    def test_runtime_policy_treats_secondary_only_gemini_key_as_configured(self):
        from backend.app.agent_orchestration.graph import _gemini_enabled

        with patch.dict(
            os.environ,
            {
                "AGENT_PROVIDER": "gemini",
                "GEMINI_API_KEY_PRIMARY": "",
                "GEMINI_API_KEY": "",
                "GOOGLE_API_KEY": "",
                "GEMINI_API_KEY_SECONDARY": "secondary-only-key",
            },
            clear=False,
        ):
            policy = load_agent_runtime_policy()

        self.assertFalse(policy.gemini_primary_configured)
        self.assertTrue(policy.gemini_secondary_configured)
        self.assertTrue(policy.gemini_configured)
        self.assertTrue(_gemini_enabled(policy))
        self.assertNotEqual(policy.gemini_api_key, "secondary-only-key")

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
                SemanticNormalizedClaimCollection(
                    claims=[
                        {
                            "claim_id": "claim-name",
                            "field_id": "name",
                            "label": "Name",
                            "canonical_label": "Name",
                            "normalized_value": "Kanak Sharma",
                            "claim_type": "identity",
                            "confidence": 0.99,
                            "normalization_source": "gemini",
                            "requires_verification": True,
                        }
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
        self.assertTrue(result["route_recommendations"])
        self.assertTrue(result["verification_tasks"])
        VerificationTask.model_validate(result["verification_tasks"][0])

    def test_gemini_graph_stages_use_balanced_pool_preferred_keys(self):
        with patch("backend.app.agent_orchestration.graph.invoke_gemini_balanced", side_effect=_gemini_balanced_graph_response) as invoke_mock:
            result = build_generalized_verification_graph(policy=_enabled_gemini_policy()).invoke(
                {
                    "session_id": "session-1",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": _runtime_payload(),
                }
            )

        self.assertFalse(result.get("gemini_fallback_used", False))
        observed = {
            call.kwargs["stage_name"]: call.kwargs["preferred_key"]
            for call in invoke_mock.call_args_list
        }
        self.assertEqual(observed["gemini_document_understanding"], "primary")
        self.assertEqual(observed["gemini_field_normalization"], "secondary")
        self.assertEqual(observed["gemini_credential_grouping"], "primary")

    def test_graph_document_understanding_invokes_primary_slot(self):
        with patch("backend.app.agent_orchestration.graph.invoke_gemini_balanced", side_effect=_gemini_balanced_graph_response) as invoke_mock:
            build_generalized_verification_graph(policy=_enabled_gemini_policy()).invoke(
                {
                    "session_id": "session-document-primary",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": _runtime_payload(),
                }
            )

        document_calls = [
            call for call in invoke_mock.call_args_list
            if call.kwargs["stage_name"] == "gemini_document_understanding"
        ]
        self.assertEqual(len(document_calls), 1)
        self.assertEqual(document_calls[0].kwargs["preferred_key"], "primary")

    def test_graph_credential_grouping_invokes_primary_slot(self):
        with patch("backend.app.agent_orchestration.graph.invoke_gemini_balanced", side_effect=_gemini_balanced_graph_response) as invoke_mock:
            build_generalized_verification_graph(policy=_enabled_gemini_policy()).invoke(
                {
                    "session_id": "session-grouping-primary",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": _runtime_payload(),
                }
            )

        grouping_calls = [
            call for call in invoke_mock.call_args_list
            if call.kwargs["stage_name"] == "gemini_credential_grouping"
        ]
        self.assertEqual(len(grouping_calls), 1)
        self.assertEqual(grouping_calls[0].kwargs["preferred_key"], "primary")

    def test_graph_field_normalization_invokes_secondary_slot_when_claims_exist(self):
        with patch("backend.app.agent_orchestration.graph.invoke_gemini_balanced", side_effect=_gemini_balanced_graph_response) as invoke_mock:
            build_generalized_verification_graph(policy=_enabled_gemini_policy()).invoke(
                {
                    "session_id": "session-field-secondary",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": _runtime_payload(),
                }
            )

        field_calls = [
            call for call in invoke_mock.call_args_list
            if call.kwargs["stage_name"] == "gemini_field_normalization"
        ]
        self.assertEqual(len(field_calls), 1)
        self.assertEqual(field_calls[0].kwargs["preferred_key"], "secondary")

    def test_graph_field_normalization_does_not_touch_secondary_without_claims(self):
        payload_without_claims = {
            "view": {
                "document_type": "academic_credential",
                "page_count": 1,
                "used_ocr": False,
                "warnings": [],
                "field_details": [],
                "field_candidates": [],
            },
            "trust_input": {"fields": []},
            "connector_input": {},
        }
        with patch("backend.app.agent_orchestration.graph.invoke_gemini_balanced", side_effect=_gemini_balanced_graph_response) as invoke_mock:
            build_generalized_verification_graph(policy=_enabled_gemini_policy()).invoke(
                {
                    "session_id": "session-no-secondary",
                    "filename": "demo.pdf",
                    "file_path": "",
                    "extraction_payload": payload_without_claims,
                }
            )

        stages = [call.kwargs["stage_name"] for call in invoke_mock.call_args_list]
        self.assertIn("gemini_document_understanding", stages)
        self.assertIn("gemini_credential_grouping", stages)
        self.assertNotIn("gemini_field_normalization", stages)

    def test_field_normalization_adapter_prefers_secondary_slot(self):
        from backend.app.agent_orchestration.graph import _build_structured_gemini_llm

        policy = AgentRuntimePolicy(
            orchestration_enabled=True,
            provider_key="gemini",
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-flash",
            gemini_demo_raw_text_enabled=True,
        )
        response = SemanticNormalizedClaimCollection(claims=[])

        with patch("backend.app.agent_orchestration.graph.invoke_gemini_balanced", return_value=response) as invoke_mock:
            llm = _build_structured_gemini_llm(
                runtime_policy=policy,
                schema=SemanticNormalizedClaimCollection,
                stage_name="gemini_field_normalization",
            )
            self.assertIs(llm.invoke("safe prompt"), response)

        invoke_mock.assert_called_once()
        self.assertEqual(invoke_mock.call_args.kwargs["preferred_key"], "secondary")
        self.assertEqual(invoke_mock.call_args.kwargs["stage_name"], "gemini_field_normalization")

    def test_gemini_stage_preference_mapping_includes_task_planning(self):
        from backend.app.agent_orchestration.graph import _preferred_gemini_key_for_stage

        self.assertEqual(_preferred_gemini_key_for_stage("gemini_document_understanding"), "primary")
        self.assertEqual(_preferred_gemini_key_for_stage("gemini_field_normalization"), "secondary")
        self.assertEqual(_preferred_gemini_key_for_stage("gemini_credential_grouping"), "primary")
        self.assertEqual(_preferred_gemini_key_for_stage("verification_task_planning"), "secondary")

    def test_gemini_pool_rate_limit_error_uses_deterministic_fallback_without_raw_leaks(self):
        raw_payload = _runtime_payload()
        raw_payload["view"]["raw_text"] = "RAW_GEMINI_WIRING_OCR_SECRET"
        raw_payload["view"]["field_details"] = [
            {
                "key": "name",
                "label": "Name",
                "value": "Raw Name",
                "source_text": "RAW_GEMINI_WIRING_CREDENTIAL_SECRET",
            }
        ]
        policy = AgentRuntimePolicy(
            orchestration_enabled=True,
            provider_key="gemini",
            gemini_api_key="test-key",
            gemini_model="gemini-2.5-flash",
            gemini_demo_raw_text_enabled=True,
        )

        with patch(
            "backend.app.agent_orchestration.graph.invoke_gemini_balanced",
            side_effect=GeminiPoolRateLimitError("Gemini rate limit encountered for configured key slots"),
        ):
            with self.assertLogs("backend.app.agent_orchestration.graph", level="WARNING") as captured:
                result = build_generalized_verification_graph(policy=policy).invoke(
                    {
                        "session_id": "session-rate-limit",
                        "filename": "demo.pdf",
                        "file_path": "",
                        "extraction_payload": raw_payload,
                    }
                )

        self.assertTrue(result["gemini_fallback_used"])
        WorkspacePayload.model_validate(result["workspace_payload"])
        combined = "\n".join(
            captured.output
            + [str(result.get("gemini_errors") or ""), str(result.get("audit_log") or ""), str(result.get("workspace_payload") or "")]
        )
        self.assertNotIn("RAW_GEMINI_WIRING_OCR_SECRET", combined)
        self.assertNotIn("RAW_GEMINI_WIRING_CREDENTIAL_SECRET", combined)
        self.assertNotIn("RAW_GEMINI_WIRING_PROVIDER_SECRET", combined)

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

    def test_document_understanding_fallback_handles_generic_document_types(self):
        samples = [
            ("identity_document", [{"key": "holder_name", "label": "Holder Name", "value": "Asha Rao"}]),
            ("professional_certificate", [{"key": "credential", "label": "Credential", "value": "ISO 27001 Lead Auditor"}]),
            ("employment_letter", [{"key": "employer", "label": "Employer", "value": "Example Corp"}]),
            ("invoice", [{"key": "amount", "label": "Invoice Amount", "value": "1250.00"}]),
        ]

        for document_type, fields in samples:
            with self.subTest(document_type=document_type):
                state = build_generalized_verification_graph(
                    policy=AgentRuntimePolicy(orchestration_enabled=True, provider_key="gemini", gemini_api_key=None)
                ).invoke(
                    {
                        "session_id": f"session-{document_type}",
                        "filename": f"{document_type}.pdf",
                        "file_path": "",
                        "extraction_payload": _generic_payload(document_type, fields),
                    }
                )

                self.assertEqual(state["document_understanding"]["document_type"], document_type)
                self.assertNotEqual(state["credential_groups"][0]["claim_type"], "academic_degree")
                self.assertTrue(state["verification_tasks"])

    def test_route_recommendation_and_task_planning_are_generic_and_sanitized(self):
        payload = _generic_payload(
            "professional_certificate",
            [
                {
                    "key": "credential",
                    "label": "Credential",
                    "value": "ISO 27001 Lead Auditor",
                    "confidence": 0.91,
                    "source_text": "RAW_SOURCE_SENTINEL",
                },
                {
                    "key": "issuer",
                    "label": "Issuer",
                    "value": "Example Standards Body",
                    "confidence": 0.88,
                    "mandatory": False,
                },
            ],
        )
        payload["view"]["raw_text"] = "RAW_TEXT_SENTINEL"

        state = build_generalized_verification_graph(
            policy=AgentRuntimePolicy(orchestration_enabled=True, provider_key="gemini", gemini_api_key=None)
        ).invoke(
            {
                "session_id": "session-routing",
                "filename": "certificate.pdf",
                "file_path": "",
                "extraction_payload": payload,
            }
        )

        route = RouteRecommendation.model_validate(state["route_recommendations"][0])
        task = VerificationTask.model_validate(state["verification_tasks"][0])
        self.assertTrue(route.provider_candidates)
        self.assertTrue(task.provider_candidates)
        self.assertIn(task.assurance_required, {"LOW", "MEDIUM", "HIGH"})
        self.assertIn(task.priority, {"REQUIRED", "OPTIONAL"})
        self.assertTrue(task.required_fields)
        serialized_tasks = str(state["verification_tasks"])
        self.assertNotIn("RAW_TEXT_SENTINEL", serialized_tasks)
        self.assertNotIn("RAW_SOURCE_SENTINEL", serialized_tasks)

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

    def test_ai_only_high_confidence_does_not_create_final_green(self):
        decision = determine_field_decision(
            field_id="credential",
            label="Credential",
            extracted_value="ISO 27001 Lead Auditor",
            normalized_value="ISO 27001 Lead Auditor",
            extraction_confidence=1.0,
            ai_confidence=1.0,
            grounding_confidence=1.0,
            verifier_result=None,
            mandatory=True,
            unsafe_or_malformed=False,
        )

        verdict = build_final_verdict([decision], [], False, [])
        self.assertNotEqual(verdict.outcome, "GREEN")

    def test_verifier_red_overrides_ai_confidence(self):
        verifier = VerifierResult(
            task_id="task-1",
            field_id="credential",
            connector_id="local_mock",
            status="MISMATCH",
            verification_confidence=0.0,
            reason_codes=["VERIFIER_MISMATCH"],
        )

        decision = determine_field_decision(
            field_id="credential",
            label="Credential",
            extracted_value="ISO 27001 Lead Auditor",
            normalized_value="ISO 27001 Lead Auditor",
            extraction_confidence=1.0,
            ai_confidence=1.0,
            grounding_confidence=1.0,
            verifier_result=verifier,
            mandatory=True,
            unsafe_or_malformed=False,
        )

        verdict = build_final_verdict([decision], [verifier], False, [])
        self.assertEqual(verdict.outcome, "RED")


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from dataclasses import dataclass

from backend.app.agent_orchestration.graph import (
    _build_workspace_payload,
    _gemini_confidence_fusion,
    _policy_verdict,
    _verification_task_planning,
    _workspace_verifier_result,
)
from backend.app.agent_orchestration.sanitization import sanitize_workspace_payload
from backend.app.agent_orchestration.schemas import WorkspacePayload
from backend.app.trust.trust_engine import evaluate_trust
from backend.app.verification_domain.adapters import build_session_credential_audits
from backend.app.verification_domain.contracts import (
    AUDIT_STATUS_MANUAL_REVIEW,
    AUDIT_STATUS_MISMATCH,
    AUDIT_STATUS_VERIFIED,
    OUTCOME_COLOR_AMBER,
    OUTCOME_COLOR_GREEN,
    OUTCOME_COLOR_RED,
    BoundingBox,
    ExtractedCredential,
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
    VerifierRouteDecision,
)
from backend.app.verifier_execution.adapters import build_execution_context
from backend.app.verifier_execution.contracts import (
    TASK_STATUS_SUCCEEDED,
    VerificationTaskResult,
)
from backend.app.verifier_execution.executor import VerificationTaskExecutor
from backend.app.verifier_providers.contracts import (
    OUTBOUND_MODE_DISABLED,
    PROVIDER_OPERATING_MODE_LOCAL_MOCK,
    PROVIDER_TECHNICAL_STATUS_SUCCESS,
    ProviderExecutionTrace,
    ProviderResponse,
)


RAW_PHASE4_PLAN_SECRET = "RAW_PHASE4_PLAN_SECRET_123"
RAW_PROVIDER_RESPONSE_SECRET = "RAW_PROVIDER_RESPONSE_SECRET_123"
RAW_CREDENTIAL_VALUE_SECRET = "RAW_CREDENTIAL_VALUE_SECRET_123"
RAW_OCR_TEXT_SECRET = "RAW_OCR_TEXT_SECRET_123"


class _FakeProviderRegistry:
    def __init__(self, providers):
        self._providers = dict(providers)

    def get(self, provider_key):
        return self._providers.get(provider_key)


class _FakeProvider:
    provider_label = "Local Mock Provider"

    def __init__(self, *, supported=True):
        self.supported = supported

    def supports(self, verifier_key, category):
        return self.supported and verifier_key == "identity_db" and category == "identity"


@dataclass
class _ProviderAttempt:
    provider_key: str
    provider_label: str
    response: ProviderResponse
    trace: ProviderExecutionTrace


class _FakeProviderRuntime:
    def __init__(self, *, registry, response):
        self.registry = registry
        self._response = response
        self.fallback_trace_ids = []

    def attempt_verification(self, **kwargs):
        provider_key = kwargs.get("preferred_provider_key") or "local_mock"
        return _ProviderAttempt(
            provider_key=provider_key,
            provider_label="Local Mock Provider",
            response=self._response,
            trace=ProviderExecutionTrace(
                request_id=f"trace-{kwargs.get('task_id')}",
                provider_key=provider_key,
                provider_label="Local Mock Provider",
                verifier_key=kwargs.get("verifier_key") or "identity_db",
                technical_status=self._response.technical_status,
                outbound_mode=OUTBOUND_MODE_DISABLED,
                provider_operating_mode=PROVIDER_OPERATING_MODE_LOCAL_MOCK,
                is_mock_result=True,
            ),
        )

    def mark_fallback_used(self, request_id):
        self.fallback_trace_ids.append(request_id)


class Phase5PersonBIntegrationTests(unittest.TestCase):
    def test_planned_task_ids_survive_into_executor_handoff(self):
        planning_update = _verification_task_planning(
            {
                "credential_groups": [
                    {
                        "group_id": "group-identity",
                        "credential_id": "credential-identity",
                        "label": "Candidate name",
                        "field_ids": ["field-name"],
                        "required_field_ids": ["field-name"],
                        "claim_type": "identity",
                    }
                ],
                "route_recommendations": [
                    {
                        "credential_id": "credential-identity",
                        "claim_type": "identity",
                        "provider_candidates": ["local_mock"],
                        "preferred_provider_key": "local_mock",
                        "assurance_required": "HIGH",
                        "priority": "REQUIRED",
                        "planner_reason": "Safe planner metadata only.",
                    }
                ],
                "semantic_claims": [
                    {
                        "field_id": "field-name",
                        "normalized_value": RAW_PHASE4_PLAN_SECRET,
                    }
                ],
            }
        )

        planned_task = planning_update["verification_tasks"][0]
        self.assertEqual(planned_task["task_id"], "task-credential-identity-1")
        self.assertEqual(planned_task["credential_id"], "credential-identity")
        self.assertEqual(planned_task["claim_type"], "identity")
        self.assertEqual(planned_task["provider_candidates"], ["local_mock"])
        self.assertEqual(planned_task["field_ids"], ["field-name"])
        self.assertEqual(planned_task["required_fields"], ["field-name"])
        self.assertEqual(planned_task["assurance_required"], "HIGH")
        self.assertEqual(planned_task["priority"], "REQUIRED")
        self.assertEqual(planned_task["planner_reason"], "Safe planner metadata only.")
        self.assertNotIn(RAW_PHASE4_PLAN_SECRET, json.dumps(planned_task, sort_keys=True))

        task = self._task_from_planning(planned_task, provider_candidates=["local_mock"])
        artifacts = self._execute_task(
            task,
            runtime=self._runtime_with_response(
                ProviderResponse(
                    request_id="request-green",
                    provider_key="local_mock",
                    technical_status=PROVIDER_TECHNICAL_STATUS_SUCCESS,
                    matched_fields={"name": "matched"},
                    confidence=0.96,
                    reason_codes=["PROVIDER_VERIFIED"],
                    operating_mode=PROVIDER_OPERATING_MODE_LOCAL_MOCK,
                    is_mock_result=True,
                )
            ),
        )
        result = artifacts["task_results"].results[0]

        self.assertEqual(result.task_id, planned_task["task_id"])
        self.assertEqual(result.credential_id, planned_task["credential_id"])
        self.assertEqual(result.executed_provider_key, "local_mock")
        self.assertEqual(task.claim_type, "identity")
        self.assertEqual(task.required_fields, ["field-name"])
        self.assertEqual(task.input_payload["field_ids"], ["field-name"])

    def test_advisory_planning_without_executable_provider_remains_amber_workspace(self):
        state = self._graph_state(
            verifier_results=[],
            normalized_value="safe-normalized",
            ai_confidence=1.0,
            grounding_confidence=1.0,
            extraction_confidence=1.0,
        )
        state.update(_gemini_confidence_fusion(state))
        state.update(_policy_verdict(state))
        state.update(_build_workspace_payload(state))

        workspace = WorkspacePayload.model_validate(state["workspace_payload"])
        self.assertEqual(workspace.final_verdict.outcome, "AMBER")
        self.assertEqual(workspace.summary.green_count, 0)
        self.assertEqual(workspace.summary.amber_count, 1)
        self.assertEqual(workspace.status, "PENDING_HUMAN_REVIEW")
        self.assertIn("LOW_CONFIDENCE_REVIEW_REQUIRED", workspace.final_verdict.reason_codes)

    def test_planned_provider_candidates_without_valid_provider_fall_back_safely(self):
        task = self._domain_task(
            provider_candidates=["unknown_provider", "wrong_category_provider"],
            input_payload={"preferred_provider_key": "unknown_provider"},
        )
        runtime = _FakeProviderRuntime(
            registry=_FakeProviderRegistry(
                {"wrong_category_provider": _FakeProvider(supported=False)}
            ),
            response=ProviderResponse(
                request_id="unused",
                provider_key="wrong_category_provider",
                technical_status=PROVIDER_TECHNICAL_STATUS_SUCCESS,
            ),
        )
        artifacts = self._execute_task(task, runtime=runtime)
        result = artifacts["task_results"].results[0]

        self.assertEqual(result.audit_status, AUDIT_STATUS_MANUAL_REVIEW)
        self.assertEqual(result.outcome_color, OUTCOME_COLOR_AMBER)
        self.assertNotEqual(result.audit_status, AUDIT_STATUS_VERIFIED)
        self.assertIn("PROVIDER_NOT_REGISTERED", result.reason_codes)
        self.assertIn("PROVIDER_CAPABILITY_MISMATCH", result.reason_codes)
        self.assertIn("NO_PROVIDER_AVAILABLE", result.reason_codes)

    def test_planned_task_with_valid_mock_provider_can_become_green(self):
        task = self._domain_task(provider_candidates=["local_mock"])
        artifacts = self._execute_task(
            task,
            runtime=self._runtime_with_response(
                ProviderResponse(
                    request_id="request-green",
                    provider_key="local_mock",
                    technical_status=PROVIDER_TECHNICAL_STATUS_SUCCESS,
                    matched_fields={"name": "matched"},
                    confidence=0.97,
                    reason_codes=["PROVIDER_VERIFIED"],
                    response_summary={"mode": "fixture", "raw_provider_body": RAW_PROVIDER_RESPONSE_SECRET},
                    operating_mode=PROVIDER_OPERATING_MODE_LOCAL_MOCK,
                    is_mock_result=True,
                )
            ),
        )
        result = artifacts["task_results"].results[0]
        trust = self._trust_for_result(result)

        self.assertEqual(result.audit_status, AUDIT_STATUS_VERIFIED)
        self.assertEqual(result.outcome_color, OUTCOME_COLOR_GREEN)
        self.assertEqual(result.executed_provider_key, "local_mock")
        self.assertEqual(trust["outcome"], "GREEN")
        self.assertEqual(trust["connector_ids"], ["local_mock"])

    def test_red_provider_result_dominates_bundle_and_trust(self):
        task = self._domain_task(provider_candidates=["local_mock"])
        artifacts = self._execute_task(
            task,
            runtime=self._runtime_with_response(
                ProviderResponse(
                    request_id="request-red",
                    provider_key="local_mock",
                    technical_status=PROVIDER_TECHNICAL_STATUS_SUCCESS,
                    matched_fields={"name": "matched"},
                    mismatched_fields={"id_number": "mismatched"},
                    confidence=0.12,
                    reason_codes=["PROVIDER_MISMATCH"],
                    operating_mode=PROVIDER_OPERATING_MODE_LOCAL_MOCK,
                    is_mock_result=True,
                )
            ),
        )
        red_result = artifacts["task_results"].results[0]
        green_result = red_result.model_copy(
            update={
                "task_id": "task-green-advisory",
                "audit_status": AUDIT_STATUS_VERIFIED,
                "outcome_color": OUTCOME_COLOR_GREEN,
                "reason_codes": ["PROVIDER_VERIFIED"],
                "matched_fields": {"name": "matched"},
                "mismatched_fields": {},
                "confidence": 0.99,
            }
        )
        bundle_artifacts = VerificationTaskExecutor()._build_bundles(
            credential_collection=self._credentials(),
            verification_plan=SessionVerificationPlan(
                session_id="session-phase5",
                document_type="identity_document",
                tasks=[task, task.model_copy(update={"task_id": "task-green-advisory"})],
            ),
            results=[green_result, red_result],
        )
        bundle = bundle_artifacts.bundles[0]
        trust = self._trust_for_result(bundle.best_result)

        self.assertEqual(bundle.final_audit_status, AUDIT_STATUS_MISMATCH)
        self.assertEqual(bundle.final_outcome_color, OUTCOME_COLOR_RED)
        self.assertEqual(bundle.best_result.task_id, red_result.task_id)
        self.assertIn("PROVIDER_MISMATCH", bundle.reason_codes)
        self.assertEqual(trust["outcome"], "RED")
        self.assertIn("PROVIDER_MISMATCH", trust["reason_codes"])

    def test_workspace_safe_output_has_no_raw_secrets_after_integration(self):
        task = self._domain_task(provider_candidates=["local_mock"])
        artifacts = self._execute_task(
            task,
            runtime=self._runtime_with_response(
                ProviderResponse(
                    request_id="request-privacy",
                    provider_key="local_mock",
                    technical_status=PROVIDER_TECHNICAL_STATUS_SUCCESS,
                    matched_fields={"name": RAW_CREDENTIAL_VALUE_SECRET},
                    confidence=0.93,
                    reason_codes=["PROVIDER_VERIFIED"],
                    response_summary={
                        "mode": "fixture",
                        "raw_provider_body": RAW_PROVIDER_RESPONSE_SECRET,
                    },
                    operating_mode=PROVIDER_OPERATING_MODE_LOCAL_MOCK,
                    is_mock_result=True,
                )
            ),
            credential=self._credential(
                value=RAW_CREDENTIAL_VALUE_SECRET,
                normalized_value=RAW_CREDENTIAL_VALUE_SECRET,
                source_text=RAW_OCR_TEXT_SECRET,
            ),
        )
        result = artifacts["task_results"].results[0]
        verifier_result = _workspace_verifier_result(result)
        state = self._graph_state(
            verifier_results=[verifier_result.model_dump(mode="json")],
            normalized_value=RAW_CREDENTIAL_VALUE_SECRET,
            ai_confidence=1.0,
            grounding_confidence=1.0,
            extraction_confidence=1.0,
        )
        state["sanitized_extraction"] = {
            "view": {
                "document_type": "identity_document",
                "raw_ocr_text": RAW_OCR_TEXT_SECRET,
                "warnings": [RAW_PHASE4_PLAN_SECRET],
            }
        }
        state.update(_gemini_confidence_fusion(state))
        state.update(_policy_verdict(state))
        state.update(_build_workspace_payload(state))
        workspace = sanitize_workspace_payload(
            WorkspacePayload.model_validate(state["workspace_payload"])
        )
        audits = build_session_credential_audits(
            "session-phase5",
            {"document_type": "identity_document"},
            credentials=self._credentials(
                credential=self._credential(
                    value=RAW_CREDENTIAL_VALUE_SECRET,
                    normalized_value=RAW_CREDENTIAL_VALUE_SECRET,
                    source_text=RAW_OCR_TEXT_SECRET,
                )
            ),
            verification_plan=SessionVerificationPlan(
                session_id="session-phase5",
                document_type="identity_document",
                route_decisions=[self._route_decision()],
                tasks=[task],
            ),
            credential_bundles=artifacts["credential_bundles"],
        )

        serialized = json.dumps(
            {
                "workspace": workspace.model_dump(mode="json"),
                "audits": audits.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        for secret in (
            RAW_PHASE4_PLAN_SECRET,
            RAW_PROVIDER_RESPONSE_SECRET,
            RAW_CREDENTIAL_VALUE_SECRET,
            RAW_OCR_TEXT_SECRET,
        ):
            self.assertNotIn(secret, serialized)

    def _runtime_with_response(self, response):
        return _FakeProviderRuntime(
            registry=_FakeProviderRegistry({"local_mock": _FakeProvider()}),
            response=response,
        )

    def _execute_task(self, task, *, runtime, credential=None):
        executor = VerificationTaskExecutor()
        return executor.execute_plan(
            credential_collection=self._credentials(credential=credential),
            verification_plan=SessionVerificationPlan(
                session_id="session-phase5",
                document_type="identity_document",
                route_decisions=[self._route_decision()],
                tasks=[task],
            ),
            context=build_execution_context(
                session_id="session-phase5",
                document_type="identity_document",
                extraction_payload={"document_type": "identity_document"},
                connector_payload=[],
                trust_outcome=None,
                reason_codes=[],
                provider_runtime=runtime,
            ),
        )

    def _trust_for_result(self, result):
        return evaluate_trust(
            {
                "fields": {"credential-identity": "safe"},
                "confidence": {"credential-identity": 1.0},
            },
            result.model_dump(mode="json"),
            {"required_fields": ["credential-identity"]},
        )

    def _credentials(self, *, credential=None):
        return SessionCredentialCollection(
            session_id="session-phase5",
            document_type="identity_document",
            credentials=[credential or self._credential()],
        )

    def _credential(
        self,
        *,
        value="Safe Runtime Value",
        normalized_value="Safe Runtime Value",
        source_text="Safe source text",
    ):
        return ExtractedCredential(
            credential_id="credential-identity",
            label="Candidate name",
            category="identity",
            value=value,
            normalized_value=normalized_value,
            source_text=source_text,
            confidence=0.99,
            page=1,
            bounding_box=BoundingBox(page=1, x0=1, y0=2, x1=3, y1=4),
            is_pii=True,
            requires_verification=True,
            verification_recommended=True,
            extraction_method="deterministic_test",
        )

    def _domain_task(
        self,
        *,
        provider_candidates=None,
        input_payload=None,
    ):
        return VerificationTask(
            task_id="task-credential-identity-1",
            credential_id="credential-identity",
            verifier_key="identity_db",
            verifier_label="Identity Database",
            verification_type="identity",
            claim_type="identity",
            required=True,
            status="PLANNED",
            provider_candidates=list(provider_candidates or []),
            required_fields=["field-name"],
            assurance_required="HIGH",
            preferred_provider_key="local_mock",
            input_payload={
                "credential_id": "credential-identity",
                "preferred_provider_key": "local_mock",
                "field_ids": ["field-name"],
                "planner_reason": "Safe planner metadata only.",
                **dict(input_payload or {}),
            },
        )

    def _task_from_planning(self, planned_task, *, provider_candidates):
        return self._domain_task(
            provider_candidates=provider_candidates,
            input_payload={
                "credential_id": planned_task["credential_id"],
                "preferred_provider_key": planned_task["connector_id"],
                "field_ids": planned_task["field_ids"],
                "planner_reason": planned_task["planner_reason"],
            },
        )

    def _route_decision(self):
        return VerifierRouteDecision(
            credential_id="credential-identity",
            selected_verifier_key="identity_db",
            selected_verifier_label="Identity Database",
            route_reason="Planned through deterministic provider capability metadata.",
            preferred_provider_key="local_mock",
            planned_provider_key="local_mock",
            planned_execution_mode="PROVIDER",
            planned_is_mock_result=True,
        )

    def _graph_state(
        self,
        *,
        verifier_results,
        normalized_value,
        ai_confidence,
        grounding_confidence,
        extraction_confidence,
    ):
        return {
            "session_id": "session-phase5",
            "filename": "phase5.pdf",
            "document_understanding": {
                "document_type": "identity_document",
                "unsafe_or_malformed": False,
                "matching_score": 0.9,
                "visual_match_probability": 0.9,
            },
            "normalized_fields": [
                {
                    "field_id": "credential-identity",
                    "label": "Candidate name",
                    "extracted_value": normalized_value,
                    "normalized_value": normalized_value,
                    "ai_confidence": ai_confidence,
                    "grounding_confidence": grounding_confidence,
                    "mandatory": True,
                    "bounding_boxes": [{"page": 1, "x0": 1, "y0": 2, "x1": 3, "y1": 4}],
                }
            ],
            "extraction_payload": {
                "fields": {"credential-identity": normalized_value},
                "confidence": {"credential-identity": extraction_confidence},
            },
            "sanitized_extraction": {
                "view": {
                    "document_type": "identity_document",
                    "page_count": 1,
                    "used_ocr": True,
                    "warnings": [],
                }
            },
            "verifier_results": verifier_results,
            "audit_log": [],
        }


if __name__ == "__main__":
    unittest.main()

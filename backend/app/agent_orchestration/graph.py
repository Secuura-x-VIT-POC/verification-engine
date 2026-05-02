from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..sessions.constants import SessionState
from ..workflow.runtime import build_connector_responses, build_policy, extract_document_payload
from ..verification_domain.adapters import build_session_credentials, build_session_verification_plan
from ..verification_domain.contracts import SessionCredentialCollection, SessionVerificationPlan
from ..verifier_execution.contracts import VerificationTaskResult
from ..verifier_execution.service import build_execution_artifacts
from ..trust.findings import build_trust_findings, normalize_reason_codes
from ..trust.trust_engine import build_final_verdict, determine_field_decision
from .policies import AgentRuntimePolicy, load_agent_runtime_policy, minimize_extraction_payload
from .schemas import (
    FieldDecision,
    GeminiCredentialGroup,
    GeminiCredentialGroupCollection,
    GeminiDocumentUnderstanding,
    GeminiNormalizedField,
    GeminiNormalizedFieldCollection,
    RouteRecommendation,
    RouteRecommendationCollection,
    SemanticNormalizedClaimCollection,
    VerificationTask,
    VerifierResult,
    WorkspaceAction,
    WorkspaceAuditEntry,
    WorkspaceDocument,
    WorkspacePayload,
    WorkspaceSummary,
    WorkspaceVerifierStatus,
)
from .providers.gemini import build_gemini_llm
from .semantic_normalization import normalize_claims_semantically, safe_normalized_string
from .state import GeneralizedVerificationState

LOGGER = logging.getLogger(__name__)

def build_generalized_verification_graph(
    *,
    policy: AgentRuntimePolicy | None = None,
):
    runtime_policy = policy or load_agent_runtime_policy()
    graph = StateGraph(GeneralizedVerificationState)
    
    graph.add_node("load_extraction_state", lambda state: _load_extraction_state(state, runtime_policy))
    graph.add_node("gemini_document_understanding", lambda state: _gemini_document_understanding(state, runtime_policy))
    graph.add_node("gemini_field_normalization", lambda state: _gemini_field_normalization(state, runtime_policy))
    graph.add_node("gemini_credential_grouping", lambda state: _gemini_credential_grouping(state, runtime_policy))
    graph.add_node("route_recommendation", _route_recommendation)
    graph.add_node("verification_task_planning", _verification_task_planning)
    graph.add_node("planning_output_for_existing_runtime", _planning_output_for_existing_runtime)
    graph.add_node("run_verifier_apis", _run_verifier_apis)
    graph.add_node("gemini_confidence_fusion", _gemini_confidence_fusion)
    graph.add_node("policy_verdict", _policy_verdict)
    graph.add_node("build_workspace_payload", _build_workspace_payload)
    
    graph.add_edge(START, "load_extraction_state")
    graph.add_edge("load_extraction_state", "gemini_document_understanding")
    graph.add_edge("gemini_document_understanding", "gemini_field_normalization")
    graph.add_edge("gemini_field_normalization", "gemini_credential_grouping")
    graph.add_edge("gemini_credential_grouping", "route_recommendation")
    graph.add_edge("route_recommendation", "verification_task_planning")
    graph.add_edge("verification_task_planning", "planning_output_for_existing_runtime")
    graph.add_edge("planning_output_for_existing_runtime", "run_verifier_apis")
    graph.add_edge("run_verifier_apis", "gemini_confidence_fusion")
    graph.add_edge("gemini_confidence_fusion", "policy_verdict")
    graph.add_edge("policy_verdict", "build_workspace_payload")
    graph.add_edge("build_workspace_payload", END)
    
    return graph.compile()

def _load_extraction_state(
    state: GeneralizedVerificationState,
    runtime_policy: AgentRuntimePolicy,
) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload")
    if not isinstance(extraction_payload, dict):
        extraction_payload = extract_document_payload(Path(str(state.get("file_path") or "")))

    sanitized_extraction = copy.deepcopy(extraction_payload)
    raw_text = str(((sanitized_extraction.get("view") or {}).get("raw_text")) or "")
    if isinstance(sanitized_extraction.get("view"), dict):
        sanitized_extraction["view"] = dict(sanitized_extraction["view"])
        sanitized_extraction["view"].pop("raw_text", None)

    return {
        "runtime_policy": runtime_policy,
        "policy": build_policy(extraction_payload),
        "extraction_payload": extraction_payload,
        "sanitized_extraction": sanitized_extraction,
        "raw_text": raw_text,
        "sanitized_workspace_fragment": minimize_extraction_payload(
            sanitized_extraction,
            max_fields=runtime_policy.max_fields_for_provider,
            max_value_chars=runtime_policy.max_value_chars,
        ) or {},
        "audit_log": [_audit_item("load_extraction_state", "Extraction payload loaded.")],
    }

def _gemini_document_understanding(
    state: GeneralizedVerificationState,
    runtime_policy: AgentRuntimePolicy,
) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload") or {}
    fallback = _fallback_document_understanding(extraction_payload)
    
    result = _invoke_gemini_with_fallback(
        runtime_policy=runtime_policy,
        schema=GeminiDocumentUnderstanding,
        prompt=_build_document_understanding_prompt(
            extraction_payload=state.get("sanitized_extraction") or extraction_payload,
            raw_text=state.get("raw_text") or "",
            runtime_policy=runtime_policy,
        ),
        fallback_model=fallback,
        stage_name="gemini_document_understanding",
    )
    result["document_profile"] = result.get("document_understanding") or fallback.model_dump(mode="json")
    return result

def _gemini_field_normalization(
    state: GeneralizedVerificationState,
    runtime_policy: AgentRuntimePolicy,
) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload") or {}
    llm = None
    fallback_used = False
    errors: list[str] = []
    if _gemini_enabled(runtime_policy):
        try:
            llm = _build_structured_gemini_llm(
                runtime_policy=runtime_policy,
                schema=SemanticNormalizedClaimCollection,
            )
        except Exception as exc:
            fallback_used = True
            errors.append(f"gemini_field_normalization: {exc}")

    semantic_claims = normalize_claims_semantically(
        _claims_from_extraction_payload(extraction_payload),
        document_profile=state.get("document_understanding") or {},
        llm=llm,
    )
    fallback = GeminiNormalizedFieldCollection(fields=_deterministic_normalized_fields(extraction_payload, semantic_claims))
    if not semantic_claims or all(claim.get("normalization_source") == "deterministic_fallback" for claim in semantic_claims):
        fallback_used = True

    result = {
        "semantic_claims": semantic_claims,
        "normalized_fields": fallback.model_dump(mode="json")["fields"],
        "audit_log": [
            _audit_item(
                "gemini_field_normalization",
                "Semantic claim normalization completed."
                if not fallback_used
                else "Semantic claim deterministic fallback applied.",
                level="WARNING" if fallback_used else "INFO",
            )
        ],
    }
    if fallback_used:
        result["gemini_fallback_used"] = True
        result["fallback_used"] = True
    if errors:
        result["gemini_errors"] = errors
    return result

def _gemini_credential_grouping(
    state: GeneralizedVerificationState,
    runtime_policy: AgentRuntimePolicy,
) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload") or {}
    normalized_fields = [
        GeminiNormalizedField.model_validate(item)
        for item in list(state.get("normalized_fields") or _deterministic_normalized_fields(extraction_payload))
    ]
    fallback = GeminiCredentialGroupCollection(groups=_deterministic_credential_groups(extraction_payload, normalized_fields))
    
    return _invoke_gemini_with_fallback(
        runtime_policy=runtime_policy,
        schema=GeminiCredentialGroupCollection,
        prompt=_build_credential_grouping_prompt(
            document_understanding=state.get("document_understanding") or {},
            normalized_fields=normalized_fields,
        ),
        fallback_model=fallback,
        stage_name="gemini_credential_grouping",
        state_key="credential_groups",
    )

def _route_recommendation(state: GeneralizedVerificationState) -> dict[str, Any]:
    groups = [
        GeminiCredentialGroup.model_validate(item)
        for item in list(state.get("credential_groups") or [])
    ]
    recommendations = [_recommend_route_for_group(group) for group in groups]
    return {
        "route_recommendations": [item.model_dump(mode="json") for item in recommendations],
        "audit_log": [_audit_item("route_recommendation", f"Built {len(recommendations)} route recommendation(s).")],
    }


def _verification_task_planning(state: GeneralizedVerificationState) -> dict[str, Any]:
    groups = [
        GeminiCredentialGroup.model_validate(item)
        for item in list(state.get("credential_groups") or [])
    ]
    routes = [
        RouteRecommendation.model_validate(item)
        for item in list(state.get("route_recommendations") or [])
    ]
    route_by_credential = {route.credential_id: route for route in routes}
    claims_by_field = {
        str(claim.get("field_id") or claim.get("claim_id") or ""): claim
        for claim in list(state.get("semantic_claims") or [])
        if isinstance(claim, dict)
    }

    tasks: list[VerificationTask] = []
    for index, group in enumerate(groups, start=1):
        credential_id = group.credential_id or group.group_id or f"credential-{index}"
        route = route_by_credential.get(credential_id) or _recommend_route_for_group(group)
        field_ids = list(dict.fromkeys(group.field_ids or group.required_field_ids or group.claim_ids))
        required_fields = list(dict.fromkeys(group.required_field_ids or field_ids))
        input_payload = {
            field_id: claims_by_field.get(field_id, {}).get("normalized_value", "")
            for field_id in field_ids
            if field_id in claims_by_field
        }
        task = VerificationTask(
            task_id=f"task-{_slug_id(credential_id)}-{index}",
            credential_id=credential_id,
            field_id=field_ids[0] if field_ids else credential_id,
            label=group.label,
            connector_id=route.preferred_provider_key or route.provider_id or "",
            claim_type=group.claim_type or route.claim_type,
            provider_candidates=list(route.provider_candidates),
            required_fields=required_fields,
            assurance_required=route.assurance_required,
            priority=route.priority,
            optional=route.priority == "OPTIONAL",
            high_assurance=route.assurance_required == "HIGH",
            input_payload=_safe_task_payload(
                {
                    "credential_id": credential_id,
                    "label": group.label,
                    "claim_type": group.claim_type or route.claim_type,
                    "required_fields": required_fields,
                    "assurance_required": route.assurance_required,
                    "provider_candidates": route.provider_candidates,
                    "preferred_provider_key": route.preferred_provider_key,
                    "planner_reason": route.planner_reason,
                    **input_payload,
                }
            ),
            field_ids=field_ids,
            planner_reason=route.planner_reason,
        )
        tasks.append(task)

    return {
        "verification_tasks": [task.model_dump(mode="json") for task in tasks],
        "ai_warnings": _planning_warnings(tasks),
        "audit_log": [_audit_item("verification_task_planning", f"Planned {len(tasks)} verification task(s).")],
    }


def _planning_output_for_existing_runtime(state: GeneralizedVerificationState) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload") or {}
    session_id = str(state.get("session_id") or "")
    credentials = build_session_credentials(session_id, extraction_payload)
    plan = build_session_verification_plan(
        session_id,
        extraction_payload,
        credentials=credentials,
    )

    return {
        "domain_credentials": credentials.model_dump(mode="json"),
        "domain_verification_plan": plan.model_dump(mode="json"),
        "audit_log": [_audit_item("planning_output_for_existing_runtime", f"Built existing runtime plan with {len(plan.tasks)} task(s).")],
    }

def _run_verifier_apis(state: GeneralizedVerificationState) -> dict[str, Any]:
    compatibility_results = build_connector_responses(
        state.get("extraction_payload") or {},
        state.get("policy") or {},
    )
    if isinstance(compatibility_results, list) and compatibility_results:
        verifier_results: list[VerifierResult] = []
        for item in compatibility_results:
            if not isinstance(item, dict):
                continue
            connector_id = str(item.get("connector_id") or item.get("provider_key") or "provider")
            status = str(item.get("status") or "ERROR").upper()
            verifier_results.append(
                VerifierResult(
                    task_id=str(item.get("task_id") or connector_id),
                    field_id=str(item.get("field_id") or "connector_claim"),
                    connector_id=connector_id,
                    status=status,
                    verification_confidence=_verification_confidence_from_status(status),
                    reason_codes=list(item.get("reason_codes") or []),
                    source_api=connector_id,
                    audit_message=_verifier_audit_message(connector_id, status, item),
                    optional=bool(item.get("optional", False)),
                    high_assurance=str(item.get("assurance_class") or "").upper() == "HIGH",
                    field_ids=list(item.get("field_ids") or []),
                )
            )
        return {
            "verifier_results": [result.model_dump(mode="json") for result in verifier_results],
            "audit_log": [_audit_item("run_verifier_apis", f"Collected {len(verifier_results)} verifier result(s).")],
        }

    extraction_payload = state.get("extraction_payload") or {}
    session_id = str(state.get("session_id") or "")
    credentials_payload = state.get("domain_credentials") or {}
    plan_payload = state.get("domain_verification_plan") or {}
    credentials = SessionCredentialCollection.model_validate(credentials_payload)
    plan = SessionVerificationPlan.model_validate(plan_payload)
    artifacts = build_execution_artifacts(
        session_id,
        extraction_payload,
        credentials=credentials,
        verification_plan=plan,
    )

    verifier_results: list[VerifierResult] = []
    task_results = artifacts["task_results"].results
    for result in task_results:
        verifier_results.append(_workspace_verifier_result(result))

    return {
        "verifier_results": [result.model_dump(mode="json") for result in verifier_results],
        "audit_log": [_audit_item("run_verifier_apis", f"Collected {len(verifier_results)} verifier result(s).")],
    }

def _gemini_confidence_fusion(state: GeneralizedVerificationState) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload") or {}
    document_understanding = GeminiDocumentUnderstanding.model_validate(state.get("document_understanding") or {})
    normalized_fields = [GeminiNormalizedField.model_validate(item) for item in list(state.get("normalized_fields") or [])]
    verifier_results = [VerifierResult.model_validate(item) for item in list(state.get("verifier_results") or [])]

    field_decisions: list[FieldDecision] = []
    if document_understanding.unsafe_or_malformed:
        verifier_by_field: dict[str, VerifierResult] = {}
        for verifier in verifier_results:
            for field_id in verifier.field_ids or [verifier.field_id]:
                verifier_by_field[field_id] = verifier

        for field in normalized_fields:
            decision = determine_field_decision(
                field_id=field.field_id,
                label=field.label,
                extracted_value=field.extracted_value,
                normalized_value=field.normalized_value,
                extraction_confidence=_resolve_extraction_confidence(extraction_payload, field.field_id, field.extracted_value),
                ai_confidence=field.ai_confidence,
                grounding_confidence=field.grounding_confidence,
                verifier_result=verifier_by_field.get(field.field_id),
                mandatory=field.mandatory,
                unsafe_or_malformed=True,
            )
            decision.bounding_boxes = list(field.bounding_boxes)
            field_decisions.append(decision)
    else:
        canonical = build_trust_findings(
            claims=[_claim_from_normalized_field(field, extraction_payload) for field in normalized_fields],
            task_results=[_canonical_result_from_verifier(verifier) for verifier in verifier_results],
            required_claim_ids=[field.field_id for field in normalized_fields if field.mandatory],
        )
        field_by_id = {field.field_id: field for field in normalized_fields}
        for finding in canonical.claim_findings:
            field = field_by_id.get(finding.field_id or finding.credential_id or finding.claim_id)
            field_decisions.append(_field_decision_from_claim_finding(finding, field, extraction_payload))

    return {
        "field_decisions": [field.model_dump(mode="json") for field in field_decisions],
        "audit_log": [_audit_item("gemini_confidence_fusion", f"Fused confidence across {len(field_decisions)} field(s).")],
    }

def _policy_verdict(state: GeneralizedVerificationState) -> dict[str, Any]:
    document_understanding = GeminiDocumentUnderstanding.model_validate(state.get("document_understanding") or {})
    field_decisions = [FieldDecision.model_validate(item) for item in list(state.get("field_decisions") or [])]
    verifier_results = [VerifierResult.model_validate(item) for item in list(state.get("verifier_results") or [])]
    
    verdict = build_final_verdict(
        field_decisions=field_decisions,
        verifier_results=verifier_results,
        unsafe_or_malformed=document_understanding.unsafe_or_malformed,
        document_reason_codes=list(document_understanding.risk_flags),
    )
    
    return {
        "final_verdict": verdict.model_dump(mode="json"),
        "audit_log": [_audit_item("policy_verdict", f"Final verdict resolved to {verdict.outcome}.")],
    }


def _claim_from_normalized_field(
    field: GeminiNormalizedField,
    extraction_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "claim_id": field.field_id,
        "credential_id": field.field_id,
        "field_id": field.field_id,
        "label": field.label,
        "claim_type": _claim_type_from_field(field),
        "confidence": _resolve_extraction_confidence(extraction_payload, field.field_id, field.extracted_value),
        "ai_confidence": field.ai_confidence,
        "requires_verification": field.mandatory,
        "bounding_boxes": [box.model_dump(mode="json") for box in field.bounding_boxes],
    }


def _canonical_result_from_verifier(verifier: VerifierResult) -> dict[str, Any]:
    return {
        "task_id": verifier.task_id,
        "credential_id": verifier.field_id,
        "field_id": verifier.field_id,
        "connector_id": verifier.connector_id,
        "status": verifier.status,
        "reason_codes": normalize_reason_codes(verifier.reason_codes),
        "confidence": verifier.verification_confidence,
        "verification_confidence": verifier.verification_confidence,
        "manual_review_recommended": any(
            code in set(verifier.reason_codes or [])
            for code in {
                "NO_PROVIDER_AVAILABLE",
                "NO_EXECUTABLE_PROVIDER",
                "MANUAL_REVIEW_REQUIRED",
                "MANUAL_REVIEW_PROVIDER_SELECTED",
                "PROVIDER_NOT_REGISTERED",
                "VERIFIER_NOT_REGISTERED",
                "PROVIDER_UNAVAILABLE",
            }
        ),
    }


def _field_decision_from_claim_finding(
    finding,
    field: GeminiNormalizedField | None,
    extraction_payload: dict[str, Any],
) -> FieldDecision:
    extracted_value = field.extracted_value if field is not None else ""
    normalized_value = field.normalized_value if field is not None else ""
    extraction_confidence = (
        _resolve_extraction_confidence(extraction_payload, field.field_id, field.extracted_value)
        if field is not None
        else 0.0
    )
    decision = FieldDecision(
        field_id=finding.field_id or finding.credential_id,
        label=finding.label,
        extracted_value=extracted_value,
        normalized_value=normalized_value,
        status=finding.status,
        ai_confidence=finding.confidence.ai,
        extraction_confidence=extraction_confidence,
        verification_confidence=finding.confidence.verifier,
        grounding_confidence=field.grounding_confidence if field is not None else 0.0,
        final_confidence=finding.confidence.final,
        reason_codes=list(finding.reason_codes),
        source_api=finding.source_provider_id,
        audit_message=finding.explanation,
        bounding_boxes=list(field.bounding_boxes) if field is not None else [],
        manual_review_required=finding.manual_review_required,
        verifier_refs=list(finding.verifier_refs),
    )
    return decision

def _build_workspace_payload(state: GeneralizedVerificationState) -> dict[str, Any]:
    sanitized_extraction = state.get("sanitized_extraction") or {}
    document_understanding = GeminiDocumentUnderstanding.model_validate(state.get("document_understanding") or {})
    field_decisions = [FieldDecision.model_validate(item) for item in list(state.get("field_decisions") or [])]
    verifier_results = [VerifierResult.model_validate(item) for item in list(state.get("verifier_results") or [])]
    final_verdict = state.get("final_verdict") or {}
    warnings = _workspace_safe_warnings(((sanitized_extraction.get("view") or {}).get("warnings")) or [])

    status = SessionState.PENDING_HUMAN_REVIEW

    active_exceptions = sorted(
        {
            code
            for field in field_decisions
            for code in field.reason_codes
            if field.status != "GREEN"
        }
    )

    verifiers = [
        WorkspaceVerifierStatus(
            connector_id=result.connector_id,
            status=result.status,
            reason_codes=normalize_reason_codes(result.reason_codes),
            source_api=result.source_api,
            confidence=result.verification_confidence,
            optional=result.optional,
            high_assurance=result.high_assurance,
            field_ids=result.field_ids,
        )
        for result in verifier_results
    ]

    ui_status = "Ready for human review"

    workspace = WorkspacePayload(
        session_id=str(state.get("session_id") or ""),
        status=status,
        ui_status=ui_status,
        document=WorkspaceDocument(
            filename=state.get("filename"),
            document_type=document_understanding.document_type or str((sanitized_extraction.get("view") or {}).get("document_type") or "unknown"),
            page_count=(sanitized_extraction.get("view") or {}).get("page_count"),
            used_ocr=bool((sanitized_extraction.get("view") or {}).get("used_ocr")),
            warnings=warnings,
            highlights_count=sum(len(field.bounding_boxes) for field in field_decisions),
        ),
        summary=WorkspaceSummary(
            total_fields=len(field_decisions),
            green_count=sum(1 for field in field_decisions if field.status == "GREEN"),
            amber_count=sum(1 for field in field_decisions if field.status == "AMBER"),
            red_count=sum(1 for field in field_decisions if field.status == "RED"),
            matching_score=final_verdict.get("matching_score", document_understanding.matching_score),
            visual_match_probability=final_verdict.get("visual_match_probability", document_understanding.visual_match_probability),
            risk_level=final_verdict.get("risk_level", "MEDIUM"),
            active_exceptions=active_exceptions,
        ),
        fields=field_decisions,
        verifiers=verifiers,
        final_verdict=final_verdict,
        audit=[WorkspaceAuditEntry.model_validate(item) for item in list(state.get("audit_log") or [])],
        actions=_workspace_actions_for_status(status),
    )
    return {"workspace_payload": workspace.model_dump(mode="json")}


def _workspace_actions_for_status(session_status: str) -> list[WorkspaceAction]:
    pending_human_review = session_status in {
        SessionState.VERIFIED_GREEN,
        SessionState.VERIFIED_AMBER,
        SessionState.VERIFIED_RED,
        SessionState.PENDING_HUMAN_REVIEW,
    }
    human_final = session_status in {
        SessionState.HUMAN_APPROVED,
        SessionState.HUMAN_REJECTED,
        SessionState.MANUAL_REVIEW_REQUIRED,
    }
    return [
        WorkspaceAction(action_id="can_rerun", label="Rerun"),
        WorkspaceAction(action_id="can_manual_override", label="Manual Override"),
        WorkspaceAction(action_id="can_export_report", label="Export Report", enabled=not pending_human_review),
        WorkspaceAction(action_id="can_close", label="Close Session", enabled=not pending_human_review or human_final),
        WorkspaceAction(action_id="can_approve", label="Approve", enabled=pending_human_review),
        WorkspaceAction(action_id="can_reject", label="Reject", enabled=pending_human_review),
        WorkspaceAction(action_id="can_manual_review", label="Manual Review", enabled=pending_human_review),
    ]


def _workspace_safe_warnings(raw_warnings: Any) -> list[str]:
    if not isinstance(raw_warnings, list):
        return []
    return [_workspace_safe_warning(item) for item in raw_warnings[:8]]


def _workspace_safe_warning(item: Any) -> str:
    if isinstance(item, dict):
        item = item.get("code") or item.get("type") or "WORKSPACE_WARNING"
    text = str(item or "").strip()
    if not text:
        return "WORKSPACE_WARNING"
    upper_text = text.upper()
    if "RAW" in upper_text or "SECRET" in upper_text or "PRIVATE" in upper_text:
        return "WORKSPACE_WARNING_REDACTED"
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ_:-")
    if len(text) <= 80 and text == upper_text and all(character in allowed for character in text):
        return text
    return "WORKSPACE_WARNING_REDACTED"


def _workspace_verifier_result(result: VerificationTaskResult) -> VerifierResult:
    status = _verifier_status_from_task_result(result)
    provider_key = result.executed_provider_key or result.planned_provider_key or result.verifier_key
    return VerifierResult(
        task_id=result.task_id,
        field_id=result.credential_id,
        connector_id=provider_key,
        status=status,
        verification_confidence=_verification_confidence_from_task_result(result),
        reason_codes=normalize_reason_codes(result.reason_codes),
        source_api=provider_key,
        audit_message=result.explanation,
        optional=False,
        high_assurance=result.planned_provider_key == "entra_verified_id",
        field_ids=[result.credential_id],
    )


def _verifier_status_from_task_result(result: VerificationTaskResult) -> str:
    if result.audit_status == "VERIFIED":
        return "VERIFIED"
    if result.audit_status == "MISMATCH":
        return "MISMATCH"
    if result.task_status == "SKIPPED":
        return "SKIPPED"
    if "TIMEOUT" in set(result.reason_codes or []):
        return "TIMEOUT"
    return "ERROR"


def _verification_confidence_from_task_result(result: VerificationTaskResult) -> float:
    if result.confidence is not None:
        return float(result.confidence)
    if result.audit_status == "VERIFIED":
        return 0.95
    if result.audit_status == "MISMATCH":
        return 0.0
    if result.audit_status in {"MANUAL_REVIEW", "PARTIAL", "UNVERIFIED"}:
        return 0.35
    return 0.0


def _safe_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe_keys = {
        "credential_id",
        "label",
        "category",
        "page",
        "is_pii",
        "claim_type",
        "required_fields",
        "assurance_required",
        "provider_candidates",
        "preferred_provider_key",
        "priority",
        "planner_reason",
        "planned_provider_key",
        "planned_provider_label",
        "fallback_reason",
    }
    return {key: value for key, value in dict(payload or {}).items() if key in safe_keys}

def _invoke_gemini_with_fallback(
    *,
    runtime_policy: AgentRuntimePolicy,
    schema,
    prompt: str,
    fallback_model,
    stage_name: str,
    state_key: str | None = None,
) -> dict[str, Any]:
    if not _gemini_enabled(runtime_policy):
        return _fallback_response(stage_name, fallback_model, "Gemini disabled or API key missing.", state_key=state_key)

    try:
        llm = _build_structured_gemini_llm(runtime_policy=runtime_policy, schema=schema)
        response = llm.invoke(prompt)
        payload = _validated_payload(schema, response)
        
        result_key = state_key or _state_key_for_collection(schema)
        result_payload = payload if schema is GeminiDocumentUnderstanding else payload.get(_default_collection_key(schema), [])
        
        return {
            result_key: result_payload,
            "audit_log": [_audit_item(stage_name, "Gemini structured response accepted.")],
        }
    except Exception as exc:
        LOGGER.warning(f"Gemini invocation failed at {stage_name}: {exc}")
        return _fallback_response(stage_name, fallback_model, str(exc), state_key=state_key)

def _fallback_response(stage_name: str, fallback_model, error_message: str, *, state_key: str | None = None) -> dict[str, Any]:
    payload = fallback_model.model_dump(mode="json") if hasattr(fallback_model, "model_dump") else fallback_model.dict()
    
    result_key = "document_understanding" if isinstance(fallback_model, GeminiDocumentUnderstanding) else (state_key or _state_key_for_collection(type(fallback_model)))
    result_payload = payload if isinstance(fallback_model, GeminiDocumentUnderstanding) else payload.get(_default_collection_key(type(fallback_model)), [])

    return {
        result_key: result_payload,
        "gemini_errors": [f"{stage_name}: {error_message}"],
        "gemini_fallback_used": True,
        "audit_log": [_audit_item(stage_name, "Gemini fallback applied.", level="WARNING")],
    }

def _build_structured_gemini_llm(*, runtime_policy: AgentRuntimePolicy, schema):
    del runtime_policy
    llm = build_gemini_llm()
    return llm.with_structured_output(schema)

def _gemini_enabled(runtime_policy: AgentRuntimePolicy) -> bool:
    return (
        runtime_policy.orchestration_enabled
        and runtime_policy.provider_key == "gemini"
        and bool(runtime_policy.gemini_api_key)
        and runtime_policy.gemini_structured_output_enabled
    )


def _validated_payload(schema, response: Any) -> dict[str, Any]:
    if hasattr(response, "model_dump"):
        payload = response.model_dump(mode="json")
    elif hasattr(response, "dict"):
        payload = response.dict()
    else:
        payload = response
    model = schema.model_validate(payload)
    return model.model_dump(mode="json")

def _build_document_understanding_prompt(
    *,
    extraction_payload: dict[str, Any],
    raw_text: str,
    runtime_policy: AgentRuntimePolicy,
) -> str:
    minimized = minimize_extraction_payload(
        extraction_payload,
        max_fields=runtime_policy.max_fields_for_provider,
        max_value_chars=runtime_policy.max_value_chars,
    )
    raw_text_block = ""
    if runtime_policy.gemini_demo_raw_text_enabled and raw_text.strip():
        raw_text_block = f"\nRaw extracted text (session scoped, demo only):\n{raw_text[: runtime_policy.gemini_max_input_chars]}"
    return (
        "Return structured document understanding for generalized verification. "
        "Do not emit prose outside the schema."
        f"\nStructured extraction summary:\n{json.dumps(minimized, default=str)}"
        f"{raw_text_block}"
    )

def _build_field_normalization_prompt(
    *,
    extraction_payload: dict[str, Any],
    raw_text: str,
    runtime_policy: AgentRuntimePolicy,
) -> str:
    raw_text_block = ""
    if runtime_policy.gemini_demo_raw_text_enabled and raw_text.strip():
        raw_text_block = f"\nRaw extracted text (session scoped, demo only):\n{raw_text[: runtime_policy.gemini_max_input_chars]}"
    return (
        "Normalize extracted document fields for generalized verification. Return structured fields only."
        f"\nExtraction payload:\n{json.dumps(minimize_extraction_payload(extraction_payload, max_fields=runtime_policy.max_fields_for_provider, max_value_chars=runtime_policy.max_value_chars), default=str)}"
        f"{raw_text_block}"
    )

def _build_credential_grouping_prompt(
    *,
    document_understanding: dict[str, Any],
    normalized_fields: list[GeminiNormalizedField],
) -> str:
    return (
        "Group normalized document fields into verifier-ready credential groupings. Return structured groups only."
        f"\nDocument understanding:\n{json.dumps(document_understanding, default=str)}"
        f"\nNormalized fields:\n{json.dumps([field.model_dump(mode='json') for field in normalized_fields], default=str)}"
    )

def _fallback_document_understanding(extraction_payload: dict[str, Any]) -> GeminiDocumentUnderstanding:
    view = extraction_payload.get("view") or {}
    warnings = [str(item) for item in list(view.get("warnings") or [])]
    field_details = list(view.get("field_details") or [])
    document_type = str(view.get("document_type") or extraction_payload.get("document_type") or "unknown_document")
    if document_type == "unknown":
        document_type = "unknown_document"
    claim_types = sorted(
        {
            _claim_type_from_label(
                str(item.get("category") or item.get("label") or item.get("key") or "")
            )
            for item in _claims_from_extraction_payload(extraction_payload)
            if isinstance(item, dict)
        }
    )
    return GeminiDocumentUnderstanding(
        document_type=document_type,
        document_type_confidence=0.7 if document_type != "unknown_document" else 0.2,
        likely_claim_types=claim_types or ["generic_claim"],
        credential_group_hints=claim_types[:4],
        mandatory_fields=[
            str(field.get("name") or field.get("field_id"))
            for field in list((extraction_payload.get("trust_input") or {}).get("fields") or [])
            if isinstance(field, dict) and field.get("is_mandatory")
        ],
        optional_fields=[
            str(field.get("name") or field.get("field_id"))
            for field in list((extraction_payload.get("trust_input") or {}).get("fields") or [])
            if isinstance(field, dict) and not field.get("is_mandatory")
        ],
        safety_flags=["UNSAFE_OR_MALFORMED"] if bool((extraction_payload.get("trust_input") or {}).get("is_unsafe")) else [],
        ambiguity_flags=warnings,
        summary="Deterministic document understanding fallback was used.",
        explanation="Gemini was disabled or unavailable, so deterministic extraction remained authoritative.",
        unsafe_or_malformed=bool((extraction_payload.get("trust_input") or {}).get("is_unsafe")),
        grounding_confidence=1.0 if field_details else 0.0,
        matching_score=0.0,
        visual_match_probability=0.0,
        risk_flags=warnings,
    )

def _claims_from_extraction_payload(extraction_payload: dict[str, Any]) -> list[dict[str, Any]]:
    view = extraction_payload.get("view") or {}
    claims = [
        dict(item)
        for item in list(view.get("field_details") or [])
        if isinstance(item, dict)
    ]
    if not claims:
        claims = [
            dict(item)
            for item in list(view.get("field_candidates") or [])
            if isinstance(item, dict)
        ]
    if claims:
        return claims
    trust_input = extraction_payload.get("trust_input") or {}
    return [
        {
            "claim_id": str(field.get("name") or f"claim-{index}"),
            "field_id": field.get("name"),
            "label": str(field.get("name") or "").replace("_", " ").title(),
            "value": field.get("value"),
            "confidence": field.get("confidence"),
            "requires_verification": field.get("is_mandatory", True),
        }
        for index, field in enumerate(list(trust_input.get("fields") or []), start=1)
        if isinstance(field, dict)
    ]


def _deterministic_normalized_fields(
    extraction_payload: dict[str, Any],
    semantic_claims: list[dict[str, Any]] | None = None,
) -> list[GeminiNormalizedField]:
    trust_input = extraction_payload.get("trust_input") or {}
    view = extraction_payload.get("view") or {}
    detail_by_key = {
        str(detail.get("key") or ""): detail
        for detail in list(view.get("field_details") or [])
        if isinstance(detail, dict)
    }
    semantic_by_field = {
        str(claim.get("field_id") or claim.get("claim_id") or ""): claim
        for claim in list(semantic_claims or [])
        if isinstance(claim, dict)
    }
    normalized_fields: list[GeminiNormalizedField] = []
    for field in list(trust_input.get("fields") or []):
        field_name = str(field.get("name") or "")
        if not field_name:
            continue
        detail = detail_by_key.get(field_name, {})
        semantic_claim = semantic_by_field.get(field_name, {})
        boxes = detail.get("bounding_boxes") or []
        normalized_fields.append(
            GeminiNormalizedField(
                field_id=field_name,
                label=str(semantic_claim.get("canonical_label") or detail.get("label") or field_name.replace("_", " ").title()),
                extracted_value=safe_normalized_string(field.get("value")),
                normalized_value=safe_normalized_string(semantic_claim.get("normalized_value") or field.get("value")),
                ai_confidence=float(field.get("confidence") or 0.0),
                grounding_confidence=1.0 if boxes or field.get("is_grounded") else 0.0,
                mandatory=bool(field.get("is_mandatory")),
                verifier_hint=None,
                bounding_boxes=boxes,
            )
        )
    if not normalized_fields:
        for index, claim in enumerate(list(semantic_claims or []), start=1):
            if not isinstance(claim, dict):
                continue
            field_id = str(claim.get("field_id") or claim.get("claim_id") or f"field-{index}")
            normalized_fields.append(
                GeminiNormalizedField(
                    field_id=field_id,
                    label=str(claim.get("canonical_label") or claim.get("label") or field_id.replace("_", " ").title()),
                    extracted_value=safe_normalized_string(claim.get("normalized_value") or claim.get("value_preview")),
                    normalized_value=safe_normalized_string(claim.get("normalized_value") or claim.get("value_preview")),
                    ai_confidence=float(claim.get("confidence") or 0.0),
                    grounding_confidence=0.0,
                    mandatory=bool(claim.get("requires_verification", True)),
                    verifier_hint=None,
                    bounding_boxes=[],
                )
            )
    return normalized_fields

def _deterministic_credential_groups(
    extraction_payload: dict[str, Any],
    normalized_fields: list[GeminiNormalizedField],
) -> list[GeminiCredentialGroup]:
    del extraction_payload
    fields_by_claim_type: dict[str, list[GeminiNormalizedField]] = {}
    for field in normalized_fields:
        fields_by_claim_type.setdefault(_claim_type_from_field(field), []).append(field)

    groups: list[GeminiCredentialGroup] = []
    for index, (claim_type, fields) in enumerate(fields_by_claim_type.items(), start=1):
        field_ids = [field.field_id for field in fields]
        required_field_ids = [field.field_id for field in fields if field.mandatory]
        assurance_required = _assurance_for_claim_type(claim_type, bool(required_field_ids))
        groups.append(
            GeminiCredentialGroup(
                group_id=f"credential-{index}",
                credential_id=f"credential-{index}",
                credential_type=claim_type,
                label=f"{claim_type.replace('_', ' ').title()} Verification",
                claim_ids=field_ids,
                field_ids=field_ids,
                required_field_ids=required_field_ids or field_ids,
                optional_field_ids=[field_id for field_id in field_ids if field_id not in set(required_field_ids)],
                connector_id=None,
                claim_type=claim_type,
                assurance_required=assurance_required,
                group_confidence=sum(field.ai_confidence for field in fields) / max(len(fields), 1),
                optional=not bool(required_field_ids),
                high_assurance=assurance_required == "HIGH",
                explanation="Deterministic grouping based on normalized claim type.",
            )
        )
    if groups:
        return groups
    return [
        GeminiCredentialGroup(
            group_id="primary-credential",
            credential_id="primary-credential",
            credential_type="generic_claim",
            label="Primary Credential Verification",
            claim_ids=[],
            field_ids=[],
            required_field_ids=[],
            connector_id=None,
            claim_type="generic_claim",
            assurance_required="MEDIUM",
            optional=False,
            high_assurance=False,
            explanation="Deterministic grouping fallback for unknown extraction.",
        )
    ]


def _recommend_route_for_group(group: GeminiCredentialGroup) -> RouteRecommendation:
    claim_type = str(group.claim_type or group.credential_type or "generic_claim")
    assurance_required = group.assurance_required or _assurance_for_claim_type(claim_type, not group.optional)
    priority = "OPTIONAL" if group.optional else "REQUIRED"
    provider_candidates = _provider_candidates_for_claim_type(claim_type, assurance_required)
    preferred_provider_key = str(provider_candidates[0].get("provider_id") if isinstance(provider_candidates[0], dict) else provider_candidates[0])
    return RouteRecommendation(
        credential_id=group.credential_id or group.group_id,
        claim_type=claim_type,
        provider_candidates=provider_candidates,
        preferred_provider_key=preferred_provider_key,
        provider_id=preferred_provider_key,
        assurance_required=assurance_required,
        priority=priority,
        planner_reason=(
            "Route recommendation is advisory only; deterministic verifier execution and trust rules remain authoritative."
        ),
    )


def _provider_candidates_for_claim_type(claim_type: str, assurance_required: str) -> list[dict[str, Any]]:
    normalized = str(claim_type or "").lower()
    try:
        from ..verifier_execution.registry import build_default_verifier_registry

        registry_candidates = build_default_verifier_registry().get_provider_candidates(
            claim_type=normalized,
            assurance_required=assurance_required,
            context={"category": normalized},
        )
        if registry_candidates:
            return [
                {
                    "provider_id": item.provider_key,
                    "provider_label": item.provider_label,
                    "provider_mode": "local_fixture" if item.provider_key == "local_mock" else "manual" if item.provider_key == "manual_review" else "architectural_candidate",
                    "verifier_key": item.verifier_key,
                    "reason_codes": list(item.reason_codes or []),
                }
                for item in registry_candidates
            ]
    except Exception:
        pass

    candidates: list[dict[str, Any]] = []
    if normalized in {"identity", "identity_document", "certificate", "certificate_document", "academic", "academic_degree", "academic_credential"}:
        candidates.append(
            {
                "provider_id": "entra_verified_id",
                "provider_label": "Microsoft Entra Verified ID",
                "provider_mode": "architectural_candidate",
            }
        )
    candidates.append(
        {
            "provider_id": "local_mock",
            "provider_label": "Local Mock Registry",
            "provider_mode": "local_fixture",
        }
    )
    if assurance_required != "LOW" or normalized in {"generic_claim", "unknown", "unknown_document"}:
        candidates.append(
            {
                "provider_id": "manual_review",
                "provider_label": "Manual Review",
                "provider_mode": "manual",
            }
        )
    return candidates


def _claim_type_from_field(field: GeminiNormalizedField) -> str:
    haystack = f"{field.field_id} {field.label}".lower()
    if any(token in haystack for token in ("identity", "passport", "aadhaar", "pan", "name", "date of birth")):
        return "identity"
    if any(token in haystack for token in ("employment", "employer", "job", "role")):
        return "employment"
    if any(token in haystack for token in ("invoice", "amount", "tax", "balance", "account")):
        return "financial"
    if any(token in haystack for token in ("certificate", "certification", "credential", "license")):
        return "certificate"
    if any(token in haystack for token in ("issuer", "institution", "organization", "authority")):
        return "issuer_identity"
    return "generic_claim"


def _claim_type_from_label(label: str) -> str:
    normalized = safe_normalized_string(label).lower()
    if not normalized:
        return "generic_claim"
    synthetic_field = GeminiNormalizedField(
        field_id=normalized.replace(" ", "_"),
        label=normalized,
    )
    return _claim_type_from_field(synthetic_field)


def _assurance_for_claim_type(claim_type: str, required: bool) -> str:
    normalized = str(claim_type or "").lower()
    if normalized in {"identity", "identity_document", "license", "financial", "tax"}:
        return "HIGH"
    if required or normalized in {"certificate", "academic", "academic_degree", "academic_credential"}:
        return "MEDIUM"
    return "LOW"


def _planning_warnings(tasks: list[VerificationTask]) -> list[str]:
    warnings: list[str] = []
    for task in tasks:
        if not task.required_fields:
            warnings.append(f"{task.task_id}:MISSING_REQUIRED_FIELDS")
        if not task.provider_candidates:
            warnings.append(f"{task.task_id}:NO_PROVIDER_CANDIDATES")
    return warnings


def _slug_id(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in str(value).lower()).strip("-") or "task"

def _resolve_extraction_confidence(extraction_payload: dict[str, Any], field_id: str, extracted_value: str) -> float:
    trust_input = extraction_payload.get("trust_input") or {}
    for field in list(trust_input.get("fields") or []):
        if str(field.get("name") or "") == field_id:
            try:
                return float(field.get("confidence") or 0.0)
            except (TypeError, ValueError):
                return 0.0
    confidence_map = (extraction_payload.get("view") or {}).get("confidence") or {}
    if field_id in confidence_map:
        try:
            return float(confidence_map[field_id])
        except (TypeError, ValueError):
            return 0.0
    return 1.0 if extracted_value else 0.0

def _verification_confidence_from_status(status: str) -> float:
    normalized = str(status or "").upper()
    if normalized == "VERIFIED":
        return 0.95
    if normalized == "MISMATCH":
        return 0.0
    if normalized == "TIMEOUT":
        return 0.2
    if normalized == "ERROR":
        return 0.1
    return 0.0

def _verifier_audit_message(connector_id: str, status: str, raw_result: dict[str, Any]) -> str:
    normalized = str(status or "").upper()
    if normalized == "VERIFIED":
        return f"{connector_id} verified the claim."
    if normalized == "MISMATCH":
        return f"{connector_id} reported a mismatch."
    if normalized == "TIMEOUT":
        return f"{connector_id} timed out after retries."
    return str(raw_result.get("message") or f"{connector_id} could not verify the claim.")

def _audit_item(stage: str, message: str, *, level: str = "INFO") -> dict[str, Any]:
    return WorkspaceAuditEntry(
        stage=stage,
        message=message,
        level=level,
        timestamp=datetime.now(timezone.utc).isoformat(),
    ).model_dump(mode="json")

def _state_key_for_collection(schema) -> str:
    if schema is GeminiNormalizedFieldCollection:
        return "normalized_fields"
    if schema is GeminiCredentialGroupCollection:
        return "credential_groups"
    return "document_understanding"

def _default_collection_key(schema) -> str:
    if schema is GeminiNormalizedFieldCollection:
        return "fields"
    if schema is GeminiCredentialGroupCollection:
        return "groups"
    return "document_understanding"

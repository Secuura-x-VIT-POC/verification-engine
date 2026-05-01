from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..workflow.runtime import build_connector_responses, build_policy, extract_document_payload
from ..verification_domain.adapters import build_session_credentials, build_session_verification_plan
from ..verification_domain.contracts import SessionCredentialCollection, SessionVerificationPlan
from ..verifier_execution.contracts import VerificationTaskResult
from ..verifier_execution.service import build_execution_artifacts
from ..trust.trust_engine import build_final_verdict, determine_field_decision
from .policies import AgentRuntimePolicy, load_agent_runtime_policy, minimize_extraction_payload
from .schemas import (
    FieldDecision,
    GeminiCredentialGroup,
    GeminiCredentialGroupCollection,
    GeminiDocumentUnderstanding,
    GeminiNormalizedField,
    GeminiNormalizedFieldCollection,
    VerificationTask,
    VerifierResult,
    WorkspaceAction,
    WorkspaceAuditEntry,
    WorkspaceDocument,
    WorkspacePayload,
    WorkspaceSummary,
    WorkspaceVerifierStatus,
)
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
    graph.add_node("build_verification_tasks", _build_verification_tasks)
    graph.add_node("run_verifier_apis", _run_verifier_apis)
    graph.add_node("gemini_confidence_fusion", _gemini_confidence_fusion)
    graph.add_node("policy_verdict", _policy_verdict)
    graph.add_node("build_workspace_payload", _build_workspace_payload)
    
    graph.add_edge(START, "load_extraction_state")
    graph.add_edge("load_extraction_state", "gemini_document_understanding")
    graph.add_edge("gemini_document_understanding", "gemini_field_normalization")
    graph.add_edge("gemini_field_normalization", "gemini_credential_grouping")
    graph.add_edge("gemini_credential_grouping", "build_verification_tasks")
    graph.add_edge("build_verification_tasks", "run_verifier_apis")
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
        "audit_log": [_audit_item("load_extraction_state", "Extraction payload loaded.")],
    }

def _gemini_document_understanding(
    state: GeneralizedVerificationState,
    runtime_policy: AgentRuntimePolicy,
) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload") or {}
    fallback = _fallback_document_understanding(extraction_payload)
    
    return _invoke_gemini_with_fallback(
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

def _gemini_field_normalization(
    state: GeneralizedVerificationState,
    runtime_policy: AgentRuntimePolicy,
) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload") or {}
    fallback = GeminiNormalizedFieldCollection(fields=_deterministic_normalized_fields(extraction_payload))
    
    return _invoke_gemini_with_fallback(
        runtime_policy=runtime_policy,
        schema=GeminiNormalizedFieldCollection,
        prompt=_build_field_normalization_prompt(
            extraction_payload=state.get("sanitized_extraction") or extraction_payload,
            raw_text=state.get("raw_text") or "",
            runtime_policy=runtime_policy,
        ),
        fallback_model=fallback,
        stage_name="gemini_field_normalization",
        state_key="normalized_fields",
    )

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

def _build_verification_tasks(state: GeneralizedVerificationState) -> dict[str, Any]:
    extraction_payload = state.get("extraction_payload") or {}
    session_id = str(state.get("session_id") or "")
    credentials = build_session_credentials(session_id, extraction_payload)
    plan = build_session_verification_plan(
        session_id,
        extraction_payload,
        credentials=credentials,
    )

    workspace_tasks: list[VerificationTask] = []
    for task in plan.tasks:
        workspace_tasks.append(
            VerificationTask(
                task_id=task.task_id,
                field_id=task.credential_id,
                label=str(task.input_payload.get("label") or task.credential_id),
                connector_id=task.selected_provider or task.planned_provider_key or task.verifier_key,
                claim_type=task.claim_type or task.verification_type,
                provider_candidates=list(task.provider_candidates or []),
                required_fields=list(task.required_fields or []),
                assurance_required=task.assurance_required,
                optional=not task.required,
                high_assurance=task.assurance_required == "HIGH",
                input_payload=_safe_task_payload(task.input_payload),
                field_ids=[task.credential_id],
            )
        )

    return {
        "domain_credentials": credentials.model_dump(mode="json"),
        "domain_verification_plan": plan.model_dump(mode="json"),
        "verification_tasks": [task.model_dump(mode="json") for task in workspace_tasks],
        "audit_log": [_audit_item("build_verification_tasks", f"Built {len(workspace_tasks)} verification task(s).")],
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
    
    verifier_by_field: dict[str, VerifierResult] = {}
    for verifier in verifier_results:
        for field_id in verifier.field_ids or [verifier.field_id]:
            verifier_by_field[field_id] = verifier

    field_decisions: list[FieldDecision] = []
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
            unsafe_or_malformed=document_understanding.unsafe_or_malformed,
        )
        decision.bounding_boxes = list(field.bounding_boxes)
        field_decisions.append(decision)

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

def _build_workspace_payload(state: GeneralizedVerificationState) -> dict[str, Any]:
    sanitized_extraction = state.get("sanitized_extraction") or {}
    document_understanding = GeminiDocumentUnderstanding.model_validate(state.get("document_understanding") or {})
    field_decisions = [FieldDecision.model_validate(item) for item in list(state.get("field_decisions") or [])]
    verifier_results = [VerifierResult.model_validate(item) for item in list(state.get("verifier_results") or [])]
    final_verdict = state.get("final_verdict") or {}
    warnings = list(((sanitized_extraction.get("view") or {}).get("warnings")) or [])

    outcome = final_verdict.get("outcome", "AMBER")
    if outcome == "GREEN":
        status = "VERIFIED_GREEN"
    elif outcome == "RED":
        status = "VERIFIED_RED"
    else:
        status = "VERIFIED_AMBER"

    active_exceptions = sorted(
        {
            code
            for field in field_decisions
            for code in field.reason_codes
            if field.status != "GREEN"
        }
    )

    if "LOW_CONFIDENCE_REVIEW_REQUIRED" in active_exceptions:
        status = "PENDING_HUMAN_REVIEW"

    verifiers = [
        WorkspaceVerifierStatus(
            connector_id=result.connector_id,
            status=result.status,
            reason_codes=result.reason_codes,
            source_api=result.source_api,
            confidence=result.verification_confidence,
            optional=result.optional,
            high_assurance=result.high_assurance,
            field_ids=result.field_ids,
        )
        for result in verifier_results
    ]

    ui_status = "Ready"
    if status == "PENDING_HUMAN_REVIEW":
        ui_status = "Ready for human review"
    elif status.startswith("VERIFIED_"):
        ui_status = "Verification completed"

    workspace = WorkspacePayload(
        session_id=str(state.get("session_id") or ""),
        status=status,
        ui_status=ui_status,
        document=WorkspaceDocument(
            filename=state.get("filename"),
            document_type=document_understanding.document_type or str((sanitized_extraction.get("view") or {}).get("document_type") or "unknown"),
            page_count=(sanitized_extraction.get("view") or {}).get("page_count"),
            used_ocr=bool((sanitized_extraction.get("view") or {}).get("used_ocr")),
            warnings=[str(item) for item in warnings],
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
        "VERIFIED_GREEN",
        "VERIFIED_AMBER",
        "VERIFIED_RED",
        "PENDING_HUMAN_REVIEW",
    }
    human_final = session_status in {"HUMAN_APPROVED", "HUMAN_REJECTED", "MANUAL_REVIEW_REQUIRED"}
    return [
        WorkspaceAction(action_id="can_rerun", label="Rerun"),
        WorkspaceAction(action_id="can_manual_override", label="Manual Override"),
        WorkspaceAction(action_id="can_export_report", label="Export Report", enabled=not pending_human_review),
        WorkspaceAction(action_id="can_close", label="Close Session", enabled=not pending_human_review or human_final),
        WorkspaceAction(action_id="can_approve", label="Approve", enabled=pending_human_review),
        WorkspaceAction(action_id="can_reject", label="Reject", enabled=pending_human_review),
        WorkspaceAction(action_id="can_manual_review", label="Manual Review", enabled=pending_human_review),
    ]


def _workspace_verifier_result(result: VerificationTaskResult) -> VerifierResult:
    status = _verifier_status_from_task_result(result)
    provider_key = result.executed_provider_key or result.planned_provider_key or result.verifier_key
    return VerifierResult(
        task_id=result.task_id,
        field_id=result.credential_id,
        connector_id=provider_key,
        status=status,
        verification_confidence=_verification_confidence_from_task_result(result),
        reason_codes=list(result.reason_codes or []),
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
        payload = response.model_dump(mode="json") if hasattr(response, "model_dump") else response.dict()
        
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
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model=runtime_policy.gemini_model,
        temperature=0.0,
        google_api_key=runtime_policy.gemini_api_key,
    )
    return llm.with_structured_output(schema)

def _gemini_enabled(runtime_policy: AgentRuntimePolicy) -> bool:
    return (
        runtime_policy.orchestration_enabled
        and runtime_policy.provider_key == "gemini"
        and bool(runtime_policy.gemini_api_key)
    )

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
    return GeminiDocumentUnderstanding(
        document_type=str(view.get("document_type") or extraction_payload.get("document_type") or "unknown"),
        summary="Deterministic document understanding fallback was used.",
        explanation="Gemini was disabled or unavailable, so deterministic extraction remained authoritative.",
        unsafe_or_malformed=bool((extraction_payload.get("trust_input") or {}).get("is_unsafe")),
        grounding_confidence=1.0 if field_details else 0.0,
        matching_score=0.0,
        visual_match_probability=0.0,
        risk_flags=warnings,
    )

def _deterministic_normalized_fields(extraction_payload: dict[str, Any]) -> list[GeminiNormalizedField]:
    trust_input = extraction_payload.get("trust_input") or {}
    view = extraction_payload.get("view") or {}
    detail_by_key = {
        str(detail.get("key") or ""): detail
        for detail in list(view.get("field_details") or [])
        if isinstance(detail, dict)
    }
    normalized_fields: list[GeminiNormalizedField] = []
    for field in list(trust_input.get("fields") or []):
        field_name = str(field.get("name") or "")
        if not field_name:
            continue
        detail = detail_by_key.get(field_name, {})
        boxes = detail.get("bounding_boxes") or []
        normalized_fields.append(
            GeminiNormalizedField(
                field_id=field_name,
                label=str(detail.get("label") or field_name.replace("_", " ").title()),
                extracted_value=str(field.get("value") or ""),
                normalized_value=str(field.get("value") or ""),
                ai_confidence=float(field.get("confidence") or 0.0),
                grounding_confidence=1.0 if boxes or field.get("is_grounded") else 0.0,
                mandatory=bool(field.get("is_mandatory")),
                verifier_hint=None,
                bounding_boxes=boxes,
            )
        )
    return normalized_fields

def _deterministic_credential_groups(
    extraction_payload: dict[str, Any],
    normalized_fields: list[GeminiNormalizedField],
) -> list[GeminiCredentialGroup]:
    field_ids = [field.field_id for field in normalized_fields if field.mandatory] or [field.field_id for field in normalized_fields]
    return [
        GeminiCredentialGroup(
            group_id="primary-credential",
            label="Primary Credential Verification",
            field_ids=field_ids,
            connector_id=None,
            claim_type="credential",
            optional=False,
            high_assurance=True,
            explanation="Deterministic grouping based on extracted connector input.",
        )
    ]

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

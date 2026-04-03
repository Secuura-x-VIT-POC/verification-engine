from __future__ import annotations

import logging
from typing import Any

from ..agent_orchestration.service import (
    build_and_persist_agent_pass_a,
    build_and_persist_agent_pass_b,
    enrich_credential_audits_with_agent_explanations,
    enrich_generalized_analysis,
    mark_agent_failure,
)
from ..verifier_execution.service import (
    build_and_persist_execution_artifacts,
    get_credential_bundles_for_session,
    get_verification_execution_summary_for_session,
    get_verification_task_results_for_session,
)
from .adapters import (
    build_session_credential_audits,
    build_session_credentials,
    build_session_verification_plan,
    build_session_verification_summary,
)
from .contracts import (
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_NOT_STARTED,
    ANALYSIS_STATUS_PLAN_BUILT,
    ANALYSIS_STATUS_READY,
    ANALYSIS_STATUS_PROFILED,
    ANALYSIS_STATUS_CREDENTIALS_BUILT,
    ANALYSIS_STATUS_AUDITS_ASSEMBLED,
    CredentialAuditCollection,
    DocumentProfile,
    DocumentVerificationSummary,
    SessionAnalysisStatus,
    SessionCredentialCollection,
    SessionVerificationPlan,
)


LOGGER = logging.getLogger(__name__)
_UNSET = object()


def build_document_profile(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
    *,
    credentials: SessionCredentialCollection | None = None,
    verification_plan: SessionVerificationPlan | None = None,
) -> DocumentProfile:
    credential_collection = credentials or build_credentials(session_id, extraction_payload)
    plan = verification_plan or build_verification_plan(
        session_id,
        extraction_payload,
        credentials=credential_collection,
    )
    has_extraction_payload = extraction_payload is not None

    document_type = credential_collection.document_type
    detected_categories = _collect_detected_categories(credential_collection)
    extraction_methods_used = _collect_extraction_methods(extraction_payload, credential_collection)
    page_count = _coerce_page_count((extraction_payload or {}).get("page_count"))
    pii_detected = any(credential.is_pii for credential in credential_collection.credentials)
    requires_manual_review = (
        has_extraction_payload
        and (
            not credential_collection.credentials
            or document_type == "unknown"
            or any(decision.manual_review_recommended for decision in plan.route_decisions)
        )
    )

    notes: list[str] = []
    if has_extraction_payload:
        error_message = (extraction_payload or {}).get("error_message")
        enrichment_metadata = (extraction_payload or {}).get("enrichment_metadata") or {}
        if error_message:
            notes.append(str(error_message))
        if not credential_collection.credentials:
            notes.append("No credentials were extracted from the current document payload.")
        if document_type == "unknown":
            notes.append("Document type could not be confidently inferred from the current extraction payload.")
        if any(decision.manual_review_recommended for decision in plan.route_decisions):
            notes.append("At least one credential is currently routed to manual review.")
        if enrichment_metadata.get("pii_enrichment_used"):
            notes.append("NVIDIA GLiNER PII enrichment contributed label or entity typing support.")
        elif enrichment_metadata.get("warning_codes"):
            notes.append(
                "NVIDIA GLiNER PII enrichment was unavailable and deterministic extraction remained the source of record."
            )

    return DocumentProfile(
        session_id=session_id,
        document_type=document_type,
        document_family=_infer_document_family(document_type, detected_categories),
        page_count=page_count,
        extraction_methods_used=extraction_methods_used,
        pii_detected=pii_detected,
        detected_categories=detected_categories,
        requires_manual_review=requires_manual_review,
        notes=notes,
    )


def build_credentials(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
) -> SessionCredentialCollection:
    return build_session_credentials(session_id, extraction_payload)


def build_verification_plan(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
    *,
    credentials: SessionCredentialCollection | None = None,
) -> SessionVerificationPlan:
    return build_session_verification_plan(
        session_id,
        extraction_payload,
        credentials=credentials,
    )


def assemble_credential_audits(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
    *,
    connector_payload: Any = None,
    trust_outcome: str | None = None,
    reason_codes: list[str] | None = None,
    audit_timestamp=None,
    credentials: SessionCredentialCollection | None = None,
    verification_plan: SessionVerificationPlan | None = None,
    credential_bundles=None,
) -> CredentialAuditCollection:
    return build_session_credential_audits(
        session_id,
        extraction_payload,
        connector_payload=connector_payload,
        trust_outcome=trust_outcome,
        reason_codes=reason_codes,
        audit_timestamp=audit_timestamp,
        credentials=credentials,
        verification_plan=verification_plan,
        credential_bundles=credential_bundles,
    )


def build_verification_summary(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
    *,
    credential_audits: CredentialAuditCollection,
    trust_outcome: str | None = None,
    reason_codes: list[str] | None = None,
    credentials: SessionCredentialCollection | None = None,
) -> DocumentVerificationSummary:
    return build_session_verification_summary(
        session_id,
        extraction_payload,
        credential_audits=credential_audits,
        trust_outcome=trust_outcome,
        reason_codes=reason_codes,
        credentials=credentials,
    )


def persist_analysis_artifacts(
    session,
    *,
    document_profile=_UNSET,
    generalized_credentials=_UNSET,
    verification_plan=_UNSET,
    credential_audits=_UNSET,
    verification_summary=_UNSET,
    generalized_analysis_status=_UNSET,
    generalized_analysis_error=_UNSET,
) -> None:
    if document_profile is not _UNSET:
        session.document_profile_payload = _dump_model(document_profile)
    if generalized_credentials is not _UNSET:
        session.generalized_credentials_payload = _dump_model(generalized_credentials)
    if verification_plan is not _UNSET:
        session.verification_plan_payload = _dump_model(verification_plan)
    if credential_audits is not _UNSET:
        session.credential_audits_payload = _dump_model(credential_audits)
    if verification_summary is not _UNSET:
        session.verification_summary_payload = _dump_model(verification_summary)
    if generalized_analysis_status is not _UNSET:
        session.generalized_analysis_status = generalized_analysis_status
    if generalized_analysis_error is not _UNSET:
        session.generalized_analysis_error = generalized_analysis_error


def build_and_persist_initial_analysis(session) -> dict[str, Any]:
    baseline_credentials = build_credentials(session.id, session.extraction_payload)
    baseline_verification_plan = build_verification_plan(
        session.id,
        session.extraction_payload,
        credentials=baseline_credentials,
    )
    baseline_document_profile = build_document_profile(
        session.id,
        session.extraction_payload,
        credentials=baseline_credentials,
        verification_plan=baseline_verification_plan,
    )
    credentials = baseline_credentials
    verification_plan = baseline_verification_plan
    document_profile = baseline_document_profile
    if hasattr(session, "agent_document_understanding_payload"):
        session.agent_document_understanding_payload = None
    if hasattr(session, "agent_credential_candidates_payload"):
        session.agent_credential_candidates_payload = None
    if hasattr(session, "agent_route_recommendations_payload"):
        session.agent_route_recommendations_payload = None
    if hasattr(session, "agent_explanations_payload"):
        session.agent_explanations_payload = None
    if hasattr(session, "agent_run_summary_payload"):
        session.agent_run_summary_payload = None
    if hasattr(session, "agent_run_status"):
        session.agent_run_status = "NOT_STARTED"
    if hasattr(session, "agent_run_error"):
        session.agent_run_error = None

    try:
        agent_artifacts = build_and_persist_agent_pass_a(
            session,
            document_profile=baseline_document_profile,
            credentials=baseline_credentials,
            verification_plan=baseline_verification_plan,
        )
        enriched = enrich_generalized_analysis(
            document_profile=baseline_document_profile,
            credentials=baseline_credentials,
            verification_plan=baseline_verification_plan,
            agent_artifacts=agent_artifacts,
        )
        document_profile = enriched["document_profile"]
        credentials = enriched["credentials"]
        verification_plan = enriched["verification_plan"]
    except Exception as exc:  # pragma: no cover - defensive path
        mark_agent_failure(session, exc)

    persist_analysis_artifacts(
        session,
        document_profile=document_profile,
        generalized_credentials=credentials,
        verification_plan=verification_plan,
        generalized_analysis_status=ANALYSIS_STATUS_PLAN_BUILT,
        generalized_analysis_error=None,
    )
    if hasattr(session, "verification_task_results_payload"):
        session.verification_task_results_payload = None
    if hasattr(session, "credential_verification_bundles_payload"):
        session.credential_verification_bundles_payload = None
    if hasattr(session, "verification_execution_summary_payload"):
        session.verification_execution_summary_payload = None
    if hasattr(session, "provider_execution_traces_payload"):
        session.provider_execution_traces_payload = None
    if hasattr(session, "provider_execution_status"):
        session.provider_execution_status = "NOT_STARTED"
    if hasattr(session, "provider_execution_error"):
        session.provider_execution_error = None
    if hasattr(session, "provider_operating_mode"):
        session.provider_operating_mode = None
    if hasattr(session, "demo_profile_key"):
        session.demo_profile_key = None
    if hasattr(session, "execution_environment_label"):
        session.execution_environment_label = None
    if hasattr(session, "provider_transition_notes"):
        session.provider_transition_notes = None
    if hasattr(session, "verification_execution_status"):
        session.verification_execution_status = "NOT_STARTED"
    if hasattr(session, "verification_execution_error"):
        session.verification_execution_error = None
    return {
        "document_profile": document_profile,
        "credentials": credentials,
        "verification_plan": verification_plan,
    }


def build_and_persist_final_analysis(session) -> dict[str, Any]:
    credentials = get_credentials_for_session(session)
    verification_plan = get_verification_plan_for_session(session)
    if any(
        (
            session.verification_task_results_payload,
            session.credential_verification_bundles_payload,
            session.verification_execution_summary_payload,
        )
    ):
        execution_artifacts = {
            "task_results": get_verification_task_results_for_session(session),
            "credential_bundles": get_credential_bundles_for_session(session),
            "execution_summary": get_verification_execution_summary_for_session(session),
        }
    else:
        execution_artifacts = build_and_persist_execution_artifacts(
            session,
            credentials=credentials,
            verification_plan=verification_plan,
        )
    document_profile = get_document_profile_for_session(session)
    credential_audits = assemble_credential_audits(
        session.id,
        session.extraction_payload,
        connector_payload=session.connector_payload,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        audit_timestamp=session.verified_at or session.updated_at or session.created_at,
        credentials=credentials,
        verification_plan=verification_plan,
        credential_bundles=execution_artifacts["credential_bundles"],
    )
    try:
        agent_artifacts = build_and_persist_agent_pass_b(
            session,
            document_profile=document_profile,
            credentials=credentials,
            verification_plan=verification_plan,
            verification_task_results=execution_artifacts["task_results"],
            credential_bundles=execution_artifacts["credential_bundles"],
            credential_audits=credential_audits,
        )
        credential_audits = enrich_credential_audits_with_agent_explanations(
            credential_audits,
            agent_artifacts,
        )
    except Exception as exc:  # pragma: no cover - defensive path
        mark_agent_failure(session, exc)
    verification_summary = build_verification_summary(
        session.id,
        session.extraction_payload,
        credential_audits=credential_audits,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        credentials=credentials,
    )
    persist_analysis_artifacts(
        session,
        document_profile=document_profile,
        generalized_credentials=credentials,
        verification_plan=verification_plan,
        credential_audits=credential_audits,
        verification_summary=verification_summary,
        generalized_analysis_status=ANALYSIS_STATUS_READY,
        generalized_analysis_error=None,
    )
    return {
        "document_profile": document_profile,
        "credentials": credentials,
        "verification_plan": verification_plan,
        "verification_task_results": execution_artifacts["task_results"],
        "credential_bundles": execution_artifacts["credential_bundles"],
        "verification_execution_summary": execution_artifacts["execution_summary"],
        "credential_audits": credential_audits,
        "verification_summary": verification_summary,
    }


def mark_analysis_failure(session, error: Exception | str) -> None:
    error_message = str(error)
    LOGGER.warning("GENERALIZED_ANALYSIS_FAILED session_id=%s error=%s", session.id, error_message)
    persist_analysis_artifacts(
        session,
        generalized_analysis_status=ANALYSIS_STATUS_FAILED,
        generalized_analysis_error=error_message,
    )


def get_document_profile_for_session(session) -> DocumentProfile:
    persisted = _load_model(DocumentProfile, session.document_profile_payload)
    if persisted is not None:
        return persisted
    return build_document_profile(session.id, session.extraction_payload)


def get_credentials_for_session(session) -> SessionCredentialCollection:
    persisted = _load_model(SessionCredentialCollection, session.generalized_credentials_payload)
    if persisted is not None:
        return _sanitize_credential_collection(persisted)
    return _sanitize_credential_collection(build_credentials(session.id, session.extraction_payload))


def get_verification_plan_for_session(session) -> SessionVerificationPlan:
    credentials = get_credentials_for_session(session)
    persisted = _load_model(SessionVerificationPlan, session.verification_plan_payload)
    if persisted is not None:
        return _sanitize_verification_plan(persisted, credentials)
    return _sanitize_verification_plan(
        build_verification_plan(session.id, session.extraction_payload, credentials=credentials),
        credentials,
    )


def get_credential_audits_for_session(session) -> CredentialAuditCollection:
    credentials = get_credentials_for_session(session)
    persisted = _load_model(CredentialAuditCollection, session.credential_audits_payload)
    if persisted is not None:
        return _sanitize_credential_audits(persisted, credentials)

    verification_plan = build_verification_plan(
        session.id,
        session.extraction_payload,
        credentials=credentials,
    )
    bundles = get_credential_bundles_for_session(session)
    return _sanitize_credential_audits(
        assemble_credential_audits(
            session.id,
            session.extraction_payload,
            connector_payload=session.connector_payload,
            trust_outcome=session.trust_outcome,
            reason_codes=list(session.reason_codes or []),
            audit_timestamp=session.verified_at or session.updated_at or session.created_at,
            credentials=credentials,
            verification_plan=verification_plan,
            credential_bundles=bundles,
        ),
        credentials,
    )


def get_verification_summary_for_session(session) -> DocumentVerificationSummary:
    persisted = _load_model(DocumentVerificationSummary, session.verification_summary_payload)
    credentials = get_credentials_for_session(session)
    audits = get_credential_audits_for_session(session)
    if persisted is not None:
        if not session.generalized_credentials_payload and not session.credential_audits_payload:
            return persisted
        if persisted.total_credentials_found == len(credentials.credentials):
            return persisted
    return build_verification_summary(
        session.id,
        session.extraction_payload,
        credential_audits=audits,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        credentials=credentials,
    )


def get_analysis_status_for_session(session) -> SessionAnalysisStatus:
    credentials = get_credentials_for_session(session) if session.extraction_payload else SessionCredentialCollection(
        session_id=session.id,
        document_type="unknown",
        credentials=[],
    )
    verification_plan = (
        get_verification_plan_for_session(session)
        if session.extraction_payload or session.verification_plan_payload
        else SessionVerificationPlan(session_id=session.id, document_type="unknown", route_decisions=[], tasks=[])
    )
    audits = (
        get_credential_audits_for_session(session)
        if session.extraction_payload or session.credential_audits_payload
        else CredentialAuditCollection(session_id=session.id, document_type="unknown", audits=[])
    )
    return SessionAnalysisStatus(
        session_id=session.id,
        workflow_state=session.status,
        generalized_analysis_status=_infer_analysis_status(session),
        generalized_analysis_error=session.generalized_analysis_error,
        document_profile_available=bool(session.document_profile_payload) or bool(session.extraction_payload),
        credentials_available=bool(credentials.credentials),
        verification_plan_available=bool(verification_plan.tasks or verification_plan.route_decisions),
        credential_audits_available=bool(audits.audits),
        verification_summary_available=bool(session.verification_summary_payload) or bool(audits.audits),
    )


def _collect_detected_categories(credentials: SessionCredentialCollection) -> list[str]:
    categories = [
        credential.category
        for credential in credentials.credentials
        if credential.normalized_value and credential.category
    ]
    return sorted(dict.fromkeys(categories))


def _collect_extraction_methods(
    extraction_payload: dict[str, Any] | None,
    credentials: SessionCredentialCollection,
) -> list[str]:
    methods = [
        credential.extraction_method
        for credential in credentials.credentials
        if credential.extraction_method and credential.extraction_method != "unknown"
    ]
    enrichment_metadata = (extraction_payload or {}).get("enrichment_metadata") or {}
    if enrichment_metadata.get("pii_enrichment_used"):
        methods.append("nvidia_gliner_pii")
    if methods:
        return sorted(dict.fromkeys(methods))

    if not extraction_payload:
        return []
    if extraction_payload.get("used_ocr") or extraction_payload.get("ocr_used"):
        return ["ocr"]
    generalized_analysis = extraction_payload.get("generalized_analysis") or {}
    if generalized_analysis.get("generalized_credentials_payload") or extraction_payload.get("field_candidates"):
        return ["generalized_analysis"]
    if extraction_payload.get("field_details"):
        return ["structured_extraction"]
    return ["rule_based"]


def _infer_document_family(document_type: str, detected_categories: list[str]) -> str:
    normalized_document_type = document_type.lower()
    if any(
        token in normalized_document_type
        for token in ("academic", "transcript", "credential", "report_card", "marksheet", "mark_sheet", "grade_report")
    ):
        return "academic_document"
    if any(token in normalized_document_type for token in ("passport", "identity", "license", "licence")):
        return "identity_document"
    if any(token in normalized_document_type for token in ("financial", "bank", "tax")):
        return "financial_document"

    families: set[str] = set()

    category_set = set(detected_categories)
    if category_set & {"identity", "address", "passport", "license"}:
        families.add("identity_document")
    if category_set & {"academic", "certificate"}:
        families.add("academic_document")
    if category_set & {"financial", "tax"}:
        families.add("financial_document")

    if len(families) > 1:
        return "mixed_document"
    if families:
        return sorted(families)[0]
    if document_type != "unknown":
        return document_type
    return "unknown"


def _coerce_page_count(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def _infer_analysis_status(session) -> str:
    has_generalized_credentials = bool(get_credentials_for_session(session).credentials) if session.extraction_payload else False
    if session.generalized_analysis_status and (
        str(session.generalized_analysis_status) != ANALYSIS_STATUS_NOT_STARTED
        or any(
            (
                session.document_profile_payload,
                session.generalized_credentials_payload,
                session.verification_plan_payload,
                session.credential_audits_payload,
                session.verification_summary_payload,
            )
        )
        or not session.extraction_payload
    ):
        return str(session.generalized_analysis_status)
    if session.generalized_analysis_error:
        return ANALYSIS_STATUS_FAILED
    if session.verification_summary_payload:
        return ANALYSIS_STATUS_READY
    if session.credential_audits_payload:
        return ANALYSIS_STATUS_AUDITS_ASSEMBLED
    if session.verification_plan_payload:
        return ANALYSIS_STATUS_PLAN_BUILT
    if session.generalized_credentials_payload:
        return ANALYSIS_STATUS_CREDENTIALS_BUILT
    if session.document_profile_payload:
        return ANALYSIS_STATUS_PROFILED
    if has_generalized_credentials and (
        session.connector_payload is not None
        or session.trust_outcome is not None
        or bool(session.reason_codes)
    ):
        return ANALYSIS_STATUS_READY
    if has_generalized_credentials:
        return ANALYSIS_STATUS_PLAN_BUILT
    if session.extraction_payload:
        return ANALYSIS_STATUS_NOT_STARTED
    return ANALYSIS_STATUS_NOT_STARTED


def _sanitize_credential_collection(
    collection: SessionCredentialCollection,
) -> SessionCredentialCollection:
    sanitized_credentials = [
        credential
        for credential in collection.credentials
        if _has_usable_credential_content(credential)
    ]
    if len(sanitized_credentials) == len(collection.credentials):
        return collection
    return SessionCredentialCollection(
        session_id=collection.session_id,
        document_type=collection.document_type,
        credentials=sanitized_credentials,
    )


def _sanitize_verification_plan(
    plan: SessionVerificationPlan,
    credentials: SessionCredentialCollection,
) -> SessionVerificationPlan:
    valid_ids = {credential.credential_id for credential in credentials.credentials}
    if not valid_ids:
        return SessionVerificationPlan(
            session_id=plan.session_id,
            document_type=plan.document_type,
            route_decisions=[],
            tasks=[],
        )

    route_decisions = [
        decision
        for decision in plan.route_decisions
        if decision.credential_id in valid_ids
    ]
    tasks = [
        task
        for task in plan.tasks
        if task.credential_id in valid_ids
    ]
    if len(route_decisions) == len(plan.route_decisions) and len(tasks) == len(plan.tasks):
        return plan
    return SessionVerificationPlan(
        session_id=plan.session_id,
        document_type=plan.document_type,
        route_decisions=route_decisions,
        tasks=tasks,
    )


def _sanitize_credential_audits(
    audits: CredentialAuditCollection,
    credentials: SessionCredentialCollection,
) -> CredentialAuditCollection:
    valid_ids = {credential.credential_id for credential in credentials.credentials}
    if not valid_ids:
        return CredentialAuditCollection(
            session_id=audits.session_id,
            document_type=audits.document_type,
            audits=[],
        )

    sanitized_audits = [
        audit
        for audit in audits.audits
        if audit.credential_id in valid_ids
    ]
    if len(sanitized_audits) == len(audits.audits):
        return audits
    return CredentialAuditCollection(
        session_id=audits.session_id,
        document_type=audits.document_type,
        audits=sanitized_audits,
    )


def _has_usable_credential_content(credential) -> bool:
    return any(
        value not in (None, "")
        for value in (
            getattr(credential, "value", None),
            getattr(credential, "normalized_value", None),
            getattr(credential, "source_text", None),
        )
    )


def _load_model(model_cls, payload: Any):
    if payload in (None, ""):
        return None

    try:
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(payload)
        return model_cls.parse_obj(payload)
    except Exception:
        LOGGER.warning(
            "GENERALIZED_ARTIFACT_LOAD_FAILED model=%s",
            getattr(model_cls, "__name__", str(model_cls)),
            exc_info=True,
        )
        return None


def _dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    return value

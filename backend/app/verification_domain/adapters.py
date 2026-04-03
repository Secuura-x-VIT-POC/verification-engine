from __future__ import annotations

from datetime import datetime
from typing import Any

from ..verifier_execution.contracts import CredentialVerificationBundleCollection
from .contracts import (
    AUDIT_STATUS_MANUAL_REVIEW,
    AUDIT_STATUS_MISMATCH,
    AUDIT_STATUS_NOT_APPLICABLE,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_UNVERIFIED,
    AUDIT_STATUS_VERIFIED,
    OUTCOME_COLOR_AMBER,
    OUTCOME_COLOR_GREEN,
    OUTCOME_COLOR_NEUTRAL,
    OUTCOME_COLOR_RED,
    CredentialAudit,
    CredentialAuditCollection,
    DocumentVerificationSummary,
    EvidenceItem,
    ExtractedCredential,
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
    VerifierRouteDecision,
)
from .planner import build_extracted_credentials
from .routing import RuleBasedVerifierRouter, VerifierRouter


def build_session_credentials(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
) -> SessionCredentialCollection:
    return SessionCredentialCollection(
        session_id=session_id,
        document_type=_resolve_document_type(extraction_payload),
        credentials=build_extracted_credentials(extraction_payload),
    )


def build_session_verification_plan(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
    *,
    router: VerifierRouter | None = None,
    credentials: SessionCredentialCollection | None = None,
) -> SessionVerificationPlan:
    active_router = router or RuleBasedVerifierRouter()
    credential_collection = credentials or build_session_credentials(session_id, extraction_payload)
    route_decisions = [active_router.route(credential) for credential in credential_collection.credentials]
    route_map = {decision.credential_id: decision for decision in route_decisions}
    tasks = [
        _build_task(credential, route_map[credential.credential_id])
        for credential in credential_collection.credentials
        if credential.requires_verification
    ]
    return SessionVerificationPlan(
        session_id=session_id,
        document_type=credential_collection.document_type,
        route_decisions=route_decisions,
        tasks=tasks,
    )


def build_session_credential_audits(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
    *,
    connector_payload: Any = None,
    trust_outcome: str | None = None,
    reason_codes: list[str] | None = None,
    audit_timestamp: datetime | None = None,
    router: VerifierRouter | None = None,
    credentials: SessionCredentialCollection | None = None,
    verification_plan: SessionVerificationPlan | None = None,
    credential_bundles: CredentialVerificationBundleCollection | None = None,
) -> CredentialAuditCollection:
    active_router = router or RuleBasedVerifierRouter()
    credential_collection = credentials or build_session_credentials(session_id, extraction_payload)
    plan = verification_plan or build_session_verification_plan(
        session_id,
        extraction_payload,
        router=active_router,
        credentials=credential_collection,
    )
    route_map = {decision.credential_id: decision for decision in plan.route_decisions}
    connectors = _normalize_connectors(connector_payload)
    timestamp = audit_timestamp
    resolved_reason_codes = list(reason_codes or [])
    bundle_map = {
        bundle.credential_id: bundle
        for bundle in (credential_bundles.bundles if credential_bundles is not None else [])
    }

    audits = [
        (
            _build_audit_from_bundle(
                credential=credential,
                decision=route_map[credential.credential_id],
                bundle=bundle_map[credential.credential_id],
                connectors=connectors,
                timestamp=timestamp,
                overall_outcome=trust_outcome,
                overall_reason_codes=resolved_reason_codes,
            )
            if credential.credential_id in bundle_map
            else _build_audit(
                credential=credential,
                decision=route_map[credential.credential_id],
                connectors=connectors,
                timestamp=timestamp,
                overall_outcome=trust_outcome,
                overall_reason_codes=resolved_reason_codes,
            )
        )
        for credential in credential_collection.credentials
    ]

    return CredentialAuditCollection(
        session_id=session_id,
        document_type=credential_collection.document_type,
        audits=audits,
    )


def _build_audit_from_bundle(
    *,
    credential: ExtractedCredential,
    decision: VerifierRouteDecision,
    bundle,
    connectors: list[dict[str, Any]],
    timestamp: datetime | None,
    overall_outcome: str | None,
    overall_reason_codes: list[str],
) -> CredentialAudit:
    best_result = bundle.best_result
    evidence = _build_base_evidence(credential, connectors, overall_outcome, overall_reason_codes)
    evidence.extend(_build_task_result_evidence(bundle))

    return CredentialAudit(
        credential_id=credential.credential_id,
        label=bundle.label or credential.label,
        document_value=credential.value,
        normalized_value=credential.normalized_value,
        verifier_label=(
            best_result.verifier_label
            if best_result is not None
            else decision.selected_verifier_label
        ),
        audit_status=bundle.final_audit_status,
        outcome_color=bundle.final_outcome_color,
        explanation=bundle.explanation,
        reason_codes=list(bundle.reason_codes or []),
        matched_fields=(dict(best_result.matched_fields) if best_result is not None else {}),
        mismatched_fields=(dict(best_result.mismatched_fields) if best_result is not None else {}),
        missing_fields=(
            list(best_result.missing_fields)
            if best_result is not None
            else ([credential.label] if credential.requires_verification else [])
        ),
        evidence=evidence,
        timestamp=(
            best_result.executed_at
            if best_result is not None and best_result.executed_at is not None
            else timestamp
        ),
    )


def build_session_verification_summary(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
    *,
    credential_audits: CredentialAuditCollection,
    trust_outcome: str | None = None,
    reason_codes: list[str] | None = None,
    credentials: SessionCredentialCollection | None = None,
) -> DocumentVerificationSummary:
    credential_collection = credentials or build_session_credentials(session_id, extraction_payload)

    green_count = 0
    amber_count = 0
    red_count = 0
    manual_review_count = 0
    total_credentials_verified = 0

    for audit in credential_audits.audits:
        if audit.audit_status == AUDIT_STATUS_NOT_APPLICABLE:
            continue
        if audit.audit_status == AUDIT_STATUS_MANUAL_REVIEW:
            manual_review_count += 1
            amber_count += 1
            continue
        if audit.audit_status == AUDIT_STATUS_VERIFIED:
            green_count += 1
            total_credentials_verified += 1
            continue
        if audit.audit_status == AUDIT_STATUS_MISMATCH:
            red_count += 1
            total_credentials_verified += 1
            continue
        if audit.audit_status == AUDIT_STATUS_PARTIAL:
            amber_count += 1
            total_credentials_verified += 1
            continue
        if audit.audit_status == AUDIT_STATUS_UNVERIFIED:
            amber_count += 1

    return DocumentVerificationSummary(
        session_id=session_id,
        document_type=credential_collection.document_type,
        total_credentials_found=len(credential_collection.credentials),
        total_credentials_verified=total_credentials_verified,
        green_count=green_count,
        amber_count=amber_count,
        red_count=red_count,
        manual_review_count=manual_review_count,
        overall_outcome=trust_outcome,
        overall_reason_codes=list(reason_codes or []),
    )


def adapt_session_to_credentials(session) -> SessionCredentialCollection:
    return build_session_credentials(session.id, session.extraction_payload)


def adapt_session_to_verification_plan(
    session,
    *,
    router: VerifierRouter | None = None,
) -> SessionVerificationPlan:
    return build_session_verification_plan(
        session.id,
        session.extraction_payload,
        router=router,
    )


def adapt_session_to_credential_audits(
    session,
    *,
    router: VerifierRouter | None = None,
    audit_timestamp: datetime | None = None,
) -> CredentialAuditCollection:
    return build_session_credential_audits(
        session.id,
        session.extraction_payload,
        connector_payload=session.connector_payload,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        audit_timestamp=audit_timestamp or session.verified_at or session.updated_at or session.created_at,
        router=router,
    )


def adapt_session_to_verification_summary(
    session,
    *,
    router: VerifierRouter | None = None,
    audit_timestamp: datetime | None = None,
) -> DocumentVerificationSummary:
    credentials = build_session_credentials(session.id, session.extraction_payload)
    audits = build_session_credential_audits(
        session.id,
        session.extraction_payload,
        connector_payload=session.connector_payload,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        audit_timestamp=audit_timestamp or session.verified_at or session.updated_at or session.created_at,
        router=router,
        credentials=credentials,
    )
    return build_session_verification_summary(
        session.id,
        session.extraction_payload,
        credential_audits=audits,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        credentials=credentials,
    )


def _build_task(credential: ExtractedCredential, decision: VerifierRouteDecision) -> VerificationTask:
    status = "MANUAL_REVIEW" if decision.manual_review_recommended else "PLANNED"
    reason_codes = [f"CATEGORY_{credential.category.upper()}"]
    if decision.manual_review_recommended:
        reason_codes.append("MANUAL_REVIEW_RECOMMENDED")
    else:
        reason_codes.append("AUTO_ROUTED")

    return VerificationTask(
        task_id=f"verify-{credential.credential_id}",
        credential_id=credential.credential_id,
        verifier_key=decision.selected_verifier_key,
        verifier_label=decision.selected_verifier_label,
        verification_type=credential.category,
        required=credential.requires_verification,
        status=status,
        reason_codes=reason_codes,
        input_payload={
            "credential_id": credential.credential_id,
            "label": credential.label,
            "category": credential.category,
            "value": credential.value,
            "normalized_value": credential.normalized_value,
            "page": credential.page,
            "is_pii": credential.is_pii,
        },
    )


def _build_audit(
    *,
    credential: ExtractedCredential,
    decision: VerifierRouteDecision,
    connectors: list[dict[str, Any]],
    timestamp: datetime | None,
    overall_outcome: str | None,
    overall_reason_codes: list[str],
) -> CredentialAudit:
    evidence = _build_base_evidence(credential, connectors, overall_outcome, overall_reason_codes)
    claim_evidence = _find_claim_evidence(connectors, credential)
    missing_fields: list[str] = []

    if decision.selected_verifier_key == "not_required":
        return CredentialAudit(
            credential_id=credential.credential_id,
            label=credential.label,
            document_value=credential.value,
            normalized_value=credential.normalized_value,
            verifier_label=decision.selected_verifier_label,
            audit_status=AUDIT_STATUS_NOT_APPLICABLE,
            outcome_color=OUTCOME_COLOR_NEUTRAL,
            explanation=decision.route_reason,
            reason_codes=["VERIFICATION_NOT_APPLICABLE"],
            evidence=evidence,
            timestamp=timestamp,
        )

    if claim_evidence["mismatched_fields"]:
        connector = claim_evidence["connector"]
        return CredentialAudit(
            credential_id=credential.credential_id,
            label=credential.label,
            document_value=credential.value,
            normalized_value=credential.normalized_value,
            verifier_label=decision.selected_verifier_label,
            audit_status=AUDIT_STATUS_MISMATCH,
            outcome_color=OUTCOME_COLOR_RED,
            explanation=f"Current connector evidence indicates a mismatch for this field via '{connector.get('connector_id', 'connector')}'.",
            reason_codes=_dedupe_reason_codes(list(connector.get("reason_codes") or ["CONNECTOR_MISMATCH"])),
            matched_fields=claim_evidence["matched_fields"],
            mismatched_fields=claim_evidence["mismatched_fields"],
            evidence=evidence,
            timestamp=timestamp,
        )

    if claim_evidence["matched_fields"]:
        connector = claim_evidence["connector"]
        return CredentialAudit(
            credential_id=credential.credential_id,
            label=credential.label,
            document_value=credential.value,
            normalized_value=credential.normalized_value,
            verifier_label=decision.selected_verifier_label,
            audit_status=AUDIT_STATUS_VERIFIED,
            outcome_color=OUTCOME_COLOR_GREEN,
            explanation=f"Current connector evidence matched this field via '{connector.get('connector_id', 'connector')}'.",
            reason_codes=_dedupe_reason_codes(list(connector.get("reason_codes") or ["CONNECTOR_VERIFIED"])),
            matched_fields=claim_evidence["matched_fields"],
            evidence=evidence,
            timestamp=timestamp,
        )

    if decision.manual_review_recommended:
        missing_fields.append(credential.label)
        return CredentialAudit(
            credential_id=credential.credential_id,
            label=credential.label,
            document_value=credential.value,
            normalized_value=credential.normalized_value,
            verifier_label=decision.selected_verifier_label,
            audit_status=AUDIT_STATUS_MANUAL_REVIEW,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation="This field has no deterministic external verifier route yet and should be reviewed manually.",
            reason_codes=["MANUAL_REVIEW_RECOMMENDED"],
            missing_fields=missing_fields,
            evidence=evidence,
            timestamp=timestamp,
        )

    if connectors:
        missing_fields.append(credential.label)
        return CredentialAudit(
            credential_id=credential.credential_id,
            label=credential.label,
            document_value=credential.value,
            normalized_value=credential.normalized_value,
            verifier_label=decision.selected_verifier_label,
            audit_status=AUDIT_STATUS_PARTIAL,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation="Connector activity exists for this session, but there is not enough field-level evidence to mark this credential as verified.",
            reason_codes=_resolve_partial_reason_codes(connectors, overall_reason_codes),
            missing_fields=missing_fields,
            evidence=evidence,
            timestamp=timestamp,
        )

    missing_fields.append(credential.label)
    return CredentialAudit(
        credential_id=credential.credential_id,
        label=credential.label,
        document_value=credential.value,
        normalized_value=credential.normalized_value,
        verifier_label=decision.selected_verifier_label,
        audit_status=AUDIT_STATUS_UNVERIFIED,
        outcome_color=OUTCOME_COLOR_AMBER,
        explanation="Verification is planned for this field, but the current session has no connector evidence yet.",
        reason_codes=["NO_CONNECTOR_EVIDENCE"],
        missing_fields=missing_fields,
        evidence=evidence,
        timestamp=timestamp,
    )


def _build_base_evidence(
    credential: ExtractedCredential,
    connectors: list[dict[str, Any]],
    overall_outcome: str | None,
    overall_reason_codes: list[str],
) -> list[EvidenceItem]:
    evidence = [
        EvidenceItem(
            evidence_type="document_extraction",
            source="session.extraction_payload",
            detail={
                "page": credential.page,
                "bounding_box": _maybe_dump_model(credential.bounding_box),
                "confidence": credential.confidence,
                "source_text": credential.source_text,
            },
        )
    ]

    for connector in connectors:
        evidence.append(
            EvidenceItem(
                evidence_type="connector_response",
                source=str(connector.get("connector_id") or "connector"),
                detail={
                    "status": connector.get("status"),
                    "reason_codes": list(connector.get("reason_codes") or []),
                    "matched_claims": dict(connector.get("matched_claims") or {}),
                    "mismatched_claims": dict(connector.get("mismatched_claims") or {}),
                },
            )
        )

    if overall_outcome or overall_reason_codes:
        evidence.append(
            EvidenceItem(
                evidence_type="trust_result",
                source="session.trust_outcome",
                detail={
                    "outcome": overall_outcome,
                    "reason_codes": overall_reason_codes,
                },
            )
        )

    return evidence


def _build_task_result_evidence(bundle) -> list[EvidenceItem]:
    evidence = []
    for result in list(bundle.all_results or []):
        evidence.append(
            EvidenceItem(
                evidence_type="verification_task_result",
                source=result.verifier_key,
                detail={
                    "task_id": result.task_id,
                    "task_status": result.task_status,
                    "audit_status": result.audit_status,
                    "outcome_color": result.outcome_color,
                    "reason_codes": list(result.reason_codes or []),
                    "matched_fields": dict(result.matched_fields or {}),
                    "mismatched_fields": dict(result.mismatched_fields or {}),
                    "missing_fields": list(result.missing_fields or []),
                    "raw_result_summary": dict(result.raw_result_summary or {}),
                    "confidence": result.confidence,
                    "latency_ms": result.latency_ms,
                    "manual_review_recommended": result.manual_review_recommended,
                },
            )
        )
    return evidence


def _find_claim_evidence(connectors: list[dict[str, Any]], credential: ExtractedCredential) -> dict[str, Any]:
    claim_keys = _claim_key_candidates(credential)
    for connector in connectors:
        matched_claims = dict(connector.get("matched_claims") or {})
        mismatched_claims = dict(connector.get("mismatched_claims") or {})

        matched_fields = {
            key: value
            for key, value in matched_claims.items()
            if _canonical_claim_key(key) in claim_keys
        }
        mismatched_fields = {
            key: value
            for key, value in mismatched_claims.items()
            if _canonical_claim_key(key) in claim_keys
        }
        if matched_fields or mismatched_fields:
            return {
                "connector": connector,
                "matched_fields": matched_fields,
                "mismatched_fields": mismatched_fields,
            }

    return {
        "connector": {},
        "matched_fields": {},
        "mismatched_fields": {},
    }


def _claim_key_candidates(credential: ExtractedCredential) -> set[str]:
    keys = {_canonical_claim_key(credential.label), _canonical_claim_key(credential.credential_id)}
    label = credential.label.lower()

    if "name" in label:
        keys.update({"name", "candidate_name"})
    if "institution" in label or "university" in label or "college" in label:
        keys.update({"institution", "issuer"})
    if "credential" in label or "degree" in label or "certificate" in label:
        keys.update({"credential", "degree", "certificate"})
    if "id" in label or "number" in label:
        keys.update({"id", "document_id", "identifier"})
    if "address" in label:
        keys.update({"address", "postal_address"})
    return {key for key in keys if key}


def _canonical_claim_key(value: str) -> str:
    normalized = value.lower().replace("-", "_")
    normalized = "".join(character for character in normalized if character.isalnum() or character == "_")
    if normalized.startswith("credential") or normalized.startswith("degree"):
        return "degree"
    if normalized.endswith("_id") or normalized in {"id", "documentid", "document_id", "identifier"}:
        return "document_id"
    if normalized in {"candidate_name", "fullname", "full_name"}:
        return "name"
    return normalized


def _normalize_connectors(raw_connectors: Any) -> list[dict[str, Any]]:
    if raw_connectors is None:
        return []
    if isinstance(raw_connectors, dict):
        connectors = [raw_connectors]
    elif isinstance(raw_connectors, list):
        connectors = raw_connectors
    else:
        return []

    normalized = []
    for connector in connectors:
        if not isinstance(connector, dict):
            continue
        normalized.append(
            {
                "connector_id": connector.get("connector_id"),
                "status": str(connector.get("status") or "").upper(),
                "reason_codes": list(connector.get("reason_codes") or []),
                "matched_claims": dict(connector.get("matched_claims") or {}),
                "mismatched_claims": dict(connector.get("mismatched_claims") or {}),
                "assurance_class": connector.get("assurance_class"),
                "source_timestamp": connector.get("source_timestamp"),
            }
        )
    return normalized


def _resolve_partial_reason_codes(
    connectors: list[dict[str, Any]],
    overall_reason_codes: list[str],
) -> list[str]:
    connector_reason_codes = []
    for connector in connectors:
        connector_reason_codes.extend(list(connector.get("reason_codes") or []))

    if overall_reason_codes:
        connector_reason_codes.extend(overall_reason_codes)
    if not connector_reason_codes:
        connector_reason_codes.append("FIELD_LEVEL_EVIDENCE_INSUFFICIENT")
    return _dedupe_reason_codes(connector_reason_codes)


def _dedupe_reason_codes(reason_codes: list[str]) -> list[str]:
    return list(dict.fromkeys(code for code in reason_codes if code))


def _resolve_document_type(extraction_payload: dict[str, Any] | None) -> str:
    if not extraction_payload:
        return "unknown"
    return str(extraction_payload.get("document_type") or "unknown")


def _maybe_dump_model(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return value

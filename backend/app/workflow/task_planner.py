from __future__ import annotations

from typing import Any

from ..verification_domain.contracts import ExtractedCredential, VerificationTask
from ..verifier_execution.registry import VerifierRegistry, build_default_verifier_registry


REQUIRED_FIELDS_BY_CLAIM_TYPE = {
    "academic_degree": ["holder_name", "institution", "degree", "issue_date"],
    "identity": ["holder_name", "identity_number"],
    "certificate": ["holder_name", "issuer", "certificate"],
    "address": ["address"],
    "passport": ["holder_name", "passport_number"],
    "license": ["holder_name", "license_number"],
    "financial": ["holder_name", "account_or_reference"],
    "tax": ["holder_name", "tax_identifier"],
}

HIGH_ASSURANCE_CLAIM_TYPES = {
    "academic_degree",
    "identity",
    "passport",
    "license",
    "financial",
    "tax",
}


def build_verification_tasks(
    credentials: list[ExtractedCredential],
    *,
    registry: VerifierRegistry | None = None,
    context: dict[str, Any] | None = None,
) -> list[VerificationTask]:
    active_registry = registry or build_default_verifier_registry()
    tasks: list[VerificationTask] = []

    for credential in credentials:
        if not credential.requires_verification:
            continue

        claim_type = infer_claim_type(credential, context=context)
        required_fields = infer_required_fields(claim_type, credential)
        assurance_required = infer_assurance_required(claim_type, credential)
        provider_candidates = active_registry.get_provider_candidates(
            claim_type=claim_type,
            required_fields=required_fields,
            assurance_required=assurance_required,
            context={
                **dict(context or {}),
                "category": credential.category,
                "document_type": (context or {}).get("document_type"),
            },
        )
        primary_candidate = provider_candidates[0]
        preferred_provider_key = _preferred_provider_for_claim(
            claim_type=claim_type,
            verifier_key=primary_candidate.verifier_key,
            assurance_required=assurance_required,
        )
        fallback_reason = primary_candidate.fallback_reason
        if (
            preferred_provider_key == "entra_verified_id"
            and primary_candidate.provider_key == "local_mock"
        ):
            fallback_reason = "ENTRA_NOT_CONFIGURED"
        verifier = active_registry.get(primary_candidate.verifier_key)

        reason_codes = _dedupe(
            [
                f"CLAIM_TYPE_{_reason_token(claim_type)}",
                f"CATEGORY_{_reason_token(credential.category)}",
                "CAPABILITY_ROUTED",
                *credential.source_candidate_ids,
                *[
                    code
                    for candidate in provider_candidates
                    for code in candidate.reason_codes
                ],
            ]
        )
        if fallback_reason:
            reason_codes.append(fallback_reason)

        task = VerificationTask(
            task_id=f"verify-{credential.credential_id}",
            credential_id=credential.credential_id,
            verifier_key=primary_candidate.verifier_key,
            verifier_label=getattr(verifier, "verifier_label", primary_candidate.verifier_key.replace("_", " ").title()),
            verification_type=credential.category or claim_type,
            required=credential.requires_verification,
            status="MANUAL_REVIEW" if primary_candidate.verifier_key == "manual_review" else "PLANNED",
            claim_type=claim_type,
            provider_candidates=[candidate.provider_key for candidate in provider_candidates],
            required_fields=required_fields,
            assurance_required=assurance_required,
            selected_provider=primary_candidate.provider_key,
            planned_provider_key=primary_candidate.provider_key,
            preferred_provider_key=preferred_provider_key,
            reason_codes=reason_codes,
            input_payload={
                "credential_id": credential.credential_id,
                "label": credential.label,
                "category": credential.category,
                "value": credential.value,
                "normalized_value": credential.normalized_value,
                "page": credential.page,
                "is_pii": credential.is_pii,
                "claim_type": claim_type,
                "required_fields": required_fields,
                "assurance_required": assurance_required,
                "provider_candidates": [candidate.provider_key for candidate in provider_candidates],
                "preferred_provider_key": preferred_provider_key,
                "planned_provider_key": primary_candidate.provider_key,
                "planned_provider_label": primary_candidate.provider_label,
                "planned_execution_mode": _planned_execution_mode(primary_candidate.provider_key),
                "fallback_reason": fallback_reason,
            },
        )
        tasks.append(task)

    return tasks


def infer_claim_type(credential: ExtractedCredential, *, context: dict[str, Any] | None = None) -> str:
    category = str(credential.category or "").strip().lower()
    label = str(credential.label or "").strip().lower()
    document_type = str((context or {}).get("document_type") or "").strip().lower()

    if category == "academic" or "academic" in document_type:
        return "academic_degree"
    if category in {"identity", "address", "passport", "license", "financial", "tax", "certificate"}:
        return category
    if "degree" in label or "transcript" in label or "institution" in label or "university" in label:
        return "academic_degree"
    if "passport" in label:
        return "passport"
    if "license" in label:
        return "license"
    if "address" in label:
        return "address"
    if "certificate" in label:
        return "certificate"
    if "tax" in label:
        return "tax"
    if "account" in label or "financial" in label:
        return "financial"
    if "name" in label or "identity" in label:
        return "identity"
    return category or "generic_claim"


def infer_required_fields(claim_type: str, credential: ExtractedCredential) -> list[str]:
    required_fields = list(REQUIRED_FIELDS_BY_CLAIM_TYPE.get(claim_type, []))
    if required_fields:
        return required_fields
    label = str(credential.label or credential.credential_id or "value").strip().lower().replace(" ", "_")
    return [label or "value"]


def infer_assurance_required(claim_type: str, credential: ExtractedCredential) -> str:
    if claim_type in HIGH_ASSURANCE_CLAIM_TYPES or credential.verification_recommended:
        return "HIGH"
    if credential.requires_verification:
        return "MEDIUM"
    return "LOW"


def _preferred_provider_for_claim(
    *,
    claim_type: str,
    verifier_key: str,
    assurance_required: str,
) -> str | None:
    if verifier_key in {"identity_db", "academic_registry", "certificate_registry"}:
        return "entra_verified_id"
    if str(assurance_required or "").upper() == "HIGH":
        return "entra_verified_id"
    if claim_type in {"identity", "academic_degree", "certificate"}:
        return "entra_verified_id"
    return None


def _planned_execution_mode(provider_key: str) -> str:
    if provider_key == "manual_review":
        return "MANUAL_REVIEW"
    if provider_key == "local_mock":
        return "LOCAL_MOCK"
    if provider_key == "entra_verified_id":
        return "LIVE_PROVIDER"
    return "PROVIDER"


def _dedupe(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]


def _reason_token(value: Any) -> str:
    token = "".join(character if character.isalnum() else "_" for character in str(value or "").upper())
    return token.strip("_") or "UNKNOWN"

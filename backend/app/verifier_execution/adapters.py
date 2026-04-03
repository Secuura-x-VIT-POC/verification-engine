from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..verification_domain.contracts import ExtractedCredential, VerificationTask


PASSPORT_PATTERN = re.compile(r"^[A-Z][0-9]{6,8}$")
LICENSE_PATTERN = re.compile(r"^[A-Z0-9-]{6,18}$")
IDENTITY_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,}$")
ADDRESS_HINT_PATTERN = re.compile(r"\d+")
TAX_PATTERN = re.compile(r"^[A-Z0-9-]{6,20}$")
FINANCIAL_PATTERN = re.compile(r"^[A-Z0-9-]{6,24}$")


@dataclass(frozen=True)
class VerificationExecutionContext:
    session_id: str
    document_type: str
    extraction_payload: dict[str, Any] | None
    connector_payload: list[dict[str, Any]]
    trust_outcome: str | None
    reason_codes: list[str]
    provider_runtime: Any | None = None


def build_execution_context(
    *,
    session_id: str,
    document_type: str,
    extraction_payload: dict[str, Any] | None,
    connector_payload: Any,
    trust_outcome: str | None,
    reason_codes: list[str] | None,
    provider_runtime: Any = None,
) -> VerificationExecutionContext:
    return VerificationExecutionContext(
        session_id=session_id,
        document_type=document_type,
        extraction_payload=extraction_payload,
        connector_payload=normalize_connector_payload(connector_payload),
        trust_outcome=trust_outcome,
        reason_codes=list(reason_codes or []),
        provider_runtime=provider_runtime,
    )


def normalize_connector_payload(raw_connectors: Any) -> list[dict[str, Any]]:
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
                "assurance_class": str(connector.get("assurance_class") or "").upper(),
            }
        )
    return normalized


def find_connector_claim_evidence(
    connectors: list[dict[str, Any]],
    credential: ExtractedCredential,
) -> dict[str, Any]:
    claim_keys = claim_key_candidates(credential)
    for connector in connectors:
        matched_claims = dict(connector.get("matched_claims") or {})
        mismatched_claims = dict(connector.get("mismatched_claims") or {})
        matched_fields = {
            key: value
            for key, value in matched_claims.items()
            if canonical_claim_key(key) in claim_keys
        }
        mismatched_fields = {
            key: value
            for key, value in mismatched_claims.items()
            if canonical_claim_key(key) in claim_keys
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


def claim_key_candidates(credential: ExtractedCredential) -> set[str]:
    keys = {canonical_claim_key(credential.label), canonical_claim_key(credential.credential_id)}
    label = credential.label.lower()
    category = credential.category.lower()

    if category == "identity" or "name" in label:
        keys.update({"name", "candidate_name", "full_name"})
    if "institution" in label or "issuer" in label or "university" in label or "college" in label:
        keys.update({"institution", "issuer"})
    if "credential" in label or "degree" in label or "certificate" in label:
        keys.update({"degree", "credential", "certificate"})
    if "address" in label or category == "address":
        keys.update({"address", "postal_address"})
    if "passport" in label or category == "passport":
        keys.update({"passport_number", "passport"})
    if "license" in label or category == "license":
        keys.update({"license_number", "license"})
    if (
        category in {"financial", "tax"}
        or "identifier" in label
        or label == "id"
        or label.endswith(" id")
        or "document id" in label
    ):
        keys.update({"document_id", "identifier", "id"})
    if "registration" in label or "roll number" in label or "roll no" in label:
        keys.update({"document_id", "registration_number", "roll_number", "id"})

    return {key for key in keys if key}


def canonical_claim_key(value: str) -> str:
    normalized = value.lower().replace("-", "_")
    normalized = "".join(character for character in normalized if character.isalnum() or character == "_")
    if normalized.startswith("credential") or normalized.startswith("degree"):
        return "degree"
    if normalized in {"candidate_name", "full_name", "fullname"}:
        return "name"
    if normalized.endswith("_id") or normalized in {"documentid", "document_id", "identifier", "id"}:
        return "document_id"
    if normalized in {"passportnumber", "passport_number"}:
        return "passport_number"
    if normalized in {"licensenumber", "license_number"}:
        return "license_number"
    return normalized


def has_grounding(credential: ExtractedCredential) -> bool:
    if credential.bounding_box is None:
        return False
    return any(
        getattr(credential.bounding_box, attr) is not None
        for attr in ("x0", "y0", "x1", "y1")
    )


def document_confidence(credential: ExtractedCredential) -> float:
    if credential.confidence is None:
        return 0.0
    return float(credential.confidence)


def summarize_result(
    *,
    execution_mode: str,
    credential: ExtractedCredential,
    task: VerificationTask,
    connector: dict[str, Any] | None = None,
    matched_fields: dict[str, Any] | None = None,
    mismatched_fields: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    truth = task_execution_truth(task)
    summary = {
        "execution_mode": execution_mode,
        "credential_label": credential.label,
        "verification_type": task.verification_type,
        "document_confidence": credential.confidence,
        "has_grounding": has_grounding(credential),
        **truth,
    }
    if connector:
        summary["connector_id"] = connector.get("connector_id")
        summary["connector_status"] = connector.get("status")
    if matched_fields:
        summary["matched_field_count"] = len(matched_fields)
    if mismatched_fields:
        summary["mismatched_field_count"] = len(mismatched_fields)
    if extra:
        summary.update(extra)
    return summary


def task_execution_truth(task: VerificationTask) -> dict[str, Any]:
    payload = dict(task.input_payload or {}) if isinstance(task.input_payload, dict) else {}
    return {
        "preferred_provider_key": payload.get("preferred_provider_key"),
        "preferred_provider_label": payload.get("preferred_provider_label"),
        "planned_provider_key": payload.get("planned_provider_key"),
        "planned_provider_label": payload.get("planned_provider_label"),
        "planned_execution_mode": payload.get("planned_execution_mode"),
        "planned_is_live_result": bool(payload.get("planned_is_live_result")),
        "planned_is_mock_result": bool(payload.get("planned_is_mock_result")),
        "planned_is_demo_result": bool(payload.get("planned_is_demo_result")),
        "fallback_reason": payload.get("fallback_reason"),
    }


def looks_like_passport(value: str | None) -> bool:
    return bool(value and PASSPORT_PATTERN.match(value))


def looks_like_license(value: str | None) -> bool:
    return bool(value and LICENSE_PATTERN.match(value))


def looks_like_name(value: str | None) -> bool:
    return bool(value and IDENTITY_NAME_PATTERN.match(value) and len(value.split()) >= 2)


def looks_like_address(value: str | None) -> bool:
    if not value:
        return False
    return len(value) >= 10 and bool(ADDRESS_HINT_PATTERN.search(value))


def looks_like_tax_identifier(value: str | None) -> bool:
    return bool(value and TAX_PATTERN.match(value))


def looks_like_financial_identifier(value: str | None) -> bool:
    return bool(value and FINANCIAL_PATTERN.match(value))


def resolve_document_institution(extraction_payload: dict[str, Any] | None) -> str:
    fields = dict((extraction_payload or {}).get("fields") or {})
    institution = fields.get("institution")
    if isinstance(institution, dict):
        institution = institution.get("value")
    return str(institution or "")

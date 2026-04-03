from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from ..base import VerifierProvider
from ..contracts import (
    PROVIDER_OPERATING_MODE_DEMO_MOCK,
    PROVIDER_TECHNICAL_STATUS_SUCCESS,
    ProviderCapability,
    ProviderRequest,
    ProviderResponse,
    REQUEST_MODE_LOCAL_FIXTURE,
)
from ..normalizers import as_dict, as_float, as_string_list
from ..policies import ProviderConfig


LOGGER = logging.getLogger(__name__)
LOCAL_VERIFICATION_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "local_verification_records.json"
)

SUPPORTED_VERIFIER_KEYS = [
    "identity_db",
    "address_check",
    "passport_db",
    "academic_registry",
    "certificate_registry",
    "license_registry",
    "financial_registry",
    "tax_authority",
]

SUPPORTED_CATEGORIES = [
    "identity",
    "address",
    "passport",
    "academic",
    "certificate",
    "license",
    "financial",
    "tax",
]


class LocalMockProvider(VerifierProvider):
    provider_key = "local_mock"
    provider_label = "Local Mock Provider"

    def __init__(self, config: ProviderConfig):
        self.config = config

    def get_capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            provider_key=self.provider_key,
            provider_label=self.provider_label,
            supported_verifier_keys=SUPPORTED_VERIFIER_KEYS,
            supported_categories=SUPPORTED_CATEGORIES,
            supports_batch=False,
            supports_partial_match=True,
            supports_document_upload=False,
            supports_field_lookup=True,
            requires_credentials=False,
            default_timeout_ms=self.config.timeout_ms,
            enabled=self.config.enabled,
            operating_mode=self.config.operating_mode,
            execution_environment_label=self.config.execution_environment_label,
            demo_supported=True,
        )

    def prepare_request(
        self,
        *,
        session_id: str,
        task_id: str,
        verifier_key: str,
        input_payload: dict,
        redacted_payload: dict,
        timeout_ms: int,
        metadata: dict | None = None,
    ) -> ProviderRequest:
        return ProviderRequest(
            request_id=f"provider-{uuid.uuid4()}",
            session_id=session_id,
            task_id=task_id,
            verifier_key=verifier_key,
            provider_key=self.provider_key,
            input_payload=dict(input_payload or {}),
            redacted_payload=dict(redacted_payload or {}),
            request_mode=REQUEST_MODE_LOCAL_FIXTURE,
            timeout_ms=timeout_ms,
            metadata=dict(metadata or {}),
        )

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        fixture = as_dict(request.input_payload.get("provider_fixture"))
        if not fixture:
            fixture = _build_local_record_fixture(
                request=request,
                fixture_path=LOCAL_VERIFICATION_FIXTURE_PATH,
                default_operating_mode=self.config.operating_mode,
                default_environment_label=self.config.execution_environment_label,
            )
        technical_status = str(fixture.get("technical_status") or PROVIDER_TECHNICAL_STATUS_SUCCESS)
        summary = as_dict(fixture.get("response_summary"))
        if not summary:
            preferred_provider_key = str(request.input_payload.get("preferred_provider_key") or "")
            preferred_provider_label = str(request.input_payload.get("preferred_provider_label") or "")
            operating_mode = str(request.metadata.get("provider_operating_mode") or self.config.operating_mode)
            note = "No live external evidence is configured in this environment."
            if operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK and preferred_provider_key == "entra_verified_id":
                note = (
                    f"{preferred_provider_label or 'Microsoft Entra Verified ID'} remains the primary trust rail, "
                    "but the bounded local fallback path was used for this seeded demo case."
                )
            elif preferred_provider_key == "entra_verified_id":
                note = (
                    f"{preferred_provider_label or 'Microsoft Entra Verified ID'} is not configured in this "
                    "environment, so the bounded local mock path was used."
                )
            summary = {
                "mode": "local_fixture",
                "note": note,
                "operating_mode": operating_mode,
                "execution_environment_label": (
                    request.metadata.get("execution_environment_label")
                    or self.config.execution_environment_label
                ),
                "demo_profile_key": request.metadata.get("demo_profile_key"),
                "mock_mode": operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK,
                "live_execution": False,
                "local_store_path": str(LOCAL_VERIFICATION_FIXTURE_PATH),
            }
        raw_missing_fields = fixture.get("missing_fields")
        missing_fields = as_string_list(raw_missing_fields)
        if raw_missing_fields is None and not missing_fields:
            label = str(request.input_payload.get("label") or request.verifier_key)
            missing_fields = [label]

        return self.normalize_response(
            request=request,
            payload={
                "technical_status": technical_status,
                "response_summary": summary,
                "matched_fields": fixture.get("matched_fields"),
                "mismatched_fields": fixture.get("mismatched_fields"),
                "missing_fields": missing_fields,
                "confidence": fixture.get("confidence"),
                "reason_codes": fixture.get("reason_codes") or ["FIXTURE_PROVIDER_NO_LIVE_EVIDENCE"],
                "manual_review_recommended": fixture.get("manual_review_recommended", False),
                "operating_mode": request.metadata.get("provider_operating_mode") or self.config.operating_mode,
                "demo_profile_key": request.metadata.get("demo_profile_key"),
                "execution_environment_label": (
                    request.metadata.get("execution_environment_label")
                    or self.config.execution_environment_label
                ),
                "transition_notes": request.metadata.get("provider_transition_notes") or [],
                "is_demo_result": bool(
                    str(request.metadata.get("provider_operating_mode") or self.config.operating_mode)
                    == PROVIDER_OPERATING_MODE_DEMO_MOCK
                ),
                "is_live_result": False,
            },
            technical_status=technical_status,
            http_status=None,
            latency_ms=fixture.get("latency_ms", 0),
        )

    def normalize_response(
        self,
        *,
        request: ProviderRequest,
        payload: dict | None,
        technical_status: str,
        http_status: int | None,
        latency_ms: int | None,
    ) -> ProviderResponse:
        normalized = as_dict(payload)
        return ProviderResponse(
            request_id=request.request_id,
            provider_key=self.provider_key,
            technical_status=str(normalized.get("technical_status") or technical_status),
            http_status=http_status,
            response_summary=as_dict(normalized.get("response_summary")),
            raw_result_ref=None,
            matched_fields=as_dict(normalized.get("matched_fields")),
            mismatched_fields=as_dict(normalized.get("mismatched_fields")),
            missing_fields=as_string_list(normalized.get("missing_fields")),
            confidence=as_float(normalized.get("confidence")),
            reason_codes=as_string_list(normalized.get("reason_codes")),
            latency_ms=int(latency_ms or 0),
            manual_review_recommended=bool(normalized.get("manual_review_recommended")),
            operating_mode=str(normalized.get("operating_mode") or request.metadata.get("provider_operating_mode") or self.config.operating_mode),
            demo_profile_key=normalized.get("demo_profile_key") or request.metadata.get("demo_profile_key"),
            execution_environment_label=(
                normalized.get("execution_environment_label")
                or request.metadata.get("execution_environment_label")
                or self.config.execution_environment_label
            ),
            transition_notes=as_string_list(
                normalized.get("transition_notes")
                or request.metadata.get("provider_transition_notes")
            ),
            is_demo_result=bool(normalized.get("is_demo_result")),
            is_live_result=bool(normalized.get("is_live_result")),
        )


def _build_local_record_fixture(
    *,
    request: ProviderRequest,
    fixture_path: Path,
    default_operating_mode: str,
    default_environment_label: str,
) -> dict[str, Any]:
    store = _load_local_verification_store(fixture_path)
    match = _match_local_record(store, request)
    operating_mode = str(request.metadata.get("provider_operating_mode") or default_operating_mode)
    execution_environment_label = (
        str(request.metadata.get("execution_environment_label") or default_environment_label)
        or default_environment_label
    )
    label = str(request.input_payload.get("label") or request.verifier_key or "Credential")
    record_id = str(match.get("record_id") or "")
    field_key = str(match.get("field_key") or _canonical_label(label))
    stored_value = match.get("stored_value")
    reason_codes = list(match.get("reason_codes") or [])

    response_summary = {
        "mode": "local_verification_store",
        "note": str(match.get("note") or "No matching local verification record was found."),
        "match_status": str(match.get("status") or "unverified"),
        "record_id": record_id or None,
        "field_key": field_key or None,
        "local_store_path": str(fixture_path),
        "operating_mode": operating_mode,
        "execution_environment_label": execution_environment_label,
        "demo_profile_key": request.metadata.get("demo_profile_key"),
        "mock_mode": operating_mode == PROVIDER_OPERATING_MODE_DEMO_MOCK,
        "live_execution": False,
    }

    if match.get("status") == "verified":
        return {
            "technical_status": PROVIDER_TECHNICAL_STATUS_SUCCESS,
            "response_summary": response_summary,
            "matched_fields": {
                field_key: stored_value,
            },
            "mismatched_fields": {},
            "missing_fields": [],
            "confidence": match.get("confidence", 0.99),
            "reason_codes": reason_codes or ["LOCAL_VERIFICATION_RECORD_MATCH"],
            "manual_review_recommended": False,
        }

    if match.get("status") == "mismatch":
        return {
            "technical_status": PROVIDER_TECHNICAL_STATUS_SUCCESS,
            "response_summary": response_summary,
            "matched_fields": {},
            "mismatched_fields": {
                field_key: {
                    "document_value": request.input_payload.get("value"),
                    "expected_value": stored_value,
                    "record_id": record_id or None,
                }
            },
            "missing_fields": [],
            "confidence": match.get("confidence", 0.98),
            "reason_codes": reason_codes or ["LOCAL_VERIFICATION_RECORD_MISMATCH"],
            "manual_review_recommended": False,
        }

    if match.get("status") == "manual_review":
        return {
            "technical_status": PROVIDER_TECHNICAL_STATUS_SUCCESS,
            "response_summary": response_summary,
            "matched_fields": {},
            "mismatched_fields": {},
            "missing_fields": [label],
            "confidence": match.get("confidence"),
            "reason_codes": reason_codes or ["LOCAL_VERIFICATION_RECORD_AMBIGUOUS"],
            "manual_review_recommended": True,
        }

    return {
        "technical_status": PROVIDER_TECHNICAL_STATUS_SUCCESS,
        "response_summary": response_summary,
        "matched_fields": {},
        "mismatched_fields": {},
        "missing_fields": [label],
        "confidence": match.get("confidence"),
        "reason_codes": reason_codes or ["LOCAL_VERIFICATION_RECORD_NOT_FOUND"],
        "manual_review_recommended": False,
    }


def _load_local_verification_store(fixture_path: Path) -> dict[str, Any]:
    if not fixture_path.exists():
        LOGGER.warning("LOCAL_VERIFICATION_STORE_MISSING path=%s", fixture_path)
        return {"records": []}
    try:
        with fixture_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:  # pragma: no cover - defensive
        LOGGER.warning("LOCAL_VERIFICATION_STORE_LOAD_FAILED path=%s", fixture_path, exc_info=True)
        return {"records": []}
    if isinstance(payload, dict):
        return payload
    LOGGER.warning("LOCAL_VERIFICATION_STORE_INVALID path=%s", fixture_path)
    return {"records": []}


def _match_local_record(store: dict[str, Any], request: ProviderRequest) -> dict[str, Any]:
    category = str(request.input_payload.get("category") or request.metadata.get("category") or "").strip().lower()
    verifier_key = str(request.verifier_key or "").strip()
    document_type = str(
        request.input_payload.get("document_type") or request.metadata.get("document_type") or ""
    ).strip()
    label = str(request.input_payload.get("label") or "").strip()
    credential_id = str(request.input_payload.get("credential_id") or "").strip()
    input_value = request.input_payload.get("value")
    normalized_value = request.input_payload.get("normalized_value") or input_value

    candidates = _collect_local_record_candidates(
        store=store,
        verifier_key=verifier_key,
        category=category,
        document_type=document_type,
        label=label,
        credential_id=credential_id,
    )
    if not candidates:
        return {
            "status": "unverified",
            "note": "No eligible local verification record matched the credential route and label.",
            "reason_codes": ["LOCAL_VERIFICATION_RECORD_NOT_FOUND"],
        }

    exact_label_matches = [
        candidate
        for candidate in candidates
        if candidate["label_match"] and _values_match(normalized_value, candidate["comparison_value"])
    ]
    if exact_label_matches:
        best = exact_label_matches[0]
        return {
            "status": "verified",
            "note": f"Matched against local verification record '{best['record_id']}'.",
            "record_id": best["record_id"],
            "field_key": best["field_key"],
            "stored_value": best["stored_value"],
            "confidence": best["confidence"],
            "reason_codes": ["LOCAL_VERIFICATION_RECORD_MATCH"],
        }

    exact_value_matches = [
        candidate
        for candidate in candidates
        if _values_match(normalized_value, candidate["comparison_value"])
    ]
    if exact_value_matches:
        best = exact_value_matches[0]
        return {
            "status": "verified",
            "note": (
                f"Matched by normalized value against local verification record '{best['record_id']}' "
                "using the bounded local store."
            ),
            "record_id": best["record_id"],
            "field_key": best["field_key"],
            "stored_value": best["stored_value"],
            "confidence": best["confidence"],
            "reason_codes": ["LOCAL_VERIFICATION_VALUE_MATCH"],
        }

    comparable_candidates = [
        candidate
        for candidate in candidates
        if candidate["label_match"] and _normalize_lookup_value(candidate["comparison_value"])
    ]
    if len(comparable_candidates) == 1:
        candidate = comparable_candidates[0]
        return {
            "status": "mismatch",
            "note": f"Local verification record '{candidate['record_id']}' contains a different value for this field.",
            "record_id": candidate["record_id"],
            "field_key": candidate["field_key"],
            "stored_value": candidate["stored_value"],
            "confidence": candidate["confidence"],
            "reason_codes": ["LOCAL_VERIFICATION_RECORD_MISMATCH"],
        }

    if comparable_candidates:
        unique_values = {
            _normalize_lookup_value(candidate["comparison_value"])
            for candidate in comparable_candidates
            if _normalize_lookup_value(candidate["comparison_value"])
        }
        if len(unique_values) == 1:
            candidate = comparable_candidates[0]
            return {
                "status": "mismatch",
                "note": (
                    "Eligible local verification records agreed on a different value for this field."
                ),
                "record_id": candidate["record_id"],
                "field_key": candidate["field_key"],
                "stored_value": candidate["stored_value"],
                "confidence": candidate["confidence"],
                "reason_codes": ["LOCAL_VERIFICATION_RECORD_MISMATCH"],
            }
        return {
            "status": "manual_review",
            "note": "Multiple local verification records could apply to this field, so manual review is safer.",
            "reason_codes": ["LOCAL_VERIFICATION_RECORD_AMBIGUOUS"],
        }

    return {
        "status": "manual_review",
        "note": "A local verification record exists for this field, but it does not contain a usable comparison value.",
        "reason_codes": ["LOCAL_VERIFICATION_RECORD_INCOMPLETE"],
    }


def _collect_local_record_candidates(
    *,
    store: dict[str, Any],
    verifier_key: str,
    category: str,
    document_type: str,
    label: str,
    credential_id: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    records = store.get("records")
    if not isinstance(records, list):
        return candidates

    for record in records:
        if not isinstance(record, dict):
            continue
        if not _record_supports_route(record, verifier_key=verifier_key, category=category, document_type=document_type):
            continue

        record_id = str(record.get("record_id") or "local-record")
        record_confidence = _safe_float(record.get("confidence"), default=0.99)
        fields = record.get("fields")
        if not isinstance(fields, list):
            continue

        for field in fields:
            if not isinstance(field, dict):
                continue
            label_match = _field_matches_label(field, label=label, credential_id=credential_id)

            score = _candidate_score(
                record=record,
                field=field,
                verifier_key=verifier_key,
                category=category,
                document_type=document_type,
                label=label,
                label_match=label_match,
            )
            candidates.append(
                {
                    "record_id": record_id,
                    "field_key": str(field.get("field_key") or _canonical_label(field.get("label") or label)),
                    "stored_value": field.get("value") if field.get("value") not in (None, "") else field.get("normalized_value"),
                    "comparison_value": field.get("normalized_value") or field.get("value"),
                    "confidence": _safe_float(field.get("confidence"), default=record_confidence),
                    "score": score,
                    "label_match": label_match,
                }
            )

    return sorted(candidates, key=lambda item: item["score"], reverse=True)


def _record_supports_route(
    record: dict[str, Any],
    *,
    verifier_key: str,
    category: str,
    document_type: str,
) -> bool:
    verifier_keys = {_canonical_label(value) for value in as_string_list(record.get("verifier_keys"))}
    categories = {_canonical_label(value) for value in as_string_list(record.get("categories"))}
    document_types = {_canonical_label(value) for value in as_string_list(record.get("document_types"))}

    if verifier_keys and _canonical_label(verifier_key) not in verifier_keys:
        return False
    if categories and _canonical_label(category) not in categories:
        return False
    if document_types and document_type and _canonical_label(document_type) not in document_types:
        return False
    return True


def _field_matches_label(field: dict[str, Any], *, label: str, credential_id: str) -> bool:
    requested = {_canonical_label(label), _canonical_label(credential_id)}
    aliases = {
        _canonical_label(field.get("field_key")),
        _canonical_label(field.get("label")),
    }
    aliases.update(_canonical_label(value) for value in as_string_list(field.get("label_aliases")))
    aliases.discard("")
    requested.discard("")
    return bool(requested and aliases.intersection(requested))


def _candidate_score(
    *,
    record: dict[str, Any],
    field: dict[str, Any],
    verifier_key: str,
    category: str,
    document_type: str,
    label: str,
    label_match: bool,
) -> int:
    score = 0
    record_document_types = {_canonical_label(value) for value in as_string_list(record.get("document_types"))}
    record_categories = {_canonical_label(value) for value in as_string_list(record.get("categories"))}
    record_verifier_keys = {_canonical_label(value) for value in as_string_list(record.get("verifier_keys"))}
    if document_type and _canonical_label(document_type) in record_document_types:
        score += 4
    if category and _canonical_label(category) in record_categories:
        score += 3
    if verifier_key and _canonical_label(verifier_key) in record_verifier_keys:
        score += 3
    if label_match:
        score += 4
    if _canonical_label(label) == _canonical_label(field.get("label")):
        score += 2
    return score


def _values_match(left: Any, right: Any) -> bool:
    normalized_left = _normalize_lookup_value(left)
    normalized_right = _normalize_lookup_value(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True

    compact_left = _compact_lookup_value(left)
    compact_right = _compact_lookup_value(right)
    return bool(compact_left and compact_right and compact_left == compact_right and len(compact_left) >= 6)


def _normalize_lookup_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _compact_lookup_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _canonical_label(value: Any) -> str:
    if value in (None, ""):
        return ""
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _safe_float(value: Any, *, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

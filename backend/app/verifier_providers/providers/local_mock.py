from __future__ import annotations

import json
import os
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
DEFAULT_LOCAL_VERIFICATION_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "mock_data" / "registry.json"
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

    def supports(self, verifier_key: str, category: str) -> bool:
        capability = self.get_capabilities()
        if not capability.enabled:
            return False
            
        # Verifier key must match one of our supported keys
        if verifier_key not in capability.supported_verifier_keys:
            return False
            
        # Category check is flexible: either in supported list or a substring match
        if not capability.supported_categories:
            return True
            
        target = _canonical_label(category)
        if any(c in target or target in c for c in capability.supported_categories):
            return True
            
        return False

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        fixture = as_dict(request.input_payload.get("provider_fixture"))
        if not fixture:
            fixture = _build_local_record_fixture(
                request=request,
                fixture_path=_resolve_local_verification_fixture_path(),
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
                "local_store_path": str(_resolve_local_verification_fixture_path()),
                "verification_authority": "local_mock",
            }
        raw_missing_fields = fixture.get("missing_fields")
        missing_fields = as_string_list(raw_missing_fields)
        # If we have a verified status, missing_fields should default to empty list, not [label]
        if raw_missing_fields is None and fixture.get("technical_status") == PROVIDER_TECHNICAL_STATUS_SUCCESS:
            match_status = (fixture.get("response_summary") or {}).get("match_status")
            if match_status == "verified":
                missing_fields = []
            elif not missing_fields:
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
                "is_mock_result": True,
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
            is_mock_result=bool(normalized.get("is_mock_result") or True),
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
        "verification_authority": "local_mock",
    }

    if match.get("status") == "verified":
        return {
            "technical_status": PROVIDER_TECHNICAL_STATUS_SUCCESS,
            "response_summary": response_summary,
            "matched_fields": match.get("matched_fields") or {field_key: stored_value},
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
            "matched_fields": match.get("matched_fields") or {},
            "mismatched_fields": match.get("mismatched_fields") or {
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


def _resolve_local_verification_fixture_path() -> Path:
    configured = (
        os.getenv("VERIFIER_LOCAL_VERIFICATION_STORE_PATH")
        or os.getenv("LOCAL_VERIFICATION_STORE_PATH")
        or ""
    ).strip()
    if configured:
        # Try relative to backend root if it's not absolute
        path = Path(configured)
        if not path.is_absolute():
            # Try from current dir, then from backend root
            if path.exists():
                return path
            backend_root = Path(__file__).resolve().parents[3]
            if (backend_root / path).exists():
                return backend_root / path
        return path
        
    # Extra check for the mock_data/registry.json location
    alt_path = Path(__file__).resolve().parents[1] / "mock_data" / "registry.json"
    if alt_path.exists():
        return alt_path
        
    return DEFAULT_LOCAL_VERIFICATION_FIXTURE_PATH


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

    # Identify the best matching record first
    records = store.get("records") or []
    best_record = None
    best_record_score = -1

    for record in records:
        if not isinstance(record, dict):
            continue
        if not _record_supports_route(record, verifier_key=verifier_key, category=category, document_type=document_type):
            continue
        
        # Simple scoring for the record as a whole, now including value matching
        score = _record_match_score(record, verifier_key, category, document_type, label, normalized_value)
        if score > best_record_score:
            best_record_score = score
            best_record = record

    if not best_record:
        return {
            "status": "unverified",
            "note": "No eligible local verification record matched the credential route and label.",
            "reason_codes": ["LOCAL_VERIFICATION_RECORD_NOT_FOUND"],
        }

    # Now collect all matching and mismatched fields from this record
    record_id = str(best_record.get("record_id") or "local-record")
    record_fields = best_record.get("fields") or []
    matched_fields = {}
    mismatched_fields = {}
    
    # Check every field in the record against the input payload (if present)
    input_fields = dict(request.input_payload.get("fields") or {})
    # If the request is for a single field (legacy behavior), we add it to a temporary dict
    if request.input_payload.get("label") and request.input_payload.get("value"):
        input_fields[_canonical_label(request.input_payload.get("label"))] = request.input_payload.get("value")

    for field in record_fields:
        if not isinstance(field, dict):
            continue
        
        field_key = str(field.get("field_key") or _canonical_label(field.get("label") or ""))
        stored_value = field.get("value") if field.get("value") not in (None, "") else field.get("normalized_value")
        comparison_value = field.get("normalized_value") or field.get("value")
        
        # Check if we have a corresponding value in the input to compare against
        # We look for the field_key or the label
        input_value = None
        for k, v in input_fields.items():
            if _canonical_label(k) == _canonical_label(field_key) or _canonical_label(k) == _canonical_label(field.get("label")):
                input_value = v
                break
        
        if input_value is not None:
            if _values_match(input_value, comparison_value):
                matched_fields[field_key] = stored_value
            else:
                mismatched_fields[field_key] = {
                    "document_value": input_value,
                    "expected_value": stored_value,
                    "record_id": record_id,
                }
        else:
            # If not in input, we still count it as "matched" evidence from the record
            # (unless it's mandatory, but the provider doesn't know that)
            matched_fields[field_key] = stored_value

    if mismatched_fields:
        return {
            "status": "mismatch",
            "note": f"Local verification record '{record_id}' contains mismatched data.",
            "record_id": record_id,
            "matched_fields": matched_fields,
            "mismatched_fields": mismatched_fields,
            "confidence": best_record.get("confidence", 0.98),
            "reason_codes": ["LOCAL_VERIFICATION_RECORD_MISMATCH"],
        }

    if matched_fields:
        return {
            "status": "verified",
            "note": f"Matched against local verification record '{record_id}'.",
            "record_id": record_id,
            "matched_fields": matched_fields,
            "confidence": best_record.get("confidence", 0.99),
            "reason_codes": ["LOCAL_VERIFICATION_RECORD_MATCH"],
        }

    return {
        "status": "manual_review",
        "note": f"A local verification record '{record_id}' exists but no field matches were confirmed.",
        "reason_codes": ["LOCAL_VERIFICATION_RECORD_INCOMPLETE"],
    }


def _record_match_score(record: dict, verifier_key: str, category: str, document_type: str, label: str, value: Any) -> int:
    score = 0
    record_verifier_keys = {_canonical_label(v) for v in as_string_list(record.get("verifier_keys"))}
    record_categories = {_canonical_label(v) for v in as_string_list(record.get("categories"))}
    record_document_types = {_canonical_label(v) for v in as_string_list(record.get("document_types"))}
    
    if _canonical_label(verifier_key) in record_verifier_keys:
        score += 10
    if _canonical_label(category) in record_categories:
        score += 5
    # Flexible category match
    elif any(c in _canonical_label(category) or _canonical_label(category) in c for c in record_categories):
        score += 3
    
    if _canonical_label(document_type) in record_document_types:
        score += 5

    # Check if any field in the record matches the requested value
    for field in record.get("fields", []):
        if _values_match(value, field.get("normalized_value") or field.get("value")):
            score += 20 # High boost for value match!
        if _field_matches_label(field, label=label, credential_id=""):
            score += 5
    
    return score


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

    # If the verifier key matches exactly, we consider it supported regardless of category
    # This allows Name/Identity verification to work even on Academic documents.
    if verifier_keys and _canonical_label(verifier_key) in verifier_keys:
        return True

    if verifier_keys and _canonical_label(verifier_key) not in verifier_keys:
        return False
    
    # Flexible category matching if verifier_key was not specified or not matched
    if categories:
        target = _canonical_label(category)
        if target not in categories:
            if not any(c in target or target in c for c in categories):
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
    if not compact_left or not compact_right:
        return False
        
    if compact_left == compact_right:
        return True
        
    # Robust substring matching: if one is contained in the other and is long enough
    if (compact_left in compact_right or compact_right in compact_left):
        return len(min(compact_left, compact_right, key=len)) >= 3
        
    return False


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

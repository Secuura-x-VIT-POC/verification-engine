from __future__ import annotations

import uuid

from ..base import VerifierProvider
from ..contracts import (
    PROVIDER_TECHNICAL_STATUS_SUCCESS,
    ProviderCapability,
    ProviderRequest,
    ProviderResponse,
    REQUEST_MODE_LOCAL_FIXTURE,
)
from ..normalizers import as_dict, as_float, as_string_list
from ..policies import ProviderConfig


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
        technical_status = str(fixture.get("technical_status") or PROVIDER_TECHNICAL_STATUS_SUCCESS)
        summary = as_dict(fixture.get("response_summary"))
        if not summary:
            summary = {
                "mode": "local_fixture",
                "note": "No live external evidence is configured in this environment.",
            }
        missing_fields = as_string_list(fixture.get("missing_fields"))
        if not missing_fields:
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
        )

from __future__ import annotations

import uuid

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

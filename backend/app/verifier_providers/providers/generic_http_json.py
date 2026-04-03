from __future__ import annotations

import time
import uuid
from urllib.parse import urljoin

from ..base import VerifierProvider
from ..contracts import (
    PROVIDER_TECHNICAL_STATUS_DISABLED,
    PROVIDER_TECHNICAL_STATUS_FAILED,
    PROVIDER_TECHNICAL_STATUS_SUCCESS,
    PROVIDER_TECHNICAL_STATUS_TIMEOUT,
    PROVIDER_TECHNICAL_STATUS_UNCONFIGURED,
    ProviderCapability,
    ProviderRequest,
    ProviderResponse,
    REQUEST_MODE_DOCUMENT_UPLOAD,
    REQUEST_MODE_FIELD_LOOKUP,
)
from ..http_client import SafeHttpClientError, SafeHttpJsonClient
from ..normalizers import as_dict, as_float, as_string_list
from ..policies import ProviderConfig


class GenericHttpJsonProvider(VerifierProvider):
    provider_key = ""
    provider_label = ""

    def __init__(
        self,
        *,
        provider_key: str,
        provider_label: str,
        config: ProviderConfig,
        client: SafeHttpJsonClient,
        supported_verifier_keys: list[str],
        supported_categories: list[str],
        endpoint_path: str,
    ):
        self.provider_key = provider_key
        self.provider_label = provider_label
        self.config = config
        self.client = client
        self.supported_verifier_keys = list(supported_verifier_keys)
        self.supported_categories = list(supported_categories)
        self.endpoint_path = endpoint_path

    def get_capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            provider_key=self.provider_key,
            provider_label=self.provider_label,
            supported_verifier_keys=self.supported_verifier_keys,
            supported_categories=self.supported_categories,
            supports_batch=False,
            supports_partial_match=True,
            supports_document_upload=self.config.allow_document_upload,
            supports_field_lookup=True,
            requires_credentials=True,
            default_timeout_ms=self.config.timeout_ms,
            enabled=self.config.enabled and bool(self.config.base_url),
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
            request_mode=REQUEST_MODE_DOCUMENT_UPLOAD if self.config.allow_document_upload else REQUEST_MODE_FIELD_LOOKUP,
            timeout_ms=timeout_ms,
            metadata=dict(metadata or {}),
        )

    def execute(self, request: ProviderRequest) -> ProviderResponse:
        if not self.config.enabled:
            return self.normalize_response(
                request=request,
                payload={"reason_codes": ["PROVIDER_DISABLED"]},
                technical_status=PROVIDER_TECHNICAL_STATUS_DISABLED,
                http_status=None,
                latency_ms=0,
            )
        if not self.config.base_url:
            return self.normalize_response(
                request=request,
                payload={"reason_codes": ["PROVIDER_UNCONFIGURED"]},
                technical_status=PROVIDER_TECHNICAL_STATUS_UNCONFIGURED,
                http_status=None,
                latency_ms=0,
            )

        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        started_at = time.perf_counter()
        try:
            response = self.client.post_json(
                url=urljoin(self.config.base_url.rstrip("/") + "/", self.endpoint_path.lstrip("/")),
                payload=request.input_payload,
                headers=headers,
                timeout_ms=request.timeout_ms,
                retry_budget=self.config.retry_budget,
                domain_allowlist=self.config.domain_allowlist,
            )
        except SafeHttpClientError as exc:
            latency_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
            technical_status = PROVIDER_TECHNICAL_STATUS_TIMEOUT if exc.code == "timeout" else PROVIDER_TECHNICAL_STATUS_FAILED
            return self.normalize_response(
                request=request,
                payload={
                    "reason_codes": [f"PROVIDER_{exc.code.upper()}"],
                    "response_summary": {"message": str(exc)},
                },
                technical_status=technical_status,
                http_status=exc.http_status,
                latency_ms=latency_ms,
            )

        latency_ms = max(int((time.perf_counter() - started_at) * 1000), 0)
        payload = dict(response.payload or {})
        payload["response_summary"] = as_dict(payload.get("response_summary"))
        payload["response_summary"]["retry_count"] = response.retry_count
        return self.normalize_response(
            request=request,
            payload=payload,
            technical_status=PROVIDER_TECHNICAL_STATUS_SUCCESS,
            http_status=response.http_status,
            latency_ms=latency_ms,
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
            response_summary=as_dict(
                normalized.get("response_summary")
                or normalized.get("summary")
                or normalized.get("data")
            ),
            raw_result_ref=normalized.get("raw_result_ref"),
            matched_fields=as_dict(normalized.get("matched_fields")),
            mismatched_fields=as_dict(normalized.get("mismatched_fields")),
            missing_fields=as_string_list(normalized.get("missing_fields")),
            confidence=as_float(normalized.get("confidence")),
            reason_codes=as_string_list(normalized.get("reason_codes")),
            latency_ms=int(latency_ms or 0),
            manual_review_recommended=bool(normalized.get("manual_review_recommended")),
        )

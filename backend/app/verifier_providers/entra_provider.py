from __future__ import annotations

import time
import uuid

from .base import VerifierProvider
from .contracts import ProviderCapability, ProviderRequest, ProviderResponse


class EntraVerifiedIDProvider(VerifierProvider):
    provider_id = "entra_verified_id"
    provider_key = "entra_verified_id"
    provider_label = "Microsoft Entra Verified ID"
    provider_mode = "live"   # important

    def get_capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            supported_verifier_keys=["entra_verified_id"],
            supported_categories=["identity", "credential"],
            enabled=True,
            claim_types=["IDENTITY", "CREDENTIAL"],
            assurance_levels=["HIGH"],
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
            request_id=str(uuid.uuid4()),
            session_id=session_id,
            task_id=task_id,
            provider_key=self.provider_key,
            verifier_key=verifier_key,
            input_payload=input_payload,
            redacted_payload=redacted_payload,
            timeout_ms=timeout_ms,
            metadata=metadata or {},
        )

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        start = time.time()

        # ⚠️ DO NOT CALL REAL ENTRA
        # simulate "not configured"
        await self._fake_delay()

        payload = {
            "status": "UNAVAILABLE",
            "confidence": 0.0,
            "reason_codes": ["ENTRA_NOT_CONFIGURED"],
            "matched_fields": [],
            "mismatched_fields": [],
        }

        latency = int((time.time() - start) * 1000)

        return self.normalize_response(
            request=request,
            payload=payload,
            technical_status="UNAVAILABLE",
            http_status=None,
            latency_ms=latency,
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

        if payload is None:
            return ProviderResponse(
                request_id=request.request_id,
                provider_key=self.provider_key,
                technical_status="FAILED",
                http_status=http_status,
                latency_ms=latency_ms,
                response_summary={},
                matched_fields={},
                mismatched_fields={},
                missing_fields=[],
                confidence=0.0,
                reason_codes=["NO_PAYLOAD"],
                manual_review_recommended=True,
                operating_mode=self.provider_mode,
                is_mock_result=False,
                is_demo_result=True,
                is_live_result=False,
                transition_notes=["No payload"],
            )

        return ProviderResponse(
            request_id=request.request_id,
            provider_key=self.provider_key,
            technical_status=technical_status,
            http_status=http_status,
            latency_ms=latency_ms,

            response_summary={
                "status": payload.get("status"),
                "provider": self.provider_id,
            },

            matched_fields={},
            mismatched_fields={},
            missing_fields=[],

            confidence=payload.get("confidence", 0.0),
            reason_codes=payload.get("reason_codes", []),

            manual_review_recommended=True,  # always true (unavailable)
            operating_mode=self.provider_mode,

            is_mock_result=False,
            is_demo_result=True,
            is_live_result=False,

            transition_notes=["Entra provider not configured"],
        )

    async def _fake_delay(self):
        import asyncio
        await asyncio.sleep(0.2)
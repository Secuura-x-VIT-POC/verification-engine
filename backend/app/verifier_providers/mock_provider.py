from __future__ import annotations

import random
import time
import uuid
from .base import VerifierProvider
from .contracts import ProviderCapability, ProviderRequest, ProviderResponse


class MockRegistryProvider(VerifierProvider):
    provider_id = "local_mock_registry"
    provider_key = "local_mock_registry"
    provider_label = "Local Mock Registry"
    provider_mode = "mock"

    def get_capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            supported_verifier_keys=["local_mock_registry"],
            supported_categories=["academic", "identity"],
            enabled=True,
            claim_types=["ISSUER_IDENTITY", "ACADEMIC_DEGREE"],
            assurance_levels=["LOW", "MEDIUM", "HIGH"],
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

        # simulate network delay
        await self._fake_delay()

        match = random.choice([True, False])

        payload = {
            "status": "MATCHED" if match else "MISMATCHED",
            "confidence": round(random.uniform(0.7, 0.99), 2),
            "reason_codes": ["MOCK_CHECK"],
            "checked_fields": list(request.input_payload.keys()),
            "matched_fields": list(request.input_payload.keys()) if match else [],
            "mismatched_fields": [] if match else list(request.input_payload.keys()),
        }

        latency = int((time.time() - start) * 1000)

        return self.normalize_response(
            request=request,
            payload=payload,
            technical_status="SUCCESS",
            http_status=200,
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
                is_mock_result=True,
                is_demo_result=True,
                is_live_result=False,
                transition_notes=["No payload received"],
            )

        return ProviderResponse(
            request_id=request.request_id,
            provider_key=self.provider_key,
            technical_status=technical_status,
            http_status=http_status,
            latency_ms=latency_ms,

            # ✅ MAIN PAYLOAD
            response_summary={
                "status": payload.get("status"),
                "provider": self.provider_id,
            },

            # ✅ REQUIRED STRUCTURED FIELDS
            matched_fields={
                k: True for k in payload.get("matched_fields", [])
            },
            mismatched_fields={
                k: True for k in payload.get("mismatched_fields", [])
            },
            missing_fields=[],

            confidence=payload.get("confidence", 0.0),
            reason_codes=payload.get("reason_codes", []),

            # ✅ SYSTEM FLAGS
            manual_review_recommended=payload.get("status") != "MATCHED",
            operating_mode=self.provider_mode,

            is_mock_result=True,
            is_demo_result=True,
            is_live_result=False,

            transition_notes=["Mock provider executed"],
        )

    async def _fake_delay(self):
        import asyncio
        await asyncio.sleep(random.uniform(0.1, 0.3))
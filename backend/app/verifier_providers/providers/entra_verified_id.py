from __future__ import annotations

from ..contracts import PROVIDER_OPERATING_MODE_DEMO_MOCK, ProviderRequest, ProviderResponse
from ..normalizers import as_dict, as_float, as_string_list
from .generic_http_json import GenericHttpJsonProvider


class EntraVerifiedIdProvider(GenericHttpJsonProvider):
    def __init__(self, *, config, client):
        super().__init__(
            provider_key="entra_verified_id",
            provider_label="Microsoft Entra Verified ID",
            config=config,
            client=client,
            supported_verifier_keys=["identity_db", "academic_registry", "certificate_registry"],
            supported_categories=["identity", "academic", "certificate"],
            endpoint_path="/presentations/verify",
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
        matched_fields = as_dict(
            normalized.get("matched_fields")
            or normalized.get("verified_claims")
            or normalized.get("validated_claims")
        )
        mismatched_fields = as_dict(
            normalized.get("mismatched_fields")
            or normalized.get("rejected_claims")
            or normalized.get("contradicted_claims")
        )
        missing_fields = as_string_list(
            normalized.get("missing_fields")
            or normalized.get("requested_but_missing_claims")
            or normalized.get("missing_claims")
        )
        response_summary = as_dict(
            normalized.get("response_summary")
            or normalized.get("presentation_summary")
            or normalized.get("presentation_result")
        )
        if "trust_rail" not in response_summary:
            response_summary["trust_rail"] = "Microsoft Entra Verified ID"
        if "presentation_mode" not in response_summary:
            response_summary["presentation_mode"] = "verifiable_credential_presentation"

        reason_codes = as_string_list(normalized.get("reason_codes"))
        if not reason_codes:
            if matched_fields and not mismatched_fields:
                reason_codes = ["ENTRA_VERIFIED_ID_MATCH"]
            elif mismatched_fields:
                reason_codes = ["ENTRA_VERIFIED_ID_MISMATCH"]
            else:
                reason_codes = ["ENTRA_VERIFIED_ID_NO_MATCH"]

        manual_review_recommended = bool(normalized.get("manual_review_recommended"))
        presentation_state = str(response_summary.get("presentation_state") or "").lower()
        if presentation_state in {"pending", "needs_review", "manual_review"}:
            manual_review_recommended = True

        return ProviderResponse(
            request_id=request.request_id,
            provider_key=self.provider_key,
            technical_status=str(normalized.get("technical_status") or technical_status),
            http_status=http_status,
            response_summary=response_summary,
            raw_result_ref=normalized.get("raw_result_ref") or normalized.get("presentation_id"),
            matched_fields=matched_fields,
            mismatched_fields=mismatched_fields,
            missing_fields=missing_fields,
            confidence=as_float(normalized.get("confidence")),
            reason_codes=reason_codes,
            latency_ms=int(latency_ms or 0),
            manual_review_recommended=manual_review_recommended,
            operating_mode=str(
                normalized.get("operating_mode")
                or request.metadata.get("provider_operating_mode")
                or self.config.operating_mode
            ),
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
            is_mock_result=bool(normalized.get("is_mock_result")),
            is_demo_result=bool(
                normalized.get("is_demo_result")
                or str(request.metadata.get("provider_operating_mode") or self.config.operating_mode)
                == PROVIDER_OPERATING_MODE_DEMO_MOCK
            ),
            is_live_result=bool(normalized.get("is_live_result") or http_status),
        )

from __future__ import annotations

from datetime import datetime, timezone

from .schema import ConnectorResponse


def verify(data: dict) -> ConnectorResponse:
    is_valid = data.get("certificate") == "valid" or data.get("credential_status") == "valid"

    if is_valid:
        return ConnectorResponse(
            connector_id="entra_vc_mock",
            assurance_class="HIGH",
            status="VERIFIED",
            reason_codes=["VC_VALID"],
            matched_claims=data,
            mismatched_claims={},
            source_timestamp=datetime.now(timezone.utc),
            technical_state="SUCCESS",
        )

    return ConnectorResponse(
        connector_id="entra_vc_mock",
        assurance_class="HIGH",
        status="INVALID",
        reason_codes=["INVALID_CERTIFICATE"],
        matched_claims={},
        mismatched_claims=data,
        source_timestamp=datetime.now(timezone.utc),
        technical_state="SUCCESS",
    )

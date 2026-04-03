# Temporary mock connector for broker testing only
# Not part of final assigned scope
from app.sessions.constants import SessionState
from app.connectors.schema import ConnectorResponse

def verify(data: dict):
    if data.get("certificate") == "valid":
        return ConnectorResponse(
            connector_id="vc",
            status=SessionState.VERIFIED,
            reason_codes=[],
            matched_claims=data,
            mismatched_claims={}
        )

    return ConnectorResponse(
        connector_id="vc",
        status="NOT_VERIFIED",
        reason_codes=["INVALID_CERTIFICATE"],
        matched_claims={},
        mismatched_claims=data
    )
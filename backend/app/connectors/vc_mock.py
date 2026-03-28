from app.connectors.schema import ConnectorResponse

def verify(data: dict):
    if data.get("certificate") == "valid":
        return ConnectorResponse(
            connector_id="vc",
            status="VERIFIED",
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
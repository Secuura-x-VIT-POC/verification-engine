from pydantic import BaseModel

class ConnectorResponse(BaseModel):
    connector_id: str
    status: str
    reason_codes: list
    matched_claims: dict
    mismatched_claims: dict
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConnectorResponse(BaseModel):
    connector_id: str
    status: str
    reason_codes: list[str] = Field(default_factory=list)
    matched_claims: dict[str, object] = Field(default_factory=dict)
    mismatched_claims: dict[str, object] = Field(default_factory=dict)
    assurance_class: str = "HIGH"
    source_timestamp: datetime | None = None
    technical_state: str = "SUCCESS"

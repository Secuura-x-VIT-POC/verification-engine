from __future__ import annotations

from typing import Any

from pydantic import Field

from ..verification_domain.contracts import ContractModel
from ..verifier_providers.contracts import PROVIDER_OPERATING_MODE_LIVE_DISABLED


class DemoProviderFixture(ContractModel):
    provider_key: str
    provider_label: str
    verifier_key: str
    scenario_status: str
    matched_fields: dict[str, Any] = Field(default_factory=dict)
    mismatched_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    response_summary: dict[str, Any] = Field(default_factory=dict)
    manual_review_recommended: bool = False
    latency_ms: int = 0


class DemoProfileSummary(ContractModel):
    session_id: str
    profile_key: str | None = None
    profile_label: str = "No seeded demo profile"
    description: str = "No seeded demo profile is active for this session."
    scenario_family: str = "none"
    provider_operating_mode: str = PROVIDER_OPERATING_MODE_LIVE_DISABLED
    seeded: bool = False
    notes: list[str] = Field(default_factory=list)

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ..verification_domain.contracts import ContractModel


PROVIDER_TECHNICAL_STATUS_SUCCESS = "SUCCESS"
PROVIDER_TECHNICAL_STATUS_FAILED = "FAILED"
PROVIDER_TECHNICAL_STATUS_TIMEOUT = "TIMEOUT"
PROVIDER_TECHNICAL_STATUS_DISABLED = "DISABLED"
PROVIDER_TECHNICAL_STATUS_BLOCKED = "BLOCKED"
PROVIDER_TECHNICAL_STATUS_UNCONFIGURED = "UNCONFIGURED"
PROVIDER_TECHNICAL_STATUS_SKIPPED = "SKIPPED"

PROVIDER_EXECUTION_STATUS_NOT_STARTED = "NOT_STARTED"
PROVIDER_EXECUTION_STATUS_RUNNING = "RUNNING"
PROVIDER_EXECUTION_STATUS_READY = "READY"
PROVIDER_EXECUTION_STATUS_FAILED = "FAILED"

REQUEST_MODE_FIELD_LOOKUP = "FIELD_LOOKUP"
REQUEST_MODE_DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
REQUEST_MODE_LOCAL_FIXTURE = "LOCAL_FIXTURE"

OUTBOUND_MODE_LOCAL_ONLY = "LOCAL_ONLY"
OUTBOUND_MODE_HTTP_JSON = "HTTP_JSON"
OUTBOUND_MODE_DISABLED = "DISABLED"

PROVIDER_OPERATING_MODE_DEMO_MOCK = "DEMO_MOCK"
PROVIDER_OPERATING_MODE_LOCAL_MOCK = "LOCAL_MOCK"
PROVIDER_OPERATING_MODE_EXTERNAL_CONFIGURED = "EXTERNAL_CONFIGURED"
PROVIDER_OPERATING_MODE_LIVE_DISABLED = "LIVE_DISABLED"
PROVIDER_OPERATING_MODE_MANUAL_ONLY = "MANUAL_ONLY"


class ProviderCapability(ContractModel):
    provider_key: str
    provider_label: str
    supported_verifier_keys: list[str] = Field(default_factory=list)
    supported_categories: list[str] = Field(default_factory=list)
    supports_batch: bool = False
    supports_partial_match: bool = False
    supports_document_upload: bool = False
    supports_field_lookup: bool = True
    requires_credentials: bool = False
    default_timeout_ms: int = 3000
    enabled: bool = False
    operating_mode: str = PROVIDER_OPERATING_MODE_LIVE_DISABLED
    execution_environment_label: str | None = None
    demo_supported: bool = False


class ProviderRequest(ContractModel):
    request_id: str
    session_id: str
    task_id: str
    verifier_key: str
    provider_key: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    redacted_payload: dict[str, Any] = Field(default_factory=dict)
    request_mode: str = REQUEST_MODE_FIELD_LOOKUP
    timeout_ms: int = 3000
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProviderResponse(ContractModel):
    request_id: str
    provider_key: str
    technical_status: str = PROVIDER_TECHNICAL_STATUS_SKIPPED
    http_status: int | None = None
    response_summary: dict[str, Any] = Field(default_factory=dict)
    raw_result_ref: str | None = None
    matched_fields: dict[str, Any] = Field(default_factory=dict)
    mismatched_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: float | None = None
    reason_codes: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
    manual_review_recommended: bool = False
    operating_mode: str = PROVIDER_OPERATING_MODE_LIVE_DISABLED
    demo_profile_key: str | None = None
    execution_environment_label: str | None = None
    transition_notes: list[str] = Field(default_factory=list)
    is_mock_result: bool = False
    is_demo_result: bool = False
    is_live_result: bool = False


class ProviderExecutionTrace(ContractModel):
    request_id: str
    provider_key: str
    provider_label: str | None = None
    verifier_key: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    technical_status: str = PROVIDER_TECHNICAL_STATUS_SKIPPED
    redaction_applied: bool = False
    outbound_mode: str = OUTBOUND_MODE_DISABLED
    retry_count: int = 0
    error_summary: str | None = None
    http_status: int | None = None
    response_summary: dict[str, Any] = Field(default_factory=dict)
    fallback_used: bool = False
    provider_operating_mode: str = PROVIDER_OPERATING_MODE_LIVE_DISABLED
    demo_profile_key: str | None = None
    execution_environment_label: str | None = None
    transition_notes: list[str] = Field(default_factory=list)
    is_mock_result: bool = False
    is_demo_result: bool = False
    is_live_result: bool = False


class ProviderTransitionConfig(ContractModel):
    preferred_provider_rail: str = "entra_verified_id"
    provider_operating_mode: str = PROVIDER_OPERATING_MODE_LIVE_DISABLED
    enabled_provider_modes: list[str] = Field(default_factory=list)
    demo_profile_key: str | None = None
    live_provider_enabled: bool = False
    fallback_policy: str = "SUPPLEMENTARY_THEN_LOCAL_MOCK"
    manual_review_policy: str = "RECOMMEND_ON_UNCERTAINTY"
    execution_environment_label: str = "Local environment"
    provider_transition_notes: list[str] = Field(default_factory=list)


class ProviderCapabilityCollection(ContractModel):
    session_id: str
    capabilities: list[ProviderCapability] = Field(default_factory=list)


class ProviderExecutionTraceCollection(ContractModel):
    session_id: str
    document_type: str = "unknown"
    traces: list[ProviderExecutionTrace] = Field(default_factory=list)


class SessionProviderExecutionStatus(ContractModel):
    session_id: str
    workflow_state: str
    provider_execution_status: str = PROVIDER_EXECUTION_STATUS_NOT_STARTED
    provider_execution_error: str | None = None
    traces_available: bool = False
    trace_count: int = 0
    provider_keys_used: list[str] = Field(default_factory=list)
    outbound_attempted: bool = False
    fallback_used: bool = False
    provider_operating_mode: str = PROVIDER_OPERATING_MODE_LIVE_DISABLED
    execution_environment_label: str | None = None
    demo_profile_key: str | None = None
    provider_transition_notes: list[str] = Field(default_factory=list)
    live_provider_enabled: bool = False
    preferred_provider_rail: str = "entra_verified_id"
    fallback_policy: str = "SUPPLEMENTARY_THEN_LOCAL_MOCK"
    manual_review_policy: str = "RECOMMEND_ON_UNCERTAINTY"


class SessionProviderOperatingMode(ContractModel):
    session_id: str
    workflow_state: str
    provider_operating_mode: str = PROVIDER_OPERATING_MODE_LIVE_DISABLED
    execution_environment_label: str = "Local environment"
    demo_profile_key: str | None = None
    preferred_provider_rail: str = "entra_verified_id"
    enabled_provider_modes: list[str] = Field(default_factory=list)
    live_provider_enabled: bool = False
    fallback_policy: str = "SUPPLEMENTARY_THEN_LOCAL_MOCK"
    manual_review_policy: str = "RECOMMEND_ON_UNCERTAINTY"
    provider_transition_notes: list[str] = Field(default_factory=list)

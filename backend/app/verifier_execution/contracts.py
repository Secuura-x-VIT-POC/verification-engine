from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from ..verification_domain.contracts import (
    AUDIT_STATUS_MANUAL_REVIEW,
    AUDIT_STATUS_NOT_APPLICABLE,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_UNVERIFIED,
    AUDIT_STATUS_VERIFIED,
    ContractModel,
    OUTCOME_COLOR_AMBER,
    OUTCOME_COLOR_GREEN,
    OUTCOME_COLOR_NEUTRAL,
)


EXECUTION_STATUS_NOT_STARTED = "NOT_STARTED"
EXECUTION_STATUS_RUNNING = "RUNNING"
EXECUTION_STATUS_READY = "READY"
EXECUTION_STATUS_FAILED = "FAILED"

TASK_STATUS_SUCCEEDED = "SUCCEEDED"
TASK_STATUS_PARTIAL = "PARTIAL"
TASK_STATUS_FAILED = "FAILED"
TASK_STATUS_MANUAL_REVIEW = "MANUAL_REVIEW"
TASK_STATUS_SKIPPED = "SKIPPED"


class VerificationTaskResult(ContractModel):
    task_id: str
    credential_id: str
    verifier_key: str
    verifier_label: str
    preferred_provider_key: str | None = None
    preferred_provider_label: str | None = None
    planned_provider_key: str | None = None
    planned_provider_label: str | None = None
    executed_provider_key: str | None = None
    executed_provider_label: str | None = None
    execution_mode: str | None = None
    fallback_reason: str | None = None
    is_live_result: bool = False
    is_mock_result: bool = False
    is_demo_result: bool = False
    task_status: str = TASK_STATUS_PARTIAL
    audit_status: str = AUDIT_STATUS_UNVERIFIED
    outcome_color: str = OUTCOME_COLOR_AMBER
    explanation: str
    reason_codes: list[str] = Field(default_factory=list)
    matched_fields: dict[str, Any] = Field(default_factory=dict)
    mismatched_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    raw_result_summary: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    executed_at: datetime | None = None
    latency_ms: int | None = None
    manual_review_recommended: bool = False


class CredentialVerificationBundle(ContractModel):
    credential_id: str
    label: str
    category: str
    selected_task_ids: list[str] = Field(default_factory=list)
    result_count: int = 0
    final_audit_status: str = AUDIT_STATUS_UNVERIFIED
    final_outcome_color: str = OUTCOME_COLOR_AMBER
    explanation: str
    reason_codes: list[str] = Field(default_factory=list)
    best_result: VerificationTaskResult | None = None
    all_results: list[VerificationTaskResult] = Field(default_factory=list)


class SessionVerificationExecutionSummary(ContractModel):
    session_id: str
    total_tasks: int = 0
    succeeded_tasks: int = 0
    partial_tasks: int = 0
    failed_tasks: int = 0
    manual_review_tasks: int = 0
    skipped_tasks: int = 0
    overall_execution_status: str = EXECUTION_STATUS_NOT_STARTED
    verifier_keys_used: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class VerificationTaskResultCollection(ContractModel):
    session_id: str
    document_type: str = "unknown"
    results: list[VerificationTaskResult] = Field(default_factory=list)


class CredentialVerificationBundleCollection(ContractModel):
    session_id: str
    document_type: str = "unknown"
    bundles: list[CredentialVerificationBundle] = Field(default_factory=list)


class SessionVerificationExecutionStatus(ContractModel):
    session_id: str
    workflow_state: str
    verification_execution_status: str = EXECUTION_STATUS_NOT_STARTED
    verification_execution_error: str | None = None
    task_results_available: bool = False
    credential_bundles_available: bool = False
    verification_execution_summary_available: bool = False


EMPTY_EXECUTION_SUMMARY = SessionVerificationExecutionSummary(
    session_id="",
    total_tasks=0,
    succeeded_tasks=0,
    partial_tasks=0,
    failed_tasks=0,
    manual_review_tasks=0,
    skipped_tasks=0,
    overall_execution_status=EXECUTION_STATUS_NOT_STARTED,
    verifier_keys_used=[],
    started_at=None,
    completed_at=None,
)


def task_status_to_default_audit(task_status: str) -> tuple[str, str]:
    if task_status == TASK_STATUS_SUCCEEDED:
        return AUDIT_STATUS_VERIFIED, OUTCOME_COLOR_GREEN
    if task_status == TASK_STATUS_PARTIAL:
        return AUDIT_STATUS_PARTIAL, OUTCOME_COLOR_AMBER
    if task_status == TASK_STATUS_MANUAL_REVIEW:
        return AUDIT_STATUS_MANUAL_REVIEW, OUTCOME_COLOR_AMBER
    if task_status == TASK_STATUS_SKIPPED:
        return AUDIT_STATUS_NOT_APPLICABLE, OUTCOME_COLOR_NEUTRAL
    return AUDIT_STATUS_UNVERIFIED, OUTCOME_COLOR_AMBER

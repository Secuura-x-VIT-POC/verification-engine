from __future__ import annotations

from abc import ABC, abstractmethod

from ...verification_domain.contracts import (
    AUDIT_STATUS_MANUAL_REVIEW,
    AUDIT_STATUS_MISMATCH,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_UNVERIFIED,
    AUDIT_STATUS_VERIFIED,
    OUTCOME_COLOR_AMBER,
    OUTCOME_COLOR_GREEN,
    OUTCOME_COLOR_RED,
    ExtractedCredential,
    VerificationTask,
)
from ..adapters import (
    VerificationExecutionContext,
    document_confidence,
    find_connector_claim_evidence,
    has_grounding,
    summarize_result,
)
from ..contracts import (
    TASK_STATUS_MANUAL_REVIEW,
    TASK_STATUS_PARTIAL,
    TASK_STATUS_SUCCEEDED,
    VerificationTaskResult,
)


class CredentialVerifier(ABC):
    verifier_key = ""
    verifier_label = ""

    @abstractmethod
    def execute(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult:
        ...

    def build_result(
        self,
        *,
        task: VerificationTask,
        credential: ExtractedCredential,
        task_status: str,
        audit_status: str,
        outcome_color: str,
        explanation: str,
        reason_codes: list[str] | None = None,
        matched_fields: dict | None = None,
        mismatched_fields: dict | None = None,
        missing_fields: list[str] | None = None,
        raw_result_summary: dict | None = None,
        confidence: float | None = None,
        manual_review_recommended: bool = False,
    ) -> VerificationTaskResult:
        return VerificationTaskResult(
            task_id=task.task_id,
            credential_id=credential.credential_id,
            verifier_key=task.verifier_key,
            verifier_label=task.verifier_label,
            task_status=task_status,
            audit_status=audit_status,
            outcome_color=outcome_color,
            explanation=explanation,
            reason_codes=list(reason_codes or []),
            matched_fields=dict(matched_fields or {}),
            mismatched_fields=dict(mismatched_fields or {}),
            missing_fields=list(missing_fields or []),
            raw_result_summary=dict(raw_result_summary or {}),
            confidence=confidence if confidence is not None else document_confidence(credential),
            manual_review_recommended=manual_review_recommended,
        )


class ConnectorAwareVerifier(CredentialVerifier):
    def execute(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult:
        claim_evidence = find_connector_claim_evidence(context.connector_payload, credential)
        connector = claim_evidence["connector"]
        matched_fields = claim_evidence["matched_fields"]
        mismatched_fields = claim_evidence["mismatched_fields"]

        if mismatched_fields:
            reason_codes = list(connector.get("reason_codes") or ["CONNECTOR_MISMATCH"])
            return self.build_result(
                task=task,
                credential=credential,
                task_status=TASK_STATUS_SUCCEEDED,
                audit_status=AUDIT_STATUS_MISMATCH,
                outcome_color=OUTCOME_COLOR_RED,
                explanation=f"{task.verifier_label} found contradictory evidence for this credential.",
                reason_codes=reason_codes,
                matched_fields=matched_fields,
                mismatched_fields=mismatched_fields,
                raw_result_summary=summarize_result(
                    execution_mode="connector_mismatch",
                    task=task,
                    credential=credential,
                    connector=connector,
                    matched_fields=matched_fields,
                    mismatched_fields=mismatched_fields,
                ),
            )

        if matched_fields:
            reason_codes = list(connector.get("reason_codes") or ["CONNECTOR_VERIFIED"])
            return self.build_result(
                task=task,
                credential=credential,
                task_status=TASK_STATUS_SUCCEEDED,
                audit_status=AUDIT_STATUS_VERIFIED,
                outcome_color=OUTCOME_COLOR_GREEN,
                explanation=f"{task.verifier_label} matched document evidence for this credential.",
                reason_codes=reason_codes,
                matched_fields=matched_fields,
                raw_result_summary=summarize_result(
                    execution_mode="connector_match",
                    task=task,
                    credential=credential,
                    connector=connector,
                    matched_fields=matched_fields,
                ),
            )

        return self.execute_without_connector(task, credential, context)

    @abstractmethod
    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult:
        ...

    def build_partial_result(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        *,
        explanation: str,
        reason_codes: list[str],
        extra_summary: dict | None = None,
    ) -> VerificationTaskResult:
        return self.build_result(
            task=task,
            credential=credential,
            task_status=TASK_STATUS_PARTIAL,
            audit_status=AUDIT_STATUS_PARTIAL,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation=explanation,
            reason_codes=reason_codes,
            raw_result_summary=summarize_result(
                execution_mode="rule_only_partial",
                task=task,
                credential=credential,
                extra=extra_summary,
            ),
        )

    def build_manual_review_result(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        *,
        explanation: str,
        reason_codes: list[str],
        extra_summary: dict | None = None,
    ) -> VerificationTaskResult:
        return self.build_result(
            task=task,
            credential=credential,
            task_status=TASK_STATUS_MANUAL_REVIEW,
            audit_status=AUDIT_STATUS_MANUAL_REVIEW,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation=explanation,
            reason_codes=reason_codes,
            missing_fields=[credential.label],
            raw_result_summary=summarize_result(
                execution_mode="manual_review",
                task=task,
                credential=credential,
                extra=extra_summary,
            ),
            manual_review_recommended=True,
        )

    def build_unverified_result(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        *,
        explanation: str,
        reason_codes: list[str],
        extra_summary: dict | None = None,
    ) -> VerificationTaskResult:
        return self.build_result(
            task=task,
            credential=credential,
            task_status=TASK_STATUS_PARTIAL,
            audit_status=AUDIT_STATUS_UNVERIFIED,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation=explanation,
            reason_codes=reason_codes,
            missing_fields=[credential.label],
            raw_result_summary=summarize_result(
                execution_mode="rule_only_unverified",
                task=task,
                credential=credential,
                extra=extra_summary,
            ),
        )

    def has_strong_document_signal(self, credential: ExtractedCredential) -> bool:
        return document_confidence(credential) >= 0.75 and has_grounding(credential)

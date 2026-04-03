from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext, summarize_result
from ..contracts import (
    TASK_STATUS_MANUAL_REVIEW,
    VerificationTaskResult,
)
from .base import CredentialVerifier


class ManualReviewVerifier(CredentialVerifier):
    verifier_key = "manual_review"
    verifier_label = "Manual Review"

    def execute(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult:
        return self.build_result(
            task=task,
            credential=credential,
            task_status=TASK_STATUS_MANUAL_REVIEW,
            audit_status="MANUAL_REVIEW",
            outcome_color="amber",
            explanation="No deterministic verifier is configured for this credential, so manual review is required.",
            reason_codes=["MANUAL_REVIEW_REQUIRED"],
            missing_fields=[credential.label],
            raw_result_summary=summarize_result(
                execution_mode="MANUAL_REVIEW",
                task=task,
                credential=credential,
            ),
            manual_review_recommended=True,
            execution_mode="MANUAL_REVIEW",
        )

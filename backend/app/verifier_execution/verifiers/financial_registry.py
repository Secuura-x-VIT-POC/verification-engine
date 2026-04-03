from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext, looks_like_financial_identifier
from .base import ConnectorAwareVerifier


class FinancialRegistryVerifier(ConnectorAwareVerifier):
    verifier_key = "financial_registry"
    verifier_label = "Financial Registry"

    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ):
        if self.has_strong_document_signal(credential) and looks_like_financial_identifier(credential.normalized_value):
            return self.build_partial_result(
                task,
                credential,
                explanation="Financial identifier formatting is plausible, but no external financial verifier is connected in this stage.",
                reason_codes=["FINANCIAL_FORMAT_ONLY"],
            )

        return self.build_manual_review_result(
            task,
            credential,
            explanation="Financial data needs manual review until a deterministic registry is configured.",
            reason_codes=["FINANCIAL_REQUIRES_MANUAL_REVIEW"],
        )

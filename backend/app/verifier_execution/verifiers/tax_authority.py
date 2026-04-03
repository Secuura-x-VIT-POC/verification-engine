from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext, looks_like_tax_identifier
from .base import ConnectorAwareVerifier


class TaxAuthorityVerifier(ConnectorAwareVerifier):
    verifier_key = "tax_authority"
    verifier_label = "Tax Authority"

    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ):
        if self.has_strong_document_signal(credential) and looks_like_tax_identifier(credential.normalized_value):
            return self.build_partial_result(
                task,
                credential,
                explanation="Tax identifier formatting is plausible, but no tax authority evidence is available in this session.",
                reason_codes=["TAX_FORMAT_ONLY"],
            )

        return self.build_manual_review_result(
            task,
            credential,
            explanation="Tax data requires manual review because no deterministic authority check is configured yet.",
            reason_codes=["TAX_REQUIRES_MANUAL_REVIEW"],
        )

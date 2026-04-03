from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext, looks_like_address
from .base import ConnectorAwareVerifier


class AddressCheckVerifier(ConnectorAwareVerifier):
    verifier_key = "address_check"
    verifier_label = "Address Check"

    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ):
        if self.has_strong_document_signal(credential) and looks_like_address(credential.normalized_value):
            return self.build_partial_result(
                task,
                credential,
                explanation="Address structure looks plausible, but this session has no external address verification evidence.",
                reason_codes=["ADDRESS_FORMAT_ONLY"],
                extra_summary={"value_shape": "address_like"},
            )

        return self.build_manual_review_result(
            task,
            credential,
            explanation="Address evidence is too weak for deterministic validation without manual review.",
            reason_codes=["ADDRESS_REQUIRES_MANUAL_REVIEW"],
        )

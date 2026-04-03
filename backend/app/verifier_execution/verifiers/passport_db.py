from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext, looks_like_passport
from .base import ConnectorAwareVerifier


class PassportDatabaseVerifier(ConnectorAwareVerifier):
    verifier_key = "passport_db"
    verifier_label = "Passport Database"

    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ):
        if self.has_strong_document_signal(credential) and looks_like_passport(credential.normalized_value):
            return self.build_partial_result(
                task,
                credential,
                explanation="Passport formatting is plausible, but there is no passport registry evidence in this session.",
                reason_codes=["PASSPORT_FORMAT_ONLY"],
                extra_summary={"value_shape": "passport_like"},
            )

        return self.build_manual_review_result(
            task,
            credential,
            explanation="Passport data cannot be confirmed deterministically from the currently available evidence.",
            reason_codes=["PASSPORT_REQUIRES_MANUAL_REVIEW"],
        )

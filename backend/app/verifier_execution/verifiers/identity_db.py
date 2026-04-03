from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext, looks_like_name
from .base import ConnectorAwareVerifier


class IdentityDatabaseVerifier(ConnectorAwareVerifier):
    verifier_key = "identity_db"
    verifier_label = "Identity Database"

    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ):
        if self.has_strong_document_signal(credential) and looks_like_name(credential.normalized_value):
            return self.build_partial_result(
                task,
                credential,
                explanation="Identity data is extracted and grounded, but no database evidence is available in this session.",
                reason_codes=["IDENTITY_EVIDENCE_PENDING"],
                extra_summary={"value_shape": "name_like"},
            )

        return self.build_manual_review_result(
            task,
            credential,
            explanation="Identity data is not grounded strongly enough to rely on without an external match.",
            reason_codes=["IDENTITY_REQUIRES_MANUAL_REVIEW"],
            extra_summary={"value_shape": "weak_or_unknown"},
        )

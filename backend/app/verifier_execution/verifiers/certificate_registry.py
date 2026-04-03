from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext
from .base import ConnectorAwareVerifier


class CertificateRegistryVerifier(ConnectorAwareVerifier):
    verifier_key = "certificate_registry"
    verifier_label = "Certificate Registry"

    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ):
        if self.has_strong_document_signal(credential):
            return self.build_partial_result(
                task,
                credential,
                explanation="Certificate data is grounded in the document, but no certificate registry evidence exists in this session.",
                reason_codes=["CERTIFICATE_EVIDENCE_PENDING"],
            )

        return self.build_manual_review_result(
            task,
            credential,
            explanation="Certificate data needs manual review because the current evidence is incomplete.",
            reason_codes=["CERTIFICATE_REQUIRES_MANUAL_REVIEW"],
        )

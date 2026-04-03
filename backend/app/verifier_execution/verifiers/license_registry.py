from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext, looks_like_license
from .base import ConnectorAwareVerifier


class LicenseRegistryVerifier(ConnectorAwareVerifier):
    verifier_key = "license_registry"
    verifier_label = "License Registry"

    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ):
        if self.has_strong_document_signal(credential) and looks_like_license(credential.normalized_value):
            return self.build_partial_result(
                task,
                credential,
                explanation="License formatting looks plausible, but no registry evidence is available in this session.",
                reason_codes=["LICENSE_FORMAT_ONLY"],
            )

        return self.build_manual_review_result(
            task,
            credential,
            explanation="License data cannot be validated deterministically from the current evidence.",
            reason_codes=["LICENSE_REQUIRES_MANUAL_REVIEW"],
        )

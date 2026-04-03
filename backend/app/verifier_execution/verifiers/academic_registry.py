from __future__ import annotations

from ...verification_domain.contracts import ExtractedCredential, VerificationTask
from ..adapters import VerificationExecutionContext, resolve_document_institution
from .base import ConnectorAwareVerifier


class AcademicRegistryVerifier(ConnectorAwareVerifier):
    verifier_key = "academic_registry"
    verifier_label = "Academic Registry"

    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ):
        institution = resolve_document_institution(context.extraction_payload).lower()
        if "vit" in institution:
            return self.build_unverified_result(
                task,
                credential,
                explanation="This issuer is routed to the academic registry, but no registry match was available for this credential.",
                reason_codes=["ACADEMIC_REGISTRY_NO_MATCH"],
                extra_summary={"issuer_hint": institution or "unknown"},
            )

        if institution:
            return self.build_manual_review_result(
                task,
                credential,
                explanation="The issuer is not yet backed by a deterministic academic registry in this environment.",
                reason_codes=["ACADEMIC_ISSUER_NOT_CONFIGURED"],
                extra_summary={"issuer_hint": institution},
            )

        return self.build_partial_result(
            task,
            credential,
            explanation="Academic data exists, but issuer evidence is incomplete for a stronger verification result.",
            reason_codes=["ACADEMIC_EVIDENCE_INCOMPLETE"],
        )

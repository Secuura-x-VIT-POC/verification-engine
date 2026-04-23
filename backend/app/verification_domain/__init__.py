from __future__ import annotations

from importlib import import_module

from .contracts import (
    ANALYSIS_STATUS_AUDITS_ASSEMBLED,
    ANALYSIS_STATUS_CREDENTIALS_BUILT,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_NOT_STARTED,
    ANALYSIS_STATUS_PLAN_BUILT,
    ANALYSIS_STATUS_PROFILED,
    ANALYSIS_STATUS_READY,
    AUDIT_STATUS_MANUAL_REVIEW,
    AUDIT_STATUS_MISMATCH,
    AUDIT_STATUS_NOT_APPLICABLE,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_UNVERIFIED,
    AUDIT_STATUS_VERIFIED,
    BoundingBox,
    CredentialAudit,
    CredentialAuditCollection,
    DocumentProfile,
    DocumentVerificationSummary,
    EvidenceItem,
    ExtractedCredential,
    SessionAnalysisStatus,
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
    VerifierRouteDecision,
)


_LAZY_IMPORTS = {
    "RuleBasedVerifierRouter": (".routing", "RuleBasedVerifierRouter"),
    "VerifierRouter": (".routing", "VerifierRouter"),
    "adapt_session_to_credential_audits": (".adapters", "adapt_session_to_credential_audits"),
    "adapt_session_to_credentials": (".adapters", "adapt_session_to_credentials"),
    "adapt_session_to_verification_plan": (".adapters", "adapt_session_to_verification_plan"),
    "adapt_session_to_verification_summary": (".adapters", "adapt_session_to_verification_summary"),
    "assemble_credential_audits": (".service", "assemble_credential_audits"),
    "build_credentials": (".service", "build_credentials"),
    "build_document_profile": (".service", "build_document_profile"),
    "build_extracted_credentials": (".planner", "build_extracted_credentials"),
    "build_verification_plan": (".service", "build_verification_plan"),
    "build_verification_summary": (".service", "build_verification_summary"),
    "classify_credential_category": (".planner", "classify_credential_category"),
    "get_analysis_status_for_session": (".service", "get_analysis_status_for_session"),
    "get_credential_audits_for_session": (".service", "get_credential_audits_for_session"),
    "get_credentials_for_session": (".service", "get_credentials_for_session"),
    "get_document_profile_for_session": (".service", "get_document_profile_for_session"),
    "get_verification_plan_for_session": (".service", "get_verification_plan_for_session"),
    "get_verification_summary_for_session": (".service", "get_verification_summary_for_session"),
    "mark_analysis_failure": (".service", "mark_analysis_failure"),
    "persist_analysis_artifacts": (".service", "persist_analysis_artifacts"),
}


def __getattr__(name: str):
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    module = import_module(module_name, __name__)
    value = getattr(module, attribute)
    globals()[name] = value
    return value


__all__ = [
    "ANALYSIS_STATUS_AUDITS_ASSEMBLED",
    "ANALYSIS_STATUS_CREDENTIALS_BUILT",
    "ANALYSIS_STATUS_FAILED",
    "ANALYSIS_STATUS_NOT_STARTED",
    "ANALYSIS_STATUS_PLAN_BUILT",
    "ANALYSIS_STATUS_PROFILED",
    "ANALYSIS_STATUS_READY",
    "AUDIT_STATUS_MANUAL_REVIEW",
    "AUDIT_STATUS_MISMATCH",
    "AUDIT_STATUS_NOT_APPLICABLE",
    "AUDIT_STATUS_PARTIAL",
    "AUDIT_STATUS_UNVERIFIED",
    "AUDIT_STATUS_VERIFIED",
    "BoundingBox",
    "CredentialAudit",
    "CredentialAuditCollection",
    "DocumentProfile",
    "DocumentVerificationSummary",
    "EvidenceItem",
    "ExtractedCredential",
    "RuleBasedVerifierRouter",
    "SessionAnalysisStatus",
    "SessionCredentialCollection",
    "SessionVerificationPlan",
    "VerificationTask",
    "VerifierRouteDecision",
    "VerifierRouter",
    "adapt_session_to_credential_audits",
    "adapt_session_to_credentials",
    "adapt_session_to_verification_plan",
    "adapt_session_to_verification_summary",
    "assemble_credential_audits",
    "build_credentials",
    "build_extracted_credentials",
    "build_document_profile",
    "build_verification_plan",
    "build_verification_summary",
    "classify_credential_category",
    "get_analysis_status_for_session",
    "get_credential_audits_for_session",
    "get_credentials_for_session",
    "get_document_profile_for_session",
    "get_verification_plan_for_session",
    "get_verification_summary_for_session",
    "mark_analysis_failure",
    "persist_analysis_artifacts",
]

from __future__ import annotations

from importlib import import_module

from .contracts import (
    EXECUTION_STATUS_FAILED,
    EXECUTION_STATUS_NOT_STARTED,
    EXECUTION_STATUS_READY,
    EXECUTION_STATUS_RUNNING,
    TASK_STATUS_FAILED,
    TASK_STATUS_MANUAL_REVIEW,
    TASK_STATUS_PARTIAL,
    TASK_STATUS_SKIPPED,
    TASK_STATUS_SUCCEEDED,
    CredentialVerificationBundle,
    CredentialVerificationBundleCollection,
    SessionVerificationExecutionStatus,
    SessionVerificationExecutionSummary,
    VerificationTaskResult,
    VerificationTaskResultCollection,
)


_LAZY_IMPORTS = {
    "VerificationTaskExecutor": (".executor", "VerificationTaskExecutor"),
    "VerifierRegistry": (".registry", "VerifierRegistry"),
    "build_default_verifier_registry": (".registry", "build_default_verifier_registry"),
    "build_execution_artifacts": (".service", "build_execution_artifacts"),
    "get_credential_bundles_for_session": (".service", "get_credential_bundles_for_session"),
    "get_verification_execution_status_for_session": (".service", "get_verification_execution_status_for_session"),
    "get_verification_execution_summary_for_session": (".service", "get_verification_execution_summary_for_session"),
    "get_verification_task_results_for_session": (".service", "get_verification_task_results_for_session"),
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
    "CredentialVerificationBundle",
    "CredentialVerificationBundleCollection",
    "EXECUTION_STATUS_FAILED",
    "EXECUTION_STATUS_NOT_STARTED",
    "EXECUTION_STATUS_READY",
    "EXECUTION_STATUS_RUNNING",
    "SessionVerificationExecutionStatus",
    "SessionVerificationExecutionSummary",
    "TASK_STATUS_FAILED",
    "TASK_STATUS_MANUAL_REVIEW",
    "TASK_STATUS_PARTIAL",
    "TASK_STATUS_SKIPPED",
    "TASK_STATUS_SUCCEEDED",
    "VerificationTaskExecutor",
    "VerificationTaskResult",
    "VerificationTaskResultCollection",
    "VerifierRegistry",
    "build_default_verifier_registry",
    "build_execution_artifacts",
    "get_credential_bundles_for_session",
    "get_verification_execution_status_for_session",
    "get_verification_execution_summary_for_session",
    "get_verification_task_results_for_session",
]

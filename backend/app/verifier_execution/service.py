from __future__ import annotations

import logging
from typing import Any

from ..verifier_providers import ProviderExecutionRuntime
from ..verification_domain.adapters import build_session_credentials, build_session_verification_plan
from ..verification_domain.contracts import SessionCredentialCollection, SessionVerificationPlan
from .adapters import build_execution_context
from .contracts import (
    EXECUTION_STATUS_FAILED,
    EXECUTION_STATUS_NOT_STARTED,
    EXECUTION_STATUS_READY,
    CredentialVerificationBundleCollection,
    SessionVerificationExecutionStatus,
    SessionVerificationExecutionSummary,
    VerificationTaskResultCollection,
)
from .executor import VerificationTaskExecutor
from .registry import VerifierRegistry


LOGGER = logging.getLogger(__name__)


def build_execution_artifacts(
    session_id: str,
    extraction_payload: dict[str, Any] | None,
    *,
    connector_payload: Any = None,
    trust_outcome: str | None = None,
    reason_codes: list[str] | None = None,
    credentials: SessionCredentialCollection | None = None,
    verification_plan: SessionVerificationPlan | None = None,
    registry: VerifierRegistry | None = None,
    provider_runtime: ProviderExecutionRuntime | None = None,
) -> dict[str, Any]:
    credential_collection = credentials or build_session_credentials(session_id, extraction_payload)
    plan = verification_plan or build_session_verification_plan(
        session_id,
        extraction_payload,
        credentials=credential_collection,
    )
    runtime = provider_runtime or ProviderExecutionRuntime()
    context = build_execution_context(
        session_id=session_id,
        document_type=credential_collection.document_type,
        extraction_payload=extraction_payload,
        connector_payload=connector_payload,
        trust_outcome=trust_outcome,
        reason_codes=reason_codes,
        provider_runtime=runtime,
    )
    executor = VerificationTaskExecutor(registry=registry)
    artifacts = executor.execute_plan(
        credential_collection=credential_collection,
        verification_plan=plan,
        context=context,
    )
    artifacts["provider_execution_traces"] = runtime.build_trace_collection(
        session_id=session_id,
        document_type=credential_collection.document_type,
    )
    artifacts["provider_execution_status"] = runtime.infer_status()
    artifacts["provider_execution_error"] = runtime.error
    artifacts["provider_operating_mode"] = runtime.operating_context.provider_operating_mode
    artifacts["demo_profile_key"] = runtime.operating_context.demo_profile_key
    artifacts["execution_environment_label"] = runtime.operating_context.execution_environment_label
    artifacts["provider_transition_notes"] = list(runtime.operating_context.provider_transition_notes)
    return artifacts


def get_verification_task_results_for_session(session) -> VerificationTaskResultCollection:
    persisted = _load_model(VerificationTaskResultCollection, session.verification_task_results_payload)
    if persisted is not None:
        return persisted
    return build_execution_artifacts(
        session.id,
        session.extraction_payload,
        connector_payload=session.connector_payload,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        credentials=_load_model(SessionCredentialCollection, getattr(session, "generalized_credentials_payload", None)),
        verification_plan=_load_model(SessionVerificationPlan, getattr(session, "verification_plan_payload", None)),
    )["task_results"]


def get_credential_bundles_for_session(session) -> CredentialVerificationBundleCollection:
    persisted = _load_model(CredentialVerificationBundleCollection, session.credential_verification_bundles_payload)
    if persisted is not None:
        return persisted
    return build_execution_artifacts(
        session.id,
        session.extraction_payload,
        connector_payload=session.connector_payload,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        credentials=_load_model(SessionCredentialCollection, getattr(session, "generalized_credentials_payload", None)),
        verification_plan=_load_model(SessionVerificationPlan, getattr(session, "verification_plan_payload", None)),
    )["credential_bundles"]


def get_verification_execution_summary_for_session(session) -> SessionVerificationExecutionSummary:
    persisted = _load_model(SessionVerificationExecutionSummary, session.verification_execution_summary_payload)
    if persisted is not None:
        return persisted
    return build_execution_artifacts(
        session.id,
        session.extraction_payload,
        connector_payload=session.connector_payload,
        trust_outcome=session.trust_outcome,
        reason_codes=list(session.reason_codes or []),
        credentials=_load_model(SessionCredentialCollection, getattr(session, "generalized_credentials_payload", None)),
        verification_plan=_load_model(SessionVerificationPlan, getattr(session, "verification_plan_payload", None)),
    )["execution_summary"]


def get_verification_execution_status_for_session(session) -> SessionVerificationExecutionStatus:
    return SessionVerificationExecutionStatus(
        session_id=session.id,
        workflow_state=session.status,
        verification_execution_status=_infer_execution_status(session),
        verification_execution_error=session.verification_execution_error,
        task_results_available=bool(session.verification_task_results_payload) or bool(session.extraction_payload),
        credential_bundles_available=bool(session.credential_verification_bundles_payload) or bool(session.extraction_payload),
        verification_execution_summary_available=bool(session.verification_execution_summary_payload)
        or bool(session.extraction_payload),
    )


def _infer_execution_status(session) -> str:
    if session.verification_execution_status and (
        str(session.verification_execution_status) != EXECUTION_STATUS_NOT_STARTED
        or any(
            (
                session.verification_task_results_payload,
                session.credential_verification_bundles_payload,
                session.verification_execution_summary_payload,
            )
        )
        or not session.extraction_payload
    ):
        return str(session.verification_execution_status)
    if session.verification_execution_error:
        return EXECUTION_STATUS_FAILED
    if session.verification_execution_summary_payload:
        return EXECUTION_STATUS_READY
    if session.verification_task_results_payload or session.credential_verification_bundles_payload:
        return EXECUTION_STATUS_READY
    if session.extraction_payload and (
        session.connector_payload is not None
        or session.trust_outcome is not None
        or bool(session.reason_codes)
    ):
        return EXECUTION_STATUS_READY
    return EXECUTION_STATUS_NOT_STARTED


def _load_model(model_cls, payload: Any):
    if payload in (None, ""):
        return None
    try:
        if hasattr(model_cls, "model_validate"):
            return model_cls.model_validate(payload)
        return model_cls.parse_obj(payload)
    except Exception:
        LOGGER.warning(
            "VERIFICATION_EXECUTION_LOAD_FAILED model=%s",
            getattr(model_cls, "__name__", str(model_cls)),
            exc_info=True,
        )
        return None

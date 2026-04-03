from __future__ import annotations

from abc import ABC, abstractmethod

from ...verification_domain.contracts import (
    AUDIT_STATUS_MANUAL_REVIEW,
    AUDIT_STATUS_MISMATCH,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_UNVERIFIED,
    AUDIT_STATUS_VERIFIED,
    OUTCOME_COLOR_AMBER,
    OUTCOME_COLOR_GREEN,
    OUTCOME_COLOR_RED,
    ExtractedCredential,
    VerificationTask,
)
from ...verifier_providers import (
    PROVIDER_TECHNICAL_STATUS_SUCCESS,
    PROVIDER_TECHNICAL_STATUS_TIMEOUT,
)
from ..adapters import (
    VerificationExecutionContext,
    document_confidence,
    find_connector_claim_evidence,
    has_grounding,
    summarize_result,
)
from ..contracts import (
    TASK_STATUS_MANUAL_REVIEW,
    TASK_STATUS_PARTIAL,
    TASK_STATUS_SUCCEEDED,
    VerificationTaskResult,
)


class CredentialVerifier(ABC):
    verifier_key = ""
    verifier_label = ""

    @abstractmethod
    def execute(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult:
        ...

    def build_result(
        self,
        *,
        task: VerificationTask,
        credential: ExtractedCredential,
        task_status: str,
        audit_status: str,
        outcome_color: str,
        explanation: str,
        reason_codes: list[str] | None = None,
        matched_fields: dict | None = None,
        mismatched_fields: dict | None = None,
        missing_fields: list[str] | None = None,
        raw_result_summary: dict | None = None,
        confidence: float | None = None,
        manual_review_recommended: bool = False,
    ) -> VerificationTaskResult:
        return VerificationTaskResult(
            task_id=task.task_id,
            credential_id=credential.credential_id,
            verifier_key=task.verifier_key,
            verifier_label=task.verifier_label,
            task_status=task_status,
            audit_status=audit_status,
            outcome_color=outcome_color,
            explanation=explanation,
            reason_codes=list(reason_codes or []),
            matched_fields=dict(matched_fields or {}),
            mismatched_fields=dict(mismatched_fields or {}),
            missing_fields=list(missing_fields or []),
            raw_result_summary=dict(raw_result_summary or {}),
            confidence=confidence if confidence is not None else document_confidence(credential),
            manual_review_recommended=manual_review_recommended,
        )


class ConnectorAwareVerifier(CredentialVerifier):
    def execute(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult:
        claim_evidence = find_connector_claim_evidence(context.connector_payload, credential)
        connector = claim_evidence["connector"]
        matched_fields = claim_evidence["matched_fields"]
        mismatched_fields = claim_evidence["mismatched_fields"]

        if mismatched_fields:
            reason_codes = list(connector.get("reason_codes") or ["CONNECTOR_MISMATCH"])
            return self.build_result(
                task=task,
                credential=credential,
                task_status=TASK_STATUS_SUCCEEDED,
                audit_status=AUDIT_STATUS_MISMATCH,
                outcome_color=OUTCOME_COLOR_RED,
                explanation=f"{task.verifier_label} found contradictory evidence for this credential.",
                reason_codes=reason_codes,
                matched_fields=matched_fields,
                mismatched_fields=mismatched_fields,
                raw_result_summary=summarize_result(
                    execution_mode="connector_mismatch",
                    task=task,
                    credential=credential,
                    connector=connector,
                    matched_fields=matched_fields,
                    mismatched_fields=mismatched_fields,
                ),
            )

        if matched_fields:
            reason_codes = list(connector.get("reason_codes") or ["CONNECTOR_VERIFIED"])
            return self.build_result(
                task=task,
                credential=credential,
                task_status=TASK_STATUS_SUCCEEDED,
                audit_status=AUDIT_STATUS_VERIFIED,
                outcome_color=OUTCOME_COLOR_GREEN,
                explanation=f"{task.verifier_label} matched document evidence for this credential.",
                reason_codes=reason_codes,
                matched_fields=matched_fields,
                raw_result_summary=summarize_result(
                    execution_mode="connector_match",
                    task=task,
                    credential=credential,
                    connector=connector,
                    matched_fields=matched_fields,
                ),
            )

        provider_result = self._execute_via_provider(task, credential, context)
        if provider_result is not None:
            return provider_result

        return self.execute_without_connector(task, credential, context)

    @abstractmethod
    def execute_without_connector(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult:
        ...

    def build_partial_result(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        *,
        explanation: str,
        reason_codes: list[str],
        extra_summary: dict | None = None,
    ) -> VerificationTaskResult:
        return self.build_result(
            task=task,
            credential=credential,
            task_status=TASK_STATUS_PARTIAL,
            audit_status=AUDIT_STATUS_PARTIAL,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation=explanation,
            reason_codes=reason_codes,
            raw_result_summary=summarize_result(
                execution_mode="rule_only_partial",
                task=task,
                credential=credential,
                extra=extra_summary,
            ),
        )

    def build_manual_review_result(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        *,
        explanation: str,
        reason_codes: list[str],
        extra_summary: dict | None = None,
    ) -> VerificationTaskResult:
        return self.build_result(
            task=task,
            credential=credential,
            task_status=TASK_STATUS_MANUAL_REVIEW,
            audit_status=AUDIT_STATUS_MANUAL_REVIEW,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation=explanation,
            reason_codes=reason_codes,
            missing_fields=[credential.label],
            raw_result_summary=summarize_result(
                execution_mode="manual_review",
                task=task,
                credential=credential,
                extra=extra_summary,
            ),
            manual_review_recommended=True,
        )

    def build_unverified_result(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        *,
        explanation: str,
        reason_codes: list[str],
        extra_summary: dict | None = None,
    ) -> VerificationTaskResult:
        return self.build_result(
            task=task,
            credential=credential,
            task_status=TASK_STATUS_PARTIAL,
            audit_status=AUDIT_STATUS_UNVERIFIED,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation=explanation,
            reason_codes=reason_codes,
            missing_fields=[credential.label],
            raw_result_summary=summarize_result(
                execution_mode="rule_only_unverified",
                task=task,
                credential=credential,
                extra=extra_summary,
            ),
        )

    def has_strong_document_signal(self, credential: ExtractedCredential) -> bool:
        return document_confidence(credential) >= 0.75 and has_grounding(credential)

    def build_provider_input_payload(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> dict:
        payload = {
            "credential_id": credential.credential_id,
            "label": credential.label,
            "category": credential.category,
            "value": credential.normalized_value or credential.value,
            "page": credential.page,
            "document_type": context.document_type,
            "task_reason_codes": list(task.reason_codes or []),
            "verification_type": task.verification_type,
        }
        if isinstance(task.input_payload, dict):
            payload.update(task.input_payload)
        if context.extraction_payload:
            fields = dict(context.extraction_payload.get("fields") or {})
            institution = fields.get("institution")
            if isinstance(institution, dict):
                institution = institution.get("value")
            if institution:
                payload["institution"] = institution
        return payload

    def _execute_via_provider(
        self,
        task: VerificationTask,
        credential: ExtractedCredential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult | None:
        runtime = getattr(context, "provider_runtime", None)
        if runtime is None:
            return None

        provider_input_payload = self.build_provider_input_payload(task, credential, context)
        preferred_provider_key = None
        if isinstance(task.input_payload, dict):
            preferred_provider_key = (
                task.input_payload.get("planned_provider_key")
                or task.input_payload.get("preferred_provider_key")
            )

        attempt = runtime.attempt_verification(
            session_id=context.session_id,
            verifier_key=task.verifier_key,
            verifier_label=task.verifier_label,
            category=credential.category,
            task_id=task.task_id,
            input_payload=provider_input_payload,
            preferred_provider_key=preferred_provider_key,
        )
        if attempt is None:
            return None

        response = attempt.response
        if response.technical_status == PROVIDER_TECHNICAL_STATUS_SUCCESS:
            return self._build_successful_provider_result(
                task=task,
                credential=credential,
                provider_key=attempt.provider_key,
                provider_label=attempt.provider_label,
                response=response,
            )

        fallback_result = self.execute_without_connector(task, credential, context)
        runtime.mark_fallback_used(attempt.trace.request_id)
        fallback_result.explanation = (
            f"{fallback_result.explanation} "
            f"Provider attempt via {attempt.provider_label} failed safely and local fallback logic was used."
        ).strip()
        fallback_result.reason_codes = _dedupe(
            list(fallback_result.reason_codes or [])
            + list(response.reason_codes or [])
            + ["PROVIDER_FALLBACK_USED", f"PROVIDER_STATUS_{response.technical_status}"]
        )
        raw_summary = dict(fallback_result.raw_result_summary or {})
        raw_summary.update(
            {
                "provider_key": attempt.provider_key,
                "provider_label": attempt.provider_label,
                "provider_technical_status": response.technical_status,
                "provider_http_status": response.http_status,
                "provider_latency_ms": response.latency_ms,
                "provider_response_summary": dict(response.response_summary or {}),
                "provider_operating_mode": response.operating_mode,
                "provider_demo_profile_key": response.demo_profile_key,
                "provider_execution_environment_label": response.execution_environment_label,
                "provider_transition_notes": list(response.transition_notes or []),
                "provider_is_demo_result": response.is_demo_result,
                "provider_is_live_result": response.is_live_result,
                "provider_fallback_used": True,
            }
        )
        fallback_result.raw_result_summary = raw_summary
        if response.technical_status == PROVIDER_TECHNICAL_STATUS_TIMEOUT:
            fallback_result.manual_review_recommended = True
        return fallback_result

    def _build_successful_provider_result(
        self,
        *,
        task: VerificationTask,
        credential: ExtractedCredential,
        provider_key: str,
        provider_label: str,
        response,
    ) -> VerificationTaskResult:
        matched_fields = dict(response.matched_fields or {})
        mismatched_fields = dict(response.mismatched_fields or {})
        missing_fields = list(response.missing_fields or [])
        raw_summary = summarize_result(
            execution_mode="provider_response",
            task=task,
            credential=credential,
            extra={
                "provider_key": provider_key,
                "provider_label": provider_label,
                "provider_technical_status": response.technical_status,
                "provider_http_status": response.http_status,
                "provider_latency_ms": response.latency_ms,
                "provider_response_summary": dict(response.response_summary or {}),
                "provider_operating_mode": response.operating_mode,
                "provider_demo_profile_key": response.demo_profile_key,
                "provider_execution_environment_label": response.execution_environment_label,
                "provider_transition_notes": list(response.transition_notes or []),
                "provider_is_demo_result": response.is_demo_result,
                "provider_is_live_result": response.is_live_result,
            },
        )

        if mismatched_fields:
            return self.build_result(
                task=task,
                credential=credential,
                task_status=TASK_STATUS_SUCCEEDED,
                audit_status=AUDIT_STATUS_MISMATCH,
                outcome_color=OUTCOME_COLOR_RED,
                explanation=f"{task.verifier_label} received contradictory external evidence from {provider_label}.",
                reason_codes=_dedupe(list(response.reason_codes or []) + ["PROVIDER_MISMATCH"]),
                matched_fields=matched_fields,
                mismatched_fields=mismatched_fields,
                missing_fields=missing_fields,
                raw_result_summary=raw_summary,
                confidence=response.confidence,
                manual_review_recommended=response.manual_review_recommended,
            )

        if matched_fields and missing_fields:
            return self.build_result(
                task=task,
                credential=credential,
                task_status=TASK_STATUS_PARTIAL,
                audit_status=AUDIT_STATUS_PARTIAL,
                outcome_color=OUTCOME_COLOR_AMBER,
                explanation=f"{task.verifier_label} returned partial external evidence from {provider_label}.",
                reason_codes=_dedupe(list(response.reason_codes or []) + ["PROVIDER_PARTIAL_MATCH"]),
                matched_fields=matched_fields,
                missing_fields=missing_fields,
                raw_result_summary=raw_summary,
                confidence=response.confidence,
                manual_review_recommended=response.manual_review_recommended,
            )

        if matched_fields:
            return self.build_result(
                task=task,
                credential=credential,
                task_status=TASK_STATUS_SUCCEEDED,
                audit_status=AUDIT_STATUS_VERIFIED,
                outcome_color=OUTCOME_COLOR_GREEN,
                explanation=f"{task.verifier_label} matched external evidence via {provider_label}.",
                reason_codes=_dedupe(list(response.reason_codes or []) + ["PROVIDER_VERIFIED"]),
                matched_fields=matched_fields,
                raw_result_summary=raw_summary,
                confidence=response.confidence,
                manual_review_recommended=response.manual_review_recommended,
            )

        if response.manual_review_recommended:
            return self.build_result(
                task=task,
                credential=credential,
                task_status=TASK_STATUS_MANUAL_REVIEW,
                audit_status=AUDIT_STATUS_MANUAL_REVIEW,
                outcome_color=OUTCOME_COLOR_AMBER,
                explanation=f"{task.verifier_label} completed via {provider_label}, but the provider recommended manual review.",
                reason_codes=_dedupe(list(response.reason_codes or []) + ["PROVIDER_MANUAL_REVIEW"]),
                missing_fields=missing_fields or [credential.label],
                raw_result_summary=raw_summary,
                confidence=response.confidence,
                manual_review_recommended=True,
            )

        return self.build_result(
            task=task,
            credential=credential,
            task_status=TASK_STATUS_PARTIAL,
            audit_status=AUDIT_STATUS_UNVERIFIED,
            outcome_color=OUTCOME_COLOR_AMBER,
            explanation=f"{task.verifier_label} completed via {provider_label}, but no match evidence was returned.",
            reason_codes=_dedupe(list(response.reason_codes or []) + ["PROVIDER_NO_MATCH"]),
            missing_fields=missing_fields or [credential.label],
            raw_result_summary=raw_summary,
            confidence=response.confidence,
            manual_review_recommended=response.manual_review_recommended,
        )


def _dedupe(values: list[str]) -> list[str]:
    return [value for value in dict.fromkeys(values) if value]

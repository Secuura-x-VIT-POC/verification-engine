from __future__ import annotations

from datetime import datetime
from time import perf_counter

from ..verification_domain.contracts import (
    AUDIT_STATUS_MANUAL_REVIEW,
    AUDIT_STATUS_MISMATCH,
    AUDIT_STATUS_NOT_APPLICABLE,
    AUDIT_STATUS_PARTIAL,
    AUDIT_STATUS_UNVERIFIED,
    AUDIT_STATUS_VERIFIED,
    OUTCOME_COLOR_AMBER,
    OUTCOME_COLOR_NEUTRAL,
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
)
from .adapters import VerificationExecutionContext, summarize_result, task_execution_truth
from .contracts import (
    EXECUTION_STATUS_READY,
    CredentialVerificationBundle,
    CredentialVerificationBundleCollection,
    SessionVerificationExecutionSummary,
    TASK_STATUS_FAILED,
    TASK_STATUS_MANUAL_REVIEW,
    TASK_STATUS_PARTIAL,
    TASK_STATUS_SKIPPED,
    TASK_STATUS_SUCCEEDED,
    VerificationTaskResult,
    VerificationTaskResultCollection,
)
from .registry import VerifierRegistry, build_default_verifier_registry
from .verifiers.manual_review import ManualReviewVerifier


AUDIT_PRIORITY = {
    AUDIT_STATUS_MISMATCH: 60,
    AUDIT_STATUS_VERIFIED: 50,
    AUDIT_STATUS_PARTIAL: 40,
    AUDIT_STATUS_UNVERIFIED: 30,
    AUDIT_STATUS_MANUAL_REVIEW: 20,
    AUDIT_STATUS_NOT_APPLICABLE: 10,
}


class VerificationTaskExecutor:
    def __init__(self, registry: VerifierRegistry | None = None):
        self.registry = registry or build_default_verifier_registry()
        self._manual_review_verifier = self.registry.get("manual_review") or ManualReviewVerifier()

    def execute_plan(
        self,
        *,
        credential_collection: SessionCredentialCollection,
        verification_plan: SessionVerificationPlan,
        context: VerificationExecutionContext,
    ) -> dict[str, object]:
        started_at = datetime.utcnow()
        credential_lookup = {
            credential.credential_id: credential
            for credential in credential_collection.credentials
        }
        results: list[VerificationTaskResult] = []

        for task in verification_plan.tasks:
            result = self._execute_task(
                task=task,
                credential=credential_lookup.get(task.credential_id),
                context=context,
            )
            results.append(result)

        task_results = VerificationTaskResultCollection(
            session_id=credential_collection.session_id,
            document_type=credential_collection.document_type,
            results=results,
        )
        bundles = self._build_bundles(
            credential_collection=credential_collection,
            verification_plan=verification_plan,
            results=results,
        )
        completed_at = datetime.utcnow()
        summary = self._build_summary(
            session_id=credential_collection.session_id,
            results=results,
            started_at=started_at,
            completed_at=completed_at,
        )
        return {
            "task_results": task_results,
            "credential_bundles": bundles,
            "execution_summary": summary,
        }

    def _execute_task(
        self,
        *,
        task: VerificationTask,
        credential,
        context: VerificationExecutionContext,
    ) -> VerificationTaskResult:
        started = perf_counter()
        executed_at = datetime.utcnow()

        if credential is None:
            route_truth = task_execution_truth(task)
            result = VerificationTaskResult(
                task_id=task.task_id,
                credential_id=task.credential_id,
                verifier_key=task.verifier_key,
                verifier_label=task.verifier_label,
                preferred_provider_key=route_truth.get("preferred_provider_key"),
                preferred_provider_label=route_truth.get("preferred_provider_label"),
                planned_provider_key=route_truth.get("planned_provider_key"),
                planned_provider_label=route_truth.get("planned_provider_label"),
                execution_mode="EXECUTOR_FAILURE",
                fallback_reason=route_truth.get("fallback_reason"),
                task_status=TASK_STATUS_FAILED,
                audit_status=AUDIT_STATUS_MANUAL_REVIEW,
                outcome_color=OUTCOME_COLOR_AMBER,
                explanation="The verification plan references a credential that is not available in the current session view.",
                reason_codes=["MISSING_CREDENTIAL_REFERENCE"],
                missing_fields=[task.credential_id],
                raw_result_summary={**route_truth, "execution_mode": "EXECUTOR_FAILURE"},
                manual_review_recommended=True,
            )
            return self._stamp_result(result, executed_at=executed_at, started=started)

        verifier = self.registry.get(task.verifier_key)
        if verifier is None:
            result = self._manual_review_verifier.execute(task, credential, context)
            result.reason_codes = list(dict.fromkeys([*result.reason_codes, "VERIFIER_NOT_REGISTERED"]))
            summary = dict(result.raw_result_summary)
            summary["requested_verifier_key"] = task.verifier_key
            result.raw_result_summary = summary
            return self._stamp_result(result, executed_at=executed_at, started=started)

        try:
            result = verifier.execute(task, credential, context)
        except Exception as exc:  # pragma: no cover - defensive
            route_truth = task_execution_truth(task)
            result = VerificationTaskResult(
                task_id=task.task_id,
                credential_id=credential.credential_id,
                verifier_key=task.verifier_key,
                verifier_label=task.verifier_label,
                preferred_provider_key=route_truth.get("preferred_provider_key"),
                preferred_provider_label=route_truth.get("preferred_provider_label"),
                planned_provider_key=route_truth.get("planned_provider_key"),
                planned_provider_label=route_truth.get("planned_provider_label"),
                execution_mode="EXECUTION_FAILURE",
                fallback_reason=route_truth.get("fallback_reason"),
                task_status=TASK_STATUS_FAILED,
                audit_status=AUDIT_STATUS_MANUAL_REVIEW,
                outcome_color=OUTCOME_COLOR_AMBER,
                explanation=f"Verifier execution failed: {exc}",
                reason_codes=["VERIFIER_EXECUTION_FAILED"],
                missing_fields=[credential.label],
                raw_result_summary=summarize_result(
                    execution_mode="EXECUTION_FAILURE",
                    task=task,
                    credential=credential,
                    extra={"error": str(exc)},
                ),
                manual_review_recommended=True,
            )
        return self._stamp_result(result, executed_at=executed_at, started=started)

    def _build_bundles(
        self,
        *,
        credential_collection: SessionCredentialCollection,
        verification_plan: SessionVerificationPlan,
        results: list[VerificationTaskResult],
    ) -> CredentialVerificationBundleCollection:
        results_by_credential: dict[str, list[VerificationTaskResult]] = {}
        for result in results:
            results_by_credential.setdefault(result.credential_id, []).append(result)

        task_ids_by_credential: dict[str, list[str]] = {}
        for task in verification_plan.tasks:
            task_ids_by_credential.setdefault(task.credential_id, []).append(task.task_id)

        bundles = []
        for credential in credential_collection.credentials:
            credential_results = results_by_credential.get(credential.credential_id, [])
            if credential_results:
                best_result = max(
                    credential_results,
                    key=lambda item: (
                        AUDIT_PRIORITY.get(item.audit_status, 0),
                        1 if item.task_status == TASK_STATUS_SUCCEEDED else 0,
                        item.confidence or 0.0,
                    ),
                )
                final_status = best_result.audit_status
                final_color = best_result.outcome_color
                explanation = best_result.explanation
                reason_codes = list(
                    dict.fromkeys(
                        code
                        for result in credential_results
                        for code in result.reason_codes
                        if code
                    )
                )
            else:
                best_result = None
                if credential.requires_verification:
                    final_status = AUDIT_STATUS_UNVERIFIED
                    final_color = OUTCOME_COLOR_AMBER
                    explanation = "A verification result was not produced for this credential."
                    reason_codes = ["NO_TASK_RESULT"]
                else:
                    final_status = AUDIT_STATUS_NOT_APPLICABLE
                    final_color = OUTCOME_COLOR_NEUTRAL
                    explanation = "No verification task was selected for this credential."
                    reason_codes = ["VERIFICATION_NOT_REQUIRED"]

            bundles.append(
                CredentialVerificationBundle(
                    credential_id=credential.credential_id,
                    label=credential.label,
                    category=credential.category,
                    selected_task_ids=task_ids_by_credential.get(credential.credential_id, []),
                    result_count=len(credential_results),
                    final_audit_status=final_status,
                    final_outcome_color=final_color,
                    explanation=explanation,
                    reason_codes=reason_codes,
                    best_result=best_result,
                    all_results=credential_results,
                )
            )

        return CredentialVerificationBundleCollection(
            session_id=credential_collection.session_id,
            document_type=credential_collection.document_type,
            bundles=bundles,
        )

    def _build_summary(
        self,
        *,
        session_id: str,
        results: list[VerificationTaskResult],
        started_at: datetime,
        completed_at: datetime,
    ) -> SessionVerificationExecutionSummary:
        succeeded_tasks = sum(1 for result in results if result.task_status == TASK_STATUS_SUCCEEDED)
        partial_tasks = sum(1 for result in results if result.task_status == TASK_STATUS_PARTIAL)
        failed_tasks = sum(1 for result in results if result.task_status == TASK_STATUS_FAILED)
        manual_review_tasks = sum(1 for result in results if result.task_status == TASK_STATUS_MANUAL_REVIEW)
        skipped_tasks = sum(1 for result in results if result.task_status == TASK_STATUS_SKIPPED)
        verifier_keys_used = sorted({result.verifier_key for result in results if result.verifier_key})

        return SessionVerificationExecutionSummary(
            session_id=session_id,
            total_tasks=len(results),
            succeeded_tasks=succeeded_tasks,
            partial_tasks=partial_tasks,
            failed_tasks=failed_tasks,
            manual_review_tasks=manual_review_tasks,
            skipped_tasks=skipped_tasks,
            overall_execution_status=EXECUTION_STATUS_READY,
            verifier_keys_used=verifier_keys_used,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _stamp_result(
        self,
        result: VerificationTaskResult,
        *,
        executed_at: datetime,
        started: float,
    ) -> VerificationTaskResult:
        if result.executed_at is None:
            result.executed_at = executed_at
        if result.latency_ms is None:
            result.latency_ms = max(int((perf_counter() - started) * 1000), 0)
        return result

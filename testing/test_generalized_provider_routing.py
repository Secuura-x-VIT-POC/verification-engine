from __future__ import annotations

import unittest

from backend.app.verification_domain.contracts import (
    ExtractedCredential,
    SessionCredentialCollection,
    SessionVerificationPlan,
    VerificationTask,
)
from backend.app.verifier_execution.service import build_execution_artifacts
from backend.app.workflow.task_planner import build_verification_tasks


def _academic_credential(*, value: str = "B.Tech", institution_hint: str = "VIT Vellore") -> ExtractedCredential:
    return ExtractedCredential(
        credential_id="degree",
        label=f"Degree from {institution_hint}",
        category="academic",
        value=value,
        normalized_value=value,
        confidence=0.91,
        requires_verification=True,
        verification_recommended=True,
    )


class GeneralizedProviderRoutingTests(unittest.TestCase):
    def test_vit_text_does_not_create_vit_substring_route(self):
        tasks = build_verification_tasks([_academic_credential()])

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].claim_type, "academic_degree")
        self.assertNotIn("vit_registry", tasks[0].provider_candidates)
        self.assertIn("CAPABILITY_ROUTED", tasks[0].reason_codes)

    def test_non_vit_academic_credential_gets_provider_candidates(self):
        tasks = build_verification_tasks([
            _academic_credential(institution_hint="State University")
        ])

        self.assertEqual(len(tasks), 1)
        self.assertTrue(tasks[0].provider_candidates)
        self.assertNotEqual(tasks[0].provider_candidates, ["local_mock_registry"])
        self.assertEqual(tasks[0].assurance_required, "HIGH")

    def test_executor_skips_missing_provider_and_tries_next_candidate(self):
        credential = _academic_credential(institution_hint="State University")
        plan_task = build_verification_tasks([credential])[0].model_copy(
            update={"provider_candidates": ["missing_provider", "local_mock"]}
        )
        artifacts = build_execution_artifacts(
            "session-routing",
            {"document_type": "academic_credential", "fields": {}},
            credentials=SessionCredentialCollection(
                session_id="session-routing",
                document_type="academic_credential",
                credentials=[credential],
            ),
            verification_plan=SessionVerificationPlan(
                session_id="session-routing",
                document_type="academic_credential",
                tasks=[plan_task],
            ),
        )

        result = artifacts["task_results"].results[0]
        self.assertEqual(result.raw_result_summary["attempted_provider_keys"], ["missing_provider", "local_mock"])
        self.assertIn("PROVIDER_NOT_REGISTERED", result.reason_codes)
        self.assertEqual(result.executed_provider_key, "local_mock")

    def test_executor_returns_amber_manual_review_when_all_providers_fail(self):
        credential = _academic_credential(institution_hint="State University")
        task = VerificationTask(
            task_id="verify-degree",
            credential_id=credential.credential_id,
            verifier_key="academic_registry",
            verifier_label="Academic Registry",
            verification_type="academic",
            required=True,
            claim_type="academic_degree",
            provider_candidates=["missing_provider"],
            required_fields=["holder_name", "institution", "degree", "issue_date"],
            assurance_required="HIGH",
        )
        artifacts = build_execution_artifacts(
            "session-all-fail",
            {"document_type": "academic_credential", "fields": {}},
            credentials=SessionCredentialCollection(
                session_id="session-all-fail",
                document_type="academic_credential",
                credentials=[credential],
            ),
            verification_plan=SessionVerificationPlan(
                session_id="session-all-fail",
                document_type="academic_credential",
                tasks=[task],
            ),
        )

        result = artifacts["task_results"].results[0]
        self.assertEqual(result.outcome_color, "amber")
        self.assertTrue(result.manual_review_recommended)
        self.assertIn("NO_PROVIDER_AVAILABLE", result.reason_codes)

    def test_workflow_result_bundle_is_not_empty_when_tasks_exist(self):
        credential = _academic_credential(institution_hint="State University")
        tasks = build_verification_tasks([credential])
        artifacts = build_execution_artifacts(
            "session-bundle",
            {"document_type": "academic_credential", "fields": {}},
            credentials=SessionCredentialCollection(
                session_id="session-bundle",
                document_type="academic_credential",
                credentials=[credential],
            ),
            verification_plan=SessionVerificationPlan(
                session_id="session-bundle",
                document_type="academic_credential",
                tasks=tasks,
            ),
        )

        self.assertTrue(tasks)
        self.assertTrue(artifacts["task_results"].results)
        self.assertTrue(artifacts["credential_bundles"].bundles)


if __name__ == "__main__":
    unittest.main()

import json
import os
import sys
import unittest


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.trust.findings import build_trust_findings


RAW_OCR_SECRET_PHASE6 = "RAW_OCR_SECRET_PHASE6"
RAW_CREDENTIAL_SECRET_PHASE6 = "RAW_CREDENTIAL_SECRET_PHASE6"
RAW_PROVIDER_BODY_PHASE6 = "RAW_PROVIDER_BODY_PHASE6"
RAW_GEMINI_SECRET_PHASE6 = "RAW_GEMINI_SECRET_PHASE6"
RAW_REASON_PRIVATE_PHASE6 = "RAW_REASON_PRIVATE_PHASE6"
RAW_MISSING_CLAIM_VALUE_PHASE6 = "RAW_MISSING_CLAIM_VALUE_PHASE6"
RAW_PROVIDER_BODY_REASON_PHASE6 = "RAW_PROVIDER_BODY_REASON_PHASE6"
RAW_GEMINI_REASON_PHASE6 = "RAW_GEMINI_REASON_PHASE6"


class Phase6TrustFindingsTests(unittest.TestCase):
    def test_verified_provider_result_maps_to_green_claim_finding(self):
        result = build_trust_findings(
            claims=[self._claim()],
            task_results=[
                self._task_result(
                    audit_status="VERIFIED",
                    outcome_color="green",
                    reason_codes=["PROVIDER_VERIFIED", "PROVIDER_VERIFIED"],
                    confidence=0.97,
                )
            ],
            required_claim_ids=["claim-name"],
        )

        finding = result.claim_findings[0]
        self.assertEqual(finding.status, "GREEN")
        self.assertFalse(finding.manual_review_required)
        self.assertEqual(finding.reason_codes, ["VERIFIED_BY_PROVIDER"])
        self.assertEqual(result.final_verdict.outcome, "GREEN")

    def test_mismatch_provider_result_maps_to_red_claim_finding(self):
        result = build_trust_findings(
            claims=[self._claim()],
            task_results=[
                self._task_result(
                    audit_status="MISMATCH",
                    outcome_color="red",
                    reason_codes=["PROVIDER_MISMATCH", "PROVIDER_MISMATCH"],
                    mismatched_fields={"name": RAW_CREDENTIAL_SECRET_PHASE6},
                    confidence=0.2,
                )
            ],
            required_claim_ids=["claim-name"],
        )

        finding = result.claim_findings[0]
        self.assertEqual(finding.status, "RED")
        self.assertFalse(finding.manual_review_required)
        self.assertEqual(finding.reason_codes, ["PROVIDER_MISMATCH"])
        self.assertEqual(result.final_verdict.outcome, "RED")

    def test_manual_review_no_provider_and_unavailable_provider_map_to_amber(self):
        cases = [
            (
                "manual",
                self._task_result(
                    task_id="task-manual",
                    audit_status="MANUAL_REVIEW",
                    task_status="MANUAL_REVIEW",
                    reason_codes=["MANUAL_REVIEW_REQUIRED"],
                    manual_review_recommended=True,
                ),
                "MANUAL_REVIEW_REQUIRED",
            ),
            (
                "missing_provider",
                self._task_result(
                    task_id="task-missing-provider",
                    audit_status="UNVERIFIED",
                    task_status="SKIPPED",
                    reason_codes=["NO_PROVIDER_AVAILABLE"],
                ),
                "NO_PROVIDER_AVAILABLE",
            ),
            (
                "unavailable",
                self._task_result(
                    task_id="task-unavailable",
                    audit_status="UNVERIFIED",
                    task_status="FAILED",
                    reason_codes=["PROVIDER_UNAVAILABLE"],
                ),
                "PROVIDER_UNAVAILABLE",
            ),
        ]

        for case_name, task_result, expected_code in cases:
            with self.subTest(case_name=case_name):
                result = build_trust_findings(
                    claims=[self._claim(claim_id=case_name)],
                    task_results=[task_result],
                    required_claim_ids=[case_name],
                )
                finding = result.claim_findings[0]
                self.assertEqual(finding.status, "AMBER")
                self.assertTrue(finding.manual_review_required)
                self.assertIn(expected_code, finding.reason_codes)
                self.assertEqual(result.final_verdict.outcome, "AMBER")

    def test_ai_only_high_confidence_without_verifier_evidence_never_green(self):
        result = build_trust_findings(
            claims=[
                self._claim(
                    confidence=1.0,
                    ai_confidence=1.0,
                    reason_codes=["AI_HIGH_CONFIDENCE"],
                )
            ],
            task_results=[],
            required_claim_ids=["claim-name"],
        )

        finding = result.claim_findings[0]
        self.assertEqual(finding.status, "AMBER")
        self.assertTrue(finding.manual_review_required)
        self.assertIn("AI_ONLY_EVIDENCE", finding.reason_codes)
        self.assertNotEqual(result.final_verdict.outcome, "GREEN")

    def test_overall_outcome_precedence_and_green_requires_verifier_evidence(self):
        red = build_trust_findings(
            claims=[self._claim("green"), self._claim("red")],
            task_results=[
                self._task_result(credential_id="green", audit_status="VERIFIED", outcome_color="green"),
                self._task_result(credential_id="red", audit_status="MISMATCH", outcome_color="red"),
            ],
            required_claim_ids=["green", "red"],
        )
        amber = build_trust_findings(
            claims=[self._claim("green"), self._claim("amber")],
            task_results=[
                self._task_result(credential_id="green", audit_status="VERIFIED", outcome_color="green"),
                self._task_result(credential_id="amber", audit_status="MANUAL_REVIEW", task_status="MANUAL_REVIEW"),
            ],
            required_claim_ids=["green", "amber"],
        )
        green = build_trust_findings(
            claims=[self._claim("green-1"), self._claim("green-2")],
            task_results=[
                self._task_result(credential_id="green-1", audit_status="VERIFIED", outcome_color="green"),
                self._task_result(credential_id="green-2", audit_status="VERIFIED", outcome_color="green"),
            ],
            required_claim_ids=["green-1", "green-2"],
        )
        ai_only = build_trust_findings(
            claims=[self._claim("ai-only", confidence=1.0)],
            task_results=[],
            required_claim_ids=["ai-only"],
        )

        self.assertEqual(red.final_verdict.outcome, "RED")
        self.assertEqual(amber.final_verdict.outcome, "AMBER")
        self.assertEqual(green.final_verdict.outcome, "GREEN")
        self.assertEqual(ai_only.final_verdict.outcome, "AMBER")

    def test_low_confidence_amber_requires_manual_review(self):
        result = build_trust_findings(
            claims=[self._claim(confidence=0.21, ai_confidence=0.21)],
            task_results=[],
            required_claim_ids=["claim-name"],
        )

        finding = result.claim_findings[0]
        self.assertEqual(finding.status, "AMBER")
        self.assertTrue(finding.manual_review_required)
        self.assertIn("LOW_CONFIDENCE_REVIEW_REQUIRED", finding.reason_codes)

    def test_final_findings_do_not_expose_raw_values_or_raw_bodies(self):
        result = build_trust_findings(
            claims=[
                {
                    **self._claim(),
                    "raw_value": RAW_CREDENTIAL_SECRET_PHASE6,
                    "extracted_value": RAW_CREDENTIAL_SECRET_PHASE6,
                    "normalized_value": RAW_CREDENTIAL_SECRET_PHASE6,
                    "source_text": RAW_OCR_SECRET_PHASE6,
                    "raw_ocr_text": RAW_OCR_SECRET_PHASE6,
                    "gemini_raw_response": RAW_GEMINI_SECRET_PHASE6,
                }
            ],
            task_results=[
                self._task_result(
                    audit_status="VERIFIED",
                    outcome_color="green",
                    raw_result_summary={
                        "raw_provider_body": RAW_PROVIDER_BODY_PHASE6,
                        "gemini_raw_response": RAW_GEMINI_SECRET_PHASE6,
                    },
                    matched_fields={"name": RAW_CREDENTIAL_SECRET_PHASE6},
                    explanation=f"Reviewer note: {RAW_CREDENTIAL_SECRET_PHASE6}",
                )
            ],
            required_claim_ids=["claim-name"],
        )

        serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)
        for secret in (
            RAW_OCR_SECRET_PHASE6,
            RAW_CREDENTIAL_SECRET_PHASE6,
            RAW_PROVIDER_BODY_PHASE6,
            RAW_GEMINI_SECRET_PHASE6,
        ):
            self.assertNotIn(secret, serialized)

        finding_payload = result.claim_findings[0].model_dump(mode="json")
        for forbidden_key in (
            "raw_value",
            "extracted_value",
            "normalized_value",
            "raw_result_summary",
            "raw_provider_body",
            "gemini_raw_response",
            "reviewer_note",
        ):
            self.assertNotIn(forbidden_key, finding_payload)

    def test_reason_codes_are_deduplicated_and_machine_safe(self):
        result = build_trust_findings(
            claims=[
                self._claim(
                    reason_codes=[
                        "PROVIDER_VERIFIED",
                        "PROVIDER_VERIFIED",
                        "",
                        None,
                        "manual review required",
                        RAW_REASON_PRIVATE_PHASE6,
                    ]
                )
            ],
            task_results=[
                self._task_result(
                    reason_codes=[
                        "PROVIDER_VERIFIED",
                        "provider unavailable",
                        RAW_PROVIDER_BODY_REASON_PHASE6,
                    ]
                )
            ],
            required_claim_ids=["claim-name"],
        )

        codes = result.claim_findings[0].reason_codes
        self.assertEqual(codes.count("VERIFIED_BY_PROVIDER"), 1)
        self.assertIn("MANUAL_REVIEW_REQUIRED", codes)
        self.assertIn("PROVIDER_UNAVAILABLE", codes)
        for code in codes:
            self.assertRegex(code, r"^[A-Z][A-Z0-9_]*$")
        serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)
        self.assertNotIn(RAW_REASON_PRIVATE_PHASE6, serialized)
        self.assertNotIn(RAW_PROVIDER_BODY_REASON_PHASE6, serialized)

    def test_empty_malformed_reason_codes_use_safe_fallbacks(self):
        result = build_trust_findings(
            claims=[self._claim(reason_codes=["", None, {"private": RAW_REASON_PRIVATE_PHASE6}])],
            task_results=[
                self._task_result(
                    audit_status="UNVERIFIED",
                    outcome_color="amber",
                    task_status="FAILED",
                    reason_codes=["", [], RAW_GEMINI_REASON_PHASE6],
                )
            ],
            required_claim_ids=["claim-name"],
        )

        finding = result.claim_findings[0]
        self.assertEqual(finding.status, "AMBER")
        self.assertTrue(finding.manual_review_required)
        self.assertIn("PROVIDER_UNAVAILABLE", finding.reason_codes)
        serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)
        self.assertNotIn(RAW_REASON_PRIVATE_PHASE6, serialized)
        self.assertNotIn(RAW_GEMINI_REASON_PHASE6, serialized)

    def test_missing_required_claim_produces_amber_finding(self):
        result = build_trust_findings(
            claims=[
                {
                    **self._claim("present-claim"),
                    "raw_value": RAW_MISSING_CLAIM_VALUE_PHASE6,
                }
            ],
            task_results=[
                self._task_result(
                    credential_id="present-claim",
                    audit_status="VERIFIED",
                    outcome_color="green",
                )
            ],
            required_claim_ids=["present-claim", "missing-claim"],
        )

        findings = {finding.credential_id: finding for finding in result.claim_findings}
        self.assertEqual(result.final_verdict.outcome, "AMBER")
        self.assertIn("missing-claim", findings)
        self.assertEqual(findings["missing-claim"].status, "AMBER")
        self.assertTrue(findings["missing-claim"].manual_review_required)
        self.assertIn("REQUIRED_CLAIM_MISSING", findings["missing-claim"].reason_codes)
        self.assertIn("MANUAL_REVIEW_REQUIRED", findings["missing-claim"].reason_codes)
        self.assertNotIn(RAW_MISSING_CLAIM_VALUE_PHASE6, json.dumps(result.model_dump(mode="json"), sort_keys=True))

    def test_empty_findings_and_no_evidence_cannot_produce_green(self):
        result = build_trust_findings(
            claims=[],
            task_results=[],
            required_claim_ids=["required-empty"],
        )

        self.assertEqual(result.final_verdict.outcome, "AMBER")
        self.assertEqual(result.finding_counts.green, 0)
        self.assertFalse(result.verifier_backed_evidence)
        self.assertEqual(result.claim_findings[0].credential_id, "required-empty")
        self.assertIn("REQUIRED_CLAIM_MISSING", result.claim_findings[0].reason_codes)

    def test_reviewer_safe_explanations_do_not_include_raw_values(self):
        cases = [
            (
                "green",
                self._task_result(explanation=f"Matched {RAW_CREDENTIAL_SECRET_PHASE6}"),
                "GREEN",
                "Verifier evidence matched this claim.",
            ),
            (
                "amber",
                self._task_result(
                    audit_status="UNVERIFIED",
                    outcome_color="amber",
                    task_status="FAILED",
                    explanation=f"Unavailable {RAW_PROVIDER_BODY_REASON_PHASE6}",
                ),
                "AMBER",
                "This claim requires manual review because verifier evidence is missing or unavailable.",
            ),
            (
                "red",
                self._task_result(
                    audit_status="MISMATCH",
                    outcome_color="red",
                    explanation=f"Mismatch {RAW_CREDENTIAL_SECRET_PHASE6}",
                ),
                "RED",
                "Verifier evidence contradicted this claim.",
            ),
        ]
        for name, task_result, status, explanation in cases:
            with self.subTest(name=name):
                result = build_trust_findings(
                    claims=[self._claim()],
                    task_results=[task_result],
                    required_claim_ids=["claim-name"],
                )
                finding = result.claim_findings[0]
                self.assertEqual(finding.status, status)
                self.assertEqual(finding.explanation, explanation)
                self.assertNotIn(RAW_CREDENTIAL_SECRET_PHASE6, finding.explanation)
                self.assertNotIn(RAW_PROVIDER_BODY_REASON_PHASE6, finding.explanation)

    def _claim(
        self,
        claim_id="claim-name",
        *,
        confidence=0.93,
        ai_confidence=None,
        reason_codes=None,
    ):
        return {
            "claim_id": claim_id,
            "credential_id": claim_id,
            "field_id": "field-name",
            "label": "Candidate name",
            "claim_type": "identity",
            "confidence": confidence,
            "ai_confidence": confidence if ai_confidence is None else ai_confidence,
            "bounding_boxes": [{"page": 1, "x0": 1, "y0": 2, "x1": 3, "y1": 4}],
            "reason_codes": list(reason_codes or []),
            "raw_value": RAW_CREDENTIAL_SECRET_PHASE6,
            "normalized_value": RAW_CREDENTIAL_SECRET_PHASE6,
            "source_text": RAW_OCR_SECRET_PHASE6,
        }

    def _task_result(
        self,
        *,
        task_id="task-name",
        credential_id="claim-name",
        audit_status="VERIFIED",
        outcome_color="green",
        task_status="SUCCEEDED",
        reason_codes=None,
        confidence=0.95,
        raw_result_summary=None,
        matched_fields=None,
        mismatched_fields=None,
        manual_review_recommended=False,
        explanation="Safe verifier summary.",
    ):
        return {
            "task_id": task_id,
            "credential_id": credential_id,
            "verifier_key": "identity_db",
            "verifier_label": "Identity Database",
            "executed_provider_key": "local_mock",
            "executed_provider_label": "Local Mock Provider",
            "task_status": task_status,
            "audit_status": audit_status,
            "outcome_color": outcome_color,
            "explanation": explanation,
            "reason_codes": list(reason_codes or ["PROVIDER_VERIFIED"]),
            "confidence": confidence,
            "raw_result_summary": raw_result_summary or {},
            "matched_fields": matched_fields or {},
            "mismatched_fields": mismatched_fields or {},
            "manual_review_recommended": manual_review_recommended,
        }


if __name__ == "__main__":
    unittest.main()

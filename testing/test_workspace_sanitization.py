import json
import os
import sys
import unittest


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.agent_orchestration.sanitization import sanitize_workspace_payload


class WorkspaceSanitizationTests(unittest.TestCase):
    def test_sanitizer_removes_unsafe_nested_keys_and_masks_values(self):
        payload = {
            "session_id": "session-1",
            "status": "AMBER",
            "ui_status": "COMPLETED",
            "document": {
                "filename": "demo.pdf",
                "document_type": "academic_credential",
                "page_count": 1,
                "used_ocr": True,
                "warnings": [],
                "highlights_count": 1,
                "raw_text": "raw pdf text should not leak",
                "full_ocr_text": "full OCR text should not leak",
            },
            "summary": {
                "total_fields": 1,
                "green_count": 0,
                "amber_count": 1,
                "red_count": 0,
                "matching_score": 0.4,
                "visual_match_probability": 0.5,
                "risk_level": "MEDIUM",
                "active_exceptions": [],
                "agent_private_notes": "private chain notes",
            },
            "fields": [
                {
                    "field_id": "name",
                    "label": "Candidate Name",
                    "extracted_value": "Student Demo",
                    "normalized_value": "student.demo@example.com",
                    "status": "AMBER",
                    "ai_confidence": 0.8,
                    "extraction_confidence": 0.9,
                    "verification_confidence": 0.3,
                    "grounding_confidence": 1.0,
                    "final_confidence": 0.6,
                    "reason_codes": ["LOW_CONFIDENCE_REVIEW_REQUIRED"],
                    "source_api": "local_mock",
                    "audit_message": "Needs review",
                    "bounding_boxes": [{"page": 1, "x0": 1, "y0": 2, "x1": 3, "y1": 4}],
                    "source_text": "Candidate Name: Student Demo",
                    "verifier_raw_evidence": {"response_body": "raw verifier response"},
                }
            ],
            "verifiers": [
                {
                    "connector_id": "local_mock",
                    "status": "ERROR",
                    "reason_codes": [],
                    "source_api": "local_mock",
                    "confidence": 0.3,
                    "optional": False,
                    "high_assurance": True,
                    "field_ids": ["name"],
                    "raw_response": {"secret": "raw provider body"},
                }
            ],
            "final_verdict": {
                "outcome": "AMBER",
                "reason_codes": [],
                "connector_ids": ["local_mock"],
                "explanation": "Review needed",
                "risk_level": "MEDIUM",
                "matching_score": 0.4,
                "visual_match_probability": 0.5,
                "generalized_analysis": {"raw": "agent output"},
            },
            "audit": [
                {
                    "stage": "agent",
                    "message": "Done",
                    "level": "INFO",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "agent_raw_output": "raw gemini output",
                    "full_prompt": "full prompt should not leak",
                    "full_response": "full response should not leak",
                    "gemini_raw_response": "raw gemini response should not leak",
                    "private_reasoning": "private reasoning should not leak",
                }
            ],
            "actions": [],
            "field_candidates": [{"source_text": "field candidate raw text"}],
            "spatial_text_map": ["raw layout text"],
            "evidence_lines": ["raw evidence line"],
            "provider_raw_response": "provider body",
            "raw_provider_body": "raw provider body sentinel",
            "provider_raw_body": "provider raw body sentinel",
            "raw_connector_response": "raw connector response sentinel",
            "raw_verifier_response": "raw verifier response sentinel",
            "full_provider_response": "full provider response sentinel",
            "raw_result_summary": {"secret": "raw result summary sentinel"},
            "request_body": "request body",
        }

        sanitized = sanitize_workspace_payload(payload)
        serialized = json.dumps(sanitized, sort_keys=True)

        for key in {
            "raw_text",
            "full_ocr_text",
            "source_text",
            "spatial_text_map",
            "evidence_lines",
            "field_candidates",
            "generalized_analysis",
            "agent_private_notes",
            "agent_raw_output",
            "verifier_raw_evidence",
            "raw_response",
            "response_body",
            "provider_raw_response",
            "raw_provider_body",
            "provider_raw_body",
            "raw_connector_response",
            "raw_verifier_response",
            "full_provider_response",
            "raw_result_summary",
            "request_body",
            "full_prompt",
            "full_response",
            "gemini_raw_response",
            "private_reasoning",
        }:
            self.assertNotIn(f'"{key}"', serialized)

        for raw_value in {
            "raw pdf text should not leak",
            "full OCR text should not leak",
            "Candidate Name: Student Demo",
            "raw verifier response",
            "raw provider body",
            "raw provider body sentinel",
            "provider raw body sentinel",
            "raw connector response sentinel",
            "raw verifier response sentinel",
            "full provider response sentinel",
            "raw result summary sentinel",
            "raw gemini output",
            "full prompt should not leak",
            "full response should not leak",
            "raw gemini response should not leak",
            "private reasoning should not leak",
            "student.demo@example.com",
            "Student Demo",
        }:
            self.assertNotIn(raw_value, serialized)

        field = sanitized["fields"][0]
        self.assertEqual(field["label"], "Candidate Name")
        self.assertEqual(field["status"], "AMBER")
        self.assertEqual(field["extraction_confidence"], 0.9)
        self.assertEqual(field["bounding_boxes"][0]["page"], 1)
        self.assertIn("***", field["extracted_value"])
        self.assertIn("***", field["normalized_value"])


if __name__ == "__main__":
    unittest.main()

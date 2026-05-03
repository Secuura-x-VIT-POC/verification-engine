import os
import sys
import unittest


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.security.redaction import (  # noqa: E402
    mask_email,
    mask_identifier,
    mask_name,
    redact_log_context,
    redact_value,
)


class LoggingRedactionTests(unittest.TestCase):
    def test_redact_value_matches_person_e_contract(self):
        self.assertEqual(redact_value("Sensitive Name", "HIGH"), "***REDACTED***")
        self.assertEqual(redact_value("ABCD", "MEDIUM"), "***")
        self.assertEqual(redact_value("ABCDEFG", "LOW"), "AB***FG")

    def test_specific_mask_helpers_keep_only_safe_preview(self):
        self.assertEqual(mask_identifier("1234 5678 9012"), "****9012")
        self.assertEqual(mask_email("alice@example.com"), "a***@example.com")
        self.assertEqual(mask_name("Alice Rao"), "A*** R***")

    def test_log_context_preserves_operational_fields_and_redacts_sensitive_payloads(self):
        payload = {
            "session_id": "session-1",
            "stage": "TRUST_SCORING",
            "status": "AMBER",
            "reason_code": "NO_VERIFIER_EVIDENCE",
            "provider_id": "local_mock",
            "duration_ms": 42,
            "raw_text": "RAW_TEXT_SENTINEL_PERSON_E",
            "request_body": {"id_number": "RAW_ID_NUMBER_SENTINEL_PERSON_E"},
            "reviewer_note": "RAW_REVIEWER_NOTE_SENTINEL_PERSON_E",
            "email": "alice@example.com",
        }

        redacted = redact_log_context(payload)
        serialized = str(redacted)

        self.assertEqual(redacted["session_id"], "session-1")
        self.assertEqual(redacted["stage"], "TRUST_SCORING")
        self.assertEqual(redacted["status"], "AMBER")
        self.assertEqual(redacted["reason_code"], "NO_VERIFIER_EVIDENCE")
        self.assertEqual(redacted["provider_id"], "local_mock")
        self.assertEqual(redacted["duration_ms"], 42)
        self.assertNotIn("RAW_TEXT_SENTINEL_PERSON_E", serialized)
        self.assertNotIn("RAW_ID_NUMBER_SENTINEL_PERSON_E", serialized)
        self.assertNotIn("RAW_REVIEWER_NOTE_SENTINEL_PERSON_E", serialized)
        self.assertNotIn("alice@example.com", serialized)


if __name__ == "__main__":
    unittest.main()

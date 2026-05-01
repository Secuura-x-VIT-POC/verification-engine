from __future__ import annotations

import unittest

from extraction.cross_field_validator import validate_cross_fields
from extraction.models import ExtractionSignals, FieldCandidate, Sensitivity, VerificationStatus


class CrossValidationTests(unittest.TestCase):
    def test_consistent_values_boost_confidence(self):
        candidates = [_candidate("CGPA", "8.5"), _candidate("CGPA", "8.5")]
        validated = validate_cross_fields(candidates)
        self.assertTrue(all(candidate.confidence > 0.8 for candidate in validated))

    def test_conflicting_values_mark_amber(self):
        candidates = [_candidate("CGPA", "8.5"), _candidate("CGPA", "9.1")]
        validated = validate_cross_fields(candidates)
        self.assertTrue(all(candidate.verification_status == VerificationStatus.AMBER for candidate in validated))


def _candidate(label: str, value: str) -> FieldCandidate:
    return FieldCandidate(
        field_id=f"{label}-{value}",
        label=label,
        raw_value=value,
        normalized_value=value,
        category="score",
        page=1,
        confidence=0.8,
        signals=ExtractionSignals(regex_score=0.8, semantic_score=0.7, ocr_confidence=0.95),
        is_pii=False,
        sensitivity=Sensitivity.LOW,
        requires_verification=True,
        source_text=f"{label}: {value}",
        extraction_method="native",
        detected_by=["regex"],
    )

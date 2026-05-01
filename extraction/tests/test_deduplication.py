from __future__ import annotations

import unittest

from extraction.deduplication import fuzzy_deduplicate
from extraction.models import ExtractionSignals, FieldCandidate, Sensitivity


class DeduplicationTests(unittest.TestCase):
    def test_exact_duplicates_removed(self):
        result = fuzzy_deduplicate([_candidate("CGPA", "8.5", 0.7), _candidate("CGPA", "8.5", 0.9)])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].confidence, 0.9)

    def test_generic_identifier_removed_when_specific_exists(self):
        result = fuzzy_deduplicate(
            [
                _candidate("Identifier", "21CSE001", 0.7, category="identifier"),
                _candidate("Roll Number", "21CSE001", 0.9, category="identifier"),
            ]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].label, "Roll Number")


def _candidate(label: str, value: str, confidence: float, *, category: str = "score") -> FieldCandidate:
    return FieldCandidate(
        field_id=f"{label}-{value}-{confidence}",
        label=label,
        raw_value=value,
        normalized_value=value,
        category=category,  # type: ignore[arg-type]
        page=1,
        confidence=confidence,
        signals=ExtractionSignals(regex_score=0.8, semantic_score=0.7, ocr_confidence=0.95),
        is_pii=False,
        sensitivity=Sensitivity.LOW,
        requires_verification=True,
        source_text=f"{label}: {value}",
        extraction_method="native",
        detected_by=["regex"],
    )

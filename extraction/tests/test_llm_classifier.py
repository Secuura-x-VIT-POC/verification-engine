from __future__ import annotations

import unittest

from extraction.llm_classifier import classify_candidate


class LLMClassifierTests(unittest.TestCase):
    def test_board_name_stays_institution(self):
        result = classify_candidate(label="Board Name", value="CBSE", context="Board Name: CBSE", llm_client=None)
        self.assertEqual(result["category"], "institution")

    def test_cgpa_maps_to_score(self):
        result = classify_candidate(label="CGPA", value="8.7", context="CGPA: 8.7", llm_client=None)
        self.assertEqual(result["category"], "score")

from __future__ import annotations

import unittest

from extraction.table_extractor import extract_from_tables


class TableExtractorTests(unittest.TestCase):
    def test_header_table_extraction(self):
        tables = {1: [[["Subject", "Marks", "Grade"], ["Mathematics", "85", "A"], ["Physics", "72", "B"]]]}
        candidates = extract_from_tables(tables)
        self.assertTrue(any("Marks" in candidate.label for candidate in candidates))

    def test_key_value_table_extraction(self):
        tables = {1: [[["Student Name", "John Smith"], ["Roll Number", "21CSE001"], ["CGPA", "8.75"]]]}
        candidates = extract_from_tables(tables)
        self.assertGreaterEqual(len(candidates), 3)

    def test_empty_table_safe(self):
        self.assertEqual(extract_from_tables({1: [[]]}), [])

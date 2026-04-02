#!/usr/bin/env python
"""Unit tests for sample catalog selection/deduplication."""

from __future__ import annotations

import unittest

from sample_catalog import resolve_sample_set


class SampleCatalogTests(unittest.TestCase):
    def test_sample_set_counts(self) -> None:
        baseline = resolve_sample_set("baseline")
        real = resolve_sample_set("real")
        real_priority = resolve_sample_set("real_priority")
        all_items = resolve_sample_set("all")
        self.assertEqual(len(baseline), 20)
        self.assertEqual(len(real), 91)
        self.assertEqual(len(all_items), 111)
        self.assertGreaterEqual(len(real_priority), 1)
        self.assertLessEqual(len(real_priority), len(real))

    def test_real_set_is_deduplicated(self) -> None:
        real = resolve_sample_set("real")
        names = [item.name for item in real]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all("(1)" not in name for name in names))
        self.assertTrue(all(item.step_path.suffix.lower() in {".stp", ".step"} for item in real))

    def test_real_priority_set_is_subset_of_real(self) -> None:
        real = {item.name for item in resolve_sample_set("real")}
        real_priority = resolve_sample_set("real_priority")
        self.assertTrue(real_priority)
        self.assertTrue(all(item.name in real for item in real_priority))


if __name__ == "__main__":
    unittest.main()

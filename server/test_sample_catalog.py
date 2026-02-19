#!/usr/bin/env python
"""Unit tests for sample catalog selection/deduplication."""

from __future__ import annotations

import unittest

from sample_catalog import resolve_sample_set


class SampleCatalogTests(unittest.TestCase):
    def test_sample_set_counts(self) -> None:
        baseline = resolve_sample_set("baseline")
        real = resolve_sample_set("real")
        all_items = resolve_sample_set("all")
        self.assertEqual(len(baseline), 20)
        self.assertEqual(len(real), 14)
        self.assertEqual(len(all_items), 34)

    def test_real_set_is_deduplicated(self) -> None:
        real = resolve_sample_set("real")
        names = [item.name for item in real]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all("(1)" not in name for name in names))
        self.assertTrue(all(item.step_path.suffix.lower() in {".stp", ".step"} for item in real))


if __name__ == "__main__":
    unittest.main()

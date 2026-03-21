from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
FREECAD_HELPER_DIR = SERVER_DIR / "freecad"
if str(FREECAD_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(FREECAD_HELPER_DIR))

from flat_pattern_helpers import build_flange_segment_metadata


class TestBuildFlangeSegmentMetadata(unittest.TestCase):
    def test_filters_positions_outside_outline(self):
        segments = build_flange_segment_metadata(
            [90.0, 120.0, 160.0],
            lower=100.0,
            upper=150.0,
            total_mm=100.0,
            axis="x",
        )

        self.assertEqual(len(segments), 2)
        self.assertAlmostEqual(segments[0]["start"], 100.0)
        self.assertAlmostEqual(segments[0]["end"], 120.0)
        self.assertAlmostEqual(segments[1]["start"], 120.0)
        self.assertAlmostEqual(segments[1]["end"], 150.0)

    def test_segment_values_sum_to_total_dimension(self):
        segments = build_flange_segment_metadata(
            [125.0, 175.0],
            lower=100.0,
            upper=200.0,
            total_mm=300.0,
            axis="x",
        )

        total = sum(float(segment["label_mm"]) for segment in segments)
        self.assertAlmostEqual(total, 300.0)

    def test_merges_nearly_identical_bend_positions(self):
        segments = build_flange_segment_metadata(
            [120.0, 120.2, 145.0],
            lower=100.0,
            upper=180.0,
            total_mm=160.0,
            axis="y",
            merge_tolerance=0.5,
        )

        self.assertEqual(len(segments), 3)
        first_split = float(segments[0]["end"])
        self.assertGreater(first_split, 120.0)
        self.assertLess(first_split, 120.2)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
FREECAD_HELPER_DIR = SERVER_DIR / "freecad"
if str(FREECAD_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(FREECAD_HELPER_DIR))

from dimension_quality_helpers import summarize_view_dimension_quality


class TestSummarizeViewDimensionQuality(unittest.TestCase):
    def test_accepts_clean_outside_dimensions(self):
        summary = summarize_view_dimension_quality(
            (0.0, 50.0, 0.0, 40.0),
            overall_dimensions=[
                {
                    "measurement_box": (0.0, 50.0, 45.0, 45.5),
                    "text_box": (22.0, 28.0, 44.0, 46.0),
                }
            ],
            feature_dimensions=[
                {
                    "outside": True,
                    "style": "line",
                    "measurement_box": (-8.0, -7.5, 5.0, 25.0),
                    "text_box": (-13.0, -11.0, 13.0, 17.0),
                }
            ],
        )
        self.assertEqual(summary["overall_geom_overlap_count"], 0)
        self.assertEqual(summary["feature_geom_overlap_count"], 0)
        self.assertEqual(summary["feature_overall_overlap_count"], 0)
        self.assertEqual(summary["text_overlap_count"], 0)

    def test_flags_feature_overlap_with_geometry(self):
        summary = summarize_view_dimension_quality(
            (0.0, 50.0, 0.0, 40.0),
            overall_dimensions=[],
            feature_dimensions=[
                {
                    "outside": True,
                    "style": "line",
                    "measurement_box": (10.0, 30.0, 20.0, 20.5),
                    "text_box": (19.0, 21.0, 18.0, 22.0),
                }
            ],
        )
        self.assertGreater(summary["feature_geom_overlap_count"], 0)

    def test_flags_feature_overlap_with_overall_dimensions(self):
        summary = summarize_view_dimension_quality(
            (0.0, 50.0, 0.0, 40.0),
            overall_dimensions=[
                {
                    "measurement_box": (0.0, 50.0, 45.0, 45.5),
                    "text_box": (22.0, 28.0, 44.0, 46.0),
                }
            ],
            feature_dimensions=[
                {
                    "outside": True,
                    "style": "leader",
                    "measurement_box": (23.0, 29.0, 44.5, 45.0),
                    "text_box": (23.0, 29.0, 44.3, 46.2),
                }
            ],
        )
        self.assertGreater(summary["feature_overall_overlap_count"], 0)
        self.assertGreater(summary["text_overlap_count"], 0)

    def test_tolerates_minor_outside_leader_text_graze(self):
        summary = summarize_view_dimension_quality(
            (0.0, 50.0, 0.0, 40.0),
            overall_dimensions=[],
            feature_dimensions=[
                {
                    "outside": True,
                    "style": "leader",
                    "measurement_box": (8.0, 12.0, 22.0, 22.5),
                    "text_box": (-2.5, 1.2, 18.0, 22.0),
                }
            ],
        )
        self.assertEqual(summary["feature_geom_overlap_count"], 0)


if __name__ == "__main__":
    unittest.main()

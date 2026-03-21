from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
FREECAD_HELPER_DIR = SERVER_DIR / "freecad"
if str(FREECAD_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(FREECAD_HELPER_DIR))

from sheet_metal_feature_helpers import (
    build_folded_feature_dimensions,
    choose_folded_feature_view,
    inject_folded_sheet_metal_feature_dims,
    plan_has_folded_feature_dims,
)


class TestChooseFoldedFeatureView(unittest.TestCase):
    def test_prefers_most_circles(self):
        self.assertEqual(
            choose_folded_feature_view({"Front": 2, "Top": 0, "Left": 1}),
            "Front",
        )

    def test_breaks_tie_by_view_priority(self):
        self.assertEqual(
            choose_folded_feature_view({"Front": 1, "Top": 1, "Left": 1}),
            "Front",
        )

    def test_returns_none_without_visible_circles(self):
        self.assertIsNone(choose_folded_feature_view({"Front": 0, "Top": 0, "Left": 0}))


class TestBuildFoldedFeatureDimensions(unittest.TestCase):
    def test_builds_expected_hole_dims(self):
        dims = build_folded_feature_dimensions(
            {
                "hole_count": 4,
                "hole_diameter_mm": 6.0,
                "hole_pitch_mm": 80.0,
                "hole_groups": [{"center_mm": {"x": 10, "y": 20, "z": 0}, "diameter_mm": 6.0}],
            },
            target_view="Left",
        )
        types = {dim["dim_type"] for dim in dims}
        self.assertEqual(
            types,
            {"hole_diameter", "hole_pitch", "hole_location_x", "hole_location_y"},
        )


class TestInjectFoldedSheetMetalFeatureDims(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "part_type": "sheet_metal",
            "detail_level": 1,
            "views": [
                {"view_name": "Front", "dimensions": []},
                {"view_name": "Top", "dimensions": []},
                {"view_name": "Left", "dimensions": []},
                {
                    "view_name": "FlatPattern",
                    "dimensions": [
                        {"dim_type": "flat_length", "target_view": "FlatPattern", "axis": "H", "value_mm": 120.0},
                        {"dim_type": "flat_width", "target_view": "FlatPattern", "axis": "V", "value_mm": 80.0},
                    ],
                },
            ],
        }
        self.payload = {
            "hole_count": 2,
            "hole_diameter_mm": 5.0,
            "hole_pitch_mm": 40.0,
            "hole_groups": [{"center_mm": {"x": 10, "y": 15, "z": 0}, "diameter_mm": 5.0}],
        }

    def test_injects_into_best_folded_view(self):
        injected = inject_folded_sheet_metal_feature_dims(
            self.plan,
            self.payload,
            {"Front": 0, "Top": 0, "Left": 2},
        )
        self.assertIsNotNone(injected)
        self.assertTrue(plan_has_folded_feature_dims(injected))
        left_view = next(view for view in injected["views"] if view["view_name"] == "Left")
        self.assertEqual(
            {dim["dim_type"] for dim in left_view["dimensions"]},
            {"hole_diameter", "hole_pitch", "hole_location_x", "hole_location_y"},
        )

    def test_keeps_flat_pattern_clean(self):
        injected = inject_folded_sheet_metal_feature_dims(
            self.plan,
            self.payload,
            {"Front": 2, "Top": 0, "Left": 0},
        )
        flat_view = next(view for view in injected["views"] if view["view_name"] == "FlatPattern")
        self.assertEqual(
            {dim["dim_type"] for dim in flat_view["dimensions"]},
            {"flat_length", "flat_width"},
        )

    def test_noop_if_no_visible_circle_view(self):
        injected = inject_folded_sheet_metal_feature_dims(
            self.plan,
            self.payload,
            {"Front": 0, "Top": 0, "Left": 0},
        )
        self.assertTrue(plan_has_folded_feature_dims(injected))
        front_view = next(view for view in injected["views"] if view["view_name"] == "Front")
        self.assertEqual(
            {dim["dim_type"] for dim in front_view["dimensions"]},
            {"hole_diameter", "hole_pitch", "hole_location_x", "hole_location_y"},
        )


if __name__ == "__main__":
    unittest.main()

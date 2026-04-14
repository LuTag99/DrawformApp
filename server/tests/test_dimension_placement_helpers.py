from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
FREECAD_HELPER_DIR = SERVER_DIR / "freecad"
if str(FREECAD_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(FREECAD_HELPER_DIR))

from dimension_placement_helpers import (
    build_feature_outside_band_profile,
    minimum_overall_dimension_offset,
    should_allow_projected_centerlines,
    should_fallback_feature_dims_to_visible_view,
    should_place_feature_dims_outside,
    should_suppress_feature_dims_postcheck,
)


class TestShouldPlaceFeatureDimsOutside(unittest.TestCase):
    def test_prefers_outside_for_orthographic_feature_views(self):
        self.assertTrue(
            should_place_feature_dims_outside("Left", {"hole_diameter", "hole_pitch"})
        )

    def test_rejects_non_feature_views(self):
        self.assertFalse(
            should_place_feature_dims_outside("Front", {"overall_length"})
        )

    def test_rejects_non_orthographic_views(self):
        self.assertFalse(
            should_place_feature_dims_outside("Iso", {"hole_diameter"})
        )


class TestShouldAllowProjectedCenterlines(unittest.TestCase):
    def test_allows_projected_centerlines_without_visible_circle_views(self):
        self.assertTrue(
            should_allow_projected_centerlines(
                "Front",
                6,
                {"Front": 0, "Top": 0, "Left": 0},
            )
        )

    def test_rejects_projected_centerlines_when_visible_circle_view_exists(self):
        self.assertFalse(
            should_allow_projected_centerlines(
                "Front",
                2,
                {"Front": 0, "Top": 2, "Left": 0},
            )
        )

    def test_rejects_non_orthographic_or_empty_projection(self):
        self.assertFalse(
            should_allow_projected_centerlines(
                "Iso",
                4,
                {"Front": 0, "Top": 0, "Left": 0},
            )
        )
        self.assertFalse(
            should_allow_projected_centerlines(
                "Front",
                0,
                {"Front": 0, "Top": 0, "Left": 0},
            )
        )


class TestShouldFallbackFeatureDimsToVisibleView(unittest.TestCase):
    def test_prefers_visible_circle_view_for_slender_rotated_front_strip(self):
        self.assertTrue(
            should_fallback_feature_dims_to_visible_view(
                "Front",
                "Top",
                0,
                2,
                2,
                (-50.0, 0.0, -300.0, 0.0),
                90,
                layout_profile="milling",
            )
        )

    def test_keeps_projected_front_dims_for_compact_front_views(self):
        self.assertFalse(
            should_fallback_feature_dims_to_visible_view(
                "Front",
                "Top",
                0,
                2,
                2,
                (-40.0, 0.0, 0.0, 60.0),
                90,
                layout_profile="milling",
            )
        )

    def test_rejects_non_milling_or_non_rotated_or_visible_front_cases(self):
        self.assertFalse(
            should_fallback_feature_dims_to_visible_view(
                "Front",
                "Top",
                1,
                2,
                2,
                (-50.0, 0.0, -300.0, 0.0),
                90,
                layout_profile="milling",
            )
        )
        self.assertFalse(
            should_fallback_feature_dims_to_visible_view(
                "Front",
                "Top",
                0,
                2,
                2,
                (-50.0, 0.0, -300.0, 0.0),
                0,
                layout_profile="milling",
            )
        )
        # sheet_metal now also supports fallback to visible view (P1 update)
        self.assertTrue(
            should_fallback_feature_dims_to_visible_view(
                "Front",
                "Top",
                0,
                2,
                2,
                (-50.0, 0.0, -300.0, 0.0),
                90,
                layout_profile="sheet_metal",
            )
        )


class TestShouldSuppressFeatureDimsPostcheck(unittest.TestCase):
    def test_suppresses_geometry_overlap_for_all_profiles(self):
        self.assertTrue(
            should_suppress_feature_dims_postcheck(
                "sheet_metal",
                {"feature_overall_overlap_count": 0, "feature_geom_overlap_count": 1},
            )
        )

    def test_suppresses_overall_overlap_for_milling_only(self):
        self.assertTrue(
            should_suppress_feature_dims_postcheck(
                "milling",
                {"feature_overall_overlap_count": 1, "feature_geom_overlap_count": 0},
            )
        )
        self.assertFalse(
            should_suppress_feature_dims_postcheck(
                "sheet_metal",
                {"feature_overall_overlap_count": 1, "feature_geom_overlap_count": 0},
            )
        )

    def test_ignores_empty_or_invalid_quality_payloads(self):
        self.assertFalse(should_suppress_feature_dims_postcheck("milling", None))
        self.assertFalse(
            should_suppress_feature_dims_postcheck(
                "milling",
                {"feature_overall_overlap_count": "0", "feature_geom_overlap_count": "0"},
            )
        )


class TestBuildFeatureOutsideBandProfile(unittest.TestCase):
    def test_rotated_sheet_metal_front_gets_wider_leader_band_than_milling(self):
        sheet_profile = build_feature_outside_band_profile(
            (-35.0, 0.0, -115.0, 0.0),
            1.0,
            90,
            view_name="Front",
            layout_profile="sheet_metal",
            overall_dimensions=[{"axis": "V"}],
        )
        milling_profile = build_feature_outside_band_profile(
            (-35.0, 0.0, -115.0, 0.0),
            1.0,
            90,
            view_name="Front",
            layout_profile="milling",
            overall_dimensions=[{"axis": "V"}],
        )
        self.assertGreater(
            sheet_profile["side_base_offset"],
            milling_profile["side_base_offset"],
        )
        self.assertGreater(
            sheet_profile["side_step"],
            milling_profile["side_step"],
        )
        self.assertEqual(sheet_profile["preferred_leader_side"], "right")
        self.assertEqual(sheet_profile["preferred_vertical_side"], "left")


class TestMinimumOverallDimensionOffset(unittest.TestCase):
    def test_vertical_offset_reserves_more_space_for_rotated_text(self):
        horizontal = minimum_overall_dimension_offset(
            1.0,
            4.2,
            axis="H",
            summary_line_pad=0.18,
        )
        vertical = minimum_overall_dimension_offset(
            1.0,
            4.2,
            axis="V",
            summary_line_pad=0.18,
        )
        self.assertGreater(vertical, horizontal)
        self.assertGreaterEqual(horizontal, 1.6)

    def test_scale_is_respected_for_small_views(self):
        vertical = minimum_overall_dimension_offset(
            2.5,
            1.68,
            axis="V",
            summary_line_pad=0.072,
        )
        self.assertGreater(vertical, 1.0)
        self.assertLess(vertical, 2.0)


if __name__ == "__main__":
    unittest.main()

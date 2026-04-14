"""Tests validating the technical drawing quality contract.

These tests verify the FACHVERTRAG (technical contract), not current behavior.
Each test encodes a non-negotiable rule from the drawing pipeline review.
"""
from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock


def _import_evaluate_pre_export_quality():
    """Import evaluate_pre_export_quality with mocked external-only modules.

    Only FreeCAD, reportlab and svglib are truly external.  The local helper
    modules (flat_pattern_helpers, etc.) live in server/freecad/ and are
    imported naturally once that directory is on sys.path.

    We stash and restore any previously-missing module entries so that other
    test files (e.g. test_step_feature_probe) are not affected by our mocks.
    """
    import pathlib
    freecad_dir = str(pathlib.Path(__file__).resolve().parent.parent / "freecad")
    if freecad_dir not in sys.path:
        sys.path.insert(0, freecad_dir)

    _EXTERNAL_MOCKS = (
        "FreeCAD", "Import", "Part", "TechDraw",
        "reportlab", "reportlab.graphics", "reportlab.graphics.renderPDF",
        "reportlab.lib", "reportlab.lib.units", "reportlab.lib.pagesizes",
        "svglib", "svglib.svglib",
    )
    _sentinel = object()
    saved = {}
    for mod in _EXTERNAL_MOCKS:
        saved[mod] = sys.modules.get(mod, _sentinel)
        if saved[mod] is _sentinel:
            sys.modules[mod] = MagicMock()

    try:
        from step_to_pdf import evaluate_pre_export_quality
        return evaluate_pre_export_quality
    finally:
        # Restore original module state so other tests are unaffected
        for mod in _EXTERNAL_MOCKS:
            if saved[mod] is _sentinel:
                sys.modules.pop(mod, None)


evaluate_pre_export_quality = _import_evaluate_pre_export_quality()


class TestPreExportQualityContract(unittest.TestCase):
    """Verify that evaluate_pre_export_quality enforces the quality contract."""

    def _make_report(self, **overrides):
        base = {
            "views": {},
            "quality": {},
            "features": {},
        }
        base.update(overrides)
        return base

    def _evaluate(self, report, page_svg="", dim_x=100, dim_y=50, dim_z=30, dim_tracking=None):
        return evaluate_pre_export_quality(
            report, page_svg, dim_x, dim_y, dim_z,
            dim_tracking=dim_tracking,
        )

    def test_fallback_projection_is_quality_blocker(self):
        """A fallback_projection source must produce a FEHLER blocker."""
        report = self._make_report(
            abwicklung={"source": "fallback_projection"},
        )
        result = self._evaluate(report)
        self.assertEqual(result["status"], "FEHLER")
        self.assertTrue(
            any("Abwicklung" in b and "Unfold" in b for b in result["blockers"]),
            f"Expected Abwicklung blocker, got: {result['blockers']}",
        )

    def test_clean_template_no_title_block_false_positive(self):
        """A clean A3 template with only title block fields must NOT trigger blockers."""
        svg = (
            '<text x="350" y="280">09.04.2026</text>'
            '<text x="350" y="285">DF-0001</text>'
            '<text x="350" y="290">1:2</text>'
        )
        result = self._evaluate(
            self._make_report(),
            page_svg=svg,
            dim_tracking={"dimension_paper_boxes": []},
        )
        title_block_blockers = [b for b in result["blockers"] if "Schriftfeld" in b]
        self.assertEqual(title_block_blockers, [],
                         "Title block fields with digits must not be flagged as dimension overlap")

    def test_real_dimension_in_title_block_zone_blocked(self):
        """A tracked dimension box inside the title block zone must be blocked."""
        # A3: tb_top_y = 297 - 55 = 242; box at y=250-260 is inside title block
        result = self._evaluate(
            self._make_report(),
            dim_tracking={"dimension_paper_boxes": [(200.0, 220.0, 250.0, 260.0)]},
        )
        self.assertEqual(result["status"], "FEHLER")
        self.assertTrue(
            any("Schriftfeld" in b for b in result["blockers"]),
            f"Expected title block blocker, got: {result['blockers']}",
        )

    def test_dimension_above_title_block_not_blocked(self):
        """A tracked dimension box fully above the title block zone must NOT be blocked."""
        # A3: tb_top_y = 242; box at y=100-110 is safely above
        result = self._evaluate(
            self._make_report(),
            dim_tracking={"dimension_paper_boxes": [(200.0, 220.0, 100.0, 110.0)]},
        )
        title_block_blockers = [b for b in result["blockers"] if "Schriftfeld" in b]
        self.assertEqual(title_block_blockers, [])

    def test_failure_classes_structured_output(self):
        """The result must contain structured failure_classes with severity/category/code."""
        result = self._evaluate(
            self._make_report(abwicklung={"source": "fallback_projection"}),
        )
        fcs = result.get("failure_classes", [])
        self.assertTrue(len(fcs) >= 1, "Expected at least one failure class")
        fc = fcs[0]
        self.assertIn("severity", fc)
        self.assertIn("category", fc)
        self.assertIn("code", fc)
        self.assertIn("message", fc)
        self.assertEqual(fc["code"], "FALLBACK_PROJECTION")
        self.assertEqual(fc["severity"], "BLOCKER")

    def test_no_failure_classes_when_clean(self):
        """A clean report should have no failure_classes key (or empty)."""
        svg = '<text x="200" y="100">100</text><text x="200" y="120">50</text><text x="200" y="140">30</text>'
        result = self._evaluate(
            self._make_report(),
            page_svg=svg,
            dim_tracking={"dimension_paper_boxes": []},
        )
        fcs = result.get("failure_classes", [])
        blocker_fcs = [fc for fc in fcs if fc.get("severity") == "BLOCKER"]
        self.assertEqual(blocker_fcs, [], "Clean report should have no blocker failure classes")


class TestViewSelectionContract(unittest.TestCase):
    """Verify that hole dimensions are placed in the view where holes are visible."""

    def test_hole_axis_z_targets_top_view(self):
        from rules.dimension_strategy import _best_view_for_hole
        fp = {"hole_groups": [{"axis": "Z", "diameter_mm": 10}]}
        self.assertEqual(_best_view_for_hole(fp), "Top")

    def test_hole_axis_y_targets_front_view(self):
        from rules.dimension_strategy import _best_view_for_hole
        fp = {"hole_groups": [{"axis": "Y", "diameter_mm": 10}]}
        self.assertEqual(_best_view_for_hole(fp), "Front")

    def test_hole_axis_x_targets_left_view(self):
        from rules.dimension_strategy import _best_view_for_hole
        fp = {"hole_groups": [{"axis": "X", "diameter_mm": 10}]}
        self.assertEqual(_best_view_for_hole(fp), "Left")

    def test_fallback_uses_thickness_axis(self):
        from rules.dimension_strategy import _best_view_for_hole
        fp = {"hole_groups": [], "thickness_axis": "Z"}
        self.assertEqual(_best_view_for_hole(fp), "Top")

    def test_empty_payload_defaults_to_front(self):
        from rules.dimension_strategy import _best_view_for_hole
        self.assertEqual(_best_view_for_hole({}), "Front")


class TestHoleCalloutContract(unittest.TestCase):
    """Verify n\u00d7\u00d8 notation for grouped holes."""

    def test_single_hole_no_count_prefix(self):
        from rules.dimension_strategy import _format_hole_callout_label
        label = _format_hole_callout_label(10.0, None, count=1)
        self.assertFalse(label.startswith("1"))
        self.assertIn("\u00d8", label)  # \u00d8 symbol

    def test_multiple_holes_get_count_prefix(self):
        from rules.dimension_strategy import _format_hole_callout_label
        label = _format_hole_callout_label(8.0, None, count=4)
        self.assertTrue(label.startswith("4\u00d7"))  # 4\u00d7
        self.assertIn("\u00d8", label)

    def test_through_hole_with_count(self):
        from rules.dimension_strategy import _format_hole_callout_label
        label = _format_hole_callout_label(6.0, {"through": True}, count=3)
        self.assertIn("3\u00d7", label)
        self.assertIn("DURCH", label)


class TestCountHolesByDiameter(unittest.TestCase):
    """Verify hole counting for n\u00d7\u00d8 grouping."""

    def test_count_matching_diameter(self):
        from rules.dimension_strategy import _count_holes_by_diameter
        groups = [
            {"diameter_mm": 10.0},
            {"diameter_mm": 10.0},
            {"diameter_mm": 6.0},
        ]
        self.assertEqual(_count_holes_by_diameter(groups, 10.0), 2)
        self.assertEqual(_count_holes_by_diameter(groups, 6.0), 1)

    def test_empty_groups_returns_one(self):
        from rules.dimension_strategy import _count_holes_by_diameter
        self.assertEqual(_count_holes_by_diameter([], 10.0), 1)

    def test_none_diameter_returns_one(self):
        from rules.dimension_strategy import _count_holes_by_diameter
        self.assertEqual(_count_holes_by_diameter([{"diameter_mm": 10}], None), 1)


class TestSectionViewContract(unittest.TestCase):
    """Verify that section views are requested for internal geometry."""

    def test_milling_step_profile_requests_section(self):
        from rules.dimension_strategy import _collect_section_views
        fp = {
            "step_count": 3,
            "slot_groups": [],
            "hole_count": 0,
            "hole_groups": [],
            "pocket_groups": [],
        }
        sections = _collect_section_views(fp, layout_profile="milling")
        self.assertTrue(len(sections) >= 1)
        self.assertEqual(sections[0].reason, "internal_step_profile")

    def test_milling_blind_slot_requests_section(self):
        from rules.dimension_strategy import _collect_section_views
        fp = {
            "step_count": 0,
            "slot_groups": [{"depth_mm": 5.0}],
            "hole_count": 0,
            "hole_groups": [],
            "pocket_groups": [],
        }
        sections = _collect_section_views(fp, layout_profile="milling")
        self.assertTrue(len(sections) >= 1)
        self.assertEqual(sections[0].reason, "blind_slot_depth")


class TestAbwicklungContract(unittest.TestCase):
    """Verify that fallback projections are never accepted as valid Abwicklung."""

    def test_fallback_projection_must_be_rejected(self):
        """The quality gate must block export when abwicklung source is fallback_projection."""
        report = {
            "views": {},
            "quality": {},
            "features": {},
            "abwicklung": {"source": "fallback_projection"},
        }
        result = evaluate_pre_export_quality(report, "", 100, 50, 30)
        self.assertEqual(result["status"], "FEHLER")
        self.assertTrue(
            any("fallback" in b.lower() or "Abwicklung" in b for b in result["blockers"]),
            f"Expected fallback_projection blocker, got: {result['blockers']}",
        )


if __name__ == "__main__":
    unittest.main()

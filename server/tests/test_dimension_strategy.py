"""Unit tests for the Dimension Strategy Engine (DSE)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure server/ is on sys.path so relative imports in rules/ work.
SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from rules.dimension_plan_schema import DimensionPlan, ViewPlan
from rules.dimension_strategy import (
    apply_overrides,
    build_dimension_plan,
    select_layout_profile_standalone,
)

# ---------------------------------------------------------------------------
# Mock feature payloads
# ---------------------------------------------------------------------------

_CUBE_10 = {
    "ok": True,
    "bbox_mm": {"X": 10.0, "Y": 10.0, "Z": 10.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "hole_count": 0,
    "hole_diameter_mm": None,
    "hole_pitch_mm": None,
    "hole_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 1.0,
    "is_flat": False,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 6,
    "cylinder_face_count": 0,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": None,
}

_FLANGE = {
    "ok": True,
    "bbox_mm": {"X": 200.0, "Y": 150.0, "Z": 12.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "hole_count": 8,
    "hole_diameter_mm": 14.0,
    "hole_pitch_mm": 180.0,
    "hole_groups": [
        {"center_mm": {"x": 10, "y": 75, "z": 6}, "diameter_mm": 14.0},
        {"center_mm": {"x": 190, "y": 75, "z": 6}, "diameter_mm": 14.0},
    ],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 0.08,
    "is_flat": True,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 20,
    "cylinder_face_count": 0,
    "cone_face_count": 2,
    "flat_pattern": None,
    "thread_label": "M6",
}

_SHEET_METAL = {
    "ok": True,
    "bbox_mm": {"X": 300.0, "Y": 200.0, "Z": 2.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "hole_count": 4,
    "hole_diameter_mm": 6.0,
    "hole_pitch_mm": 100.0,
    "hole_groups": [
        {"center_mm": {"x": 50, "y": 100, "z": 1}, "diameter_mm": 6.0},
        {"center_mm": {"x": 150, "y": 100, "z": 1}, "diameter_mm": 6.0},
    ],
    "bend_radius_mm": 1.5,
    "measured_thickness_mm": 2.0,
    "flat_ratio": 0.01,
    "is_flat": True,
    "is_sheet_metal_by_faces": True,
    "plane_face_count": 30,
    "cylinder_face_count": 4,
    "cone_face_count": 0,
    "flat_pattern": {
        "bend_count": 2,
        "k_factor_used": 0.33,
        "flat_length_mm": 310.0,
        "flat_width_mm": 200.0,
    },
    "thread_label": None,
}

_UNFOLD_OK = {
    "ok": True,
    "flat_length_mm": 310.0,
    "flat_width_mm": 200.0,
    "bend_count": 2,
    "bend_lines": [
        {"x1": 50, "y1": 0, "x2": 50, "y2": 200},
        {"x1": 260, "y1": 0, "x2": 260, "y2": 200},
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLayoutProfileStandalone(unittest.TestCase):
    def test_cube_is_milling(self):
        self.assertEqual(select_layout_profile_standalone("part.step", _CUBE_10), "milling")

    def test_flange_is_milling(self):
        # Flange has cone faces → milling (not sheet metal)
        self.assertEqual(select_layout_profile_standalone("part.step", _FLANGE), "milling")

    def test_sheet_metal_by_faces(self):
        self.assertEqual(select_layout_profile_standalone("part.step", _SHEET_METAL), "sheet_metal")

    def test_path_override(self):
        self.assertEqual(select_layout_profile_standalone("Sheetmetals/part.step", _CUBE_10), "sheet_metal")

    def test_empty_payload_is_milling(self):
        self.assertEqual(select_layout_profile_standalone("part.step", {}), "milling")


class TestMillingBasic(unittest.TestCase):
    def setUp(self):
        self.plan = build_dimension_plan(_CUBE_10, "milling")

    def test_part_type(self):
        self.assertEqual(self.plan.part_type, "milling")

    def test_has_front_overall_dims(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("overall_length", types)
        self.assertIn("overall_height", types)

    def test_top_has_depth_only(self):
        top = next(v for v in self.plan.views if v.view_name == "Top")
        types = {d.dim_type for d in top.dimensions}
        self.assertIn("overall_depth", types)
        self.assertNotIn("overall_length", types)

    def test_left_empty_at_level_1(self):
        left = next(v for v in self.plan.views if v.view_name == "Left")
        self.assertEqual(len(left.dimensions), 0)

    def test_iso_empty(self):
        iso = next(v for v in self.plan.views if v.view_name == "Iso")
        self.assertEqual(len(iso.dimensions), 0)

    def test_no_feature_dims(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        feature_types = {"hole_diameter", "hole_pitch", "thread_callout"}
        actual = {d.dim_type for d in front.dimensions}
        self.assertEqual(actual & feature_types, set())


class TestMillingWithHoles(unittest.TestCase):
    def setUp(self):
        self.plan = build_dimension_plan(_FLANGE, "milling")

    def test_has_hole_diameter(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("hole_diameter", types)

    def test_has_hole_pitch(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("hole_pitch", types)

    def test_has_hole_locations(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("hole_location_x", types)
        self.assertIn("hole_location_y", types)

    def test_has_thread_callout(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("thread_callout", types)

    def test_hole_diameter_value(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        hd = next(d for d in front.dimensions if d.dim_type == "hole_diameter")
        self.assertAlmostEqual(hd.value_mm, 14.0)

    def test_hole_pitch_value(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        hp = next(d for d in front.dimensions if d.dim_type == "hole_pitch")
        self.assertAlmostEqual(hp.value_mm, 180.0)


class TestSheetMetalWithUnfold(unittest.TestCase):
    def setUp(self):
        self.plan = build_dimension_plan(
            _SHEET_METAL, "sheet_metal", unfold_result=_UNFOLD_OK
        )

    def test_part_type(self):
        self.assertEqual(self.plan.part_type, "sheet_metal")

    def test_has_flat_pattern_view(self):
        names = {v.view_name for v in self.plan.views}
        self.assertIn("FlatPattern", names)

    def test_flat_pattern_dims(self):
        fp = next(v for v in self.plan.views if v.view_name == "FlatPattern")
        types = {d.dim_type for d in fp.dimensions}
        self.assertIn("flat_length", types)
        self.assertIn("flat_width", types)

    def test_flat_length_value(self):
        fp = next(v for v in self.plan.views if v.view_name == "FlatPattern")
        fl = next(d for d in fp.dimensions if d.dim_type == "flat_length")
        self.assertAlmostEqual(fl.value_mm, 310.0)

    def test_process_notes_thickness(self):
        note_types = {n.note_type for n in self.plan.process_notes}
        self.assertIn("thickness", note_types)

    def test_process_notes_k_factor(self):
        note_types = {n.note_type for n in self.plan.process_notes}
        self.assertIn("k_factor", note_types)

    def test_process_notes_inner_radius(self):
        note_types = {n.note_type for n in self.plan.process_notes}
        self.assertIn("inner_radius", note_types)

    def test_front_has_overall_dims(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("overall_length", types)
        self.assertIn("overall_height", types)

    def test_flat_pattern_has_holes(self):
        fp = next(v for v in self.plan.views if v.view_name == "FlatPattern")
        types = {d.dim_type for d in fp.dimensions}
        self.assertIn("hole_diameter", types)


class TestSheetMetalNoUnfold(unittest.TestCase):
    def test_no_flat_pattern_view(self):
        plan = build_dimension_plan(_SHEET_METAL, "sheet_metal", unfold_result=None)
        names = {v.view_name for v in plan.views}
        self.assertNotIn("FlatPattern", names)

    def test_front_still_has_overall(self):
        plan = build_dimension_plan(_SHEET_METAL, "sheet_metal", unfold_result=None)
        front = next(v for v in plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("overall_length", types)


class TestTurningPlaceholder(unittest.TestCase):
    def test_turning_has_overall(self):
        fp = {**_CUBE_10, "bbox_mm": {"X": 100.0, "Y": 30.0, "Z": 30.0}}
        plan = build_dimension_plan(fp, "turning")
        self.assertEqual(plan.part_type, "turning")
        front = next(v for v in plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("overall_length", types)
        self.assertIn("overall_height", types)


class TestDeduplication(unittest.TestCase):
    def test_no_duplicate_overall_depth(self):
        """overall_depth should not appear in both Top and Left at detail_level=2."""
        plan = build_dimension_plan(_CUBE_10, "milling", detail_level=2)
        all_dims = []
        for view in plan.views:
            for dim in view.dimensions:
                if dim.value_mm is not None:
                    all_dims.append((dim.dim_type, dim.value_mm))
        # No duplicates
        self.assertEqual(len(all_dims), len(set(all_dims)))


class TestDetailLevels(unittest.TestCase):
    def test_level_monotonic(self):
        counts = []
        for level in (1, 2, 3):
            plan = build_dimension_plan(_FLANGE, "milling", detail_level=level)
            total = sum(len(v.dimensions) for v in plan.views)
            counts.append(total)
        # Each level should have >= dimensions of previous level
        for i in range(1, len(counts)):
            self.assertGreaterEqual(counts[i], counts[i - 1])


class TestOverrideAdd(unittest.TestCase):
    def test_add_dimension(self):
        plan = build_dimension_plan(_CUBE_10, "milling")
        plan = apply_overrides(plan, [
            {
                "action": "add",
                "target_view": "Front",
                "dimension": {
                    "dim_type": "pocket_depth",
                    "target_view": "Front",
                    "value_mm": 5.0,
                    "label": "5,0",
                },
            }
        ])
        front = next(v for v in plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("pocket_depth", types)
        self.assertEqual(len(plan.overrides_applied), 1)


class TestOverrideRemove(unittest.TestCase):
    def test_remove_dimension(self):
        plan = build_dimension_plan(_FLANGE, "milling")
        front = next(v for v in plan.views if v.view_name == "Front")
        self.assertTrue(any(d.dim_type == "hole_pitch" for d in front.dimensions))

        plan = apply_overrides(plan, [
            {
                "action": "remove",
                "target_view": "Front",
                "dim_type": "hole_pitch",
            }
        ])
        front = next(v for v in plan.views if v.view_name == "Front")
        self.assertFalse(any(d.dim_type == "hole_pitch" for d in front.dimensions))
        self.assertEqual(len(plan.overrides_applied), 1)


class TestDatumSystem(unittest.TestCase):
    def test_datum_axes(self):
        plan = build_dimension_plan(_CUBE_10, "milling")
        ds = plan.datum_system
        self.assertEqual(ds.A, "Z")  # thickness axis
        self.assertEqual(ds.B, "X")  # longest axis
        self.assertIn(ds.C, ("Y",))


class TestSerializable(unittest.TestCase):
    def test_model_dump_roundtrip(self):
        plan = build_dimension_plan(_FLANGE, "milling")
        d = plan.model_dump()
        self.assertIsInstance(d, dict)
        self.assertIn("views", d)
        self.assertIn("datum_system", d)
        # Should be JSON-serializable
        import json
        json.dumps(d)


if __name__ == "__main__":
    unittest.main()

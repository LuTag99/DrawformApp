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
    classify_milling_subtype,
    classify_turning_subtype,
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

_COMPACT_FLAT_PLATE = {
    "ok": True,
    "bbox_mm": {"X": 100.0, "Y": 100.0, "Z": 10.0},
    "longest_axis": "X",
    "thickness_axis": None,
    "hole_count": 6,
    "hole_diameter_mm": 10.0,
    "hole_pitch_mm": 70.0,
    "hole_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 0.10,
    "is_flat": True,
    "is_sheet_metal_by_faces": None,
    "plane_face_count": None,
    "cylinder_face_count": None,
    "cone_face_count": None,
    "flat_pattern": None,
    "thread_label": None,
}

_THICK_RECT_BLOCK = {
    "ok": True,
    "bbox_mm": {"X": 100.0, "Y": 300.0, "Z": 50.0},
    "longest_axis": "Y",
    "thickness_axis": None,
    "hole_count": 2,
    "hole_diameter_mm": 32.5,
    "hole_pitch_mm": 148.6,
    "hole_groups": [],
    "bend_radius_mm": 16.1,
    "measured_thickness_mm": None,
    "flat_ratio": 0.5,
    "is_flat": False,
    "is_sheet_metal_by_faces": None,
    "plane_face_count": None,
    "cylinder_face_count": None,
    "cone_face_count": None,
    "flat_pattern": None,
    "thread_label": None,
}

_SHAFT_FALSE_SHEET_METAL = {
    "ok": True,
    "bbox_mm": {"X": 30.0, "Y": 30.0, "Z": 100.0},
    "longest_axis": "Z",
    "thickness_axis": "Y",
    "hole_count": 3,
    "hole_diameter_mm": 25.0,
    "hole_pitch_mm": 100.0,
    "hole_groups": [
        {"center_mm": {"x": 0.0, "y": 0.0, "z": 40.0}, "diameter_mm": 25.0},
        {"center_mm": {"x": 0.0, "y": 0.0, "z": 0.0}, "diameter_mm": 30.0},
        {"center_mm": {"x": 0.0, "y": 0.0, "z": 100.0}, "diameter_mm": 20.0},
    ],
    "bend_radius_mm": 15.0,
    "measured_thickness_mm": 5.0,
    "flat_ratio": 1.0,
    "is_flat": False,
    "is_sheet_metal_by_faces": True,
    "plane_face_count": 3,
    "cylinder_face_count": 2,
    "cone_face_count": 0,
    "flat_pattern": {
        "bend_count": 2,
        "k_factor_used": 0.5,
        "flat_length_mm": 124.248,
        "flat_width_mm": 30.0,
    },
    "thread_label": None,
    "step_count": 1,
    "step_profile": [
        {"axis": "Z", "diameter_mm": 30.0, "start_mm": 0.0, "end_mm": 100.0, "length_mm": 100.0},
    ],
}

_STEPPED_SHAFT_FALSE_SHEET_METAL = {
    "ok": True,
    "bbox_mm": {"X": 250.0, "Y": 64.0, "Z": 64.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "hole_count": 7,
    "hole_diameter_mm": 36.0,
    "hole_pitch_mm": 250.0,
    "hole_groups": [
        {"center_mm": {"x": 60.0, "y": 0.0, "z": 0.0}, "diameter_mm": 42.0},
        {"center_mm": {"x": 0.0, "y": 0.0, "z": 0.0}, "diameter_mm": 32.0},
        {"center_mm": {"x": 250.0, "y": 0.0, "z": 0.0}, "diameter_mm": 24.0},
        {"center_mm": {"x": 82.0, "y": 0.0, "z": 0.0}, "diameter_mm": 50.0},
    ],
    "bend_radius_mm": 32.0,
    "measured_thickness_mm": 2.0,
    "flat_ratio": 1.0,
    "is_flat": False,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 12,
    "cylinder_face_count": 11,
    "cone_face_count": 0,
    "flat_pattern": {
        "bend_count": 9,
        "k_factor_used": 0.5,
        "flat_length_mm": 448.838,
        "flat_width_mm": 64.0,
    },
    "thread_label": None,
    "step_count": 6,
    "step_profile": [
        {"axis": "X", "diameter_mm": 48.0, "start_mm": 0.0, "end_mm": 60.0, "length_mm": 60.0},
        {"axis": "X", "diameter_mm": 36.0, "start_mm": 60.0, "end_mm": 82.0, "length_mm": 22.0},
        {"axis": "X", "diameter_mm": 64.0, "start_mm": 82.0, "end_mm": 94.0, "length_mm": 12.0},
        {"axis": "X", "diameter_mm": 36.0, "start_mm": 94.0, "end_mm": 140.0, "length_mm": 46.0},
        {"axis": "X", "diameter_mm": 24.0, "start_mm": 140.0, "end_mm": 210.0, "length_mm": 70.0},
        {"axis": "X", "diameter_mm": 32.0, "start_mm": 210.0, "end_mm": 250.0, "length_mm": 40.0},
    ],
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

_CHAMFERED_BLOCK = {
    **_CUBE_10,
    "bbox_mm": {"X": 120.0, "Y": 80.0, "Z": 40.0},
    "chamfers": [
        {
            "size_mm": 1.0,
            "angle_deg": 45.0,
            "axis_pair": "X-Y",
            "count": 4,
            "center_mm": {"x": 10.0, "y": 10.0, "z": 40.0},
        }
    ],
}

_BLIND_SLOT_BLOCK = {
    **_CUBE_10,
    "bbox_mm": {"X": 140.0, "Y": 90.0, "Z": 30.0},
    "slot_count": 1,
    "slot_groups": [
        {
            "width_mm": 12.0,
            "length_mm": 40.0,
            "depth_mm": 6.0,
            "center_mm": {"x": 70.0, "y": 45.0, "z": 24.0},
            "orientation": "H",
        }
    ],
}

_BLIND_HOLE_BLOCK = {
    **_CUBE_10,
    "bbox_mm": {"X": 120.0, "Y": 80.0, "Z": 30.0},
    "hole_count": 1,
    "hole_diameter_mm": 10.0,
    "hole_groups": [
        {
            "center_mm": {"x": 60.0, "y": 40.0, "z": 24.0},
            "diameter_mm": 10.0,
            "axis": "Z",
            "through": False,
            "depth_mm": 12.0,
        }
    ],
}

_THROUGH_HOLE_BLOCK = {
    **_CUBE_10,
    "bbox_mm": {"X": 120.0, "Y": 80.0, "Z": 20.0},
    "hole_count": 1,
    "hole_diameter_mm": 8.0,
    "hole_groups": [
        {
            "center_mm": {"x": 30.0, "y": 40.0, "z": 10.0},
            "diameter_mm": 8.0,
            "axis": "Z",
            "through": True,
            "depth_mm": None,
        }
    ],
}

_BLIND_THREAD_BLOCK = {
    **_BLIND_HOLE_BLOCK,
    "thread_label": "M8",
    "thread_through": False,
    "thread_depth_mm": 10.0,
}

_TURNING_WITH_RELIEF_GROOVE = {
    "ok": True,
    "bbox_mm": {"X": 40.0, "Y": 40.0, "Z": 140.0},
    "longest_axis": "Z",
    "thickness_axis": None,
    "hole_count": 0,
    "hole_diameter_mm": None,
    "hole_pitch_mm": None,
    "hole_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 1.0,
    "is_flat": False,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 4,
    "cylinder_face_count": 3,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": "M20",
    "rotational_profile": True,
    "step_count": 3,
    "step_profile": [
        {"axis": "Z", "diameter_mm": 30.0, "start_mm": 0.0, "end_mm": 58.0, "length_mm": 58.0},
        {"axis": "Z", "diameter_mm": 24.0, "start_mm": 58.0, "end_mm": 62.0, "length_mm": 4.0},
        {"axis": "Z", "diameter_mm": 30.0, "start_mm": 62.0, "end_mm": 140.0, "length_mm": 78.0},
    ],
    "groove_count": 1,
    "groove_groups": [
        {
            "axis": "Z",
            "kind": "freistich",
            "din_ref": "DIN 509",
            "start_mm": 58.0,
            "end_mm": 62.0,
            "width_mm": 4.0,
            "diameter_mm": 24.0,
            "center_mm": {"x": 0.0, "y": 0.0, "z": 60.0},
        }
    ],
    "thread_relief_recommended": False,
}

_SURFACE_FINISH_BLOCK = {
    **_CUBE_10,
    "surface_finish": {
        "parameter": "RA",
        "value": 3.2,
        "source": "step_metadata",
    },
}

_DENSE_DETAIL_BLOCK = {
    **_CUBE_10,
    "bbox_mm": {"X": 260.0, "Y": 120.0, "Z": 24.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "flat_ratio": 0.2,
    "is_flat": True,
    "hole_count": 12,
    "hole_diameter_mm": 6.0,
    "hole_pitch_mm": 26.0,
    "hole_groups": [
        {"center_mm": {"x": 45.0, "y": 25.0, "z": 12.0}, "diameter_mm": 6.0, "axis": "Z", "through": True, "depth_mm": None},
        {"center_mm": {"x": 71.0, "y": 25.0, "z": 12.0}, "diameter_mm": 6.0, "axis": "Z", "through": True, "depth_mm": None},
        {"center_mm": {"x": 97.0, "y": 25.0, "z": 12.0}, "diameter_mm": 6.0, "axis": "Z", "through": True, "depth_mm": None},
        {"center_mm": {"x": 45.0, "y": 95.0, "z": 12.0}, "diameter_mm": 6.0, "axis": "Z", "through": True, "depth_mm": None},
    ],
}

_POCKETED_BLOCK = {
    **_CUBE_10,
    "bbox_mm": {"X": 260.0, "Y": 140.0, "Z": 30.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "flat_ratio": 0.21429,
    "is_flat": True,
    "hole_count": 5,
    "hole_diameter_mm": 20.0,
    "hole_pitch_mm": 90.0,
    "hole_groups": [
        {"center_mm": {"x": 40.0, "y": 35.0, "z": 30.0}, "diameter_mm": 20.0, "axis": "Z", "through": True, "depth_mm": None},
        {"center_mm": {"x": 220.0, "y": 35.0, "z": 30.0}, "diameter_mm": 20.0, "axis": "Z", "through": True, "depth_mm": None},
        {"center_mm": {"x": 40.0, "y": 105.0, "z": 30.0}, "diameter_mm": 20.0, "axis": "Z", "through": True, "depth_mm": None},
        {"center_mm": {"x": 220.0, "y": 105.0, "z": 30.0}, "diameter_mm": 20.0, "axis": "Z", "through": True, "depth_mm": None},
        {"center_mm": {"x": 130.0, "y": 70.0, "z": 18.0}, "diameter_mm": 10.2, "axis": "Z", "through": False, "depth_mm": 6.0},
    ],
    "blind_hole_count": 1,
    "is_sheet_metal_by_faces": True,
    "measured_thickness_mm": 2.0,
    "bend_radius_mm": 5.1,
    "plane_face_count": 23,
    "cylinder_face_count": 5,
    "cone_face_count": 0,
    "flat_pattern": {
        "bend_count": 5,
        "k_factor_used": 0.5,
        "flat_length_mm": 557.396,
        "flat_width_mm": 140.0,
    },
    "pocket_count": 3,
    "pocket_groups": [
        {
            "axis": "Z",
            "depth_mm": 12.0,
            "length_mm": 120.0,
            "width_mm": 28.0,
            "center_mm": {"x": 130.0, "y": 70.0, "z": 18.0},
            "orientation": "H",
        },
        {
            "axis": "Z",
            "depth_mm": 14.0,
            "length_mm": 42.0,
            "width_mm": 30.0,
            "center_mm": {"x": 31.0, "y": 25.0, "z": 14.0},
            "orientation": "H",
        },
        {
            "axis": "Z",
            "depth_mm": 10.0,
            "length_mm": 50.0,
            "width_mm": 24.0,
            "center_mm": {"x": 232.0, "y": 70.0, "z": 20.0},
            "orientation": "V",
        },
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

    def test_rotational_shaft_is_turning(self):
        self.assertEqual(
            select_layout_profile_standalone("part.step", _SHAFT_FALSE_SHEET_METAL),
            "turning",
        )

    def test_stepped_shaft_is_turning(self):
        self.assertEqual(
            select_layout_profile_standalone("part.step", _STEPPED_SHAFT_FALSE_SHEET_METAL),
            "turning",
        )

    def test_path_override(self):
        self.assertEqual(select_layout_profile_standalone("Sheetmetals/part.step", _CUBE_10), "sheet_metal")

    def test_empty_payload_is_milling(self):
        self.assertEqual(select_layout_profile_standalone("part.step", {}), "milling")

    def test_compact_flat_plate_without_probe_evidence_is_milling(self):
        self.assertEqual(select_layout_profile_standalone("part.step", _COMPACT_FLAT_PLATE), "milling")

    def test_thick_rectangular_block_without_probe_evidence_is_milling(self):
        self.assertEqual(select_layout_profile_standalone("part.step", _THICK_RECT_BLOCK), "milling")

    def test_pocketed_flat_milling_sample_stays_milling(self):
        self.assertEqual(select_layout_profile_standalone("part.step", _POCKETED_BLOCK), "milling")


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

    def test_hole_diameter_rule_id_from_kb(self):
        """KB drives the hole_diameter gate — rule_id must be set by KB rule."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        hd = next(d for d in front.dimensions if d.dim_type == "hole_diameter")
        self.assertEqual(hd.rule_id, "hole_diameter_required")

    def test_hole_pitch_rule_id_from_kb(self):
        """KB drives the hole_pitch gate — rule_id must be set by KB rule."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        hp = next(d for d in front.dimensions if d.dim_type == "hole_pitch")
        self.assertEqual(hp.rule_id, "hole_location_required")

    def test_hole_location_rule_id_from_kb(self):
        """KB drives the hole_location gate — rule_id must be set by KB rule."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        hlx = next(d for d in front.dimensions if d.dim_type == "hole_location_x")
        self.assertEqual(hlx.rule_id, "hole_location_required")

    def test_thread_callout_rule_id_from_kb(self):
        """KB drives the thread_callout gate — rule_id must be set by KB rule."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        tc = next(d for d in front.dimensions if d.dim_type == "thread_callout")
        self.assertEqual(tc.rule_id, "thread_callout_required")

    def test_overall_dims_rule_id_from_kb(self):
        """KB drives overall dimension gates — rule_id must be set by KB rule."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        ol = next(d for d in front.dimensions if d.dim_type == "overall_length")
        self.assertEqual(ol.rule_id, "overall_dimensions_required")


class TestHoleDepthAndThreadCallouts(unittest.TestCase):
    def test_blind_hole_adds_depth_dimension_and_label(self):
        plan = build_dimension_plan(_BLIND_HOLE_BLOCK, "milling")
        front = next(v for v in plan.views if v.view_name == "Front")
        hole_dim = next(d for d in front.dimensions if d.dim_type == "hole_diameter")
        hole_depth = next(d for d in front.dimensions if d.dim_type == "hole_depth")
        self.assertEqual(hole_dim.label, "Ø10,0 x 12,0 TIEF")
        self.assertAlmostEqual(hole_depth.value_mm, 12.0)
        self.assertEqual(hole_depth.rule_id, "hole_callout_complete_for_special_holes")

    def test_through_hole_callout_marks_durch(self):
        plan = build_dimension_plan(_THROUGH_HOLE_BLOCK, "milling")
        front = next(v for v in plan.views if v.view_name == "Front")
        hole_dim = next(d for d in front.dimensions if d.dim_type == "hole_diameter")
        self.assertEqual(hole_dim.label, "Ø8,0 DURCH")
        self.assertFalse(any(d.dim_type == "hole_depth" for d in front.dimensions))

    def test_blind_thread_callout_includes_depth(self):
        plan = build_dimension_plan(_BLIND_THREAD_BLOCK, "milling")
        front = next(v for v in plan.views if v.view_name == "Front")
        thread = next(d for d in front.dimensions if d.dim_type == "thread_callout")
        self.assertEqual(thread.label, "M8 GEWINDE TIEF 10,0")
        self.assertEqual(thread.rule_id, "hole_blind_thread_depth")


class TestMillingSubtypeClassification(unittest.TestCase):
    def test_feature_dense_from_holes(self):
        self.assertEqual(classify_milling_subtype(_FLANGE), "feature_dense")

    def test_plate_2p5d_from_flat_ratio(self):
        payload = {**_CUBE_10, "flat_ratio": 0.2, "hole_count": 1, "slot_count": 0}
        self.assertEqual(classify_milling_subtype(payload), "plate_2p5d")

    def test_block_prismatic_default(self):
        payload = {**_CUBE_10, "flat_ratio": 0.8, "hole_count": 2, "slot_count": 1}
        self.assertEqual(classify_milling_subtype(payload), "block_prismatic")

    def test_plan_exposes_milling_subtype(self):
        plan = build_dimension_plan(_FLANGE, "milling")
        self.assertEqual(plan.milling_subtype, "feature_dense")


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

    def test_flat_pattern_has_only_overall_dims(self):
        fp = next(v for v in self.plan.views if v.view_name == "FlatPattern")
        types = {d.dim_type for d in fp.dimensions}
        self.assertEqual(types, {"flat_length", "flat_width"})

    def test_flat_length_rule_id_from_kb(self):
        """KB drives flat_length gate — rule_id must be set by KB rule."""
        fv = next(v for v in self.plan.views if v.view_name == "FlatPattern")
        fl = next(d for d in fv.dimensions if d.dim_type == "flat_length")
        self.assertEqual(fl.rule_id, "flat_pattern_dimensions_required")

    def test_flat_width_rule_id_from_kb(self):
        """KB drives flat_width gate — rule_id must be set by KB rule."""
        fv = next(v for v in self.plan.views if v.view_name == "FlatPattern")
        fw = next(d for d in fv.dimensions if d.dim_type == "flat_width")
        self.assertEqual(fw.rule_id, "flat_pattern_dimensions_required")

    def test_sheet_thickness_rule_id_from_kb(self):
        """KB drives sheet_thickness gate — rule_id must be set by KB rule."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        st = next(d for d in front.dimensions if d.dim_type == "sheet_thickness")
        self.assertEqual(st.rule_id, "sheet_thickness_required")


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

    def test_no_bend_radius_without_real_bends(self):
        fp = {
            **_SHEET_METAL,
            "bend_radius_mm": 4.0,
            "flat_pattern": {
                "bend_count": 0,
                "k_factor_used": 0.33,
                "flat_length_mm": 300.0,
                "flat_width_mm": 200.0,
            },
        }
        plan = build_dimension_plan(fp, "sheet_metal", unfold_result=None)
        front = next(v for v in plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertNotIn("bend_radius", types)


class TestTurningPlaceholder(unittest.TestCase):
    def setUp(self):
        fp = {**_CUBE_10, "bbox_mm": {"X": 100.0, "Y": 30.0, "Z": 30.0}}
        self.plan = build_dimension_plan(fp, "turning")

    def test_turning_has_overall(self):
        self.assertEqual(self.plan.part_type, "turning")
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("overall_length", types)
        self.assertIn("overall_height", types)

    def test_turning_diameter_rule_id_from_kb(self):
        """KB drives Ø-label on overall_height — rule_id must be turning_diameter_overall_required."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        oh = next(d for d in front.dimensions if d.dim_type == "overall_height")
        self.assertEqual(oh.rule_id, "turning_diameter_overall_required")

    def test_turning_overall_height_has_diameter_label(self):
        """overall_height on turning parts must carry the Ø symbol."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        oh = next(d for d in front.dimensions if d.dim_type == "overall_height")
        self.assertIn("Ø", oh.label or "")

    def test_simple_turning_subtype(self):
        self.assertEqual(self.plan.turning_subtype, "simple_rotational")


class TestTurningStepPlanning(unittest.TestCase):
    def test_turning_subtype_detects_stepped_shaft(self):
        self.assertEqual(classify_turning_subtype(_STEPPED_SHAFT_FALSE_SHEET_METAL), "stepped_shaft")

    def test_stepped_shaft_plans_cumulative_step_lengths(self):
        plan = build_dimension_plan(_STEPPED_SHAFT_FALSE_SHEET_METAL, "turning")
        front = next(v for v in plan.views if v.view_name == "Front")
        step_lengths = [d for d in front.dimensions if d.dim_type == "step_length"]
        self.assertEqual([round(float(d.value_mm or 0.0), 1) for d in step_lengths], [60.0, 82.0, 94.0, 140.0, 210.0])

    def test_stepped_shaft_plans_step_diameters_without_overall_repeat(self):
        plan = build_dimension_plan(_STEPPED_SHAFT_FALSE_SHEET_METAL, "turning")
        self.assertEqual(plan.turning_subtype, "stepped_shaft")
        front = next(v for v in plan.views if v.view_name == "Front")
        step_diameters = [d for d in front.dimensions if d.dim_type == "step_diameter"]
        self.assertEqual(
            [d.label for d in step_diameters],
            ["Ø48,0", "Ø36,0", "Ø24,0", "Ø32,0"],
        )


class TestTurningGrooveAndSurfacePlanning(unittest.TestCase):
    def test_turning_plan_includes_groove_callout_with_din_reference(self):
        plan = build_dimension_plan(_TURNING_WITH_RELIEF_GROOVE, "turning")
        front = next(v for v in plan.views if v.view_name == "Front")
        groove = next(d for d in front.dimensions if d.dim_type == "groove_callout")
        self.assertIn("FREISTICH", groove.label or "")
        self.assertIn("DIN 509", groove.label or "")
        self.assertIn("4,0", groove.label or "")
        self.assertIn("24,0", groove.label or "")

    def test_thread_without_relief_sets_policy_warning(self):
        payload = {
            **_TURNING_WITH_RELIEF_GROOVE,
            "groove_count": 0,
            "groove_groups": [],
            "thread_relief_recommended": True,
        }
        plan = build_dimension_plan(payload, "turning")
        self.assertIn("thread_relief_warning", plan.policy_hints)

    def test_surface_finish_model_and_process_note_are_emitted(self):
        plan = build_dimension_plan(_SURFACE_FINISH_BLOCK, "milling")
        note = next(n for n in plan.process_notes if n.note_type == "surface_finish")
        self.assertEqual(note.text, "Ra 3,2")
        self.assertIsNotNone(plan.surface_finish)
        self.assertEqual(plan.surface_finish.parameter, "RA")
        self.assertAlmostEqual(plan.surface_finish.value, 3.2)


class TestChamferPlanning(unittest.TestCase):
    def test_milling_plan_includes_grouped_chamfer_dimension(self):
        plan = build_dimension_plan(_CHAMFERED_BLOCK, "milling")
        front = next(v for v in plan.views if v.view_name == "Front")
        chamfer = next(d for d in front.dimensions if d.dim_type == "chamfer")
        self.assertEqual(chamfer.axis, "D")
        self.assertAlmostEqual(chamfer.value_mm, 1.0)
        self.assertEqual(chamfer.label, "4×1,0×45°")

    def test_turning_plan_can_emit_chamfer_dimension(self):
        payload = {
            **_CHAMFERED_BLOCK,
            "rotational_profile": True,
            "longest_axis": "Z",
        }
        plan = build_dimension_plan(payload, "turning")
        front = next(v for v in plan.views if v.view_name == "Front")
        self.assertTrue(any(d.dim_type == "chamfer" for d in front.dimensions))


class TestSectionPlanning(unittest.TestCase):
    def test_milling_blind_slot_requests_section_view(self):
        plan = build_dimension_plan(_BLIND_SLOT_BLOCK, "milling")
        self.assertEqual(len(plan.section_views), 1)
        section = plan.section_views[0]
        self.assertEqual(section.parent_view, "Front")
        self.assertEqual(section.cut_axis, "V")
        self.assertEqual(section.reason, "blind_slot_depth")

    def test_milling_blind_hole_requests_section_view(self):
        plan = build_dimension_plan(_BLIND_HOLE_BLOCK, "milling")
        self.assertEqual(len(plan.section_views), 1)
        section = plan.section_views[0]
        self.assertEqual(section.parent_view, "Front")
        self.assertEqual(section.cut_axis, "V")
        self.assertEqual(section.reason, "blind_hole_depth")

    def test_milling_mixed_blind_and_through_holes_do_not_force_section_view(self):
        payload = {
            **_BLIND_HOLE_BLOCK,
            "hole_count": 3,
            "hole_groups": [
                {
                    "center_mm": {"x": 30.0, "y": 20.0, "z": 24.0},
                    "diameter_mm": 8.0,
                    "axis": "Z",
                    "through": True,
                    "depth_mm": None,
                },
                {
                    "center_mm": {"x": 60.0, "y": 40.0, "z": 24.0},
                    "diameter_mm": 10.0,
                    "axis": "Z",
                    "through": False,
                    "depth_mm": 12.0,
                },
                {
                    "center_mm": {"x": 90.0, "y": 60.0, "z": 24.0},
                    "diameter_mm": 8.0,
                    "axis": "Z",
                    "through": True,
                    "depth_mm": None,
                },
            ],
        }
        plan = build_dimension_plan(payload, "milling")
        self.assertEqual(plan.section_views, [])

    def test_milling_multiple_blind_holes_do_not_force_section_view(self):
        payload = {
            **_BLIND_HOLE_BLOCK,
            "hole_count": 2,
            "hole_groups": [
                {
                    "center_mm": {"x": 35.0, "y": 25.0, "z": 24.0},
                    "diameter_mm": 10.0,
                    "axis": "Z",
                    "through": False,
                    "depth_mm": 12.0,
                },
                {
                    "center_mm": {"x": 85.0, "y": 55.0, "z": 24.0},
                    "diameter_mm": 10.0,
                    "axis": "Z",
                    "through": False,
                    "depth_mm": 12.0,
                },
            ],
        }
        plan = build_dimension_plan(payload, "milling")
        self.assertEqual(plan.section_views, [])

    def test_milling_multiple_blind_threaded_holes_do_not_force_section_view(self):
        payload = {
            **_BLIND_THREAD_BLOCK,
            "hole_count": 2,
            "hole_groups": [
                {
                    "center_mm": {"x": 35.0, "y": 25.0, "z": 24.0},
                    "diameter_mm": 8.0,
                    "axis": "Z",
                    "through": False,
                    "depth_mm": 10.0,
                },
                {
                    "center_mm": {"x": 85.0, "y": 55.0, "z": 24.0},
                    "diameter_mm": 8.0,
                    "axis": "Z",
                    "through": False,
                    "depth_mm": 10.0,
                },
            ],
            "thread_label": "M8",
            "thread_through": False,
            "thread_depth_mm": 10.0,
        }
        plan = build_dimension_plan(payload, "milling")
        self.assertEqual(plan.section_views, [])

    def test_turning_internal_bore_requests_section_view(self):
        payload = {
            **_CUBE_10,
            "bbox_mm": {"X": 40.0, "Y": 40.0, "Z": 120.0},
            "rotational_profile": True,
            "longest_axis": "Z",
            "hole_count": 1,
            "hole_diameter_mm": 18.0,
            "hole_groups": [
                {"center_mm": {"x": 0.0, "y": 0.0, "z": 60.0}, "diameter_mm": 18.0},
            ],
        }
        plan = build_dimension_plan(payload, "turning")
        self.assertEqual(len(plan.section_views), 1)
        section = plan.section_views[0]
        self.assertEqual(section.parent_view, "Front")
        self.assertEqual(section.cut_axis, "H")
        self.assertEqual(section.reason, "internal_bore")


class TestDetailViewPlanning(unittest.TestCase):
    def test_dense_front_pattern_requests_detail_view(self):
        plan = build_dimension_plan(_DENSE_DETAIL_BLOCK, "milling")
        self.assertEqual(len(plan.detail_views), 1)
        detail = plan.detail_views[0]
        self.assertEqual(detail.parent_view, "Front")
        self.assertEqual(detail.label, "Z")
        self.assertEqual(detail.reason, "dense_hole_pattern")

    def test_section_priority_suppresses_detail_view(self):
        payload = {
            **_DENSE_DETAIL_BLOCK,
            "slot_count": 1,
            "slot_groups": [
                {
                    "width_mm": 10.0,
                    "length_mm": 36.0,
                    "depth_mm": 5.0,
                    "center_mm": {"x": 130.0, "y": 60.0, "z": 19.0},
                    "orientation": "H",
                }
            ],
        }
        plan = build_dimension_plan(payload, "milling")
        self.assertEqual(len(plan.section_views), 1)
        self.assertEqual(plan.detail_views, [])


class TestDeduplication(unittest.TestCase):
    def test_policy_hints_include_kb_dimension_and_view_rules(self):
        plan = build_dimension_plan(_CUBE_10, "milling", detail_level=2)
        self.assertEqual(plan.policy_hints.get("front_view_rule_id"), "front_view_information_priority")
        self.assertEqual(plan.policy_hints.get("front_view_strategy"), "maximize_shape_information")
        self.assertTrue(plan.policy_hints.get("prefer_low_hidden_edge_load"))
        self.assertEqual(
            plan.policy_hints.get("layout_density_rule_id"),
            "dimension_density_requires_layout_escalation",
        )
        self.assertEqual(
            plan.policy_hints.get("detail_view_rule_id"),
            "detail_view_for_small_or_dense_features",
        )
        self.assertEqual(
            plan.policy_hints.get("section_clutter_rule_id"),
            "section_preferred_over_hidden_edge_clutter",
        )
        self.assertEqual(plan.policy_hints.get("dimension_chain_rule_id"), "avoid_closed_dimension_chains")
        self.assertTrue(plan.policy_hints.get("avoid_closed_dimension_chains"))

    def test_closed_chain_policy_prefers_top_for_depth(self):
        plan = build_dimension_plan(_CUBE_10, "milling", detail_level=2)
        top = next(v for v in plan.views if v.view_name == "Top")
        left = next(v for v in plan.views if v.view_name == "Left")
        self.assertTrue(any(d.dim_type == "overall_depth" for d in top.dimensions))
        self.assertFalse(any(d.dim_type == "overall_depth" for d in left.dimensions))

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

    def test_depth_prefers_top_view(self):
        """Closed-chain policy keeps depth on the most descriptive orthographic view."""
        plan = build_dimension_plan(_CUBE_10, "milling", detail_level=2)
        top = next(v for v in plan.views if v.view_name == "Top")
        left = next(v for v in plan.views if v.view_name == "Left")
        self.assertEqual(
            sum(1 for dim in top.dimensions if dim.dim_type == "overall_depth"),
            1,
        )
        self.assertEqual(
            sum(1 for dim in left.dimensions if dim.dim_type == "overall_depth"),
            0,
        )


class TestPolicyHints(unittest.TestCase):
    def test_kb_policy_hints_are_exposed(self):
        plan = build_dimension_plan(_FLANGE, "milling", detail_level=2)
        self.assertEqual(
            plan.policy_hints.get("front_view_rule_id"),
            "front_view_information_priority",
        )
        self.assertEqual(
            plan.policy_hints.get("dimension_view_rule_id"),
            "dimension_in_most_descriptive_view",
        )
        self.assertEqual(
            plan.policy_hints.get("dimension_chain_rule_id"),
            "avoid_closed_dimension_chains",
        )
        self.assertEqual(
            plan.policy_hints.get("layout_density_rule_id"),
            "dimension_density_requires_layout_escalation",
        )
        self.assertEqual(
            plan.policy_hints.get("detail_view_rule_id"),
            "detail_view_for_small_or_dense_features",
        )
        self.assertEqual(
            plan.policy_hints.get("section_clutter_rule_id"),
            "section_preferred_over_hidden_edge_clutter",
        )
        self.assertTrue(plan.policy_hints.get("prefer_low_hidden_edge_load"))
        self.assertTrue(plan.policy_hints.get("avoid_closed_dimension_chains"))


class TestSlotFeatures(unittest.TestCase):
    """Tests for slot (Langloch/Nut) dimension planning from slot_groups payload."""

    _SLOT_PART = {
        **{k: v for k, v in {
            "ok": True,
            "bbox_mm": {"X": 200.0, "Y": 100.0, "Z": 20.0},
            "longest_axis": "X",
            "thickness_axis": "Z",
            "hole_count": 0,
            "hole_diameter_mm": None,
            "hole_pitch_mm": None,
            "hole_groups": [],
            "bend_radius_mm": None,
            "measured_thickness_mm": None,
            "flat_ratio": 0.2,
            "thread_label": None,
            "flat_pattern": None,
        }.items()},
        "slot_count": 2,
        "slot_groups": [
            {"width_mm": 8.0, "length_mm": 30.0, "depth_mm": None,
             "center_mm": {"x": 50.0, "y": 50.0, "z": 0.0}, "orientation": "H"},
            {"width_mm": 8.0, "length_mm": 30.0, "depth_mm": None,
             "center_mm": {"x": 150.0, "y": 50.0, "z": 0.0}, "orientation": "H"},
        ],
    }

    def setUp(self):
        self.plan = build_dimension_plan(self._SLOT_PART, "milling")

    def test_has_slot_width(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("slot_width", types)

    def test_has_slot_length(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("slot_length", types)

    def test_has_slot_location(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("slot_location", types)

    def test_has_feature_count_for_multiple_slots(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("feature_count", types)

    def test_slot_width_value(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        sw = next(d for d in front.dimensions if d.dim_type == "slot_width")
        self.assertAlmostEqual(sw.value_mm, 8.0)

    def test_slot_length_value(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        sl = next(d for d in front.dimensions if d.dim_type == "slot_length")
        self.assertAlmostEqual(sl.value_mm, 30.0)

    def test_slot_width_rule_id_from_kb(self):
        """KB drives slot_width — rule_id must be slot_complete_definition."""
        front = next(v for v in self.plan.views if v.view_name == "Front")
        sw = next(d for d in front.dimensions if d.dim_type == "slot_width")
        self.assertEqual(sw.rule_id, "slot_complete_definition")

    def test_single_slot_no_feature_count(self):
        """A single slot must not emit a feature_count dimension."""
        single = {**self._SLOT_PART, "slot_count": 1, "slot_groups": [self._SLOT_PART["slot_groups"][0]]}
        plan = build_dimension_plan(single, "milling")
        front = next(v for v in plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertNotIn("feature_count", types)


class TestPocketFeatures(unittest.TestCase):
    def setUp(self):
        self.plan = build_dimension_plan(_POCKETED_BLOCK, "milling")

    def test_has_pocket_location_in_front(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        types = {d.dim_type for d in front.dimensions}
        self.assertIn("pocket_location", types)

    def test_has_pocket_depth_in_left(self):
        left = next(v for v in self.plan.views if v.view_name == "Left")
        types = {d.dim_type for d in left.dimensions}
        self.assertIn("pocket_depth", types)

    def test_pocket_uses_representative_largest_floor(self):
        front = next(v for v in self.plan.views if v.view_name == "Front")
        pocket_location = next(d for d in front.dimensions if d.dim_type == "pocket_location")
        self.assertAlmostEqual(pocket_location.value_mm, 120.0)
        self.assertIn("TASCHE", pocket_location.label or "")

    def test_pocket_depth_value(self):
        left = next(v for v in self.plan.views if v.view_name == "Left")
        pocket_depth = next(d for d in left.dimensions if d.dim_type == "pocket_depth")
        self.assertAlmostEqual(pocket_depth.value_mm, 12.0)
        self.assertEqual(pocket_depth.label, "TASCHE TIEF 12,0")

    def test_multiple_pockets_do_not_force_section_view(self):
        self.assertEqual(self.plan.section_views, [])

    def test_single_pocket_requests_section_view(self):
        payload = {
            **_POCKETED_BLOCK,
            "hole_count": 0,
            "hole_diameter_mm": None,
            "hole_pitch_mm": None,
            "hole_groups": [],
            "blind_hole_count": 0,
            "pocket_count": 1,
            "pocket_groups": [_POCKETED_BLOCK["pocket_groups"][0]],
        }
        plan = build_dimension_plan(payload, "milling")
        self.assertEqual(len(plan.section_views), 1)
        self.assertEqual(plan.section_views[0].reason, "internal_pocket_depth")


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


class TestOverrideModify(unittest.TestCase):
    def test_modify_dimension_label(self):
        plan = build_dimension_plan(_CUBE_10, "milling")
        front = next(v for v in plan.views if v.view_name == "Front")
        orig_dim = next(d for d in front.dimensions if d.dim_type == "overall_length")
        orig_label = orig_dim.label

        plan = apply_overrides(plan, [
            {
                "action": "modify",
                "target_view": "Front",
                "dim_type": "overall_length",
                "changes": {"label": "custom label", "priority": "should"},
            }
        ])
        front = next(v for v in plan.views if v.view_name == "Front")
        modified = next(d for d in front.dimensions if d.dim_type == "overall_length")
        self.assertEqual(modified.label, "custom label")
        self.assertEqual(modified.priority, "should")
        self.assertEqual(len(plan.overrides_applied), 1)

    def test_modify_without_target_view_skips(self):
        plan = build_dimension_plan(_CUBE_10, "milling")
        front = next(v for v in plan.views if v.view_name == "Front")
        orig_count = len(front.dimensions)

        plan = apply_overrides(plan, [
            {
                "action": "modify",
                "dim_type": "overall_length",
                "changes": {"label": "bad"},
            }
        ])
        front = next(v for v in plan.views if v.view_name == "Front")
        # Dimensions should be unchanged — modify without target_view is skipped
        self.assertEqual(len(front.dimensions), orig_count)
        modified = next(d for d in front.dimensions if d.dim_type == "overall_length")
        self.assertNotEqual(modified.label, "bad")


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
        self.assertIn("policy_hints", d)
        # Should be JSON-serializable
        import json
        json.dumps(d)


if __name__ == "__main__":
    unittest.main()

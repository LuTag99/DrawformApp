"""Guideline regression tests — validate DSE output against Bemassungsleitlinien.

Each test builds a dimension plan from a mock feature payload and verifies
that the plan satisfies the mandatory rules from the corresponding
Bemassungsleitlinie document.

Organized by part_type:
- Fraesteile (milling) — FRAESTEIL_BEMASSUNGSLEITLINIE_V1.md
- Blechteile (sheet_metal) — BLECHTEIL_BEMASSUNGSLEITLINIE_V1.md
- Drehteile (turning) — DREHTEIL_BEMASSUNGSLEITLINIE_V1.md
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from rules.dimension_plan_schema import DimensionPlan
from rules.dimension_strategy import build_dimension_plan, classify_milling_subtype

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dim_types(plan: DimensionPlan) -> set[str]:
    """Collect all dim_types across all views."""
    return {d.dim_type for v in plan.views for d in v.dimensions}


def _dims_in_view(plan: DimensionPlan, view_name: str) -> list:
    """Return dimensions for a specific view."""
    for v in plan.views:
        if v.view_name == view_name:
            return v.dimensions
    return []


def _has_dim_with_label_prefix(plan: DimensionPlan, prefix: str) -> bool:
    """Check if any dimension label starts with a prefix (e.g. 'Ø')."""
    for v in plan.views:
        for d in v.dimensions:
            if d.label and d.label.startswith(prefix):
                return True
    return False


def _note_types(plan: DimensionPlan) -> set[str]:
    """Collect all process note types."""
    return {n.note_type for n in plan.process_notes}


# ---------------------------------------------------------------------------
# Mock feature payloads
# ---------------------------------------------------------------------------

# -- Milling payloads --

_MILLING_PLATE_2P5D = {
    "ok": True,
    "bbox_mm": {"X": 200.0, "Y": 100.0, "Z": 10.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "hole_count": 4,
    "hole_diameter_mm": 8.0,
    "hole_pitch_mm": 60.0,
    "hole_groups": [
        {"center_mm": {"x": 40, "y": 50, "z": 5}, "diameter_mm": 8.0},
        {"center_mm": {"x": 100, "y": 50, "z": 5}, "diameter_mm": 8.0},
    ],
    "slot_count": 0,
    "slot_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 0.05,
    "is_flat": True,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 10,
    "cylinder_face_count": 4,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": None,
}

_MILLING_FEATURE_DENSE = {
    "ok": True,
    "bbox_mm": {"X": 250.0, "Y": 180.0, "Z": 30.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "hole_count": 12,
    "hole_diameter_mm": 10.0,
    "hole_pitch_mm": 40.0,
    "hole_groups": [
        {"center_mm": {"x": 30, "y": 90, "z": 15}, "diameter_mm": 10.0},
        {"center_mm": {"x": 70, "y": 90, "z": 15}, "diameter_mm": 10.0},
    ],
    "slot_count": 2,
    "slot_groups": [
        {"width_mm": 6.0, "length_mm": 20.0, "orientation": "H"},
    ],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 0.17,
    "is_flat": True,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 30,
    "cylinder_face_count": 12,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": "M8",
}

_MILLING_BLOCK_PRISMATIC = {
    "ok": True,
    "bbox_mm": {"X": 120.0, "Y": 80.0, "Z": 60.0},
    "longest_axis": "X",
    "thickness_axis": None,
    "hole_count": 2,
    "hole_diameter_mm": 12.0,
    "hole_pitch_mm": 70.0,
    "hole_groups": [
        {"center_mm": {"x": 25, "y": 40, "z": 30}, "diameter_mm": 12.0},
        {"center_mm": {"x": 95, "y": 40, "z": 30}, "diameter_mm": 12.0},
    ],
    "slot_count": 0,
    "slot_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 0.75,
    "is_flat": False,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 12,
    "cylinder_face_count": 2,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": None,
}

# -- Sheet metal payloads --

_SHEET_BIEGETEIL = {
    "ok": True,
    "bbox_mm": {"X": 300.0, "Y": 200.0, "Z": 2.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "hole_count": 4,
    "hole_diameter_mm": 6.5,
    "hole_pitch_mm": 120.0,
    "hole_groups": [
        {"center_mm": {"x": 50, "y": 100, "z": 1}, "diameter_mm": 6.5},
        {"center_mm": {"x": 170, "y": 100, "z": 1}, "diameter_mm": 6.5},
    ],
    "slot_count": 0,
    "slot_groups": [],
    "bend_radius_mm": 1.5,
    "measured_thickness_mm": 2.0,
    "flat_ratio": 0.007,
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

_SHEET_LASERTEIL = {
    "ok": True,
    "bbox_mm": {"X": 400.0, "Y": 250.0, "Z": 3.0},
    "longest_axis": "X",
    "thickness_axis": "Z",
    "hole_count": 6,
    "hole_diameter_mm": 8.0,
    "hole_pitch_mm": 80.0,
    "hole_groups": [
        {"center_mm": {"x": 60, "y": 125, "z": 1.5}, "diameter_mm": 8.0},
        {"center_mm": {"x": 140, "y": 125, "z": 1.5}, "diameter_mm": 8.0},
    ],
    "slot_count": 2,
    "slot_groups": [
        {"width_mm": 5.0, "length_mm": 15.0, "orientation": "H"},
    ],
    "bend_radius_mm": None,
    "measured_thickness_mm": 3.0,
    "flat_ratio": 0.012,
    "is_flat": True,
    "is_sheet_metal_by_faces": True,
    "plane_face_count": 20,
    "cylinder_face_count": 6,
    "cone_face_count": 0,
    "flat_pattern": {
        "bend_count": 0,
        "k_factor_used": None,
        "flat_length_mm": 400.0,
        "flat_width_mm": 250.0,
    },
    "thread_label": None,
}

# -- Turning payloads --

_TURNING_SIMPLE = {
    "ok": True,
    "bbox_mm": {"X": 30.0, "Y": 30.0, "Z": 100.0},
    "longest_axis": "Z",
    "thickness_axis": None,
    "hole_count": 0,
    "hole_diameter_mm": None,
    "hole_pitch_mm": None,
    "hole_groups": [],
    "slot_count": 0,
    "slot_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 1.0,
    "is_flat": False,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 2,
    "cylinder_face_count": 1,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": None,
    "rotational_profile": True,
}

_TURNING_STEPPED_SHAFT = {
    "ok": True,
    "bbox_mm": {"X": 50.0, "Y": 50.0, "Z": 200.0},
    "longest_axis": "Z",
    "thickness_axis": None,
    "hole_count": 0,
    "hole_diameter_mm": None,
    "hole_pitch_mm": None,
    "hole_groups": [
        {"center_mm": {"x": 0, "y": 0, "z": 0}, "diameter_mm": 50.0},
        {"center_mm": {"x": 0, "y": 0, "z": 80}, "diameter_mm": 30.0},
        {"center_mm": {"x": 0, "y": 0, "z": 160}, "diameter_mm": 20.0},
    ],
    "slot_count": 0,
    "slot_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 1.0,
    "is_flat": False,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 4,
    "cylinder_face_count": 3,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": None,
    "rotational_profile": True,
}

_TURNING_WITH_THREAD = {
    "ok": True,
    "bbox_mm": {"X": 40.0, "Y": 40.0, "Z": 150.0},
    "longest_axis": "Z",
    "thickness_axis": None,
    "hole_count": 0,
    "hole_diameter_mm": None,
    "hole_pitch_mm": None,
    "hole_groups": [],
    "slot_count": 0,
    "slot_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 1.0,
    "is_flat": False,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 3,
    "cylinder_face_count": 2,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": "M12",
    "rotational_profile": True,
}

_TURNING_WITH_HOLE = {
    "ok": True,
    "bbox_mm": {"X": 60.0, "Y": 60.0, "Z": 80.0},
    "longest_axis": "Z",
    "thickness_axis": None,
    "hole_count": 1,
    "hole_diameter_mm": 20.0,
    "hole_pitch_mm": None,
    "hole_groups": [
        {"center_mm": {"x": 0, "y": 0, "z": 40}, "diameter_mm": 20.0},
    ],
    "slot_count": 0,
    "slot_groups": [],
    "bend_radius_mm": None,
    "measured_thickness_mm": None,
    "flat_ratio": 1.0,
    "is_flat": False,
    "is_sheet_metal_by_faces": False,
    "plane_face_count": 3,
    "cylinder_face_count": 2,
    "cone_face_count": 0,
    "flat_pattern": None,
    "thread_label": None,
    "rotational_profile": True,
}


# ===========================================================================
# Fraesteil guideline tests
# ===========================================================================


class TestMillingGuideline(unittest.TestCase):
    """Verify milling DSE output against FRAESTEIL_BEMASSUNGSLEITLINIE_V1."""

    # --- Prio A: Aussenmasse ---

    def test_overall_dims_present_plate(self):
        plan = build_dimension_plan(_MILLING_PLATE_2P5D, "milling")
        types = _dim_types(plan)
        self.assertIn("overall_length", types, "Prio A: overall_length missing")
        self.assertIn("overall_height", types, "Prio A: overall_height missing")

    def test_overall_dims_present_block(self):
        plan = build_dimension_plan(_MILLING_BLOCK_PRISMATIC, "milling")
        types = _dim_types(plan)
        self.assertIn("overall_length", types)
        self.assertIn("overall_height", types)

    def test_third_overall_dim_milling(self):
        """Milling parts must expose a third overall size (depth)."""
        plan = build_dimension_plan(_MILLING_BLOCK_PRISMATIC, "milling")
        types = _dim_types(plan)
        self.assertIn("overall_depth", types, "Milling needs 3 overall dims")

    # --- Prio A: Bohrungen ---

    def test_hole_diameter_when_holes_present(self):
        plan = build_dimension_plan(_MILLING_PLATE_2P5D, "milling")
        types = _dim_types(plan)
        self.assertIn("hole_diameter", types, "Prio A: holes detected but no hole_diameter")

    def test_hole_pitch_when_multiple_holes(self):
        plan = build_dimension_plan(_MILLING_PLATE_2P5D, "milling")
        types = _dim_types(plan)
        self.assertIn("hole_pitch", types, "Prio A: 4 holes but no hole_pitch")

    def test_hole_location_when_holes_present(self):
        plan = build_dimension_plan(_MILLING_PLATE_2P5D, "milling")
        types = _dim_types(plan)
        self.assertIn("hole_location_x", types, "Prio A: hole_location_x missing")
        self.assertIn("hole_location_y", types, "Prio A: hole_location_y missing")

    # --- Prio A: Gewinde ---

    def test_thread_callout_when_thread_detected(self):
        plan = build_dimension_plan(_MILLING_FEATURE_DENSE, "milling")
        types = _dim_types(plan)
        self.assertIn("thread_callout", types, "Prio A: thread detected but no callout")

    # --- Prio A: Slots ---

    def test_slot_dims_when_slots_present(self):
        plan = build_dimension_plan(_MILLING_FEATURE_DENSE, "milling")
        types = _dim_types(plan)
        self.assertIn("slot_width", types, "Prio A: slot detected but no slot_width")
        self.assertIn("slot_length", types, "Prio A: slot detected but no slot_length")

    # --- No duplicate dims ---

    def test_no_duplicate_dims(self):
        """Leitlinie: Ein Mass nur einmal."""
        plan = build_dimension_plan(_MILLING_PLATE_2P5D, "milling")
        seen = set()
        for v in plan.views:
            for d in v.dimensions:
                if d.value_mm is not None:
                    key = (d.dim_type, d.value_mm)
                    self.assertNotIn(key, seen, f"Duplicate dimension: {key}")
                    seen.add(key)

    # --- Isometrie: keine Masse ---

    def test_iso_view_no_dimensions(self):
        """Leitlinie: Isometrie ist nur Uebersicht, nie Haupttraeger."""
        plan = build_dimension_plan(_MILLING_PLATE_2P5D, "milling")
        iso_dims = _dims_in_view(plan, "Iso")
        self.assertEqual(len(iso_dims), 0, "Iso view should have no dimensions")

    # --- Subtypklassifikation (Mindestregeln #1) ---

    def test_subtype_plate_2p5d(self):
        subtype = classify_milling_subtype(_MILLING_PLATE_2P5D)
        self.assertEqual(subtype, "plate_2p5d")

    def test_subtype_feature_dense(self):
        subtype = classify_milling_subtype(_MILLING_FEATURE_DENSE)
        self.assertEqual(subtype, "feature_dense")

    def test_subtype_block_prismatic(self):
        subtype = classify_milling_subtype(_MILLING_BLOCK_PRISMATIC)
        self.assertEqual(subtype, "block_prismatic")

    def test_milling_subtype_in_plan(self):
        """Mindestregeln #1: milling_subtype must be set in the plan."""
        plan = build_dimension_plan(_MILLING_PLATE_2P5D, "milling")
        self.assertIsNotNone(plan.milling_subtype)

    # --- Datum system (Mindestregeln #7) ---

    def test_datum_system_populated(self):
        """Leitlinie: Bezugssystem ist Pflicht."""
        plan = build_dimension_plan(_MILLING_BLOCK_PRISMATIC, "milling")
        ds = plan.datum_system
        self.assertIsNotNone(ds.A, "Datum A must be set")


# ===========================================================================
# Blechteil guideline tests
# ===========================================================================


class TestSheetMetalGuideline(unittest.TestCase):
    """Verify sheet_metal DSE output against BLECHTEIL_BEMASSUNGSLEITLINIE_V1."""

    # --- Prio A: Aussenmasse ---

    def test_overall_dims_present_biegeteil(self):
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        types = _dim_types(plan)
        self.assertIn("overall_length", types)
        self.assertIn("overall_height", types)

    def test_overall_dims_present_laserteil(self):
        plan = build_dimension_plan(_SHEET_LASERTEIL, "sheet_metal",
                                    unfold_result={"bend_count": 0})
        types = _dim_types(plan)
        self.assertIn("overall_length", types)
        self.assertIn("overall_height", types)

    # --- Prio A: Materialdicke ---

    def test_thickness_note_present(self):
        """Leitlinie: Materialdicke ist Pflicht."""
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        note_types = _note_types(plan)
        self.assertIn("thickness", note_types, "Prio A: thickness process note missing")

    # --- Prio A: Biegeradius ---

    def test_bend_radius_in_plan(self):
        """Leitlinie: Biegeradius ist Prio A fuer Biegeteile."""
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        types = _dim_types(plan)
        self.assertIn("bend_radius", types, "Prio A: bend_radius missing for biegeteil")

    # --- Flat pattern dimensions ---

    def test_flat_pattern_dims_for_biegeteil(self):
        """Flat pattern dims require unfold_result with ok=True and actual dimensions."""
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={
                                        "ok": True, "bend_count": 2,
                                        "flat_length_mm": 310.0, "flat_width_mm": 200.0,
                                    })
        types = _dim_types(plan)
        self.assertIn("flat_length", types, "Biegeteil needs flat_length")
        self.assertIn("flat_width", types, "Biegeteil needs flat_width")

    # --- Prio A: Bohrungen ---

    def test_hole_diameter_when_holes_present(self):
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        types = _dim_types(plan)
        self.assertIn("hole_diameter", types, "Prio B: holes detected but no diameter")

    # --- No duplicate dims ---

    def test_no_duplicate_dims(self):
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        seen = set()
        for v in plan.views:
            for d in v.dimensions:
                if d.value_mm is not None:
                    key = (d.dim_type, d.value_mm)
                    self.assertNotIn(key, seen, f"Duplicate: {key}")
                    seen.add(key)

    # --- K-factor note for biegeteil ---

    def test_k_factor_note_present(self):
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        note_types = _note_types(plan)
        self.assertIn("k_factor", note_types, "K-factor note expected for biegeteil")

    # --- Inner radius note ---

    def test_inner_radius_note(self):
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        note_types = _note_types(plan)
        self.assertIn("inner_radius", note_types, "Inner radius note expected")

    # --- Hole pitch and location (Prio B) ---

    def test_hole_pitch_when_multiple_holes(self):
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        types = _dim_types(plan)
        self.assertIn("hole_pitch", types, "Prio B: 4 holes but no hole_pitch")

    def test_hole_location_when_holes_present(self):
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        types = _dim_types(plan)
        self.assertIn("hole_location_x", types, "hole_location_x missing")
        self.assertIn("hole_location_y", types, "hole_location_y missing")

    # --- Laserteil: no bend notes ---

    def test_laserteil_no_bend_radius(self):
        """Laserteil (0 bends) should NOT have bend_radius."""
        plan = build_dimension_plan(_SHEET_LASERTEIL, "sheet_metal",
                                    unfold_result={"bend_count": 0})
        types = _dim_types(plan)
        self.assertNotIn("bend_radius", types, "Laserteil should have no bend_radius")

    def test_laserteil_no_k_factor_note(self):
        """Laserteil should NOT have k_factor process note."""
        plan = build_dimension_plan(_SHEET_LASERTEIL, "sheet_metal",
                                    unfold_result={"bend_count": 0})
        note_types = _note_types(plan)
        self.assertNotIn("k_factor", note_types, "Laserteil should have no k_factor")


# ===========================================================================
# Drehteil guideline tests
# ===========================================================================


class TestTurningGuideline(unittest.TestCase):
    """Verify turning DSE output against DREHTEIL_BEMASSUNGSLEITLINIE_V1."""

    # --- Prio A: Gesamtmasse ---

    def test_overall_length_present(self):
        plan = build_dimension_plan(_TURNING_SIMPLE, "turning")
        types = _dim_types(plan)
        self.assertIn("overall_length", types, "Prio A: Gesamtlaenge missing")

    def test_overall_diameter_present(self):
        """Leitlinie: Groesster Aussendurchmesser als Ø-Mass."""
        plan = build_dimension_plan(_TURNING_SIMPLE, "turning")
        types = _dim_types(plan)
        self.assertIn("overall_height", types, "Prio A: Gesamtdurchmesser missing")

    def test_diameter_has_symbol(self):
        """Leitlinie: Durchmesser als Ø, nie als Radius."""
        plan = build_dimension_plan(_TURNING_SIMPLE, "turning")
        self.assertTrue(
            _has_dim_with_label_prefix(plan, "\u00D8"),
            "Turning diameter must use Ø symbol"
        )

    # --- Prio A: Gewinde ---

    def test_thread_callout_when_thread_detected(self):
        plan = build_dimension_plan(_TURNING_WITH_THREAD, "turning")
        types = _dim_types(plan)
        self.assertIn("thread_callout", types, "Prio A: thread detected but no callout")

    # --- Prio A: Bohrungen ---

    def test_hole_diameter_when_hole_present(self):
        plan = build_dimension_plan(_TURNING_WITH_HOLE, "turning")
        types = _dim_types(plan)
        self.assertIn("hole_diameter", types, "Prio A: hole detected but no diameter")

    # --- Stepped shaft ---

    def test_stepped_shaft_has_both_overall_dims(self):
        plan = build_dimension_plan(_TURNING_STEPPED_SHAFT, "turning")
        types = _dim_types(plan)
        self.assertIn("overall_length", types)
        self.assertIn("overall_height", types)

    # --- No duplicate dims ---

    def test_no_duplicate_dims(self):
        plan = build_dimension_plan(_TURNING_SIMPLE, "turning")
        seen = set()
        for v in plan.views:
            for d in v.dimensions:
                if d.value_mm is not None:
                    key = (d.dim_type, d.value_mm)
                    self.assertNotIn(key, seen, f"Duplicate: {key}")
                    seen.add(key)

    # --- Iso view: keine Masse ---

    def test_iso_view_no_dimensions(self):
        plan = build_dimension_plan(_TURNING_SIMPLE, "turning")
        iso_dims = _dims_in_view(plan, "Iso")
        self.assertEqual(len(iso_dims), 0)

    # --- Front view dominance ---

    def test_all_dims_on_front_view(self):
        """For simple turning parts, all dims should be on Front."""
        plan = build_dimension_plan(_TURNING_SIMPLE, "turning")
        front_dims = _dims_in_view(plan, "Front")
        all_dims = [d for v in plan.views for d in v.dimensions]
        self.assertEqual(
            len(front_dims), len(all_dims),
            "Simple turning: all dims should be on Front view"
        )

    # --- Mittellinie (Mindestregeln #8) ---

    def test_front_view_has_centerlines(self):
        """Leitlinie: Mittellinie (Drehachse) ist verpflichtend."""
        plan = build_dimension_plan(_TURNING_SIMPLE, "turning")
        front = next((v for v in plan.views if v.view_name == "Front"), None)
        self.assertIsNotNone(front)
        self.assertTrue(front.show_centerlines, "Front view must show centerlines")

    # --- Diameter symbol on all turning diameters ---

    def test_hole_diameter_uses_symbol(self):
        """Leitlinie: Durchmesser als Ø."""
        plan = build_dimension_plan(_TURNING_WITH_HOLE, "turning")
        hole_dims = [d for v in plan.views for d in v.dimensions
                     if d.dim_type == "hole_diameter"]
        for d in hole_dims:
            self.assertTrue(
                d.label and d.label.startswith("\u00D8"),
                f"hole_diameter label must start with Ø, got: {d.label}"
            )


# ===========================================================================
# Cross-cutting guideline tests (apply to all part types)
# ===========================================================================


class TestCrossCuttingGuideline(unittest.TestCase):
    """Rules that apply across all Bemassungsleitlinien."""

    def _check_plan(self, plan: DimensionPlan):
        # Every plan must have at least one view with dimensions
        total = sum(len(v.dimensions) for v in plan.views)
        self.assertGreater(total, 0, "Plan must have at least one dimension")

        # No None dim_types
        for v in plan.views:
            for d in v.dimensions:
                self.assertIsNotNone(d.dim_type, "dim_type must not be None")

        # No negative value_mm
        for v in plan.views:
            for d in v.dimensions:
                if d.value_mm is not None:
                    self.assertGreater(d.value_mm, 0, f"Negative dim: {d.dim_type}={d.value_mm}")

    def test_milling_plan_valid(self):
        plan = build_dimension_plan(_MILLING_PLATE_2P5D, "milling")
        self._check_plan(plan)

    def test_sheet_metal_plan_valid(self):
        plan = build_dimension_plan(_SHEET_BIEGETEIL, "sheet_metal",
                                    unfold_result={"bend_count": 2})
        self._check_plan(plan)

    def test_turning_plan_valid(self):
        plan = build_dimension_plan(_TURNING_SIMPLE, "turning")
        self._check_plan(plan)

    def test_tolerance_note_all_types(self):
        """All part types should get a tolerance process note (if KB available)."""
        for fp, profile in [
            (_MILLING_PLATE_2P5D, "milling"),
            (_SHEET_BIEGETEIL, "sheet_metal"),
            (_TURNING_SIMPLE, "turning"),
        ]:
            unfold = {"bend_count": 2} if profile == "sheet_metal" else None
            plan = build_dimension_plan(fp, profile, unfold_result=unfold)
            # Tolerance note is KB-driven; if KB is loaded, it should be present
            if plan.policy_hints:
                note_types = _note_types(plan)
                self.assertIn(
                    "tolerance", note_types,
                    f"{profile}: tolerance note missing (KB loaded but no note)"
                )

    def test_detail_level_2_has_edge_note(self):
        """detail_level >= 2 should include edge_note (Entgrathinweis)."""
        for fp, profile in [
            (_MILLING_PLATE_2P5D, "milling"),
            (_SHEET_BIEGETEIL, "sheet_metal"),
            (_TURNING_SIMPLE, "turning"),
        ]:
            unfold = {"bend_count": 2} if profile == "sheet_metal" else None
            plan = build_dimension_plan(fp, profile, unfold_result=unfold,
                                        detail_level=2)
            if plan.policy_hints:
                note_types = _note_types(plan)
                self.assertIn(
                    "edge_note", note_types,
                    f"{profile}: edge_note missing at detail_level=2 (KB loaded)"
                )

    def test_detail_level_2_has_more_dims(self):
        """detail_level=2 should produce >= as many dims as detail_level=1."""
        plan_1 = build_dimension_plan(_MILLING_BLOCK_PRISMATIC, "milling",
                                      detail_level=1)
        plan_2 = build_dimension_plan(_MILLING_BLOCK_PRISMATIC, "milling",
                                      detail_level=2)
        count_1 = sum(len(v.dimensions) for v in plan_1.views)
        count_2 = sum(len(v.dimensions) for v in plan_2.views)
        self.assertGreaterEqual(count_2, count_1,
                                "detail_level=2 should have >= dims as level=1")


if __name__ == "__main__":
    unittest.main()

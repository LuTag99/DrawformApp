"""Targeted unit tests for step_feature_probe helper heuristics."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

try:
    from freecad.step_feature_probe import (
        _detect_turning_relief_grooves,
        _extract_surface_finish_from_step_metadata,
    )
    _FREECAD_PROBE_AVAILABLE = True
except ModuleNotFoundError:
    _FREECAD_PROBE_AVAILABLE = False


class _BBox:
    XMin = -20.0
    XMax = 20.0
    YMin = -20.0
    YMax = 20.0
    ZMin = 0.0
    ZMax = 140.0


@unittest.skipUnless(_FREECAD_PROBE_AVAILABLE, "FreeCAD probe helpers unavailable in this Python environment")
class TestStepFeatureProbeHelpers(unittest.TestCase):
    def test_detect_turning_relief_groove_from_local_minimum(self):
        step_profile = [
            {"axis": "Z", "diameter_mm": 30.0, "start_mm": 0.0, "end_mm": 58.0, "length_mm": 58.0},
            {"axis": "Z", "diameter_mm": 24.0, "start_mm": 58.0, "end_mm": 62.0, "length_mm": 4.0},
            {"axis": "Z", "diameter_mm": 30.0, "start_mm": 62.0, "end_mm": 140.0, "length_mm": 78.0},
        ]
        grooves = _detect_turning_relief_grooves(_BBox(), step_profile, "Z", thread_label="M20")
        self.assertEqual(len(grooves), 1)
        groove = grooves[0]
        self.assertEqual(groove["kind"], "freistich")
        self.assertEqual(groove["din_ref"], "DIN 509")
        self.assertAlmostEqual(float(groove["width_mm"]), 4.0)
        self.assertAlmostEqual(float(groove["diameter_mm"]), 24.0)

    def test_extract_surface_finish_from_step_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            step_path = Path(temp_dir) / "surface_note.stp"
            step_path.write_text(
                "ISO-10303-21;\nDATA;\n#100=DESCRIPTIVE_REPRESENTATION_ITEM('Ra 3.2','');\nENDSEC;\nEND-ISO-10303-21;\n",
                encoding="utf-8",
            )
            surface_finish = _extract_surface_finish_from_step_metadata(step_path)
        self.assertIsNotNone(surface_finish)
        self.assertEqual(surface_finish["parameter"], "RA")
        self.assertAlmostEqual(float(surface_finish["value"]), 3.2)


if __name__ == "__main__":
    unittest.main()

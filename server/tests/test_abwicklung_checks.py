from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from test_views import check_abwicklung


def _base_report() -> dict:
    return {
        "abwicklung": {
            "source": "sheetmetal_unfold",
            "outline_bounds": [100.0, 50.0, 220.0, 130.0],
            "dim_h_endpoints": [100.0, 220.0],
            "dim_v_endpoints": [50.0, 130.0],
            "dim_h_label_mm": 160.0,
            "dim_v_label_mm": 80.0,
            "model_fl_mm": 160.0,
            "model_fw_mm": 80.0,
            "bend_count": 2,
            "bend_line_count": 2,
            "bend_legend_count": 0,
            "drawing_area": [10.0, 10.0, 400.0, 220.0],
            "flange_dims": [
                {"axis": "x", "start": 100.0, "end": 130.0, "label_mm": 40.0},
                {"axis": "x", "start": 130.0, "end": 190.0, "label_mm": 80.0},
                {"axis": "x", "start": 190.0, "end": 220.0, "label_mm": 40.0},
            ],
        }
    }


class TestAbwicklungChecks(unittest.TestCase):
    def test_accepts_clean_abwicklung_without_bend_legend(self):
        ok, issues = check_abwicklung(_base_report(), {"has_abwicklung": True})

        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_rejects_bend_legend_texts(self):
        report = _base_report()
        report["abwicklung"]["bend_legend_count"] = 2

        ok, issues = check_abwicklung(report, {"has_abwicklung": True})

        self.assertFalse(ok)
        self.assertTrue(any("bend legend texts" in issue for issue in issues))

    def test_rejects_missing_bend_lines(self):
        report = _base_report()
        report["abwicklung"]["bend_line_count"] = 1

        ok, issues = check_abwicklung(report, {"has_abwicklung": True})

        self.assertFalse(ok)
        self.assertTrue(any("Bend line mismatch" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()

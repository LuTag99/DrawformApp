from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from test_views import check_dimension_plan


def _base_report():
    return {
        "dimension_plan": {
            "part_type": "milling",
            "views": [
                {
                    "view_name": "Front",
                    "dimensions": [
                        {"dim_type": "overall_length", "value_mm": 40.0},
                        {"dim_type": "overall_height", "value_mm": 20.0},
                        {"dim_type": "chamfer", "value_mm": 1.0},
                    ],
                }
            ],
        },
        "features": {
            "groove_count": 0,
            "chamfer_count": 2,
        },
        "views": {
            "Front": {
                "feature_dim_types": ["chamfer"],
            }
        },
    }


class TestCheckDimensionPlan(unittest.TestCase):
    def test_accepts_rendered_chamfer_feature_type(self):
        ok, issues = check_dimension_plan(_base_report(), {"dse_check": True, "part_type": "milling"})
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_rejects_missing_rendered_chamfer_feature_type(self):
        report = _base_report()
        report["views"]["Front"]["feature_dim_types"] = []
        ok, issues = check_dimension_plan(report, {"dse_check": True, "part_type": "milling"})
        self.assertFalse(ok)
        self.assertTrue(any("chamfer feature_dim_type" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()

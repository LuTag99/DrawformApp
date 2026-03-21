from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from test_views import check_dim_quality


def _base_report():
    return {
        "pre_export_check": {
            "dim_metrics": {
                "dim_text_count": 4,
                "step_dim_count": 0,
                "feature_dim_present": True,
                "labels_in_bounds": True,
                "feature_dim_outside_views": ["Left"],
                "feature_dim_internal_views": [],
                "outside_preferred_feature_views": [],
                "overall_geom_overlap_views": [],
                "feature_geom_overlap_views": [],
                "feature_overall_overlap_views": [],
                "text_overlap_views": [],
            }
        }
    }


class TestCheckDimQuality(unittest.TestCase):
    def test_accepts_outside_feature_dimensions(self):
        ok, issues = check_dim_quality(
            _base_report(),
            {"min_dim_text_count": 2, "feature_dims_required": True},
        )
        self.assertTrue(ok)
        self.assertEqual(issues, [])

    def test_rejects_labels_outside_page(self):
        report = _base_report()
        report["pre_export_check"]["dim_metrics"]["labels_in_bounds"] = False
        ok, issues = check_dim_quality(report, {})
        self.assertFalse(ok)
        self.assertTrue(any("labels_in_bounds" in issue for issue in issues))

    def test_rejects_internal_feature_dimensions_when_outside_preferred(self):
        report = _base_report()
        report["pre_export_check"]["dim_metrics"]["outside_preferred_feature_views"] = ["Left"]
        ok, issues = check_dim_quality(report, {"feature_dims_required": True})
        self.assertFalse(ok)
        self.assertTrue(any("feature_dims_outside" in issue for issue in issues))

    def test_rejects_feature_dimensions_over_geometry(self):
        report = _base_report()
        report["pre_export_check"]["dim_metrics"]["feature_geom_overlap_views"] = ["Front"]
        ok, issues = check_dim_quality(report, {"strict_dim_arrangement": True})
        self.assertFalse(ok)
        self.assertTrue(any("feature_dims_overlap_geometry" in issue for issue in issues))

    def test_rejects_text_collisions(self):
        report = _base_report()
        report["pre_export_check"]["dim_metrics"]["text_overlap_views"] = ["Front"]
        ok, issues = check_dim_quality(report, {})
        self.assertFalse(ok)
        self.assertTrue(any("dimension_text_overlap" in issue for issue in issues))

    def test_feature_geometry_overlap_is_warning_only_without_strict_gate(self):
        report = _base_report()
        report["pre_export_check"]["dim_metrics"]["feature_geom_overlap_views"] = ["Front"]
        ok, issues = check_dim_quality(report, {})
        self.assertTrue(ok)
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()

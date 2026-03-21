from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
FREECAD_HELPER_DIR = SERVER_DIR / "freecad"
if str(FREECAD_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(FREECAD_HELPER_DIR))

from dimension_placement_helpers import should_place_feature_dims_outside


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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent.parent
FREECAD_HELPER_DIR = SERVER_DIR / "freecad"
if str(FREECAD_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(FREECAD_HELPER_DIR))

from svg_transform_helpers import (
    svg_uses_y_flip,
    transform_svg_bounds_for_display,
    transform_svg_y_for_display,
)


class TestSvgTransformHelpers(unittest.TestCase):
    def test_detects_inner_y_flip_group(self):
        svg = '<g transform="scale(1, -1)"><path d="M 0 -40 L 10 0" /></g>'

        self.assertTrue(svg_uses_y_flip(svg))

    def test_transforms_bounds_for_display_when_y_is_flipped(self):
        bounds = (0.0, 78.89, -40.0, 0.0)

        transformed = transform_svg_bounds_for_display(bounds, flip_y=True)

        self.assertEqual(transformed, (0.0, 78.89, -0.0, 40.0))

    def test_transforms_single_y_value_for_display(self):
        self.assertEqual(transform_svg_y_for_display(-20.0, flip_y=True), 20.0)
        self.assertEqual(transform_svg_y_for_display(-20.0, flip_y=False), -20.0)


if __name__ == "__main__":
    unittest.main()

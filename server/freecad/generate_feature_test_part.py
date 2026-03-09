#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate a deterministic STEP sample with clear geometric features."""

from __future__ import annotations

import sys
from pathlib import Path

import FreeCAD as App
import Part


def build_feature_part() -> Part.Shape:
    # Base block: 260 x 140 x 30 mm
    shape = Part.makeBox(260.0, 140.0, 30.0, App.Vector(0, 0, 0))

    # 4 through holes (diameter 20 mm) to validate hole detection.
    for x in (40.0, 220.0):
        for y in (35.0, 105.0):
            hole = Part.makeCylinder(10.0, 30.0, App.Vector(x, y, 0), App.Vector(0, 0, 1))
            shape = shape.cut(hole)

    # Top rectangular pocket (depth 12 mm).
    shape = shape.cut(Part.makeBox(120.0, 28.0, 12.0, App.Vector(70.0, 56.0, 18.0)))

    # Front rectangular pocket (depth 14 mm).
    shape = shape.cut(Part.makeBox(42.0, 30.0, 14.0, App.Vector(10.0, 10.0, 0.0)))

    # Side pocket for additional non-circular feature complexity.
    shape = shape.cut(Part.makeBox(24.0, 50.0, 10.0, App.Vector(220.0, 45.0, 20.0)))

    # M12 threaded hole (represented as tap drill + lead-in chamfer).
    # In STEP test geometry, thread is typically not modeled as full helix.
    # Core hole for M12x1.75 is approx. 10.2 mm.
    thread_center = App.Vector(130.0, 70.0, 30.0)
    core_hole = Part.makeCylinder(5.1, 18.0, thread_center, App.Vector(0, 0, -1))
    lead_in = Part.makeCone(6.0, 5.1, 1.5, thread_center, App.Vector(0, 0, -1))
    shape = shape.cut(core_hole.fuse(lead_in))
    return shape


def export_step(output_path: Path):
    doc = App.newDocument("FeatureTestPart")
    try:
        obj = doc.addObject("Part::Feature", "FeaturePart")
        obj.Shape = build_feature_part()
        doc.recompute()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Part.export([obj], str(output_path))
    finally:
        App.closeDocument(doc.Name)


def main() -> int:
    if len(sys.argv) > 1:
        output_path = Path(sys.argv[1])
    else:
        output_path = Path(__file__).resolve().parent.parent / "_samples" / "feature_test_part.stp"
    export_step(output_path)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

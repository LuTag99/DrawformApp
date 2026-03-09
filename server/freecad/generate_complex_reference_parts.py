#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Generate deterministic complex STEP reference parts for regression tests."""

from __future__ import annotations

import sys
from pathlib import Path

import FreeCAD as App
import Part


def build_slot_cutout(
    origin: App.Vector,
    length: float,
    width: float,
    depth: float,
) -> Part.Shape:
    """Build a rounded slot solid (Z-up) suitable for subtraction."""
    radius = width * 0.5
    z_axis = App.Vector(0, 0, 1)
    spine = Part.makeBox(max(0.001, length - width), width, depth, origin)
    c1 = Part.makeCylinder(radius, depth, App.Vector(origin.x + radius, origin.y + radius, origin.z), z_axis)
    c2 = Part.makeCylinder(
        radius,
        depth,
        App.Vector(origin.x + length - radius, origin.y + radius, origin.z),
        z_axis,
    )
    return spine.fuse(c1).fuse(c2)


def build_complex_bracket() -> Part.Shape:
    shape = Part.makeBox(220.0, 140.0, 24.0, App.Vector(0, 0, 0))
    shape = shape.fuse(Part.makeBox(24.0, 140.0, 120.0, App.Vector(0, 0, 24.0)))
    shape = shape.fuse(Part.makeBox(50.0, 18.0, 70.0, App.Vector(24.0, 20.0, 24.0)))
    shape = shape.fuse(Part.makeBox(50.0, 18.0, 70.0, App.Vector(24.0, 102.0, 24.0)))

    slot = build_slot_cutout(App.Vector(90.0, 60.0, 0.0), length=100.0, width=20.0, depth=24.0)
    shape = shape.cut(slot)

    for x in (55.0, 165.0):
        for y in (35.0, 105.0):
            shape = shape.cut(Part.makeCylinder(7.0, 24.0, App.Vector(x, y, 0.0), App.Vector(0, 0, 1)))

    for z in (68.0, 118.0):
        shape = shape.cut(Part.makeCylinder(6.0, 24.0, App.Vector(0.0, 70.0, z), App.Vector(1, 0, 0)))

    shape = shape.cut(Part.makeBox(24.0, 42.0, 34.0, App.Vector(0.0, 49.0, 80.0)))
    return shape.removeSplitter()


def build_flanged_manifold() -> Part.Shape:
    shape = Part.makeBox(180.0, 110.0, 70.0, App.Vector(0, 0, 0))
    shape = shape.fuse(Part.makeCylinder(55.0, 15.0, App.Vector(-15.0, 55.0, 35.0), App.Vector(1, 0, 0)))
    shape = shape.fuse(Part.makeCylinder(55.0, 15.0, App.Vector(180.0, 55.0, 35.0), App.Vector(1, 0, 0)))
    shape = shape.cut(Part.makeCylinder(20.0, 210.0, App.Vector(-15.0, 55.0, 35.0), App.Vector(1, 0, 0)))

    for y, z in ((25.0, 15.0), (85.0, 15.0), (25.0, 55.0), (85.0, 55.0)):
        shape = shape.cut(Part.makeCylinder(6.0, 210.0, App.Vector(-15.0, y, z), App.Vector(1, 0, 0)))

    for x in (42.0, 90.0, 138.0):
        shape = shape.cut(Part.makeCylinder(5.0, 70.0, App.Vector(x, 55.0, 0.0), App.Vector(0, 0, 1)))
        shape = shape.cut(Part.makeCylinder(9.0, 16.0, App.Vector(x, 55.0, 54.0), App.Vector(0, 0, 1)))

    shape = shape.cut(Part.makeCylinder(8.0, 110.0, App.Vector(90.0, 0.0, 35.0), App.Vector(0, 1, 0)))
    shape = shape.cut(Part.makeBox(82.0, 36.0, 18.0, App.Vector(49.0, 37.0, 52.0)))
    return shape.removeSplitter()


def build_stepped_shaft() -> Part.Shape:
    shape = Part.makeCylinder(24.0, 60.0, App.Vector(0, 0, 0), App.Vector(1, 0, 0))
    shape = shape.fuse(Part.makeCylinder(18.0, 80.0, App.Vector(60.0, 0, 0), App.Vector(1, 0, 0)))
    shape = shape.fuse(Part.makeCylinder(12.0, 70.0, App.Vector(140.0, 0, 0), App.Vector(1, 0, 0)))
    shape = shape.fuse(Part.makeCylinder(16.0, 40.0, App.Vector(210.0, 0, 0), App.Vector(1, 0, 0)))
    shape = shape.fuse(Part.makeCylinder(32.0, 12.0, App.Vector(82.0, 0, 0), App.Vector(1, 0, 0)))

    shape = shape.cut(Part.makeCylinder(8.0, 250.0, App.Vector(0.0, 0, 0), App.Vector(1, 0, 0)))
    for x in (40.0, 170.0):
        shape = shape.cut(Part.makeCylinder(6.0, 80.0, App.Vector(x, -40.0, 0), App.Vector(0, 1, 0)))

    shape = shape.cut(Part.makeBox(66.0, 10.0, 8.0, App.Vector(148.0, -5.0, 10.0)))
    shape = shape.cut(Part.makeCylinder(5.0, 20.0, App.Vector(250.0, 0, 0), App.Vector(-1, 0, 0)))
    return shape.removeSplitter()


def build_u_channel_assembly() -> Part.Shape:
    shape = Part.makeBox(260.0, 120.0, 6.0, App.Vector(0, 0, 0))
    shape = shape.fuse(Part.makeBox(260.0, 6.0, 70.0, App.Vector(0, 0, 6.0)))
    shape = shape.fuse(Part.makeBox(260.0, 6.0, 70.0, App.Vector(0, 114.0, 6.0)))
    shape = shape.fuse(Part.makeBox(260.0, 20.0, 6.0, App.Vector(0, 6.0, 70.0)))
    shape = shape.fuse(Part.makeBox(260.0, 20.0, 6.0, App.Vector(0, 94.0, 70.0)))

    for x in (35.0, 110.0, 185.0):
        slot = build_slot_cutout(App.Vector(x, 50.0, 0.0), length=42.0, width=12.0, depth=6.0)
        shape = shape.cut(slot)

    for x in (45.0, 130.0, 215.0):
        for y in (0.0, 114.0):
            shape = shape.cut(Part.makeCylinder(5.0, 6.0, App.Vector(x, y, 32.0), App.Vector(0, 1, 0)))
            shape = shape.cut(Part.makeCylinder(5.0, 6.0, App.Vector(x, y, 50.0), App.Vector(0, 1, 0)))

    shape = shape.cut(Part.makeBox(40.0, 108.0, 30.0, App.Vector(110.0, 6.0, 22.0)))
    return shape.removeSplitter()


def build_mounting_panel_complex() -> Part.Shape:
    shape = Part.makeBox(320.0, 180.0, 12.0, App.Vector(0, 0, 0))

    for x in (38.0, 160.0, 282.0):
        for y in (30.0, 90.0, 150.0):
            shape = shape.cut(Part.makeCylinder(5.0, 12.0, App.Vector(x, y, 0.0), App.Vector(0, 0, 1)))

    shape = shape.cut(Part.makeBox(28.0, 12.0, 12.0, App.Vector(18.0, 84.0, 0.0)))
    shape = shape.cut(Part.makeBox(28.0, 12.0, 12.0, App.Vector(274.0, 84.0, 0.0)))

    shape = shape.cut(Part.makeBox(180.0, 80.0, 6.0, App.Vector(70.0, 50.0, 6.0)))

    for x, y in ((24.0, 24.0), (296.0, 24.0), (24.0, 156.0), (296.0, 156.0)):
        shape = shape.cut(Part.makeCylinder(4.0, 12.0, App.Vector(x, y, 0.0), App.Vector(0, 0, 1)))
        shape = shape.cut(Part.makeCylinder(8.0, 4.0, App.Vector(x, y, 8.0), App.Vector(0, 0, 1)))
    return shape.removeSplitter()


def export_part(shape: Part.Shape, part_name: str, output_dir: Path):
    doc = App.newDocument(f"Sample_{part_name}")
    try:
        obj = doc.addObject("Part::Feature", part_name)
        obj.Shape = shape
        doc.recompute()
        output_dir.mkdir(parents=True, exist_ok=True)
        Part.export([obj], str(output_dir / f"{part_name}.stp"))
    finally:
        App.closeDocument(doc.Name)


def generate_samples(output_dir: Path):
    builders = {
        "complex_bracket": build_complex_bracket,
        "flanged_manifold": build_flanged_manifold,
        "stepped_shaft": build_stepped_shaft,
        "u_channel_assembly": build_u_channel_assembly,
        "mounting_panel_complex": build_mounting_panel_complex,
    }
    for name, builder in builders.items():
        export_part(builder(), name, output_dir)


def main() -> int:
    if len(sys.argv) > 1:
        output_dir = Path(sys.argv[1])
    else:
        output_dir = Path(__file__).resolve().parent.parent / "_samples"
    generate_samples(output_dir)
    print(f"Generated reference parts in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

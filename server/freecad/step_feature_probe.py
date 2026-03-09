#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Extract lightweight geometric features from a CAD file for analyzer jobs."""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

import FreeCAD as App
import Part


def vec_axis_value(vector: App.Vector, axis: str) -> float:
    if axis == "X":
        return float(vector.x)
    if axis == "Y":
        return float(vector.y)
    return float(vector.z)


def center_key(center: App.Vector, thickness_axis: str) -> tuple[float, float]:
    if thickness_axis == "X":
        return (round(float(center.y), 3), round(float(center.z), 3))
    if thickness_axis == "Y":
        return (round(float(center.x), 3), round(float(center.z), 3))
    return (round(float(center.x), 3), round(float(center.y), 3))


def _axis_direction_vector(axis_name: str) -> App.Vector:
    """Return the unit vector for a named world axis."""
    if axis_name == "X":
        return App.Vector(1, 0, 0)
    if axis_name == "Y":
        return App.Vector(0, 1, 0)
    return App.Vector(0, 0, 1)


def _axes_are_parallel(v1: App.Vector, v2: App.Vector, tol_deg: float = 15.0) -> bool:
    """Return True if two vectors are parallel or anti-parallel within tol_deg."""
    len1 = v1.Length
    len2 = v2.Length
    if len1 < 1e-9 or len2 < 1e-9:
        return False
    cos_theta = abs(v1.dot(v2) / (len1 * len2))  # abs() covers anti-parallel
    return cos_theta >= math.cos(math.radians(tol_deg))


def collect_circle_data(shape: Part.Shape, thickness_axis: str):
    grouped: dict[tuple[float, float], dict[str, object]] = {}
    all_diameters: list[float] = []
    thickness_vec = _axis_direction_vector(thickness_axis)

    for edge in shape.Edges:
        curve = getattr(edge, "Curve", None)
        if curve is None:
            continue
        curve_name = curve.__class__.__name__
        if curve_name not in {"Circle", "ArcOfCircle"}:
            continue

        radius = float(getattr(curve, "Radius", 0.0) or 0.0)
        center = getattr(curve, "Center", None)
        if radius <= 1e-6 or center is None:
            continue

        # Filter: arc must span ≥50% of the full circumference.
        # Accepts: full holes (100%), slot semicircular ends (180° = 50%).
        # Rejects: bend arcs (90° = 25%), edge fillets/chamfers (<45%).
        expected_circ = 2.0 * math.pi * radius
        edge_length = float(getattr(edge, "Length", expected_circ) or expected_circ)
        if edge_length < expected_circ * 0.50:
            continue

        diameter = radius * 2.0
        key = center_key(center, thickness_axis)
        bucket = grouped.setdefault(
            key,
            {
                "center": center,
                "diameters": [],
            },
        )
        bucket["diameters"].append(diameter)
        all_diameters.append(diameter)

    unique_centers: list[tuple[App.Vector, float]] = []
    for item in grouped.values():
        center = item["center"]
        diameters = item["diameters"]
        mean_diameter = float(sum(diameters) / max(len(diameters), 1))
        unique_centers.append((center, mean_diameter))
    return unique_centers, all_diameters


def collect_cylindrical_radii(shape: Part.Shape) -> list[float]:
    radii: list[float] = []
    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        if surface is None:
            continue
        if surface.__class__.__name__ != "Cylinder":
            continue
        radius = float(getattr(surface, "Radius", 0.0) or 0.0)
        if radius > 1e-6:
            radii.append(radius)
    return radii


def measure_wall_thickness(shape: Part.Shape) -> float | None:
    """
    Find the actual sheet metal wall thickness using two strategies:

    1. **Cylinder pairs** (primary for bent parts): Find pairs of cylindrical faces
       sharing the same axis direction and center line but different radii. The radius
       difference (outer - inner) equals the wall thickness. This works reliably on
       sheet metal bends where antiparallel plane pairs measure flange-to-flange
       distance instead of wall thickness.

    2. **Antiparallel planes** (fallback): Find the minimum perpendicular distance
       between antiparallel planar face pairs.

    Returns the minimum plausible thickness in mm, or None if no valid pair found.
    """
    # --- Strategy 1: Cylinder radius difference (best for bent sheet metal) ---
    cylinders: list[tuple[App.Vector, App.Vector, float]] = []  # (axis_dir, center_pt, radius)
    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        if surface is None or surface.__class__.__name__ != "Cylinder":
            continue
        axis = getattr(surface, "Axis", None)
        center = getattr(surface, "Center", None)
        radius = getattr(surface, "Radius", None)
        if axis is None or center is None or radius is None or radius <= 0:
            continue
        a_len = axis.Length
        if a_len < 1e-9:
            continue
        unit_axis = App.Vector(axis.x / a_len, axis.y / a_len, axis.z / a_len)
        cylinders.append((unit_axis, center, float(radius)))

    cyl_thickness = None
    axis_tol = math.cos(math.radians(5.0))
    for i in range(len(cylinders)):
        a1, c1, r1 = cylinders[i]
        for j in range(i + 1, len(cylinders)):
            a2, c2, r2 = cylinders[j]
            # Must share the same axis direction (parallel or anti-parallel)
            dot = abs(a1.dot(a2))
            if dot < axis_tol:
                continue
            # Must share approximately the same center line
            delta = c2.sub(c1)
            perp_dist = delta.sub(a1.multiply(delta.dot(a1))).Length
            if perp_dist > max(r1, r2) * 0.3:
                continue  # centers too far apart — different bend
            rdiff = abs(r1 - r2)
            if rdiff < 0.1 or rdiff > 10.0:
                continue  # too small (same surface) or too large (not wall thickness)
            if cyl_thickness is None or rdiff < cyl_thickness:
                cyl_thickness = rdiff

    if cyl_thickness is not None and cyl_thickness <= 10.0:
        return round(cyl_thickness, 2)

    # --- Strategy 2: Antiparallel plane face pairs (fallback) ---
    plane_faces: list[tuple[App.Vector, App.Vector]] = []
    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        if surface is None or surface.__class__.__name__ != "Plane":
            continue
        normal = getattr(surface, "Axis", None)
        if normal is None:
            continue
        n_len = normal.Length
        if n_len < 1e-9:
            continue
        unit_normal = App.Vector(normal.x / n_len, normal.y / n_len, normal.z / n_len)
        try:
            pt = face.CenterOfMass
        except Exception:
            continue
        plane_faces.append((unit_normal, pt))

    if len(plane_faces) < 2:
        return None

    min_distance = None
    anti_tol = math.cos(math.radians(5.0))  # normals within 5° of anti-parallel
    for i in range(len(plane_faces)):
        n1, pt1 = plane_faces[i]
        for j in range(i + 1, len(plane_faces)):
            n2, pt2 = plane_faces[j]
            if n1.dot(n2) > -anti_tol:
                continue  # not anti-parallel (same side or perpendicular)
            delta = pt2.sub(pt1)
            dist = abs(delta.dot(n1))
            if dist < 0.05:
                continue  # co-planar faces (< 0.05mm apart), skip
            if min_distance is None or dist < min_distance:
                min_distance = dist

    # Only accept plane-based thickness if plausible for sheet metal (≤10mm)
    if min_distance is not None and min_distance <= 10.0:
        return round(min_distance, 2)

    return round(min_distance, 2) if min_distance is not None else None


def classify_face_types(shape: Part.Shape) -> dict:
    """Count faces by surface type to characterise the part geometry."""
    counts: dict[str, int] = {
        "plane": 0,
        "cylinder": 0,
        "cone": 0,
        "torus": 0,
        "other": 0,
        "total": 0,
    }
    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        name = surface.__class__.__name__ if surface is not None else "other"
        key = name.lower()
        if key not in counts:
            key = "other"
        counts[key] += 1
        counts["total"] += 1
    return counts


def detect_bend_direction(cyl_face, shape: Part.Shape) -> str:
    """
    Determine if a cylindrical bend face goes NACH OBEN or NACH UNTEN.
    Strategy: compare the face's center of mass Z-coordinate to the shape's mid-Z.
    Bends whose center of mass is above the shape center are considered OBEN.
    """
    try:
        com = cyl_face.CenterOfMass
        bbox = shape.BoundBox
        shape_mid_z = (bbox.ZMax + bbox.ZMin) / 2.0
        return "OBEN" if com.z > shape_mid_z else "UNTEN"
    except Exception:
        return "OBEN"


def compute_flat_pattern(shape: Part.Shape, thickness_axis: str, measured_thickness: float | None, k_factor_override: float | None = None) -> dict | None:
    """
    Compute a mathematical flat pattern for a sheet metal part without the SheetMetal module.

    Uses:
    - Plane faces (flanges/segments): measure extent perpendicular to thickness axis
    - Cylinder faces (bends): compute bend allowance via K-factor formula
      bend_allowance = (R + K * t) * angle_rad
      K = 0.33 for R/t < 2 (tight bend), K = 0.50 for R/t >= 2 (gradual bend)

    Returns a dict with flat_length_mm, flat_width_mm, bend_segments, or None on failure.
    """
    if measured_thickness is None or measured_thickness < 0.1:
        return None

    t = measured_thickness
    thickness_vec = _axis_direction_vector(thickness_axis)

    # --- Collect flat (wall/flange) face extents ---
    # Group faces by their normal direction (±22.5° buckets) and take ONE max extent
    # per direction.  This prevents a single flange that is split into many sub-faces
    # (by holes, notches, edges) from being summed multiple times.
    normal_buckets: dict[tuple, list[float]] = {}
    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        if surface is None or surface.__class__.__name__ != "Plane":
            continue
        normal = getattr(surface, "Axis", None)
        if normal is None or normal.Length < 1e-9:
            continue
        unit_n = App.Vector(normal.x / normal.Length, normal.y / normal.Length, normal.z / normal.Length)
        dot_with_thickness = abs(unit_n.dot(thickness_vec))
        if dot_with_thickness > math.cos(math.radians(75.0)):
            # Normal mostly aligned with thickness = top/bottom sheet face, skip
            continue
        try:
            bb = face.BoundBox
        except Exception:
            continue
        if thickness_axis == "X":
            extent = max(bb.YLength, bb.ZLength)
        elif thickness_axis == "Y":
            extent = max(bb.XLength, bb.ZLength)
        else:
            extent = max(bb.XLength, bb.YLength)
        # Quantize normal to ~22.5° buckets (0.25 grid); abs() merges parallel+anti-parallel
        abs_key = (
            round(abs(unit_n.x) * 4) / 4,
            round(abs(unit_n.y) * 4) / 4,
            round(abs(unit_n.z) * 4) / 4,
        )
        normal_buckets.setdefault(abs_key, []).append(extent)

    # One representative extent per unique flange direction (the largest face in that direction)
    flat_extents: list[float] = [
        max(extents) for extents in normal_buckets.values() if max(extents) > t * 0.5
    ]

    # --- Collect bend (Cylinder) faces ---
    bend_segments: list[dict] = []
    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        if surface is None or surface.__class__.__name__ != "Cylinder":
            continue
        radius = float(getattr(surface, "Radius", 0.0) or 0.0)
        if radius < t * 0.4:
            continue  # too small to be a bend (likely a bore/hole surface)
        # Large radius relative to thickness = bore/hole wall surface, not a bend
        if radius > t * 10.0:
            continue

        # Estimate subtended angle from face area: Area = radius * angle_rad * arc_height
        try:
            area = face.Area
            bb = face.BoundBox
        except Exception:
            continue
        if thickness_axis == "X":
            arc_height = bb.YLength if bb.YLength >= bb.ZLength else bb.ZLength
        elif thickness_axis == "Y":
            arc_height = bb.XLength if bb.XLength >= bb.ZLength else bb.ZLength
        else:
            arc_height = bb.XLength if bb.XLength >= bb.YLength else bb.YLength
        if arc_height < 1e-6:
            continue
        # Thin cylinder surface = edge fillet, not a bend (bend zone width > 1.5× thickness)
        if arc_height < t * 1.5:
            continue
        angle_rad = area / (radius * arc_height)
        angle_rad = min(max(angle_rad, 0.01), math.pi)
        angle_deg = math.degrees(angle_rad)

        # K-factor selection
        r_over_t = radius / t
        if k_factor_override is not None:
            k = float(k_factor_override)
        else:
            k = 0.33 if r_over_t < 2.0 else 0.50
        bend_allowance = (radius + k * t) * angle_rad

        direction = detect_bend_direction(face, shape)
        bend_segments.append({
            "radius_mm": round(radius, 3),
            "angle_deg": round(angle_deg, 1),
            "allowance_mm": round(bend_allowance, 3),
            "k_factor": round(k, 3),
            "direction": direction,
        })

    if not flat_extents and not bend_segments:
        return None

    total_segments_mm = sum(flat_extents)
    total_allowance_mm = sum(seg["allowance_mm"] for seg in bend_segments)
    flat_length_mm = total_segments_mm + total_allowance_mm

    # Flat width = the dimension perpendicular to the unfolding direction
    bbox = shape.BoundBox
    if thickness_axis == "X":
        flat_width_mm = min(bbox.YLength, bbox.ZLength)
    elif thickness_axis == "Y":
        flat_width_mm = min(bbox.XLength, bbox.ZLength)
    else:
        flat_width_mm = min(bbox.XLength, bbox.YLength)

    # Only trust the result for simple geometries (≤4 bends, all near-90°)
    # Tolerance 30° avoids false "complex" flags for slight deviations from 90°
    complex_geometry = len(bend_segments) > 4 or any(
        abs(seg["angle_deg"] - 90.0) > 30.0 for seg in bend_segments
    )

    # Sort flat_extents descending so the largest flanges come first.
    # When n_bends = n_extents - 1, the sorted order approximates the positional
    # order for simple "ladder" sheet metal parts (largest flange = base).
    flat_extents_sorted = sorted(flat_extents, reverse=True)

    return {
        "flat_length_mm": round(flat_length_mm, 3),
        "flat_width_mm": round(flat_width_mm, 3),
        "total_segments_mm": round(total_segments_mm, 3),
        "total_allowance_mm": round(total_allowance_mm, 3),
        "flat_extents": [round(e, 3) for e in flat_extents_sorted],
        "bend_count": len(bend_segments),
        "bend_segments": bend_segments,
        "complex_geometry": complex_geometry,
        "k_factor_used": bend_segments[0].get("k_factor") if bend_segments else None,
    }


def infer_metric_thread_label(core_diameter_mm: float | None) -> str | None:
    if core_diameter_mm is None or core_diameter_mm <= 0:
        return None
    candidates = [
        ("M5", 4.2),
        ("M6", 5.0),
        ("M8", 6.8),
        ("M10", 8.5),
        ("M12", 10.2),
        ("M16", 14.0),
        ("M20", 17.5),
    ]
    best = min(candidates, key=lambda item: abs(item[1] - core_diameter_mm))
    if abs(best[1] - core_diameter_mm) <= 0.6:
        return best[0]
    return None


def compute_payload(shape: Part.Shape, k_factor_override: float | None = None) -> dict:
    bbox = shape.BoundBox
    dims = {
        "X": float(bbox.XLength),
        "Y": float(bbox.YLength),
        "Z": float(bbox.ZLength),
    }
    ordered_axes = sorted(dims.items(), key=lambda item: item[1], reverse=True)
    longest_axis = ordered_axes[0][0]
    thickness_axis = ordered_axes[2][0]
    mid = max(ordered_axes[1][1], 1e-6)
    flat_ratio = ordered_axes[2][1] / mid
    is_flat = flat_ratio < 0.3

    unique_centers, all_diameters = collect_circle_data(shape, thickness_axis)
    hole_count = len(unique_centers)

    hole_diameter_mm = None
    if all_diameters:
        hole_diameter_mm = float(statistics.median(all_diameters))

    hole_groups = [
        {
            "center_mm": {
                "x": round(float(center.x), 5),
                "y": round(float(center.y), 5),
                "z": round(float(center.z), 5),
            },
            "diameter_mm": round(float(diameter), 5),
        }
        for center, diameter in unique_centers
    ]
    unique_diameters = sorted({round(float(diameter), 4) for _, diameter in unique_centers})
    thread_core_diameter_mm = None
    if len(unique_diameters) >= 2:
        smallest = float(min(unique_diameters))
        largest = float(max(unique_diameters))
        if smallest < largest * 0.78:
            thread_core_diameter_mm = smallest
    thread_label = infer_metric_thread_label(thread_core_diameter_mm)

    # Suppress thread detection on thin sheet metal parts: a thread needs
    # minimum engagement depth ≈ nominal_diameter * 0.5. If measured wall
    # thickness is known and too thin, the "thread" is actually a through-hole.
    measured_thickness_for_thread = measure_wall_thickness(shape)
    if thread_label and measured_thickness_for_thread is not None:
        # Extract nominal diameter from thread label (e.g. "M8" -> 8.0)
        try:
            nom_dia = float(thread_label[1:])
            min_engagement = nom_dia * 0.5
            if measured_thickness_for_thread < min_engagement:
                thread_label = None
                thread_core_diameter_mm = None
        except (ValueError, IndexError):
            pass

    hole_pitch_mm = None
    if hole_count >= 2:
        positions = [vec_axis_value(center, longest_axis) for center, _ in unique_centers]
        span = max(positions) - min(positions)
        if span > 1e-4:
            hole_pitch_mm = float(span)

    cylindrical_radii = collect_cylindrical_radii(shape)
    bend_radius_mm = None
    if cylindrical_radii:
        thickness = max(ordered_axes[2][1], 1e-6)
        filtered = [radius for radius in cylindrical_radii if radius >= thickness * 0.5]
        candidates = filtered or cylindrical_radii
        bend_radius_mm = float(min(candidates))

    # Face-type classification for sheet metal detection
    face_types = classify_face_types(shape)
    total_faces = max(face_types["total"], 1)
    plane_fraction = face_types["plane"] / total_faces
    is_sheet_metal_by_faces = (
        plane_fraction >= 0.60           # predominantly flat faces
        and face_types["cylinder"] >= 1  # at least one bend (cylinder face)
        and face_types["cone"] <= 2      # no complex machined surfaces
        and face_types["torus"] <= 1
    )

    # Actual wall thickness via anti-parallel plane face pair distances
    measured_thickness_mm = measure_wall_thickness(shape)

    # Flat pattern computation (for sheet metal parts)
    flat_pattern = compute_flat_pattern(shape, thickness_axis, measured_thickness_mm, k_factor_override)

    return {
        "ok": True,
        "bbox_mm": {axis: round(value, 5) for axis, value in dims.items()},
        "axis_order": [axis for axis, _ in ordered_axes],
        "longest_axis": longest_axis,
        "thickness_axis": thickness_axis,
        "flat_ratio": round(flat_ratio, 5),
        "is_flat": is_flat,
        "hole_count": hole_count,
        "hole_diameter_mm": round(hole_diameter_mm, 5) if hole_diameter_mm else None,
        "hole_pitch_mm": round(hole_pitch_mm, 5) if hole_pitch_mm else None,
        "hole_groups": hole_groups,
        "hole_diameters_mm": unique_diameters,
        "thread_core_diameter_mm": round(thread_core_diameter_mm, 5) if thread_core_diameter_mm else None,
        "thread_label": thread_label,
        "bend_radius_mm": round(bend_radius_mm, 5) if bend_radius_mm else None,
        "circular_edge_count": len(all_diameters),
        "cylindrical_face_count": len(cylindrical_radii),
        # Sheet metal characterisation fields
        "plane_face_count": face_types["plane"],
        "cylinder_face_count": face_types["cylinder"],
        "cone_face_count": face_types["cone"],
        "plane_fraction": round(plane_fraction, 5),
        "is_sheet_metal_by_faces": is_sheet_metal_by_faces,
        "measured_thickness_mm": round(measured_thickness_mm, 5) if measured_thickness_mm is not None else None,
        "flat_pattern": flat_pattern,
    }


def write_json(output_path: Path, payload: dict):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: step_feature_probe.py <input.step> <output.json>")
        return 1

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        write_json(output_path, {"ok": False, "error": f"Input file not found: {input_path}"})
        return 2

    # Optional k_factor override from environment variable (set by main.py via metadata)
    import os
    k_factor_override: float | None = None
    k_env = os.environ.get("DRAWFORM_K_FACTOR", "").strip()
    if k_env:
        try:
            k_factor_override = float(k_env)
        except ValueError:
            pass

    try:
        shape = Part.Shape()
        shape.read(str(input_path))
        if shape.isNull():
            write_json(output_path, {"ok": False, "error": "Imported shape is null."})
            return 3
        payload = compute_payload(shape, k_factor_override=k_factor_override)
        write_json(output_path, payload)
        return 0
    except Exception as exc:
        write_json(output_path, {"ok": False, "error": f"Feature probe failed: {exc}"})
        return 4


if __name__ == "__main__":
    sys.exit(main())

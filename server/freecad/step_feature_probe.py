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


def _cylinder_face_angle_span(face: Part.Face) -> float:
    try:
        u0, u1, _v0, _v1 = face.ParameterRange
        return abs(float(u1) - float(u0))
    except (AttributeError, TypeError, ValueError):
        return 0.0


def _cylinder_face_is_internal(face: Part.Face, center: App.Vector, axis: App.Vector) -> bool:
    try:
        u0, u1, v0, v1 = face.ParameterRange
        u_mid = (float(u0) + float(u1)) * 0.5
        v_mid = (float(v0) + float(v1)) * 0.5
        point = face.valueAt(u_mid, v_mid)
        normal = face.normalAt(u_mid, v_mid)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return False

    axis_len_sq = axis.dot(axis)
    if axis_len_sq <= 1e-9:
        return False
    axis_point = center.add(axis.multiply(axis.dot(point.sub(center)) / axis_len_sq))
    radial = point.sub(axis_point)
    if radial.Length <= 1e-9:
        return False
    return normal.dot(radial) < 0.0


def collect_edge_circle_data(shape: Part.Shape, thickness_axis: str):
    grouped: dict[tuple[float, float], dict[str, object]] = {}
    all_diameters: list[float] = []

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

    circle_groups: list[dict[str, object]] = []
    for item in grouped.values():
        center = item["center"]
        diameters = sorted({
            round(float(diameter), 5)
            for diameter in item["diameters"]
            if float(diameter) > 1e-6
        })
        if not diameters:
            continue
        circle_groups.append(
            {
                "center": center,
                "diameters": diameters,
            }
        )
    return circle_groups, all_diameters


def collect_internal_cylinder_circle_data(shape: Part.Shape, thickness_axis: str):
    grouped: dict[tuple[float, float], dict[str, object]] = {}
    thickness_vec = _axis_direction_vector(thickness_axis)

    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        if surface is None or surface.__class__.__name__ != "Cylinder":
            continue
        radius = float(getattr(surface, "Radius", 0.0) or 0.0)
        center = getattr(surface, "Center", None)
        axis = getattr(surface, "Axis", None)
        if radius <= 1e-6 or center is None or axis is None:
            continue
        if not _axes_are_parallel(axis, thickness_vec):
            continue
        if not _cylinder_face_is_internal(face, center, axis):
            continue

        # Filter: individual face arc must span ≥8° to exclude degenerate slivers.
        # Faces are grouped by center location; the GROUP total must reach 300°
        # (see below). The 8° per-face minimum filters numerical noise from
        # tiny split faces while allowing multi-face holes to accumulate coverage.
        angle_span = _cylinder_face_angle_span(face)
        if angle_span < math.radians(8.0):
            continue

        diameter = radius * 2.0
        key = center_key(center, thickness_axis)
        bucket = grouped.setdefault(
            key,
            {
                "centers": [],
                "diameters": [],
                "angle_span_total": 0.0,
            },
        )
        bucket["centers"].append(center)
        bucket["diameters"].append(diameter)
        bucket["angle_span_total"] += angle_span

    circle_groups: list[dict[str, object]] = []
    all_diameters: list[float] = []
    for item in grouped.values():
        # 300° ≈ 83% of full circle — rejects partial cylindrical surfaces
        # (e.g. 180° half-shells, 90° quarter-bends) while accepting holes
        # split into multiple faces by adjacent features.
        if float(item.get("angle_span_total") or 0.0) < math.radians(300.0):
            continue
        centers = [center for center in item.get("centers", []) if isinstance(center, App.Vector)]
        if not centers:
            continue
        center = App.Vector(
            sum(float(candidate.x) for candidate in centers) / len(centers),
            sum(float(candidate.y) for candidate in centers) / len(centers),
            sum(float(candidate.z) for candidate in centers) / len(centers),
        )
        diameters = sorted({
            round(float(diameter), 5)
            for diameter in item["diameters"]
            if float(diameter) > 1e-6
        })
        if not diameters:
            continue
        all_diameters.append(float(sum(diameters) / len(diameters)))
        circle_groups.append(
            {
                "center": center,
                "diameters": diameters,
            }
        )
    return circle_groups, all_diameters


def _hole_centers_from_circle_groups(
    circle_groups: list[dict[str, object]],
) -> list[tuple[App.Vector, float]]:
    hole_centers: list[tuple[App.Vector, float]] = []
    for group in circle_groups:
        center = group.get("center")
        diameters = group.get("diameters") or []
        if not isinstance(center, App.Vector) or not diameters:
            continue
        mean_diameter = float(sum(float(value) for value in diameters) / len(diameters))
        hole_centers.append((center, mean_diameter))
    return hole_centers


def _prefer_internal_cylinder_groups(
    edge_groups: list[dict[str, object]],
    edge_diameters: list[float],
    internal_groups: list[dict[str, object]],
    dims: dict[str, float],
    longest_axis: str,
    flat_ratio: float,
) -> bool:
    if flat_ratio >= 0.30 or not internal_groups:
        return False

    edge_holes = _hole_centers_from_circle_groups(edge_groups)
    internal_holes = _hole_centers_from_circle_groups(internal_groups)
    if not edge_holes:
        return bool(internal_holes)
    if len(internal_holes) < 3:
        return False

    edge_pitch = _infer_linear_hole_pitch(edge_holes, longest_axis)
    internal_pitch = _infer_linear_hole_pitch(internal_holes, longest_axis)
    if edge_pitch is None and internal_pitch is not None:
        return True

    edge_dom = _dominant_group_diameter(edge_holes)
    if edge_dom is None or not edge_diameters:
        return False
    edge_max = max(float(value) for value in edge_diameters)
    transverse_axes = _transverse_axes(longest_axis)
    cross_max = max((float(dims.get(axis, 0.0)) for axis in transverse_axes), default=0.0)
    edge_has_large_outlier = edge_max > max(edge_dom * 2.5, cross_max * 0.45)
    if edge_has_large_outlier and len(edge_holes) > len(internal_holes):
        return True
    return False


def _dominant_group_diameter(hole_centers: list[tuple[App.Vector, float]]) -> float | None:
    buckets: dict[float, int] = {}
    for _center, diameter in hole_centers:
        if diameter <= 1e-6:
            continue
        bucket = round(float(diameter) * 2.0) / 2.0
        buckets[bucket] = buckets.get(bucket, 0) + 1
    if not buckets:
        return None
    return max(buckets.items(), key=lambda item: (item[1], item[0]))[0]


def _infer_linear_hole_pitch(
    hole_centers: list[tuple[App.Vector, float]],
    longest_axis: str,
    tolerance_mm: float = 1.0,
) -> float | None:
    """Find consistent linear hole pitch by grouping holes into transverse rows.

    tolerance_mm (default 1.0): grouping bin width for transverse alignment.
    Requires ≥3 holes in a row and ≥2 consistent spacings (within 8% of median).
    """
    if len(hole_centers) < 3:
        return None
    transverse_axes = [axis for axis in ("X", "Y", "Z") if axis != longest_axis]
    grouped: dict[tuple[float, ...], list[tuple[App.Vector, float]]] = {}
    for center, diameter in hole_centers:
        if not isinstance(center, App.Vector):
            continue
        key = tuple(
            round(vec_axis_value(center, axis) / max(tolerance_mm, 1e-6)) * tolerance_mm
            for axis in transverse_axes
        )
        grouped.setdefault(key, []).append((center, diameter))

    best_pitch = None
    best_rank = None
    for items in grouped.values():
        if len(items) < 3:
            continue
        positions = sorted(vec_axis_value(center, longest_axis) for center, _diameter in items)
        spacings = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
        spacings = [spacing for spacing in spacings if spacing > 1e-4]
        if len(spacings) < 2:
            continue
        median_spacing = float(statistics.median(spacings))
        # 8% of median: tolerates manufacturing deviations while rejecting irregular spacing
        spacing_tol = max(1.0, median_spacing * 0.08)
        consistent = [spacing for spacing in spacings if abs(spacing - median_spacing) <= spacing_tol]
        if len(consistent) < 2:
            continue
        spread = statistics.pstdev(consistent) if len(consistent) >= 2 else 0.0
        rank = (len(items), len(consistent), -spread, median_spacing)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_pitch = float(statistics.median(consistent))
    return best_pitch


def _infer_axis_median_hole_pitch(
    hole_centers: list[tuple[App.Vector, float]],
    longest_axis: str,
    tolerance_mm: float = 0.5,
) -> float | None:
    """Simpler fallback: median of all pairwise spacings along longest axis.

    tolerance_mm (default 0.5): position quantization bin to merge near-coincident holes.
    Requires ≥2 holes.
    """
    if len(hole_centers) < 2:
        return None
    positions = sorted({
        round(vec_axis_value(center, longest_axis) / max(tolerance_mm, 1e-6)) * tolerance_mm
        for center, _diameter in hole_centers
        if isinstance(center, App.Vector)
    })
    spacings = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    spacings = [spacing for spacing in spacings if spacing > 1e-4]
    if not spacings:
        return None
    return float(statistics.median(spacings))


def _transverse_axes(longest_axis: str) -> list[str]:
    return [axis for axis in ("X", "Y", "Z") if axis != longest_axis]


def _looks_like_rotational_profile(
    circle_groups: list[dict[str, object]],
    dims: dict[str, float],
    longest_axis: str,
    flat_ratio: float,
    cylindrical_radii: list[float],
) -> bool:
    """Detect axisymmetric turning parts so outer profile circles are not misread as holes."""
    if flat_ratio < 0.55 or len(circle_groups) < 2 or not cylindrical_radii:
        return False

    transverse_axes = _transverse_axes(longest_axis)
    if len(transverse_axes) != 2:
        return False

    cross_dims = [max(0.0, float(dims.get(axis, 0.0))) for axis in transverse_axes]
    cross_max = max(cross_dims) if cross_dims else 0.0
    cross_min = min(cross_dims) if cross_dims else 0.0
    if cross_max <= 0.0 or cross_min / cross_max < 0.85:
        return False

    max_circle_diameter = max(
        max(group.get("diameters") or [0.0]) for group in circle_groups
    )
    if max_circle_diameter < cross_max * 0.75:
        return False

    center_tol = max(0.5, cross_max * 0.02)
    for axis in transverse_axes:
        coords = [
            vec_axis_value(group["center"], axis)
            for group in circle_groups
            if isinstance(group.get("center"), App.Vector)
        ]
        if len(coords) != len(circle_groups):
            return False
        if max(coords) - min(coords) > center_tol:
            return False
    return True


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
        except (AttributeError, RuntimeError):
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
    except (AttributeError, RuntimeError):
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
        except (AttributeError, RuntimeError):
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
        except (AttributeError, RuntimeError):
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


def _face_pos_along(face, axis_vec: App.Vector) -> float | None:
    """Return the projection of a face's center of mass onto axis_vec."""
    try:
        com = face.CenterOfMass
        return float(com.dot(axis_vec))
    except (AttributeError, RuntimeError):
        return None


def _arc_span_fraction(edge: Part.Edge) -> float:
    """Return arc length as a fraction of the full circle circumference (0..1)."""
    try:
        r = float(edge.Curve.Radius)
        if r < 1e-6:
            return 0.0
        return float(edge.Length) / (2.0 * math.pi * r)
    except (AttributeError, ZeroDivisionError):
        return 0.0


def collect_slot_data(
    shape: Part.Shape,
    thickness_axis: str,
    dims: dict,
    longest_axis: str,
) -> list[dict]:
    """Detect slot features (Nuten/Langlöcher) in a part shape.

    A slot is a planar pocket whose boundary consists of exactly two
    semicircular arcs (~180° each, matching radius) and two straight edges.
    Both through-slots (depth=None) and blind pockets are detected.

    Returns a list of slot dicts:
        width_mm       — slot width = arc diameter
        length_mm      — end-to-end length = center-to-center distance + width
        depth_mm       — pocket depth in mm, or None for through-slots
        center_mm      — geometric center {x, y, z}
        orientation    — "H" if length axis aligns with longest part axis, else "V"
    """
    thickness_vec = _axis_direction_vector(thickness_axis)

    outer_max: float | None = None
    outer_min: float | None = None
    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        if surface is None or surface.__class__.__name__ != "Plane":
            continue
        try:
            normal = surface.Axis
        except AttributeError:
            continue
        if normal is None:
            continue
        # Outer faces: normal roughly parallel to thickness axis
        if not _axes_are_parallel(normal, thickness_vec, tol_deg=10.0):
            continue
        pos = _face_pos_along(face, thickness_vec)
        if pos is not None:
            if outer_max is None or pos > outer_max:
                outer_max = pos
            if outer_min is None or pos < outer_min:
                outer_min = pos

    slots: list[dict] = []
    seen: set[tuple[float, float, float]] = set()  # deduplicate by rounded center

    for face in shape.Faces:
        surface = getattr(face, "Surface", None)
        if surface is None or surface.__class__.__name__ != "Plane":
            continue

        # Collect edges of this face, skip degenerate micro-edges (< 0.5 mm)
        arcs: list[Part.Edge] = []
        lines: list[Part.Edge] = []
        for edge in face.Edges:
            edge_len = float(getattr(edge, "Length", 0.0) or 0.0)
            if edge_len < 0.5:
                continue
            curve = getattr(edge, "Curve", None)
            if curve is None:
                continue
            cname = curve.__class__.__name__
            if cname in {"Circle", "ArcOfCircle"}:
                arcs.append(edge)
            elif cname in {"Line", "LineSegment"}:
                lines.append(edge)

        # Slot signature: exactly 2 arcs + 2 lines
        if len(arcs) != 2 or len(lines) != 2:
            continue

        # Both arcs must be semicircular (~180°) and same radius
        span0 = _arc_span_fraction(arcs[0])
        span1 = _arc_span_fraction(arcs[1])
        if not (0.40 <= span0 <= 0.60 and 0.40 <= span1 <= 0.60):
            continue

        r0 = float(arcs[0].Curve.Radius)
        r1 = float(arcs[1].Curve.Radius)
        if abs(r0 - r1) > max(0.5, r0 * 0.05):
            continue

        # Arc centers
        c0 = getattr(arcs[0].Curve, "Center", None)
        c1 = getattr(arcs[1].Curve, "Center", None)
        if not isinstance(c0, App.Vector) or not isinstance(c1, App.Vector):
            continue

        slot_width = (r0 + r1)  # avg diameter
        center_dist = float(c0.distanceToPoint(c1))
        slot_length = center_dist + slot_width
        if slot_length < slot_width * 1.1:
            continue  # degenerate: barely longer than wide → not a slot

        # Geometric center of the slot
        cx = (float(c0.x) + float(c1.x)) / 2.0
        cy = (float(c0.y) + float(c1.y)) / 2.0
        cz = (float(c0.z) + float(c1.z)) / 2.0

        # Deduplicate: same center within 1mm
        center_key_val = (round(cx), round(cy), round(cz))
        if center_key_val in seen:
            continue
        seen.add(center_key_val)

        # Depth: distance from this face to the nearest outer face along thickness axis
        face_pos = _face_pos_along(face, thickness_vec)
        depth_mm = None
        if face_pos is not None and outer_max is not None and outer_min is not None:
            dist_to_max = abs(outer_max - face_pos)
            dist_to_min = abs(face_pos - outer_min)
            part_thickness = abs(outer_max - outer_min)
            depth_candidate = min(dist_to_max, dist_to_min)
            # Through-slot: face is very close to one outer surface (< 5% of thickness)
            if depth_candidate < max(0.3, part_thickness * 0.05):
                depth_mm = None  # through-slot
            else:
                depth_mm = round(depth_candidate, 3)

        # Orientation: does the slot length axis align with the longest part axis?
        delta = c1.sub(c0)
        long_vec = _axis_direction_vector(longest_axis)
        length_along_long = abs(float(delta.dot(long_vec)))
        orientation = "H" if length_along_long > center_dist * 0.5 else "V"

        slots.append({
            "width_mm": round(slot_width, 3),
            "length_mm": round(slot_length, 3),
            "depth_mm": depth_mm,
            "center_mm": {
                "x": round(cx, 3),
                "y": round(cy, 3),
                "z": round(cz, 3),
            },
            "orientation": orientation,
        })

    return slots


def _detect_chamfers(shape, dims: dict, ordered_axes: list) -> list[dict]:
    """Detect chamfer faces: small planar faces whose normal is at ~45° to axis-aligned planes.

    Returns a list of dicts with keys: size_mm, angle_deg, axis_pair, center_mm.
    """
    chamfers = []
    # Axis unit vectors
    axis_vectors = {
        "X": (1.0, 0.0, 0.0),
        "Y": (0.0, 1.0, 0.0),
        "Z": (0.0, 0.0, 1.0),
    }
    # Typical chamfer: normal is ~45° from two axis planes
    # A 45° chamfer between X and Y has normal ≈ (±0.707, ±0.707, 0)
    max_face_area = 0.0
    face_areas = []
    for face in shape.Faces:
        area = float(face.Area)
        face_areas.append(area)
        if area > max_face_area:
            max_face_area = area

    if max_face_area < 1e-6:
        return chamfers

    for face, area in zip(shape.Faces, face_areas):
        # Chamfer faces are small relative to main faces:
        # - Upper bound 15% of largest face: chamfers are edge features, not primary surfaces
        # - Lower bound 0.5 mm²: filters numerical noise / degenerate faces
        if area > max_face_area * 0.15 or area < 0.5:
            continue
        surface = getattr(face, "Surface", None)
        if surface is None or surface.__class__.__name__ != "Plane":
            continue
        normal = getattr(surface, "Axis", None)
        if normal is None:
            continue
        nx, ny, nz = float(normal.x), float(normal.y), float(normal.z)
        n_len = (nx * nx + ny * ny + nz * nz) ** 0.5
        if n_len < 1e-6:
            continue
        nx, ny, nz = nx / n_len, ny / n_len, nz / n_len

        # Check if normal is at ~45° from any two axis pairs.
        # A perfect 45° chamfer has dot(normal, axis) ≈ cos(45°) = 0.707.
        # Range 0.45-0.85 corresponds to ~32°-63°, covering standard chamfers
        # (30°, 45°, 60°) while rejecting axis-aligned and diagonal faces.
        for i, (a1_name, a1_vec) in enumerate(axis_vectors.items()):
            dot1 = abs(nx * a1_vec[0] + ny * a1_vec[1] + nz * a1_vec[2])
            if not (0.45 <= dot1 <= 0.85):
                continue
            for a2_name, a2_vec in list(axis_vectors.items())[i + 1:]:
                dot2 = abs(nx * a2_vec[0] + ny * a2_vec[1] + nz * a2_vec[2])
                if not (0.45 <= dot2 <= 0.85):
                    continue
                # This face's normal is between two axes — likely a chamfer
                angle = math.degrees(math.acos(min(dot1, 1.0)))
                # Estimate chamfer size from face bounding box
                fb = face.BoundBox
                face_dims = sorted([float(fb.XLength), float(fb.YLength), float(fb.ZLength)])
                # Smallest non-zero dimension ≈ chamfer width
                chamfer_size = next((d for d in face_dims if d > 0.1), 0.0)
                if chamfer_size < 0.2:
                    continue
                center = face.CenterOfMass
                chamfers.append({
                    "size_mm": round(chamfer_size, 3),
                    "angle_deg": round(angle, 1),
                    "axis_pair": f"{a1_name}-{a2_name}",
                    "center_mm": {
                        "x": round(float(center.x), 3),
                        "y": round(float(center.y), 3),
                        "z": round(float(center.z), 3),
                    },
                })
                break
            else:
                continue
            break

    # Deduplicate similar chamfers (same size within 0.5mm tolerance)
    if chamfers:
        unique = []
        seen_sizes = set()
        for ch in chamfers:
            key = round(ch["size_mm"] * 2) / 2  # round to 0.5mm
            if key not in seen_sizes:
                seen_sizes.add(key)
                unique.append(ch)
        chamfers = unique

    return chamfers


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

    edge_circle_groups, edge_diameters = collect_edge_circle_data(shape, thickness_axis)
    internal_circle_groups, internal_diameters = collect_internal_cylinder_circle_data(shape, thickness_axis)
    if _prefer_internal_cylinder_groups(
        edge_circle_groups,
        edge_diameters,
        internal_circle_groups,
        dims,
        longest_axis,
        flat_ratio,
    ):
        circle_groups = internal_circle_groups
        all_diameters = internal_diameters
    else:
        circle_groups = edge_circle_groups
        all_diameters = edge_diameters
    face_types = classify_face_types(shape)
    cylindrical_radii = collect_cylindrical_radii(shape)
    rotational_profile = _looks_like_rotational_profile(
        circle_groups,
        dims,
        longest_axis,
        flat_ratio,
        cylindrical_radii,
    )
    if rotational_profile:
        hole_centers = []
        effective_diameters = []
    else:
        hole_centers = _hole_centers_from_circle_groups(circle_groups)
        effective_diameters = list(all_diameters)

    hole_count = len(hole_centers)

    hole_diameter_mm = None
    dominant_group_diameter = _dominant_group_diameter(hole_centers)
    if dominant_group_diameter is not None:
        hole_diameter_mm = float(dominant_group_diameter)
    elif effective_diameters:
        hole_diameter_mm = float(statistics.median(effective_diameters))

    hole_groups = [
        {
            "center_mm": {
                "x": round(float(center.x), 5),
                "y": round(float(center.y), 5),
                "z": round(float(center.z), 5),
            },
            "diameter_mm": round(float(diameter), 5),
        }
        for center, diameter in hole_centers
    ]
    unique_diameters = sorted({round(float(diameter), 4) for _, diameter in hole_centers})
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
    measured_thickness_for_thread = None if rotational_profile else measure_wall_thickness(shape)
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
    hole_pitch_source = None
    preferred_hole_pitch_mm = None
    preferred_hole_pitch_source = None
    if hole_count >= 2:
        linear_pitch = _infer_linear_hole_pitch(hole_centers, longest_axis)
        if linear_pitch is not None:
            preferred_hole_pitch_mm = linear_pitch
            preferred_hole_pitch_source = "linear_pattern"
        axis_pitch = _infer_axis_median_hole_pitch(hole_centers, longest_axis)
        if axis_pitch is not None:
            hole_pitch_mm = axis_pitch
            hole_pitch_source = "axis_median"
        elif linear_pitch is not None:
            hole_pitch_mm = linear_pitch
            hole_pitch_source = "linear_pattern"
        if preferred_hole_pitch_mm is None and hole_pitch_mm is not None:
            preferred_hole_pitch_mm = hole_pitch_mm
            preferred_hole_pitch_source = hole_pitch_source

    _raw_bend_radius_mm = None
    if cylindrical_radii and not rotational_profile:
        thickness = max(ordered_axes[2][1], 1e-6)
        filtered = [radius for radius in cylindrical_radii if radius >= thickness * 0.5]
        candidates = filtered or cylindrical_radii
        _raw_bend_radius_mm = float(min(candidates))

    # Face-type classification for sheet metal detection
    total_faces = max(face_types["total"], 1)
    plane_fraction = face_types["plane"] / total_faces
    is_sheet_metal_by_faces = (
        not rotational_profile
        and
        plane_fraction >= 0.60           # predominantly flat faces
        and face_types["cylinder"] >= 1  # at least one bend (cylinder face)
        and face_types["cone"] <= 2      # no complex machined surfaces
        and face_types["torus"] <= 1
    )

    # Actual wall thickness via anti-parallel plane face pair distances
    measured_thickness_mm = None if rotational_profile else measured_thickness_for_thread

    # Flat pattern computation (for sheet metal parts)
    flat_pattern = None
    if not rotational_profile:
        flat_pattern = compute_flat_pattern(shape, thickness_axis, measured_thickness_mm, k_factor_override)

    # Only report bend_radius if there is a real sheet metal signal:
    # face-type classification, flat pattern with bends, or thin wall
    bend_radius_mm = None
    if _raw_bend_radius_mm is not None:
        fp_bend_count = int((flat_pattern or {}).get("bend_count") or 0)
        has_sheet_signal = (
            is_sheet_metal_by_faces
            or fp_bend_count > 0
            or (measured_thickness_mm is not None and measured_thickness_mm <= 5.0)
        )
        if has_sheet_signal:
            bend_radius_mm = _raw_bend_radius_mm

    # Chamfer detection: small planar faces at non-axis-aligned angles
    chamfers = _detect_chamfers(shape, dims, ordered_axes)

    # Slot detection: planar pockets with 2 semicircular arcs + 2 straight edges
    slot_groups = collect_slot_data(shape, thickness_axis, dims, longest_axis)

    return {
        "ok": True,
        "bbox_mm": {axis: round(value, 5) for axis, value in dims.items()},
        "axis_order": [axis for axis, _ in ordered_axes],
        "longest_axis": longest_axis,
        "thickness_axis": thickness_axis,
        "flat_ratio": round(flat_ratio, 5),
        "is_flat": is_flat,
        "rotational_profile": rotational_profile,
        "hole_count": hole_count,
        "hole_diameter_mm": round(hole_diameter_mm, 5) if hole_diameter_mm else None,
        "hole_pitch_mm": round(hole_pitch_mm, 5) if hole_pitch_mm else None,
        "hole_pitch_source": hole_pitch_source,
        "preferred_hole_pitch_mm": round(preferred_hole_pitch_mm, 5) if preferred_hole_pitch_mm else None,
        "preferred_hole_pitch_source": preferred_hole_pitch_source,
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
        "chamfers": chamfers,
        "slot_count": len(slot_groups),
        "slot_groups": slot_groups,
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

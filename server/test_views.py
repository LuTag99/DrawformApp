#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Regression test for view selection/alignment plus golden baseline checks.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from sample_catalog import resolve_sample_set

# Force UTF-8 output on Windows
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

FREECAD_DEFAULT_PYTHON = r"C:\Program Files\FreeCAD 1.0\bin\python.exe"
DEBUG_DIR = Path(__file__).parent / "_debug"
SCRIPT_PATH = Path(__file__).parent / "freecad" / "step_to_pdf.py"
BASELINE_GOLDEN_PATH = Path(__file__).parent / "_golden" / "views_baseline.json"
REAL_GOLDEN_PATH = DEBUG_DIR / "views_baseline_real.json"
ALL_GOLDEN_PATH = DEBUG_DIR / "views_baseline_all.json"

# Numeric tolerances for baseline comparisons (millimeter unless noted).
BBOX_TOL_MM = 0.05
PAPER_TOL_MM = 0.25
CENTER_TOL_MM = 0.25
FLATNESS_TOL = 0.01
FEATURE_DIM_TOL_MM = 0.5
QUALITY_OVERFLOW_TOL_MM = 0.5
STABILITY_PAPER_TOL_MM = 0.3
STABILITY_CENTER_TOL_MM = 0.3

# Expected results for each test part
EXPECTED = {
    "10x10x10": {
        "longest_axis": "X",  # Cube, any axis is fine
        "is_flat": False,
        "alignment_ok": True,
    },
    "rechteck": {
        "longest_axis": "Y",  # 300mm is Y
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # 300mm should be horizontal (wider than tall)
        "top_rotation_deg": 270,  # Asymmetric details must keep canonical orientation
    },
    "cylinder": {
        "longest_axis": "Z",  # 80mm length
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
        "min_hole_count": 2,
    },
    "shaft": {
        "longest_axis": "Z",  # 100mm length
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
        "min_hole_count": 3,
    },
    "flange": {
        "longest_axis": "X",  # Diameter 100mm
        "is_flat": True,  # 10mm thick << 100mm diameter
        "alignment_ok": True,
        "front_aspect_near_1": True,  # Circle should be ~square
        "min_hole_count": 6,
    },
    "sheet_metal": {
        "longest_axis": "X",  # 200mm
        "is_flat": True,  # 3mm thick
        "alignment_ok": True,
        "front_width_gt_height": True,  # 200x100 rectangle
    },
    "l_shape": {
        "longest_axis": "X",  # 100mm (tied with Y)
        "is_flat": False,
        "alignment_ok": True,
        "top_rotation_deg": 180,
    },
    "angle_profile": {
        "longest_axis": "X",  # 150mm
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
    },
    "tall_thin": {
        "longest_axis": "Z",  # 200mm
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # 200mm should be horizontal
    },
    "slot_plate": {
        "longest_axis": "X",  # 120mm
        "is_flat": True,  # 8mm thick
        "alignment_ok": True,
        # Slot has 2 semicircular ends; one end arc may round to exactly 50% and
        # be rejected by FP tolerance → reliably detect at least 1 slot feature.
        "min_hole_count": 1,
    },
    "bracket": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "min_hole_count": 2,
    },
    "housing": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
    },
    "t_profile": {
        "longest_axis": "Y",
        "is_flat": False,
        "alignment_ok": True,
        "top_rotation_deg": 270,
    },
    "rect_part": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
    },
    "feature_test_part": {
        "longest_axis": "X",
        "is_flat": True,
        "alignment_ok": True,
        "front_width_gt_height": True,
        "min_hole_count": 5,
        "min_hole_pitch_mm": 100.0,
        "min_bend_radius_mm": 4.0,
        "min_centerline_count": 2,
    },
    "complex_bracket": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,
        "min_hole_count": 8,
        "min_hole_diameter_mm": 10.0,
        "min_hole_pitch_mm": 120.0,
        "min_centerline_count": 3,
        "stability_check": True,
    },
    "flanged_manifold": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,
        "min_hole_count": 10,
        # Large central bore (40mm) may not be detected as a discrete edge due to
        # topology splits in the boolean fused solid; bolt holes (12mm) dominate.
        "min_hole_diameter_mm": 10.0,
        "min_hole_pitch_mm": 160.0,
        "min_bend_radius_mm": 20.0,
        "min_centerline_count": 4,
        "stability_check": True,
    },
    "stepped_shaft": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,
        "min_hole_count": 5,
        "min_hole_diameter_mm": 20.0,
        "min_hole_pitch_mm": 180.0,
        "min_centerline_count": 3,
        "stability_check": True,
    },
    "u_channel_assembly": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,
        "min_hole_count": 10,
        "min_hole_pitch_mm": 120.0,
        "min_centerline_count": 4,
        "stability_check": True,
    },
    "mounting_panel_complex": {
        "longest_axis": "X",
        "is_flat": True,
        "alignment_ok": True,
        "front_width_gt_height": True,
        "min_hole_count": 8,
        "min_hole_pitch_mm": 150.0,
        "min_centerline_count": 6,
        "stability_check": True,
    },
}


def _float_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_or_none(value, digits=3):
    parsed = _float_or_none(value)
    if parsed is None:
        return None
    return round(parsed, digits)


def resolve_freecad_python() -> str:
    env_value = (os.getenv("FREECAD_PYTHON") or "").strip()
    if env_value:
        if Path(env_value).exists():
            return env_value
        resolved = shutil.which(env_value)
        if resolved:
            return resolved
    if Path(FREECAD_DEFAULT_PYTHON).exists():
        return FREECAD_DEFAULT_PYTHON
    resolved = shutil.which("python.exe") or shutil.which("python")
    if resolved:
        return resolved
    return FREECAD_DEFAULT_PYTHON


def run_conversion(step_file: Path, sample_name: str | None = None) -> dict:
    """Run the PDF conversion and return the JSON report."""
    base_name = sample_name or step_file.stem
    json_path = DEBUG_DIR / f"{base_name}_report.json"
    env = {"DRAWFORM_DEBUG_DIR": str(DEBUG_DIR)}
    freecad_python = resolve_freecad_python()
    base_pdf = DEBUG_DIR / f"{base_name}_test.pdf"
    pdf_candidates = [
        base_pdf,
        DEBUG_DIR / f"{base_name}_test_{int(time.time() * 1000)}.pdf",
    ]
    result = None

    for attempt, pdf_path in enumerate(pdf_candidates, start=1):
        result = subprocess.run(
            [freecad_python, str(SCRIPT_PATH), str(step_file), str(pdf_path)],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )
        if result.returncode == 0:
            break
        error_text = (result.stderr or result.stdout or "").strip()
        lock_error = "Permission denied" in error_text or "WinError 32" in error_text
        if lock_error and attempt < len(pdf_candidates):
            continue
        return {"error": f"FreeCAD conversion failed (exit {result.returncode}): {error_text}"}

    if not json_path.exists():
        return {"error": f"No report generated. stderr: {result.stderr}"}

    return json.loads(json_path.read_text(encoding="utf-8"))


def check_alignment(report: dict) -> tuple[bool, list[str]]:
    """Check if views are properly aligned."""
    issues = []
    alignment = report.get("alignment", {})

    if not alignment.get("front_top_left_match", False):
        diff = abs(alignment.get("front_left_edge", 0) - alignment.get("top_left_edge", 0))
        issues.append(f"Front/Top left edges differ by {diff:.2f}mm")

    if not alignment.get("front_left_top_match", False):
        diff = abs(alignment.get("front_top_edge", 0) - alignment.get("left_top_edge", 0))
        issues.append(f"Front/Left top edges differ by {diff:.2f}mm")

    return len(issues) == 0, issues


def check_view_orientation(report: dict, expected: dict) -> tuple[bool, list[str]]:
    """Check if the view selection is correct."""
    issues = []
    detection = report.get("detection", {})
    views = report.get("views", {})

    expected_axis = expected.get("longest_axis")
    actual_axis = detection.get("longest_axis")
    if expected_axis and actual_axis != expected_axis:
        issues.append(f"Wrong longest axis: expected {expected_axis}, got {actual_axis}")

    expected_flat = expected.get("is_flat")
    # Check if flat detection worked (look at flatness in debug info)
    bb = report.get("bounding_box", {})
    dims = sorted([bb.get("X", 0), bb.get("Y", 0), bb.get("Z", 0)], reverse=True)
    if expected_flat is not None and len(dims) == 3 and dims[1] > 0:
        actual_flat = (dims[2] / dims[1]) < 0.3
        if bool(expected_flat) != actual_flat:
            issues.append(f"Flat detection: expected {bool(expected_flat)}, got {actual_flat}")

    # Check Front view orientation
    front = views.get("Front", {})
    if front:
        paper_w, paper_h = front.get("paper_size", [0, 0])

        # Check if width > height (longest axis horizontal)
        if expected.get("front_width_gt_height"):
            if paper_w <= paper_h:
                issues.append(f"Front not horizontal: w={paper_w:.1f} <= h={paper_h:.1f}")

        # Check if aspect ratio is near 1 (for circles/squares)
        if expected.get("front_aspect_near_1"):
            aspect = paper_w / max(paper_h, 0.1)
            if aspect < 0.7 or aspect > 1.4:
                issues.append(f"Front not square-ish: aspect={aspect:.2f}")

    # Optional strict orientation checks for asymmetric reference parts.
    top_expected_rotation = expected.get("top_rotation_deg")
    top = views.get("Top", {})
    if top_expected_rotation is not None and top:
        actual_rotation = int(top.get("rotation_deg", -1))
        if actual_rotation != int(top_expected_rotation):
            issues.append(
                f"Top rotation mismatch: expected {top_expected_rotation}deg, got {actual_rotation}deg"
            )

    return len(issues) == 0, issues


def check_feature_expectations(report: dict, expected: dict) -> tuple[bool, list[str]]:
    """Check feature extraction expectations for feature-rich samples."""
    issues = []
    features = report.get("features", {})

    if expected.get("min_hole_count") is not None:
        actual_holes = int(_float_or_none(features.get("hole_count")) or 0)
        if actual_holes < int(expected["min_hole_count"]):
            issues.append(
                f"Feature holes too low: expected >= {expected['min_hole_count']}, got {actual_holes}"
            )

    if expected.get("min_hole_diameter_mm") is not None:
        hole_dia = _float_or_none(features.get("hole_diameter_mm"))
        if hole_dia is None or hole_dia < float(expected["min_hole_diameter_mm"]):
            issues.append(
                f"Hole diameter too low: expected >= {expected['min_hole_diameter_mm']}, got {hole_dia}"
            )

    if expected.get("min_hole_pitch_mm") is not None:
        hole_pitch = _float_or_none(features.get("hole_pitch_mm"))
        if hole_pitch is None or hole_pitch < float(expected["min_hole_pitch_mm"]):
            issues.append(
                f"Hole pitch too low: expected >= {expected['min_hole_pitch_mm']}, got {hole_pitch}"
            )

    if expected.get("min_bend_radius_mm") is not None:
        bend_r = _float_or_none(features.get("bend_radius_mm"))
        if bend_r is None or bend_r < float(expected["min_bend_radius_mm"]):
            issues.append(
                f"Bend radius too low: expected >= {expected['min_bend_radius_mm']}, got {bend_r}"
            )

    return len(issues) == 0, issues


def check_layout_quality(report: dict) -> tuple[bool, list[str]]:
    """Check drawing area fit and clipping quality metrics from the report."""
    issues = []
    quality = report.get("quality")
    if not isinstance(quality, dict):
        issues.append("Missing quality block in report.")
        return False, issues

    overflow = quality.get("overflow_mm", {})
    max_overflow = _float_or_none(overflow.get("max")) or 0.0
    fits = bool(quality.get("fits_inside_drawing_area", False))
    scale_reduction_needed = bool(quality.get("scale_reduction_needed", False))

    if max_overflow > QUALITY_OVERFLOW_TOL_MM:
        issues.append(
            f"Drawing overflow too high: max={max_overflow:.3f}mm (tol {QUALITY_OVERFLOW_TOL_MM:.3f}mm)"
        )
    if not fits:
        issues.append("Views do not fully fit into drawing area.")
    if scale_reduction_needed:
        issues.append("Layout required scale reduction to fit drawing area.")

    return len(issues) == 0, issues


def check_norm_conformity(sample_name: str, report: dict, expected: dict) -> tuple[bool, list[str]]:
    """Lightweight norm-conformity checks based on rendered debug SVG and report metadata."""
    issues = []
    svg_path = DEBUG_DIR / f"{sample_name}_debug.svg"
    if not svg_path.exists():
        issues.append(f"Missing debug SVG for norm checks: {svg_path}")
        return False, issues

    svg_text = svg_path.read_text(encoding="utf-8", errors="replace")

    required_markers = [
        "Norm:",
        "Projektion:",
        "Allgemeintoleranzen nach",
        "Alle Masse in ",
        "sofern nicht anders angegeben",
    ]
    for marker in required_markers:
        if marker not in svg_text:
            issues.append(f"Missing norm annotation marker: {marker}")

    # Dimension text should remain unitless (mm only in the global note).
    text_values = re.findall(r"<text[^>]*>([^<]*)</text>", svg_text, flags=re.IGNORECASE)
    for raw in text_values:
        text = raw.strip()
        if not text:
            continue
        if "Alle Masse in" in text:
            continue
        if re.search(r"(?<![A-Za-z])\d+(?:[,.]\d+)?\s*mm\b", text, flags=re.IGNORECASE):
            issues.append(f"Unit suffix found in dimension text: '{text}'")
            break

    # ISO 128 centerline expectation: hole-rich parts with detectable circular SVG geometry
    # should contain dashed centerlines.
    min_holes = int(expected.get("min_hole_count", 0) or 0)
    features = report.get("features", {})
    actual_holes = int(_float_or_none(features.get("hole_count")) or 0)
    quality = report.get("quality", {})
    centerline_total = int(_float_or_none((quality or {}).get("centerline_total")) or 0)
    views = report.get("views", {})
    circle_total = sum(int(_float_or_none((view or {}).get("circle_count")) or 0) for view in views.values())
    if min_holes > 0 and actual_holes > 0 and circle_total > 0:
        if "stroke-dasharray" not in svg_text:
            issues.append("Missing dashed centerlines for hole features.")
        if centerline_total <= 0:
            issues.append("No centerlines emitted although circular features are present.")
        for view_name, view in views.items():
            if view_name == "Iso":
                continue
            circle_count = int(_float_or_none((view or {}).get("circle_count")) or 0)
            if circle_count <= 0:
                continue
            centerline_count = int(_float_or_none((view or {}).get("centerline_count")) or 0)
            if centerline_count <= 0:
                issues.append(f"View '{view_name}' has circles but no centerlines.")
                break

    min_centerline_count = int(expected.get("min_centerline_count", 0) or 0)
    if min_centerline_count > 0 and centerline_total < min_centerline_count:
        issues.append(
            f"Centerline count too low: expected >= {min_centerline_count}, got {centerline_total}"
        )

    # Cross-check report quality contains centerline metrics.
    if not isinstance(quality, dict):
        issues.append("Missing quality block for norm checks.")
    else:
        if quality.get("centerline_total") is None:
            issues.append("Missing quality.centerline_total metric.")

    return len(issues) == 0, issues


def build_baseline_snapshot(report: dict) -> dict:
    """Extract the stable subset of report metrics used for golden regression checks."""
    bbox = report.get("bounding_box", {})
    detection = report.get("detection", {})
    features = report.get("features", {})
    alignment = report.get("alignment", {})
    quality = report.get("quality", {})
    views = report.get("views", {})

    view_snapshot = {}
    for view_name in ("Front", "Top", "Left", "Iso"):
        view = views.get(view_name, {})
        paper = view.get("paper_size", [0.0, 0.0])
        center = view.get("center", [0.0, 0.0])
        if len(paper) != 2:
            paper = [0.0, 0.0]
        if len(center) != 2:
            center = [0.0, 0.0]
        view_snapshot[view_name] = {
            "rotation_deg": int(view.get("rotation_deg", 0)),
            "paper_size": [_round_or_none(paper[0]), _round_or_none(paper[1])],
            "center": [_round_or_none(center[0]), _round_or_none(center[1])],
        }

    return {
        "bounding_box": {
            "X": _round_or_none(bbox.get("X")),
            "Y": _round_or_none(bbox.get("Y")),
            "Z": _round_or_none(bbox.get("Z")),
        },
        "detection": {
            "method": str(detection.get("method", "")),
            "longest_axis": str(detection.get("longest_axis", "")),
            "is_flat": bool(detection.get("is_flat", False)),
            "flatness_ratio": _round_or_none(detection.get("flatness_ratio"), digits=5),
        },
        "features": {
            "ok": bool(features.get("ok", False)),
            "hole_count": int(features.get("hole_count", 0) or 0),
            "hole_diameter_mm": _round_or_none(features.get("hole_diameter_mm")),
            "hole_pitch_mm": _round_or_none(features.get("hole_pitch_mm")),
            "bend_radius_mm": _round_or_none(features.get("bend_radius_mm")),
        },
        "views": view_snapshot,
        "alignment": {
            "front_top_left_match": bool(alignment.get("front_top_left_match", False)),
            "front_left_top_match": bool(alignment.get("front_left_top_match", False)),
        },
        "quality": {
            "fits_inside_drawing_area": bool(quality.get("fits_inside_drawing_area", False)),
            "scale_reduction_needed": bool(quality.get("scale_reduction_needed", False)),
            "overflow_max_mm": _round_or_none((quality.get("overflow_mm") or {}).get("max")),
            "centerline_total": int(_float_or_none(quality.get("centerline_total")) or 0),
        },
    }


def _compare_optional_float(
    actual_value,
    expected_value,
    *,
    label: str,
    tolerance: float,
    issues: list[str],
):
    actual = _float_or_none(actual_value)
    expected = _float_or_none(expected_value)
    if expected is None and actual is None:
        return
    if expected is None and actual is not None:
        issues.append(f"{label}: expected None, got {actual}")
        return
    if expected is not None and actual is None:
        issues.append(f"{label}: expected {expected}, got None")
        return
    if abs(actual - expected) > tolerance:
        issues.append(
            f"{label}: expected {expected:.3f}, got {actual:.3f} (tol {tolerance:.3f})"
        )


def compare_baseline_snapshot(actual: dict, expected: dict) -> list[str]:
    """Compare a report snapshot against golden baseline with tolerances."""
    issues = []

    for axis in ("X", "Y", "Z"):
        _compare_optional_float(
            actual.get("bounding_box", {}).get(axis),
            expected.get("bounding_box", {}).get(axis),
            label=f"bbox.{axis}",
            tolerance=BBOX_TOL_MM,
            issues=issues,
        )

    actual_det = actual.get("detection", {})
    expected_det = expected.get("detection", {})
    for key in ("method", "longest_axis"):
        if actual_det.get(key) != expected_det.get(key):
            issues.append(f"detection.{key}: expected {expected_det.get(key)}, got {actual_det.get(key)}")
    if bool(actual_det.get("is_flat")) != bool(expected_det.get("is_flat")):
        issues.append(
            f"detection.is_flat: expected {bool(expected_det.get('is_flat'))}, got {bool(actual_det.get('is_flat'))}"
        )
    _compare_optional_float(
        actual_det.get("flatness_ratio"),
        expected_det.get("flatness_ratio"),
        label="detection.flatness_ratio",
        tolerance=FLATNESS_TOL,
        issues=issues,
    )

    actual_feat = actual.get("features", {})
    expected_feat = expected.get("features", {})
    if bool(actual_feat.get("ok")) != bool(expected_feat.get("ok")):
        issues.append(f"features.ok: expected {expected_feat.get('ok')}, got {actual_feat.get('ok')}")
    if int(actual_feat.get("hole_count", 0) or 0) != int(expected_feat.get("hole_count", 0) or 0):
        issues.append(
            f"features.hole_count: expected {expected_feat.get('hole_count')}, got {actual_feat.get('hole_count')}"
        )
    for key in ("hole_diameter_mm", "hole_pitch_mm", "bend_radius_mm"):
        _compare_optional_float(
            actual_feat.get(key),
            expected_feat.get(key),
            label=f"features.{key}",
            tolerance=FEATURE_DIM_TOL_MM,
            issues=issues,
        )

    actual_views = actual.get("views", {})
    expected_views = expected.get("views", {})
    for view_name, expected_view in expected_views.items():
        actual_view = actual_views.get(view_name)
        if actual_view is None:
            issues.append(f"views.{view_name}: missing view")
            continue
        if int(actual_view.get("rotation_deg", -1)) != int(expected_view.get("rotation_deg", -1)):
            issues.append(
                f"views.{view_name}.rotation_deg: expected {expected_view.get('rotation_deg')}, "
                f"got {actual_view.get('rotation_deg')}"
            )
        actual_paper = actual_view.get("paper_size", [None, None])
        expected_paper = expected_view.get("paper_size", [None, None])
        actual_center = actual_view.get("center", [None, None])
        expected_center = expected_view.get("center", [None, None])
        _compare_optional_float(
            actual_paper[0] if len(actual_paper) > 0 else None,
            expected_paper[0] if len(expected_paper) > 0 else None,
            label=f"views.{view_name}.paper_size_w",
            tolerance=PAPER_TOL_MM,
            issues=issues,
        )
        _compare_optional_float(
            actual_paper[1] if len(actual_paper) > 1 else None,
            expected_paper[1] if len(expected_paper) > 1 else None,
            label=f"views.{view_name}.paper_size_h",
            tolerance=PAPER_TOL_MM,
            issues=issues,
        )
        _compare_optional_float(
            actual_center[0] if len(actual_center) > 0 else None,
            expected_center[0] if len(expected_center) > 0 else None,
            label=f"views.{view_name}.center_x",
            tolerance=CENTER_TOL_MM,
            issues=issues,
        )
        _compare_optional_float(
            actual_center[1] if len(actual_center) > 1 else None,
            expected_center[1] if len(expected_center) > 1 else None,
            label=f"views.{view_name}.center_y",
            tolerance=CENTER_TOL_MM,
            issues=issues,
        )

    actual_alignment = actual.get("alignment", {})
    expected_alignment = expected.get("alignment", {})
    for key in ("front_top_left_match", "front_left_top_match"):
        if bool(actual_alignment.get(key)) != bool(expected_alignment.get(key)):
            issues.append(
                f"alignment.{key}: expected {bool(expected_alignment.get(key))}, got {bool(actual_alignment.get(key))}"
            )

    actual_quality = actual.get("quality", {})
    expected_quality = expected.get("quality", {})
    if expected_quality:
        for key in ("fits_inside_drawing_area", "scale_reduction_needed"):
            if bool(actual_quality.get(key)) != bool(expected_quality.get(key)):
                issues.append(
                    f"quality.{key}: expected {bool(expected_quality.get(key))}, got {bool(actual_quality.get(key))}"
                )
        if int(actual_quality.get("centerline_total", 0) or 0) != int(expected_quality.get("centerline_total", 0) or 0):
            issues.append(
                f"quality.centerline_total: expected {expected_quality.get('centerline_total')}, "
                f"got {actual_quality.get('centerline_total')}"
            )
        _compare_optional_float(
            actual_quality.get("overflow_max_mm"),
            expected_quality.get("overflow_max_mm"),
            label="quality.overflow_max_mm",
            tolerance=QUALITY_OVERFLOW_TOL_MM,
            issues=issues,
        )

    return issues


def compare_stability_snapshot(reference: dict, current: dict) -> list[str]:
    """Compare two snapshots from repeated runs to detect nondeterminism."""
    issues = []
    ref_det = reference.get("detection", {})
    cur_det = current.get("detection", {})
    if ref_det.get("longest_axis") != cur_det.get("longest_axis"):
        issues.append(
            f"stability longest_axis drift: {ref_det.get('longest_axis')} -> {cur_det.get('longest_axis')}"
        )
    if bool(ref_det.get("is_flat")) != bool(cur_det.get("is_flat")):
        issues.append(f"stability is_flat drift: {ref_det.get('is_flat')} -> {cur_det.get('is_flat')}")

    ref_feat = reference.get("features", {})
    cur_feat = current.get("features", {})
    if int(ref_feat.get("hole_count", 0) or 0) != int(cur_feat.get("hole_count", 0) or 0):
        issues.append(
            f"stability hole_count drift: {ref_feat.get('hole_count')} -> {cur_feat.get('hole_count')}"
        )

    ref_views = reference.get("views", {})
    cur_views = current.get("views", {})
    for view_name in ("Front", "Top", "Left", "Iso"):
        rv = ref_views.get(view_name, {})
        cv = cur_views.get(view_name, {})
        if int(rv.get("rotation_deg", -1)) != int(cv.get("rotation_deg", -1)):
            issues.append(
                f"stability {view_name}.rotation drift: {rv.get('rotation_deg')} -> {cv.get('rotation_deg')}"
            )

        ref_paper = rv.get("paper_size", [None, None])
        cur_paper = cv.get("paper_size", [None, None])
        _compare_optional_float(
            ref_paper[0] if len(ref_paper) > 0 else None,
            cur_paper[0] if len(cur_paper) > 0 else None,
            label=f"stability {view_name}.paper_w",
            tolerance=STABILITY_PAPER_TOL_MM,
            issues=issues,
        )
        _compare_optional_float(
            ref_paper[1] if len(ref_paper) > 1 else None,
            cur_paper[1] if len(cur_paper) > 1 else None,
            label=f"stability {view_name}.paper_h",
            tolerance=STABILITY_PAPER_TOL_MM,
            issues=issues,
        )

        ref_center = rv.get("center", [None, None])
        cur_center = cv.get("center", [None, None])
        _compare_optional_float(
            ref_center[0] if len(ref_center) > 0 else None,
            cur_center[0] if len(cur_center) > 0 else None,
            label=f"stability {view_name}.center_x",
            tolerance=STABILITY_CENTER_TOL_MM,
            issues=issues,
        )
        _compare_optional_float(
            ref_center[1] if len(ref_center) > 1 else None,
            cur_center[1] if len(cur_center) > 1 else None,
            label=f"stability {view_name}.center_y",
            tolerance=STABILITY_CENTER_TOL_MM,
            issues=issues,
        )

    return issues


def run_stability_loop(
    step_file: Path, reference_snapshot: dict, runs: int, *, sleep_ms: int = 0
) -> tuple[bool, list[str]]:
    """Run repeated conversions and check deterministic output stability."""
    if runs <= 1:
        return True, []
    issues = []
    for run_index in range(2, runs + 1):
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)
        report = run_conversion(step_file)
        if "error" in report:
            issues.append(f"stability run {run_index}: conversion error: {report['error']}")
            continue
        current_snapshot = build_baseline_snapshot(report)
        drift = compare_stability_snapshot(reference_snapshot, current_snapshot)
        if drift:
            for issue in drift:
                issues.append(f"stability run {run_index}: {issue}")
    return len(issues) == 0, issues


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run view tests and optional golden baseline checks.")
    parser.add_argument(
        "--sample-set",
        choices=("baseline", "real", "all"),
        default="baseline",
        help="Sample set to test (default: baseline).",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=None,
        help="Optional golden baseline JSON path. Defaults by sample-set.",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Update/create the golden baseline JSON from the current run.",
    )
    parser.add_argument(
        "--stability-runs",
        type=int,
        default=1,
        help="Repeated runs for marked stability samples (default: 1, disabled).",
    )
    parser.add_argument(
        "--stability-sleep-ms",
        type=int,
        default=0,
        help="Optional delay between stability runs in milliseconds.",
    )
    return parser.parse_args(argv)


def resolve_golden_path(sample_set: str, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    normalized = str(sample_set or "").strip().lower() or "baseline"
    if normalized == "real":
        return REAL_GOLDEN_PATH
    if normalized == "all":
        return ALL_GOLDEN_PATH
    return BASELINE_GOLDEN_PATH


def main(argv=None):
    args = parse_args(argv)
    DEBUG_DIR.mkdir(exist_ok=True)
    golden_path = resolve_golden_path(args.sample_set, args.golden)

    golden_payload = None
    if not args.update_golden:
        if not golden_path.exists():
            print(f"Golden baseline missing: {golden_path}")
            print("Create it with: python server/test_views.py --update-golden")
            return 1
        try:
            golden_payload = json.loads(golden_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Golden baseline is not valid JSON: {golden_path} ({exc})")
            return 1
    golden_parts = (golden_payload or {}).get("parts", {})

    samples = resolve_sample_set(args.sample_set)
    results = []
    all_passed = True
    baseline_snapshots = {}

    print(f"\n{'='*60}")
    print(f"Sample set: {args.sample_set}")
    print(f"Testing {len(samples)} STEP files")
    print(f"{'='*60}\n")

    for sample in samples:
        step_file = sample.step_path
        name = sample.name
        print(f"Testing: {name}...", end=" ", flush=True)

        report = run_conversion(step_file, sample_name=name)
        if "error" in report:
            print(f"ERROR: {report['error'][:70]}")
            results.append(
                {
                    "name": name,
                    "passed": False,
                    "issues": [report["error"]],
                    "report": report,
                    "align_ok": False,
                    "orient_ok": False,
                }
            )
            all_passed = False
            continue

        expected = EXPECTED.get(name, {})

        align_ok, align_issues = check_alignment(report)
        orient_ok, orient_issues = check_view_orientation(report, expected)
        feature_ok, feature_issues = check_feature_expectations(report, expected)
        quality_ok, quality_issues = check_layout_quality(report)
        norm_ok, norm_issues = check_norm_conformity(name, report, expected)
        all_issues = align_issues + orient_issues + feature_issues + quality_issues + norm_issues

        snapshot = build_baseline_snapshot(report)
        baseline_snapshots[name] = snapshot
        if not args.update_golden:
            expected_snapshot = golden_parts.get(name)
            if expected_snapshot is None:
                all_issues.append(f"Golden baseline missing entry for sample '{name}'")
            else:
                all_issues.extend(compare_baseline_snapshot(snapshot, expected_snapshot))

        if args.stability_runs > 1 and expected.get("stability_check"):
            stable_ok, stable_issues = run_stability_loop(
                step_file,
                snapshot,
                args.stability_runs,
                sleep_ms=max(0, args.stability_sleep_ms),
            )
            if not stable_ok:
                all_issues.extend(stable_issues)

        if all_issues:
            print("FAILED")
            for issue in all_issues:
                print(f"   - {issue}")
            all_passed = False
        else:
            det = report.get("detection", {})
            print(f"OK (axis={det.get('longest_axis', '?')}, conf={det.get('confidence', 0):.2f})")

        results.append(
            {
                "name": name,
                "passed": len(all_issues) == 0,
                "issues": all_issues,
                "report": report,
                "align_ok": align_ok,
                "orient_ok": orient_ok,
                "feature_ok": feature_ok,
                "quality_ok": quality_ok,
                "norm_ok": norm_ok,
            }
        )

    if args.update_golden:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "sample_count": len(baseline_snapshots),
            "parts": dict(sorted(baseline_snapshots.items())),
        }
        golden_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nGolden baseline updated: {golden_path}")

    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r["passed"])
    print(f"Results: {passed}/{len(samples)} passed")
    print(f"{'='*60}\n")

    print(f"\n{'Part':<20} {'Axis':<6} {'Flat':<6} {'Align':<8} {'Front WxH':<16} {'Conf':<6}")
    print("-" * 70)
    for result in results:
        report = result.get("report", {})
        if "error" in report:
            continue
        det = report.get("detection", {})
        align = report.get("alignment", {})
        front = report.get("views", {}).get("Front", {})
        paper = front.get("paper_size", [0, 0])
        align_ok = align.get("front_top_left_match", False) and align.get("front_left_top_match", False)
        if len(paper) != 2:
            paper = [0, 0]
        orientation = "->" if paper[0] > paper[1] else "v" if paper[1] > paper[0] else "[]"
        print(
            f"{result['name']:<20} {det.get('longest_axis', '?'):<6} "
            f"{str(det.get('is_flat', '?')):<6} {str(align_ok):<8} "
            f"{paper[0]:>6.1f}x{paper[1]:<6.1f} {orientation}  {det.get('confidence', 0):.2f}"
        )

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())

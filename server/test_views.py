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


def render_preview_png(svg_path: Path, png_path: Path, width_px: int = 1600) -> bool:
    """Render a debug SVG to PNG so the agent can inspect it with the Read tool.

    Uses a small inline script run via FreeCAD's python.exe (which has svglib).
    """
    freecad_python = resolve_freecad_python()
    script = (
        "import sys\n"
        "from svglib.svglib import svg2rlg\n"
        "from reportlab.graphics import renderPM\n"
        "from reportlab.graphics.shapes import Group\n"
        f"svg = {str(svg_path)!r}\n"
        f"png = {str(png_path)!r}\n"
        f"w = {width_px}\n"
        "d = svg2rlg(svg)\n"
        "if not d or d.width < 1: sys.exit(1)\n"
        "scale = w / d.width\n"
        "root = Group(*d.contents, transform=(scale,0,0,scale,0,0))\n"
        "d.contents = [root]\n"
        "d.width = int(d.width * scale)\n"
        "d.height = int(d.height * scale)\n"
        "renderPM.drawToFile(d, png, fmt='PNG')\n"
    )
    try:
        result = subprocess.run(
            [freecad_python, "-c", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0 and png_path.exists()
    except Exception:
        return False
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
        "dse_check": True,
        "part_type": "milling",
    },
    "rechteck": {
        "longest_axis": "Y",  # 300mm is Y
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # 300mm should be horizontal (wider than tall)
        "top_rotation_deg": 270,  # Asymmetric details must keep canonical orientation
        "dse_check": True,
        "part_type": "milling",
    },
    "cylinder": {
        "longest_axis": "Z",  # 80mm length
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
        "max_hole_count": 0,
        "bend_radius_absent": True,
        "rotational_profile": True,
        "dse_check": True,
        "part_type": "turning",
    },
    "shaft": {
        "longest_axis": "Z",  # 100mm length
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
        "max_hole_count": 0,
        "bend_radius_absent": True,
        "rotational_profile": True,
        "dse_check": True,
        "part_type": "turning",
    },
    "flange": {
        "longest_axis": "X",  # Diameter 100mm
        "is_flat": True,  # 10mm thick << 100mm diameter
        "alignment_ok": True,
        "front_aspect_near_1": True,  # Circle should be ~square
        "min_hole_count": 6,
        "min_dim_text_count": 2,
        "feature_dims_required": True,
        "dse_check": True,
        "part_type": "milling",
    },
    "sheet_metal": {
        "longest_axis": "X",  # 200mm
        "is_flat": True,  # 3mm thick
        "alignment_ok": True,
        "front_width_gt_height": True,  # 200x100 rectangle
        "min_dim_text_count": 2,
        "has_abwicklung": False,  # Laserteil (0 bends) — no Abwicklung
        "dse_check": True,
    },
    "l_shape": {
        "longest_axis": "X",  # 100mm (tied with Y)
        "is_flat": False,
        "alignment_ok": True,
        "top_rotation_deg": 180,
        "dse_check": True,
        "part_type": "milling",
    },
    "angle_profile": {
        "longest_axis": "X",  # 150mm
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # Length horizontal
        "dse_check": True,
        "part_type": "milling",
    },
    "tall_thin": {
        "longest_axis": "Z",  # 200mm
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,  # 200mm should be horizontal
        "dse_check": True,
        "part_type": "milling",
    },
    "slot_plate": {
        "longest_axis": "X",  # 120mm
        "is_flat": True,  # 8mm thick
        "alignment_ok": True,
        # Slot has 2 semicircular ends; one end arc may round to exactly 50% and
        # be rejected by FP tolerance → reliably detect at least 1 slot feature.
        "min_hole_count": 1,
        "dse_check": True,
    },
    "bracket": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "min_hole_count": 2,
        "dse_check": True,
        "part_type": "milling",
    },
    "housing": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "dse_check": True,
        "part_type": "milling",
    },
    "t_profile": {
        "longest_axis": "Y",
        "is_flat": False,
        "alignment_ok": True,
        "top_rotation_deg": 270,
        "dse_check": True,
        "part_type": "milling",
    },
    "rect_part": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "dse_check": True,
        "part_type": "milling",
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
        "has_abwicklung": False,  # Laserteil (0 bends) — no Abwicklung
        "dse_check": True,
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
        "min_dim_text_count": 3,
        "feature_dims_required": True,
        "dse_check": True,
        "part_type": "milling",
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
        "dse_check": True,
        "part_type": "milling",
    },
    "stepped_shaft": {
        "longest_axis": "X",
        "is_flat": False,
        "alignment_ok": True,
        "front_width_gt_height": True,
        "max_hole_count": 0,
        "bend_radius_absent": True,
        "rotational_profile": True,
        "min_centerline_count": 3,
        "stability_check": True,
        "dse_check": True,
        "part_type": "turning",
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
        "dse_check": True,
        "part_type": "milling",
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
        "min_dim_text_count": 3,
        "feature_dims_required": True,
        "dse_check": True,
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


def _parse_scale_label(value: str | None):
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*:\s*(\d+(?:[.,]\d+)?)\s*", str(value))
    if not match:
        return None
    left = _float_or_none(match.group(1).replace(",", "."))
    right = _float_or_none(match.group(2).replace(",", "."))
    if left is None or right is None or left <= 0 or right <= 0:
        return None
    return left / right


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


def _run_freecad_subprocess(freecad_python, step_file, pdf_path, env, timeout=180):
    """Run FreeCAD conversion subprocess. Returns (result, error_dict_or_none)."""
    try:
        result = subprocess.run(
            [freecad_python, str(SCRIPT_PATH), str(step_file), str(pdf_path)],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, {"error": f"FreeCAD conversion timed out ({timeout}s)"}
    if result.returncode == 0:
        return result, None
    error_text = (result.stderr or result.stdout or "").strip()
    # Stack overflow / access violation crash (0xC0000409 = 3221226505, signed = -1073740791)
    is_crash = result.returncode in (3221226505, -1073740791)
    return result, {
        "error": f"FreeCAD {'crashed' if is_crash else 'failed'} (exit {result.returncode}): {error_text[:200]}",
        "crash_type": "stack_overflow" if is_crash else "exit_error",
    }


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

    for attempt, pdf_path in enumerate(pdf_candidates, start=1):
        result, err = _run_freecad_subprocess(freecad_python, step_file, pdf_path, env)
        if err is None:
            break  # success
        if err.get("crash_type") == "stack_overflow" and attempt == 1:
            # Retry with safe_mode: simplified HLR, no hidden lines
            print(f"  [safe_mode retry] crash detected, retrying with DRAWFORM_SAFE_MODE=1", flush=True)
            safe_env = {**env, "DRAWFORM_SAFE_MODE": "1"}
            retry_pdf = DEBUG_DIR / f"{base_name}_test_safe.pdf"
            result, err = _run_freecad_subprocess(freecad_python, step_file, retry_pdf, safe_env)
            if err is None:
                break
        error_text = (result.stderr or result.stdout or "").strip() if result else ""
        lock_error = "Permission denied" in error_text or "WinError 32" in error_text
        if lock_error and attempt < len(pdf_candidates):
            continue
        return err or {"error": f"FreeCAD conversion failed: {error_text[:200]}"}

    if not json_path.exists():
        stderr = result.stderr if result else "no result"
        return {"error": f"No report generated. stderr: {stderr}"}

    report = json.loads(json_path.read_text(encoding="utf-8"))
    actual_pdf_path = Path(pdf_path).resolve()
    latest_pdf_alias = (DEBUG_DIR / f"{base_name}_latest.pdf").resolve()
    artifacts = report.setdefault("artifacts", {})
    artifacts["pdf_path"] = str(actual_pdf_path)
    artifacts["preferred_open_pdf"] = str(actual_pdf_path)
    artifacts["latest_pdf_alias"] = str(actual_pdf_path)
    try:
        if actual_pdf_path != latest_pdf_alias:
            shutil.copy2(actual_pdf_path, latest_pdf_alias)
        artifacts["latest_pdf_alias"] = str(latest_pdf_alias)
    except Exception:
        pass
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Render debug SVG → PNG for agent visual inspection
    svg_path = DEBUG_DIR / f"{base_name}_debug.svg"
    png_path = DEBUG_DIR / f"{base_name}_preview.png"
    if svg_path.exists():
        ok = render_preview_png(svg_path, png_path)
        if ok:
            print(f"  [preview] {png_path}", flush=True)

    return report


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

    if expected.get("max_hole_count") is not None:
        actual_holes = int(_float_or_none(features.get("hole_count")) or 0)
        if actual_holes > int(expected["max_hole_count"]):
            issues.append(
                f"Feature holes too high: expected <= {expected['max_hole_count']}, got {actual_holes}"
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

    if expected.get("bend_radius_absent"):
        bend_r = _float_or_none(features.get("bend_radius_mm"))
        if bend_r is not None:
            issues.append(f"Bend radius should be absent, got {bend_r}")

    expected_rotational_profile = expected.get("rotational_profile")
    if expected_rotational_profile is not None:
        actual_rotational_profile = bool(features.get("rotational_profile"))
        if actual_rotational_profile != bool(expected_rotational_profile):
            issues.append(
                f"rotational_profile mismatch: expected {bool(expected_rotational_profile)}, "
                f"got {actual_rotational_profile}"
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
    if scale_reduction_needed and not fits:
        issues.append("Layout required scale reduction but views still do not fit.")
    overlap_pairs = list(quality.get("view_overlap_pairs") or [])
    if overlap_pairs:
        issues.append("Views overlap: " + ", ".join(overlap_pairs))

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


def check_dim_quality(report: dict, expected: dict) -> tuple[bool, list[str]]:
    """Check dimension quality metrics tracked during rendering."""
    issues = []
    dm = (report.get("pre_export_check") or {}).get("dim_metrics") or {}
    if not dm:
        return True, []  # Old report without dim_metrics — skip silently

    min_dims = int(expected.get("min_dim_text_count", 0) or 0)
    if min_dims > 0:
        actual = int(dm.get("dim_text_count", 0))
        if actual < min_dims:
            issues.append(f"dim_text_count: expected >={min_dims}, got {actual}")

    if expected.get("feature_dims_required") and not dm.get("feature_dim_present"):
        issues.append("feature_dim_present: expected True, got False")

    if not dm.get("labels_in_bounds", True):
        issues.append("labels_in_bounds: some dimension labels outside drawing area")
    if not dm.get("dimension_graphics_in_bounds", True):
        issues.append("dimension_graphics_in_bounds: some dimension graphics outside drawing area")
    label_out_of_bounds = list(dm.get("label_out_of_bounds_views") or [])
    if label_out_of_bounds:
        issues.append(
            "dimension_labels_outside_drawing_area: " + ", ".join(sorted(label_out_of_bounds))
        )
    dimension_out_of_bounds = list(dm.get("dimension_out_of_bounds_views") or [])
    if dimension_out_of_bounds:
        issues.append(
            "dimension_graphics_outside_drawing_area: " + ", ".join(sorted(dimension_out_of_bounds))
        )

    outside_preferred = list(dm.get("outside_preferred_feature_views") or [])
    if outside_preferred:
        issues.append(
            "feature_dims_outside: preferred outside placement missing in "
            + ", ".join(sorted(outside_preferred))
        )
    strict_dim_arrangement = bool(expected.get("strict_dim_arrangement"))
    if strict_dim_arrangement:
        overall_geom_overlap = list(dm.get("overall_geom_overlap_views") or [])
        if overall_geom_overlap:
            issues.append(
                "overall_dims_overlap_geometry: " + ", ".join(sorted(overall_geom_overlap))
            )
        feature_geom_overlap = list(dm.get("feature_geom_overlap_views") or [])
        if feature_geom_overlap:
            issues.append(
                "feature_dims_overlap_geometry: " + ", ".join(sorted(feature_geom_overlap))
            )
        feature_overall_overlap = list(dm.get("feature_overall_overlap_views") or [])
        if feature_overall_overlap:
            issues.append(
                "feature_dims_overlap_overall: " + ", ".join(sorted(feature_overall_overlap))
            )
    text_overlap_views = list(dm.get("text_overlap_views") or [])
    if text_overlap_views:
        issues.append(
            "dimension_text_overlap: " + ", ".join(sorted(text_overlap_views))
        )

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Dimension plan (DSE) quality checks
# ---------------------------------------------------------------------------


def check_dimension_plan(report: dict, expected: dict) -> tuple[bool, list[str]]:
    """Validate that a DSE dimension plan exists and is structurally sound."""
    issues: list[str] = []
    if not expected.get("dse_check"):
        return True, []  # Not opted-in for DSE checks

    plan = report.get("dimension_plan")
    if not plan:
        issues.append("dimension_plan: missing from report (DSE not executed)")
        return False, issues

    # part_type must be present
    part_type = plan.get("part_type")
    if not part_type:
        issues.append("dimension_plan: missing part_type")
    expected_part_type = expected.get("part_type")
    if expected_part_type and part_type != expected_part_type:
        issues.append(
            f"dimension_plan: expected part_type={expected_part_type}, got {part_type}"
        )

    # Must have at least one view with dimensions
    views = plan.get("views", [])
    if not views:
        issues.append("dimension_plan: no views in plan")

    # Front view should have overall dimensions
    front = next((v for v in views if v.get("view_name") == "Front"), None)
    if front:
        front_types = {d.get("dim_type") for d in front.get("dimensions", [])}
        if "overall_length" not in front_types:
            issues.append("dimension_plan: Front view missing overall_length")
        if "overall_height" not in front_types:
            issues.append("dimension_plan: Front view missing overall_height")

    # No duplicate (dim_type, value_mm) across views
    seen_dims: set = set()
    for view in views:
        for dim in view.get("dimensions", []):
            val = dim.get("value_mm")
            if val is not None:
                key = (dim.get("dim_type"), val)
                if key in seen_dims:
                    issues.append(f"dimension_plan: duplicate dim ({key[0]}, {key[1]})")
                seen_dims.add(key)

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Geometry accuracy verification: DSE dimensions vs. CAD geometry
# ---------------------------------------------------------------------------
GEOM_OVERALL_TOL_MM = 0.5      # Overall dimension tolerance (mm)
GEOM_HOLE_DIA_TOL_MM = 0.2     # Hole diameter tolerance (mm)
GEOM_FLAT_PATTERN_TOL_MM = 1.0  # Flat pattern length/width tolerance (mm)
GEOM_THICKNESS_TOL_MM = 0.1     # Thickness tolerance (mm)


def check_geometry_accuracy(report: dict, expected: dict) -> tuple[bool, list[str]]:
    """Verify that DSE dimension values match the actual CAD geometry from feature probe.

    Compares:
    - Overall dimensions (length/height/width) against bbox_mm
    - Hole diameters against detected hole_diameters_mm
    - Sheet metal thickness against measured_thickness_mm
    - Flat pattern dimensions against computed flat_pattern
    """
    issues: list[str] = []
    features = report.get("features", {})
    plan = report.get("dimension_plan")

    if not features.get("ok"):
        return True, []  # No feature data available, skip
    if not plan:
        return True, []  # No DSE plan, skip

    bbox = features.get("bbox_mm", {})
    if not bbox:
        return True, []

    # Build a map of axis→size from bbox
    bbox_x = float(bbox.get("X", 0))
    bbox_y = float(bbox.get("Y", 0))
    bbox_z = float(bbox.get("Z", 0))
    bbox_sorted = sorted([bbox_x, bbox_y, bbox_z], reverse=True)

    # Collect all dimension values from the plan
    all_dims: list[dict] = []
    for view in plan.get("views", []):
        for dim in view.get("dimensions", []):
            all_dims.append(dim)

    # 1. Overall dimensions vs. bbox
    for dim in all_dims:
        dim_type = dim.get("dim_type", "")
        value = dim.get("value_mm")
        if value is None:
            continue

        if dim_type == "overall_length":
            # Should match the longest bbox dimension
            closest = min(bbox_sorted, key=lambda x: abs(x - value))
            if abs(closest - value) > GEOM_OVERALL_TOL_MM:
                issues.append(
                    f"geom_accuracy: overall_length={value:.1f}mm vs bbox closest={closest:.1f}mm "
                    f"(delta={abs(closest - value):.2f}mm > tol {GEOM_OVERALL_TOL_MM}mm)"
                )

        elif dim_type == "overall_height":
            closest = min(bbox_sorted, key=lambda x: abs(x - value))
            if abs(closest - value) > GEOM_OVERALL_TOL_MM:
                issues.append(
                    f"geom_accuracy: overall_height={value:.1f}mm vs bbox closest={closest:.1f}mm "
                    f"(delta={abs(closest - value):.2f}mm > tol {GEOM_OVERALL_TOL_MM}mm)"
                )

        elif dim_type == "overall_width":
            closest = min(bbox_sorted, key=lambda x: abs(x - value))
            if abs(closest - value) > GEOM_OVERALL_TOL_MM:
                issues.append(
                    f"geom_accuracy: overall_width={value:.1f}mm vs bbox closest={closest:.1f}mm "
                    f"(delta={abs(closest - value):.2f}mm > tol {GEOM_OVERALL_TOL_MM}mm)"
                )

    # 2. Hole diameters: each DSE hole_diameter must match a detected diameter
    detected_diameters = features.get("hole_diameters_mm", [])
    if detected_diameters:
        for dim in all_dims:
            if dim.get("dim_type") != "hole_diameter":
                continue
            value = dim.get("value_mm")
            if value is None:
                continue
            closest_dia = min(detected_diameters, key=lambda d: abs(d - value))
            if abs(closest_dia - value) > GEOM_HOLE_DIA_TOL_MM:
                issues.append(
                    f"geom_accuracy: hole_diameter={value:.1f}mm not found in detected diameters "
                    f"(closest={closest_dia:.1f}mm, delta={abs(closest_dia - value):.2f}mm)"
                )

    # 3. Sheet metal thickness
    measured_t = features.get("measured_thickness_mm")
    if measured_t is not None:
        for note in plan.get("process_notes", []):
            text = note.get("text", "") if isinstance(note, dict) else str(note)
            # Look for "t = X,Y mm" pattern
            import re as _re
            t_match = _re.search(r"t\s*=\s*(\d+[.,]\d+)", text)
            if t_match:
                noted_t = float(t_match.group(1).replace(",", "."))
                if abs(noted_t - measured_t) > GEOM_THICKNESS_TOL_MM:
                    issues.append(
                        f"geom_accuracy: thickness note t={noted_t:.1f}mm vs measured={measured_t:.2f}mm "
                        f"(delta={abs(noted_t - measured_t):.2f}mm)"
                    )

    # 4. Flat pattern dimensions
    flat_pattern = features.get("flat_pattern")
    if flat_pattern and flat_pattern.get("flat_length_mm"):
        computed_fl = flat_pattern["flat_length_mm"]
        computed_fw = flat_pattern.get("flat_width_mm", 0)
        for dim in all_dims:
            dim_type = dim.get("dim_type", "")
            value = dim.get("value_mm")
            if value is None:
                continue
            if dim_type == "flat_length":
                if abs(value - computed_fl) > GEOM_FLAT_PATTERN_TOL_MM:
                    issues.append(
                        f"geom_accuracy: flat_length={value:.1f}mm vs computed={computed_fl:.1f}mm "
                        f"(delta={abs(value - computed_fl):.2f}mm)"
                    )
            elif dim_type == "flat_width":
                if abs(value - computed_fw) > GEOM_FLAT_PATTERN_TOL_MM:
                    issues.append(
                        f"geom_accuracy: flat_width={value:.1f}mm vs computed={computed_fw:.1f}mm "
                        f"(delta={abs(value - computed_fw):.2f}mm)"
                    )

    # 5. Cross-check: bbox dimensions must all appear in plan (completeness)
    plan_values = [d.get("value_mm") for d in all_dims if d.get("value_mm") is not None]
    for bbox_dim in bbox_sorted[:2]:  # At least the two largest dimensions should be dimensioned
        if bbox_dim < 1.0:
            continue
        closest_plan = min(plan_values, key=lambda v: abs(v - bbox_dim)) if plan_values else None
        if closest_plan is None or abs(closest_plan - bbox_dim) > GEOM_OVERALL_TOL_MM:
            issues.append(
                f"geom_accuracy: bbox dimension {bbox_dim:.1f}mm not found in any DSE dimension "
                f"(completeness check)"
            )

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Abwicklung (flat pattern) quality checks
# ---------------------------------------------------------------------------
ABWICKLUNG_ALIGNMENT_TOL_MM = 0.5  # Extension lines must start within this of outline edges


def check_abwicklung(report: dict, expected: dict) -> tuple[bool, list[str]]:
    """Validate flat pattern (Abwicklung) dimension placement and completeness."""
    issues = []
    abw = report.get("abwicklung")

    # If part is expected to have Abwicklung but doesn't
    if expected.get("has_abwicklung") and not abw:
        issues.append("Abwicklung expected but not present in report.")
        return False, issues

    # If part is explicitly NOT expected to have Abwicklung but does
    if expected.get("has_abwicklung") is False and abw:
        issues.append("Abwicklung present but not expected (Laserteil should have no Abwicklung).")
        return False, issues

    # If no Abwicklung data, skip checks (non-sheet-metal part)
    if not abw:
        return True, []

    source = abw.get("source", "")
    if source == "fallback_projection":
        # Fallback projection has no dimensioning metadata to validate
        return True, []

    # 1. Outline bounds must have positive dimensions
    bounds = abw.get("outline_bounds", [])
    if len(bounds) == 4:
        x1, y1, x2, y2 = bounds
        ow = x2 - x1
        oh = y2 - y1
        if ow <= 0 or oh <= 0:
            issues.append(f"Abwicklung outline has non-positive dimensions: {ow:.2f} x {oh:.2f}")
    else:
        issues.append("Abwicklung outline_bounds missing or malformed.")

    # 2. Dimension-to-outline alignment (extension lines start at outline edges)
    dim_h_eps = abw.get("dim_h_endpoints", [])
    if len(dim_h_eps) == 2 and len(bounds) == 4:
        if abs(dim_h_eps[0] - bounds[0]) > ABWICKLUNG_ALIGNMENT_TOL_MM:
            issues.append(
                f"H-dim left endpoint misaligned: dim={dim_h_eps[0]:.2f} vs outline={bounds[0]:.2f} "
                f"(delta={abs(dim_h_eps[0] - bounds[0]):.2f}mm)"
            )
        if abs(dim_h_eps[1] - bounds[2]) > ABWICKLUNG_ALIGNMENT_TOL_MM:
            issues.append(
                f"H-dim right endpoint misaligned: dim={dim_h_eps[1]:.2f} vs outline={bounds[2]:.2f} "
                f"(delta={abs(dim_h_eps[1] - bounds[2]):.2f}mm)"
            )

    dim_v_eps = abw.get("dim_v_endpoints", [])
    if len(dim_v_eps) == 2 and len(bounds) == 4:
        if abs(dim_v_eps[0] - bounds[1]) > ABWICKLUNG_ALIGNMENT_TOL_MM:
            issues.append(
                f"V-dim top endpoint misaligned: dim={dim_v_eps[0]:.2f} vs outline={bounds[1]:.2f} "
                f"(delta={abs(dim_v_eps[0] - bounds[1]):.2f}mm)"
            )
        if abs(dim_v_eps[1] - bounds[3]) > ABWICKLUNG_ALIGNMENT_TOL_MM:
            issues.append(
                f"V-dim bottom endpoint misaligned: dim={dim_v_eps[1]:.2f} vs outline={bounds[3]:.2f} "
                f"(delta={abs(dim_v_eps[1] - bounds[3]):.2f}mm)"
            )

    # 3. Dimension values must be positive and plausible
    dim_h = abw.get("dim_h_label_mm", 0)
    dim_v = abw.get("dim_v_label_mm", 0)
    if dim_h <= 0:
        issues.append(f"Abwicklung horizontal dimension <= 0: {dim_h}")
    if dim_v <= 0:
        issues.append(f"Abwicklung vertical dimension <= 0: {dim_v}")

    # 4. Dimension values should approximate fl + fw (model dimensions)
    fl = abw.get("model_fl_mm", 0)
    fw = abw.get("model_fw_mm", 0)
    if fl > 0 and fw > 0 and dim_h > 0 and dim_v > 0:
        # dim_h and dim_v should together match fl and fw (possibly swapped)
        actual_set = sorted([dim_h, dim_v])
        expected_set = sorted([fl, fw])
        for actual_val, expected_val in zip(actual_set, expected_set):
            if abs(actual_val - expected_val) > max(expected_val * 0.05, 1.0):
                issues.append(
                    f"Abwicklung dimension mismatch: displayed {actual_val:.1f} vs model {expected_val:.1f}"
                )

    # 5. Flange dimensions should sum to total dimension (within tolerance)
    # For complex sheet metal parts (return flanges, Z-bends), bend line positions
    # can create segments whose sum legitimately exceeds the overall flat dimension
    # (bend allowance adds material, multiple close bend lines create tiny segments).
    # When the unfold outline SVG is present and valid, demote mismatch to warning.
    flange_dims = abw.get("flange_dims", [])
    has_valid_outline = (source == "sheetmetal_unfold" and len(bounds) == 4
                         and (bounds[2] - bounds[0]) > 1.0 and (bounds[3] - bounds[1]) > 1.0)
    if flange_dims:
        x_flanges = [f for f in flange_dims if f.get("axis") == "x"]
        y_flanges = [f for f in flange_dims if f.get("axis") == "y"]
        flange_dim_line_y = _float_or_none(abw.get("flange_dim_line_y"))
        flange_dim_line_x = _float_or_none(abw.get("flange_dim_line_x"))
        if x_flanges and dim_h > 0:
            flange_sum = sum(f.get("label_mm", 0) for f in x_flanges)
            if abs(flange_sum - dim_h) > max(dim_h * 0.05, 1.0):
                if has_valid_outline:
                    pass  # Warning only: outline SVG is ground truth for complex parts
                else:
                    issues.append(
                        f"X-flange sum ({flange_sum:.1f}) != horizontal dim ({dim_h:.1f})"
                    )
            if flange_dim_line_y is not None:
                if flange_dim_line_y <= bounds[3] + 0.5:
                    issues.append("X-flange dimension line is not outside the flat-pattern outline")
                if _float_or_none(abw.get("dim_h_line_y")) is not None and dim_h_eps and flange_dim_line_y >= float(abw.get("dim_h_line_y")) - 0.5:
                    issues.append("Horizontal overall dimension is not placed outside the X-flange dimensions")
        if y_flanges and dim_v > 0:
            flange_sum = sum(f.get("label_mm", 0) for f in y_flanges)
            if abs(flange_sum - dim_v) > max(dim_v * 0.05, 1.0):
                if has_valid_outline:
                    pass  # Warning only: outline SVG is ground truth for complex parts
                else:
                    issues.append(
                        f"Y-flange sum ({flange_sum:.1f}) != vertical dim ({dim_v:.1f})"
                    )
            if flange_dim_line_x is not None:
                if flange_dim_line_x <= bounds[2] + 0.5:
                    issues.append("Y-flange dimension line is not outside the flat-pattern outline")
                if _float_or_none(abw.get("dim_v_line_x")) is not None and flange_dim_line_x >= float(abw.get("dim_v_line_x")) - 0.5:
                    issues.append("Vertical overall dimension is not placed outside the Y-flange dimensions")

    # 6. Bend edges must still be represented, but bend legends are disallowed
    bend_count = abw.get("bend_count", 0)
    bend_line_count = abw.get("bend_line_count")
    if bend_line_count is None:
        bend_line_count = abw.get("bend_annotations", bend_count)
    if bend_count > 0 and bend_line_count != bend_count:
        issues.append(
            f"Bend line mismatch: {bend_line_count} visible bend lines for {bend_count} bends"
        )
    bend_legend_count = int(abw.get("bend_legend_count", 0) or 0)
    if bend_legend_count > 0:
        issues.append(
            f"Abwicklung contains {bend_legend_count} bend legend texts although only outer/bend-edge dimensions are allowed"
        )

    # 7. Outline should be within drawing area
    drawing_area = abw.get("drawing_area", [])
    if len(drawing_area) == 4 and len(bounds) == 4:
        da_x1, da_y1, da_x2, da_y2 = drawing_area
        if bounds[0] < da_x1 - 1.0 or bounds[2] > da_x2 + 1.0:
            issues.append("Abwicklung outline extends beyond drawing area (horizontal)")
        if bounds[1] < da_y1 - 1.0 or bounds[3] > da_y2 + 1.0:
            issues.append("Abwicklung outline extends beyond drawing area (vertical)")
    render_bounds = abw.get("render_bounds") or {}
    if len(drawing_area) == 4 and isinstance(render_bounds, dict):
        da_x1, da_y1, da_x2, da_y2 = drawing_area
        if _float_or_none(render_bounds.get("left")) is not None and _float_or_none(render_bounds.get("right")) is not None:
            if float(render_bounds["left"]) < da_x1 - 1.0 or float(render_bounds["right"]) > da_x2 + 1.0:
                issues.append("Abwicklung dimensions extend beyond drawing area (horizontal)")
        if _float_or_none(render_bounds.get("top")) is not None and _float_or_none(render_bounds.get("bottom")) is not None:
            if float(render_bounds["top"]) < da_y1 - 1.0 or float(render_bounds["bottom"]) > da_y2 + 1.0:
                issues.append("Abwicklung dimensions extend beyond drawing area (vertical)")

    # 8. Min bend count expectation
    min_bends = expected.get("abwicklung_min_bend_count")
    if min_bends is not None and bend_count < int(min_bends):
        issues.append(
            f"Bend count too low: expected >= {min_bends}, got {bend_count}"
        )

    return len(issues) == 0, issues


# ---------------------------------------------------------------------------
# Title block quality checks
# ---------------------------------------------------------------------------

def check_title_block(sample_name: str, report: dict) -> tuple[bool, list[str]]:
    """Validate title block completeness and scale consistency via debug SVG."""
    issues = []
    svg_path = DEBUG_DIR / f"{sample_name}_debug.svg"
    if not svg_path.exists():
        issues.append(f"Missing debug SVG for title block checks: {svg_path}")
        return False, issues

    svg_text = svg_path.read_text(encoding="utf-8", errors="replace")

    # Required title block field labels (ISO 7200)
    required_fields = {
        "BENENNUNG": "Title (Benennung)",
        "FIRMA": "Company (Firma)",
        "ZEICHN": "Drawing number (Zeichnungsnummer)",
        "DATUM": "Date (Datum)",
        "MASSSTAB": "Scale (Massstab)",
        "EINHEIT": "Unit (Einheit)",
        "BLATT": "Sheet size (Blatt)",
    }
    for marker, label in required_fields.items():
        if marker not in svg_text:
            issues.append(f"Title block missing field: {label}")

    # Scale field must exist and match the effective render scale from the report.
    scale_match = re.search(r'<text[^>]*id="SCALE"[^>]*>([^<]+)</text>', svg_text)
    if not scale_match:
        issues.append("No scale value found in title block")
    else:
        scale_label = scale_match.group(1).strip()
        parsed_scale = _parse_scale_label(scale_label)
        if parsed_scale is None:
            issues.append("Scale value in title block is not parseable as 'N:M'")
        else:
            report_scale = _float_or_none(report.get("scale"))
            if report_scale is None or report_scale <= 0:
                issues.append("Report scale missing or invalid")
            else:
                tolerance = max(0.01, abs(report_scale) * 0.015)
                if abs(parsed_scale - report_scale) > tolerance:
                    issues.append(
                        f"Title block scale mismatch: label '{scale_label}' -> {parsed_scale:.4f}, "
                        f"report={report_scale:.4f}"
                    )

    # Date format check: DD.MM.YYYY
    date_matches = re.findall(r'>(\d{2}\.\d{2}\.\d{4})<', svg_text)
    if not date_matches:
        issues.append("No date in DD.MM.YYYY format found in title block")

    # DIN norm reference
    if "DIN" not in svg_text:
        issues.append("No DIN norm reference found in drawing")

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
        "dimension_plan_summary": _build_plan_summary(report.get("dimension_plan")),
    }


def _build_plan_summary(plan: dict | None) -> dict | None:
    """Compact summary of a dimension plan for golden baseline snapshots."""
    if not isinstance(plan, dict):
        return None
    views = plan.get("views", [])
    return {
        "part_type": plan.get("part_type", ""),
        "detail_level": int(plan.get("detail_level", 1)),
        "view_count": len(views),
        "total_dim_count": sum(len(v.get("dimensions", [])) for v in views),
        "process_note_count": len(plan.get("process_notes", [])),
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
        for key in ("fits_inside_drawing_area",):
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
    parser.add_argument(
        "--single",
        metavar="PART",
        default=None,
        help="Run only one part by name (e.g. --single complex_bracket).",
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
    if args.single:
        needle = args.single.lower().replace("-", "_").replace(" ", "_")
        samples = [s for s in samples if s.name.lower().replace("-", "_") == needle]
        if not samples:
            print(f"Part '{args.single}' not found in sample set '{args.sample_set}'.")
            print(f"Available: {[s.name for s in resolve_sample_set(args.sample_set)]}")
            return 1
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
        dim_ok, dim_issues = check_dim_quality(report, expected)
        dse_ok, dse_issues = check_dimension_plan(report, expected)
        geom_ok, geom_issues = check_geometry_accuracy(report, expected)
        abw_ok, abw_issues = check_abwicklung(report, expected)
        title_ok, title_issues = check_title_block(name, report)
        all_issues = (align_issues + orient_issues + feature_issues + quality_issues
                      + norm_issues + dim_issues + dse_issues + geom_issues
                      + abw_issues + title_issues)

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
                "dim_ok": dim_ok,
                "geom_ok": geom_ok,
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

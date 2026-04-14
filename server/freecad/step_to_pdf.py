# ---------------------------------------------------------------------------
# step_to_pdf.py — Main FreeCAD drawing generation pipeline
#
# P2 MODULARIZATION PLAN (not yet extracted):
#   1. step_to_pdf_orchestration.py — main(), FreeCAD doc loading, view creation
#   2. step_to_pdf_layout.py — sheet selection, view positioning, scale computation
#   3. step_to_pdf_flat_pattern.py — build_flat_pattern_overlay(), unfold rendering
#   4. step_to_pdf_feature_dims.py — build_feature_dimension_svg(), feature text
#   5. step_to_pdf_quality_gate.py — evaluate_pre_export_quality(), QualityGateError
#   6. step_to_pdf_title_block.py — build_page_svg(), title block rendering
#
# All modules run inside FreeCAD's Python environment (no pydantic).
# Extract incrementally — keep imports minimal to avoid circular dependencies.
# ---------------------------------------------------------------------------

import json
import os
import re
import sys
import math
import subprocess
import datetime as dt
from pathlib import Path
from xml.sax.saxutils import escape


class QualityGateError(RuntimeError):
    """Raised when the pre-export quality check detects blocker-level issues.

    Exit code 3 distinguishes quality failures from FreeCAD crashes (exit code 1).
    """
    pass

from flat_pattern_helpers import build_flange_segment_metadata
from dimension_placement_helpers import (
    build_feature_outside_band_profile,
    minimum_overall_dimension_offset,
    should_allow_projected_centerlines,
    should_fallback_feature_dims_to_visible_view,
    should_place_feature_dims_outside,
    should_suppress_feature_dims_postcheck,
)
from dimension_quality_helpers import (
    rotated_text_collision_box as quality_rotated_text_collision_box,
    summarize_view_dimension_quality,
    text_collision_box as quality_text_collision_box,
)
from sheet_metal_feature_helpers import inject_folded_sheet_metal_feature_dims
from svg_transform_helpers import (
    svg_uses_y_flip,
    transform_svg_bounds_for_display,
    transform_svg_y_for_display,
)

import FreeCAD as App
import Import
import Part
import TechDraw
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg

try:
    # Reuse analyzer geometry probe for consistent feature extraction.
    from step_feature_probe import compute_payload as probe_feature_payload
except Exception:
    probe_feature_payload = None

SVG_PATH_NUMBER_RE = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
SVG_PATH_TOKEN_RE = re.compile(rf"[MLHVCSQTAZmlhvcsqtaz]|{SVG_PATH_NUMBER_RE}")
SVG_PATH_COMMANDS = set("MLHVCSQTAZmlhvcsqtaz")
SCALE_CANDIDATES = (
    # ISO 5455 preferred scales + DIN 823 supplementary scales (4:1, 2.5:1, 1:2.5).
    # Non-standard ratios (1:3, 1:4, 1:6) removed — they are not in ISO 5455 or DIN 823
    # and caused format_actual_scale_label to produce non-compliant title block labels.
    (20.0, "20:1"),
    (10.0, "10:1"),
    (5.0, "5:1"),
    (4.0, "4:1"),
    (2.5, "2,5:1"),
    (2.0, "2:1"),
    (1.0, "1:1"),
    (0.5, "1:2"),
    (0.4, "1:2,5"),
    (0.2, "1:5"),
    (0.1, "1:10"),
    (0.05, "1:20"),
    (0.02, "1:50"),
    (0.01, "1:100"),
)
ALLOWED_SCALE_LABELS = {label for _, label in SCALE_CANDIDATES}
TOLERANCE_2768_RE = re.compile(r"^(?:din\s+iso|iso)\s*2768-([fmcv])([hkl])?$", re.IGNORECASE)
DEFAULT_STANDARD = "DIN EN ISO 128/129-1"
DEFAULT_PROJECTION = "1. Winkel (DIN EN ISO 5456-2)"
DEFAULT_GENERAL_TOLERANCE = "DIN ISO 2768-mK"
SHEET_SPECS = {
    "A3": {"width": 420.0, "height": 297.0, "title_block_h": 55.0, "template": "iso7200_a3_landscape.svg"},
    "A2": {"width": 594.0, "height": 420.0, "title_block_h": 62.0, "template": "iso7200_a2_landscape.svg"},
}
_DIMENSION_STRATEGY_HOLE_HELPERS = None
_FAILURE_CLASSES_MODULE = None


def _get_failure_classes():
    """Lazy-import failure_classes from rules/ using the same sys.path pattern."""
    global _FAILURE_CLASSES_MODULE
    if _FAILURE_CLASSES_MODULE is not None:
        return _FAILURE_CLASSES_MODULE

    server_root = Path(__file__).resolve().parent.parent
    if str(server_root) not in sys.path:
        sys.path.insert(0, str(server_root))

    try:
        import rules.failure_classes as fc_mod
        _FAILURE_CLASSES_MODULE = fc_mod
    except Exception:
        _FAILURE_CLASSES_MODULE = None
    return _FAILURE_CLASSES_MODULE


def log(message, level="INFO"):
    """Log a message with structured prefix for root cause tracing.

    Levels: INFO, WARN, ERROR, DECISION, QUALITY
    - DECISION: logs a pipeline routing decision (layout profile, view selection, etc.)
    - QUALITY: logs a quality gate finding (blocker, warning)
    """
    sys.stderr.write(f"[drawform:{level}] {message}\n")


def _get_dimension_strategy_hole_helpers():
    global _DIMENSION_STRATEGY_HOLE_HELPERS
    if _DIMENSION_STRATEGY_HOLE_HELPERS is not None:
        return _DIMENSION_STRATEGY_HOLE_HELPERS

    server_root = Path(__file__).resolve().parent.parent
    if str(server_root) not in sys.path:
        sys.path.insert(0, str(server_root))

    from rules.feature_payload_hole_helpers import (
        match_feature_hole_groups,
        summarize_feature_hole_extent,
    )

    _DIMENSION_STRATEGY_HOLE_HELPERS = (
        match_feature_hole_groups,
        summarize_feature_hole_extent,
    )
    return _DIMENSION_STRATEGY_HOLE_HELPERS


def complexity_score(shape):
    """Compute a geometry complexity score for safe_mode decisions.
    Returns dict with individual counts and a composite score.
    The score heavily weights assembly indicators (shells > 2, compounds)
    that correlate with TechDraw HLR crashes, rather than face/edge count alone."""
    n_faces = len(shape.Faces)
    n_edges = len(shape.Edges)
    n_verts = len(shape.Vertexes)
    n_shells = len(shape.Shells) if hasattr(shape, "Shells") else 0
    n_compounds = len(shape.Compounds) if hasattr(shape, "Compounds") else 0
    # Count BSpline surfaces/curves (expensive for HLR)
    n_bspline_faces = 0
    for face in shape.Faces:
        stype = getattr(getattr(face, "Surface", None), "__class__", type(None)).__name__
        if "BSpline" in stype:
            n_bspline_faces += 1
    n_bspline_edges = 0
    for edge in shape.Edges:
        ctype = getattr(getattr(edge, "Curve", None), "__class__", type(None)).__name__
        if "BSpline" in ctype:
            n_bspline_edges += 1
    # Composite score: assembly structure is the primary crash indicator.
    # Single-shell parts (sh=1, co=0) rarely crash regardless of face count.
    # Multi-shell assemblies with compounds are the crash-prone pattern.
    score = (n_faces * 0.05 + n_edges * 0.02 + n_bspline_faces * 1.0
             + n_bspline_edges * 0.3 + max(0, n_shells - 1) * 30.0 + n_compounds * 50.0)
    return {
        "faces": n_faces, "edges": n_edges, "vertexes": n_verts,
        "shells": n_shells, "compounds": n_compounds,
        "bspline_faces": n_bspline_faces, "bspline_edges": n_bspline_edges,
        "score": round(score, 1),
    }


def _bbox_wireframe_svg(shape, direction):
    """Generate a simple bounding-box wireframe SVG as fallback when HLR crashes.
    Projects the 8 BBox corners onto the view plane and draws the outline."""
    bb = shape.BoundBox
    corners_3d = [
        App.Vector(bb.XMin, bb.YMin, bb.ZMin), App.Vector(bb.XMax, bb.YMin, bb.ZMin),
        App.Vector(bb.XMax, bb.YMax, bb.ZMin), App.Vector(bb.XMin, bb.YMax, bb.ZMin),
        App.Vector(bb.XMin, bb.YMin, bb.ZMax), App.Vector(bb.XMax, bb.YMin, bb.ZMax),
        App.Vector(bb.XMax, bb.YMax, bb.ZMax), App.Vector(bb.XMin, bb.YMax, bb.ZMax),
    ]
    # Build orthonormal basis from direction
    d = App.Vector(direction)
    d.normalize()
    # Find a non-parallel reference vector
    ref = App.Vector(0, 0, 1) if abs(d.z) < 0.9 else App.Vector(1, 0, 0)
    right = d.cross(ref)
    right.normalize()
    up = right.cross(d)
    up.normalize()
    # Project corners to 2D
    pts_2d = []
    for c in corners_3d:
        x2d = c.dot(right)
        y2d = -c.dot(up)  # SVG Y-axis is inverted
        pts_2d.append((x2d, y2d))
    # Compute convex hull (simple approach: use min/max for bounding rect)
    xs = [p[0] for p in pts_2d]
    ys = [p[1] for p in pts_2d]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    # Draw projected bbox edges
    edges_idx = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    lines = []
    for i, j in edges_idx:
        px1, py1 = pts_2d[i]
        px2, py2 = pts_2d[j]
        lines.append(f'<line x1="{px1:.3f}" y1="{py1:.3f}" x2="{px2:.3f}" y2="{py2:.3f}" '
                     f'stroke="rgb(0,0,0)" stroke-width="0.35" />')
    return f'<g>\n{"".join(lines)}\n</g>'


def safe_project_to_svg(shape, direction, use_safe_mode=False):
    """Wrapper around TechDraw.projectToSVG with exception handling.
    In safe_mode, uses simplified bbox wireframe projection to avoid HLR crashes.
    Returns (svg_string, ok, degraded)."""
    if use_safe_mode:
        try:
            svg = _bbox_wireframe_svg(shape, direction)
            return svg, True, True
        except (RuntimeError, TypeError, ValueError) as exc:
            log(f"Bbox wireframe fallback also failed: {exc}")
            return '<g></g>', False, True
    try:
        svg = TechDraw.projectToSVG(shape, direction)
        return svg, True, False
    except (RuntimeError, TypeError, ValueError) as exc:
        log(f"TechDraw.projectToSVG failed: {exc} — trying bbox wireframe fallback")
        try:
            svg = _bbox_wireframe_svg(shape, direction)
            return svg, True, True
        except (RuntimeError, TypeError, ValueError):
            return '<g></g>', False, True


def _compute_section_cut(shape, cut_origin, cut_normal):
    """Compute a cross-section of a shape at the given plane.

    Parameters:
        shape: Part.Shape to section
        cut_origin: FreeCAD.Vector — a point on the cutting plane
        cut_normal: FreeCAD.Vector — normal of the cutting plane
    Returns:
        (section_shape, cut_faces) where section_shape is the half-solid
        and cut_faces are the cross-section wire/face outlines, or (None, None) on failure.
    """
    try:
        import FreeCAD
        bb = shape.BoundBox
        n = FreeCAD.Vector(cut_normal)
        if n.Length <= 1e-9:
            return None, None
        n.normalize()

        plane_size = max(bb.DiagonalLength, 10.0) * 2.0
        section_wires = shape.section(Part.makePlane(plane_size, plane_size, cut_origin, n))

        margin = max(bb.DiagonalLength, 10.0)
        if abs(float(n.x)) >= 0.9:
            origin = FreeCAD.Vector(
                float(cut_origin.x) if n.x >= 0 else float(cut_origin.x) - margin * 2.0,
                float(bb.YMin) - margin,
                float(bb.ZMin) - margin,
            )
            box = Part.makeBox(
                margin * 2.0,
                float(bb.YLength) + margin * 2.0,
                float(bb.ZLength) + margin * 2.0,
                origin,
            )
        elif abs(float(n.y)) >= 0.9:
            origin = FreeCAD.Vector(
                float(bb.XMin) - margin,
                float(cut_origin.y) if n.y >= 0 else float(cut_origin.y) - margin * 2.0,
                float(bb.ZMin) - margin,
            )
            box = Part.makeBox(
                float(bb.XLength) + margin * 2.0,
                margin * 2.0,
                float(bb.ZLength) + margin * 2.0,
                origin,
            )
        else:
            origin = FreeCAD.Vector(
                float(bb.XMin) - margin,
                float(bb.YMin) - margin,
                float(cut_origin.z) if n.z >= 0 else float(cut_origin.z) - margin * 2.0,
            )
            box = Part.makeBox(
                float(bb.XLength) + margin * 2.0,
                float(bb.YLength) + margin * 2.0,
                margin * 2.0,
                origin,
            )

        half = shape.cut(box)
        if half.isNull() or half.Volume < 1e-6:
            half = shape.common(box)
        if half.isNull() or half.Volume < 1e-6:
            return None, section_wires

        return half, section_wires
    except Exception as exc:
        log(f"Section cut failed: {exc}")
        return None, None


def _generate_section_view_svg(shape, cut_origin, cut_normal, view_direction, scale=1.0):
    """Generate SVG for a section view with cross-hatching.

    Parameters:
        shape: Part.Shape
        cut_origin: cutting plane origin
        cut_normal: cutting plane normal
        view_direction: projection direction for the section view
        scale: drawing scale
    Returns:
        (svg_string, section_bounds) or (None, None) on failure
    """
    half_solid, section_wires = _compute_section_cut(shape, cut_origin, cut_normal)
    projection_shape = half_solid
    if projection_shape is None and section_wires is not None:
        projection_shape = section_wires
    if projection_shape is None:
        projection_shape = shape

    # Project the cut half when available, otherwise fall back to the actual
    # section geometry so the section view is still visible.
    svg, ok, degraded = safe_project_to_svg(projection_shape, view_direction)
    if not ok:
        return None, None

    # Generate cross-hatching for the cut faces
    hatch_svg = _generate_cross_hatch_svg(section_wires, view_direction, scale)
    if not hatch_svg:
        hatch_svg = _generate_cross_hatch_bounds_svg(extract_svg_bounds(svg), scale)

    combined = f'<g class="section-view">{svg}{hatch_svg}</g>'
    return combined, None


def _generate_cross_hatch_svg(section_wires, view_direction, scale, spacing_mm=2.0, angle_deg=45.0):
    """Generate ISO 128-50 cross-hatching lines for section cut faces.

    Parameters:
        section_wires: Part.Shape containing section outline wires
        view_direction: projection direction
        scale: drawing scale
        spacing_mm: hatch line spacing in mm (ISO 128-50: 1-10mm depending on area)
        angle_deg: hatch line angle (default 45° per ISO 128-50)
    Returns:
        SVG string with hatching pattern
    """
    if section_wires is None or not hasattr(section_wires, "BoundBox"):
        return ""

    try:
        bb = section_wires.BoundBox
        return _generate_cross_hatch_bounds_svg(
            (float(bb.XMin), float(bb.XMax), float(bb.YMin), float(bb.YMax)),
            scale,
            spacing_mm=spacing_mm,
            angle_deg=angle_deg,
        )
    except Exception as exc:
        log(f"Cross-hatch generation failed: {exc}")
        return ""


def _generate_cross_hatch_bounds_svg(bounds, scale, spacing_mm=2.0, angle_deg=45.0):
    """Generate cross-hatching directly from projected 2D bounds."""

    if not bounds or len(bounds) != 4:
        return ""

    try:
        min_x, max_x, min_y, max_y = [float(value) for value in bounds]
        width = max_x - min_x
        height = max_y - min_y

        if width < 0.1 or height < 0.1:
            return ""

        spacing = spacing_mm / max(scale, 0.05)
        sw = max(0.0005, 0.15 / max(scale, 0.05))
        angle_rad = math.radians(angle_deg)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        diag = math.hypot(width, height)
        n_lines = int(diag / spacing) + 2
        cx = (min_x + max_x) / 2
        cy = (min_y + max_y) / 2

        lines = []
        for i in range(-n_lines, n_lines + 1):
            offset = i * spacing
            x1 = cx + offset * cos_a - diag * sin_a
            y1 = cy + offset * sin_a + diag * cos_a
            x2 = cx + offset * cos_a + diag * sin_a
            y2 = cy + offset * sin_a - diag * cos_a
            lines.append(
                f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}"/>'
            )

        return (
            f'<g class="cross-hatch" fill="none" stroke="#000" '
            f'stroke-width="{sw:.4f}" stroke-linecap="butt">'
            + "".join(lines)
            + "</g>"
        )
    except Exception as exc:
        log(f"Cross-hatch generation failed: {exc}")
        return ""


def _build_section_line_svg(
    cut_pos,
    min_pos,
    max_pos,
    label="A",
    scale=1.0,
    stroke_width=0.002,
    cut_axis="V",
):
    """Build the section cutting line indicator on the parent view (ISO 128-40).

    Renders: dashed center line + arrow endpoints + "A" labels at both ends.
    Supports vertical (`cut_axis="V"`) and horizontal (`cut_axis="H"`) cuts.

    Parameters:
        cut_pos: x- or y-coordinate of the cutting plane in local view space
        min_pos, max_pos: extent of the section line along the orthogonal axis
        label: section identifier (e.g. "A" for section A-A)
        scale: drawing scale
        stroke_width: line width
        cut_axis: "V" for a vertical cut line, "H" for a horizontal cut line
    Returns:
        SVG string
    """
    sw = max(0.001, stroke_width * 1.5)
    text_size = max(2.5, 4.0 / max(scale, 0.05))
    ext = text_size * 1.5  # extension beyond the view
    arrow_len = max(1.0, 2.0 / max(scale, 0.05))
    arrow_half = arrow_len * 0.4

    axis_kind = str(cut_axis or "V").strip().upper()
    if axis_kind not in {"H", "V"}:
        axis_kind = "V"

    parts = [f'<g class="section-line">']

    # Dash-dot center line (ISO 128-24: long dash-dot)
    dash = max(3.0, 8.0 / max(scale, 0.05))
    gap = max(0.5, 1.5 / max(scale, 0.05))
    dot = max(0.3, 0.5 / max(scale, 0.05))
    if axis_kind == "H":
        x_left = min_pos - ext
        x_right = max_pos + ext
        cut_y = cut_pos
        parts.append(
            f'<line x1="{x_left:.3f}" y1="{cut_y:.3f}" x2="{x_right:.3f}" y2="{cut_y:.3f}" '
            f'stroke="#000" stroke-width="{sw:.4f}" '
            f'stroke-dasharray="{dash:.2f},{gap:.2f},{dot:.2f},{gap:.2f}"/>'
        )
        parts.append(
            f'<polygon points="{x_left:.3f},{cut_y:.3f} '
            f'{x_left - arrow_len:.3f},{cut_y - arrow_half:.3f} '
            f'{x_left - arrow_len:.3f},{cut_y + arrow_half:.3f}" '
            f'fill="#000" stroke="none"/>'
        )
        parts.append(
            f'<polygon points="{x_right:.3f},{cut_y:.3f} '
            f'{x_right + arrow_len:.3f},{cut_y - arrow_half:.3f} '
            f'{x_right + arrow_len:.3f},{cut_y + arrow_half:.3f}" '
            f'fill="#000" stroke="none"/>'
        )
        label_offset = arrow_len + text_size * 0.8
        parts.append(
            f'<g transform="scale(1,-1)">'
            f'<text x="{x_left - label_offset:.3f}" y="{-(cut_y + text_size * 0.9):.3f}" '
            f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
            f'font-size="{text_size:.2f}" font-weight="bold" fill="#000">'
            f'{escape(label)}</text>'
            f'<text x="{x_right + label_offset * 0.35:.3f}" y="{-(cut_y + text_size * 0.9):.3f}" '
            f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
            f'font-size="{text_size:.2f}" font-weight="bold" fill="#000">'
            f'{escape(label)}</text>'
            f'</g>'
        )
    else:
        y_top = min_pos - ext
        y_bot = max_pos + ext
        cut_x = cut_pos
        parts.append(
            f'<line x1="{cut_x:.3f}" y1="{y_top:.3f}" x2="{cut_x:.3f}" y2="{y_bot:.3f}" '
            f'stroke="#000" stroke-width="{sw:.4f}" '
            f'stroke-dasharray="{dash:.2f},{gap:.2f},{dot:.2f},{gap:.2f}"/>'
        )
        parts.append(
            f'<polygon points="{cut_x:.3f},{y_top:.3f} '
            f'{cut_x - arrow_half:.3f},{y_top - arrow_len:.3f} '
            f'{cut_x + arrow_half:.3f},{y_top - arrow_len:.3f}" '
            f'fill="#000" stroke="none"/>'
        )
        parts.append(
            f'<polygon points="{cut_x:.3f},{y_bot:.3f} '
            f'{cut_x - arrow_half:.3f},{y_bot + arrow_len:.3f} '
            f'{cut_x + arrow_half:.3f},{y_bot + arrow_len:.3f}" '
            f'fill="#000" stroke="none"/>'
        )
        label_offset = arrow_len + text_size * 0.8
        parts.append(
            f'<g transform="scale(1,-1)">'
            f'<text x="{cut_x + text_size * 0.8:.3f}" y="{-(y_top - label_offset):.3f}" '
            f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
            f'font-size="{text_size:.2f}" font-weight="bold" fill="#000">'
            f'{escape(label)}</text>'
            f'<text x="{cut_x + text_size * 0.8:.3f}" y="{-(y_bot + label_offset):.3f}" '
            f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
            f'font-size="{text_size:.2f}" font-weight="bold" fill="#000">'
            f'{escape(label)}</text>'
            f'</g>'
        )

    parts.append('</g>')
    return "\n".join(parts)


def _build_section_view_label_svg(x, y, label="A", scale=1.0):
    """Render the section view title label, e.g. 'A-A' below the section view."""
    text_size = max(3.0, 5.0 / max(scale, 0.05))
    full_label = f"{label}-{label}"
    return (
        f'<g transform="scale(1,-1)">'
        f'<text x="{x:.3f}" y="{-y:.3f}" text-anchor="middle" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-size="{text_size:.2f}" font-weight="bold" fill="#000" '
        f'text-decoration="underline">{escape(full_label)}</text>'
        f'</g>'
    )


def _build_detail_circle_svg(
    cx, cy, radius, label="Z", scale=1.0, stroke_width=0.002,
):
    """Build the detail circle indicator on the parent view (ISO 128-40).

    Renders: thin circle + leader line to label.

    Parameters:
        cx, cy: center of detail region in drawing coordinates
        radius: circle radius in drawing units
        label: detail identifier (e.g. "Z" → rendered as "Detail Z")
        scale: drawing scale
        stroke_width: line width
    Returns:
        SVG string
    """
    sw = max(0.001, stroke_width * 0.8)
    text_size = max(2.5, 4.0 / max(scale, 0.05))
    leader_len = radius * 2.5

    parts = [f'<g class="detail-circle">']

    # Circle outline (thin line per ISO 128-40)
    parts.append(
        f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{radius:.3f}" '
        f'fill="none" stroke="#000" stroke-width="{sw:.4f}"/>'
    )

    # Leader line from circle edge to label (45° up-right)
    lx = cx + radius * 0.707
    ly = cy + radius * 0.707
    end_x = cx + leader_len
    end_y = cy + leader_len

    parts.append(
        f'<line x1="{lx:.3f}" y1="{ly:.3f}" x2="{end_x:.3f}" y2="{end_y:.3f}" '
        f'stroke="#000" stroke-width="{sw:.4f}"/>'
    )

    # Label at the end of the leader
    parts.append(
        f'<g transform="scale(1,-1)">'
        f'<text x="{end_x + text_size * 0.3:.3f}" y="{-end_y:.3f}" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-size="{text_size:.2f}" font-weight="bold" fill="#000">'
        f'{escape(label)}</text>'
        f'</g>'
    )

    parts.append('</g>')
    return "\n".join(parts)


def _build_detail_view_label_svg(x, y, label="Z", zoom_factor=2.0, scale=1.0):
    """Render the detail view title, e.g. 'Detail Z (2:1)' below the zoomed view."""
    text_size = max(3.0, 5.0 / max(scale, 0.05))
    # Format zoom as ISO 5455 scale
    if zoom_factor >= 1.0:
        scale_text = f"{zoom_factor:.0f}:1" if zoom_factor == int(zoom_factor) else f"{zoom_factor:.1f}:1"
    else:
        inv = 1.0 / zoom_factor
        scale_text = f"1:{inv:.0f}" if inv == int(inv) else f"1:{inv:.1f}"
    full_label = f"Detail {label} ({scale_text})"
    return (
        f'<g transform="scale(1,-1)">'
        f'<text x="{x:.3f}" y="{-y:.3f}" text-anchor="middle" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-size="{text_size:.2f}" font-weight="bold" fill="#000" '
        f'text-decoration="underline">{escape(full_label)}</text>'
        f'</g>'
    )


def _generate_detail_view_svg(
    parent_svg, parent_bounds, cx_ratio, cy_ratio,
    radius_mm, zoom_factor, scale,
):
    """Extract and enlarge a circular region from the parent view SVG.

    This creates a clipped, zoomed version of the parent view centered on (cx, cy).

    Parameters:
        parent_svg: full SVG string of the parent view
        parent_bounds: (min_x, max_x, min_y, max_y) of the parent view
        cx_ratio, cy_ratio: center of detail as 0..1 ratios within parent bounds
        radius_mm: clip circle radius in model mm
        zoom_factor: enlargement factor
        scale: parent view scale
    Returns:
        SVG string of the zoomed detail view with circular clip
    """
    _ = scale
    min_x, max_x, min_y, max_y = parent_bounds
    w = max_x - min_x
    h = max_y - min_y
    cx = min_x + cx_ratio * w
    cy = min_y + cy_ratio * h
    r = max(float(radius_mm or 0.0), 1e-3)

    view_radius = r / max(zoom_factor, 1e-3)
    view_size = max(view_radius * 2.0, 1e-3)
    viewport_x = cx - r
    viewport_y = cy - r
    viewbox_x = cx - view_radius
    viewbox_y = cy - view_radius

    # Use a nested SVG viewport instead of clipPath. It is simpler for the
    # export stack and still gives a hard crop plus deterministic zoom.
    detail_svg = (
        f'<g class="detail-view">'
        f'<svg x="{viewport_x:.3f}" y="{viewport_y:.3f}" width="{r * 2.0:.3f}" height="{r * 2.0:.3f}" '
        f'viewBox="{viewbox_x:.3f} {viewbox_y:.3f} {view_size:.3f} {view_size:.3f}" overflow="hidden">'
        f'{parent_svg}'
        f'</svg>'
        f'<circle cx="{cx:.3f}" cy="{cy:.3f}" '
        f'r="{r:.3f}" fill="none" stroke="#000" stroke-width="0.3"/>'
        f'</g>'
    )
    return detail_svg


def read_metadata(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _run_unfold_subprocess(input_path, feature_payload, dxf_output_path=None):
    """Run step_unfold.py as a subprocess and return the result dict, or None.
    If dxf_output_path is given, also export the unfolded shape as DXF."""
    import subprocess as _sp
    import tempfile
    unfold_script = os.path.join(os.path.dirname(__file__), "step_unfold.py")
    if not os.path.exists(unfold_script):
        return None
    freecad_py = sys.executable  # same Python that is running us
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        out_json = tmp.name
    try:
        env = dict(os.environ)
        # Pass K-factor from feature_payload if available
        fp = feature_payload or {}
        flat_pat = fp.get("flat_pattern") or {}
        k = flat_pat.get("k_factor_used")
        if k is not None:
            env["DRAWFORM_K_FACTOR"] = str(k)
        env["DRAWFORM_K_STANDARD"] = "din"
        cmd = [freecad_py, unfold_script, str(input_path), out_json]
        if dxf_output_path:
            cmd.append(str(dxf_output_path))
        result = _sp.run(
            cmd,
            capture_output=True, text=True, timeout=90, env=env,
        )
        if os.path.exists(out_json):
            with open(out_json, "r", encoding="utf-8") as f:
                return json.load(f)
        return None
    except Exception as e:
        log(f"Unfold subprocess error: {e}")
        return None
    finally:
        try:
            os.unlink(out_json)
        except OSError:
            pass


def _extract_part_name(input_path: str) -> str:
    """Extract human-readable part name from STEP filename.

    '202500521_Halteblech Lackierpistole_V1.0' → 'Halteblech Lackierpistole'
    'bracket.stp'                               → 'bracket'
    """
    stem = Path(input_path).stem
    stem = re.sub(r"^\d+_", "", stem)                               # date prefix (any length)
    stem = re.sub(r"_V\d+[\.\d]*$", "", stem, flags=re.IGNORECASE)  # _V1.0 suffix
    stem = stem.replace("_", " ")
    stem = re.sub(r"\s+", " ", stem)
    return stem.strip(" -_")


def normalize_export_metadata(meta):
    payload = dict(meta or {})
    today = dt.date.today().strftime("%d.%m.%Y")
    forced_sheet = str(os.getenv("DRAWFORM_SHEET_FORCE") or "").strip().upper()

    def text_field(key, default, max_len):
        value = str(payload.get(key) or "").strip() or default
        return value[:max_len]

    def normalize_scale_label(value):
        candidate = str(value or "").strip()
        if not candidate or candidate.lower() == "auto":
            return "auto"
        compact = candidate.replace(" ", "")
        return compact if compact in ALLOWED_SCALE_LABELS else "auto"

    def normalize_projection(value):
        projection = str(value or "").strip()
        if not projection:
            return DEFAULT_PROJECTION
        compact = projection.lower().replace(" ", "").replace("-", "")
        if compact in {
            "1.winkel(dineniso54562)",
            "1.winkel",
            "firstangle",
            "1stangle",
            "first_angle",
            "1st_angle",
        }:
            return DEFAULT_PROJECTION
        return DEFAULT_PROJECTION

    def normalize_standard(value):
        standard = str(value or "").strip()
        if not standard:
            return DEFAULT_STANDARD
        compact = standard.lower().replace(" ", "")
        if compact in {
            "dineniso128/129-1",
            "diniso128/129-1",
            "iso128/129-1",
        }:
            return DEFAULT_STANDARD
        return DEFAULT_STANDARD

    def normalize_general_tolerance(value):
        tolerance = str(value or "").strip()
        if not tolerance:
            return DEFAULT_GENERAL_TOLERANCE
        compact = " ".join(tolerance.split()).lower().replace("_", "-")
        if compact in {"f", "fein"}:
            return "DIN ISO 2768-fK"
        if compact in {"m", "mittel"}:
            return "DIN ISO 2768-mK"
        if compact in {"c", "grob"}:
            return "DIN ISO 2768-cK"
        match = re.search(r"2768-([fmcv])([hkl])?", compact)
        if match:
            cls = match.group(1)
            form_cls = (match.group(2) or "K").upper()
            return f"DIN ISO 2768-{cls}{form_cls}"
        match = TOLERANCE_2768_RE.fullmatch(compact)
        if match:
            cls = match.group(1).lower()
            form_cls = (match.group(2) or "K").upper()
            return f"DIN ISO 2768-{cls}{form_cls}"
        return DEFAULT_GENERAL_TOLERANCE

    def normalize_sheet(value):
        if forced_sheet in {"A3", "A2"}:
            return forced_sheet
        sheet = str(value or "").strip().upper()
        if not sheet or sheet == "AUTO":
            return "auto"
        if sheet in {"A3", "A2"}:
            return sheet
        return "auto"

    default_title = _extract_part_name(payload.get("input_path", "")) or "Bauteilzeichnung"
    normalized = {
        "title": text_field("title", default_title, 80),
        "drawing_no": text_field("drawing_no", "DF-0001", 32),
        "revision": text_field("revision", "A", 8),
        "author": text_field("author", "Drawform", 40),
        "company": text_field("company", "Drawform", 40),
        "material": text_field("material", "", 60),
        "deburr_note": text_field("deburr_note", "Alle Kanten 0,2-0,5 entgraten", 90),
        "date": text_field("date", today, 20),
        "unit": "mm" if str(payload.get("unit") or "").strip().lower() in {"", "mm"} else "mm",
        "sheet": normalize_sheet(payload.get("sheet")),
        "scale": normalize_scale_label(payload.get("scale")),
        "views": ["Top", "Front", "Left", "Iso"],
        "standard": normalize_standard(payload.get("standard")),
        "projection": normalize_projection(payload.get("projection")),
        "general_tolerance": normalize_general_tolerance(payload.get("general_tolerance")),
    }
    # Preserve DSE fields passed through from the API / test harness
    if "dimension_plan" in payload:
        normalized["dimension_plan"] = payload["dimension_plan"]
    if "features" in payload:
        normalized["features"] = payload["features"]
    return normalized


def load_shape(doc, step_path):
    log(f"Importing STEP: {step_path}")
    Import.insert(step_path, doc.Name)
    doc.recompute()
    shapes = []
    for obj in doc.Objects:
        if not hasattr(obj, "Shape"):
            continue
        shape = obj.Shape
        if not shape or shape.isNull():
            continue
        # Filter out datum planes/axes imported from STEP assemblies.
        # These are infinite geometry objects with enormous bounding boxes (>1e10mm)
        # that corrupt downstream calculations (TechDraw, scaling, layout).
        # Accept only shapes with Solids, or non-degenerate Faces with bounded extent.
        if shape.Solids:
            shapes.append(shape)
        elif shape.Faces:
            bb = shape.BoundBox
            max_ext = max(bb.XLength, bb.YLength, bb.ZLength)
            if max_ext < 1e6:  # realistic part: < 1km
                shapes.append(shape)
            else:
                log(f"Skipping datum/infinite geometry: {obj.Label} (extent={max_ext:.1e}mm)")
        # Skip pure edges/vertices without faces (axes, construction geometry)
    if not shapes:
        raise RuntimeError("No solid geometry found in STEP file.")
    combined = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
    # Shape healing: removeSplitter merges split faces and simplifies topology.
    # Only apply when multiple shells/compounds indicate assembly STEP with redundant seams.
    # Avoids changing geometry of simple parts (which would break golden baseline regression).
    n_shells = len(combined.Shells) if hasattr(combined, "Shells") else 0
    if n_shells > 2:
        try:
            healed = combined.removeSplitter()
            if healed and not healed.isNull() and len(healed.Faces) > 0:
                hbb = healed.BoundBox
                max_extent = max(hbb.XLength, hbb.YLength, hbb.ZLength)
                if max_extent < 1e6:
                    log(f"Shape healed: {len(combined.Faces)} -> {len(healed.Faces)} faces ({n_shells} shells)")
                    return healed
                else:
                    log(f"removeSplitter produced degenerate bbox ({max_extent:.1e}mm), keeping original")
        except Exception as exc:
            log(f"removeSplitter failed (non-fatal): {exc}")
    return combined


def replace_text(svg, key, value):
    pattern = rf'(<text[^>]*id="{re.escape(key)}"[^>]*>)(.*?)(</text>)'
    def replacer(match):
        return f"{match.group(1)}{escape(str(value))}{match.group(3)}"
    return re.sub(pattern, replacer, svg, flags=re.DOTALL)


def extract_edge_segments(svg_group, min_length=0.5):
    """Extract horizontal and vertical line segments from SVG path data.

    Returns a list of dicts:
        {x1, y1, x2, y2, length, orientation: 'h'|'v'|'d'}
    Only segments longer than *min_length* SVG units are included.
    """
    segments: list[dict] = []
    paths = re.findall(r'd="([^"]+)"', svg_group)
    for path_data in paths:
        tokens = SVG_PATH_TOKEN_RE.findall(path_data)
        if not tokens:
            continue
        index = 0
        cmd = None
        cx, cy = 0.0, 0.0

        def _is_cmd(t):
            return t in SVG_PATH_COMMANDS

        def _add_seg(x1, y1, x2, y2):
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            length = (dx ** 2 + dy ** 2) ** 0.5
            if length < min_length:
                return
            if dy < 0.3 and dx >= min_length:
                orient = "h"
            elif dx < 0.3 and dy >= min_length:
                orient = "v"
            else:
                orient = "d"  # diagonal — skip for step dims
            if orient != "d":
                segments.append({"x1": min(x1, x2), "y1": min(y1, y2),
                                 "x2": max(x1, x2), "y2": max(y1, y2),
                                 "length": length, "orientation": orient})

        while index < len(tokens):
            token = tokens[index]
            if _is_cmd(token):
                cmd = token
                index += 1
            elif cmd is None:
                index += 1
                continue

            prev_x, prev_y = cx, cy

            if cmd in ("M", "m"):
                while index + 1 < len(tokens) and not _is_cmd(tokens[index]):
                    x, y = float(tokens[index]), float(tokens[index + 1])
                    index += 2
                    if cmd == "m":
                        x += cx; y += cy
                    cx, cy = x, y
                continue

            if cmd in ("L", "l"):
                while index + 1 < len(tokens) and not _is_cmd(tokens[index]):
                    x, y = float(tokens[index]), float(tokens[index + 1])
                    index += 2
                    if cmd == "l":
                        x += cx; y += cy
                    _add_seg(cx, cy, x, y)
                    cx, cy = x, y
                continue

            if cmd in ("H", "h"):
                while index < len(tokens) and not _is_cmd(tokens[index]):
                    x = float(tokens[index]); index += 1
                    if cmd == "h":
                        x += cx
                    _add_seg(cx, cy, x, cy)
                    cx = x
                continue

            if cmd in ("V", "v"):
                while index < len(tokens) and not _is_cmd(tokens[index]):
                    y = float(tokens[index]); index += 1
                    if cmd == "v":
                        y += cy
                    _add_seg(cx, cy, cx, y)
                    cy = y
                continue

            if cmd == "Z" or cmd == "z":
                continue

            # Skip curves (C, S, Q, T, A) — consume their parameters
            param_count = {"C": 6, "c": 6, "S": 4, "s": 4,
                           "Q": 4, "q": 4, "T": 2, "t": 2,
                           "A": 7, "a": 7}.get(cmd, 0)
            if param_count:
                while index + param_count - 1 < len(tokens) and not _is_cmd(tokens[index]):
                    for _ in range(param_count):
                        if index < len(tokens) and not _is_cmd(tokens[index]):
                            index += 1
                    # Update current position to last 2 params
                    if param_count >= 2:
                        try:
                            cx = float(tokens[index - 2])
                            cy = float(tokens[index - 1])
                            if cmd.islower():
                                cx += prev_x; cy += prev_y
                        except (ValueError, IndexError):
                            pass
                continue

            index += 1  # fallback: skip unknown

    return segments


def _unique_positions(values, tolerance=0.5):
    """Return sorted unique position values, merging those within tolerance."""
    if not values:
        return []
    vals = sorted(set(values))
    unique = [vals[0]]
    for v in vals[1:]:
        if v - unique[-1] > tolerance:
            unique.append(v)
    return unique


def build_step_dimensions(svg_group, bounds, scale, stroke_width, line_profile=None,
                          label_width=None, label_height=None, max_steps=5,
                          show_horizontal_steps=True, show_vertical_steps=True,
                          horizontal_side="above", horizontal_max_ratio=None):
    """Build ISO 129-1 step dimensions from edge segments.

    Identifies horizontal and vertical steps in the part outline and adds
    cumulative dimension lines from a reference edge (left/bottom).
    Returns an SVG fragment string.
    """
    min_x, max_x, min_y, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    if width < 1 or height < 1:
        return ""

    segments = extract_edge_segments(svg_group, min_length=max(1.0, width * 0.03))
    if not segments:
        return ""

    dim_sw = float((line_profile or {}).get("dimension", stroke_width * 0.6))
    text_size = 3.6 / scale
    arrow_len = max(0.6, min(2.2, max(width, height) * scale * 0.01)) / scale
    arrow_half = arrow_len * 0.35
    gap = 1.0 / scale         # gap between geometry and extension line
    ext_over = 1.5 / scale    # extension line overshoot past dimension line
    step_spacing = 6.0 / scale  # spacing between stacked dimension lines

    parts: list[str] = []

    def _arrow_h(ax, ay, pointing_left):
        if pointing_left:
            pts = f"{ax:.3f},{ay:.3f} {ax+arrow_len:.3f},{ay-arrow_half:.3f} {ax+arrow_len:.3f},{ay+arrow_half:.3f}"
        else:
            pts = f"{ax:.3f},{ay:.3f} {ax-arrow_len:.3f},{ay-arrow_half:.3f} {ax-arrow_len:.3f},{ay+arrow_half:.3f}"
        return f'<polygon points="{pts}" fill="rgb(0,0,0)" />'

    def _arrow_v(ax, ay, pointing_up):
        if pointing_up:
            pts = f"{ax:.3f},{ay:.3f} {ax-arrow_half:.3f},{ay+arrow_len:.3f} {ax+arrow_half:.3f},{ay+arrow_len:.3f}"
        else:
            pts = f"{ax:.3f},{ay:.3f} {ax-arrow_half:.3f},{ay-arrow_len:.3f} {ax+arrow_half:.3f},{ay-arrow_len:.3f}"
        return f'<polygon points="{pts}" fill="rgb(0,0,0)" />'

    # Collect unique X and Y positions from horizontal/vertical segments
    h_segs = [s for s in segments if s["orientation"] == "h"]
    v_segs = [s for s in segments if s["orientation"] == "v"]

    def _pick_step_positions(raw_positions, lower_bound, upper_bound, span, tolerance):
        unique = _unique_positions(list(raw_positions), tolerance=tolerance)
        candidates = [value for value in unique if value > lower_bound and value < upper_bound]
        if not candidates:
            return []

        def _hit_count(value):
            return sum(1 for raw in raw_positions if abs(raw - value) <= tolerance)

        ranked = []
        for value in candidates:
            hits = _hit_count(value)
            edge_dist = min(abs(value - min_x), abs(max_x - value))
            if hits < 2 and edge_dist > span * 0.10:
                continue
            ranked.append((value, hits, edge_dist))

        if not ranked:
            ranked = [
                (value, _hit_count(value), min(abs(value - min_x), abs(max_x - value)))
                for value in candidates
            ]

        ranked.sort(key=lambda item: (-item[1], -item[2], item[0]))
        return sorted(item[0] for item in ranked[:max_steps])

    # Horizontal step dimensions (below geometry):
    # Unique X positions along horizontal segments → step widths from left edge
    x_positions = set()
    for s in h_segs:
        x_positions.add(s["x1"])
        x_positions.add(s["x2"])
    for s in v_segs:
        x_positions.add(s["x1"])  # x1==x2 for vertical
    horizontal_upper_bound = max_x - width * 0.05
    if horizontal_max_ratio is not None:
        max_ratio = max(0.15, min(0.98, float(horizontal_max_ratio)))
        horizontal_upper_bound = min(horizontal_upper_bound, min_x + width * max_ratio)
    step_x = _pick_step_positions(
        list(x_positions),
        min_x + width * 0.05,
        horizontal_upper_bound,
        width,
        tolerance=1.0 / scale,
    )

    # Draw horizontal step dimensions below geometry
    if show_horizontal_steps and step_x:
        direction = 1.0 if str(horizontal_side).lower() != "below" else -1.0
        ref_y = max_y if direction > 0 else min_y
        for i, x_pos in enumerate(step_x):
            dim_y = ref_y + direction * (gap + step_spacing * (i + 2))
            ext_y = dim_y + direction * ext_over
            step_val = (x_pos - min_x) / scale if scale > 0 else 0
            if label_width is not None:
                step_val = (x_pos - min_x) / (max_x - min_x) * label_width
            # Extension lines
            parts.append(f'<line x1="{x_pos:.3f}" y1="{ref_y:.3f}" x2="{x_pos:.3f}" y2="{ext_y:.3f}" stroke="rgb(0,0,0)" stroke-width="{dim_sw:.4f}" />')
            # Left reference extension (only first time)
            if i == 0:
                far_ext_y = ref_y + direction * (gap + step_spacing * (len(step_x) + 1) + ext_over)
                parts.append(f'<line x1="{min_x:.3f}" y1="{ref_y:.3f}" x2="{min_x:.3f}" y2="{far_ext_y:.3f}" stroke="rgb(0,0,0)" stroke-width="{dim_sw:.4f}" />')
            # Dimension line
            parts.append(f'<line x1="{min_x:.3f}" y1="{dim_y:.3f}" x2="{x_pos:.3f}" y2="{dim_y:.3f}" stroke="rgb(0,0,0)" stroke-width="{dim_sw:.4f}" />')
            # Arrows
            parts.append(_arrow_h(min_x, dim_y, True))
            parts.append(_arrow_h(x_pos, dim_y, False))
            # Text
            mid_x = (min_x + x_pos) / 2
            parts.append(
                f'<g fill="rgb(0,0,0)" stroke="none" font-size="{text_size:.3f}" '
                f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
                f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
                f'<text x="{mid_x:.3f}" y="{-dim_y + text_size * 0.3:.3f}" text-anchor="middle">'
                f'{format_de_number(step_val)}</text></g>'
            )

    # Vertical step dimensions (right of geometry):
    y_positions = set()
    for s in v_segs:
        y_positions.add(s["y1"])
        y_positions.add(s["y2"])
    for s in h_segs:
        y_positions.add(s["y1"])
    step_y = _pick_step_positions(
        list(y_positions),
        min_y + height * 0.05,
        max_y - height * 0.05,
        height,
        tolerance=1.0 / scale,
    )

    if show_vertical_steps and step_y:
        for i, y_pos in enumerate(step_y):
            dim_x = max_x + gap + step_spacing * (i + 2)
            step_val = (y_pos - min_y) / scale if scale > 0 else 0
            if label_height is not None:
                step_val = (y_pos - min_y) / (max_y - min_y) * label_height
            # Extension lines
            parts.append(f'<line x1="{max_x:.3f}" y1="{y_pos:.3f}" x2="{dim_x + ext_over:.3f}" y2="{y_pos:.3f}" stroke="rgb(0,0,0)" stroke-width="{dim_sw:.4f}" />')
            if i == 0:
                parts.append(f'<line x1="{max_x:.3f}" y1="{min_y:.3f}" x2="{dim_x + ext_over + step_spacing * (len(step_y) - 1):.3f}" y2="{min_y:.3f}" stroke="rgb(0,0,0)" stroke-width="{dim_sw:.4f}" />')
            # Dimension line
            parts.append(f'<line x1="{dim_x:.3f}" y1="{min_y:.3f}" x2="{dim_x:.3f}" y2="{y_pos:.3f}" stroke="rgb(0,0,0)" stroke-width="{dim_sw:.4f}" />')
            # Arrows
            parts.append(_arrow_v(dim_x, min_y, True))
            parts.append(_arrow_v(dim_x, y_pos, False))
            # Text (rotated)
            mid_y = (min_y + y_pos) / 2
            parts.append(
                f'<g fill="rgb(0,0,0)" stroke="none" font-size="{text_size:.3f}" '
                f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
                f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
                f'<text x="{dim_x - text_size * 0.3:.3f}" y="{-mid_y:.3f}" text-anchor="middle" '
                f'transform="rotate(90,{dim_x - text_size * 0.3:.3f},{-mid_y:.3f})">'
                f'{format_de_number(step_val)}</text></g>'
            )

    return "\n".join(parts)


def extract_svg_bounds(svg_group):
    """
    Extract bounding box from SVG elements including paths and circles.
    Correctly handles SVG path commands (M, L, A, etc.) to extract only coordinates.
    Arc commands (A/a) have format: A rx ry x-rotation large-arc sweep x y
    where only the last two numbers are coordinates.
    """
    coords = []
    
    # Extract from path elements
    paths = re.findall(r'd="([^"]+)"', svg_group)
    for path in paths:
        coords.extend(_extract_path_coords(path, include_arc_envelopes=True))
    
    # Extract from circle elements (attribute order may vary)
    for circle in re.findall(r'<circle[^>]+>', svg_group):
        cx_m = re.search(r'cx\s*=\s*"([^"]+)"', circle)
        cy_m = re.search(r'cy\s*=\s*"([^"]+)"', circle)
        r_m = re.search(r'\br\s*=\s*"([^"]+)"', circle)
        if cx_m and cy_m and r_m:
            cx, cy, r = float(cx_m.group(1)), float(cy_m.group(1)), float(r_m.group(1))
            coords.append((cx - r, cy - r))
            coords.append((cx + r, cy + r))
    
    # Extract from ellipse elements: <ellipse cx="X" cy="Y" rx="RX" ry="RY" />
    ellipses = re.findall(r'<ellipse[^>]+>', svg_group)
    for ellipse in ellipses:
        cx_match = re.search(r'cx\s*=\s*"([^"]+)"', ellipse)
        cy_match = re.search(r'cy\s*=\s*"([^"]+)"', ellipse)
        rx_match = re.search(r'rx\s*=\s*"([^"]+)"', ellipse)
        ry_match = re.search(r'ry\s*=\s*"([^"]+)"', ellipse)
        if cx_match and cy_match and rx_match and ry_match:
            cx = float(cx_match.group(1))
            cy = float(cy_match.group(1))
            rx = float(rx_match.group(1))
            ry = float(ry_match.group(1))
            coords.append((cx - rx, cy - ry))
            coords.append((cx + rx, cy + ry))
    
    # Extract from line elements: <line x1="X1" y1="Y1" x2="X2" y2="Y2" />
    lines = re.findall(r'<line[^>]+>', svg_group)
    for line in lines:
        x1 = re.search(r'x1\s*=\s*"([^"]+)"', line)
        y1 = re.search(r'y1\s*=\s*"([^"]+)"', line)
        x2 = re.search(r'x2\s*=\s*"([^"]+)"', line)
        y2 = re.search(r'y2\s*=\s*"([^"]+)"', line)
        if x1 and y1:
            coords.append((float(x1.group(1)), float(y1.group(1))))
        if x2 and y2:
            coords.append((float(x2.group(1)), float(y2.group(1))))
    
    # Extract from rect elements: <rect x="X" y="Y" width="W" height="H" />
    rects = re.findall(r'<rect[^>]+>', svg_group)
    for rect in rects:
        x = re.search(r'\bx\s*=\s*"([^"]+)"', rect)
        y = re.search(r'\by\s*=\s*"([^"]+)"', rect)
        w = re.search(r'width\s*=\s*"([^"]+)"', rect)
        h = re.search(r'height\s*=\s*"([^"]+)"', rect)
        if x and y and w and h:
            rx, ry = float(x.group(1)), float(y.group(1))
            rw, rh = float(w.group(1)), float(h.group(1))
            coords.append((rx, ry))
            coords.append((rx + rw, ry + rh))
    
    if not coords:
        return 0.0, 1.0, 0.0, 1.0
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]
    return min(xs), max(xs), min(ys), max(ys)


def _normalize_angle_2pi(angle):
    two_pi = 2.0 * math.pi
    while angle < 0.0:
        angle += two_pi
    while angle >= two_pi:
        angle -= two_pi
    return angle


def _svg_vector_angle(ux, uy, vx, vy):
    return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)


def _svg_arc_center_params(x1, y1, rx, ry, xrot_deg, large_arc, sweep, x2, y2):
    rx = abs(float(rx))
    ry = abs(float(ry))
    if rx <= 1e-8 or ry <= 1e-8:
        return None

    phi = math.radians(float(xrot_deg) % 360.0)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    dx2 = (x1 - x2) * 0.5
    dy2 = (y1 - y2) * 0.5
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale

    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    if abs(den) <= 1e-12:
        return None
    sign = -1.0 if int(large_arc) == int(sweep) else 1.0
    coef = sign * math.sqrt(max(0.0, num / den))

    cxp = coef * ((rx * y1p) / ry)
    cyp = coef * (-(ry * x1p) / rx)
    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) * 0.5
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) * 0.5

    ux = (x1p - cxp) / rx
    uy = (y1p - cyp) / ry
    vx = (-x1p - cxp) / rx
    vy = (-y1p - cyp) / ry
    theta1 = _svg_vector_angle(1.0, 0.0, ux, uy)
    delta = _svg_vector_angle(ux, uy, vx, vy)
    if not int(sweep) and delta > 0.0:
        delta -= 2.0 * math.pi
    elif int(sweep) and delta < 0.0:
        delta += 2.0 * math.pi

    return {
        "cx": cx,
        "cy": cy,
        "rx": rx,
        "ry": ry,
        "phi": phi,
        "theta1": theta1,
        "delta": delta,
    }


def _svg_arc_contains_angle(angle, start_angle, delta_angle, tol=1e-6):
    angle = _normalize_angle_2pi(angle)
    start = _normalize_angle_2pi(start_angle)
    if delta_angle >= 0.0:
        span = min(delta_angle, 2.0 * math.pi)
        diff = (angle - start) % (2.0 * math.pi)
        return diff <= span + tol
    span = min(-delta_angle, 2.0 * math.pi)
    diff = (start - angle) % (2.0 * math.pi)
    return diff <= span + tol


def _svg_arc_bbox_points(x1, y1, rx, ry, xrot_deg, large_arc, sweep, x2, y2):
    params = _svg_arc_center_params(x1, y1, rx, ry, xrot_deg, large_arc, sweep, x2, y2)
    if not params:
        return [(x1, y1), (x2, y2)]

    cx = params["cx"]
    cy = params["cy"]
    rx = params["rx"]
    ry = params["ry"]
    phi = params["phi"]
    theta1 = params["theta1"]
    delta = params["delta"]

    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    def arc_point(theta):
        ct = math.cos(theta)
        st = math.sin(theta)
        return (
            cx + rx * ct * cos_phi - ry * st * sin_phi,
            cy + rx * ct * sin_phi + ry * st * cos_phi,
        )

    candidates = [theta1, theta1 + delta]
    candidates.extend([
        math.atan2(-ry * sin_phi, rx * cos_phi),
        math.atan2(-ry * sin_phi, rx * cos_phi) + math.pi,
        math.atan2(ry * cos_phi, rx * sin_phi),
        math.atan2(ry * cos_phi, rx * sin_phi) + math.pi,
    ])

    points = []
    for theta in candidates:
        if _svg_arc_contains_angle(theta, theta1, delta):
            points.append(arc_point(theta))
    if not points:
        points = [(x1, y1), (x2, y2)]
    return points


def _extract_path_coords(path_data, include_arc_envelopes=False):
    """Parse SVG path data and return coordinate points relevant for bounds/scoring."""
    tokens = SVG_PATH_TOKEN_RE.findall(path_data)
    if not tokens:
        return []

    coords = []
    index = 0
    cmd = None
    cx = 0.0
    cy = 0.0
    sx = None
    sy = None

    def is_cmd(token):
        return token in SVG_PATH_COMMANDS

    while index < len(tokens):
        token = tokens[index]
        if is_cmd(token):
            cmd = token
            index += 1
        elif cmd is None:
            index += 1
            continue

        if cmd in ("M", "m"):
            first_move = True
            while index + 1 < len(tokens) and not is_cmd(tokens[index]):
                x = float(tokens[index])
                y = float(tokens[index + 1])
                index += 2
                if cmd == "m":
                    x += cx
                    y += cy
                cx, cy = x, y
                if first_move:
                    sx, sy = cx, cy
                    first_move = False
                coords.append((cx, cy))
            continue

        if cmd in ("L", "l"):
            while index + 1 < len(tokens) and not is_cmd(tokens[index]):
                x = float(tokens[index])
                y = float(tokens[index + 1])
                index += 2
                if cmd == "l":
                    x += cx
                    y += cy
                cx, cy = x, y
                coords.append((cx, cy))
            continue

        if cmd in ("H", "h"):
            while index < len(tokens) and not is_cmd(tokens[index]):
                x = float(tokens[index])
                index += 1
                if cmd == "h":
                    x += cx
                cx = x
                coords.append((cx, cy))
            continue

        if cmd in ("V", "v"):
            while index < len(tokens) and not is_cmd(tokens[index]):
                y = float(tokens[index])
                index += 1
                if cmd == "v":
                    y += cy
                cy = y
                coords.append((cx, cy))
            continue

        if cmd in ("C", "c"):
            while index + 5 < len(tokens) and not is_cmd(tokens[index]):
                x1 = float(tokens[index])
                y1 = float(tokens[index + 1])
                x2 = float(tokens[index + 2])
                y2 = float(tokens[index + 3])
                x = float(tokens[index + 4])
                y = float(tokens[index + 5])
                index += 6
                if cmd == "c":
                    x1 += cx
                    y1 += cy
                    x2 += cx
                    y2 += cy
                    x += cx
                    y += cy
                coords.append((x1, y1))
                coords.append((x2, y2))
                coords.append((x, y))
                cx, cy = x, y
            continue

        if cmd in ("S", "s"):
            while index + 3 < len(tokens) and not is_cmd(tokens[index]):
                x2 = float(tokens[index])
                y2 = float(tokens[index + 1])
                x = float(tokens[index + 2])
                y = float(tokens[index + 3])
                index += 4
                if cmd == "s":
                    x2 += cx
                    y2 += cy
                    x += cx
                    y += cy
                coords.append((x2, y2))
                coords.append((x, y))
                cx, cy = x, y
            continue

        if cmd in ("Q", "q"):
            while index + 3 < len(tokens) and not is_cmd(tokens[index]):
                x1 = float(tokens[index])
                y1 = float(tokens[index + 1])
                x = float(tokens[index + 2])
                y = float(tokens[index + 3])
                index += 4
                if cmd == "q":
                    x1 += cx
                    y1 += cy
                    x += cx
                    y += cy
                coords.append((x1, y1))
                coords.append((x, y))
                cx, cy = x, y
            continue

        if cmd in ("T", "t"):
            while index + 1 < len(tokens) and not is_cmd(tokens[index]):
                x = float(tokens[index])
                y = float(tokens[index + 1])
                index += 2
                if cmd == "t":
                    x += cx
                    y += cy
                cx, cy = x, y
                coords.append((x, y))
            continue

        if cmd in ("A", "a"):
            while index + 6 < len(tokens) and not is_cmd(tokens[index]):
                rx = abs(float(tokens[index]))
                ry = abs(float(tokens[index + 1]))
                _xrot = float(tokens[index + 2])
                _laf = float(tokens[index + 3])
                _sf = float(tokens[index + 4])
                x = float(tokens[index + 5])
                y = float(tokens[index + 6])
                index += 7
                start_x = cx
                start_y = cy
                if cmd == "a":
                    x += cx
                    y += cy
                coords.append((x, y))
                if include_arc_envelopes and (rx > 0.0 or ry > 0.0):
                    coords.extend(
                        _svg_arc_bbox_points(
                            start_x,
                            start_y,
                            rx,
                            ry,
                            _xrot,
                            int(_laf),
                            int(_sf),
                            x,
                            y,
                        )
                    )
                cx, cy = x, y
            continue

        if cmd in ("Z", "z"):
            if sx is not None and sy is not None:
                cx, cy = sx, sy
                coords.append((cx, cy))
            continue

        # Unknown command token, consume one token to avoid infinite loops.
        index += 1

    return coords


def svg_detail_score(svg_group):
    paths = re.findall(r'd="([^"]+)"', svg_group)
    segments = []
    coords_all = []
    for path in paths:
        coords = _extract_path_coords(path, include_arc_envelopes=False)
        if len(coords) < 2:
            continue
        for index in range(0, len(coords) - 1):
            x1, y1 = coords[index]
            x2, y2 = coords[index + 1]
            segments.append((x1, y1, x2, y2))
            coords_all.append((x1, y1))
            coords_all.append((x2, y2))
    if not segments:
        return 0.0
    xs = [point[0] for point in coords_all]
    ys = [point[1] for point in coords_all]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    width = max(max_x - min_x, 1e-6)
    height = max(max_y - min_y, 1e-6)
    min_dim = max(1e-6, min(width, height))
    edge_band = max(min_dim * 0.08, 1e-6)
    inner_boost = 2.0
    score = 0.0
    for x1, y1, x2, y2 in segments:
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 1e-12:
            continue
        mid_x = (x1 + x2) * 0.5
        mid_y = (y1 + y2) * 0.5
        edge_dist = min(mid_x - min_x, max_x - mid_x, mid_y - min_y, max_y - mid_y)
        if edge_dist <= 0.0:
            weight = 1.0
        else:
            t = min(1.0, edge_dist / edge_band)
            weight = 1.0 + inner_boost * t
        score += length * weight
    return score


def svg_hidden_edge_load(svg_group):
    hidden_score = 0.0
    for path_tag in re.findall(r"<path\b[^>]*>", svg_group or "", flags=re.IGNORECASE):
        lowered = path_tag.lower()
        if (
            "stroke-dasharray" not in lowered
            and "hidden" not in lowered
            and "verdeckt" not in lowered
        ):
            continue
        match = re.search(r'd="([^"]+)"', path_tag)
        if not match:
            continue
        coords = _extract_path_coords(match.group(1), include_arc_envelopes=False)
        if len(coords) < 2:
            continue
        for index in range(0, len(coords) - 1):
            x1, y1 = coords[index]
            x2, y2 = coords[index + 1]
            hidden_score += math.hypot(x2 - x1, y2 - y1)
    return hidden_score


def evaluate_front_candidate(shape, direction, policy_hints=None):
    try:
        svg = TechDraw.projectToSVG(shape, direction)
    except (RuntimeError, TypeError, ValueError):
        svg = "<g></g>"

    detail_score = svg_detail_score(svg)
    hidden_edge_load = svg_hidden_edge_load(svg)
    hidden_ratio = (hidden_edge_load / detail_score) if detail_score > 1e-6 else (1.0 if hidden_edge_load > 0.0 else 0.0)
    penalty = 0.0
    effective_score = detail_score

    if isinstance(policy_hints, dict) and policy_hints.get("prefer_low_hidden_edge_load"):
        penalty = hidden_edge_load * 0.35
        if detail_score > 0.0:
            penalty = min(penalty, detail_score * 0.45)
        effective_score = detail_score - penalty

    section_recommended = bool(
        isinstance(policy_hints, dict)
        and policy_hints.get("prefer_section_over_hidden_edge_clutter")
        and hidden_edge_load > 0.0
        and hidden_ratio >= 0.14
    )
    if section_recommended:
        section_penalty = hidden_edge_load * 0.20
        if detail_score > 0.0:
            section_penalty = min(section_penalty, detail_score * 0.25)
        penalty += section_penalty
        effective_score = detail_score - penalty

    return {
        "detail_score": detail_score,
        "hidden_edge_load": hidden_edge_load,
        "hidden_ratio": hidden_ratio,
        "penalty": penalty,
        "effective_score": effective_score,
        "section_recommended": section_recommended,
    }


def bounds_size(bounds):
    min_x, max_x, min_y, max_y = bounds
    width = max(max_x - min_x, 0.1)
    height = max(max_y - min_y, 0.1)
    return width, height


def expand_bounds(bounds, pad):
    min_x, max_x, min_y, max_y = bounds
    return min_x - pad, max_x + pad, min_y - pad, max_y + pad


def expand_bounds_asymmetric(bounds, *, left=0.0, right=0.0, top=0.0, bottom=0.0):
    min_x, max_x, min_y, max_y = bounds
    return (
        min_x - max(0.0, float(left)),
        max_x + max(0.0, float(right)),
        min_y - max(0.0, float(top)),
        max_y + max(0.0, float(bottom)),
    )


def expand_dimension_bounds(bounds, pad, *, show_horizontal=True, show_vertical=True, bleed_ratio=0.12):
    min_x, max_x, min_y, max_y = bounds
    bleed = max(0.0, pad * bleed_ratio)
    return (
        min_x - bleed,
        max_x + (pad if show_vertical else bleed),
        min_y - bleed,
        max_y + (pad if show_horizontal else bleed),
    )


def rotate_bounds_90(bounds):
    min_x, max_x, min_y, max_y = bounds
    return (-max_y, -min_y, min_x, max_x)


def append_to_group(svg_group, extra):
    if not extra:
        return svg_group
    parts = svg_group.rsplit("</g>", 1)
    if len(parts) == 2:
        return f"{parts[0]}{extra}</g>{parts[1]}"
    return svg_group + extra


def _outline_start_x(svg_group, bounds, y_target, find_max=True):
    """Find the rightmost (find_max=True) or leftmost x of the part outline at y=y_target.

    Only considers SVG <circle> elements whose extent TOUCHES the bounding box boundary
    (i.e. outer silhouette circles, not inner holes). This avoids false positives from
    inner features (pockets, slots) that share path coordinates with the outer boundary region.

    Example: circular disk Ø90 — at y=max_y (top tangent), returns cx, not cx+r.
    Rectangular part — no boundary-touching circle found, falls back to bounding-box corner.
    """
    min_x, max_x, min_y, max_y = bounds
    # Tolerance for "circle touches bounding-box edge" check (0.5% of dimension, min 0.5mm)
    tol = max(0.5, (max_y - min_y) * 0.005)
    candidate_x = []

    for circle_str in re.finditer(r'<circle[^>]+>', svg_group):
        cs = circle_str.group()
        cx_m = re.search(r'cx\s*=\s*"([^"]+)"', cs)
        cy_m = re.search(r'cy\s*=\s*"([^"]+)"', cs)
        r_m = re.search(r'\br\s*=\s*"([^"]+)"', cs)
        if not (cx_m and cy_m and r_m):
            continue
        cx = float(cx_m.group(1))
        cy = float(cy_m.group(1))
        r = float(r_m.group(1))
        # Only use circles whose top or bottom extent touches the bounding-box y-boundary
        touches_top = abs(cy - r - min_y) <= tol
        touches_bottom = abs(cy + r - max_y) <= tol
        if not (touches_top or touches_bottom):
            continue
        dy = abs(y_target - cy)
        if dy <= r:
            dx = math.sqrt(max(0.0, r * r - dy * dy))
            candidate_x.append(cx + dx)
            candidate_x.append(cx - dx)

    if not candidate_x:
        return max_x if find_max else min_x
    return max(candidate_x) if find_max else min(candidate_x)


def _outline_start_y(svg_group, bounds, x_target, find_max=True):
    """Find the bottommost (find_max=True in Y-down) or topmost y of the part outline at x=x_target.

    Only considers SVG <circle> elements whose extent TOUCHES the bounding box boundary.
    Paths are intentionally excluded: they include inner features (pockets, slots, holes)
    that share x-coordinates with the outer boundary, causing false positives.

    Example: circular disk — at x=min_x (left tangent), returns cy, not cy+r.
    Rectangular/complex part — falls back to bounding-box corner (max_y or min_y).
    """
    min_x, max_x, min_y, max_y = bounds
    tol = max(0.5, (max_x - min_x) * 0.005)
    candidate_y = []

    for circle_str in re.finditer(r'<circle[^>]+>', svg_group):
        cs = circle_str.group()
        cx_m = re.search(r'cx\s*=\s*"([^"]+)"', cs)
        cy_m = re.search(r'cy\s*=\s*"([^"]+)"', cs)
        r_m = re.search(r'\br\s*=\s*"([^"]+)"', cs)
        if not (cx_m and cy_m and r_m):
            continue
        cx = float(cx_m.group(1))
        cy = float(cy_m.group(1))
        r = float(r_m.group(1))
        # Only use circles whose left or right extent touches the bounding-box x-boundary
        touches_left = abs(cx - r - min_x) <= tol
        touches_right = abs(cx + r - max_x) <= tol
        if not (touches_left or touches_right):
            continue
        dx = abs(x_target - cx)
        if dx <= r:
            dy = math.sqrt(max(0.0, r * r - dx * dx))
            candidate_y.append(cy + dy)
            candidate_y.append(cy - dy)

    if not candidate_y:
        return max_y if find_max else min_y
    return max(candidate_y) if find_max else min(candidate_y)


def dimension_metrics(bounds, scale):
    width, height = bounds_size(bounds)
    max_dim_paper = max(width, height) * scale
    offset_mm = max(1.6, min(max_dim_paper * 0.1, 10.0))
    if max_dim_paper < 18.0:
        offset_mm = max(offset_mm, 2.4)
    if max_dim_paper < 12.0:
        offset_mm = max(offset_mm, 3.0)
    gap_mm = 0.0  # Extension lines start at part edge (DIN ISO 129-1, $DIMEXO=0)
    ext_over_mm = max(0.6, min(2.0, offset_mm * 0.25))
    arrow_len_mm = max(0.6, min(2.2, offset_mm * 0.22))
    arrow_half_mm = max(0.3, arrow_len_mm * 0.35)
    layout_text_size_mm = 4.2
    text_size_mm = max(
        layout_text_size_mm,
        min(4.9, layout_text_size_mm + max(0.0, max_dim_paper - 70.0) * 0.006),
    )
    text_gap_mm = 1.6
    pad_mm = offset_mm + ext_over_mm + text_gap_mm + layout_text_size_mm

    return {
        "offset": offset_mm / scale,
        "gap": gap_mm / scale,
        "ext_over": ext_over_mm / scale,
        "arrow_len": arrow_len_mm / scale,
        "arrow_half": arrow_half_mm / scale,
        "text_size": text_size_mm / scale,
        "text_gap": text_gap_mm / scale,
        "pad": pad_mm / scale,
    }


def freecad_svg_basis(direction):
    """
    Returns (svg_x_axis, svg_y_axis) as 3D vectors for FreeCAD's SVG mapping.
    For each projection direction, FreeCAD maps 3D axes to SVG X/Y as follows:
    - Z+ : SVG_X = +X, SVG_Y = +Y
    - Z- : SVG_X = -X, SVG_Y = +Y
    - Y- : SVG_X = -Z, SVG_Y = +X
    - Y+ : SVG_X = +Z, SVG_Y = +X
    - X- : SVG_X = -Z, SVG_Y = -Y
    - X+ : SVG_X = +Z, SVG_Y = -Y
    """
    d = direction
    if hasattr(d, "Length") and d.Length > 0:
        d = App.Vector(d.x / d.Length, d.y / d.Length, d.z / d.Length)
    else:
        d = App.Vector(0, 0, 1)
    if abs(d.z) > 0.9:
        # Z+ or Z-
        svg_x = App.Vector(1, 0, 0) if d.z > 0 else App.Vector(-1, 0, 0)
        svg_y = App.Vector(0, 1, 0)
    elif abs(d.y) > 0.9:
        # Y+ or Y-
        svg_x = App.Vector(0, 0, 1) if d.y > 0 else App.Vector(0, 0, -1)
        svg_y = App.Vector(1, 0, 0)
    elif abs(d.x) > 0.9:
        # X+ or X-
        svg_x = App.Vector(0, 0, 1) if d.x > 0 else App.Vector(0, 0, -1)
        svg_y = App.Vector(0, -1, 0)
    else:
        # Fallback: treat as Z+
        svg_x = App.Vector(1, 0, 0)
        svg_y = App.Vector(0, 1, 0)
    return svg_x, svg_y


def build_dimension_svg(
    bounds,
    scale,
    stroke_width,
    line_profile=None,
    label_width=None,
    label_height=None,
    rotation_deg=0,
    show_horizontal=True,
    show_vertical=True,
    svg_group=None,
    metadata=None,
):
    min_x, max_x, min_y, max_y = bounds
    width, height = bounds_size(bounds)
    label_width = width if label_width is None else label_width
    label_height = height if label_height is None else label_height
    metrics = dimension_metrics(bounds, scale)
    offset = metrics["offset"]
    gap = metrics["gap"]
    ext_over = metrics["ext_over"]
    arrow_len = metrics["arrow_len"]
    arrow_half = metrics["arrow_half"]
    text_size = metrics["text_size"]
    text_gap = metrics["text_gap"]
    line_pad = max(0.25, 0.6 / max(scale, 0.05))
    summary_line_pad = max(0.05, 0.18 / max(scale, 0.05))
    dim_stroke = max(0.0008, stroke_width * 0.6)
    if isinstance(line_profile, dict):
        dim_stroke = max(0.0008, float(line_profile.get("dimension", dim_stroke)))

    horizontal_offset = offset
    vertical_offset = offset
    min_horizontal_offset = minimum_overall_dimension_offset(
        scale,
        text_size,
        axis="H",
        summary_line_pad=summary_line_pad,
    )
    min_vertical_offset = minimum_overall_dimension_offset(
        scale,
        text_size,
        axis="V",
        summary_line_pad=summary_line_pad,
    )
    y_dim = max_y + max(horizontal_offset, min_horizontal_offset)
    x_dim = max_x + max(vertical_offset, min_vertical_offset)

    # --- Clamp overall dimension offsets to stay within drawing area ---
    placement_ctx = (metadata or {}).get("_placement_context") if isinstance(metadata, dict) else None
    if isinstance(placement_ctx, dict):
        try:
            _pc = placement_ctx.get("paper_center") or ()
            _db = placement_ctx.get("drawing_bounds") or ()
            _reserved_paper_boxes = []
            _neighbor_slot_boxes = []
            _neighbor_view_boxes = []
            for _reserved in placement_ctx.get("reserved_paper_boxes") or []:
                normalized_reserved = _normalize_collision_box(_reserved)
                if normalized_reserved is not None:
                    _reserved_paper_boxes.append(normalized_reserved)
            for _neighbor in placement_ctx.get("neighbor_slot_bounds") or []:
                normalized_neighbor = _normalize_collision_box(_neighbor)
                if normalized_neighbor is not None:
                    _neighbor_slot_boxes.append(normalized_neighbor)
            for _neighbor in placement_ctx.get("neighbor_view_bounds") or []:
                normalized_neighbor = _normalize_collision_box(_neighbor)
                if normalized_neighbor is not None:
                    _neighbor_view_boxes.append(normalized_neighbor)
            if len(_pc) == 2 and len(_db) == 4:
                _cx, _cy = float(_pc[0]), float(_pc[1])
                _dl, _dr, _dt, _db_bottom = (float(v) for v in _db)
                _svg_b = bounds  # svg_bounds passed as bounds parameter
                _neighbor_guard_boxes = _neighbor_view_boxes or _neighbor_slot_boxes

                def _local_to_paper_bounds(local_box):
                    return transform_local_bounds_to_paper(
                        tuple(float(v) for v in local_box), _svg_b, _cx, _cy, scale, rotation_deg
                    )

                # Include extension lines + text label in the footprint.
                _text_pad = text_size * 0.8 + ext_over

                def _paper_box_fits(paper_box):
                    if paper_box is None:
                        return True
                    if not (
                        paper_box[2] >= _dt
                        and paper_box[3] <= _db_bottom
                        and paper_box[0] >= _dl
                        and paper_box[1] <= _dr
                    ):
                        return False
                    if any(
                        _bbox_overlaps(paper_box, reserved_box, margin=0.25)
                        for reserved_box in _reserved_paper_boxes
                    ):
                        return False
                    return not any(
                        _bbox_overlaps(paper_box, neighbor_box, margin=0.35)
                        for neighbor_box in _neighbor_guard_boxes
                    )

                # Check horizontal dimension (placed at y_dim, above geometry in local coords)
                if show_horizontal:
                    horizontal_offset = max(y_dim - max_y, min_horizontal_offset)
                    y_dim = max_y + horizontal_offset
                    h_box = (
                        min_x - summary_line_pad,
                        max_x + summary_line_pad,
                        min(min_y, y_dim + ext_over + _text_pad),
                        max(max_y, y_dim + ext_over + _text_pad),
                    )
                    h_paper = _local_to_paper_bounds(h_box)
                    if h_paper is not None:
                        for _ in range(12):
                            if _paper_box_fits(h_paper):
                                break
                            offset_reduction = max(horizontal_offset * 0.2, 0.1 / max(scale, 0.05))
                            next_offset = max(
                                min_horizontal_offset,
                                horizontal_offset - offset_reduction,
                            )
                            if abs(next_offset - horizontal_offset) < 1e-9:
                                break
                            horizontal_offset = next_offset
                            y_dim = max_y + horizontal_offset
                            h_box = (
                                min_x - summary_line_pad,
                                max_x + summary_line_pad,
                                min(min_y, y_dim + ext_over + _text_pad),
                                max(max_y, y_dim + ext_over + _text_pad),
                            )
                            h_paper = _local_to_paper_bounds(h_box)
                            if h_paper is None:
                                break

                # Check vertical dimension (placed at x_dim, right of geometry in local coords)
                if show_vertical:
                    vertical_offset = max(x_dim - max_x, min_vertical_offset)
                    x_dim = max_x + vertical_offset
                    v_box = (
                        min(min_x, x_dim + ext_over + _text_pad),
                        max(max_x, x_dim + ext_over + _text_pad),
                        min_y - summary_line_pad,
                        max_y + summary_line_pad,
                    )
                    v_paper = _local_to_paper_bounds(v_box)
                    if v_paper is not None:
                        for _ in range(12):
                            if _paper_box_fits(v_paper):
                                break
                            offset_reduction = max(vertical_offset * 0.2, 0.1 / max(scale, 0.05))
                            next_offset = max(
                                min_vertical_offset,
                                vertical_offset - offset_reduction,
                            )
                            if abs(next_offset - vertical_offset) < 1e-9:
                                break
                            vertical_offset = next_offset
                            x_dim = max_x + vertical_offset
                            v_box = (
                                min(min_x, x_dim + ext_over + _text_pad),
                                max(max_x, x_dim + ext_over + _text_pad),
                                min_y - summary_line_pad,
                                max_y + summary_line_pad,
                            )
                            v_paper = _local_to_paper_bounds(v_box)
                            if v_paper is None:
                                break
        except (TypeError, ValueError, ZeroDivisionError):
            pass  # Graceful fallback: use original positions
    # --- End of bounds clamping ---

    mid_x = (min_x + max_x) / 2
    mid_y = (min_y + max_y) / 2
    width_x = mid_x
    width_y = -y_dim
    height_x = x_dim
    height_y = -mid_y

    # DIN/ISO style: unit is defined in title block; dimension numbers stay unitless.
    label_w = format_de_number(label_width)
    label_h = format_de_number(label_height)

    # Compute outline-anchored extension line start points.
    # For a circle: the extension line for the HEIGHT dim at y=max_y starts at x=cx (top tangent),
    # not at x=max_x (bounding box right). Same principle for all curved profiles.
    # Falls back to bounding box corner when no svg_group is provided.
    if svg_group is not None:
        y_ext_left = _outline_start_y(svg_group, bounds, min_x, find_max=True)
        y_ext_right = _outline_start_y(svg_group, bounds, max_x, find_max=True)
        x_ext_top = _outline_start_x(svg_group, bounds, max_y, find_max=True)
        x_ext_bottom = _outline_start_x(svg_group, bounds, min_y, find_max=True)
    else:
        y_ext_left = y_ext_right = max_y
        x_ext_top = x_ext_bottom = max_x

    line_parts = []
    arrow_parts = []
    show_horizontal = bool(show_horizontal)
    show_vertical = bool(show_vertical)
    if show_horizontal:
        horiz_line_box = _line_collision_box(min_x, y_dim, max_x, y_dim, summary_line_pad)
        horiz_text_box = quality_text_collision_box(label_w, width_x, y_dim, text_size, "middle")
        line_parts.extend(
            [
                f'<line x1="{min_x:.3f}" y1="{y_dim:.3f}" x2="{max_x:.3f}" y2="{y_dim:.3f}" />',
                f'<line x1="{min_x:.3f}" y1="{y_ext_left:.3f}" x2="{min_x:.3f}" y2="{y_dim + ext_over:.3f}" />',
                f'<line x1="{max_x:.3f}" y1="{y_ext_right:.3f}" x2="{max_x:.3f}" y2="{y_dim + ext_over:.3f}" />',
            ]
        )
        arrow_parts.extend(
            [
                f'<polygon points="{min_x:.3f},{y_dim:.3f} {min_x + arrow_len:.3f},{y_dim - arrow_half:.3f} {min_x + arrow_len:.3f},{y_dim + arrow_half:.3f}" />',
                f'<polygon points="{max_x:.3f},{y_dim:.3f} {max_x - arrow_len:.3f},{y_dim - arrow_half:.3f} {max_x - arrow_len:.3f},{y_dim + arrow_half:.3f}" />',
            ]
        )
        _record_dimension_entry(
            metadata,
            "overall_dimensions",
            dim_type="overall_width",
            axis="H",
            style="line",
            outside=True,
            measurement_box=horiz_line_box,
            text_box=horiz_text_box,
        )
    if show_vertical:
        vert_line_box = _line_collision_box(x_dim, min_y, x_dim, max_y, summary_line_pad)
        vert_text_box = quality_rotated_text_collision_box(label_h, height_x, mid_y, text_size)
        line_parts.extend(
            [
                f'<line x1="{x_ext_bottom:.3f}" y1="{min_y:.3f}" x2="{x_dim + ext_over:.3f}" y2="{min_y:.3f}" />',
                f'<line x1="{x_ext_top:.3f}" y1="{max_y:.3f}" x2="{x_dim + ext_over:.3f}" y2="{max_y:.3f}" />',
                f'<line x1="{x_dim:.3f}" y1="{min_y:.3f}" x2="{x_dim:.3f}" y2="{max_y:.3f}" />',
            ]
        )
        arrow_parts.extend(
            [
                f'<polygon points="{x_dim:.3f},{min_y:.3f} {x_dim - arrow_half:.3f},{min_y + arrow_len:.3f} {x_dim + arrow_half:.3f},{min_y + arrow_len:.3f}" />',
                f'<polygon points="{x_dim:.3f},{max_y:.3f} {x_dim - arrow_half:.3f},{max_y - arrow_len:.3f} {x_dim + arrow_half:.3f},{max_y - arrow_len:.3f}" />',
            ]
        )
        _record_dimension_entry(
            metadata,
            "overall_dimensions",
            dim_type="overall_height",
            axis="V",
            style="line",
            outside=True,
            measurement_box=vert_line_box,
            text_box=vert_text_box,
        )

    lines = (
        f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
        f'stroke-linecap="butt" stroke-linejoin="miter" font-size="{text_size:.2f}" '
        f'font-family="Arial">'
        + "".join(line_parts)
        + "</g>"
    )
    char_w = text_size * 0.6
    width_text_w = max(len(label_w), 1) * char_w
    height_text_w = max(len(label_h), 1) * char_w
    rect_pad = text_size * 0.25  # Unified padding for consistent text mask (ISO 129-1)
    width_rect_x = width_x - width_text_w * 0.5 - rect_pad
    width_rect_y = width_y - text_size * 0.8
    width_rect_w = width_text_w + rect_pad * 2
    width_rect_h = text_size * 1.5
    height_rect_x = height_x - height_text_w * 0.5 - rect_pad
    height_rect_y = height_y - text_size * 0.8
    height_rect_w = height_text_w + rect_pad * 2
    height_rect_h = text_size * 1.5
    height_rotate = f' transform="rotate(-90 {height_x:.3f} {height_y:.3f})"'
    text_parts = [
        f'<g fill="rgb(0, 0, 0)" stroke="none" font-size="{text_size:.3f}" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
    ]
    if show_horizontal:
        text_parts.extend(
            [
                f'<rect x="{width_rect_x:.3f}" y="{width_rect_y:.3f}" '
                f'width="{width_rect_w:.3f}" height="{width_rect_h:.3f}" fill="white" />',
                f'<text x="{width_x:.3f}" y="{width_y:.3f}" text-anchor="middle">{escape(label_w)}</text>',
            ]
        )
    if show_vertical:
        text_parts.extend(
            [
                f'<g{height_rotate}>',
                f'<rect x="{height_rect_x:.3f}" y="{height_rect_y:.3f}" '
                f'width="{height_rect_w:.3f}" height="{height_rect_h:.3f}" fill="white" />',
                f'<text x="{height_x:.3f}" y="{height_y:.3f}" text-anchor="middle">{escape(label_h)}</text>',
                "</g>",
            ]
        )
    text_parts.append("</g>")
    text_group = "".join(text_parts)
    arrows = f'<g fill="rgb(0, 0, 0)" stroke="none">' + "".join(arrow_parts) + "</g>"
    return lines + arrows + text_group if (show_horizontal or show_vertical) else ""


def build_diagonal_dimension_svg(
    p1,
    p2,
    label_text,
    scale,
    stroke_width,
    offset_mm=5.0,
    line_profile=None,
    metadata=None,
):
    """Build an ISO 129-1 compliant diagonal/angular dimension line between two points.

    Parameters:
        p1: (x1, y1) start point in drawing coordinates
        p2: (x2, y2) end point in drawing coordinates
        label_text: dimension label (e.g. "45,5" or "2\u00d745\u00b0")
        scale: drawing scale factor
        offset_mm: offset distance from the measured edge (in drawing units)
        line_profile: optional line width overrides
        metadata: dimension tracking dict
    Returns:
        SVG string for the diagonal dimension
    """
    x1, y1 = p1
    x2, y2 = p2
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return ""

    # Unit direction along the dimension
    ux, uy = dx / length, dy / length
    # Normal direction (perpendicular, pointing outward)
    nx, ny = -uy, ux

    # Offset the dimension line away from the edge
    offset = offset_mm / max(scale, 0.05)
    ox1 = x1 + nx * offset
    oy1 = y1 + ny * offset
    ox2 = x2 + nx * offset
    oy2 = y2 + ny * offset

    metrics = dimension_metrics((min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)), scale)
    dim_stroke = max(0.0008, stroke_width * 0.6)
    if isinstance(line_profile, dict):
        dim_stroke = max(0.0008, float(line_profile.get("dimension", dim_stroke)))
    ext_over = metrics["ext_over"]
    arrow_len = metrics["arrow_len"]
    arrow_half = metrics["arrow_half"]
    text_size = metrics["text_size"]

    parts = []

    # Extension lines (from original points to offset dimension line + overshoot)
    ext_end_x1 = ox1 + nx * ext_over
    ext_end_y1 = oy1 + ny * ext_over
    ext_end_x2 = ox2 + nx * ext_over
    ext_end_y2 = oy2 + ny * ext_over
    parts.append(
        f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{ext_end_x1:.3f}" y2="{ext_end_y1:.3f}" '
        f'stroke="#000" stroke-width="{dim_stroke:.4f}"/>'
    )
    parts.append(
        f'<line x1="{x2:.3f}" y1="{y2:.3f}" x2="{ext_end_x2:.3f}" y2="{ext_end_y2:.3f}" '
        f'stroke="#000" stroke-width="{dim_stroke:.4f}"/>'
    )

    # Dimension line
    parts.append(
        f'<line x1="{ox1:.3f}" y1="{oy1:.3f}" x2="{ox2:.3f}" y2="{oy2:.3f}" '
        f'stroke="#000" stroke-width="{dim_stroke:.4f}"/>'
    )

    # Arrowheads (triangles at both ends, aligned with dimension direction)
    # Arrow at p1 end (pointing towards p1)
    a1_tip_x, a1_tip_y = ox1, oy1
    a1_base_x = ox1 + ux * arrow_len
    a1_base_y = oy1 + uy * arrow_len
    a1_left_x = a1_base_x + nx * arrow_half
    a1_left_y = a1_base_y + ny * arrow_half
    a1_right_x = a1_base_x - nx * arrow_half
    a1_right_y = a1_base_y - ny * arrow_half
    parts.append(
        f'<polygon points="{a1_tip_x:.3f},{a1_tip_y:.3f} '
        f'{a1_left_x:.3f},{a1_left_y:.3f} {a1_right_x:.3f},{a1_right_y:.3f}" '
        f'fill="#000" stroke="none"/>'
    )

    # Arrow at p2 end (pointing towards p2)
    a2_tip_x, a2_tip_y = ox2, oy2
    a2_base_x = ox2 - ux * arrow_len
    a2_base_y = oy2 - uy * arrow_len
    a2_left_x = a2_base_x + nx * arrow_half
    a2_left_y = a2_base_y + ny * arrow_half
    a2_right_x = a2_base_x - nx * arrow_half
    a2_right_y = a2_base_y - ny * arrow_half
    parts.append(
        f'<polygon points="{a2_tip_x:.3f},{a2_tip_y:.3f} '
        f'{a2_left_x:.3f},{a2_left_y:.3f} {a2_right_x:.3f},{a2_right_y:.3f}" '
        f'fill="#000" stroke="none"/>'
    )

    # Text label at midpoint, rotated parallel to dimension line
    mid_x = (ox1 + ox2) / 2
    mid_y = (oy1 + oy2) / 2
    # Angle of the dimension line (for text rotation)
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)
    # ISO 129-1: text should be readable from bottom or right
    # If angle is between 90-270°, flip 180° so text reads left-to-right
    if angle_deg > 90 or angle_deg < -90:
        angle_deg += 180

    # Text offset above the dimension line
    text_offset = text_size * 0.8
    text_x = mid_x + nx * text_offset
    text_y = mid_y + ny * text_offset

    # White background rect for text (approximate)
    char_w = text_size * 0.6
    text_w = max(len(label_text), 1) * char_w
    rect_pad = text_size * 0.2

    parts.append(
        f'<g transform="scale(1,-1)">'
        f'<g transform="rotate({-angle_deg:.2f} {text_x:.3f} {-text_y:.3f})">'
        f'<rect x="{text_x - text_w / 2 - rect_pad:.3f}" y="{-text_y - text_size * 0.7:.3f}" '
        f'width="{text_w + rect_pad * 2:.3f}" height="{text_size * 1.4:.3f}" fill="white"/>'
        f'<text x="{text_x:.3f}" y="{-text_y:.3f}" text-anchor="middle" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-size="{text_size:.3f}" font-style="normal" font-weight="normal" '
        f'fill="#000">{escape(label_text)}</text>'
        f'</g></g>'
    )

    if metadata is not None:
        _record_dimension_entry(
            metadata,
            "diagonal_dimensions",
            dim_type="diagonal",
            axis="D",
            style="line",
            outside=True,
            measurement_box=(min(ox1, ox2), min(oy1, oy2), max(ox1, ox2), max(oy1, oy2)),
            text_box=None,
        )

    return "\n".join(parts)


def build_angle_dimension_svg(
    vertex,
    p1,
    p2,
    angle_deg,
    label_text,
    scale,
    stroke_width,
    radius_mm=8.0,
    line_profile=None,
    metadata=None,
):
    """Build an ISO 129-1 angular dimension arc between two edges meeting at a vertex.

    Parameters:
        vertex: (vx, vy) the intersection point of the two edges
        p1: (x1, y1) point on the first edge
        p2: (x2, y2) point on the second edge
        angle_deg: the angle value in degrees
        label_text: formatted label (e.g. "45\u00b0")
        scale: drawing scale
        radius_mm: arc radius in drawing units
        line_profile: optional line width overrides
        metadata: dimension tracking dict
    Returns:
        SVG string for the angular dimension
    """
    vx, vy = vertex
    x1, y1 = p1
    x2, y2 = p2

    dim_stroke = max(0.0008, stroke_width * 0.6)
    if isinstance(line_profile, dict):
        dim_stroke = max(0.0008, float(line_profile.get("dimension", dim_stroke)))
    metrics = dimension_metrics((vx - 10, vx + 10, vy - 10, vy + 10), scale)
    text_size = metrics["text_size"]
    arrow_len = metrics["arrow_len"]
    arrow_half = metrics["arrow_half"]

    # Compute angles from vertex to each edge point
    r = radius_mm / max(scale, 0.05)
    a1 = math.atan2(y1 - vy, x1 - vx)
    a2 = math.atan2(y2 - vy, x2 - vx)

    # Ensure we sweep the smaller angle
    sweep = a2 - a1
    if sweep > math.pi:
        sweep -= 2 * math.pi
    elif sweep < -math.pi:
        sweep += 2 * math.pi

    # Arc endpoints
    arc_x1 = vx + r * math.cos(a1)
    arc_y1 = vy + r * math.sin(a1)
    arc_x2 = vx + r * math.cos(a2)
    arc_y2 = vy + r * math.sin(a2)

    # SVG arc: large-arc-flag = 0 (always < 180°), sweep-flag depends on direction
    large_arc = 0
    sweep_flag = 1 if sweep > 0 else 0

    parts = []

    # Arc dimension line
    parts.append(
        f'<path d="M {arc_x1:.3f},{arc_y1:.3f} A {r:.3f},{r:.3f} 0 {large_arc},{sweep_flag} '
        f'{arc_x2:.3f},{arc_y2:.3f}" fill="none" stroke="#000" stroke-width="{dim_stroke:.4f}"/>'
    )

    # Extension lines from vertex edges to arc
    ext_len = r * 1.15  # slightly beyond the arc
    parts.append(
        f'<line x1="{vx:.3f}" y1="{vy:.3f}" '
        f'x2="{vx + ext_len * math.cos(a1):.3f}" y2="{vy + ext_len * math.sin(a1):.3f}" '
        f'stroke="#000" stroke-width="{dim_stroke:.4f}"/>'
    )
    parts.append(
        f'<line x1="{vx:.3f}" y1="{vy:.3f}" '
        f'x2="{vx + ext_len * math.cos(a2):.3f}" y2="{vy + ext_len * math.sin(a2):.3f}" '
        f'stroke="#000" stroke-width="{dim_stroke:.4f}"/>'
    )

    # Arrowheads at arc endpoints (tangent direction)
    for ax, ay, angle, direction in [
        (arc_x1, arc_y1, a1, 1),
        (arc_x2, arc_y2, a2, -1),
    ]:
        # Tangent at arc point (perpendicular to radius, in sweep direction)
        tang = angle + direction * math.pi / 2
        if sweep < 0:
            tang = angle - direction * math.pi / 2
        tx, ty = math.cos(tang), math.sin(tang)
        nx, ny = -ty, tx
        parts.append(
            f'<polygon points='
            f'"{ax:.3f},{ay:.3f} '
            f'{ax + tx * arrow_len:.3f},{ay + ty * arrow_len:.3f} '
            f'{ax + tx * arrow_len * 0.7 + nx * arrow_half:.3f},{ay + ty * arrow_len * 0.7 + ny * arrow_half:.3f}" '
            f'fill="#000" stroke="none"/>'
        )

    # Text at arc midpoint
    mid_angle = a1 + sweep / 2
    text_r = r + text_size * 0.8
    text_x = vx + text_r * math.cos(mid_angle)
    text_y = vy + text_r * math.sin(mid_angle)

    # Readable orientation
    text_angle = math.degrees(mid_angle)
    if text_angle > 90 or text_angle < -90:
        text_angle += 180

    parts.append(
        f'<g transform="scale(1,-1)">'
        f'<text x="{text_x:.3f}" y="{-text_y:.3f}" text-anchor="middle" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-size="{text_size:.3f}" font-style="normal" font-weight="normal" '
        f'fill="#000">{escape(label_text)}</text>'
        f'</g>'
    )

    if metadata is not None:
        _record_dimension_entry(
            metadata,
            "angle_dimensions",
            dim_type="angle",
            axis="D",
            style="arc",
            outside=True,
            measurement_box=(
                min(arc_x1, arc_x2, vx), min(arc_y1, arc_y2, vy),
                max(arc_x1, arc_x2, vx), max(arc_y1, arc_y2, vy),
            ),
            text_box=None,
        )

    return "\n".join(parts)


def build_chamfer_dimension_svg(
    corner,
    edge_dir,
    chamfer_size,
    chamfer_angle_deg,
    scale,
    stroke_width,
    line_profile=None,
    metadata=None,
    label_text=None,
):
    """Build an ISO 129-1 chamfer dimension notation (e.g. "2\u00d745\u00b0").

    Parameters:
        corner: (cx, cy) the chamfer corner point
        edge_dir: "H" or "V" indicating which edge the chamfer is on
        chamfer_size: chamfer leg length in mm
        chamfer_angle_deg: chamfer angle (typically 45°)
        scale: drawing scale
        stroke_width: base stroke width
    Returns:
        SVG string for the chamfer callout
    """
    cx, cy = corner
    label = label_text or f"{format_de_number(chamfer_size)}\u00d7{chamfer_angle_deg:.0f}\u00b0"

    metrics = dimension_metrics((cx - 5, cx + 5, cy - 5, cy + 5), scale)
    text_size = metrics["text_size"]
    dim_stroke = max(0.0008, stroke_width * 0.6)

    # Leader line from chamfer corner to label
    offset = 6.0 / max(scale, 0.05)
    # Place label diagonally away from the corner
    if edge_dir == "H":
        lx, ly = cx + offset, cy + offset
    else:
        lx, ly = cx + offset, cy - offset

    parts = [
        f'<line x1="{cx:.3f}" y1="{cy:.3f}" x2="{lx:.3f}" y2="{ly:.3f}" '
        f'stroke="#000" stroke-width="{dim_stroke:.4f}"/>',
        f'<g transform="scale(1,-1)">'
        f'<text x="{lx:.3f}" y="{-ly:.3f}" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-size="{text_size:.3f}" font-style="normal" font-weight="normal" '
        f'fill="#000">{escape(label)}</text>'
        f'</g>',
    ]

    if metadata is not None:
        _record_dimension_entry(
            metadata,
            "chamfer_dimensions",
            dim_type="chamfer",
            axis="D",
            style="leader",
            outside=True,
            measurement_box=None,
            text_box=None,
        )

    return "\n".join(parts)


def build_round_overall_dimension_svg(svg_group, bounds, scale, stroke_width, line_profile=None, metadata=None):
    width, height = bounds_size(bounds)
    diameter = max(width, height)
    round_ratio = abs(width - height) / max(diameter, 1e-6)
    if round_ratio > 0.12 or diameter <= 1.0:
        return ""

    min_x, max_x, min_y, max_y = bounds
    metrics = dimension_metrics(bounds, scale)
    offset = metrics["offset"]
    ext_over = metrics["ext_over"]
    arrow_len = metrics["arrow_len"]
    arrow_half = metrics["arrow_half"]
    text_size = metrics["text_size"]
    line_pad = max(0.25, 0.6 / max(scale, 0.05))
    summary_line_pad = max(0.05, 0.18 / max(scale, 0.05))
    dim_stroke = max(0.0008, stroke_width * 0.6)
    if isinstance(line_profile, dict):
        dim_stroke = max(0.0008, float(line_profile.get("dimension", dim_stroke)))

    y_dim = max_y + offset
    mid_x = (min_x + max_x) / 2
    label = f"Ø{format_de_number(diameter)}"
    y_ext_left = _outline_start_y(svg_group, bounds, min_x, find_max=True)
    y_ext_right = _outline_start_y(svg_group, bounds, max_x, find_max=True)
    measurement_box = _line_collision_box(min_x, y_dim, max_x, y_dim, summary_line_pad)
    text_box = quality_text_collision_box(label, mid_x, y_dim, text_size, "middle")

    lines = (
        f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
        f'stroke-linecap="butt" stroke-linejoin="miter">'
        f'<line x1="{min_x:.3f}" y1="{y_dim:.3f}" x2="{max_x:.3f}" y2="{y_dim:.3f}" />'
        f'<line x1="{min_x:.3f}" y1="{y_ext_left:.3f}" x2="{min_x:.3f}" y2="{y_dim + ext_over:.3f}" />'
        f'<line x1="{max_x:.3f}" y1="{y_ext_right:.3f}" x2="{max_x:.3f}" y2="{y_dim + ext_over:.3f}" />'
        "</g>"
    )
    arrows = (
        f'<g fill="rgb(0, 0, 0)" stroke="none">'
        f'<polygon points="{min_x:.3f},{y_dim:.3f} {min_x + arrow_len:.3f},{y_dim - arrow_half:.3f} {min_x + arrow_len:.3f},{y_dim + arrow_half:.3f}" />'
        f'<polygon points="{max_x:.3f},{y_dim:.3f} {max_x - arrow_len:.3f},{y_dim - arrow_half:.3f} {max_x - arrow_len:.3f},{y_dim + arrow_half:.3f}" />'
        "</g>"
    )
    _record_dimension_entry(
        metadata,
        "overall_dimensions",
        dim_type="overall_diameter",
        axis="H",
        style="line",
        outside=True,
        measurement_box=measurement_box,
        text_box=text_box,
    )
    return lines + arrows + _feature_text_svg(label, mid_x, y_dim, text_size, anchor="middle")


def get_dimension_plan_view(dim_plan, view_name):
    if not isinstance(dim_plan, dict):
        return None
    for view in dim_plan.get("views", []):
        if isinstance(view, dict) and str(view.get("view_name")) == view_name:
            return view
    return None


def get_dimension_plan_policy_hints(dim_plan):
    if not isinstance(dim_plan, dict):
        return {}
    policy_hints = dim_plan.get("policy_hints")
    return policy_hints if isinstance(policy_hints, dict) else {}


def get_dimension_plan_section_views(dim_plan):
    if not isinstance(dim_plan, dict):
        return []
    section_views = dim_plan.get("section_views")
    if not isinstance(section_views, list):
        return []
    return [entry for entry in section_views if isinstance(entry, dict)]


def get_dimension_plan_detail_views(dim_plan):
    if not isinstance(dim_plan, dict):
        return []
    detail_views = dim_plan.get("detail_views")
    if not isinstance(detail_views, list):
        return []
    return [entry for entry in detail_views if isinstance(entry, dict)]


def get_dimension_plan_dim_types(view_plan):
    if not isinstance(view_plan, dict):
        return set()
    dim_types = set()
    for dim in view_plan.get("dimensions", []):
        if not isinstance(dim, dict):
            continue
        dim_type = str(dim.get("dim_type") or "").strip()
        if dim_type:
            dim_types.add(dim_type)
    return dim_types


def get_dimension_plan_dim_value(view_plan, dim_type):
    if not isinstance(view_plan, dict):
        return None
    for dim in view_plan.get("dimensions", []):
        if not isinstance(dim, dict):
            continue
        if str(dim.get("dim_type")) != str(dim_type):
            continue
        return _optional_float(dim.get("value_mm"))
    return None


def infer_feature_dimension_types_for_view(view_name, feature_payload=None, dim_plan=None):
    if str(view_name or "") != "Front":
        return set()
    if str((dim_plan or {}).get("part_type") or "").strip().lower() != "sheet_metal":
        return set()
    if not isinstance(feature_payload, dict):
        return set()

    inferred = set()

    # Sheet metal thickness ("s = X,X") — always shown for sheet metal parts
    sheet_t = _optional_float(feature_payload.get("measured_thickness_mm"))
    if sheet_t and 0 < sheet_t <= 10.0:
        inferred.add("sheet_thickness")

    hole_count = int(_optional_float(feature_payload.get("hole_count")) or 0)
    if hole_count > 0:
        inferred.add("hole_diameter")
        hole_extent = _summarize_hole_extent(
            feature_payload,
            diameter_mm=_optional_float(feature_payload.get("hole_diameter_mm")),
        )
        if hole_extent and hole_extent.get("through") is False:
            inferred.add("hole_depth")
        if feature_payload.get("hole_groups") or feature_payload.get("hole_diameter_mm") is not None:
            inferred.update({"hole_location_x", "hole_location_y"})
        hole_pitch = _optional_float(feature_payload.get("hole_pitch_mm"))
        if hole_count >= 2 and hole_pitch and hole_pitch > 0:
            inferred.add("hole_pitch")

    if feature_payload.get("chamfers"):
        inferred.add("chamfer")

    return inferred


def feature_dimension_types_for_view(view_name, dim_plan=None, feature_payload=None):
    supported = {
        "hole_diameter",
        "hole_depth",
        "hole_pitch",
        "hole_location_x",
        "hole_location_y",
        "pocket_depth",
        "pocket_location",
        "thread_callout",
        "groove_callout",
        "bend_radius",
        "sheet_thickness",
        "chamfer",
    }
    view_plan = get_dimension_plan_view(dim_plan, view_name)
    planned = get_dimension_plan_dim_types(view_plan) & supported
    inferred = infer_feature_dimension_types_for_view(
        view_name,
        feature_payload=feature_payload,
        dim_plan=dim_plan,
    ) & supported
    return planned | inferred


def _select_detail_feature_cluster(circles):
    if not circles:
        return []

    cluster_size = 4 if len(circles) >= 8 else min(3, len(circles))
    cluster_size = max(1, cluster_size)
    best_cluster = [circles[0]]
    best_key = None

    for index, seed in enumerate(circles):
        distances = sorted(
            (
                math.hypot(float(seed["cx"]) - float(candidate["cx"]), float(seed["cy"]) - float(candidate["cy"])),
                candidate_index,
            )
            for candidate_index, candidate in enumerate(circles)
            if candidate_index != index
        )
        cluster_indices = [index] + [candidate_index for _distance, candidate_index in distances[: max(0, cluster_size - 1)]]
        cluster = [circles[candidate_index] for candidate_index in cluster_indices]
        center_x = sum(float(circle["cx"]) for circle in cluster) / len(cluster)
        center_y = sum(float(circle["cy"]) for circle in cluster) / len(cluster)
        radius = max(
            math.hypot(float(circle["cx"]) - center_x, float(circle["cy"]) - center_y) + float(circle["r"])
            for circle in cluster
        )
        mean_neighbor_distance = (
            sum(distance for distance, _candidate_index in distances[: max(0, cluster_size - 1)])
            / max(1, cluster_size - 1)
        )
        candidate_key = (radius, mean_neighbor_distance, -len(cluster))
        if best_key is None or candidate_key < best_key:
            best_key = candidate_key
            best_cluster = cluster

    return best_cluster


def _resolve_detail_view_region(parent_item, detail_plan):
    svg_bounds = parent_item.get("svg_bounds")
    if not svg_bounds:
        return None
    min_x, max_x, min_y, max_y = svg_bounds
    width = max(1e-6, max_x - min_x)
    height = max(1e-6, max_y - min_y)

    center_ratio = detail_plan.get("center_ratio") or (0.5, 0.5)
    try:
        ratio_x = float(center_ratio[0])
        ratio_y = float(center_ratio[1])
    except (TypeError, ValueError, IndexError):
        ratio_x = 0.5
        ratio_y = 0.5
    ratio_x = min(max(ratio_x, 0.1), 0.9)
    ratio_y = min(max(ratio_y, 0.1), 0.9)

    center_x = min_x + ratio_x * width
    center_y = min_y + ratio_y * height
    default_radius = _optional_float(detail_plan.get("radius_mm")) or min(width, height) * 0.2

    circular_features = extract_svg_circular_features(str(parent_item.get("svg") or ""))
    cluster = _select_detail_feature_cluster(circular_features)
    if cluster:
        center_x = sum(float(circle["cx"]) for circle in cluster) / len(cluster)
        center_y = sum(float(circle["cy"]) for circle in cluster) / len(cluster)
        cluster_radius = max(
            math.hypot(float(circle["cx"]) - center_x, float(circle["cy"]) - center_y) + float(circle["r"])
            for circle in cluster
        )
        max_feature_radius = max(float(circle["r"]) for circle in cluster)
        default_radius = max(default_radius, cluster_radius + max(2.0, max_feature_radius * 0.8))

    max_radius = min(width, height) * 0.45
    min_radius = max(6.0, min(width, height) * 0.12)
    radius = min(max(default_radius, min_radius), max_radius)
    center_x = min(max(center_x, min_x + radius), max_x - radius)
    center_y = min(max(center_y, min_y + radius), max_y - radius)

    return {
        "center_x": center_x,
        "center_y": center_y,
        "center_ratio_x": (center_x - min_x) / width,
        "center_ratio_y": (center_y - min_y) / height,
        "radius_mm": radius,
    }


def _inject_section_view_into_iso_slot(view_data, shape, points, dim_plan, iso_padding=0.84):
    """Replace the Iso slot content with a section view when the plan requests one."""

    _ = (shape, points)
    section_views = get_dimension_plan_section_views(dim_plan)
    if not section_views:
        return False

    section_plan = section_views[0]
    parent_view_name = str(section_plan.get("parent_view") or "Front")
    parent_item = next(
        (
            item
            for item in view_data
            if item.get("name") == parent_view_name and item.get("enabled", True)
        ),
        None,
    )
    iso_item = next((item for item in view_data if item.get("name") == "Iso"), None)
    if parent_item is None or iso_item is None or not iso_item.get("enabled", True):
        return False

    cut_axis = str(section_plan.get("cut_axis") or "V").strip().upper()
    if cut_axis not in {"H", "V"}:
        cut_axis = "V"
    try:
        ratio = float(section_plan.get("cut_position_ratio", 0.5))
    except (TypeError, ValueError):
        ratio = 0.5
    ratio = min(max(ratio, 0.0), 1.0)

    source_view_name = None
    if parent_view_name == "Front":
        source_view_name = "Left" if cut_axis == "V" else "Top"
    elif parent_view_name == "Top":
        source_view_name = "Left" if cut_axis == "V" else "Front"
    elif parent_view_name == "Left":
        source_view_name = "Top" if cut_axis == "V" else "Front"
    if not source_view_name:
        return False
    source_item = next(
        (
            item
            for item in view_data
            if item.get("name") == source_view_name and item.get("enabled", True)
        ),
        None,
    )
    if source_item is None:
        return False

    source_svg = str(source_item.get("svg") or "")
    section_bounds = source_item.get("svg_bounds")
    if not source_svg or not section_bounds:
        return False
    section_svg = append_to_group(
        source_svg,
        _generate_cross_hatch_bounds_svg(section_bounds, scale=1.0),
    )
    layout_bounds = source_item.get("layout_bounds") or section_bounds
    bounds_for_scale = source_item.get("bounds_for_scale") or layout_bounds
    section_w, section_h = bounds_size(layout_bounds)

    slot = iso_item.get("slot") or {}
    slot_w = _optional_float(slot.get("w")) or 0.0
    slot_h = _optional_float(slot.get("h")) or 0.0
    scale_fit = compute_scale_for_area(
        layout_bounds,
        slot_w,
        slot_h,
        padding=iso_padding,
    )

    section_label = str(section_plan.get("label") or "A").strip() or "A"
    iso_item.update(
        {
            "svg": section_svg,
            "svg_bounds": section_bounds,
            "proj_bounds": source_item.get("proj_bounds") or section_bounds,
            "rotation_deg": int(source_item.get("rotation_deg", 0) or 0),
            "layout_bounds": layout_bounds,
            "bounds_for_scale": bounds_for_scale,
            "scale_fit": scale_fit,
            "geom_w": section_w,
            "geom_h": section_h,
            "fit_w": bounds_size(bounds_for_scale)[0],
            "fit_h": bounds_size(bounds_for_scale)[1],
            "direction": source_item.get("direction"),
            "view_kind": "section",
            "view_title": f"{section_label}-{section_label}",
            "section_label": section_label,
            "section_parent_view": parent_view_name,
            "section_cut_axis": cut_axis,
        }
    )
    parent_item["section_line_plan"] = {
        "label": section_label,
        "cut_axis": cut_axis,
        "cut_position_ratio": ratio,
    }
    log(
        f"Section view injected into Iso slot: {section_label}-{section_label} "
        f"from {parent_view_name} ({cut_axis}, ratio={ratio:.2f})"
    )
    return True


def _inject_detail_view_into_iso_slot(view_data, dim_plan, iso_padding=0.84):
    """Replace the Iso slot content with a detail view when the plan requests one."""

    detail_views = get_dimension_plan_detail_views(dim_plan)
    if not detail_views:
        return False

    detail_plan = detail_views[0]
    parent_view_name = str(detail_plan.get("parent_view") or "Front")
    parent_item = next(
        (
            item
            for item in view_data
            if item.get("name") == parent_view_name and item.get("enabled", True)
        ),
        None,
    )
    iso_item = next((item for item in view_data if item.get("name") == "Iso"), None)
    if parent_item is None or iso_item is None or not iso_item.get("enabled", True):
        return False
    if str(iso_item.get("view_kind") or "").strip().lower() == "section":
        return False

    detail_region = _resolve_detail_view_region(parent_item, detail_plan)
    if not detail_region:
        return False

    zoom_factor = _optional_float(detail_plan.get("zoom_factor")) or 2.0
    detail_label = str(detail_plan.get("label") or "Z").strip() or "Z"
    detail_reason = str(detail_plan.get("reason") or "").strip() or None
    detail_bounds = (
        detail_region["center_x"] - detail_region["radius_mm"],
        detail_region["center_x"] + detail_region["radius_mm"],
        detail_region["center_y"] - detail_region["radius_mm"],
        detail_region["center_y"] + detail_region["radius_mm"],
    )
    detail_svg = _generate_detail_view_svg(
        str(parent_item.get("svg") or ""),
        parent_item.get("svg_bounds"),
        detail_region["center_ratio_x"],
        detail_region["center_ratio_y"],
        detail_region["radius_mm"],
        zoom_factor,
        _optional_float(parent_item.get("scale")) or _optional_float(parent_item.get("scale_fit")) or 1.0,
    )

    slot = iso_item.get("slot") or {}
    slot_w = _optional_float(slot.get("w")) or 0.0
    slot_h = _optional_float(slot.get("h")) or 0.0
    scale_fit = compute_scale_for_area(
        detail_bounds,
        slot_w,
        slot_h,
        padding=iso_padding,
    )

    detail_w, detail_h = bounds_size(detail_bounds)
    iso_item.update(
        {
            "svg": detail_svg,
            "svg_bounds": detail_bounds,
            "proj_bounds": detail_bounds,
            "rotation_deg": int(parent_item.get("rotation_deg", 0) or 0),
            "layout_bounds": detail_bounds,
            "bounds_for_scale": detail_bounds,
            "scale_fit": scale_fit,
            "geom_w": detail_w,
            "geom_h": detail_h,
            "fit_w": detail_w,
            "fit_h": detail_h,
            "direction": parent_item.get("direction"),
            "view_kind": "detail",
            "view_title": f"Detail {detail_label}",
            "detail_label": detail_label,
            "detail_parent_view": parent_view_name,
            "detail_zoom_factor": zoom_factor,
            "detail_reason": detail_reason,
        }
    )
    parent_item["detail_circle_plan"] = {
        "label": detail_label,
        "center_x": detail_region["center_x"],
        "center_y": detail_region["center_y"],
        "radius_mm": detail_region["radius_mm"],
    }
    log(
        f"Detail view injected into Iso slot: Detail {detail_label} from {parent_view_name} "
        f"(zoom={zoom_factor:.2f}, radius={detail_region['radius_mm']:.2f})"
    )
    return True


def resolve_overall_dimension_axes(view_name, dim_plan=None):
    if dim_plan:
        view_plan = get_dimension_plan_view(dim_plan, view_name)
        view_dims = (view_plan or {}).get("dimensions", [])
        show_horizontal = any(
            d.get("axis") == "H" and str(d.get("dim_type", "")).startswith("overall")
            for d in view_dims
        )
        show_vertical = any(
            d.get("axis") == "V" and str(d.get("dim_type", "")).startswith("overall")
            for d in view_dims
        )
        return show_horizontal, show_vertical

    show_horizontal = True
    show_vertical = True
    if view_name == "Left":
        show_horizontal = False
        show_vertical = False
    elif view_name == "Top":
        show_horizontal = False
        show_vertical = True
    return show_horizontal, show_vertical


def view_requests_feature_dimensions(view_name, dim_plan=None, feature_payload=None):
    if not dim_plan:
        return False
    return bool(
        feature_dimension_types_for_view(
            view_name,
            dim_plan=dim_plan,
            feature_payload=feature_payload,
        )
    )


def compute_stroke_width(scale, stroke_base=0.12, min_width=0.001):
    return max(min_width, stroke_base / max(scale, 0.05))


def iso128_line_profile(scale):
    visible = compute_stroke_width(scale, stroke_base=0.18, min_width=0.001)
    hidden = max(0.0008, visible * 0.62)
    centerline = max(0.0006, visible * 0.46)
    dimension = max(0.0007, visible * 0.48)
    section = max(0.0014, visible * 1.35)
    hidden_dash = f"{max(0.8, 4.0 / max(scale, 0.05)):.3f} {max(0.5, 1.8 / max(scale, 0.05)):.3f}"
    center_dash = (
        f"{max(1.0, 5.0 / max(scale, 0.05)):.3f} "
        f"{max(0.5, 2.0 / max(scale, 0.05)):.3f} "
        f"{max(0.5, 1.2 / max(scale, 0.05)):.3f} "
        f"{max(0.5, 2.0 / max(scale, 0.05)):.3f}"
    )
    return {
        "visible": visible,
        "hidden": hidden,
        "centerline": centerline,
        "dimension": dimension,
        "section": section,
        "hidden_dash": hidden_dash,
        "center_dash": center_dash,
    }


def apply_iso128_geometry_style(svg_group, line_profile):
    visible_w = float(line_profile.get("visible", 0.001))
    hidden_w = float(line_profile.get("hidden", visible_w * 0.62))
    section_w = float(line_profile.get("section", visible_w * 1.35))
    hidden_dash = str(line_profile.get("hidden_dash", "3 1.5"))

    styled = svg_group
    # Baseline: visible outline as thick continuous line.
    styled = re.sub(r'stroke-width="[^"]+"', f'stroke-width="{visible_w:.4f}"', styled)
    styled = re.sub(r'stroke-width:\s*[^;"\']+', f'stroke-width:{visible_w:.4f}', styled)
    # Hidden edges: keep dashed and reduce thickness.
    styled = re.sub(
        r'(<[^>]*stroke-dasharray="[^"]*"[^>]*?)stroke-width="[^"]*"',
        rf"\1stroke-width=\"{hidden_w:.4f}\"",
        styled,
        flags=re.IGNORECASE,
    )
    styled = re.sub(
        r'(<[^>]*stroke-dasharray="[^"]*"[^>]*style="[^"]*?)stroke-width:\s*[^;"\']+',
        rf"\1stroke-width:{hidden_w:.4f}",
        styled,
        flags=re.IGNORECASE,
    )
    # If hidden elements are tagged by class/id, force dashed pattern as fallback.
    styled = re.sub(
        r'(<[^>]*(?:class|id)="[^"]*(?:hidden|verdeckt)[^"]*"[^>]*)(/?>)',
        rf'\1 stroke-dasharray="{hidden_dash}" stroke-width="{hidden_w:.4f}"\2',
        styled,
        flags=re.IGNORECASE,
    )
    # Section lines (if tagged by class/id) become strongest.
    styled = re.sub(
        r'(<[^>]*(?:class|id)="[^"]*(?:section|schnitt)[^"]*"[^>]*?)stroke-width="[^"]*"',
        rf"\1stroke-width=\"{section_w:.4f}\"",
        styled,
        flags=re.IGNORECASE,
    )
    styled = re.sub(
        r'(<[^>]*(?:class|id)="[^"]*(?:section|schnitt)[^"]*"[^>]*style="[^"]*?)stroke-width:\s*[^;"\']+',
        rf"\1stroke-width:{section_w:.4f}",
        styled,
        flags=re.IGNORECASE,
    )
    return styled


def transform_local_point_to_paper(x, y, svg_bounds, center_x, center_y, scale, rotation_deg):
    """Transform one local SVG-space point into paper coordinates.

    This mirrors the `build_view_group()` transform exactly:
    translate(center) scale(scale) rotate(rotation) translate(-local_center_x, -local_center_y)
    """
    min_x, max_x, min_y, max_y = svg_bounds
    local_center_x = (min_x + max_x) / 2
    local_center_y = (min_y + max_y) / 2

    x1 = x - local_center_x
    y1 = y - local_center_y

    rad = math.radians(rotation_deg)
    cos_r = math.cos(rad)
    sin_r = math.sin(rad)
    x2 = x1 * cos_r - y1 * sin_r
    y2 = x1 * sin_r + y1 * cos_r

    return x2 * scale + center_x, y2 * scale + center_y


def transform_local_bounds_to_paper(bounds, svg_bounds, center_x, center_y, scale, rotation_deg):
    """Transform a local SVG-space bounds tuple (min_x, max_x, min_y, max_y) to paper bounds."""
    if not bounds or len(bounds) != 4:
        return None
    min_x, max_x, min_y, max_y = bounds
    corners = [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]
    paper_corners = [
        transform_local_point_to_paper(x, y, svg_bounds, center_x, center_y, scale, rotation_deg)
        for x, y in corners
    ]
    xs = [point[0] for point in paper_corners]
    ys = [point[1] for point in paper_corners]
    return (min(xs), max(xs), min(ys), max(ys))


def transform_dimension_entries_to_paper(entries, svg_bounds, center_x, center_y, scale, rotation_deg):
    transformed_entries = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        transformed_entry = dict(entry)
        for box_key in ("measurement_box", "text_box"):
            transformed_entry[box_key] = transform_local_bounds_to_paper(
                entry.get(box_key),
                svg_bounds,
                center_x,
                center_y,
                scale,
                rotation_deg,
            )
        transformed_entries.append(transformed_entry)
    return transformed_entries


def compute_transformed_bounds(svg_bounds, center_x, center_y, scale, rotation_deg):
    return transform_local_bounds_to_paper(svg_bounds, svg_bounds, center_x, center_y, scale, rotation_deg)


def merge_bounds(*bounds_list):
    valid = [tuple(bounds) for bounds in bounds_list if bounds and len(bounds) == 4]
    if not valid:
        return None
    return (
        min(bounds[0] for bounds in valid),
        max(bounds[1] for bounds in valid),
        min(bounds[2] for bounds in valid),
        max(bounds[3] for bounds in valid),
    )


def bounds_to_rect_dict(bounds):
    if not bounds or len(bounds) != 4:
        return None
    return {
        "left": round(float(bounds[0]), 2),
        "right": round(float(bounds[1]), 2),
        "top": round(float(bounds[2]), 2),
        "bottom": round(float(bounds[3]), 2),
    }


def compute_bounds_overflow(bounds, drawing_bounds):
    if not bounds or not drawing_bounds or len(bounds) != 4 or len(drawing_bounds) != 4:
        return {"left": 0.0, "top": 0.0, "right": 0.0, "bottom": 0.0, "max": 0.0}
    draw_left, draw_right, draw_top, draw_bottom = drawing_bounds
    overflow_left = max(0.0, draw_left - float(bounds[0]))
    overflow_top = max(0.0, draw_top - float(bounds[2]))
    overflow_right = max(0.0, float(bounds[1]) - draw_right)
    overflow_bottom = max(0.0, float(bounds[3]) - draw_bottom)
    return {
        "left": round(overflow_left, 3),
        "top": round(overflow_top, 3),
        "right": round(overflow_right, 3),
        "bottom": round(overflow_bottom, 3),
        "max": round(max(overflow_left, overflow_top, overflow_right, overflow_bottom), 3),
    }


def compute_bounds_intersection(bounds_a, bounds_b):
    if not bounds_a or not bounds_b or len(bounds_a) != 4 or len(bounds_b) != 4:
        return {"x": 0.0, "y": 0.0, "area": 0.0}
    overlap_x = max(0.0, min(float(bounds_a[1]), float(bounds_b[1])) - max(float(bounds_a[0]), float(bounds_b[0])))
    overlap_y = max(0.0, min(float(bounds_a[3]), float(bounds_b[3])) - max(float(bounds_a[2]), float(bounds_b[2])))
    return {
        "x": round(overlap_x, 3),
        "y": round(overlap_y, 3),
        "area": round(overlap_x * overlap_y, 3),
    }


def bounds_from_center(center_x, center_y, width, height):
    half_w = max(0.0, float(width)) * 0.5
    half_h = max(0.0, float(height)) * 0.5
    return (
        float(center_x) - half_w,
        float(center_x) + half_w,
        float(center_y) - half_h,
        float(center_y) + half_h,
    )


def compute_abwicklung_render_bounds(abwicklung_meta):
    if not isinstance(abwicklung_meta, dict):
        return None
    outline_bounds = abwicklung_meta.get("outline_bounds") or []
    if len(outline_bounds) != 4:
        return None
    x1, y1, x2, y2 = [float(value) for value in outline_bounds]
    min_x = min(x1, x2)
    max_x = max(x1, x2)
    min_y = min(y1, y2)
    max_y = max(y1, y2)

    for key in ("dim_h_line_y", "flange_dim_line_y"):
        value = _optional_float(abwicklung_meta.get(key))
        if value is not None:
            max_y = max(max_y, value + 3.5)
    for key in ("dim_v_line_x", "flange_dim_line_x"):
        value = _optional_float(abwicklung_meta.get(key))
        if value is not None:
            max_x = max(max_x, value + 6.0)

    return (min_x, max_x, min_y, max_y)


def build_coordinate_system_svg(svg_bounds, view_name, scale):
    """
    Build a small coordinate system indicator for debugging.
    Shows X (red), Y (green), Z (blue) axes with labels.
    Placed in the bottom-left corner of the view.
    """
    min_x, max_x, min_y, max_y = svg_bounds
    
    # Position in bottom-left corner of the SVG bounds
    # Note: SVG Y is inverted, so "bottom" = larger Y values in SVG
    origin_x = min_x + 5 / scale  # Small offset from edge
    origin_y = max_y - 5 / scale  # Bottom of SVG (larger Y)
    
    # Axis length in SVG units
    axis_len = 15 / scale
    arrow_size = 3 / scale
    font_size = 10 / scale
    stroke_w = 0.5 / scale
    
    # Define which world axes appear as screen X and screen Y for each view
    # Screen X = right, Screen Y = up (but SVG Y is inverted, so -Y = up)
    # For each view, we show what world axes map to screen axes
    axis_info = {
        "Front": {"screen_x": "X", "screen_y": "Y"},  # Looking at XY plane from +Z
        "Left":  {"screen_x": "Z", "screen_y": "Y"},  # Looking at ZY plane from +X
        "Top":   {"screen_x": "X", "screen_y": "Z"},  # Looking at XZ plane from +Y
        "Iso":   {"screen_x": "~", "screen_y": "~"},  # Isometric - mixed
    }
    
    info = axis_info.get(view_name, {"screen_x": "?", "screen_y": "?"})
    x_label = info["screen_x"]
    y_label = info["screen_y"]
    
    # Colors for axes
    colors = {"X": "#FF0000", "Y": "#00AA00", "Z": "#0000FF", "~": "#666666", "?": "#999999"}
    x_color = colors.get(x_label, "#999999")
    y_color = colors.get(y_label, "#999999")
    
    svg_parts = []
    
    # Background box for visibility
    box_size = axis_len * 1.8
    svg_parts.append(
        f'<rect x="{origin_x - 2/scale}" y="{origin_y - box_size}" '
        f'width="{box_size}" height="{box_size}" '
        f'fill="white" fill-opacity="0.8" stroke="#CCCCCC" stroke-width="{stroke_w * 0.5}"/>'
    )
    
    # X axis (horizontal, pointing right) with arrow
    x_end = origin_x + axis_len
    svg_parts.append(
        f'<line x1="{origin_x}" y1="{origin_y}" x2="{x_end}" y2="{origin_y}" '
        f'stroke="{x_color}" stroke-width="{stroke_w}"/>'
    )
    # Arrow head
    svg_parts.append(
        f'<polygon points="{x_end},{origin_y} {x_end - arrow_size},{origin_y - arrow_size/2} '
        f'{x_end - arrow_size},{origin_y + arrow_size/2}" fill="{x_color}"/>'
    )
    # Label
    svg_parts.append(
        f'<text x="{x_end + 2/scale}" y="{origin_y + font_size/3}" '
        f'font-size="{font_size}" fill="{x_color}" font-family="Arial" font-weight="bold">{x_label}</text>'
    )
    
    # Y axis (vertical, pointing up = negative SVG Y) with arrow
    y_end = origin_y - axis_len
    svg_parts.append(
        f'<line x1="{origin_x}" y1="{origin_y}" x2="{origin_x}" y2="{y_end}" '
        f'stroke="{y_color}" stroke-width="{stroke_w}"/>'
    )
    # Arrow head
    svg_parts.append(
        f'<polygon points="{origin_x},{y_end} {origin_x - arrow_size/2},{y_end + arrow_size} '
        f'{origin_x + arrow_size/2},{y_end + arrow_size}" fill="{y_color}"/>'
    )
    # Label
    svg_parts.append(
        f'<text x="{origin_x - font_size/2}" y="{y_end - 2/scale}" '
        f'font-size="{font_size}" fill="{y_color}" font-family="Arial" font-weight="bold">{y_label}</text>'
    )
    
    # View name label
    svg_parts.append(
        f'<text x="{origin_x}" y="{origin_y + font_size * 1.2}" '
        f'font-size="{font_size * 0.8}" fill="#333333" font-family="Arial">{view_name}</text>'
    )
    
    return "\n".join(svg_parts)


def build_view_group(
    svg_group,
    svg_bounds,
    proj_bounds,
    center_x,
    center_y,
    scale,
    rotation_deg=0,
    stroke_width=None,
    line_profile=None,
    stroke_base=0.006,
    dimension_svg="",
    view_name="",
    show_coordinate_system=True,
):
    """
    Build SVG group for a view.
    
    The SVG content is centered around its own bounds (svg_bounds).
    The dimension lines are also in svg_bounds coordinates (drawn around the geometry).
    The paper position (center_x, center_y) is calculated based on proj_bounds for layout.
    """
    # Calculate SVG center (where the content actually is)
    svg_min_x, svg_max_x, svg_min_y, svg_max_y = svg_bounds
    svg_center_x = (svg_min_x + svg_max_x) / 2
    svg_center_y = (svg_min_y + svg_max_y) / 2
    
    # Use SVG center for the transformation (content is centered around this)
    local_center_x = svg_center_x
    local_center_y = svg_center_y
    
    if line_profile is None:
        line_profile = iso128_line_profile(scale)
    if stroke_width is None:
        stroke_width = float(line_profile.get("visible", compute_stroke_width(scale, stroke_base=stroke_base)))
    svg_group = apply_iso128_geometry_style(svg_group, line_profile)
    svg_group = re.sub(
        r"<g\s",
        '<g vector-effect="non-scaling-stroke" data-layer="geometry-visible" ',
        svg_group,
        count=1,
    )
    if dimension_svg:
        svg_group = append_to_group(svg_group, f'<g data-layer="dimensions">{dimension_svg}</g>')
    
    # Add coordinate system indicator for debugging
    if show_coordinate_system and view_name:
        coord_svg = build_coordinate_system_svg(svg_bounds, view_name, scale)
        svg_group = append_to_group(svg_group, f'<g data-layer="debug-axis">{coord_svg}</g>')
    rotate_clause = f" rotate({rotation_deg})" if rotation_deg else ""
    
    # Transform order in SVG is applied right-to-left. For bounds calculations we
    # therefore mirror the effective local-center subtraction before rotation.
    transform = (
        f"translate({center_x:.2f},{center_y:.2f}) "
        f"scale({scale:.4f},{scale:.4f}){rotate_clause} "
        f"translate({-local_center_x:.2f},{local_center_y:.2f})"
    )
    return f'<g transform="{transform}">\n{svg_group}\n</g>'


def compute_ortho_scale(dim_x, dim_y, dim_z, cell_w, cell_h):
    max_width = max(dim_x, dim_y, 0.1)
    max_height = max(dim_y, dim_z, 0.1)
    return min((cell_w * 0.9) / max_width, (cell_h * 0.9) / max_height)


def compute_fit_scale(bounds, cell_w, cell_h, padding=0.9):
    width, height = bounds_size(bounds)
    return min((cell_w * padding) / width, (cell_h * padding) / height)


def compute_scale_for_area(bounds, area_w, area_h, padding=0.85):
    width, height = bounds_size(bounds)
    return min((area_w * padding) / width, (area_h * padding) / height)


def compute_dimension_padded_bounds(
    base_bounds,
    cell_w,
    cell_h,
    padding=0.85,
    iterations=2,
    show_horizontal=True,
    show_vertical=True,
    extra_padding_fn=None,
):
    scale = compute_fit_scale(base_bounds, cell_w, cell_h, padding=padding)
    padded_bounds = base_bounds
    for _ in range(max(1, iterations)):
        pad = dimension_metrics(base_bounds, scale)["pad"]
        padded_bounds = expand_dimension_bounds(
            base_bounds,
            pad,
            show_horizontal=show_horizontal,
            show_vertical=show_vertical,
        )
        if callable(extra_padding_fn):
            extra_padding = extra_padding_fn(scale)
            if isinstance(extra_padding, dict):
                padded_bounds = expand_bounds_asymmetric(
                    padded_bounds,
                    left=extra_padding.get("left", 0.0),
                    right=extra_padding.get("right", 0.0),
                    top=extra_padding.get("top", 0.0),
                    bottom=extra_padding.get("bottom", 0.0),
                )
        scale = compute_fit_scale(padded_bounds, cell_w, cell_h, padding=padding)
    return padded_bounds, scale


def estimate_feature_dimension_padding(scale, view_name, *, dim_plan=None, feature_payload=None, policy_hints=None):
    allowed_types = (
        feature_dimension_types_for_view(
            view_name,
            dim_plan=dim_plan,
            feature_payload=feature_payload,
        )
        if dim_plan
        else set()
    )
    if not should_place_feature_dims_outside(view_name, allowed_types):
        return {}

    scale = max(float(scale or 0.0), 0.05)
    text_size = max(0.2, 3.7 / scale)
    label_gap = max(1.8, 4.0 / scale)
    outside_margin = max(4.0 / scale, label_gap * 0.9)
    hole_count = int(_optional_float((feature_payload or {}).get("hole_count")) or 0)
    part_type = str((dim_plan or {}).get("part_type") or "").strip().lower()
    density_score = feature_dimension_density_score(view_name, dim_plan=dim_plan, feature_payload=feature_payload)
    layout_escalation = view_requires_layout_escalation(
        view_name,
        dim_plan=dim_plan,
        feature_payload=feature_payload,
        policy_hints=policy_hints,
    )
    detail_escalation = view_prefers_detail_escalation(
        view_name,
        dim_plan=dim_plan,
        feature_payload=feature_payload,
        policy_hints=policy_hints,
    )
    aggressive_sheet_padding = part_type == "sheet_metal" and not bool((feature_payload or {}).get("is_flat"))

    # Sheet-metal front views frequently place outside pitch/datum dimensions
    # above and left of the folded view. Milling parts should remain much more
    # conservative to avoid needless A2 promotion.
    if part_type == "sheet_metal":
        if aggressive_sheet_padding:
            top_pad = outside_margin + label_gap * 3.4 + text_size * 2.2
            left_pad = outside_margin + label_gap * 2.8 + text_size * 2.8
            if hole_count > 4:
                top_pad += min(16.0 / scale, hole_count * 0.55 / scale)
                left_pad += min(12.0 / scale, hole_count * 0.35 / scale)
            if str(view_name or "") == "Front":
                top_pad += max(6.0 / scale, text_size * 1.6)
                left_pad += max(5.0 / scale, text_size * 1.2)
            right_pad = text_size * 1.2 if {"hole_diameter", "thread_callout"} & set(allowed_types) else 0.0
            bottom_pad = text_size * 0.8 if "bend_radius" in allowed_types else 0.0
        else:
            top_pad = outside_margin + label_gap * 2.6 + text_size * 1.8
            left_pad = outside_margin + label_gap * 2.2 + text_size * 2.3
            if hole_count > 4:
                top_pad += min(12.0 / scale, hole_count * 0.45 / scale)
                left_pad += min(8.0 / scale, hole_count * 0.25 / scale)
            right_pad = text_size * 0.9 if {"hole_diameter", "thread_callout"} & set(allowed_types) else 0.0
            bottom_pad = text_size * 0.6 if "bend_radius" in allowed_types else 0.0
    elif part_type == "milling":
        top_pad = outside_margin + label_gap * 1.6 + text_size * 1.1
        if hole_count > 4:
            top_pad += min(10.0 / scale, hole_count * 0.3 / scale)
        if str(view_name or "") == "Front":
            top_pad += max(3.0 / scale, text_size * 0.8)
        left_pad = max(1.5 / scale, text_size * 0.4) if "hole_location_y" in allowed_types else 0.0
        right_pad = max(1.8 / scale, text_size * 0.8) if {"hole_diameter", "thread_callout"} & set(allowed_types) else 0.0
        bottom_pad = max(1.2 / scale, text_size * 0.4) if "bend_radius" in allowed_types else 0.0
        if layout_escalation:
            top_pad += max(3.0 / scale, text_size * 0.8)
            if density_score >= 5:
                top_pad += max(1.5 / scale, text_size * 0.4)
            if "hole_location_y" in allowed_types:
                left_pad += max(2.0 / scale, text_size * 0.5)
            if {"hole_diameter", "thread_callout"} & set(allowed_types):
                right_pad += max(2.0 / scale, text_size * 0.5)
        if detail_escalation:
            top_pad += max(4.0 / scale, text_size * 1.0)
            right_pad += max(2.5 / scale, text_size * 0.6)
    else:
        return {}

    return {
        "left": left_pad,
        "right": right_pad,
        "top": top_pad,
        "bottom": bottom_pad,
    }


def scaled_bounds(bounds, scale, center_x, center_y):
    width, height = bounds_size(bounds)
    half_w = (width * scale) / 2
    half_h = (height * scale) / 2
    return center_x - half_w, center_x + half_w, center_y - half_h, center_y + half_h


def normalize_vec(vec):
    length = vec.Length
    if length == 0:
        return None
    return vec.multiply(1.0 / length)


def snap_axis(vec, threshold=0.98):
    axis = normalize_vec(vec)
    if axis is None:
        return None
    world_axes = [
        App.Vector(1, 0, 0),
        App.Vector(0, 1, 0),
        App.Vector(0, 0, 1),
    ]
    best_dot = 0.0
    best_axis = None
    for base in world_axes:
        dot_value = axis.dot(base)
        if abs(dot_value) > abs(best_dot):
            best_dot = dot_value
            best_axis = base
    if best_axis is None or abs(best_dot) < threshold:
        return axis
    return best_axis if best_dot >= 0 else best_axis.negative()


def collect_points(shape):
    points = [vertex.Point for vertex in shape.Vertexes if vertex.Point]
    try:
        bb = shape.BoundBox
        max_dim = max(bb.XLength, bb.YLength, bb.ZLength, 1.0)
        deflection = max(0.5, max_dim / 40.0)
        vertices, _ = shape.tessellate(deflection)
        for vertex in vertices:
            points.append(App.Vector(vertex[0], vertex[1], vertex[2]))
    except (RuntimeError, AttributeError, TypeError):
        pass
    return points


def compute_covariance(points):
    count = len(points)
    if count == 0:
        return None, None
    mean_x = sum(point.x for point in points) / count
    mean_y = sum(point.y for point in points) / count
    mean_z = sum(point.z for point in points) / count
    mean = App.Vector(mean_x, mean_y, mean_z)
    centered = [point.sub(mean) for point in points]
    cov = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    for point in centered:
        cov[0][0] += point.x * point.x
        cov[0][1] += point.x * point.y
        cov[0][2] += point.x * point.z
        cov[1][0] += point.y * point.x
        cov[1][1] += point.y * point.y
        cov[1][2] += point.y * point.z
        cov[2][0] += point.z * point.x
        cov[2][1] += point.z * point.y
        cov[2][2] += point.z * point.z
    scale = 1.0 / count
    for i in range(3):
        for j in range(3):
            cov[i][j] *= scale
    return cov, centered


def mat_vec(mat, vec):
    return App.Vector(
        mat[0][0] * vec.x + mat[0][1] * vec.y + mat[0][2] * vec.z,
        mat[1][0] * vec.x + mat[1][1] * vec.y + mat[1][2] * vec.z,
        mat[2][0] * vec.x + mat[2][1] * vec.y + mat[2][2] * vec.z,
    )


def outer(vec):
    return [
        [vec.x * vec.x, vec.x * vec.y, vec.x * vec.z],
        [vec.y * vec.x, vec.y * vec.y, vec.y * vec.z],
        [vec.z * vec.x, vec.z * vec.y, vec.z * vec.z],
    ]


def mat_sub(a, b):
    return [[a[i][j] - b[i][j] for j in range(3)] for i in range(3)]


def power_iteration(mat, iterations=30):
    seed = mat[0][0] + mat[1][1] + mat[2][2]
    initial = App.Vector(mat[0][0] + 0.01, mat[0][1] + 0.02, mat[0][2] + 0.03)
    if initial.Length < 1e-8 and abs(seed) < 1e-8:
        initial = App.Vector(1, 0, 0)
    vec = normalize_vec(initial)
    if vec is None:
        return None
    for _ in range(iterations):
        next_vec = mat_vec(mat, vec)
        norm = next_vec.Length
        if norm < 1e-10:
            return None
        vec = next_vec.multiply(1.0 / norm)
    return vec


def eigenvalue(mat, vec):
    return vec.dot(mat_vec(mat, vec))


def perpendicular_vec(vec):
    ref = App.Vector(1, 0, 0) if abs(vec.x) < 0.9 else App.Vector(0, 1, 0)
    perp = vec.cross(ref)
    return normalize_vec(perp)


def pca_axes(points):
    cov, centered = compute_covariance(points)
    if cov is None or centered is None:
        return None, None
    e1 = power_iteration(cov)
    if e1 is None:
        return None, centered
    lambda1 = eigenvalue(cov, e1)
    deflated = mat_sub(cov, [[lambda1 * value for value in row] for row in outer(e1)])
    e2 = power_iteration(deflated)
    if e2 is None:
        e2 = perpendicular_vec(e1)
    else:
        proj = e1.multiply(e2.dot(e1))
        e2 = normalize_vec(e2.sub(proj))
    if e2 is None:
        e2 = perpendicular_vec(e1)
    e3 = normalize_vec(e1.cross(e2))
    if e3 is None:
        return None, centered
    return (e1, e2, e3), centered


def view_basis(direction):
    forward = normalize_vec(direction)
    if forward is None:
        return None
    up_hint = App.Vector(0, 0, 1)
    if abs(forward.dot(up_hint)) > 0.9:
        up_hint = App.Vector(0, 1, 0)
    right = normalize_vec(up_hint.cross(forward))
    if right is None:
        return None
    up = normalize_vec(forward.cross(right))
    if up is None:
        return None
    return right, up


def convex_hull(points):
    unique = sorted({(round(p[0], 6), round(p[1], 6)) for p in points})
    if len(unique) <= 2:
        return unique

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def polygon_area(points):
    if len(points) < 3:
        return 0.0
    area = 0.0
    for idx, point in enumerate(points):
        x1, y1 = point
        x2, y2 = points[(idx + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


def projected_area(points, direction):
    basis = view_basis(direction)
    if basis is None:
        return 0.0
    right, up = basis
    projected = [(point.dot(right), point.dot(up)) for point in points]
    hull = convex_hull(projected)
    return polygon_area(hull)


def choose_side_direction(shape, right_dir, points=None):
    # Side view follows the front-view arrow direction (screen-right).
    _ = (shape, points)
    return right_dir


def rotation_for_view(direction, desired_up):
    basis = view_basis(direction)
    if basis is None:
        return 0
    right, up = basis
    du_r = desired_up.dot(right)
    du_u = desired_up.dot(up)
    if abs(du_u) >= abs(du_r):
        return 0 if du_u >= 0 else 180
    return 270 if du_r > 0 else 90


def rotation_for_view_with_axes(direction, desired_right, desired_up):
    basis = view_basis(direction)
    if basis is None:
        return 0
    right, up = basis
    rr_x = desired_right.dot(right)
    rr_y = desired_right.dot(up)
    ru_x = desired_up.dot(right)
    ru_y = desired_up.dot(up)

    def rot2d(x, y, deg):
        if deg == 90:
            return -y, x
        if deg == 180:
            return -x, -y
        if deg == 270:
            return y, -x
        return x, y

    best = 0
    best_score = -1e9
    for deg in (0, 90, 180, 270):
        r_x, r_y = rot2d(rr_x, rr_y, deg)
        u_x, u_y = rot2d(ru_x, ru_y, deg)
        score = (r_x + u_y) - (abs(r_y) + abs(u_x))
        if r_x <= 0 or u_y <= 0:
            score -= 2.0
        if score > best_score:
            best_score = score
            best = deg
    return best


def rotation_for_view_with_expected(direction, desired_up, svg_bounds, expected_w, expected_h):
    svg_w, svg_h = bounds_size(svg_bounds)
    swap = False
    if (
        expected_w is not None
        and expected_h is not None
        and expected_w > 1e-6
        and expected_h > 1e-6
    ):
        delta_keep = abs(svg_w - expected_w) + abs(svg_h - expected_h)
        delta_swap = abs(svg_h - expected_w) + abs(svg_w - expected_h)
        swap = delta_swap + 1e-9 < delta_keep
    base = rotation_for_view(direction, desired_up)
    candidates = [90, 270] if swap else [0, 180]

    def distance(a, b):
        delta = abs(a - b) % 360
        return min(delta, 360 - delta)

    return min(candidates, key=lambda value: (distance(value, base), value))


def rotation_to_make_horizontal(svg_bounds, target_horizontal_extent):
    """
    Calculate rotation needed to make the target dimension appear horizontal.
    If the SVG height matches the target better than width, rotate 90°.
    """
    svg_w, svg_h = bounds_size(svg_bounds)
    if target_horizontal_extent is None or target_horizontal_extent < 1e-6:
        return 0
    
    # Check if SVG width or height better matches target_horizontal_extent
    diff_w = abs(svg_w - target_horizontal_extent)
    diff_h = abs(svg_h - target_horizontal_extent)
    
    # If height matches better, we need to rotate 90° to make it horizontal
    if diff_h < diff_w - 1e-6:
        return 90
    return 0


def projected_bounds(points, direction):
    basis = view_basis(direction)
    if basis is None:
        return None
    right, up = basis
    projected = [(point.dot(right), point.dot(up)) for point in points]
    if not projected:
        return None
    xs = [point[0] for point in projected]
    ys = [point[1] for point in projected]
    return min(xs), max(xs), min(ys), max(ys)


def axis_extent(points, axis):
    axis_norm = normalize_vec(axis)
    if axis_norm is None:
        return 0.0
    values = [point.dot(axis_norm) for point in points]
    return max(values) - min(values) if values else 0.0


def _select_functional_feature_zone(feature_payload, longest_axis):
    if not isinstance(feature_payload, dict):
        return None
    axis_getter = {
        "X": lambda point: float(point.x),
        "Y": lambda point: float(point.y),
        "Z": lambda point: float(point.z),
    }.get(str(longest_axis or "").upper(), lambda point: float(point.x))
    hole_groups = feature_payload.get("hole_groups") or []
    candidates = []
    for group in hole_groups:
        if not isinstance(group, dict):
            continue
        center = group.get("center_mm") or {}
        if not isinstance(center, dict):
            continue
        cx = _optional_float(center.get("x"))
        cy = _optional_float(center.get("y"))
        cz = _optional_float(center.get("z"))
        diameter = _optional_float(group.get("diameter_mm")) or 1.0
        if None in (cx, cy, cz):
            continue
        point = App.Vector(float(cx), float(cy), float(cz))
        candidates.append(
            {
                "point": point,
                "coord": axis_getter(point),
                "weight": max(1.0, float(diameter)),
            }
        )
    if len(candidates) < 2:
        return None

    bbox = feature_payload.get("bbox_mm") or {}
    longest_len = _optional_float(bbox.get(longest_axis)) or 0.0
    if longest_len <= 0.0:
        longest_len = max(item["coord"] for item in candidates) - min(item["coord"] for item in candidates)
    if longest_len <= 0.0:
        return None

    window = max(24.0, min(longest_len * 0.22, 120.0))
    best_cluster = None
    best_rank = None
    for seed in candidates:
        cluster = [
            item
            for item in candidates
            if abs(float(item["coord"]) - float(seed["coord"])) <= window * 0.5
        ]
        if len(cluster) < 2:
            continue
        coords = [float(item["coord"]) for item in cluster]
        span = max(max(coords) - min(coords), 1.0)
        weight = sum(float(item["weight"]) for item in cluster)
        density = weight / span
        rank = (density, len(cluster), -span)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            best_cluster = cluster
    if not best_cluster:
        return None

    total_weight = sum(float(item["weight"]) for item in best_cluster)
    if total_weight <= 1e-6:
        return None
    return App.Vector(
        sum(float(item["point"].x) * float(item["weight"]) for item in best_cluster) / total_weight,
        sum(float(item["point"].y) * float(item["weight"]) for item in best_cluster) / total_weight,
        sum(float(item["point"].z) * float(item["weight"]) for item in best_cluster) / total_weight,
    )


def _functional_front_bias(front_dir, feature_point):
    if feature_point is None:
        return None
    if abs(front_dir.z) > 0.9:
        preferred_up = App.Vector(0, 1, 0)
    else:
        preferred_up = App.Vector(0, 0, 1)
    local_right = normalize_vec(preferred_up.cross(front_dir))
    if local_right is None:
        return None
    return float(feature_point.dot(local_right))


def first_angle_projection(shape, points, policy_hints=None, feature_payload=None):
    """
    First-Angle (ISO/DIN) Projection System:
    
    1. Define FRONT view (direction + up vector)
    2. Derive view coordinate system
    3. LEFT = look from LEFT side (-VIEW_RIGHT)
    4. TOP = look from ABOVE (-VIEW_UP)
    
    Layout:
    ┌───────────┬───────────┐
    │   FRONT   │   LEFT    │  (Left looks from left, placed right of Front)
    ├───────────┼───────────┤
    │    TOP    │    ISO    │  (Top looks from above, placed below Front)
    └───────────┴───────────┘
    
    Alignment:
    - Front ↔ Left: Same HEIGHT, top edges aligned
    - Front ↔ Top: Same WIDTH, left edges aligned
    """
    bb = shape.BoundBox
    dims = [
        ("X", bb.XLength, App.Vector(1, 0, 0)),
        ("Y", bb.YLength, App.Vector(0, 1, 0)),
        ("Z", bb.ZLength, App.Vector(0, 0, 1)),
    ]
    dims_sorted = sorted(dims, key=lambda d: d[1], reverse=True)
    
    longest_name, longest_len, longest_axis = dims_sorted[0]
    second_name, second_len, second_axis = dims_sorted[1]
    third_name, third_len, third_axis = dims_sorted[2]
    
    log(f"[FirstAngle] BBox: {longest_name}={longest_len:.2f}, {second_name}={second_len:.2f}, {third_name}={third_len:.2f}")
    
    # === STEP 1: Choose FRONT direction ===
    # Goal: Longest axis should appear HORIZONTAL in Front view
    # Therefore: Look from a direction PERPENDICULAR to the longest axis
    
    # Detect flat parts
    flatness_ratio = third_len / max(second_len, 1e-6)
    is_flat_part = flatness_ratio < 0.3
    
    def _front_candidate_priority(name):
        # Deterministic tie-break order for ambiguous fronts.
        # Preferred engineering default is negative Y, then positive Y,
        # then negative X/positive X, then Z directions.
        order = {
            "-Y": 0,
            "+Y": 1,
            "-X": 2,
            "+X": 3,
            "-Z": 4,
            "+Z": 5,
        }
        return order.get(str(name), 99)

    candidate_scores = []
    best_name = None
    best_score = float("-inf")

    if is_flat_part:
        # Flat part: look from thin side to show large face
        log(f"[FirstAngle] FLAT part (ratio={flatness_ratio:.2f}) -> look from {third_name}")
        front_dir = third_axis
        # Check which direction shows more detail.
        score_pos = evaluate_front_candidate(shape, third_axis, policy_hints=policy_hints)
        score_neg = evaluate_front_candidate(shape, third_axis.negative(), policy_hints=policy_hints)
        candidate_scores = [
            {"name": f"+{third_name}", **score_pos},
            {"name": f"-{third_name}", **score_neg},
        ]
        pos_effective = score_pos["effective_score"]
        neg_effective = score_neg["effective_score"]
        score_eps = max(0.5, abs(pos_effective) * 0.005, abs(neg_effective) * 0.005)
        relative_gap = abs(pos_effective - neg_effective) / max(abs(pos_effective), abs(neg_effective), 1e-6)
        ambiguous_flat_front = relative_gap < 0.08
        functional_zone = None
        functional_bias = None
        if neg_effective > pos_effective + score_eps and not ambiguous_flat_front:
            front_dir = third_axis.negative()
            best_name = f"-{third_name}"
            best_score = neg_effective
        elif pos_effective > neg_effective + score_eps and not ambiguous_flat_front:
            front_dir = third_axis
            best_name = f"+{third_name}"
            best_score = pos_effective
        else:
            if bool((policy_hints or {}).get("prefer_functional_front_tie_break")):
                functional_zone = _select_functional_feature_zone(feature_payload, longest_name)
                pos_bias = _functional_front_bias(third_axis, functional_zone)
                neg_bias = _functional_front_bias(third_axis.negative(), functional_zone)
                if pos_bias is not None and neg_bias is not None:
                    functional_bias = {
                        f"+{third_name}": round(pos_bias, 5),
                        f"-{third_name}": round(neg_bias, 5),
                    }
                    bias_eps = max(0.25, longest_len * 0.0005)
                    if pos_bias < neg_bias - bias_eps:
                        front_dir = third_axis
                        best_name = f"+{third_name}"
                        best_score = pos_effective
                    elif neg_bias < pos_bias - bias_eps:
                        front_dir = third_axis.negative()
                        best_name = f"-{third_name}"
                        best_score = neg_effective
                    else:
                        front_dir = third_axis.negative()
                        best_name = f"-{third_name}"
                        best_score = max(pos_effective, neg_effective)
                else:
                    front_dir = third_axis.negative()
                    best_name = f"-{third_name}"
                    best_score = max(pos_effective, neg_effective)
            else:
                # Tie: keep deterministic negative preference for mirrored views.
                front_dir = third_axis.negative()
                best_name = f"-{third_name}"
                best_score = max(pos_effective, neg_effective)
        # For flat parts, longest is horizontal
        horizontal_axis = longest_axis
    else:
        # Normal part: look perpendicular to longest axis
        # Choose between second and third axis based on detail score
        #
        # ISO engineering convention: Z MUST be "up" in the Front view.
        # Therefore EXCLUDE Z-axis front directions for non-flat parts.
        # The Z-direction view will naturally become the Top view
        # through the first-angle projection derivation.
        #
        # Among candidates with equal scores, prefer the negative direction
        # (-Y before +Y, -X before +X) because -Y is the standard engineering
        # front and -X is the standard left.
        all_candidates = [
            (third_axis.negative(), f"-{third_name}"),
            (third_axis, f"+{third_name}"),
            (second_axis.negative(), f"-{second_name}"),
            (second_axis, f"+{second_name}"),
        ]
        # Filter out Z-axis directions to guarantee Z-up in Front view
        candidates = [(d, n) for d, n in all_candidates if abs(d.z) < 0.5]
        if not candidates:
            # Fallback: all candidates were Z-axis (shouldn't happen for non-flat)
            candidates = all_candidates
            log("[FirstAngle] WARNING: No non-Z candidates available, using all")
        best_dir = candidates[0][0]
        best_score = float("-inf")
        best_name = candidates[0][1]
        for d, name in candidates:
            candidate = evaluate_front_candidate(shape, d, policy_hints=policy_hints)
            score = candidate["effective_score"]
            candidate_scores.append({"name": name, **candidate})
            log(
                f"[FirstAngle]   candidate {name}: "
                f"detail={candidate['detail_score']:.1f} "
                f"hidden={candidate['hidden_edge_load']:.1f} "
                f"effective={score:.1f}"
            )
            score_eps = max(0.5, abs(best_score) * 0.005) if best_score > float("-inf") else 0.0
            if score > best_score + score_eps:
                best_score = score
                best_dir = d
                best_name = name
            elif abs(score - best_score) <= score_eps:
                # Tie-break deterministically by engineering priority.
                if _front_candidate_priority(name) < _front_candidate_priority(best_name):
                    best_score = score
                    best_dir = d
                    best_name = name
        front_dir = best_dir
        log(f"[FirstAngle] Chose front {best_name} with effective score {best_score:.1f}")
        # Longest axis will be horizontal
        horizontal_axis = longest_axis
    
    log(f"[FirstAngle] Front direction: ({front_dir.x:.2f}, {front_dir.y:.2f}, {front_dir.z:.2f})")
    log(f"[FirstAngle] Horizontal axis (longest): {longest_name}")
    
    # === STEP 2: Build LOCAL Coordinate System ===
    #
    # After choosing front_dir (camera position direction), we define LOCAL axes:
    # - local_right  = "right" in the Front view (screen X)
    # - local_up     = "up"    in the Front view (screen Y)
    # - front_dir    = camera position direction (screen depth)
    #
    # Then first-angle projection derives:
    # - Left view direction  = -local_right  (camera on the LEFT side)
    # - Top view direction   = +local_up     (camera ABOVE)
    
    front_dir = snap_axis(front_dir)
    
    # === STEP 2: Build LOCAL Coordinate System via Cross Product ===
    #
    # Convention:
    #   1. "up" prefers +Z (engineering standard), falls back to +Y
    #   2. "right" = preferred_up × front_dir  (cross product → sign-correct)
    #   3. "up" = front_dir × right            (back-calculated → exactly orthogonal)
    #
    # Why this works:
    #   The cross product automatically flips its sign when front_dir flips.
    #   front=(0,0,+1) → right = (0,1,0)×(0,0,+1) = (+1,0,0)  X goes right
    #   front=(0,0,-1) → right = (0,1,0)×(0,0,-1) = (-1,0,0)  X goes left ✓
    #   This is physically correct: from the opposite side, left/right swap.
    
    if abs(front_dir.z) > 0.9:
        # Looking along Z axis → Z cannot be "up" → use Y
        preferred_up = App.Vector(0, 1, 0)
    else:
        # Looking along X or Y → Z is "up" (engineering convention)
        preferred_up = App.Vector(0, 0, 1)
    
    local_right = normalize_vec(preferred_up.cross(front_dir))
    if local_right is None:
        local_right = App.Vector(1, 0, 0)  # Fallback (should never happen)
    local_right = snap_axis(local_right)
    
    local_up = normalize_vec(front_dir.cross(local_right))
    if local_up is None:
        local_up = App.Vector(0, 0, 1)
    local_up = snap_axis(local_up)
    
    # NOTE: No landscape swap — keeping natural orientation so that
    # Left/Top directions always correspond to engineering world axes.
    # Portrait front views (tall parts) are acceptable per ISO convention.
    # The SVG rotation in the rendering step handles paper-space presentation.
    
    view_right = local_right
    view_up = local_up
    
    log(f"[FirstAngle] Local coord system (cross-product):")
    log(f"[FirstAngle]   RIGHT  = {vec_str(local_right)}")
    log(f"[FirstAngle]   FORWARD= {vec_str(front_dir)}")
    log(f"[FirstAngle]   UP     = {vec_str(local_up)}")
    
    # === STEP 3: Derive Left and Top from LOCAL coordinate system ===
    #
    # First-Angle Projection (ISO standard):
    # - LEFT view: rays go toward left side = -local_right
    # - TOP view: rays go toward top = +local_up
    
    left_dir = App.Vector(-local_right.x, -local_right.y, -local_right.z)
    top_dir = local_up
    
    # ISO view: Diagonal from front-right-top
    forward = App.Vector(-front_dir.x, -front_dir.y, -front_dir.z)
    iso_dir = normalize_vec(App.Vector(
        forward.x + view_right.x + view_up.x,
        forward.y + view_right.y + view_up.y,
        forward.z + view_right.z + view_up.z
    ))
    if iso_dir is None:
        iso_dir = App.Vector(1, 1, 1)
    
    log(f"[FirstAngle] FRONT={vec_str(front_dir)}, LEFT={vec_str(left_dir)}, TOP={vec_str(top_dir)}")
    
    # === STEP 4: Calculate real confidence ===
    # Compare detail scores of all front candidates to see how clear the choice was
    all_candidates = [
        (third_axis, f"+{third_name}"),
        (third_axis.negative(), f"-{third_name}"),
    ]
    if not is_flat_part:
        all_candidates += [
            (second_axis, f"+{second_name}"),
            (second_axis.negative(), f"-{second_name}"),
        ]
    scores = []
    for d, _name in all_candidates:
        try:
            candidate = evaluate_front_candidate(shape, d, policy_hints=policy_hints)
            scores.append(candidate["effective_score"])
        except (RuntimeError, TypeError, ValueError, KeyError):
            scores.append(0.0)
    confidence_basis = "all_candidates"
    confidence_values = scores
    # If available, prefer the exact candidates used for front selection.
    if candidate_scores:
        confidence_basis = "front_candidates"
        confidence_values = [
            float(candidate.get("effective_score") or 0.0)
            for candidate in candidate_scores
        ]

    score_gap = 1.0
    if len(confidence_values) >= 2:
        sorted_scores = sorted(confidence_values, reverse=True)
        confidence_best = sorted_scores[0]
        second_score = sorted_scores[1]
        if confidence_best > 1e-6:
            score_gap = (confidence_best - second_score) / confidence_best
            confidence = min(1.0, score_gap / 0.3)  # 30% gap = full confidence
        else:
            confidence = 0.0
    else:
        confidence = 1.0
        score_gap = 1.0
    
    debug_info = {
        "longest_axis": longest_name,
        "is_flat": is_flat_part,
        "flatness_ratio": round(flatness_ratio, 3),
        "view_right": [round(view_right.x, 2), round(view_right.y, 2), round(view_right.z, 2)],
        "view_up": [round(view_up.x, 2), round(view_up.y, 2), round(view_up.z, 2)],
        "chosen_front": best_name if "best_name" in locals() else vec_str(front_dir),
        "candidates": [
            {
                "name": candidate.get("name"),
                "detail_score": round(float(candidate.get("detail_score") or 0.0), 2),
                "hidden_edge_load": round(float(candidate.get("hidden_edge_load") or 0.0), 2),
                "hidden_ratio": round(float(candidate.get("hidden_ratio") or 0.0), 4),
                "penalty": round(float(candidate.get("penalty") or 0.0), 2),
                "effective_score": round(float(candidate.get("effective_score") or 0.0), 2),
                "section_recommended": bool(candidate.get("section_recommended", False)),
            }
            for candidate in (candidate_scores if "candidate_scores" in locals() else [])
        ],
        "confidence_basis": confidence_basis,
        "candidate_score_gap": round(score_gap, 5),
        "front_ambiguous": bool(score_gap < 0.08),
        "front_view_rule_id": (policy_hints or {}).get("front_view_rule_id"),
        "front_view_strategy": (policy_hints or {}).get("front_view_strategy"),
        "prefer_low_hidden_edge_load": bool((policy_hints or {}).get("prefer_low_hidden_edge_load")),
        "prefer_functional_front_tie_break": bool((policy_hints or {}).get("prefer_functional_front_tie_break")),
        "functional_front_bias": functional_bias if "functional_bias" in locals() else None,
        "functional_zone_center": (
            [
                round(float(functional_zone.x), 3),
                round(float(functional_zone.y), 3),
                round(float(functional_zone.z), 3),
            ]
            if "functional_zone" in locals() and isinstance(functional_zone, App.Vector)
            else None
        ),
        "section_clutter_rule_id": (policy_hints or {}).get("section_clutter_rule_id"),
        "section_recommended": any(
            bool(candidate.get("section_recommended", False))
            for candidate in (candidate_scores if "candidate_scores" in locals() else [])
            if candidate.get("name") == best_name
        ),
    }
    
    return {
        "front": front_dir,
        "left": left_dir,
        "top": top_dir,
        "iso": iso_dir,
        "view_right": view_right,
        "view_up": view_up,
        "confidence": confidence,
        "debug": debug_info,
    }


def vec_str(v):
    """Format vector for logging."""
    return f"({v.x:.2f},{v.y:.2f},{v.z:.2f})"


def compute_view_directions(shape, points=None, dim_plan=None, feature_payload=None):
    """
    Use First-Angle Projection (ISO/DIN) for view selection.
    
    Returns dictionary with front, left, top, iso directions and debug info.
    """
    points = points or collect_points(shape)
    if len(points) < 3:
        return None
    
    policy_hints = get_dimension_plan_policy_hints(dim_plan)
    result = first_angle_projection(shape, points, policy_hints=policy_hints, feature_payload=feature_payload)
    
    if result is None or result.get("front") is None:
        return None
    
    result["debug"]["method"] = "first_angle_projection"
    result["right"] = result.get("view_right", result["left"].negative())
    
    return result


def derive_view_frame(front_dir):
    forward = snap_axis(front_dir.negative())
    if forward is None:
        return None
    up_hint = App.Vector(0, 0, 1)
    if abs(forward.dot(up_hint)) > 0.9:
        up_hint = App.Vector(0, 1, 0)
    right = normalize_vec(up_hint.cross(forward))
    if right is None:
        return None
    up = normalize_vec(forward.cross(right))
    if up is None:
        return None
    right = snap_axis(right)
    up = snap_axis(up)
    if right is None or up is None:
        return None
    top_dir = up
    iso_basis = normalize_vec(App.Vector(1, 1, 1))
    if iso_basis is None:
        return None
    iso_dir = normalize_vec(
        right.multiply(iso_basis.x).add(up.multiply(iso_basis.y)).add(forward.multiply(iso_basis.z))
    )
    if iso_dir is None:
        return None
    return right, top_dir, iso_dir


def detect_feature_payload(shape, meta):
    raw = meta.get("features")
    if isinstance(raw, dict):
        return raw
    if probe_feature_payload is None:
        return {"ok": False, "error": "feature_probe_unavailable"}
    try:
        payload = probe_feature_payload(shape, source_path=meta.get("input_path"))
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log(f"Feature probe failed in PDF export: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "feature_probe_invalid_payload"}


def _find_helper_python():
    """Locate the venv Python that has pydantic and the DSE installed."""
    server_root = Path(__file__).resolve().parent.parent
    candidates = [
        server_root / ".venv" / "Scripts" / "python.exe",
        server_root.parent / ".venv" / "Scripts" / "python.exe",
        server_root / ".venv" / "bin" / "python",
        server_root.parent / ".venv" / "bin" / "python",
    ]
    return next((str(p) for p in candidates if p.exists()), None)


def build_local_dimension_plan(meta, feature_payload, layout_profile, unfold_result=None):
    if not isinstance(feature_payload, dict) or feature_payload.get("ok") is not True:
        return None
    try:
        detail_level = int((meta or {}).get("detail_level", 1) or 1)
    except (TypeError, ValueError):
        detail_level = 1

    server_root = Path(__file__).resolve().parent.parent
    if str(server_root) not in sys.path:
        sys.path.insert(0, str(server_root))

    try:
        from rules.dimension_strategy import build_dimension_plan as dse_build_dimension_plan
        plan = dse_build_dimension_plan(
            feature_payload=feature_payload,
            layout_profile=layout_profile,
            unfold_result=unfold_result,
            detail_level=detail_level,
        )
    except Exception as exc:
        log(f"Local DSE import/build failed: {exc}")
        payload = {
            "feature_payload": feature_payload,
            "layout_profile": layout_profile,
            "unfold_result": unfold_result,
            "detail_level": detail_level,
        }
        helper_python = _find_helper_python()
        if not helper_python:
            log("No helper Python with DSE dependencies found")
            return None
        helper_script = (
            "import json, sys\n"
            "from rules.dimension_strategy import build_dimension_plan\n"
            "payload = json.load(sys.stdin)\n"
            "plan = build_dimension_plan(\n"
            "    feature_payload=payload['feature_payload'],\n"
            "    layout_profile=payload['layout_profile'],\n"
            "    unfold_result=payload.get('unfold_result'),\n"
            "    detail_level=int(payload.get('detail_level', 1) or 1),\n"
            ")\n"
            "if hasattr(plan, 'model_dump'):\n"
            "    plan = plan.model_dump()\n"
            "json.dump(plan, sys.stdout)\n"
        )
        try:
            result = subprocess.run(
                [helper_python, "-c", helper_script],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                cwd=str(server_root),
                timeout=30,
            )
        except Exception as sub_exc:
            log(f"Local DSE helper subprocess failed: {sub_exc}")
            return None
        if result.returncode != 0:
            err = (result.stderr or "").strip() or f"exit={result.returncode}"
            log(f"Local DSE helper returned error: {err}")
            return None
        try:
            plan = json.loads(result.stdout)
        except json.JSONDecodeError as parse_exc:
            log(f"Local DSE helper produced invalid JSON: {parse_exc}")
            return None

    if hasattr(plan, "model_dump"):
        return plan.model_dump()
    if isinstance(plan, dict):
        return plan
    return None


def _optional_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _looks_like_turning_part(feature_payload, dims):
    """Detect rotational/coaxial parts before sheet-metal heuristics kick in."""
    if not isinstance(feature_payload, dict):
        return False
    if feature_payload.get("rotational_profile") is True:
        return True

    flat_ratio = _optional_float(feature_payload.get("flat_ratio"))
    if flat_ratio is not None and flat_ratio < 0.55:
        return False

    longest_axis = str(feature_payload.get("longest_axis") or "").upper()
    if longest_axis not in {"X", "Y", "Z"}:
        longest_axis = max(dims, key=dims.get) if dims else "X"
    transverse_axes = [axis for axis in ("X", "Y", "Z") if axis != longest_axis]
    if len(transverse_axes) != 2:
        return False

    cross_dims = [max(0.0, float(dims.get(axis, 0.0))) for axis in transverse_axes]
    cross_max = max(cross_dims) if cross_dims else 0.0
    cross_min = min(cross_dims) if cross_dims else 0.0
    if cross_max <= 0.0 or cross_min / cross_max < 0.85:
        return False

    cylindrical_faces = int(
        feature_payload.get("cylinder_face_count")
        or feature_payload.get("cylindrical_face_count")
        or 0
    )
    hole_groups = feature_payload.get("hole_groups") or []
    if cylindrical_faces < 2 or len(hole_groups) < 2:
        return False

    unique_diameters = {
        round(float(group.get("diameter_mm") or 0.0), 3)
        for group in hole_groups
        if _optional_float(group.get("diameter_mm")) not in (None, 0.0)
    }
    if len(unique_diameters) < 2:
        return False

    spans = []
    for axis in transverse_axes:
        key = axis.lower()
        coords = []
        for group in hole_groups:
            center = group.get("center_mm") or {}
            if not isinstance(center, dict):
                return False
            value = _optional_float(center.get(key))
            if value is None:
                return False
            coords.append(value)
        spans.append(max(coords) - min(coords))

    center_tol = max(0.5, cross_max * 0.02)
    return all(span <= center_tol for span in spans)


def _looks_like_compact_flat_milling_part(feature_payload, dims, measured_t):
    """Keep compact plates out of the weak sheet-metal bbox fallback."""
    if not isinstance(feature_payload, dict):
        return False

    flat_ratio = _optional_float(feature_payload.get("flat_ratio"))
    if flat_ratio is not None and flat_ratio >= 0.35:
        return True

    sorted_dims = sorted((max(0.0, float(value)) for value in dims.values()), reverse=True)
    if len(sorted_dims) < 3 or sorted_dims[1] <= 0.0:
        return False

    longest, mid_dim, thickness = sorted_dims[:3]

    # Thick plates (> 8mm) are always milling, regardless of aspect ratio
    if thickness > 8.0:
        return True

    plan_aspect = longest / max(mid_dim, 1e-6)
    thickness_ratio = thickness / max(mid_dim, 1e-6)
    return plan_aspect <= 1.35 and thickness_ratio >= 0.08


def format_de_number(value, decimals=1):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:.{decimals}f}".replace(".", ",")


def sheet_spec(sheet_name):
    normalized = str(sheet_name or "A3").strip().upper()
    if normalized not in SHEET_SPECS:
        normalized = "A3"
    spec = dict(SHEET_SPECS[normalized])
    spec["name"] = normalized
    return spec


def resolve_requested_sheet(meta):
    value = str((meta or {}).get("sheet") or "").strip().upper()
    if value in {"A2", "A3"}:
        return value
    return "auto"


def _legacy_select_layout_profile(input_path, feature_payload, dim_x, dim_y, dim_z):
    lower_input = str(input_path or "").lower()

    # Tier 0: Explicit path-based override (backward compatible)
    if "sheetmetals" in lower_input or "sheetmetal" in lower_input:
        return "sheet_metal"

    if isinstance(feature_payload, dict):
        measured_t = _optional_float(feature_payload.get("measured_thickness_mm"))
        dims = {"X": float(dim_x), "Y": float(dim_y), "Z": float(dim_z)}

        # Guard before sheet-metal tiers:
        # coaxial multi-diameter cylinders can look like "bent" geometry to the
        # lightweight probe, but produce implausible flat-pattern drawings.
        if _looks_like_turning_part(feature_payload, dims):
            return "turning"

        pocket_count = int(_optional_float(feature_payload.get("pocket_count")) or 0)
        blind_hole_count = int(_optional_float(feature_payload.get("blind_hole_count")) or 0)
        if pocket_count > 0 or blind_hole_count > 0:
            return "milling"

        if _looks_like_compact_flat_milling_part(feature_payload, dims, measured_t):
            return "milling"

        # Tier 1 (PRIMARY): Face-type geometry classification from feature probe.
        # Sheet metal = predominantly Plane faces + at least one Cylinder (bend zone)
        # + no complex machined surfaces (cones, tori indicate turning/milling).
        # Thickness guard (≤5mm): thick milling parts with fillets also have many
        # Plane faces, so we require a measurably thin wall before accepting Tier 1.
        if (feature_payload.get("is_sheet_metal_by_faces") is True
                and measured_t is not None and measured_t <= 5.0):
            return "sheet_metal"

        # Tier 1.5: Probe detected bend geometry — strongest sheet metal signal.
        # The probe's edge-based bend detector (50% circumference filter) already
        # rejects milling fillets/chamfers. If bends are found, they're real bends.
        # No cone_count or thickness guard needed: bent parts may have chamfered
        # edges (cone faces) and measured_thickness_mm can be wrong on complex
        # bent parts (it may measure the bend height instead of wall thickness).
        fp = feature_payload.get("flat_pattern") or {}
        probe_bend_count = int(fp.get("bend_count") or 0)
        if probe_bend_count > 0:
            return "sheet_metal"

        # Tier 2: Measured wall thickness < 5mm (typical sheet metal range) combined
        # with flat bbox (flat parts without bends = laser cut).
        # Guard: pocket_ratio — if bbox_min >> measured_t, it's a pocket, not wall.
        # Guard: cone faces — fillets/chamfers indicate milling.
        if measured_t is not None and 0.3 <= measured_t <= 5.0:
            cone_count = int(feature_payload.get("cone_face_count") or 0)
            if cone_count == 0:
                bbox_min_dim = min(float(dim_x), float(dim_y), float(dim_z))
                pocket_ratio = bbox_min_dim / max(measured_t, 0.01)
                if pocket_ratio <= 3.0:
                    flat_ratio = _optional_float(feature_payload.get("flat_ratio"))
                    if flat_ratio is not None and flat_ratio < 0.7:
                        return "sheet_metal"

        # Tier 3 (FALLBACK): BBox ratio with tighter threshold (was 0.25, now 0.15).
        # Prevents thick milling parts from being misclassified.
        # Guard: absolute thickness > 8mm is never sheet metal (max ~6mm in practice)
        bbox_min_dim = min(float(dim_x), float(dim_y), float(dim_z))
        if bbox_min_dim > 8.0:
            return "milling"
        # Guard: cone faces (chamfers/fillets) are a strong milling indicator.
        cone_count_t3 = int(feature_payload.get("cone_face_count") or 0)
        if cone_count_t3 == 0:
            thickness_axis = str(feature_payload.get("thickness_axis") or "").upper()
            thickness = dims.get(thickness_axis, min(dims.values()))
            mid_dim = sorted(dims.values(), reverse=True)[1]
            if mid_dim > 0 and thickness / mid_dim < 0.15:
                return "sheet_metal"

    return "milling"


def _subprocess_layout_profile(input_path, feature_payload):
    """Call select_layout_profile_standalone via subprocess helper (venv Python).

    This avoids the pydantic import problem in FreeCAD's bundled Python and
    ensures a single source of truth for layout classification.
    """
    helper_python = _find_helper_python()
    if not helper_python:
        return None
    server_root = Path(__file__).resolve().parent.parent
    helper_script = (
        "import json, sys\n"
        "from rules.dimension_strategy import select_layout_profile_standalone\n"
        "payload = json.load(sys.stdin)\n"
        "result = select_layout_profile_standalone(payload['input_path'], payload['feature_payload'])\n"
        "print(result)\n"
    )
    try:
        result = subprocess.run(
            [helper_python, "-c", helper_script],
            input=json.dumps({"input_path": str(input_path), "feature_payload": feature_payload}),
            capture_output=True,
            text=True,
            cwd=str(server_root),
            timeout=10,
        )
        if result.returncode == 0:
            profile = result.stdout.strip()
            if profile in ("milling", "sheet_metal", "turning"):
                return profile
        err = (result.stderr or "").strip()
        log(f"Layout classifier subprocess returned error: {err or f'exit={result.returncode}'}")
    except Exception as exc:
        log(f"Layout classifier subprocess failed: {exc}")
    return None


def select_layout_profile(input_path, feature_payload, dim_x, dim_y, dim_z):
    """Resolve the layout profile via the shared DSE classifier.

    Primary path: subprocess helper calling select_layout_profile_standalone()
    from dimension_strategy.py (single source of truth, uses venv Python).
    Fallback: legacy local implementation (only when subprocess is unavailable).
    """
    if isinstance(feature_payload, dict) and isinstance(feature_payload.get("bbox_mm"), dict):
        profile = _subprocess_layout_profile(input_path, feature_payload)
        if profile is not None:
            return profile
        log("Subprocess classifier unavailable, falling back to legacy path")

    return _legacy_select_layout_profile(input_path, feature_payload, dim_x, dim_y, dim_z)


def detect_flat_pattern_mode(layout_profile):
    if layout_profile != "sheet_metal":
        return "not_applicable"
    for module_name in ("SheetMetal", "SheetMetalCmd", "SheetMetalUnfolder", "SMUnfold"):
        try:
            __import__(module_name)
            return "sheetmetal_module"
        except (ImportError, ModuleNotFoundError):
            continue
    return "fallback_projected"


def compute_layout_usage(views_bbox, draw_bbox):
    views_w = max(0.0, float(views_bbox.get("right", 0.0)) - float(views_bbox.get("left", 0.0)))
    views_h = max(0.0, float(views_bbox.get("bottom", 0.0)) - float(views_bbox.get("top", 0.0)))
    draw_w = max(1e-6, float(draw_bbox.get("right", 0.0)) - float(draw_bbox.get("left", 0.0)))
    draw_h = max(1e-6, float(draw_bbox.get("bottom", 0.0)) - float(draw_bbox.get("top", 0.0)))
    return (views_w / draw_w) * (views_h / draw_h)


def feature_dimension_density_score(view_name, dim_plan=None, feature_payload=None):
    feature_types = (
        feature_dimension_types_for_view(
            view_name,
            dim_plan=dim_plan,
            feature_payload=feature_payload,
        )
        if dim_plan
        else set()
    )
    hole_count = int(_optional_float((feature_payload or {}).get("hole_count")) or 0)
    score = len(feature_types)
    if {"hole_location_x", "hole_location_y"} <= set(feature_types):
        score += 1
    if "hole_pitch" in feature_types:
        score += 1
    if hole_count >= 4 and feature_types:
        score += 1
    if hole_count >= 8 and feature_types:
        score += 1
    return score


def view_requires_layout_escalation(view_name, dim_plan=None, feature_payload=None, policy_hints=None):
    if str(view_name or "") != "Front":
        return False
    if not isinstance(policy_hints, dict) or not policy_hints.get("escalate_layout_for_dimension_density"):
        return False
    feature_types = (
        feature_dimension_types_for_view(
            view_name,
            dim_plan=dim_plan,
            feature_payload=feature_payload,
        )
        if dim_plan
        else set()
    )
    hole_count = int(_optional_float((feature_payload or {}).get("hole_count")) or 0)
    density_score = feature_dimension_density_score(view_name, dim_plan=dim_plan, feature_payload=feature_payload)
    return density_score >= 6 and (hole_count >= 10 or "thread_callout" in feature_types)


def view_prefers_detail_escalation(view_name, dim_plan=None, feature_payload=None, policy_hints=None):
    if str(view_name or "") != "Front":
        return False
    if not isinstance(policy_hints, dict) or not policy_hints.get("prefer_detail_views_for_dense_features"):
        return False
    feature_types = (
        feature_dimension_types_for_view(
            view_name,
            dim_plan=dim_plan,
            feature_payload=feature_payload,
        )
        if dim_plan
        else set()
    )
    hole_count = int(_optional_float((feature_payload or {}).get("hole_count")) or 0)
    density_score = feature_dimension_density_score(view_name, dim_plan=dim_plan, feature_payload=feature_payload)
    return density_score >= 7 and (hole_count >= 12 or ("thread_callout" in feature_types and hole_count >= 8))


def select_view_layout_variant(layout_profile, sheet_metal_subtype, feature_payload, dim_x, dim_y, dim_z, dim_plan=None):
    policy_hints = get_dimension_plan_policy_hints(dim_plan)
    if layout_profile == "sheet_metal" and sheet_metal_subtype == "biegeteil":
        return "sheet_bent"

    dims = sorted([float(dim_x), float(dim_y), float(dim_z)], reverse=True)
    mid_dim = max(dims[1], 0.1)
    thickness_ratio = dims[2] / mid_dim
    is_flat = bool((feature_payload or {}).get("is_flat")) or thickness_ratio < 0.22
    round_span = max(float(dim_x), float(dim_z), 0.1)
    roundish_front = abs(float(dim_x) - float(dim_z)) / round_span < 0.12

    if is_flat and roundish_front:
        return "flat_round_dominant"
    if is_flat:
        return "flat_dominant"
    return "grid_2x2"


def build_view_slots(layout_variant, origin_x, origin_y, avail_w, avail_h):
    if layout_variant == "sheet_bent":
        views_w = avail_w * 0.60
        gap = 8.0
        aux_w = min(max(48.0, views_w * 0.26), views_w * 0.34)
        bottom_h = min(max(34.0, avail_h * 0.22), avail_h * 0.30)
        front_w = max(70.0, views_w - aux_w - gap)
        front_h = max(70.0, avail_h - bottom_h - gap)
        left_h = max(46.0, front_h * 0.62)
        iso_h = max(34.0, avail_h - left_h - gap)
        return {
            "Front": {"w": front_w, "h": front_h, "cx": origin_x + front_w * 0.5, "cy": origin_y + front_h * 0.5, "enabled": True},
            "Left": {"w": aux_w, "h": left_h, "cx": origin_x + front_w + gap + aux_w * 0.5, "cy": origin_y + left_h * 0.5, "enabled": True},
            "Top": {"w": front_w, "h": bottom_h, "cx": origin_x + front_w * 0.5, "cy": origin_y + front_h + gap + bottom_h * 0.5, "enabled": True},
            "Iso": {"w": aux_w, "h": iso_h, "cx": origin_x + front_w + gap + aux_w * 0.5, "cy": origin_y + left_h + gap + iso_h * 0.5, "enabled": True},
        }

    if layout_variant == "flat_round_dominant":
        gap = 8.0
        bottom_h = min(32.0, max(26.0, avail_h * 0.13))
        iso_w = min(92.0, max(74.0, avail_w * 0.20))
        front_span = min(avail_h - bottom_h - gap, avail_w - iso_w - gap)
        front_span = max(front_span, min(avail_w * 0.42, avail_h * 0.60))
        iso_h = min(max(38.0, iso_w * 0.68), avail_h * 0.32)
        iso_w = min(iso_w, max(40.0, avail_w - front_span - gap))
        return {
            "Front": {
                "w": front_span,
                "h": front_span,
                "cx": origin_x + front_span * 0.5,
                "cy": origin_y + front_span * 0.5,
                "enabled": True,
            },
            "Left": {
                "w": 0.0,
                "h": 0.0,
                "cx": origin_x + front_span * 0.5,
                "cy": origin_y + front_span * 0.5,
                "enabled": False,
            },
            "Top": {
                "w": front_span,
                "h": bottom_h,
                "cx": origin_x + front_span * 0.5,
                "cy": origin_y + front_span + gap + bottom_h * 0.5,
                "enabled": True,
            },
            "Iso": {
                "w": iso_w,
                "h": iso_h,
                "cx": origin_x + front_span + gap + iso_w * 0.5,
                "cy": origin_y + avail_h - iso_h * 0.5,
                "enabled": True,
            },
        }

    if layout_variant == "flat_dominant":
        gap = 8.0
        side_w = min(max(62.0, avail_w * 0.22), avail_w * 0.28)
        bottom_h = min(max(28.0, avail_h * 0.16), avail_h * 0.24)
        front_w = max(70.0, avail_w - side_w - gap)
        front_h = max(70.0, avail_h - bottom_h - gap)
        left_h = max(42.0, front_h * 0.62)
        iso_h = max(28.0, avail_h - left_h - gap)
        return {
            "Front": {"w": front_w, "h": front_h, "cx": origin_x + front_w * 0.5, "cy": origin_y + front_h * 0.5, "enabled": True},
            "Left": {"w": side_w, "h": left_h, "cx": origin_x + front_w + gap + side_w * 0.5, "cy": origin_y + left_h * 0.5, "enabled": True},
            "Top": {"w": front_w, "h": bottom_h, "cx": origin_x + front_w * 0.5, "cy": origin_y + front_h + gap + bottom_h * 0.5, "enabled": True},
            "Iso": {"w": side_w, "h": iso_h, "cx": origin_x + front_w + gap + side_w * 0.5, "cy": origin_y + left_h + gap + iso_h * 0.5, "enabled": True},
        }

    cell_w = avail_w / 2.0
    cell_h = avail_h / 2.0
    return {
        "Front": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 0.5, "cy": origin_y + cell_h * 0.5, "enabled": True},
        "Left": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 1.5, "cy": origin_y + cell_h * 0.5, "enabled": True},
        "Top": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 0.5, "cy": origin_y + cell_h * 1.5, "enabled": True},
        "Iso": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 1.5, "cy": origin_y + cell_h * 1.5, "enabled": True},
    }


def should_promote_to_a2(report, dim_x, dim_y, dim_z, *, requested_sheet, dim_plan=None):
    if str(requested_sheet or "").lower() != "auto":
        return False
    quality = (report or {}).get("quality", {})
    overflow_max = _optional_float(((quality.get("overflow_mm") or {}).get("max"))) or 0.0
    if overflow_max > 0.5:
        return True
    policy_hints = get_dimension_plan_policy_hints(dim_plan)
    dim_metrics = ((report or {}).get("pre_export_check") or {}).get("dim_metrics") or {}
    if policy_hints.get("escalate_layout_for_dimension_density"):
        report_views = {
            name: view
            for name, view in ((report or {}).get("views") or {}).items()
            if isinstance(view, dict)
        }
        detail_view_recommended = any(
            bool((view or {}).get("detail_view_recommended", False))
            for view in report_views.values()
        )
        outside_preferred_feature_views = any(
            bool((view or {}).get("feature_dim_outside_preferred"))
            and int(_optional_float((view or {}).get("feature_dim_text_count")) or 0) > 0
            for view in report_views.values()
        )
        out_of_bounds_in_report = any(
            not bool((view or {}).get("labels_fit_inside_drawing_area", True))
            or not bool((view or {}).get("dimensions_fit_inside_drawing_area", True))
            or (_optional_float(((view or {}).get("label_overflow_mm") or {}).get("max")) or 0.0) > 0.5
            or (_optional_float(((view or {}).get("dimension_overflow_mm") or {}).get("max")) or 0.0) > 0.5
            for view in report_views.values()
        )
        if (
            (
                detail_view_recommended
                or outside_preferred_feature_views
                or bool(dim_metrics.get("outside_preferred_feature_views"))
            )
            and (
                out_of_bounds_in_report
                or
                not bool(dim_metrics.get("labels_in_bounds", True))
                or not bool(dim_metrics.get("dimension_graphics_in_bounds", True))
            )
        ):
            return True
    draw_bbox = quality.get("drawing_area") or {}
    views_bbox = quality.get("views_bbox") or {}
    usage = compute_layout_usage(views_bbox, draw_bbox)
    max_dim = max(float(dim_x), float(dim_y), float(dim_z))
    scale = _optional_float((report or {}).get("scale")) or 1.0
    if max_dim >= 500.0 and scale < 0.12:
        return True
    return max_dim >= 500.0 and usage < 0.24


def estimate_sheet_thickness(feature_payload, dim_x, dim_y, dim_z):
    # Prefer geometry-derived measurement (face pair distance) over bbox heuristics.
    measured = _optional_float((feature_payload or {}).get("measured_thickness_mm"))
    if measured is not None and 0.3 <= measured <= 10.0:
        return measured
    dims = {"X": float(dim_x), "Y": float(dim_y), "Z": float(dim_z)}
    axis = str((feature_payload or {}).get("thickness_axis") or "").upper()
    if axis in dims:
        return dims[axis]
    return min(dims.values())


def build_feature_annotation_lines(feature_payload, layout_profile="milling"):
    """
    Returns manufacturing notes for the annotation block (bottom-left of drawing).

    - milling: empty list — all feature info appears as callout leaders in the drawing.
    - sheet_metal: only K-factor and deburring note (thickness is in process_lines).
    """
    if not isinstance(feature_payload, dict):
        return []
    if feature_payload.get("ok") is not True:
        return []  # suppress error messages from the annotation block

    if layout_profile == "sheet_metal":
        # K-Faktor is already listed in process_lines — only deburring note here.
        return ["Scharfe Kanten entgraten"]

    # milling: no free-text block — feature dimensions appear as callout annotations
    return []


def extract_svg_circles(svg_group):
    circles = []
    for circle in re.findall(r"<circle[^>]+>", svg_group):
        cx_match = re.search(r'cx\s*=\s*"([^"]+)"', circle)
        cy_match = re.search(r'cy\s*=\s*"([^"]+)"', circle)
        r_match = re.search(r'\br\s*=\s*"([^"]+)"', circle)
        if not (cx_match and cy_match and r_match):
            continue
        try:
            cx = float(cx_match.group(1))
            cy = float(cy_match.group(1))
            radius = abs(float(r_match.group(1)))
        except (TypeError, ValueError):
            continue
        if radius > 1e-6:
            circles.append({"cx": cx, "cy": cy, "r": radius})
    return circles


def _parse_svg_path_arcs(path_data):
    tokens = SVG_PATH_TOKEN_RE.findall(path_data)
    if not tokens:
        return []

    arcs = []
    index = 0
    cmd = None
    cx = 0.0
    cy = 0.0
    sx = None
    sy = None

    def is_cmd(token):
        return token in SVG_PATH_COMMANDS

    while index < len(tokens):
        token = tokens[index]
        if is_cmd(token):
            cmd = token
            index += 1
        elif cmd is None:
            index += 1
            continue

        try:
            if cmd in ("M", "m"):
                first_move = True
                while index + 1 < len(tokens) and not is_cmd(tokens[index]):
                    x = float(tokens[index])
                    y = float(tokens[index + 1])
                    index += 2
                    if cmd == "m":
                        x += cx
                        y += cy
                    cx, cy = x, y
                    if first_move:
                        sx, sy = cx, cy
                        first_move = False
                continue

            if cmd in ("L", "l"):
                while index + 1 < len(tokens) and not is_cmd(tokens[index]):
                    x = float(tokens[index])
                    y = float(tokens[index + 1])
                    index += 2
                    if cmd == "l":
                        x += cx
                        y += cy
                    cx, cy = x, y
                continue

            if cmd in ("H", "h"):
                while index < len(tokens) and not is_cmd(tokens[index]):
                    x = float(tokens[index])
                    index += 1
                    if cmd == "h":
                        x += cx
                    cx = x
                continue

            if cmd in ("V", "v"):
                while index < len(tokens) and not is_cmd(tokens[index]):
                    y = float(tokens[index])
                    index += 1
                    if cmd == "v":
                        y += cy
                    cy = y
                continue

            if cmd in ("C", "c"):
                while index + 5 < len(tokens) and not is_cmd(tokens[index]):
                    x = float(tokens[index + 4])
                    y = float(tokens[index + 5])
                    index += 6
                    if cmd == "c":
                        x += cx
                        y += cy
                    cx, cy = x, y
                continue

            if cmd in ("S", "s"):
                while index + 3 < len(tokens) and not is_cmd(tokens[index]):
                    x = float(tokens[index + 2])
                    y = float(tokens[index + 3])
                    index += 4
                    if cmd == "s":
                        x += cx
                        y += cy
                    cx, cy = x, y
                continue

            if cmd in ("Q", "q"):
                while index + 3 < len(tokens) and not is_cmd(tokens[index]):
                    x = float(tokens[index + 2])
                    y = float(tokens[index + 3])
                    index += 4
                    if cmd == "q":
                        x += cx
                        y += cy
                    cx, cy = x, y
                continue

            if cmd in ("T", "t"):
                while index + 1 < len(tokens) and not is_cmd(tokens[index]):
                    x = float(tokens[index])
                    y = float(tokens[index + 1])
                    index += 2
                    if cmd == "t":
                        x += cx
                        y += cy
                    cx, cy = x, y
                continue

            if cmd in ("A", "a"):
                while index + 6 < len(tokens) and not is_cmd(tokens[index]):
                    rx = abs(float(tokens[index]))
                    ry = abs(float(tokens[index + 1]))
                    xrot = float(tokens[index + 2])
                    large_arc = int(abs(float(tokens[index + 3])) >= 0.5)
                    sweep = int(abs(float(tokens[index + 4])) >= 0.5)
                    x = float(tokens[index + 5])
                    y = float(tokens[index + 6])
                    index += 7
                    start_x = cx
                    start_y = cy
                    if cmd == "a":
                        x += cx
                        y += cy
                    arcs.append(
                        {
                            "start_x": start_x,
                            "start_y": start_y,
                            "end_x": x,
                            "end_y": y,
                            "rx": rx,
                            "ry": ry,
                            "xrot": xrot,
                            "large_arc": large_arc,
                            "sweep": sweep,
                        }
                    )
                    cx, cy = x, y
                continue

            if cmd in ("Z", "z"):
                if sx is not None and sy is not None:
                    cx, cy = sx, sy
                continue
        except (TypeError, ValueError):
            # Malformed path chunk: consume one token and continue safely.
            index += 1
            continue

        index += 1

    return arcs


def _normalize_arc_delta(start_angle, end_angle, sweep_flag):
    delta = end_angle - start_angle
    if sweep_flag:
        while delta < 0.0:
            delta += 2.0 * math.pi
    else:
        while delta > 0.0:
            delta -= 2.0 * math.pi
    return delta


def _resolve_circular_arc_center(arc):
    rx = abs(float(arc.get("rx", 0.0)))
    ry = abs(float(arc.get("ry", 0.0)))
    if rx <= 1e-6 or ry <= 1e-6:
        return None
    circle_tol = max(0.2, max(rx, ry) * 0.08)
    if abs(rx - ry) > circle_tol:
        return None
    radius = (rx + ry) * 0.5

    x1 = float(arc.get("start_x", 0.0))
    y1 = float(arc.get("start_y", 0.0))
    x2 = float(arc.get("end_x", 0.0))
    y2 = float(arc.get("end_y", 0.0))
    dx = x2 - x1
    dy = y2 - y1
    chord = math.hypot(dx, dy)
    if chord <= 1e-8:
        return None

    if chord > (2.0 * radius + 0.6):
        return None
    radius = max(radius, chord * 0.5)

    half = chord * 0.5
    h_sq = radius * radius - half * half
    if h_sq < -1e-6:
        return None
    height = math.sqrt(max(0.0, h_sq))

    mx = (x1 + x2) * 0.5
    my = (y1 + y2) * 0.5
    ux = -dy / chord
    uy = dx / chord
    candidates = [
        (mx + ux * height, my + uy * height),
        (mx - ux * height, my - uy * height),
    ]

    want_large = int(arc.get("large_arc", 0))
    sweep_flag = int(arc.get("sweep", 0))
    best = None
    best_penalty = None
    for cx, cy in candidates:
        start_ang = math.atan2(y1 - cy, x1 - cx)
        end_ang = math.atan2(y2 - cy, x2 - cx)
        delta = _normalize_arc_delta(start_ang, end_ang, sweep_flag)
        sweep_abs = abs(delta)
        penalty = 0.0
        if want_large and sweep_abs < math.pi:
            penalty += (math.pi - sweep_abs)
        if (not want_large) and sweep_abs > math.pi:
            penalty += (sweep_abs - math.pi)
        penalty += abs(math.hypot(x1 - cx, y1 - cy) - radius) * 0.15
        penalty += abs(math.hypot(x2 - cx, y2 - cy) - radius) * 0.15
        if best_penalty is None or penalty < best_penalty:
            best_penalty = penalty
            best = (cx, cy, sweep_abs)
    if best is None:
        return None
    cx, cy, sweep_abs = best
    return {"cx": cx, "cy": cy, "r": radius, "sweep_abs": sweep_abs}


def extract_svg_arc_circles(svg_group):
    circles = []
    grouped = {}
    for path_data in re.findall(r'd="([^"]+)"', svg_group):
        for arc in _parse_svg_path_arcs(path_data):
            resolved = _resolve_circular_arc_center(arc)
            if not resolved:
                continue
            # Do not treat single 180° slot-end arcs as standalone circular holes.
            # Real circles are emitted either as <circle> elements or as multiple arcs
            # whose grouped sweep exceeds ~360°.
            if float(resolved["sweep_abs"]) >= math.radians(320.0):
                circles.append(
                    {
                        "cx": float(resolved["cx"]),
                        "cy": float(resolved["cy"]),
                        "r": float(resolved["r"]),
                    }
                )
            radius = float(resolved["r"])
            tol = max(0.2, radius * 0.03)
            key = (
                round(float(resolved["cx"]) / tol),
                round(float(resolved["cy"]) / tol),
                round(radius / tol),
            )
            bucket = grouped.setdefault(
                key,
                {"cx": 0.0, "cy": 0.0, "r": 0.0, "sweep_abs": 0.0, "count": 0},
            )
            bucket["cx"] += float(resolved["cx"])
            bucket["cy"] += float(resolved["cy"])
            bucket["r"] += radius
            bucket["sweep_abs"] += min(float(resolved["sweep_abs"]), 2.0 * math.pi)
            bucket["count"] += 1
    for bucket in grouped.values():
        if int(bucket.get("count") or 0) <= 0:
            continue
        total_sweep = float(bucket.get("sweep_abs") or 0.0)
        # Accept circles reconstructed from multiple smaller arcs. This captures
        # outer round contours emitted as 4x90° segments, while rejecting fillets.
        if total_sweep < math.radians(300.0):
            continue
        count = float(bucket["count"])
        circles.append(
            {
                "cx": bucket["cx"] / count,
                "cy": bucket["cy"] / count,
                "r": bucket["r"] / count,
            }
        )
    return circles


def _dedupe_circle_candidates(candidates, center_tol=0.2, radius_tol=0.2):
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda item: item.get("r", 0.0), reverse=True)
    deduped = []
    for circle in ordered:
        cx = float(circle.get("cx", 0.0))
        cy = float(circle.get("cy", 0.0))
        radius = abs(float(circle.get("r", 0.0)))
        if radius <= 1e-6:
            continue
        duplicate = False
        for picked in deduped:
            ctol = max(center_tol, picked["r"] * 0.03, radius * 0.03)
            rtol = max(radius_tol, picked["r"] * 0.03, radius * 0.03)
            if abs(cx - picked["cx"]) <= ctol and abs(cy - picked["cy"]) <= ctol and abs(radius - picked["r"]) <= rtol:
                duplicate = True
                break
        if not duplicate:
            deduped.append({"cx": cx, "cy": cy, "r": radius})
    return deduped


def extract_svg_circular_features(svg_group):
    circles = []
    circles.extend(extract_svg_circles(svg_group))
    circles.extend(extract_svg_arc_circles(svg_group))
    return _dedupe_circle_candidates(circles)


def count_svg_circles(svg_group):
    return len(extract_svg_circular_features(svg_group))


def _select_centerline_circles(circles, scale, limit=12):
    if not circles:
        return []
    ordered = sorted(circles, key=lambda item: item["r"], reverse=True)
    center_tol = max(0.2, 0.8 / max(scale, 0.1))
    radius_tol = max(0.15, 0.5 / max(scale, 0.1))

    deduped = []
    for circle in ordered:
        duplicate = False
        for picked in deduped:
            if (
                abs(circle["cx"] - picked["cx"]) <= center_tol
                and abs(circle["cy"] - picked["cy"]) <= center_tol
                and abs(circle["r"] - picked["r"]) <= radius_tol
            ):
                duplicate = True
                break
        if not duplicate:
            deduped.append(circle)

    if not deduped:
        return []
    max_radius = max(item["r"] for item in deduped)
    min_radius = max(0.05, 0.25 / max(scale, 0.1), max_radius * 0.03)
    selected = [item for item in deduped if item["r"] >= min_radius]
    return selected[:limit]


def _project_feature_centerline_targets(
    feature_payload,
    direction,
    scale,
    limit=12,
    *,
    allow_nonflat=False,
):
    if not isinstance(feature_payload, dict):
        return []
    flat_pattern = feature_payload.get("flat_pattern") or {}
    if (
        not allow_nonflat
        and not bool(feature_payload.get("is_flat"))
        and feature_payload.get("is_sheet_metal_by_faces") is not True
        and int(flat_pattern.get("bend_count") or 0) <= 0
    ):
        return []
    hole_groups = feature_payload.get("hole_groups") or []
    basis = view_basis(direction)
    if not hole_groups or basis is None:
        return []
    right, up = basis
    projected = []
    fallback_dia = _optional_float(feature_payload.get("hole_diameter_mm"))
    for group in hole_groups:
        if not isinstance(group, dict):
            continue
        center = group.get("center_mm") or {}
        if not isinstance(center, dict):
            continue
        cx = _optional_float(center.get("x"))
        cy = _optional_float(center.get("y"))
        cz = _optional_float(center.get("z"))
        diameter = _optional_float(group.get("diameter_mm"))
        diameter = diameter if diameter and diameter > 0 else fallback_dia
        if None in (cx, cy, cz) or diameter is None or diameter <= 0:
            continue
        point = App.Vector(float(cx), float(cy), float(cz))
        projected.append(
            {
                "cx": float(point.dot(right)),
                "cy": float(point.dot(up)),
                "r": max(0.05, float(diameter) * 0.5),
            }
        )
    return _select_centerline_circles(projected, scale, limit=limit)


def build_centerline_svg(
    svg_group,
    scale,
    stroke_width,
    limit=12,
    line_profile=None,
    feature_payload=None,
    direction=None,
    allow_projected_feature_targets=False,
):
    """
    Build ISO-128 style centerlines (chain thin) for circular features.
    """
    circles = extract_svg_circular_features(svg_group)
    targets = _select_centerline_circles(circles, scale, limit=limit)
    source = "visible" if targets else "none"
    if not targets and direction is not None and isinstance(feature_payload, dict):
        targets = _project_feature_centerline_targets(
            feature_payload,
            direction,
            scale,
            limit=limit,
            allow_nonflat=allow_projected_feature_targets,
        )
        if targets:
            source = "projected"
    if not targets:
        return "", 0, "none"

    thin_stroke = max(0.0006, stroke_width * 0.45)
    dash_pattern = None
    if isinstance(line_profile, dict):
        thin_stroke = max(0.0006, float(line_profile.get("centerline", thin_stroke)))
        dash_pattern = str(line_profile.get("center_dash", "")).strip() or None
    ext = max(1.5, 3.2 / max(scale, 0.05))
    if not dash_pattern:
        dash_long = max(1.0, 5.0 / max(scale, 0.05))
        dash_gap = max(0.5, 2.0 / max(scale, 0.05))
        dash_short = max(0.5, 1.2 / max(scale, 0.05))
        dash_pattern = f"{dash_long:.3f} {dash_gap:.3f} {dash_short:.3f} {dash_gap:.3f}"

    parts = [
        f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{thin_stroke:.4f}" '
        f'stroke-linecap="butt" stroke-linejoin="miter" stroke-dasharray="{dash_pattern}">'
    ]
    for circle in targets:
        cx = circle["cx"]
        cy = circle["cy"]
        radius = circle["r"]
        h0 = cx - radius - ext
        h1 = cx + radius + ext
        v0 = cy - radius - ext
        v1 = cy + radius + ext
        parts.append(f'<line x1="{h0:.3f}" y1="{cy:.3f}" x2="{h1:.3f}" y2="{cy:.3f}" />')
        parts.append(f'<line x1="{cx:.3f}" y1="{v0:.3f}" x2="{cx:.3f}" y2="{v1:.3f}" />')
    parts.append("</g>")
    return "".join(parts), len(targets), source


def _reserve_feature_label_y(preferred_y, used_positions, min_gap, min_y, max_y):
    y = preferred_y
    for _ in range(12):
        if all(abs(y - other) >= min_gap for other in used_positions):
            used_positions.append(y)
            return y
        y += min_gap
        if y > max_y - min_gap:
            y = preferred_y - min_gap
            if y < min_y + min_gap:
                y = min_y + min_gap
    clamped = max(min_y + min_gap, min(max_y - min_gap, y))
    used_positions.append(clamped)
    return clamped


def _bbox_overlaps(box_a, box_b, margin=0.0):
    if box_a is None or box_b is None:
        return False
    return not (
        (box_a[1] + margin) < box_b[0]
        or (box_b[1] + margin) < box_a[0]
        or (box_a[3] + margin) < box_b[2]
        or (box_b[3] + margin) < box_a[2]
    )


def _line_collision_box(x1, y1, x2, y2, pad):
    return (
        min(x1, x2) - pad,
        max(x1, x2) + pad,
        min(y1, y2) - pad,
        max(y1, y2) + pad,
    )


def _text_collision_box(text, x, y, text_size, anchor):
    width = max(text_size * 1.6, text_size * 0.58 * max(1, len(str(text))))
    height = max(text_size * 1.15, 0.4)
    if anchor == "start":
        left = x
    elif anchor == "end":
        left = x - width
    else:
        left = x - width * 0.5
    right = left + width
    bottom = y - height * 0.30
    top = y + height * 0.85
    return (left, right, bottom, top)


def _normalize_collision_box(box):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        left, right, bottom, top = [float(value) for value in box]
    except (TypeError, ValueError):
        return None
    return (
        min(left, right),
        max(left, right),
        min(bottom, top),
        max(bottom, top),
    )


def _append_unique_collision_box(boxes, box):
    normalized_box = _normalize_collision_box(box)
    if normalized_box is None:
        return None
    if isinstance(boxes, list) and normalized_box not in boxes:
        boxes.append(normalized_box)
    return normalized_box


def _get_shared_collision_boxes(metadata):
    if not isinstance(metadata, dict):
        return None
    shared_boxes = metadata.setdefault("_shared_collision_boxes", [])
    return shared_boxes if isinstance(shared_boxes, list) else None


def _record_dimension_entry(metadata, bucket, *, dim_type, axis, style, outside, measurement_box=None, text_box=None):
    if not isinstance(metadata, dict):
        return
    normalized_measurement_box = _normalize_collision_box(measurement_box)
    normalized_text_box = _normalize_collision_box(text_box)
    metadata.setdefault(bucket, []).append(
        {
            "dim_type": str(dim_type or ""),
            "axis": axis,
            "style": str(style or "line"),
            "outside": bool(outside),
            "measurement_box": normalized_measurement_box,
            "text_box": normalized_text_box,
        }
    )
    shared_boxes = _get_shared_collision_boxes(metadata)
    if shared_boxes is not None:
        if normalized_measurement_box is not None:
            _append_unique_collision_box(shared_boxes, normalized_measurement_box)
        if normalized_text_box is not None:
            _append_unique_collision_box(shared_boxes, normalized_text_box)


def _reserve_feature_label_position(
    text,
    x,
    preferred_y,
    text_size,
    anchor,
    used_positions,
    min_gap,
    min_y,
    max_y,
    collision_boxes,
    paper_box_resolver=None,
):
    margin = max(0.15, text_size * 0.15)
    paper_margin = margin
    if callable(paper_box_resolver):
        paper_margin = max(margin, text_size * 0.4)
    base = max(min_y + text_size, min(max_y - text_size, preferred_y))
    offsets = [0.0]
    max_steps = 16 if callable(paper_box_resolver) else 10
    for step in range(1, max_steps):
        delta = step * min_gap
        offsets.append(delta)
        offsets.append(-delta)

    def _position_is_free(y):
        if any(abs(y - other) < min_gap * 0.85 for other in used_positions):
            return False
        bbox = _text_collision_box(text, x, y, text_size, anchor)
        if any(_bbox_overlaps(bbox, box, margin=margin) for box in collision_boxes):
            return False
        if callable(paper_box_resolver):
            paper_bbox = paper_box_resolver(bbox)
            if paper_bbox is not None:
                for collision_box in collision_boxes:
                    paper_collision_box = paper_box_resolver(collision_box)
                    if paper_collision_box is not None and _bbox_overlaps(
                        paper_bbox, paper_collision_box, margin=paper_margin
                    ):
                        return False
        return True

    for offset in offsets:
        y = max(min_y + text_size, min(max_y - text_size, base + offset))
        if not _position_is_free(y):
            continue
        bbox = _text_collision_box(text, x, y, text_size, anchor)
        used_positions.append(y)
        collision_boxes.append(bbox)
        return y
    if callable(paper_box_resolver):
        sweep_step = max(1.0, min_gap * 0.7, text_size * 0.55)
        sweep_positions = []
        y = min_y + text_size
        while y <= max_y - text_size:
            sweep_positions.append(y)
            y += sweep_step
        sweep_positions.sort(key=lambda candidate: abs(candidate - base))
        for y in sweep_positions:
            if not _position_is_free(y):
                continue
            bbox = _text_collision_box(text, x, y, text_size, anchor)
            used_positions.append(y)
            collision_boxes.append(bbox)
            return y
    y = _reserve_feature_label_y(base, used_positions, min_gap, min_y, max_y)
    bbox = _text_collision_box(text, x, y, text_size, anchor)
    collision_boxes.append(bbox)
    return y


def infer_metric_thread_label(core_diameter_mm):
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


def _matching_hole_groups(feature_payload, diameter_mm=None):
    matching_hole_groups, _ = _get_dimension_strategy_hole_helpers()
    return matching_hole_groups(feature_payload or {}, diameter_mm=diameter_mm)


def _summarize_hole_extent(feature_payload, diameter_mm=None):
    _, summarize_hole_extent = _get_dimension_strategy_hole_helpers()
    return summarize_hole_extent(feature_payload or {}, diameter_mm=diameter_mm)


def _format_hole_callout_text(base_text, feature_payload, diameter_mm=None):
    hole_extent = _summarize_hole_extent(feature_payload, diameter_mm=diameter_mm)
    if not hole_extent:
        return base_text
    if hole_extent.get("through") is True:
        return f"{base_text} DURCH"
    depth_mm = _optional_float(hole_extent.get("depth_mm"))
    if hole_extent.get("through") is False and depth_mm is not None and depth_mm > 0:
        return f"{base_text} x {format_de_number(depth_mm)} TIEF"
    return base_text


def _format_thread_callout_text(thread_label, feature_payload):
    base_text = f"{thread_label} GEWINDE"
    thread_through = (feature_payload or {}).get("thread_through")
    thread_depth_mm = _optional_float((feature_payload or {}).get("thread_depth_mm"))
    if thread_through is None and thread_depth_mm is None:
        thread_extent = _summarize_hole_extent(
            feature_payload,
            diameter_mm=_optional_float((feature_payload or {}).get("thread_core_diameter_mm")),
        )
        if thread_extent:
            thread_through = thread_extent.get("through")
            thread_depth_mm = _optional_float(thread_extent.get("depth_mm"))
    if thread_through is True:
        return f"{base_text} DURCH"
    if thread_through is False and thread_depth_mm is not None and thread_depth_mm > 0:
        return f"{base_text} TIEF {format_de_number(thread_depth_mm)}"
    return base_text


def _format_pocket_location_text(pocket):
    if not isinstance(pocket, dict):
        return "TASCHE"
    length_mm = _optional_float(pocket.get("length_mm")) or 0.0
    width_mm = _optional_float(pocket.get("width_mm")) or 0.0
    if length_mm > 0.0 and width_mm > 0.0:
        return f"TASCHE {format_de_number(length_mm)}\u00D7{format_de_number(width_mm)}"
    return "TASCHE"


def _format_pocket_depth_text(pocket):
    if not isinstance(pocket, dict):
        return "TASCHE"
    depth_mm = _optional_float(pocket.get("depth_mm"))
    if depth_mm is not None and depth_mm > 0.0:
        return f"TASCHE TIEF {format_de_number(depth_mm)}"
    return "TASCHE"


def _format_groove_callout_text(groove):
    if not isinstance(groove, dict):
        return "EINSTICH DIN 509"
    kind = str(groove.get("kind") or "").strip().lower()
    prefix = "FREISTICH" if kind == "freistich" else "EINSTICH"
    din_ref = str(groove.get("din_ref") or "DIN 509").strip() or "DIN 509"
    width_mm = _optional_float(groove.get("width_mm"))
    diameter_mm = _optional_float(groove.get("diameter_mm"))
    if width_mm is not None and diameter_mm is not None:
        return f"{prefix} {din_ref} {format_de_number(width_mm)}\u00D7\u00D8{format_de_number(diameter_mm)}"
    if width_mm is not None:
        return f"{prefix} {din_ref} b={format_de_number(width_mm)}"
    return f"{prefix} {din_ref}"


def _feature_text_svg(text, x, y, text_size, anchor="middle"):
    # White background rectangle behind text for readability (ISO 129-1 text mask)
    char_w = text_size * 0.6
    text_w = max(len(text), 1) * char_w
    rect_pad = text_size * 0.25  # Increased padding to prevent line-through appearance
    if anchor == "middle":
        rect_x = x - text_w * 0.5 - rect_pad
    elif anchor == "start":
        rect_x = x - rect_pad
    else:
        rect_x = x - text_w - rect_pad
    rect_y = -y - text_size * 0.8
    rect_w = text_w + rect_pad * 2
    rect_h = text_size * 1.5
    return (
        f'<g fill="rgb(0, 0, 0)" stroke="none" font-size="{text_size:.3f}" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
        f'<rect x="{rect_x:.3f}" y="{rect_y:.3f}" '
        f'width="{rect_w:.3f}" height="{rect_h:.3f}" fill="white" />'
        f'<text x="{x:.3f}" y="{-y:.3f}" text-anchor="{anchor}">{escape(text)}</text>'
        "</g>"
    )


def _is_round_flat_feature_case(feature_payload):
    if not isinstance(feature_payload, dict):
        return False
    if feature_payload.get("ok") is not True or feature_payload.get("is_flat") is not True:
        return False
    bbox = feature_payload.get("bbox_mm") or {}
    dims = sorted(
        [
            _optional_float(bbox.get("X")) or 0.0,
            _optional_float(bbox.get("Y")) or 0.0,
            _optional_float(bbox.get("Z")) or 0.0,
        ],
        reverse=True,
    )
    if len(dims) < 3 or dims[0] <= 0.0 or dims[1] <= 0.0:
        return False
    round_ratio = abs(dims[0] - dims[1]) / max(dims[0], dims[1], 1e-6)
    flat_ratio = dims[2] / max(dims[1], 1e-6)
    return round_ratio <= 0.12 and flat_ratio <= 0.22


def _build_round_feature_dimension_svg(
    svg_group,
    svg_bounds,
    feature_payload,
    scale,
    dim_stroke,
    text_size,
    label_gap,
    metadata=None,
):
    if not _is_round_flat_feature_case(feature_payload):
        return ""

    circles = extract_svg_circular_features(svg_group)
    if len(circles) < 4:
        return ""

    outer = max(circles, key=lambda item: item["r"])
    outer_dia = outer["r"] * 2.0
    if outer_dia <= 1.0:
        return ""

    center_x = float(outer["cx"])
    center_y = float(outer["cy"])
    inner_circles = [circle for circle in circles if circle["r"] < outer["r"] * 0.92]
    if not inner_circles:
        return ""

    grouped = {}
    for circle in inner_circles:
        dia = round((circle["r"] * 2.0) * 2.0) / 2.0
        radial = round((math.hypot(circle["cx"] - center_x, circle["cy"] - center_y)) * 2.0) / 2.0
        grouped.setdefault((dia, radial), []).append(circle)

    center_feature = None
    radial_patterns = {}
    radial_center_tol = max(0.8, outer["r"] * 0.05)
    for (dia, radial), members in grouped.items():
        if radial <= radial_center_tol:
            if center_feature is None or dia > center_feature["dia"]:
                center_feature = {
                    "dia": dia,
                    "circle": max(members, key=lambda item: item["r"]),
                }
            continue
        if len(members) < 3:
            continue
        candidate = {
            "dia": dia,
            "radial": radial,
            "count": len(members),
            "circle": max(members, key=lambda item: math.hypot(item["cx"] - center_x, item["cy"] - center_y)),
        }
        picked = radial_patterns.get(radial)
        if (
            picked is None
            or candidate["count"] > picked["count"]
            or (candidate["count"] == picked["count"] and candidate["dia"] > picked["dia"])
        ):
            radial_patterns[radial] = candidate

    callouts = []
    if center_feature and center_feature["dia"] < outer_dia * 0.95:
        callouts.append(
            {
                "label": f"Ø{format_de_number(center_feature['dia'])}",
                "circle": center_feature["circle"],
                "dir": (-0.86, 0.52),
            }
        )

    for pattern in sorted(radial_patterns.values(), key=lambda item: (-item["radial"], -item["count"], -item["dia"]))[:3]:
        label = f"{pattern['count']}x Ø{format_de_number(pattern['dia'])}"
        if pattern["radial"] > max(1.5, pattern["dia"] * 0.6):
            label += f" LK Ø{format_de_number(pattern['radial'] * 2.0)}"
        px = float(pattern["circle"]["cx"]) - center_x
        py = float(pattern["circle"]["cy"]) - center_y
        plen = math.hypot(px, py) or 1.0
        callouts.append(
            {
                "label": label,
                "circle": pattern["circle"],
                "dir": (px / plen, py / plen),
            }
        )

    if not callouts:
        return ""

    min_x, max_x, min_y, max_y = svg_bounds
    line_pad = max(0.25, 0.6 / max(scale, 0.05))
    used_label_y = []
    collision_boxes = [
        (
            min_x - max(0.8, 1.8 / max(scale, 0.05)),
            max_x + max(0.8, 1.8 / max(scale, 0.05)),
            min_y - max(0.8, 1.8 / max(scale, 0.05)),
            max_y + max(0.8, 1.8 / max(scale, 0.05)),
        )
    ]
    parts = []
    used_dimension_labels = set()
    text_offset = max(12.0 / max(scale, 0.05), outer["r"] * 0.22)
    knee_offset = max(5.0 / max(scale, 0.05), outer["r"] * 0.10)

    for callout in callouts:
        label = callout["label"]
        if label in used_dimension_labels:
            continue
        used_dimension_labels.add(label)
        circle = callout["circle"]
        ux, uy = callout["dir"]
        start_x = float(circle["cx"]) + ux * max(float(circle["r"]) * 0.75, 1.2 / max(scale, 0.05))
        start_y = float(circle["cy"]) + uy * max(float(circle["r"]) * 0.75, 1.2 / max(scale, 0.05))
        knee_x = center_x + ux * (outer["r"] + knee_offset)
        knee_y = center_y + uy * (outer["r"] + knee_offset)
        text_x = center_x + ux * (outer["r"] + text_offset)
        pref_y = center_y + uy * (outer["r"] + text_offset * 0.8)
        anchor = "start" if ux >= 0.0 else "end"
        text_clearance = max(3.0 / max(scale, 0.05), outer["r"] * 0.08)
        if anchor == "start":
            text_x = max(text_x, max_x + text_clearance)
        else:
            text_x = min(text_x, min_x - text_clearance)
        text_y = _reserve_feature_label_position(
            label,
            text_x,
            pref_y,
            text_size,
            anchor,
            used_label_y,
            label_gap,
            min_y - (8.0 / max(scale, 0.05)),
            max_y + (8.0 / max(scale, 0.05)),
            collision_boxes,
        )
        end_x = text_x - (1.0 / max(scale, 0.05)) if anchor == "start" else text_x + (1.0 / max(scale, 0.05))
        end_y = text_y
        parts.append(
            f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
            f'stroke-linecap="butt" stroke-linejoin="miter">'
            f'<line x1="{start_x:.3f}" y1="{start_y:.3f}" x2="{knee_x:.3f}" y2="{knee_y:.3f}" />'
            f'<line x1="{knee_x:.3f}" y1="{knee_y:.3f}" x2="{end_x:.3f}" y2="{end_y:.3f}" />'
            "</g>"
        )
        line_box_a = _line_collision_box(start_x, start_y, knee_x, knee_y, line_pad)
        line_box_b = _line_collision_box(knee_x, knee_y, end_x, end_y, line_pad)
        collision_boxes.append(line_box_a)
        collision_boxes.append(line_box_b)
        text_box = quality_text_collision_box(label, text_x, text_y, text_size, anchor)
        collision_boxes.append(text_box)
        _record_dimension_entry(
            metadata,
            "feature_dimensions",
            dim_type="hole_diameter",
            axis=None,
            style="leader",
            outside=True,
            measurement_box=(
                min(line_box_a[0], line_box_b[0]),
                max(line_box_a[1], line_box_b[1]),
                min(line_box_a[2], line_box_b[2]),
                max(line_box_a[3], line_box_b[3]),
            ),
            text_box=text_box,
        )
        parts.append(_feature_text_svg(label, text_x, text_y, text_size, anchor=anchor))

    return "".join(parts)


def build_feature_dimension_svg(
    svg_group,
    svg_bounds,
    feature_payload,
    scale,
    stroke_width,
    line_profile=None,
    allowed_dim_types=None,
    outside_placement=False,
    metadata=None,
    direction=None,
    rotation_deg=0,
    view_name=None,
    layout_profile=None,
    allow_projected_feature_targets=False,
):
    if not isinstance(feature_payload, dict) or feature_payload.get("ok") is not True:
        return ""
    allowed_types = set(allowed_dim_types) if allowed_dim_types is not None else None

    def _allow(dim_type):
        return allowed_types is None or dim_type in allowed_types

    min_x, max_x, min_y, max_y = svg_bounds
    circles = extract_svg_circular_features(svg_group)
    projected_circles = (
        _project_feature_centerline_targets(
            feature_payload,
            direction,
            scale,
            limit=40,
            allow_nonflat=allow_projected_feature_targets,
        )
        if direction is not None
        else []
    )

    def _dominant_circle_bucket(candidates):
        if not candidates:
            return None, 0
        buckets = {}
        for circle in candidates:
            key = round(float(circle.get("r", 0.0)) * 2.0) / 2.0
            buckets.setdefault(key, []).append(circle)
        if not buckets:
            return None, 0
        radius, bucket = max(buckets.items(), key=lambda item: (len(item[1]), item[0]))
        return radius, len(bucket)

    source_circles = circles
    if projected_circles:
        use_projected_circles = not circles
        expected_hole_dia = _optional_float((feature_payload or {}).get("hole_diameter_mm"))
        visible_radius, visible_count = _dominant_circle_bucket(circles)
        projected_radius, projected_count = _dominant_circle_bucket(projected_circles)
        if not use_projected_circles and expected_hole_dia and projected_radius:
            visible_dia = visible_radius * 2.0 if visible_radius else None
            projected_dia = projected_radius * 2.0
            diameter_tol = max(0.5, expected_hole_dia * 0.15)
            visible_matches_expected = bool(
                visible_dia is not None and abs(visible_dia - expected_hole_dia) <= diameter_tol
            )
            projected_matches_expected = abs(projected_dia - expected_hole_dia) <= diameter_tol
            if projected_matches_expected and not visible_matches_expected and projected_count >= max(visible_count, 4):
                use_projected_circles = True
        if (
            not use_projected_circles
            and bool((feature_payload or {}).get("is_flat"))
            and projected_count >= 6
            and projected_count >= max(visible_count * 2, 6)
        ):
            use_projected_circles = True
        if use_projected_circles:
            source_circles = projected_circles

    main_holes = []
    main_radius = 0.0
    if source_circles:
        circles = sorted(source_circles, key=lambda item: item["r"], reverse=True)
        buckets = {}
        for circle in circles:
            key = round(circle["r"] * 2.0) / 2.0
            buckets.setdefault(key, []).append(circle)
        main_bucket = max(buckets.items(), key=lambda item: (len(item[1]), item[0]))[0]
        tol = max(0.5, main_bucket * 0.15)
        main_holes = [circle for circle in circles if abs(circle["r"] - main_bucket) <= tol]
        main_radius = main_bucket

    def _pick_hole_pattern_group(candidates):
        if len(candidates) < 3:
            return list(candidates)
        cluster_gap = max(
            main_radius * 10.0,
            min(max_x - min_x, max_y - min_y) * 0.30,
            14.0 / max(scale, 0.05),
        )
        remaining = list(candidates)
        clusters = []
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            changed = True
            while changed:
                changed = False
                still_open = []
                for circle in remaining:
                    if any(
                        math.hypot(float(circle["cx"]) - float(member["cx"]), float(circle["cy"]) - float(member["cy"])) <= cluster_gap
                        for member in cluster
                    ):
                        cluster.append(circle)
                        changed = True
                    else:
                        still_open.append(circle)
                remaining = still_open
            clusters.append(cluster)

        def _cluster_score(cluster):
            xs = [float(circle["cx"]) for circle in cluster]
            ys = [float(circle["cy"]) for circle in cluster]
            span_x = max(xs) - min(xs)
            span_y = max(ys) - min(ys)
            area = max(span_x * span_y, 1.0)
            return (len(cluster), -area, -max(span_x, span_y))

        picked = max(clusters, key=_cluster_score)
        return picked if len(picked) >= 3 else list(candidates)

    pattern_holes = _pick_hole_pattern_group(main_holes) if main_holes else []
    pattern_is_radial = False
    if len(pattern_holes) >= 4:
        cx_mean = sum(float(circle["cx"]) for circle in pattern_holes) / len(pattern_holes)
        cy_mean = sum(float(circle["cy"]) for circle in pattern_holes) / len(pattern_holes)
        radial_values = [
            math.hypot(float(circle["cx"]) - cx_mean, float(circle["cy"]) - cy_mean)
            for circle in pattern_holes
        ]
        radial_mean = sum(radial_values) / max(len(radial_values), 1)
        radial_spread = (max(radial_values) - min(radial_values)) if radial_values else 0.0
        pattern_is_radial = bool(
            radial_values
            and radial_mean > max(main_radius * 0.75, 2.0 / max(scale, 0.05))
            and radial_spread <= max(main_radius * 0.45, 1.8 / max(scale, 0.05))
        )
    dim_stroke = max(0.0008, stroke_width * 0.55)
    if isinstance(line_profile, dict):
        dim_stroke = max(0.0008, float(line_profile.get("dimension", dim_stroke)))
    # Use dimension_metrics for consistent sizing with overall dimensions
    _metrics = dimension_metrics(svg_bounds, scale)
    arrow_len = _metrics["arrow_len"]
    arrow_half = _metrics["arrow_half"]
    is_flat_part = bool((feature_payload or {}).get("is_flat"))
    hole_count = int(_optional_float((feature_payload or {}).get("hole_count")) or 0)
    aggressive_outside = bool(outside_placement and (not is_flat_part or hole_count >= 4))
    overall_dimensions = list((metadata or {}).get("overall_dimensions") or []) if isinstance(metadata, dict) else []
    band_profile = build_feature_outside_band_profile(
        svg_bounds,
        scale,
        rotation_deg,
        view_name=view_name,
        layout_profile=layout_profile,
        overall_dimensions=overall_dimensions,
    )
    text_size = max(0.2, (4.2 if aggressive_outside else 3.7) / scale)
    label_gap = max(1.8, (4.8 if aggressive_outside else 4.0) / max(scale, 0.05))
    outside_margin = max((5.6 if aggressive_outside else 4.0) / max(scale, 0.05), label_gap * (1.18 if aggressive_outside else 0.9))
    label_min_y = min_y - (
        max(
            outside_margin * (4.2 if aggressive_outside else 3.0),
            band_profile.get("label_band_depth", 0.0),
        )
        if outside_placement
        else 0.0
    )
    label_max_y = max_y + (outside_margin * (4.2 if aggressive_outside else 3.0) if outside_placement else 0.0)
    outside_text_offset = max(
        (5.2 if aggressive_outside else 4.0) / max(scale, 0.05),
        label_gap * (1.15 if aggressive_outside else 0.9),
        band_profile.get("side_step", 0.0) * 0.8,
    )
    if _allow("hole_diameter"):
        round_feature_svg = _build_round_feature_dimension_svg(
            svg_group,
            svg_bounds,
            feature_payload,
            scale,
            dim_stroke,
            text_size,
            label_gap,
            metadata=metadata,
        )
        if round_feature_svg:
            return round_feature_svg
    used_label_y = []
    parts = []
    hole_pitch = _optional_float(feature_payload.get("preferred_hole_pitch_mm"))
    hole_pitch_source = str(feature_payload.get("preferred_hole_pitch_source") or "").strip().lower()
    allow_hole_pitch_dimension = hole_pitch_source == "linear_pattern" or (
        hole_count == 2 and hole_pitch is not None and hole_pitch > 0
    )
    rotation_norm = int(round(_optional_float(rotation_deg) or 0.0)) % 360

    def _feature_text_box(label, x, y, anchor):
        if outside_placement and str(view_name or "") == "Front" and rotation_norm in {90, 270}:
            return quality_rotated_text_collision_box(label, x, y, text_size)
        return quality_text_collision_box(label, x, y, text_size, anchor)

    pitch_drawn = False
    location_x_drawn = False
    location_y_drawn = False
    used_dimension_labels = set()

    geom_pad = max(0.8, 1.8 / max(scale, 0.05))
    line_pad = max(0.25, 0.6 / max(scale, 0.05))
    summary_line_pad = max(0.05, 0.18 / max(scale, 0.05))
    arrow_pad = max(0.25, 0.7 / max(scale, 0.05))
    shared_collision_boxes = _get_shared_collision_boxes(metadata)
    overall_reserved_boxes = []
    overall_vertical_boxes = []
    for entry in overall_dimensions:
        if not isinstance(entry, dict):
            continue
        axis = str(entry.get("axis") or "").strip().upper()
        for box_key in ("measurement_box", "text_box"):
            box = entry.get(box_key)
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            try:
                normalized_box = tuple(float(value) for value in box)
            except (TypeError, ValueError):
                continue
            overall_reserved_boxes.append(normalized_box)
            if axis == "V":
                overall_vertical_boxes.append(normalized_box)
    collision_boxes = []
    _append_unique_collision_box(
        collision_boxes,
        (min_x - geom_pad, max_x + geom_pad, min_y - geom_pad, max_y + geom_pad),
    )
    for shared_box in shared_collision_boxes or []:
        _append_unique_collision_box(collision_boxes, shared_box)
    for overall_box in overall_reserved_boxes:
        _append_unique_collision_box(collision_boxes, overall_box)
    placement_context = (metadata or {}).get("_placement_context") if isinstance(metadata, dict) else None
    paper_center = None
    drawing_bounds_paper = None
    neighbor_slot_bounds = []
    neighbor_view_bounds = []
    reserved_paper_boxes = []
    if isinstance(placement_context, dict):
        try:
            center_payload = placement_context.get("paper_center") or ()
            if len(center_payload) == 2:
                paper_center = (float(center_payload[0]), float(center_payload[1]))
        except (TypeError, ValueError):
            paper_center = None
        try:
            drawing_payload = placement_context.get("drawing_bounds") or ()
            if len(drawing_payload) == 4:
                drawing_bounds_paper = tuple(float(value) for value in drawing_payload)
        except (TypeError, ValueError):
            drawing_bounds_paper = None
        for bounds in placement_context.get("neighbor_slot_bounds") or []:
            try:
                if len(bounds) == 4:
                    neighbor_slot_bounds.append(tuple(float(value) for value in bounds))
            except (TypeError, ValueError):
                continue
        for bounds in placement_context.get("neighbor_view_bounds") or []:
            try:
                if len(bounds) == 4:
                    neighbor_view_bounds.append(tuple(float(value) for value in bounds))
            except (TypeError, ValueError):
                continue
        for bounds in placement_context.get("reserved_paper_boxes") or []:
            normalized_reserved = _normalize_collision_box(bounds)
            if normalized_reserved is not None:
                reserved_paper_boxes.append(normalized_reserved)
    layout_mode = str(layout_profile or "").strip().lower()
    basis = view_basis(direction) if direction is not None else None
    if basis is not None:
        right, up = basis
    else:
        right, up = None, None
    if layout_mode == "milling":
        neighbor_guard_bounds = neighbor_view_bounds or neighbor_slot_bounds
    else:
        neighbor_guard_bounds = neighbor_slot_bounds or neighbor_view_bounds

    def _transform_local_point_to_view_paper(x, y):
        if paper_center is None:
            return None
        return transform_local_point_to_paper(
            float(x),
            float(y),
            svg_bounds,
            paper_center[0],
            paper_center[1],
            scale,
            rotation_deg,
        )

    def _transform_local_bounds_to_view_paper(bounds):
        if paper_center is None or not bounds or len(bounds) != 4:
            return None
        return transform_local_bounds_to_paper(
            tuple(float(value) for value in bounds),
            svg_bounds,
            paper_center[0],
            paper_center[1],
            scale,
            rotation_deg,
        )

    def _reserve_view_label_position(*args, **kwargs):
        paper_box_resolver = (
            _transform_local_bounds_to_view_paper
            if paper_center is not None and rotation_norm in {90, 270}
            else None
        )
        return _reserve_feature_label_position(
            *args,
            **kwargs,
            paper_box_resolver=paper_box_resolver,
        )

    def _boxes_overlap_in_collision_space(box_a, box_b, margin=0.12):
        if box_a is None or box_b is None:
            return False
        if paper_center is not None and rotation_norm in {90, 270}:
            paper_box_a = _transform_local_bounds_to_view_paper(box_a)
            paper_box_b = _transform_local_bounds_to_view_paper(box_b)
            if paper_box_a is not None and paper_box_b is not None:
                return _bbox_overlaps(paper_box_a, paper_box_b, margin=margin)
        return _bbox_overlaps(box_a, box_b, margin=margin)

    def _local_box_within_drawing_bounds(local_box):
        """Check if a local-coordinate box fits within the drawing area bounds.

        Works for ALL views (not just Front+rotated).  Returns True when
        bounds information is unavailable so callers fall through gracefully.
        """
        if paper_center is None or drawing_bounds_paper is None:
            return True
        paper_box = _transform_local_bounds_to_view_paper(local_box)
        if paper_box is None:
            return True
        if (
            paper_box[0] < drawing_bounds_paper[0]
            or paper_box[1] > drawing_bounds_paper[1]
            or paper_box[2] < drawing_bounds_paper[2]
            or paper_box[3] > drawing_bounds_paper[3]
        ):
            return False
        return not any(
            _bbox_overlaps(paper_box, reserved_box, margin=0.25)
            for reserved_box in reserved_paper_boxes
        )

    def _local_box_fits_neighbor_slots(local_box):
        if paper_center is None:
            return True
        # Drawing-area bounds check applies to ALL views.
        if not _local_box_within_drawing_bounds(local_box):
            return False
        # Neighbor-slot overlap check only for Front view with rotation.
        if (
            str(view_name or "") != "Front"
            or rotation_norm not in {90, 270}
            or not neighbor_guard_bounds
        ):
            return True
        paper_box = _transform_local_bounds_to_view_paper(local_box)
        if paper_box is None:
            return True
        return not any(
            _bbox_overlaps(paper_box, slot_box, margin=0.35)
            for slot_box in neighbor_guard_bounds
        )

    def _leader_candidate_fits_neighbor_slots(line_bounds, text_bounds):
        for bounds in (line_bounds, text_bounds):
            if bounds is not None and not _local_box_fits_neighbor_slots(bounds):
                return False
        return True
    def _outside_side_order(preferred_side=None):
        preferred = str(preferred_side or band_profile.get("preferred_vertical_side") or "left").strip().lower()
        if preferred not in {"left", "right"}:
            preferred = "left"
        return (preferred, "right" if preferred == "left" else "left")

    def _outside_side_geometry(side):
        if str(side).strip().lower() == "right":
            return max_x, 1.0, "start"
        return min_x, -1.0, "end"

    def _project_probe_center_to_local(center):
        if right is None or up is None or not isinstance(center, dict):
            return None
        px = _optional_float(center.get("x"))
        py = _optional_float(center.get("y"))
        pz = _optional_float(center.get("z"))
        if None in {px, py, pz}:
            return None
        point = App.Vector(float(px), float(py), float(pz))
        return float(point.dot(right)), float(point.dot(up))

    def _select_representative_pocket():
        pockets = [pocket for pocket in (feature_payload.get("pocket_groups") or []) if isinstance(pocket, dict)]
        if not pockets:
            return None

        def _rank(pocket):
            length_mm = _optional_float(pocket.get("length_mm")) or 0.0
            width_mm = _optional_float(pocket.get("width_mm")) or 0.0
            depth_mm = _optional_float(pocket.get("depth_mm")) or 0.0
            center = pocket.get("center_mm") or {}
            center_x = _optional_float(center.get("x")) or 0.0
            return (length_mm * width_mm, depth_mm, length_mm, -center_x)

        return max(pockets, key=_rank)

    def _select_representative_groove():
        grooves = [groove for groove in (feature_payload.get("groove_groups") or []) if isinstance(groove, dict)]
        if not grooves:
            return None

        def _rank(groove):
            kind = str(groove.get("kind") or "").strip().lower()
            width_mm = _optional_float(groove.get("width_mm")) or 0.0
            diameter_mm = _optional_float(groove.get("diameter_mm")) or 0.0
            return (
                1 if kind == "freistich" else 0,
                -width_mm,
                -diameter_mm,
            )

        return max(grooves, key=_rank)

    def _draw_generic_feature_note(dim_type, label_text, target_xy):
        if not label_text or label_text in used_dimension_labels or target_xy is None:
            return False

        target_x = max(min_x + (1.0 / max(scale, 0.05)), min(max_x - (1.0 / max(scale, 0.05)), float(target_xy[0])))
        target_y = max(min_y + (1.0 / max(scale, 0.05)), min(max_y - (1.0 / max(scale, 0.05)), float(target_xy[1])))
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5
        dir_x = -1.0 if target_x <= center_x else 1.0
        dir_y = -1.0 if target_y <= center_y else 1.0

        if outside_placement:
            ky = target_y + dir_y * (4.2 / scale)
            leader_band = _allocate_outside_leader_band(
                target_x,
                target_y,
                ky,
                preferred_side=band_profile.get("preferred_leader_side"),
                side_margin_factor=0.55,
                text_margin_factor=0.70,
                min_text_offset=8.0 / scale,
                label_text=label_text,
                label_text_size=text_size,
            )
            if leader_band.get("suppress"):
                return False
            kx = leader_band["knee_x"]
            ex = leader_band["text_edge_x"]
            ey = ky
            anchor = leader_band["anchor"]
            text_x = ex - (1.0 / scale) if anchor == "end" else ex + (1.0 / scale)
        else:
            kx = target_x + dir_x * (6.0 / scale)
            ky = target_y + dir_y * (4.0 / scale)
            ex = kx + dir_x * (10.0 / scale)
            ey = ky
            anchor = "end" if dir_x < 0 else "start"
            text_x = ex - (1.0 / scale) if anchor == "end" else ex + (1.0 / scale)

        line_box_a = _line_collision_box(target_x, target_y, kx, ky, line_pad)
        line_box_b = _line_collision_box(kx, ky, ex, ey, line_pad)
        trial_measurement_box = (
            min(line_box_a[0], line_box_b[0]),
            max(line_box_a[1], line_box_b[1]),
            min(line_box_a[2], line_box_b[2]),
            max(line_box_a[3], line_box_b[3]),
        )
        trial_text_y = ey - (0.8 / scale) if dir_y < 0 else ey + (0.8 / scale)
        text_y = _reserve_view_label_position(
            label_text,
            text_x,
            trial_text_y,
            text_size,
            anchor,
            used_label_y,
            label_gap,
            label_min_y,
            label_max_y,
            collision_boxes,
        )
        text_box = _feature_text_box(label_text, text_x, text_y, anchor)
        if not _leader_candidate_fits_neighbor_slots(trial_measurement_box, text_box):
            return False

        parts.append(
            f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" stroke-linecap="butt">'
            f'<line x1="{target_x:.3f}" y1="{target_y:.3f}" x2="{kx:.3f}" y2="{ky:.3f}" />'
            f'<line x1="{kx:.3f}" y1="{ky:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" />'
            "</g>"
        )
        collision_boxes.append(line_box_a)
        collision_boxes.append(line_box_b)
        collision_boxes.append(text_box)
        used_dimension_labels.add(label_text)
        _record_dimension_entry(
            metadata,
            "feature_dimensions",
            dim_type=dim_type,
            axis=None,
            style="leader",
            outside=outside_placement,
            measurement_box=trial_measurement_box,
            text_box=text_box,
        )
        parts.append(
            _feature_text_svg(
                label_text,
                text_x,
                text_y,
                text_size,
                anchor=anchor,
            )
        )
        return True

    def _allocate_horizontal_outside_y(x0, x1, ext_y):
        base_y = min_y - band_profile.get("top_base_offset", outside_margin * 1.15)
        step = max(band_profile.get("top_step", outside_margin * 0.8), 1.2 / scale)
        first_in_bounds = None
        for band_index in range(10):
            y_dim = base_y - step * band_index
            occupied_box = (
                min(float(x0), float(x1)) - line_pad,
                max(float(x0), float(x1)) + line_pad,
                min(float(ext_y), y_dim) - line_pad,
                max(float(ext_y), y_dim) + line_pad,
            )
            if not _local_box_within_drawing_bounds(occupied_box):
                continue
            if first_in_bounds is None:
                first_in_bounds = y_dim
            if any(_bbox_overlaps(occupied_box, box, margin=0.12) for box in collision_boxes):
                continue
            return y_dim
        # All collision-free positions were out of bounds — return the closest
        # in-bounds position (accept collision) or the first band as last resort.
        return first_in_bounds if first_in_bounds is not None else base_y

    def _allocate_vertical_outside_x(y0, y1, anchor_x, preferred_side=None):
        first_in_bounds = None
        first_in_bounds_side = None
        for side in _outside_side_order(preferred_side):
            side_edge_x, sign, _ = _outside_side_geometry(side)
            base_x = side_edge_x + sign * band_profile.get("side_base_offset", outside_margin * 1.18)
            step = sign * max(band_profile.get("side_step", outside_margin * 0.8), 1.6 / scale)
            for band_index in range(10):
                x_dim = base_x + step * band_index
                occupied_box = _line_collision_box(x_dim, y0, x_dim, y1, summary_line_pad)
                if not _local_box_within_drawing_bounds(occupied_box):
                    continue
                if first_in_bounds is None:
                    first_in_bounds = x_dim
                    first_in_bounds_side = side
                if any(_bbox_overlaps(occupied_box, box, margin=0.12) for box in collision_boxes):
                    continue
                return x_dim, side
        if first_in_bounds is not None:
            return first_in_bounds, first_in_bounds_side
        fallback_side = _outside_side_order(preferred_side)[0]
        side_edge_x, sign, _ = _outside_side_geometry(fallback_side)
        return (
            side_edge_x
            + sign
            * band_profile.get("side_base_offset", outside_margin * 1.18),
            fallback_side,
        )

    def _allocate_outside_leader_band(
        sx,
        sy,
        ky,
        preferred_side=None,
        *,
        side_margin_factor=0.45,
        text_margin_factor=1.1,
        min_side_margin=None,
        min_text_offset=None,
        label_text=None,
        label_text_size=None,
    ):
        leader_preference = preferred_side or band_profile.get("preferred_leader_side")
        min_side_margin = max(2.6 / scale, float(min_side_margin or 0.0))
        min_text_offset = max(2.0 / scale, float(min_text_offset or 0.0))
        fallback_any = None
        fallback_in_bounds = None
        vertical_band_clearance = max(
            band_profile.get("side_step", outside_margin * 0.8),
            4.5 / scale,
        )
        for side in _outside_side_order(leader_preference):
            side_edge_x, sign, anchor = _outside_side_geometry(side)
            for band_index in range(10):
                band_offset = band_profile.get("side_base_offset", outside_margin * 1.18) + band_profile.get("side_step", outside_margin * 0.8) * band_index
                knee_x = side_edge_x + sign * max(band_offset * side_margin_factor, min_side_margin)
                text_edge_x = side_edge_x + sign * max(band_offset * text_margin_factor, min_text_offset)
                occupied_box = (
                    min(float(sx), knee_x, text_edge_x) - line_pad,
                    max(float(sx), knee_x, text_edge_x) + line_pad,
                    min(float(sy), float(ky)) - line_pad,
                    max(float(sy), float(ky)) + line_pad,
                )
                text_x = text_edge_x - (1.0 / scale) if anchor == "end" else text_edge_x + (1.0 / scale)
                text_probe_box = None
                if label_text and label_text_size:
                    text_probe_box = _text_collision_box(
                        label_text,
                        text_x,
                        float(ky),
                        float(label_text_size),
                        anchor,
                    )
                    candidate_in_bounds = _leader_candidate_fits_neighbor_slots(occupied_box, text_probe_box)
                    if not candidate_in_bounds:
                        continue
                else:
                    candidate_in_bounds = _leader_candidate_fits_neighbor_slots(occupied_box, None)
                    if not candidate_in_bounds:
                        continue
                if (
                    layout_mode == "sheet_metal"
                    and str(view_name or "") == "Front"
                    and rotation_norm in {90, 270}
                    and overall_vertical_boxes
                ):
                    if side == "right":
                        reserved_edge = max(box[1] for box in overall_vertical_boxes)
                        candidate_box = text_probe_box or occupied_box
                        if candidate_box[0] < reserved_edge + vertical_band_clearance:
                            continue
                    elif side == "left":
                        reserved_edge = min(box[0] for box in overall_vertical_boxes)
                        candidate_box = text_probe_box or occupied_box
                        if candidate_box[1] > reserved_edge - vertical_band_clearance:
                            continue
                candidate = {
                    "side": side,
                    "direction": sign,
                    "anchor": anchor,
                    "knee_x": knee_x,
                    "text_edge_x": text_edge_x,
                }
                if fallback_any is None:
                    fallback_any = dict(candidate)
                if candidate_in_bounds and fallback_in_bounds is None:
                    fallback_in_bounds = dict(candidate)
                if any(_boxes_overlap_in_collision_space(occupied_box, box, margin=0.12) for box in collision_boxes):
                    continue
                if text_probe_box and any(
                    _boxes_overlap_in_collision_space(text_probe_box, box, margin=0.12)
                    for box in collision_boxes
                ):
                    continue
                return candidate
        if fallback_in_bounds is not None:
            return fallback_in_bounds
        if fallback_any is not None:
            fallback_any["suppress"] = True
            return fallback_any
        side_edge_x, sign, anchor = _outside_side_geometry(_outside_side_order(leader_preference)[0])
        band_offset = band_profile.get("side_base_offset", outside_margin * 1.18) + band_profile.get("side_step", outside_margin * 0.8) * 9
        return {
            "side": _outside_side_order(leader_preference)[0],
            "direction": sign,
            "anchor": anchor,
            "knee_x": side_edge_x + sign * max(band_offset * side_margin_factor, min_side_margin),
            "text_edge_x": side_edge_x + sign * max(band_offset * text_margin_factor, min_text_offset),
            "suppress": True,
        }

    def _reserve_top_band_note_position(text, preferred_x, preferred_y, anchor="middle"):
        probe_box = _text_collision_box(text, preferred_x, preferred_y, text_size, anchor)
        text_width = max(probe_box[1] - probe_box[0], text_size * 1.6)
        half_width = text_width * 0.5
        span_x = max(max_x - min_x, 1.0)
        top_step = max(band_profile.get("top_step", outside_margin * 0.8), 1.2 / scale)
        narrow_rotated_front = (
            str(view_name or "") == "Front"
            and rotation_norm in {90, 270}
            and span_x <= max(40.0, text_width * 0.95)
        )
        side_allowance = max(outside_margin * 0.95, text_size * 1.8, 4.0 / scale)
        if narrow_rotated_front:
            side_allowance = max(side_allowance, outside_margin * 2.0, text_width * 0.8)
        min_center = min_x - side_allowance + half_width
        max_center = max_x + side_allowance - half_width
        x_candidates = []
        candidate_factors = (0.0, -0.22, 0.22, -0.38, 0.38, -0.52, 0.52)
        if narrow_rotated_front and rotation_norm == 90:
            candidate_factors = (0.0, 0.42, -0.42, 0.72, -0.72, 0.96, -0.96)
        elif narrow_rotated_front and rotation_norm == 270:
            candidate_factors = (0.0, -0.42, 0.42, -0.72, 0.72, -0.96, 0.96)
        for factor in candidate_factors:
            candidate_x = preferred_x + span_x * factor
            if min_center <= max_center:
                candidate_x = max(min_center, min(max_center, candidate_x))
            key = round(candidate_x, 4)
            if key in x_candidates:
                continue
            x_candidates.append(key)
        max_band_index = 4 if narrow_rotated_front else 10
        for band_index in range(max_band_index):
            note_y = preferred_y - top_step * band_index
            for candidate_x in x_candidates:
                note_box = _text_collision_box(text, candidate_x, note_y, text_size, anchor)
                if any(_bbox_overlaps(note_box, box, margin=0.12) for box in collision_boxes):
                    continue
                if not _local_box_fits_neighbor_slots(note_box):
                    continue
                used_label_y.append(note_y)
                collision_boxes.append(note_box)
                return float(candidate_x), note_y
        fallback_x = float(x_candidates[0]) if x_candidates else float(preferred_x)
        fallback_y = _reserve_view_label_position(
            text,
            fallback_x,
            preferred_y,
            text_size,
            anchor,
            used_label_y,
            label_gap,
            label_min_y,
            label_max_y,
            collision_boxes,
        )
        return fallback_x, fallback_y

    def _draw_edge_location_dimension(axis, side, circle):
        if not circle:
            return
        radius = max(0.0, float(circle.get("r", 0.0)))
        if axis == "H":
            if side == "left":
                x0 = min_x
                x1 = float(circle["cx"])
            else:
                x0 = float(circle["cx"])
                x1 = max_x
            span = abs(x1 - x0)
            if span <= max(1.0, 4.0 / scale):
                return
            if outside_placement:
                # Keep hole X-location dimensions above the flat pattern so they do
                # not collapse into the global flat-length dimension below the view.
                y_dim = _allocate_horizontal_outside_y(x0, x1, min_y)
                ext_y = min_y
            else:
                pref_above = float(circle["cy"]) - radius - max(4.0 / scale, label_gap * 0.55)
                pref_below = float(circle["cy"]) + radius + max(4.0 / scale, label_gap * 0.55)
                y_dim = pref_above
                if y_dim < min_y + (2.5 / scale):
                    y_dim = pref_below
                y_dim = max(min_y + (2.5 / scale), min(max_y - (2.5 / scale), y_dim))
                ext_y = float(circle["cy"])
            parts.append(
                f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
                f'stroke-linecap="butt" stroke-linejoin="miter">'
                f'<line x1="{x0:.3f}" y1="{y_dim:.3f}" x2="{x1:.3f}" y2="{y_dim:.3f}" />'
                f'<line x1="{x0:.3f}" y1="{ext_y:.3f}" x2="{x0:.3f}" y2="{y_dim:.3f}" />'
                f'<line x1="{x1:.3f}" y1="{ext_y:.3f}" x2="{x1:.3f}" y2="{y_dim:.3f}" />'
                "</g>"
            )
            collision_boxes.append(_line_collision_box(x0, y_dim, x1, y_dim, line_pad))
            collision_boxes.append(_line_collision_box(x0, ext_y, x0, y_dim, line_pad))
            collision_boxes.append(_line_collision_box(x1, ext_y, x1, y_dim, line_pad))
            measurement_box = _line_collision_box(x0, y_dim, x1, y_dim, summary_line_pad)
            parts.append(
                f'<g fill="rgb(0, 0, 0)" stroke="none">'
                f'<polygon points="{x0:.3f},{y_dim:.3f} {x0 + arrow_len:.3f},{y_dim - arrow_half:.3f} {x0 + arrow_len:.3f},{y_dim + arrow_half:.3f}" />'
                f'<polygon points="{x1:.3f},{y_dim:.3f} {x1 - arrow_len:.3f},{y_dim - arrow_half:.3f} {x1 - arrow_len:.3f},{y_dim + arrow_half:.3f}" />'
                "</g>"
            )
            label_text = format_de_number(span)
            if label_text not in used_dimension_labels:
                used_dimension_labels.add(label_text)
                text_x = (x0 + x1) * 0.5
                label_pref_y = y_dim + (1.8 / scale)
                if outside_placement:
                    if y_dim < min_y:
                        label_pref_y = y_dim - (1.8 / scale)
                    elif y_dim > max_y:
                        label_pref_y = y_dim + (1.8 / scale)
                text_y = _reserve_view_label_position(
                    label_text,
                    text_x,
                    label_pref_y,
                    text_size,
                    "middle",
                    used_label_y,
                    label_gap,
                    label_min_y,
                    label_max_y,
                    collision_boxes,
                )
                text_box = _feature_text_box(label_text, text_x, text_y, "middle")
                collision_boxes.append(text_box)
                _record_dimension_entry(
                    metadata,
                    "feature_dimensions",
                    dim_type="hole_location_x",
                    axis="H",
                    style="line",
                    outside=outside_placement,
                    measurement_box=measurement_box,
                    text_box=text_box,
                )
                parts.append(
                    _feature_text_svg(
                        label_text,
                        text_x,
                        text_y,
                        text_size,
                        anchor="middle",
                    )
                )
            return

        if side == "top":
            y0 = min_y
            y1 = float(circle["cy"])
        else:
            y0 = float(circle["cy"])
            y1 = max_y
        span = abs(y1 - y0)
        if span <= max(1.0, 4.0 / scale):
            return
        if outside_placement:
            x_dim, dim_side = _allocate_vertical_outside_x(y0, y1, min_x, preferred_side=band_profile.get("preferred_vertical_side"))
            ext_x = min_x if dim_side == "left" else max_x
        else:
            pref_right = float(circle["cx"]) + radius + max(4.0 / scale, label_gap * 0.55)
            pref_left = float(circle["cx"]) - radius - max(4.0 / scale, label_gap * 0.55)
            x_dim = pref_right
            if x_dim > max_x - (2.5 / scale):
                x_dim = pref_left
            x_dim = max(min_x + (2.5 / scale), min(max_x - (2.5 / scale), x_dim))
            ext_x = float(circle["cx"])
        parts.append(
            f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
            f'stroke-linecap="butt" stroke-linejoin="miter">'
            f'<line x1="{x_dim:.3f}" y1="{y0:.3f}" x2="{x_dim:.3f}" y2="{y1:.3f}" />'
            f'<line x1="{ext_x:.3f}" y1="{y0:.3f}" x2="{x_dim:.3f}" y2="{y0:.3f}" />'
            f'<line x1="{ext_x:.3f}" y1="{y1:.3f}" x2="{x_dim:.3f}" y2="{y1:.3f}" />'
            "</g>"
        )
        collision_boxes.append(_line_collision_box(x_dim, y0, x_dim, y1, line_pad))
        collision_boxes.append(_line_collision_box(ext_x, y0, x_dim, y0, line_pad))
        collision_boxes.append(_line_collision_box(ext_x, y1, x_dim, y1, line_pad))
        measurement_box = _line_collision_box(x_dim, y0, x_dim, y1, summary_line_pad)
        parts.append(
            f'<g fill="rgb(0, 0, 0)" stroke="none">'
            f'<polygon points="{x_dim:.3f},{y0:.3f} {x_dim - arrow_half:.3f},{y0 + arrow_len:.3f} {x_dim + arrow_half:.3f},{y0 + arrow_len:.3f}" />'
            f'<polygon points="{x_dim:.3f},{y1:.3f} {x_dim - arrow_half:.3f},{y1 - arrow_len:.3f} {x_dim + arrow_half:.3f},{y1 - arrow_len:.3f}" />'
            "</g>"
        )
        label_text = format_de_number(span)
        if label_text not in used_dimension_labels:
            used_dimension_labels.add(label_text)
            if outside_placement:
                text_x = x_dim - outside_text_offset if x_dim < min_x else x_dim + outside_text_offset
            else:
                text_x = x_dim + max(2.5 / scale, label_gap * 0.75)
            text_y = _reserve_view_label_position(
                label_text,
                text_x,
                (y0 + y1) * 0.5,
                text_size,
                "middle",
                used_label_y,
                label_gap,
                label_min_y,
                label_max_y,
                collision_boxes,
            )
            rotated_extent = max(text_size * 1.15, text_size * 0.58 * max(1, len(label_text)))
            collision_boxes.append(
                (
                    text_x - text_size * 0.7,
                    text_x + text_size * 0.7,
                    text_y - rotated_extent * 0.55,
                    text_y + rotated_extent * 0.55,
                )
            )
            text_box = quality_rotated_text_collision_box(label_text, text_x, text_y, text_size)
            _record_dimension_entry(
                metadata,
                "feature_dimensions",
                dim_type="hole_location_y",
                axis="V",
                style="line",
                outside=outside_placement,
                measurement_box=measurement_box,
                text_box=text_box,
            )
            parts.append(
                f'<g fill="rgb(0,0,0)" stroke="none" font-size="{text_size:.3f}" '
                f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
                f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
                f'<text x="{text_x:.3f}" y="{-text_y:.3f}" text-anchor="middle" '
                f'transform="rotate(90,{text_x:.3f},{-text_y:.3f})">{label_text}</text></g>'
            )

    edge_location_targets = list(pattern_holes) if pattern_holes else []
    if not edge_location_targets:
        if circles:
            edge_location_targets = sorted(circles, key=lambda item: item["r"], reverse=True)
        elif main_holes:
            edge_location_targets = list(main_holes)

    # Hole pitch dimension between outer main-hole centers.
    if _allow("hole_pitch") and allow_hole_pitch_dimension and len(pattern_holes) >= 2 and not pattern_is_radial:
        by_x = sorted(pattern_holes, key=lambda item: item["cx"])
        left_hole = by_x[0]
        right_hole = by_x[-1]
        span = abs(right_hole["cx"] - left_hole["cx"])
        if span > max(1.0, 5.0 / scale):
            if hole_pitch is None or hole_pitch <= 0 or hole_pitch > span * 1.6:
                hole_pitch = span
            if outside_placement:
                # Keep the pitch chain in the top band and reserve a second tier
                # for the outer datum-to-hole dimension above it.
                y_dim = _allocate_horizontal_outside_y(left_hole["cx"], right_hole["cx"], min(left_hole["cy"], right_hole["cy"]))
            else:
                y_dim = min(left_hole["cy"], right_hole["cy"]) - max(left_hole["r"], right_hole["r"]) - (4.0 / scale)
                if y_dim < min_y + (3.0 / scale):
                    y_dim = max(left_hole["cy"], right_hole["cy"]) + max(left_hole["r"], right_hole["r"]) + (4.0 / scale)
                y_dim = max(min_y + (2.5 / scale), min(max_y - (2.5 / scale), y_dim))
            lx = left_hole["cx"]
            rx = right_hole["cx"]
            parts.append(
                f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
                f'stroke-linecap="butt" stroke-linejoin="miter">'
                f'<line x1="{lx:.3f}" y1="{y_dim:.3f}" x2="{rx:.3f}" y2="{y_dim:.3f}" />'
                f'<line x1="{lx:.3f}" y1="{left_hole["cy"]:.3f}" x2="{lx:.3f}" y2="{y_dim:.3f}" />'
                f'<line x1="{rx:.3f}" y1="{right_hole["cy"]:.3f}" x2="{rx:.3f}" y2="{y_dim:.3f}" />'
                "</g>"
            )
            collision_boxes.append(_line_collision_box(lx, y_dim, rx, y_dim, line_pad))
            collision_boxes.append(_line_collision_box(lx, left_hole["cy"], lx, y_dim, line_pad))
            collision_boxes.append(_line_collision_box(rx, right_hole["cy"], rx, y_dim, line_pad))
            pitch_measurement_box = _line_collision_box(lx, y_dim, rx, y_dim, summary_line_pad)
            parts.append(
                f'<g fill="rgb(0, 0, 0)" stroke="none">'
                f'<polygon points="{lx:.3f},{y_dim:.3f} {lx + arrow_len:.3f},{y_dim - arrow_half:.3f} {lx + arrow_len:.3f},{y_dim + arrow_half:.3f}" />'
                f'<polygon points="{rx:.3f},{y_dim:.3f} {rx - arrow_len:.3f},{y_dim - arrow_half:.3f} {rx - arrow_len:.3f},{y_dim + arrow_half:.3f}" />'
                "</g>"
            )
            collision_boxes.append(
                (
                    min(lx, lx + arrow_len) - arrow_pad,
                    max(lx, lx + arrow_len) + arrow_pad,
                    y_dim - arrow_half - arrow_pad,
                    y_dim + arrow_half + arrow_pad,
                )
            )
            collision_boxes.append(
                (
                    min(rx, rx - arrow_len) - arrow_pad,
                    max(rx, rx - arrow_len) + arrow_pad,
                    y_dim - arrow_half - arrow_pad,
                    y_dim + arrow_half + arrow_pad,
                )
            )
            # Prefer positioning from the nearest outer datum edge to avoid pure chain dimensioning.
            left_edge_span = abs(left_hole["cx"] - min_x)
            right_edge_span = abs(max_x - right_hole["cx"])
            if min(left_edge_span, right_edge_span) > max(1.0, 4.0 / scale):
                if outside_placement:
                    edge_y = _allocate_horizontal_outside_y(
                        min(left_hole["cx"], right_hole["cx"], min_x),
                        max(left_hole["cx"], right_hole["cx"], max_x),
                        min(left_hole["cy"], right_hole["cy"]),
                    )
                else:
                    edge_y = y_dim - max(2.5 / scale, label_gap * 0.55)
                    if edge_y < min_y + (2.5 / scale):
                        edge_y = y_dim + max(2.5 / scale, label_gap * 0.55)
                if right_edge_span < left_edge_span:
                    ex0 = right_hole["cx"]
                    ex1 = max_x
                    edge_circle = right_hole
                    edge_span = right_edge_span
                else:
                    ex0 = min_x
                    ex1 = left_hole["cx"]
                    edge_circle = left_hole
                    edge_span = left_edge_span
                parts.append(
                    f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
                    f'stroke-linecap="butt" stroke-linejoin="miter">'
                    f'<line x1="{ex0:.3f}" y1="{edge_y:.3f}" x2="{ex1:.3f}" y2="{edge_y:.3f}" />'
                    f'<line x1="{ex0:.3f}" y1="{edge_circle["cy"]:.3f}" x2="{ex0:.3f}" y2="{edge_y:.3f}" />'
                    f'<line x1="{ex1:.3f}" y1="{edge_circle["cy"]:.3f}" x2="{ex1:.3f}" y2="{edge_y:.3f}" />'
                    "</g>"
                )
                collision_boxes.append(_line_collision_box(ex0, edge_y, ex1, edge_y, line_pad))
                collision_boxes.append(_line_collision_box(ex0, edge_circle["cy"], ex0, edge_y, line_pad))
                collision_boxes.append(_line_collision_box(ex1, edge_circle["cy"], ex1, edge_y, line_pad))
                edge_measurement_box = _line_collision_box(ex0, edge_y, ex1, edge_y, summary_line_pad)
                parts.append(
                    f'<g fill="rgb(0, 0, 0)" stroke="none">'
                    f'<polygon points="{ex0:.3f},{edge_y:.3f} {ex0 + arrow_len:.3f},{edge_y - arrow_half:.3f} {ex0 + arrow_len:.3f},{edge_y + arrow_half:.3f}" />'
                    f'<polygon points="{ex1:.3f},{edge_y:.3f} {ex1 - arrow_len:.3f},{edge_y - arrow_half:.3f} {ex1 - arrow_len:.3f},{edge_y + arrow_half:.3f}" />'
                    "</g>"
                )
                edge_text = format_de_number(edge_span)
                if edge_text not in used_dimension_labels:
                    used_dimension_labels.add(edge_text)
                    edge_tx = (ex0 + ex1) * 0.5
                    edge_pref_y = edge_y + (1.8 / scale)
                    if outside_placement and edge_y < min_y:
                        edge_pref_y = edge_y - (1.8 / scale)
                    edge_ty = _reserve_view_label_position(
                        edge_text,
                        edge_tx,
                        edge_pref_y,
                        text_size,
                        "middle",
                        used_label_y,
                        label_gap,
                        label_min_y,
                        label_max_y,
                        collision_boxes,
                    )
                    edge_text_box = _feature_text_box(edge_text, edge_tx, edge_ty, "middle")
                    collision_boxes.append(edge_text_box)
                    _record_dimension_entry(
                        metadata,
                        "feature_dimensions",
                        dim_type="hole_location_x",
                        axis="H",
                        style="line",
                        outside=outside_placement,
                        measurement_box=edge_measurement_box,
                        text_box=edge_text_box,
                    )
                    parts.append(
                        _feature_text_svg(
                            edge_text,
                            edge_tx,
                            edge_ty,
                            text_size,
                            anchor="middle",
                        )
                    )
                location_x_drawn = True
            # Vertical hole-to-edge: distance from the nearest horizontal datum edge.
            by_y = sorted(pattern_holes, key=lambda item: item["cy"], reverse=True)
            bottom_hole = by_y[0]
            top_hole = by_y[-1]
            bottom_span = abs(max_y - bottom_hole["cy"])
            top_span = abs(float(top_hole["cy"]) - min_y)
            vert_edge_span = min(bottom_span, top_span)
            if vert_edge_span > max(1.0, 4.0 / scale):
                if top_span < bottom_span:
                    anchor_hole = top_hole
                    ey0 = min_y
                    ey1 = anchor_hole["cy"]
                else:
                    anchor_hole = bottom_hole
                    ey0 = max_y
                    ey1 = anchor_hole["cy"]
                if outside_placement:
                    edge_x, _edge_side = _allocate_vertical_outside_x(
                        ey0,
                        ey1,
                        anchor_hole["cx"],
                        preferred_side=band_profile.get("preferred_vertical_side"),
                    )
                else:
                    edge_x = max_x + max(2.5 / scale, label_gap * 0.55)
                parts.append(
                    f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
                    f'stroke-linecap="butt" stroke-linejoin="miter">'
                    f'<line x1="{edge_x:.3f}" y1="{ey0:.3f}" x2="{edge_x:.3f}" y2="{ey1:.3f}" />'
                    f'<line x1="{anchor_hole["cx"]:.3f}" y1="{ey0:.3f}" x2="{edge_x:.3f}" y2="{ey0:.3f}" />'
                    f'<line x1="{anchor_hole["cx"]:.3f}" y1="{ey1:.3f}" x2="{edge_x:.3f}" y2="{ey1:.3f}" />'
                    "</g>"
                )
                collision_boxes.append(_line_collision_box(edge_x, ey0, edge_x, ey1, line_pad))
                collision_boxes.append(_line_collision_box(anchor_hole["cx"], ey0, edge_x, ey0, line_pad))
                collision_boxes.append(_line_collision_box(anchor_hole["cx"], ey1, edge_x, ey1, line_pad))
                vert_measurement_box = _line_collision_box(edge_x, ey0, edge_x, ey1, summary_line_pad)
                # Vertical arrows
                parts.append(
                    f'<g fill="rgb(0, 0, 0)" stroke="none">'
                    f'<polygon points="{edge_x:.3f},{ey0:.3f} {edge_x - arrow_half:.3f},{ey0 - arrow_len:.3f} {edge_x + arrow_half:.3f},{ey0 - arrow_len:.3f}" />'
                    f'<polygon points="{edge_x:.3f},{ey1:.3f} {edge_x - arrow_half:.3f},{ey1 + arrow_len:.3f} {edge_x + arrow_half:.3f},{ey1 + arrow_len:.3f}" />'
                    "</g>"
                )
                vert_text = format_de_number(vert_edge_span)
                if vert_text not in used_dimension_labels:
                    used_dimension_labels.add(vert_text)
                    text_offset = outside_text_offset if outside_placement else max(5.0 / scale, label_gap * 1.1)
                    vert_tx = edge_x - text_offset if outside_placement and edge_x < min_x else edge_x + text_offset
                    vert_ty = _reserve_view_label_position(
                        vert_text,
                        vert_tx,
                        (ey0 + ey1) * 0.5,
                        text_size,
                        "middle",
                        used_label_y,
                        label_gap,
                        label_min_y,
                        label_max_y,
                        collision_boxes,
                    )
                    rotated_extent = max(text_size * 1.15, text_size * 0.58 * max(1, len(vert_text)))
                    collision_boxes.append(
                        (
                            vert_tx - text_size * 0.7,
                            vert_tx + text_size * 0.7,
                            vert_ty - rotated_extent * 0.55,
                            vert_ty + rotated_extent * 0.55,
                        )
                    )
                    vert_text_box = quality_rotated_text_collision_box(vert_text, vert_tx, vert_ty, text_size)
                    _record_dimension_entry(
                        metadata,
                        "feature_dimensions",
                        dim_type="hole_location_y",
                        axis="V",
                        style="line",
                        outside=outside_placement,
                        measurement_box=vert_measurement_box,
                        text_box=vert_text_box,
                    )
                    parts.append(
                        f'<g fill="rgb(0,0,0)" stroke="none" font-size="{text_size:.3f}" '
                        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
                        f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
                        f'<text x="{vert_tx:.3f}" y="{-vert_ty:.3f}" text-anchor="middle" '
                        f'transform="rotate(90,{vert_tx:.3f},{-vert_ty:.3f})">'
                        f'{vert_text}</text></g>'
                    )
                location_y_drawn = True
            pitch_text = format_de_number(hole_pitch)
            if pitch_text not in used_dimension_labels:
                used_dimension_labels.add(pitch_text)
                text_x = (lx + rx) * 0.5
                pitch_pref_y = y_dim - (2.0 / scale) if outside_placement else y_dim + (2.0 / scale)
                text_y = _reserve_view_label_position(
                    pitch_text,
                    text_x,
                    pitch_pref_y,
                    text_size,
                    "middle",
                    used_label_y,
                    label_gap,
                    label_min_y,
                    label_max_y,
                    collision_boxes,
                )
                pitch_text_box = _feature_text_box(pitch_text, text_x, text_y, "middle")
                collision_boxes.append(pitch_text_box)
                _record_dimension_entry(
                    metadata,
                    "feature_dimensions",
                    dim_type="hole_pitch",
                    axis="H",
                    style="line",
                    outside=outside_placement,
                    measurement_box=pitch_measurement_box,
                    text_box=pitch_text_box,
                )
                parts.append(
                    _feature_text_svg(
                        pitch_text,
                        text_x,
                        text_y,
                        text_size,
                        anchor="middle",
                    )
                )
            pitch_drawn = True
    if (
        _allow("hole_pitch")
        and allow_hole_pitch_dimension
        and (not pitch_drawn)
        and hole_pitch
        and hole_pitch > 0
        and not pattern_is_radial
    ):
        bbox = feature_payload.get("bbox_mm") or {}
        longest_axis = str(feature_payload.get("longest_axis", ""))
        longest_len = _optional_float(bbox.get(longest_axis)) or _optional_float(feature_payload.get("hole_pitch_mm")) or 1.0
        ratio = max(0.2, min(0.9, hole_pitch / max(longest_len, 1e-6)))
        span = (max_x - min_x) * ratio
        cx = (min_x + max_x) * 0.5
        lx = cx - span * 0.5
        rx = cx + span * 0.5
        if outside_placement:
            y_dim = _allocate_horizontal_outside_y(lx, rx, min_y)
        else:
            y_dim = min_y + (7.0 / scale)
            y_dim = max(min_y + (2.5 / scale), min(max_y - (2.5 / scale), y_dim))
        parts.append(
            f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
            f'stroke-linecap="butt" stroke-linejoin="miter">'
            f'<line x1="{lx:.3f}" y1="{y_dim:.3f}" x2="{rx:.3f}" y2="{y_dim:.3f}" />'
            "</g>"
        )
        fallback_pitch_measurement_box = _line_collision_box(lx, y_dim, rx, y_dim, summary_line_pad)
        collision_boxes.append(fallback_pitch_measurement_box)
        parts.append(
            f'<g fill="rgb(0, 0, 0)" stroke="none">'
            f'<polygon points="{lx:.3f},{y_dim:.3f} {lx + arrow_len:.3f},{y_dim - arrow_half:.3f} {lx + arrow_len:.3f},{y_dim + arrow_half:.3f}" />'
            f'<polygon points="{rx:.3f},{y_dim:.3f} {rx - arrow_len:.3f},{y_dim - arrow_half:.3f} {rx - arrow_len:.3f},{y_dim + arrow_half:.3f}" />'
            "</g>"
        )
        collision_boxes.append(
            (
                min(lx, lx + arrow_len) - arrow_pad,
                max(lx, lx + arrow_len) + arrow_pad,
                y_dim - arrow_half - arrow_pad,
                y_dim + arrow_half + arrow_pad,
            )
        )
        collision_boxes.append(
            (
                min(rx, rx - arrow_len) - arrow_pad,
                max(rx, rx - arrow_len) + arrow_pad,
                y_dim - arrow_half - arrow_pad,
                y_dim + arrow_half + arrow_pad,
            )
        )
        pitch_text = format_de_number(hole_pitch)
        if pitch_text not in used_dimension_labels:
            used_dimension_labels.add(pitch_text)
            text_x = (lx + rx) * 0.5
            pitch_pref_y = y_dim - (2.0 / scale) if outside_placement else y_dim + (2.0 / scale)
            text_y = _reserve_view_label_position(
                pitch_text,
                text_x,
                pitch_pref_y,
                text_size,
                "middle",
                used_label_y,
                label_gap,
                label_min_y,
                label_max_y,
                collision_boxes,
            )
            fallback_pitch_text_box = _feature_text_box(pitch_text, text_x, text_y, "middle")
            collision_boxes.append(fallback_pitch_text_box)
            _record_dimension_entry(
                metadata,
                "feature_dimensions",
                dim_type="hole_pitch",
                axis="H",
                style="line",
                outside=outside_placement,
                measurement_box=fallback_pitch_measurement_box,
                text_box=fallback_pitch_text_box,
            )
            parts.append(
                _feature_text_svg(
                    pitch_text,
                    text_x,
                    text_y,
                    text_size,
                    anchor="middle",
                )
            )

    if edge_location_targets and (
        (_allow("hole_location_x") and not location_x_drawn)
        or (_allow("hole_location_y") and not location_y_drawn)
    ):
        min_h_span = max(1.0, 4.0 / scale)
        horizontal_candidate = None
        horizontal_key = None
        for circle in edge_location_targets:
            left_span = abs(float(circle["cx"]) - min_x)
            right_span = abs(max_x - float(circle["cx"]))
            if left_span > min_h_span:
                key = (left_span, -float(circle.get("r", 0.0)))
                if horizontal_key is None or key < horizontal_key:
                    horizontal_key = key
                    horizontal_candidate = ("left", circle)
            if right_span > min_h_span:
                key = (right_span, -float(circle.get("r", 0.0)))
                if horizontal_key is None or key < horizontal_key:
                    horizontal_key = key
                    horizontal_candidate = ("right", circle)
        if _allow("hole_location_x") and horizontal_candidate and not location_x_drawn:
            _draw_edge_location_dimension("H", horizontal_candidate[0], horizontal_candidate[1])

        min_v_span = max(1.0, 4.0 / scale)
        vertical_candidate = None
        vertical_key = None
        for circle in edge_location_targets:
            top_span = abs(float(circle["cy"]) - min_y)
            bottom_span = abs(max_y - float(circle["cy"]))
            if top_span > min_v_span:
                key = (top_span, -float(circle.get("r", 0.0)))
                if vertical_key is None or key < vertical_key:
                    vertical_key = key
                    vertical_candidate = ("top", circle)
            if bottom_span > min_v_span:
                key = (bottom_span, -float(circle.get("r", 0.0)))
                if vertical_key is None or key < vertical_key:
                    vertical_key = key
                    vertical_candidate = ("bottom", circle)
        if _allow("hole_location_y") and vertical_candidate and not location_y_drawn:
            _draw_edge_location_dimension("V", vertical_candidate[0], vertical_candidate[1])

    # Diameter annotation for dominant hole size.
    hole_dia = _optional_float(feature_payload.get("hole_diameter_mm"))
    if pattern_holes and main_radius > 0:
        visible_pattern_dia = max(0.0, main_radius * 2.0)
        if hole_dia is None or hole_dia <= 0 or abs(hole_dia - visible_pattern_dia) > max(0.5, visible_pattern_dia * 0.15):
            hole_dia = visible_pattern_dia
    if (hole_dia is None or hole_dia <= 0) and main_radius > 0:
        hole_dia = max(0.0, main_radius * 2.0)
    if _allow("hole_diameter") and hole_dia and hole_dia > 0:
        diameter_group_count = 0
        thread_hint_present = bool(
            feature_payload.get("thread_label")
            or _optional_float(feature_payload.get("thread_core_diameter_mm"))
        )
        diameter_tol = max(0.25, hole_dia * 0.08)
        for group in feature_payload.get("hole_groups") or []:
            if not isinstance(group, dict):
                continue
            group_dia = _optional_float(group.get("diameter_mm"))
            if group_dia is None:
                continue
            if abs(group_dia - hole_dia) <= diameter_tol:
                diameter_group_count += 1
        if pattern_holes:
            cx_mean = sum(float(circle["cx"]) for circle in pattern_holes) / len(pattern_holes)
            cy_mean = sum(float(circle["cy"]) for circle in pattern_holes) / len(pattern_holes)
            radial_values = [
                math.hypot(float(circle["cx"]) - cx_mean, float(circle["cy"]) - cy_mean)
                for circle in pattern_holes
            ]
            radial_mean = sum(radial_values) / max(len(radial_values), 1)
            radial_spread = (max(radial_values) - min(radial_values)) if radial_values else 0.0
            target = max(
                pattern_holes,
                key=lambda item: math.hypot(float(item["cx"]) - cx_mean, float(item["cy"]) - cy_mean),
            )
            pattern_count = len(pattern_holes)
            if diameter_group_count > pattern_count:
                pattern_count = min(diameter_group_count, hole_count or diameter_group_count)
            dia_text = f"{pattern_count}x \u00D8 {format_de_number(hole_dia)}"
            if pattern_is_radial:
                dia_text += f" LK \u00D8{format_de_number(radial_mean * 2.0)}"
        elif main_holes:
            target = sorted(main_holes, key=lambda item: (item["cx"], item["cy"]))[0]
            dia_text = f"\u00D8 {format_de_number(hole_dia)}"
        else:
            target = {
                "cx": min_x + (max_x - min_x) * 0.2,
                "cy": min_y + (max_y - min_y) * 0.25,
                "r": max(0.8, 2.0 / scale),
            }
            dia_text = f"\u00D8 {format_de_number(hole_dia)}"
        hole_extent = _summarize_hole_extent(feature_payload, diameter_mm=hole_dia)
        dia_text = _format_hole_callout_text(dia_text, feature_payload, diameter_mm=hole_dia)
        hole_pattern_note_preferred = bool(
            outside_placement
            and (
                bool(feature_payload.get("is_flat"))
                or (
                    str(layout_profile or "").strip().lower() != "milling"
                    and
                    str(view_name or "") == "Front"
                    and rotation_norm in {90, 270}
                    and (
                        len(main_holes) >= 2
                        or thread_hint_present
                        or (
                            str(layout_profile or "").strip().lower() == "milling"
                            and hole_count >= 10
                            and diameter_group_count >= 2
                        )
                    )
                )
            )
        )
        if hole_pattern_note_preferred:
            if bool(feature_payload.get("is_flat")):
                _note_edge_x, _note_sign, anchor = _outside_side_geometry(band_profile.get("preferred_leader_side"))
                text_x = _note_edge_x + _note_sign * max(
                    band_profile.get("side_base_offset", outside_margin * 0.7) * 0.7,
                    5.0 / scale,
                )
                text_y = _reserve_view_label_position(
                    dia_text,
                    text_x,
                    _allocate_horizontal_outside_y(min_x, max_x, min_y),
                    text_size,
                    anchor,
                    used_label_y,
                    label_gap,
                    label_min_y,
                    label_max_y,
                    collision_boxes,
                )
            else:
                narrow_rotated_front_note = (
                    str(view_name or "") == "Front"
                    and rotation_norm in {90, 270}
                    and (max_x - min_x) <= 40.0
                )
                if narrow_rotated_front_note:
                    _note_edge_x, _note_sign, anchor = _outside_side_geometry(
                        band_profile.get("preferred_leader_side")
                    )
                    text_x = _note_edge_x + _note_sign * max(
                        band_profile.get("side_base_offset", outside_margin * 0.7) * 0.9,
                        5.0 / scale,
                    )
                    text_y = _reserve_view_label_position(
                        dia_text,
                        text_x,
                        _allocate_horizontal_outside_y(min_x, max_x, min_y),
                        text_size,
                        anchor,
                        used_label_y,
                        label_gap,
                        label_min_y,
                        label_max_y,
                        collision_boxes,
                    )
                else:
                    anchor = "middle"
                    text_x, text_y = _reserve_top_band_note_position(
                        dia_text,
                        (min_x + max_x) * 0.5,
                        _allocate_horizontal_outside_y(min_x, max_x, min_y),
                        anchor=anchor,
                    )
            if dia_text not in used_dimension_labels:
                used_dimension_labels.add(dia_text)
                dia_text_box = _feature_text_box(dia_text, text_x, text_y, anchor)
                collision_boxes.append(dia_text_box)
                _record_dimension_entry(
                    metadata,
                    "feature_dimensions",
                    dim_type="hole_diameter",
                    axis=None,
                    style="note",
                    outside=False,
                    measurement_box=None,
                    text_box=dia_text_box,
                )
                if hole_extent and hole_extent.get("through") is False and _allow("hole_depth"):
                    _record_dimension_entry(
                        metadata,
                        "feature_dimensions",
                        dim_type="hole_depth",
                        axis=None,
                        style="note",
                        outside=False,
                        measurement_box=None,
                        text_box=dia_text_box,
                    )
                parts.append(
                    _feature_text_svg(
                        dia_text,
                        text_x,
                        text_y,
                        text_size,
                        anchor=anchor,
                    )
                )
            target = None
        if target is None:
            pass
        else:
            center_x = (min_x + max_x) * 0.5
            center_y = (min_y + max_y) * 0.5
            dir_x = -1.0 if float(target["cx"]) <= center_x else 1.0
            dir_y = -1.0 if float(target["cy"]) <= center_y else 1.0
            if outside_placement and str(view_name or "") == "Front" and rotation_norm == 90:
                dir_y = -1.0
            sx = target["cx"] + dir_x * target["r"] * 0.55
            sy = target["cy"] + dir_y * target["r"] * 0.55
            leader_dx = (4.0 / scale) if outside_placement else (5.0 / scale)
            leader_dy = (3.0 / scale) if outside_placement else (4.0 / scale)
            text_dx = (5.5 / scale) if outside_placement else (8.0 / scale)
            if outside_placement:
                ky = sy + dir_y * leader_dy
                leader_band = _allocate_outside_leader_band(
                    sx,
                    sy,
                    ky,
                    preferred_side=band_profile.get("preferred_leader_side"),
                    side_margin_factor=0.45,
                    text_margin_factor=1.1,
                    min_text_offset=text_dx,
                    label_text=dia_text,
                    label_text_size=text_size,
                )
                _suppress_hole_leader = bool(leader_band.get("suppress"))
                if not _suppress_hole_leader:
                    dir_x = leader_band["direction"]
                    anchor = leader_band["anchor"]
                    kx = leader_band["knee_x"]
                    ex = leader_band["text_edge_x"]
                    text_x = ex - (1.0 / scale) if anchor == "end" else ex + (1.0 / scale)
                    ey = ky
            else:
                _suppress_hole_leader = False
                kx = sx + dir_x * leader_dx
                ky = sy + dir_y * leader_dy
                ex = kx + dir_x * text_dx
                ey = ky
                anchor = "end" if dir_x < 0 else "start"
                text_x = ex - (1.0 / scale) if dir_x < 0 else ex + (1.0 / scale)
            if not _suppress_hole_leader:
                parts.append(
                    f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" stroke-linecap="butt">'
                    f'<line x1="{sx:.3f}" y1="{sy:.3f}" x2="{kx:.3f}" y2="{ky:.3f}" />'
                    f'<line x1="{kx:.3f}" y1="{ky:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" />'
                    "</g>"
                )
                line_box_a = _line_collision_box(sx, sy, kx, ky, line_pad)
                line_box_b = _line_collision_box(kx, ky, ex, ey, line_pad)
                collision_boxes.append(line_box_a)
                collision_boxes.append(line_box_b)
                text_y = _reserve_view_label_position(
                    dia_text,
                    text_x,
                    ey - (0.8 / scale) if dir_y < 0 else ey + (0.8 / scale),
                    text_size,
                    anchor,
                    used_label_y,
                    label_gap,
                    label_min_y,
                    label_max_y,
                    collision_boxes,
                )
                if dia_text not in used_dimension_labels:
                    used_dimension_labels.add(dia_text)
                    dia_text_box = _feature_text_box(dia_text, text_x, text_y, anchor)
                    collision_boxes.append(dia_text_box)
                    _record_dimension_entry(
                        metadata,
                        "feature_dimensions",
                        dim_type="hole_diameter",
                        axis=None,
                        style="leader",
                        outside=True,
                        measurement_box=(
                            min(line_box_a[0], line_box_b[0]),
                            max(line_box_a[1], line_box_b[1]),
                            min(line_box_a[2], line_box_b[2]),
                            max(line_box_a[3], line_box_b[3]),
                        ),
                        text_box=dia_text_box,
                    )
                    if hole_extent and hole_extent.get("through") is False and _allow("hole_depth"):
                        _record_dimension_entry(
                            metadata,
                            "feature_dimensions",
                            dim_type="hole_depth",
                            axis=None,
                            style="leader",
                            outside=True,
                            measurement_box=(
                                min(line_box_a[0], line_box_b[0]),
                                max(line_box_a[1], line_box_b[1]),
                                min(line_box_a[2], line_box_b[2]),
                                max(line_box_a[3], line_box_b[3]),
                            ),
                            text_box=dia_text_box,
                        )
                    parts.append(
                        _feature_text_svg(
                            dia_text,
                            text_x,
                            text_y,
                            text_size,
                            anchor=anchor,
                        )
                    )

    # Thread annotation: smallest circle compared to dominant hole group.
    # Suppressed for sheet metal parts with thin walls (threads need engagement depth).
    thread_label = feature_payload.get("thread_label")
    thread_core = _optional_float(feature_payload.get("thread_core_diameter_mm"))
    if not thread_label and thread_core:
        thread_label = infer_metric_thread_label(thread_core)
    # Suppress thread callout when wall thickness is too thin for the thread
    measured_t = _optional_float(feature_payload.get("measured_thickness_mm"))
    if thread_label and measured_t is not None:
        try:
            nom_dia = float(thread_label[1:])
            if measured_t < nom_dia * 0.5:
                thread_label = None
        except (ValueError, IndexError):
            pass
    thread_circle = None
    if circles and main_radius > 0:
        thread_candidates = [circle for circle in circles if circle["r"] < main_radius * 0.78]
        if thread_candidates:
            thread_circle = sorted(thread_candidates, key=lambda item: item["r"])[0]
            if not thread_label:
                candidate_label = infer_metric_thread_label(thread_circle["r"] * 2.0)
                # Also check thickness for SVG-inferred threads
                if candidate_label and measured_t is not None:
                    try:
                        nom_dia = float(candidate_label[1:])
                        if measured_t >= nom_dia * 0.5:
                            thread_label = candidate_label
                    except (ValueError, IndexError):
                        thread_label = candidate_label
                else:
                    thread_label = candidate_label
    _suppress_thread = False
    if _allow("thread_callout") and thread_label:
        if thread_circle is None:
            thread_circle = {
                "cx": min_x + (max_x - min_x) * 0.55,
                "cy": min_y + (max_y - min_y) * 0.45,
                "r": max(0.8, 2.0 / scale),
            }
        if outside_placement:
            sx = thread_circle["cx"] - thread_circle["r"] * 0.7
            sy = thread_circle["cy"] + thread_circle["r"] * 0.45
            ky = sy + (4.0 / scale)
            thread_side_margin_factor = 0.45
            thread_text_margin_factor = 1.2
            thread_min_text_offset = 10.0 / scale
            if str(view_name or "") == "Front" and rotation_norm in {90, 270}:
                thread_side_margin_factor = 0.34
                thread_text_margin_factor = 0.72
                thread_min_text_offset = 6.4 / scale
            thread_preferred_side = band_profile.get("preferred_leader_side")
            if (
                str(view_name or "") == "Front"
                and rotation_norm in {90, 270}
                and hole_dia
                and hole_dia > 0
            ):
                thread_preferred_side = (
                    "left" if str(thread_preferred_side or "right") == "right" else "right"
                )
            thread_band = _allocate_outside_leader_band(
                sx,
                sy,
                ky,
                preferred_side=thread_preferred_side,
                side_margin_factor=thread_side_margin_factor,
                text_margin_factor=thread_text_margin_factor,
                min_text_offset=thread_min_text_offset,
                label_text=_format_thread_callout_text(thread_label, feature_payload),
                label_text_size=text_size,
            )
            if thread_band.get("suppress"):
                _suppress_thread = True
            else:
                kx = thread_band["knee_x"]
                ex = thread_band["text_edge_x"]
                if (
                    str(view_name or "") == "Front"
                    and rotation_norm in {90, 270}
                    and thread_band.get("side") == "right"
                ):
                    thread_clearance = max(
                        band_profile.get("side_step", outside_margin * 0.8),
                        5.5 / scale,
                    )
                    kx += thread_clearance * 0.35
                    ex += thread_clearance
                elif (
                    str(view_name or "") == "Front"
                    and rotation_norm in {90, 270}
                    and thread_band.get("side") == "left"
                ):
                    thread_clearance = max(
                        band_profile.get("side_step", outside_margin * 0.8),
                        5.5 / scale,
                    )
                    kx -= thread_clearance * 0.35
                    ex -= thread_clearance
                if str(view_name or "") == "Front" and rotation_norm in {90, 270} and hole_dia and hole_dia > 0:
                    extra_gap = max(24.0 / scale, band_profile.get("side_step", 0.0) * 2.8)
                    if thread_band.get("side") == "left":
                        ex -= extra_gap
                    else:
                        ex += extra_gap
                ey = ky
                thread_anchor = thread_band["anchor"]
                text_x = ex - (1.0 / scale) if thread_anchor == "end" else ex + (1.0 / scale)
        else:
            sx = thread_circle["cx"] + thread_circle["r"] * 0.7
            sy = thread_circle["cy"] + thread_circle["r"] * 0.7
            kx = sx + (8.0 / scale)
            ky = sy + (5.0 / scale)
            ex = min(max_x - (2.0 / scale), kx + (12.0 / scale))
            ey = ky
            thread_anchor = "start"
            text_x = ex + (1.0 / scale)
        if not _suppress_thread:
            parts.append(
                f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" stroke-linecap="butt">'
                f'<line x1="{sx:.3f}" y1="{sy:.3f}" x2="{kx:.3f}" y2="{ky:.3f}" />'
                f'<line x1="{kx:.3f}" y1="{ky:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" />'
                "</g>"
            )
            line_box_a = _line_collision_box(sx, sy, kx, ky, line_pad)
            line_box_b = _line_collision_box(kx, ky, ex, ey, line_pad)
            collision_boxes.append(line_box_a)
            collision_boxes.append(line_box_b)
            thread_text = _format_thread_callout_text(thread_label, feature_payload)
            text_y = _reserve_view_label_position(
                thread_text,
                text_x,
                ey - (1.1 / scale),
                text_size,
                thread_anchor,
                used_label_y,
                label_gap,
                label_min_y,
                label_max_y,
                collision_boxes,
            )
            if thread_text not in used_dimension_labels:
                used_dimension_labels.add(thread_text)
                thread_text_box = _feature_text_box(thread_text, text_x, text_y, thread_anchor)
                collision_boxes.append(thread_text_box)
                _record_dimension_entry(
                    metadata,
                    "feature_dimensions",
                    dim_type="thread_callout",
                    axis=None,
                    style="leader",
                    outside=True,
                    measurement_box=(
                        min(line_box_a[0], line_box_b[0]),
                        max(line_box_a[1], line_box_b[1]),
                        min(line_box_a[2], line_box_b[2]),
                        max(line_box_a[3], line_box_b[3]),
                    ),
                    text_box=thread_text_box,
                )
                parts.append(
                    _feature_text_svg(
                        thread_text,
                        text_x,
                        text_y,
                        text_size,
                        anchor=thread_anchor,
                    )
                )

    representative_groove = _select_representative_groove()
    if representative_groove and _allow("groove_callout"):
        groove_target = _project_probe_center_to_local(representative_groove.get("center_mm") or {})
        if groove_target is None:
            groove_target = (
                min_x + (max_x - min_x) * 0.55,
                min_y + (max_y - min_y) * 0.52,
            )
        _draw_generic_feature_note(
            "groove_callout",
            _format_groove_callout_text(representative_groove),
            groove_target,
        )

    representative_pocket = _select_representative_pocket()
    if representative_pocket:
        pocket_target = _project_probe_center_to_local(representative_pocket.get("center_mm") or {})
        if pocket_target is None:
            pocket_target = (
                min_x + (max_x - min_x) * 0.5,
                min_y + (max_y - min_y) * 0.35,
            )
        if _allow("pocket_location"):
            _draw_generic_feature_note(
                "pocket_location",
                _format_pocket_location_text(representative_pocket),
                pocket_target,
            )
        if _allow("pocket_depth"):
            _draw_generic_feature_note(
                "pocket_depth",
                _format_pocket_depth_text(representative_pocket),
                pocket_target,
            )

    # Bend radius annotation (sheet metal only)
    bend_r = _optional_float(feature_payload.get("bend_radius_mm"))
    if _allow("bend_radius") and bend_r and bend_r > 0:
        bend_text = f"R{format_de_number(bend_r)}"
        if bend_text not in used_dimension_labels:
            used_dimension_labels.add(bend_text)
            # Place near a bend area — approximate as the center-left of the view
            bx = min_x + (max_x - min_x) * 0.15
            by = min_y + (max_y - min_y) * 0.5
            # Leader line from bend region to text
            ky = by - (6.0 / scale)
            _suppress_bend = False
            if outside_placement:
                bend_band = _allocate_outside_leader_band(
                    bx,
                    by,
                    ky,
                    preferred_side=band_profile.get("preferred_leader_side"),
                    side_margin_factor=0.55,
                    text_margin_factor=0.45,
                    min_side_margin=2.0 / scale,
                    min_text_offset=2.0 / scale,
                    label_text=bend_text,
                    label_text_size=text_size,
                )
                if bend_band.get("suppress"):
                    _suppress_bend = True
                else:
                    kx = bend_band["knee_x"]
                    ex = bend_band["text_edge_x"]
                    bend_anchor = bend_band["anchor"]
            else:
                kx = bx - (8.0 / scale)
                ex = min_x - (2.0 / scale)
                bend_anchor = "end"
            if _suppress_bend:
                pass  # suppressed — skip drawing
            else:
                ey = ky
                parts.append(
                    f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" stroke-linecap="butt">'
                    f'<line x1="{bx:.3f}" y1="{by:.3f}" x2="{kx:.3f}" y2="{ky:.3f}" />'
                    f'<line x1="{kx:.3f}" y1="{ky:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" />'
                    "</g>"
                )
                line_box_a = _line_collision_box(bx, by, kx, ky, line_pad)
                line_box_b = _line_collision_box(kx, ky, ex, ey, line_pad)
                collision_boxes.append(line_box_a)
                collision_boxes.append(line_box_b)
                text_x = ex - (1.0 / scale) if bend_anchor == "end" else ex + (1.0 / scale)
                text_y = _reserve_view_label_position(
                    bend_text,
                    text_x,
                    ey - (1.2 / scale),
                    text_size,
                    bend_anchor,
                    used_label_y,
                    label_gap,
                    min_y,
                    max_y,
                    collision_boxes,
                )
                bend_text_box = _feature_text_box(bend_text, text_x, text_y, bend_anchor)
                collision_boxes.append(bend_text_box)
                _record_dimension_entry(
                    metadata,
                    "feature_dimensions",
                    dim_type="bend_radius",
                    axis=None,
                    style="leader",
                    outside=True,
                    measurement_box=(
                        min(line_box_a[0], line_box_b[0]),
                        max(line_box_a[1], line_box_b[1]),
                        min(line_box_a[2], line_box_b[2]),
                        max(line_box_a[3], line_box_b[3]),
                    ),
                    text_box=bend_text_box,
                )
                parts.append(
                    _feature_text_svg(
                        bend_text,
                        text_x,
                        text_y,
                        text_size,
                        anchor=bend_anchor,
                    )
                )

    # Sheet metal thickness annotation ("s = X,X") — DIN 6930 / ISO 6892
    # Mandatory for sheet metal drawings: identifies material gauge.
    sheet_t = _optional_float(feature_payload.get("measured_thickness_mm"))
    if _allow("sheet_thickness") and sheet_t and sheet_t > 0 and sheet_t <= 10.0:
            thickness_text = f"s = {format_de_number(sheet_t)}"
            if thickness_text not in used_dimension_labels:
                used_dimension_labels.add(thickness_text)
                # Place at bottom-left of the view, below bend radius if present
                tx = min_x + (max_x - min_x) * 0.85
                ty = max_y - (max_y - min_y) * 0.1
                # Leader line from edge region to text
                ky = ty + (3.0 / scale)
                if outside_placement and str(view_name or "") == "Front" and rotation_norm == 90:
                    ky = ty - (3.0 / scale)
                if outside_placement:
                    thickness_side_margin_factor = 0.45
                    thickness_text_margin_factor = 0.75
                    thickness_min_text_offset = 8.0 / scale
                    if (
                        str(view_name or "") == "Front"
                        and rotation_norm in {90, 270}
                        and (max_x - min_x) <= 40.0
                    ):
                        thickness_side_margin_factor = 0.36
                        thickness_text_margin_factor = 0.56
                        thickness_min_text_offset = 5.8 / scale
                    thickness_band = _allocate_outside_leader_band(
                        tx,
                        ty,
                        ky,
                        preferred_side=band_profile.get("preferred_leader_side"),
                        side_margin_factor=thickness_side_margin_factor,
                        text_margin_factor=thickness_text_margin_factor,
                        min_text_offset=thickness_min_text_offset,
                        label_text=thickness_text,
                        label_text_size=text_size,
                    )
                    _suppress_thickness = bool(thickness_band.get("suppress"))
                kx = thickness_band["knee_x"]
                ex = thickness_band["text_edge_x"]
                thickness_anchor = thickness_band["anchor"]
            else:
                _suppress_thickness = False
                kx = max_x + max(outside_margin * 0.45, 2.6 / scale)
                ex = max_x + max(outside_margin * 1.1, 8.0 / scale)
                thickness_anchor = "start"
            if not _suppress_thickness:
                ey = ky
                parts.append(
                    f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" stroke-linecap="butt">'
                    f'<line x1="{tx:.3f}" y1="{ty:.3f}" x2="{kx:.3f}" y2="{ky:.3f}" />'
                    f'<line x1="{kx:.3f}" y1="{ky:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" />'
                    "</g>"
                )
                line_box_a = _line_collision_box(tx, ty, kx, ky, line_pad)
                line_box_b = _line_collision_box(kx, ky, ex, ey, line_pad)
                collision_boxes.append(line_box_a)
                collision_boxes.append(line_box_b)
                text_x = ex - (1.0 / scale) if thickness_anchor == "end" else ex + (1.0 / scale)
                text_y = _reserve_view_label_position(
                    thickness_text,
                    text_x,
                    ey - (0.8 / scale),
                    text_size,
                    thickness_anchor,
                    used_label_y,
                    label_gap,
                    label_min_y,
                    label_max_y,
                    collision_boxes,
                )
                thickness_text_box = _feature_text_box(thickness_text, text_x, text_y, thickness_anchor)
                collision_boxes.append(thickness_text_box)
                _record_dimension_entry(
                    metadata,
                    "feature_dimensions",
                    dim_type="sheet_thickness",
                    axis=None,
                    style="leader",
                    outside=True,
                    measurement_box=(
                        min(line_box_a[0], line_box_b[0]),
                        max(line_box_a[1], line_box_b[1]),
                        min(line_box_a[2], line_box_b[2]),
                        max(line_box_a[3], line_box_b[3]),
                    ),
                    text_box=thickness_text_box,
                )
                parts.append(
                    _feature_text_svg(
                        thickness_text,
                        text_x,
                        text_y,
                        text_size,
                        anchor=thickness_anchor,
                    )
                )

    # Chamfer callouts reuse the existing leader-style renderer and are driven
    # by probe-provided chamfer centers projected into the current view.
    chamfers = feature_payload.get("chamfers") or []
    if _allow("chamfer") and chamfers:
        basis = view_basis(direction) if direction is not None else None
        fallback_positions = (
            (min_x + (max_x - min_x) * 0.12, min_y + (max_y - min_y) * 0.18),
            (max_x - (max_x - min_x) * 0.12, min_y + (max_y - min_y) * 0.18),
            (min_x + (max_x - min_x) * 0.12, max_y - (max_y - min_y) * 0.18),
            (max_x - (max_x - min_x) * 0.12, max_y - (max_y - min_y) * 0.18),
        )
        if basis is not None:
            right, up = basis
        else:
            right, up = None, None
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5
        for index, chamfer in enumerate(chamfers[:4]):
            if not isinstance(chamfer, dict):
                continue
            size_mm = _optional_float(chamfer.get("size_mm"))
            angle_deg = _optional_float(chamfer.get("angle_deg")) or 45.0
            if size_mm is None or size_mm <= 0:
                continue
            count = max(1, int(chamfer.get("count") or 1))
            chamfer_text = f"{format_de_number(size_mm)}\u00D7{angle_deg:.0f}\u00B0"
            if count > 1:
                chamfer_text = f"{count}\u00D7{chamfer_text}"
            if chamfer_text in used_dimension_labels:
                continue
            cx = cy = None
            if right is not None and up is not None:
                center = chamfer.get("center_mm") or {}
                if isinstance(center, dict):
                    px = _optional_float(center.get("x"))
                    py = _optional_float(center.get("y"))
                    pz = _optional_float(center.get("z"))
                    if None not in (px, py, pz):
                        point = App.Vector(float(px), float(py), float(pz))
                        cx = float(point.dot(right))
                        cy = float(point.dot(up))
            if cx is None or cy is None:
                cx, cy = fallback_positions[index % len(fallback_positions)]
            cx = max(min_x + (1.0 / max(scale, 0.05)), min(max_x - (1.0 / max(scale, 0.05)), cx))
            cy = max(min_y + (1.0 / max(scale, 0.05)), min(max_y - (1.0 / max(scale, 0.05)), cy))
            edge_dir = "H" if abs(cy - center_y) >= abs(cx - center_x) else "V"
            parts.append(
                build_chamfer_dimension_svg(
                    (cx, cy),
                    edge_dir,
                    size_mm,
                    angle_deg,
                    scale,
                    stroke_width,
                    line_profile=line_profile,
                    metadata=metadata,
                    label_text=chamfer_text,
                )
            )
            used_dimension_labels.add(chamfer_text)

    return "".join(parts)


# ISO 1101 GD&T characteristic symbols (Unicode approximation for SVG text rendering)
_GDT_SYMBOLS = {
    "straightness":      "\u2014",    # —
    "flatness":          "\u25ad",    # ▭
    "circularity":       "\u25cb",    # ○
    "cylindricity":      "\u232d",    # ⌭
    "line_profile":      "\u2312",    # ⌒
    "surface_profile":   "\u2313",    # ⌓
    "perpendicularity":  "\u27c2",    # ⊥
    "angularity":        "\u2220",    # ∠
    "parallelism":       "\u2225",    # ∥
    "position":          "\u2295",    # ⊕
    "concentricity":     "\u25ce",    # ◎
    "symmetry":          "\u2261",    # ≡
    "circular_runout":   "\u2197",    # ↗
    "total_runout":      "\u2197\u2197",  # ↗↗
}

_GDT_MODIFIER_SYMBOLS = {
    "M": "\u24c2",   # Ⓜ (Maximum Material Condition)
    "L": "\u24c1",   # Ⓛ (Least Material Condition)
    "S": "\u24c8",   # Ⓢ (Regardless of Feature Size — default, often omitted)
    "P": "\u24c5",   # Ⓟ (Projected Tolerance Zone)
}


def _build_gdt_frame_svg(
    x, y,
    characteristic,
    tolerance_value,
    tolerance_modifier=None,
    datum_refs=None,
    cell_height=5.0,
    cell_width=8.0,
    leader_to=None,
):
    """Render an ISO 1101 feature control frame (tolerance frame) at (x, y).

    The frame is a horizontal sequence of compartments:
    [symbol] [tolerance value] [datum A] [datum B] [datum C]

    Parameters:
        x, y: top-left corner of the frame (page coordinates, y increases downward)
        characteristic: GD&T type key (e.g. "perpendicularity")
        tolerance_value: tolerance in mm (e.g. 0.05)
        tolerance_modifier: "M", "L", "S", "P" or None
        datum_refs: list of datum letters, e.g. ["A", "B"]
        cell_height: height of each compartment
        cell_width: width of the symbol and datum cells
        leader_to: optional (lx, ly) for a leader line from the frame to a feature
    Returns:
        SVG string
    """
    datum_refs = datum_refs or []
    sw = 0.25  # stroke width for the frame
    text_size = cell_height * 0.7
    text_style = (
        f"font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        f"font-size: {text_size:.1f}px; font-style: normal; font-weight: normal;"
    )

    parts = [f'<g class="iso1101-gdt">']

    # Compartment 1: characteristic symbol
    sym = _GDT_SYMBOLS.get(characteristic, "?")
    # Compartment 2: tolerance value (wider)
    tol_text = format_de_number(tolerance_value)
    if tolerance_modifier and tolerance_modifier in _GDT_MODIFIER_SYMBOLS:
        tol_text += " " + _GDT_MODIFIER_SYMBOLS[tolerance_modifier]
    tol_cell_width = max(cell_width * 1.5, len(tol_text) * text_size * 0.7)

    # Calculate total frame width
    n_datum = len(datum_refs)
    total_w = cell_width + tol_cell_width + n_datum * cell_width

    # Outer frame rectangle
    parts.append(
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{total_w:.2f}" height="{cell_height:.2f}" '
        f'fill="white" stroke="#000" stroke-width="{sw}"/>'
    )

    # Vertical dividers and cell contents
    cx = x

    # Cell 1: symbol
    parts.append(
        f'<line x1="{cx + cell_width:.2f}" y1="{y:.2f}" '
        f'x2="{cx + cell_width:.2f}" y2="{y + cell_height:.2f}" '
        f'stroke="#000" stroke-width="{sw}"/>'
    )
    parts.append(
        f'<text x="{cx + cell_width / 2:.2f}" y="{y + cell_height * 0.75:.2f}" '
        f'text-anchor="middle" style="{text_style}">{escape(sym)}</text>'
    )
    cx += cell_width

    # Cell 2: tolerance value
    parts.append(
        f'<line x1="{cx + tol_cell_width:.2f}" y1="{y:.2f}" '
        f'x2="{cx + tol_cell_width:.2f}" y2="{y + cell_height:.2f}" '
        f'stroke="#000" stroke-width="{sw}"/>'
    )
    parts.append(
        f'<text x="{cx + tol_cell_width / 2:.2f}" y="{y + cell_height * 0.75:.2f}" '
        f'text-anchor="middle" style="{text_style}">{escape(tol_text)}</text>'
    )
    cx += tol_cell_width

    # Datum cells
    for i, datum in enumerate(datum_refs):
        if i < n_datum - 1:
            parts.append(
                f'<line x1="{cx + cell_width:.2f}" y1="{y:.2f}" '
                f'x2="{cx + cell_width:.2f}" y2="{y + cell_height:.2f}" '
                f'stroke="#000" stroke-width="{sw}"/>'
            )
        parts.append(
            f'<text x="{cx + cell_width / 2:.2f}" y="{y + cell_height * 0.75:.2f}" '
            f'text-anchor="middle" style="{text_style}">{escape(datum)}</text>'
        )
        cx += cell_width

    # Leader line from frame to feature
    if leader_to is not None:
        lx, ly = leader_to
        # Connect from left edge center of the frame
        frame_attach_x = x
        frame_attach_y = y + cell_height / 2
        parts.append(
            f'<line x1="{frame_attach_x:.2f}" y1="{frame_attach_y:.2f}" '
            f'x2="{lx:.2f}" y2="{ly:.2f}" '
            f'stroke="#000" stroke-width="{sw}"/>'
        )
        # Arrow at target
        dx = lx - frame_attach_x
        dy = ly - frame_attach_y
        d = math.hypot(dx, dy)
        if d > 1e-6:
            ux, uy = dx / d, dy / d
            ah = 1.2
            parts.append(
                f'<polygon points="{lx:.2f},{ly:.2f} '
                f'{lx - ux * ah * 2 + uy * ah:.2f},{ly - uy * ah * 2 - ux * ah:.2f} '
                f'{lx - ux * ah * 2 - uy * ah:.2f},{ly - uy * ah * 2 + ux * ah:.2f}" '
                f'fill="#000" stroke="none"/>'
            )

    parts.append('</g>')
    return "\n".join(parts)


def _build_datum_flag_svg(x, y, datum_letter, size=5.0):
    """Render an ISO 1101 datum flag (filled triangle + letter) at (x, y).

    The datum flag is a triangle pointing down with the datum letter above.
    """
    sw = 0.25
    text_size = size * 0.7
    text_style = (
        f"font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        f"font-size: {text_size:.1f}px; font-style: normal; font-weight: normal;"
    )
    half = size / 2
    # Square frame with datum letter
    parts = [f'<g class="iso1101-datum">']
    parts.append(
        f'<rect x="{x - half:.2f}" y="{y - size:.2f}" width="{size:.2f}" height="{size:.2f}" '
        f'fill="white" stroke="#000" stroke-width="{sw}"/>'
    )
    parts.append(
        f'<text x="{x:.2f}" y="{y - size * 0.25:.2f}" '
        f'text-anchor="middle" style="{text_style}">{escape(datum_letter)}</text>'
    )
    # Triangle pointing to the surface
    tri_h = size * 0.6
    parts.append(
        f'<polygon points="{x - half:.2f},{y:.2f} {x + half:.2f},{y:.2f} '
        f'{x:.2f},{y + tri_h:.2f}" fill="none" stroke="#000" stroke-width="{sw}"/>'
    )
    parts.append('</g>')
    return "\n".join(parts)


def _iso1302_symbol_svg(x, y, ra_value=None, rz_value=None, removal="any", height=8.0):
    """Render an ISO 1302 surface finish symbol at (x, y) bottom-left of the checkmark.

    Parameters:
        x, y: Position (bottom of the checkmark vertex)
        ra_value: Ra roughness value (e.g. 3.2) or None
        rz_value: Rz roughness value (e.g. 12.5) or None
        removal: "any" (basic symbol), "required" (line on top), "prohibited" (circle)
        height: Symbol height in mm (default 8mm per ISO 1302)
    Returns:
        SVG string for the symbol
    """
    sw = 0.3  # stroke width
    h = height
    # The checkmark: short leg at 60° left, long leg at 60° right
    # Vertex at (x, y), short leg goes up-left, long leg goes up-right
    short_len = h * 0.35
    long_len = h
    # Short leg: 60° from vertical going left
    sx = x - short_len * math.sin(math.radians(60))
    sy = y - short_len * math.cos(math.radians(60))
    # Long leg: 60° from vertical going right
    lx = x + long_len * math.sin(math.radians(60))
    ly = y - long_len * math.cos(math.radians(60))

    parts = [f'<g class="iso1302-surface">']
    # Checkmark shape
    parts.append(
        f'<polyline points="{sx:.2f},{sy:.2f} {x:.2f},{y:.2f} {lx:.2f},{ly:.2f}" '
        f'fill="none" stroke="#000" stroke-width="{sw}" stroke-linejoin="miter"/>'
    )

    # Horizontal extension line from top of long leg
    ext_len = h * 0.8
    if removal == "required":
        # Line on top = material removal required
        parts.append(
            f'<line x1="{lx:.2f}" y1="{ly:.2f}" x2="{lx + ext_len:.2f}" y2="{ly:.2f}" '
            f'stroke="#000" stroke-width="{sw}"/>'
        )
    elif removal == "prohibited":
        # Circle at vertex = material removal not permitted
        cr = h * 0.12
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y - cr * 1.5:.2f}" r="{cr:.2f}" '
            f'fill="none" stroke="#000" stroke-width="{sw}"/>'
        )
        parts.append(
            f'<line x1="{lx:.2f}" y1="{ly:.2f}" x2="{lx + ext_len:.2f}" y2="{ly:.2f}" '
            f'stroke="#000" stroke-width="{sw}"/>'
        )
    else:
        # Basic symbol — just extend the top line
        parts.append(
            f'<line x1="{lx:.2f}" y1="{ly:.2f}" x2="{lx + ext_len:.2f}" y2="{ly:.2f}" '
            f'stroke="#000" stroke-width="{sw}"/>'
        )

    # Ra/Rz text above the extension line
    text_style = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 3.2px; font-style: normal; font-weight: normal;"
    )
    text_x = lx + 0.5
    text_y = ly - 1.0
    if ra_value is not None:
        parts.append(
            f'<text x="{text_x:.2f}" y="{text_y:.2f}" style="{text_style}">Ra {ra_value}</text>'
        )
    elif rz_value is not None:
        parts.append(
            f'<text x="{text_x:.2f}" y="{text_y:.2f}" style="{text_style}">Rz {rz_value}</text>'
        )

    parts.append('</g>')
    return "\n".join(parts)


def _build_surface_finish_symbol(meta, sheet_value, label_x, base_y, row_step):
    """Build the default surface finish symbol for the drawing (ISO 1302).

    Placed above the title block info area, right-aligned.
    If meta contains surface_ra or surface_rz, a specific value is shown.
    Otherwise shows a general symbol with parentheses (default finish).
    """
    # Determine surface finish parameters from meta
    ra = meta.get("surface_ra")
    rz = meta.get("surface_rz")
    removal = meta.get("surface_removal", "any")

    # Position: above the top info row, right-aligned with value column
    if sheet_value == "A2":
        sym_x = 380
        sym_y = base_y - len([1, 2, 3, 4, 5, 6]) * row_step - 4  # above last info row
    else:
        sym_x = 262
        sym_y = base_y - 6 * row_step - 4

    parts = []

    if ra is not None or rz is not None:
        # Specific default surface finish with parentheses
        # The parenthesized symbol means "all surfaces unless otherwise specified"
        parts.append(_iso1302_symbol_svg(sym_x, sym_y, ra_value=ra, rz_value=rz, removal=removal))
        # Add parentheses around the symbol
        paren_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 10px; font-style: normal; font-weight: normal;"
        )
        parts.append(
            f'<text x="{sym_x - 5:.1f}" y="{sym_y - 1:.1f}" style="{paren_style}">(</text>'
        )
        parts.append(
            f'<text x="{sym_x + 18:.1f}" y="{sym_y - 1:.1f}" style="{paren_style}">)</text>'
        )
    else:
        # No specific finish — show generic symbol indicating "machined surface"
        # Only show if layout_profile is milling or turning (not sheet_metal)
        layout = meta.get("layout_profile", "")
        if layout in ("milling", "turning", "P1.1", "P1.1b", "P1.2", "P2.1", "P3.1"):
            parts.append(_iso1302_symbol_svg(sym_x, sym_y, removal="required"))

    return "\n".join(parts)


def _iso2553_weld_symbol_svg(
    weld_type,
    arrow_x,
    arrow_y,
    ref_angle_deg=30,
    ref_length=15.0,
    arrow_side=True,
    size_s=None,
    size_a=None,
    size_l=None,
    supplementary=None,
):
    """Render an ISO 2553 weld symbol at the given arrow point.

    Parameters:
        weld_type: "fillet", "v_butt", "square_butt", "bevel", "j_groove", "u_groove"
        arrow_x, arrow_y: where the arrow points (joint location)
        ref_angle_deg: angle of the arrow line from horizontal
        ref_length: length of the reference line in mm
        arrow_side: True = symbol below reference line (arrow side), False = above (other side)
        size_s: throat/leg size (e.g. "a3" or "s5")
        size_a: weld cross-section size
        size_l: weld length
        supplementary: "all_around", "field", None
    Returns:
        SVG string
    """
    sw = 0.3
    sym_h = 4.0  # symbol height on reference line
    text_style = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 3.0px; font-style: normal; font-weight: normal;"
    )

    # Arrow line from point to reference line start
    arrow_len = 8.0
    a_rad = math.radians(ref_angle_deg)
    ref_start_x = arrow_x + arrow_len * math.cos(a_rad)
    ref_start_y = arrow_y + arrow_len * math.sin(a_rad)
    ref_end_x = ref_start_x + ref_length
    ref_end_y = ref_start_y

    parts = [f'<g class="iso2553-weld">']

    # Arrow line
    parts.append(
        f'<line x1="{arrow_x:.2f}" y1="{arrow_y:.2f}" '
        f'x2="{ref_start_x:.2f}" y2="{ref_start_y:.2f}" '
        f'stroke="#000" stroke-width="{sw}"/>'
    )
    # Arrowhead
    ah = 1.5
    parts.append(
        f'<polygon points="{arrow_x:.2f},{arrow_y:.2f} '
        f'{arrow_x + ah * 1.5 * math.cos(a_rad) + ah * 0.5 * math.sin(a_rad):.2f},'
        f'{arrow_y + ah * 1.5 * math.sin(a_rad) - ah * 0.5 * math.cos(a_rad):.2f} '
        f'{arrow_x + ah * 1.5 * math.cos(a_rad) - ah * 0.5 * math.sin(a_rad):.2f},'
        f'{arrow_y + ah * 1.5 * math.sin(a_rad) + ah * 0.5 * math.cos(a_rad):.2f}" '
        f'fill="#000" stroke="none"/>'
    )

    # Reference line (solid)
    parts.append(
        f'<line x1="{ref_start_x:.2f}" y1="{ref_start_y:.2f}" '
        f'x2="{ref_end_x:.2f}" y2="{ref_end_y:.2f}" '
        f'stroke="#000" stroke-width="{sw}"/>'
    )

    # Dashed identification line (other side)
    if not arrow_side:
        dash_y = ref_start_y - sym_h * 0.5
        parts.append(
            f'<line x1="{ref_start_x:.2f}" y1="{dash_y:.2f}" '
            f'x2="{ref_end_x:.2f}" y2="{dash_y:.2f}" '
            f'stroke="#000" stroke-width="{sw}" stroke-dasharray="2,1"/>'
        )

    # Weld type symbol on the reference line
    sym_x = ref_start_x + 2.0
    sym_y_base = ref_start_y if arrow_side else ref_start_y - sym_h

    if weld_type == "fillet":
        # Triangle (fillet weld symbol)
        parts.append(
            f'<polygon points="{sym_x:.2f},{sym_y_base:.2f} '
            f'{sym_x + sym_h:.2f},{sym_y_base:.2f} '
            f'{sym_x:.2f},{sym_y_base - sym_h:.2f}" '
            f'fill="none" stroke="#000" stroke-width="{sw}"/>'
        )
    elif weld_type == "v_butt":
        # V shape
        parts.append(
            f'<polyline points="{sym_x:.2f},{sym_y_base - sym_h:.2f} '
            f'{sym_x + sym_h / 2:.2f},{sym_y_base:.2f} '
            f'{sym_x + sym_h:.2f},{sym_y_base - sym_h:.2f}" '
            f'fill="none" stroke="#000" stroke-width="{sw}"/>'
        )
    elif weld_type == "square_butt":
        # Two vertical lines
        parts.append(
            f'<line x1="{sym_x:.2f}" y1="{sym_y_base:.2f}" '
            f'x2="{sym_x:.2f}" y2="{sym_y_base - sym_h:.2f}" '
            f'stroke="#000" stroke-width="{sw}"/>'
        )
        parts.append(
            f'<line x1="{sym_x + sym_h * 0.6:.2f}" y1="{sym_y_base:.2f}" '
            f'x2="{sym_x + sym_h * 0.6:.2f}" y2="{sym_y_base - sym_h:.2f}" '
            f'stroke="#000" stroke-width="{sw}"/>'
        )
    elif weld_type == "bevel":
        # Half-V shape
        parts.append(
            f'<polyline points="{sym_x:.2f},{sym_y_base - sym_h:.2f} '
            f'{sym_x:.2f},{sym_y_base:.2f} '
            f'{sym_x + sym_h:.2f},{sym_y_base - sym_h:.2f}" '
            f'fill="none" stroke="#000" stroke-width="{sw}"/>'
        )

    # Size annotations
    size_text_x = sym_x - 1.0
    size_text_y = sym_y_base - sym_h - 1.5
    size_parts = []
    if size_s:
        size_parts.append(str(size_s))
    if size_a:
        size_parts.append(str(size_a))
    if size_l:
        size_parts.append(str(size_l))
    if size_parts:
        label = " ".join(size_parts)
        parts.append(
            f'<text x="{size_text_x:.2f}" y="{size_text_y:.2f}" style="{text_style}">'
            f'{escape(label)}</text>'
        )

    # Supplementary symbols
    if supplementary == "all_around":
        # Circle at the junction of arrow and reference line
        parts.append(
            f'<circle cx="{ref_start_x:.2f}" cy="{ref_start_y:.2f}" r="1.5" '
            f'fill="none" stroke="#000" stroke-width="{sw}"/>'
        )
    elif supplementary == "field":
        # Flag (filled triangle) at junction
        parts.append(
            f'<polygon points="{ref_start_x:.2f},{ref_start_y:.2f} '
            f'{ref_start_x:.2f},{ref_start_y - 3:.2f} '
            f'{ref_start_x + 2:.2f},{ref_start_y - 1.5:.2f}" '
            f'fill="#000" stroke="none"/>'
        )

    parts.append('</g>')
    return "\n".join(parts)


def build_page_svg(template_path, meta, views_svg, annotation_lines, annotation_y):
    svg = template_path.read_text(encoding="utf-8")
    sheet_value = str(meta.get("sheet_resolved") or meta.get("sheet") or "A3").upper()
    replacements = {
        "TITLE": meta.get("title", "Manufacturing Drawing"),
        "DRAWING_NO": meta.get("drawing_no", "DF-0001"),
        "REV": meta.get("revision", "A"),
        "DATE": meta.get("date", ""),
        "SCALE": meta.get("scale", "auto"),
        "UNIT": meta.get("unit", "mm"),
        "SHEET": sheet_value,
        "AUTHOR": meta.get("author", ""),
        "COMPANY": meta.get("company", ""),
        "MATERIAL": str(meta.get("material", "")).strip() or "-",
    }
    for key, value in replacements.items():
        svg = replace_text(svg, key, value)
    annotation_lines = [line for line in (annotation_lines or []) if str(line).strip()]
    if not annotation_lines:
        annotation_lines = [""]
    text_style = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 4.2px; font-style: normal; font-weight: normal;"
    )
    annotation_chunks = []
    for index, line in enumerate(annotation_lines[:10]):
        y = annotation_y - (index * 4.0)
        annotation_chunks.append(
            f'<text x="12" y="{y:.1f}" style="{text_style}">{escape(str(line))}</text>'
        )
    annotation = "\n".join(annotation_chunks)
    projection_value = str(meta.get("projection", DEFAULT_PROJECTION))
    projection_short = "1. Winkel" if "1." in projection_value or "first" in projection_value.lower() else projection_value
    material_value = str(meta.get("material", "")).strip() or "-"
    deburr_value = str(meta.get("deburr_note", "Alle Kanten 0,2-0,5 entgraten")).strip()
    tolerance_value = str(meta.get("general_tolerance", DEFAULT_GENERAL_TOLERANCE)).strip()
    title_info_style_label = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 3.4px; font-style: normal; font-weight: normal;"
    )
    title_info_style_value = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 4.0px; font-style: normal; font-weight: normal;"
    )
    is_first_angle = "1." in projection_value or "first" in projection_value.lower()
    # Mass (ISO 7200 mandatory field)
    mass_kg = meta.get("mass_kg")
    if mass_kg is not None and mass_kg > 0:
        if mass_kg < 0.01:
            mass_text = f"{mass_kg * 1000:.1f} g"
        elif mass_kg < 10:
            mass_text = f"{mass_kg:.2f} kg"
        else:
            mass_text = f"{mass_kg:.1f} kg"
    else:
        mass_text = "-"
    surface_value = str(meta.get("surface_treatment", "")).strip() or "-"
    info_rows = [
        ("MATERIAL", material_value),
        ("MASSE", mass_text),
        ("OBERFL\u00c4CHE", surface_value),
        ("KANTEN", deburr_value),
        ("PROJEKTION", projection_short if not is_first_angle else ""),
        ("TOLERANZ", f"Allgemeintoleranzen nach {tolerance_value}"),
    ]
    info_chunks = []
    if sheet_value == "A2":
        label_x = 348
        value_x = 374
        base_y = 344.0
        row_step = 3.6
    else:
        label_x = 232
        value_x = 255
        base_y = 228.5
        row_step = 3.2
    for idx, (label, value) in enumerate(info_rows):
        y = base_y - idx * row_step
        info_chunks.append(f'<text x="{label_x}" y="{y:.1f}" style="{title_info_style_label}">{escape(label)}</text>')
        info_chunks.append(f'<text x="{value_x}" y="{y:.1f}" style="{title_info_style_value}">{escape(value)}</text>')
    # ISO first-angle projection symbol (truncated cone + circle per ISO 5456-2)
    projection_symbol = ""
    if is_first_angle:
        proj_row_idx = 2  # PROJEKTION is the 3rd row (idx=2)
        sym_y = base_y - proj_row_idx * row_step
        sym_x = value_x
        # Truncated cone (side view) + circle (front view)
        sw = 0.25
        # Side view: trapezoid
        projection_symbol = (
            f'<g transform="translate({sym_x},{sym_y - 2.5})">'
            f'<line x1="0" y1="0" x2="0" y2="5" stroke="#000" stroke-width="{sw}"/>'
            f'<line x1="2" y1="1" x2="2" y2="4" stroke="#000" stroke-width="{sw}"/>'
            f'<line x1="0" y1="0" x2="2" y2="1" stroke="#000" stroke-width="{sw}"/>'
            f'<line x1="0" y1="5" x2="2" y2="4" stroke="#000" stroke-width="{sw}"/>'
            # Front view: two concentric circles
            f'<circle cx="5.5" cy="2.5" r="2.5" fill="none" stroke="#000" stroke-width="{sw}"/>'
            f'<circle cx="5.5" cy="2.5" r="1.0" fill="none" stroke="#000" stroke-width="{sw}"/>'
            # Horizontal + vertical center lines
            f'<line x1="2.5" y1="2.5" x2="8.5" y2="2.5" stroke="#000" stroke-width="0.12" stroke-dasharray="0.8,0.4"/>'
            f'<line x1="5.5" y1="-0.5" x2="5.5" y2="5.5" stroke="#000" stroke-width="0.12" stroke-dasharray="0.8,0.4"/>'
            f'</g>'
        )
    title_info = "\n".join(info_chunks)

    # ISO 1302 surface finish symbol (default/general surface requirement)
    # Placed above the title block, right-aligned (ISO convention)
    surface_finish_svg = _build_surface_finish_symbol(meta, sheet_value, label_x, base_y, row_step)

    return svg.replace("</svg>", f"{views_svg}\n{annotation}\n{title_info}\n{projection_symbol}\n{surface_finish_svg}\n</svg>")


def build_flat_pattern_overlay(
    view_data,
    *,
    sheet_name,
    sheet_w,
    draw_bottom,
    margin,
    layout_profile,
    feature_payload,
    flat_pattern_mode,
    unfold_result=None,
    sheet_metal_subtype=None,
    dim_plan=None,
):
    if layout_profile != "sheet_metal":
        return "", None
    # Laserteile (bend_count=0): no Abwicklung needed — flat pattern = top view
    if sheet_metal_subtype == "laserteil":
        return "", None

    # Flat pattern area: dedicated 3rd column on the right side of the drawing.
    # The 4 orthographic views use 72% of the width; the Abwicklung column gets 28%.
    avail_draw_w = sheet_w - 2 * margin
    avail_draw_h = draw_bottom - margin

    # The 3rd column for sheet_metal layout
    views_col_w = avail_draw_w * 0.60
    abwicklung_col_w = avail_draw_w - views_col_w  # ~40%
    area_w = abwicklung_col_w - 4.0   # 4mm internal padding
    area_h = avail_draw_h * 0.85      # 85% of drawing height

    area_w = max(80.0, area_w)
    area_h = max(80.0, area_h)
    # Position: centered in the 3rd column, vertically centered
    flat_cx = margin + views_col_w + abwicklung_col_w * 0.5
    flat_cy = margin + avail_draw_h * 0.50

    text_style = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 3.4px; font-style: normal; font-weight: normal;"
    )
    dim_style = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 3.0px; font-style: normal; font-weight: normal;"
    )
    title_x = flat_cx - area_w / 2
    title_y = flat_cy - area_h / 2 - 4.0

    flat_pattern = (feature_payload or {}).get("flat_pattern")
    flat_view_plan = get_dimension_plan_view(dim_plan, "FlatPattern")
    planned_flat_length = get_dimension_plan_dim_value(flat_view_plan, "flat_length")
    planned_flat_width = get_dimension_plan_dim_value(flat_view_plan, "flat_width")

    # ---------- Priority 1: Real SheetMetal Unfold (SVG contour from addon) ----------
    if unfold_result and unfold_result.get("ok") and unfold_result.get("outline_svg"):
        fl_model = float(unfold_result["flat_length_mm"])
        fw_model = float(unfold_result["flat_width_mm"])
        fl = planned_flat_length if planned_flat_length and planned_flat_length > 0 else fl_model
        fw = planned_flat_width if planned_flat_width and planned_flat_width > 0 else fw_model
        k_used = float(((feature_payload or {}).get("flat_pattern") or {}).get("k_factor_used") or 0.40)

        outline_svg = unfold_result["outline_svg"]
        outline_uses_y_flip = svg_uses_y_flip(outline_svg)

        # Use extract_svg_bounds() to get the ACTUAL bounds of the outline SVG.
        # The outline is projected by TechDraw in model coordinates; without
        # normalization the origin may be at any offset and Y may be flipped.
        # extract_svg_bounds handles all SVG element types and gives (minX,maxX,minY,maxY).
        try:
            ob = extract_svg_bounds(outline_svg)
            ob = transform_svg_bounds_for_display(ob, flip_y=outline_uses_y_flip)
        except (ValueError, TypeError, AttributeError):
            ob = None
        _min_size = max(fl * 0.05, fw * 0.05, 1.0)  # reasonable minimum: 5% of expected size
        if ob and abs(ob[1] - ob[0]) > _min_size and abs(ob[3] - ob[2]) > _min_size:
            ob_x1, ob_x2, ob_y1, ob_y2 = ob
            ob_w = ob_x2 - ob_x1
            ob_h = ob_y2 - ob_y1
        else:
            # Fallback: assume normalized shape (XMin=YMin=0) using unfold dimensions
            ob_x1, ob_y1 = 0.0, 0.0
            ob_w, ob_h = fl, fw

        # Extract outline-only bounds (without bend line overhangs) for dimension placement.
        # Bend lines in <g class="bend-lines"> may extend beyond the part outline,
        # causing the total SVG bounds to be larger/shifted vs. the actual part.
        outline_only_svg = re.sub(r'<g[^>]*class="bend-lines"[^>]*>.*?</g>', '', outline_svg, flags=re.DOTALL)
        try:
            part_bounds = extract_svg_bounds(outline_only_svg)
            part_bounds = transform_svg_bounds_for_display(part_bounds, flip_y=outline_uses_y_flip)
        except (ValueError, TypeError, AttributeError):
            part_bounds = None
        if part_bounds and abs(part_bounds[1] - part_bounds[0]) > _min_size and abs(part_bounds[3] - part_bounds[2]) > _min_size:
            pb_x1, pb_x2, pb_y1, pb_y2 = part_bounds
        else:
            # Fallback: use full SVG bounds
            pb_x1, pb_x2, pb_y1, pb_y2 = ob_x1, ob_x1 + ob_w, ob_y1, ob_y1 + ob_h

        # Scale SVG contour to fit the allocated area (leave room for dim lines)
        scale_x = (area_w * 0.70) / max(ob_w, 1e-6)
        scale_y = (area_h * 0.55) / max(ob_h, 1e-6)
        draw_scale = min(scale_x, scale_y)
        svg_w = ob_w * draw_scale
        svg_h = ob_h * draw_scale
        svg_x = flat_cx - svg_w / 2
        svg_y = flat_cy - svg_h / 2

        # Transform: map SVG origin (ob_x1, ob_y1) → drawing (svg_x, svg_y).
        # This correctly handles any offset and Y-flip from TechDraw projection.
        tx = svg_x - ob_x1 * draw_scale
        ty = svg_y - ob_y1 * draw_scale

        outline_x1 = tx + pb_x1 * draw_scale
        outline_y1 = ty + pb_y1 * draw_scale
        outline_x2 = tx + pb_x2 * draw_scale
        outline_y2 = ty + pb_y2 * draw_scale
        outline_cx = (outline_x1 + outline_x2) * 0.5
        outline_cy = (outline_y1 + outline_y2) * 0.5
        title_anchor_x = outline_cx
        title_y = max(margin + 4.0, outline_y1 - 6.0)

        # Determine which model dimension maps to SVG X and which to SVG Y.
        # The SVG outline extent tells us the orientation.
        pb_w = pb_x2 - pb_x1
        pb_h = pb_y2 - pb_y1
        if pb_w >= pb_h:
            # SVG X is the longer dimension (fl), SVG Y is shorter (fw)
            dim_h_mm = fl
            dim_v_mm = fw
        else:
            # SVG Y is the longer dimension (fl), SVG X is shorter (fw)
            dim_h_mm = fw
            dim_v_mm = fl

        if os.environ.get("DRAWFORM_DEBUG_DIR"):
            outline_w = outline_x2 - outline_x1
            outline_h = outline_y2 - outline_y1
            print(f"[drawform] ABWICKLUNG: fl={fl:.1f} fw={fw:.1f} ob=({ob_x1:.1f},{ob_y1:.1f},{ob_w:.1f},{ob_h:.1f}) part=({pb_x1:.1f},{pb_y1:.1f},{pb_x2:.1f},{pb_y2:.1f}) outline=({outline_x1:.1f},{outline_y1:.1f},{outline_w:.1f},{outline_h:.1f})")

        parts: list[str] = []
        flat_line_profile = iso128_line_profile(draw_scale)
        flat_stroke_width = float(flat_line_profile.get("visible", compute_stroke_width(draw_scale)))
        styled_outline_svg = apply_iso128_geometry_style(outline_svg, flat_line_profile)
        outline_with_line_profile = re.sub(
            r"<g\s",
            '<g vector-effect="non-scaling-stroke" data-layer="geometry-visible" ',
            styled_outline_svg,
            count=1,
        )
        if outline_with_line_profile == styled_outline_svg:
            outline_with_line_profile = (
                f'<g vector-effect="non-scaling-stroke" data-layer="geometry-visible">'
                f"{styled_outline_svg}</g>"
            )
        # Flat-pattern rule: no center marks/centerlines in the Abwicklung.
        centerline_svg = ""
        centerline_count = 0
        feature_callout_count = 0

        # Render the real outline SVG (bend lines are already embedded in outline_svg
        # as styled <g class="bend-lines"> elements from step_unfold.py)
        parts.append(
            f'<g transform="translate({tx:.3f},{ty:.3f}) scale({draw_scale:.6f})">'
            f'{outline_with_line_profile}'
            f'{centerline_svg}'
            f'</g>'
        )

        # Only draw separate bend lines if NOT already embedded in outline_svg
        # (backward compat with unfold results generated before this fix)
        bend_lines = unfold_result.get("bend_lines") or []
        if bend_lines and 'class="bend-lines"' not in outline_svg:
            for bl in bend_lines:
                bx1 = tx + float(bl["x1"]) * draw_scale
                by1 = ty + float(bl["y1"]) * draw_scale
                bx2 = tx + float(bl["x2"]) * draw_scale
                by2 = ty + float(bl["y2"]) * draw_scale
                if abs(bx1 - bx2) > 0.1 or abs(by1 - by2) > 0.1:
                    parts.append(
                        f'<line x1="{bx1:.3f}" y1="{by1:.3f}" x2="{bx2:.3f}" y2="{by2:.3f}" '
                        f'stroke="rgb(40,40,160)" stroke-width="0.18" stroke-dasharray="2.5,1.0" />'
                    )

        # Flat-pattern rule: only outer dimensions and bend-edge dimensions.
        # Direction/radius legends ("NACH ...") must stay off the Abwicklung.
        bend_lines_data = unfold_result.get("bend_lines") or []
        bend_lines_svg_match = re.search(
            r'(<g[^>]*class="bend-lines"[^>]*>.*?</g>)',
            outline_svg,
            flags=re.DOTALL,
        )
        bend_lines_svg = bend_lines_svg_match.group(1) if bend_lines_svg_match else ""
        bend_legend_count = 0

        # --- Flange dimensions between bend lines ---
        # Collect bend line positions in drawing coordinates.
        # For mostly-vertical bend lines, use X position; for horizontal, use Y.
        bend_positions_x = []  # (x_pos, bend_index) for vertical bend lines
        bend_positions_y = []  # (y_pos, bend_index) for horizontal bend lines
        for bi, bl in enumerate(bend_lines_data):
            bx1 = tx + float(bl["x1"]) * draw_scale
            by1 = ty + float(bl["y1"]) * draw_scale
            bx2 = tx + float(bl["x2"]) * draw_scale
            by2 = ty + float(bl["y2"]) * draw_scale
            bdx = bx2 - bx1
            bdy = by2 - by1
            if abs(bdx) < abs(bdy):
                # Mostly vertical bend line → position along X axis
                bend_positions_x.append(((bx1 + bx2) / 2, bi))
            else:
                # Mostly horizontal bend line → position along Y axis
                bend_positions_y.append(((by1 + by2) / 2, bi))
        if bend_lines_svg:
            bend_positions_x = []
            bend_positions_y = []
            min_bend_svg_length = max(0.5, 3.0 / max(draw_scale, 0.05))
            for segment in extract_edge_segments(bend_lines_svg, min_length=min_bend_svg_length):
                if segment["orientation"] == "v":
                    bend_positions_x.append((tx + ((segment["x1"] + segment["x2"]) * 0.5) * draw_scale, None))
                elif segment["orientation"] == "h":
                    bend_y = transform_svg_y_for_display(
                        (segment["y1"] + segment["y2"]) * 0.5,
                        flip_y=outline_uses_y_flip,
                    )
                    bend_positions_y.append((ty + bend_y * draw_scale, None))

        # Boundaries: stay within the available drawing area
        max_x_bound = margin + avail_draw_w - 2.0   # right edge of drawing
        max_y_bound = draw_bottom - 2.0              # bottom edge of drawing
        flange_dims = []
        flange_dim_line_y = None
        flange_dim_line_x = None
        overall_dim_y = min(outline_y2 + 18.0, max_y_bound - 4.0)
        overall_dim_x = min(outline_x2 + 18.0, max_x_bound - 4.0)

        # Flange dimension lines along X axis: place them closer to the contour than the overall dim.
        flange_segments_x = build_flange_segment_metadata(
            (position for position, _ in bend_positions_x),
            lower=outline_x1,
            upper=outline_x2,
            total_mm=dim_h_mm,
            axis="x",
        )
        if flange_segments_x:
            flange_dim_y = min(outline_y2 + 8.0, overall_dim_y - 6.0)
            flange_ext_y0 = outline_y2
            flange_dim_line_y = flange_dim_y
            flange_dim_style = (
                "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
                "font-size: 2.2px; font-style: normal; font-weight: normal; fill: #000;"
            )
            for segment in flange_segments_x:
                sx1 = float(segment["start"])
                sx2 = float(segment["end"])
                seg_w_mm = float(segment["label_mm"])
                # Extension lines from outline bottom to flange dim line
                parts.append(f'<line x1="{sx1:.3f}" y1="{flange_ext_y0:.3f}" x2="{sx1:.3f}" y2="{flange_dim_y:.3f}" stroke="rgb(0,0,0)" stroke-width="0.12" />')
                parts.append(f'<line x1="{sx2:.3f}" y1="{flange_ext_y0:.3f}" x2="{sx2:.3f}" y2="{flange_dim_y:.3f}" stroke="rgb(0,0,0)" stroke-width="0.12" />')
                # Dimension line
                parts.append(f'<line x1="{sx1:.3f}" y1="{flange_dim_y:.3f}" x2="{sx2:.3f}" y2="{flange_dim_y:.3f}" stroke="rgb(0,0,0)" stroke-width="0.12" />')
                # Arrows (small for flange dims)
                faw, fah = 1.8, 0.3
                parts.append(f'<polygon points="{sx1:.3f},{flange_dim_y:.3f} {sx1+faw:.3f},{flange_dim_y-fah:.3f} {sx1+faw:.3f},{flange_dim_y+fah:.3f}" fill="rgb(0,0,0)" />')
                parts.append(f'<polygon points="{sx2:.3f},{flange_dim_y:.3f} {sx2-faw:.3f},{flange_dim_y-fah:.3f} {sx2-faw:.3f},{flange_dim_y+fah:.3f}" fill="rgb(0,0,0)" />')
                # Label
                label_x = (sx1 + sx2) / 2
                parts.append(f'<text x="{label_x:.3f}" y="{flange_dim_y - 0.8:.3f}" style="{flange_dim_style}" text-anchor="middle">{format_de_number(seg_w_mm)}</text>')
            flange_dims.extend(
                {
                    "axis": "x",
                    "start": round(float(segment["start"]), 2),
                    "end": round(float(segment["end"]), 2),
                    "label_mm": round(float(segment["label_mm"]), 2),
                }
                for segment in flange_segments_x
            )

        # Flange dimension lines along Y axis: place them closer to the contour than the overall dim.
        flange_segments_y = build_flange_segment_metadata(
            (position for position, _ in bend_positions_y),
            lower=outline_y1,
            upper=outline_y2,
            total_mm=dim_v_mm,
            axis="y",
        )
        if flange_segments_y:
            flange_dim_x = min(outline_x2 + 8.0, overall_dim_x - 6.0)
            flange_ext_x0 = outline_x2
            flange_dim_line_x = flange_dim_x
            flange_dim_style = (
                "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
                "font-size: 2.2px; font-style: normal; font-weight: normal; fill: #000;"
            )
            for segment in flange_segments_y:
                sy1 = float(segment["start"])
                sy2 = float(segment["end"])
                seg_h_mm = float(segment["label_mm"])
                parts.append(f'<line x1="{flange_ext_x0:.3f}" y1="{sy1:.3f}" x2="{flange_dim_x:.3f}" y2="{sy1:.3f}" stroke="rgb(0,0,0)" stroke-width="0.12" />')
                parts.append(f'<line x1="{flange_ext_x0:.3f}" y1="{sy2:.3f}" x2="{flange_dim_x:.3f}" y2="{sy2:.3f}" stroke="rgb(0,0,0)" stroke-width="0.12" />')
                parts.append(f'<line x1="{flange_dim_x:.3f}" y1="{sy1:.3f}" x2="{flange_dim_x:.3f}" y2="{sy2:.3f}" stroke="rgb(0,0,0)" stroke-width="0.12" />')
                faw, fah = 1.8, 0.3
                parts.append(f'<polygon points="{flange_dim_x:.3f},{sy1:.3f} {flange_dim_x-fah:.3f},{sy1+faw:.3f} {flange_dim_x+fah:.3f},{sy1+faw:.3f}" fill="rgb(0,0,0)" />')
                parts.append(f'<polygon points="{flange_dim_x:.3f},{sy2:.3f} {flange_dim_x-fah:.3f},{sy2-faw:.3f} {flange_dim_x+fah:.3f},{sy2-faw:.3f}" fill="rgb(0,0,0)" />')
                label_y = (sy1 + sy2) / 2
                parts.append(
                    f'<text x="{flange_dim_x + 1.0:.3f}" y="{label_y:.3f}" style="{flange_dim_style}" text-anchor="middle" '
                    f'transform="rotate(-90,{flange_dim_x + 1.0:.3f},{label_y:.3f})">{format_de_number(seg_h_mm)}</text>'
                )
            flange_dims.extend(
                {
                    "axis": "y",
                    "start": round(float(segment["start"]), 2),
                    "end": round(float(segment["end"]), 2),
                    "label_mm": round(float(segment["label_mm"]), 2),
                }
                for segment in flange_segments_y
            )

        # Arrow helper for dimension lines
        aw, ah = 2.5, 0.4

        def _arrow(ax, ay, direction):
            if direction == "left":
                pts = f"{ax:.3f},{ay:.3f} {ax+aw:.3f},{ay-ah:.3f} {ax+aw:.3f},{ay+ah:.3f}"
            elif direction == "right":
                pts = f"{ax:.3f},{ay:.3f} {ax-aw:.3f},{ay-ah:.3f} {ax-aw:.3f},{ay+ah:.3f}"
            elif direction == "up":
                pts = f"{ax:.3f},{ay:.3f} {ax-ah:.3f},{ay+aw:.3f} {ax+ah:.3f},{ay+aw:.3f}"
            else:
                pts = f"{ax:.3f},{ay:.3f} {ax-ah:.3f},{ay-aw:.3f} {ax+ah:.3f},{ay-aw:.3f}"
            return f'<polygon points="{pts}" fill="rgb(0,0,0)" />'

        # Horizontal dimension (flat length) below the outline
        dim_y_h = overall_dim_y
        ext_y0 = outline_y2
        parts.append(f'<line x1="{outline_x1:.3f}" y1="{ext_y0:.3f}" x2="{outline_x1:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{outline_x2:.3f}" y1="{ext_y0:.3f}" x2="{outline_x2:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{outline_x1:.3f}" y1="{dim_y_h:.3f}" x2="{outline_x2:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(_arrow(outline_x1, dim_y_h, "left"))
        parts.append(_arrow(outline_x2, dim_y_h, "right"))
        parts.append(f'<text x="{outline_cx:.3f}" y="{dim_y_h - 1.0:.3f}" style="{dim_style}" text-anchor="middle">{format_de_number(dim_h_mm)}</text>')

        # Vertical dimension (flat width) to the right of outline
        dim_x_v = overall_dim_x
        ext_x0 = outline_x2
        mid_y = outline_cy
        parts.append(f'<line x1="{ext_x0:.3f}" y1="{outline_y1:.3f}" x2="{dim_x_v:.3f}" y2="{outline_y1:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{ext_x0:.3f}" y1="{outline_y2:.3f}" x2="{dim_x_v:.3f}" y2="{outline_y2:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{dim_x_v:.3f}" y1="{outline_y1:.3f}" x2="{dim_x_v:.3f}" y2="{outline_y2:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(_arrow(dim_x_v, outline_y1, "up"))
        parts.append(_arrow(dim_x_v, outline_y2, "down"))
        parts.append(
            f'<text x="{dim_x_v + 1.0:.3f}" y="{mid_y:.3f}" style="{dim_style}" text-anchor="middle" '
            f'transform="rotate(-90,{dim_x_v + 1.0:.3f},{mid_y:.3f})">{format_de_number(dim_v_mm)}</text>'
        )

        # Title
        title_bold_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 4.0px; font-style: normal; font-weight: bold; fill: #000;"
        )
        subtitle_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 2.8px; font-style: normal; font-weight: normal; fill: #555;"
        )
        bend_count = unfold_result.get("bend_count", 0)
        k_subtitle = f"K={format_de_number(k_used, 2)} \u2014 {bend_count} Biegung{'en' if bend_count != 1 else ''}"
        note_parts = [
            f'<text x="{title_anchor_x:.1f}" y="{title_y:.1f}" style="{title_bold_style}" text-anchor="middle">ABWICKLUNG</text>',
            f'<text x="{title_anchor_x:.1f}" y="{title_y + 5.0:.1f}" style="{subtitle_style}" text-anchor="middle">{escape(k_subtitle)}</text>',
        ]

        # Collect validation metadata for automated quality checks
        abwicklung_meta = {
            "source": "sheetmetal_unfold",
            "outline_bounds": [round(outline_x1, 2), round(outline_y1, 2),
                               round(outline_x2, 2), round(outline_y2, 2)],
            "dim_h_line_y": round(dim_y_h, 2),
            "dim_h_endpoints": [round(outline_x1, 2), round(outline_x2, 2)],
            "dim_v_line_x": round(dim_x_v, 2),
            "dim_v_endpoints": [round(outline_y1, 2), round(outline_y2, 2)],
            "dim_h_label_mm": round(dim_h_mm, 2),
            "dim_v_label_mm": round(dim_v_mm, 2),
            "model_fl_mm": round(fl_model, 2),
            "model_fw_mm": round(fw_model, 2),
            "plan_fl_mm": round(planned_flat_length, 2) if planned_flat_length else None,
            "plan_fw_mm": round(planned_flat_width, 2) if planned_flat_width else None,
            "bend_count": bend_count,
            "bend_line_count": len(bend_lines_data),
            "bend_annotations": 0,
            "bend_legend_count": bend_legend_count,
            "centerline_count": int(centerline_count),
            "feature_callout_count": int(feature_callout_count),
            "plan_dimension_types": ["flat_length", "flat_width"],
            "drawing_area": [round(margin, 2), round(margin, 2),
                             round(margin + avail_draw_w, 2), round(draw_bottom, 2)],
        }
        abwicklung_meta["flange_dims"] = flange_dims
        if flange_dim_line_y is not None:
            abwicklung_meta["flange_dim_line_y"] = round(flange_dim_line_y, 2)
        if flange_dim_line_x is not None:
            abwicklung_meta["flange_dim_line_x"] = round(flange_dim_line_x, 2)

        return "\n".join(parts) + "\n" + "\n".join(note_parts), abwicklung_meta

    # ---------- Priority 2: Mathematical fallback (simple geometry only) ----------
    if (flat_pattern and flat_pattern.get("flat_length_mm") and flat_pattern.get("flat_width_mm")
            and not flat_pattern.get("complex_geometry")):
        fl_model = float(flat_pattern["flat_length_mm"])
        fw_model = float(flat_pattern["flat_width_mm"])
        fl = planned_flat_length if planned_flat_length and planned_flat_length > 0 else fl_model
        fw = planned_flat_width if planned_flat_width and planned_flat_width > 0 else fw_model
        complex_geom = bool(flat_pattern.get("complex_geometry"))
        k_used = flat_pattern.get("k_factor_used")

        # Scale the blank rectangle to fit the allocated area (leave room for dim lines)
        scale_x = (area_w * 0.70) / max(fl, 1e-6)
        scale_y = (area_h * 0.55) / max(fw, 1e-6)
        draw_scale = min(scale_x, scale_y)
        rect_w = fl * draw_scale
        rect_h = fw * draw_scale
        rect_x = flat_cx - rect_w / 2
        rect_y = flat_cy - rect_h / 2
        title_anchor_x = rect_x + rect_w * 0.5
        title_y = max(margin + 4.0, rect_y - 6.0)
        sw = max(0.18, 0.35)  # stroke width for the blank outline

        parts: list[str] = []

        # Outer blank rectangle (ISO 128 visible line weight)
        parts.append(
            f'<rect x="{rect_x:.3f}" y="{rect_y:.3f}" '
            f'width="{rect_w:.3f}" height="{rect_h:.3f}" '
            f'fill="none" stroke="rgb(0,0,0)" stroke-width="{sw:.3f}" />'
        )

        # Bend lines: vertical dashed lines at calculated positions.
        # Use flat_extents (per-flange lengths) when available for better accuracy.
        segments = flat_pattern.get("bend_segments") or []
        total_segs_mm = float(flat_pattern.get("total_segments_mm") or 0)
        flat_extents = flat_pattern.get("flat_extents") or []
        def _add_bend_line(bend_x):
            """Draw the bend edge only; bend legends are suppressed on the flat pattern."""
            if rect_x < bend_x < rect_x + rect_w:
                parts.append(
                    f'<line x1="{bend_x:.3f}" y1="{rect_y:.3f}" '
                    f'x2="{bend_x:.3f}" y2="{rect_y + rect_h:.3f}" '
                    f'stroke="rgb(40,40,160)" stroke-width="0.18" '
                    f'stroke-dasharray="2.5,1.0" />'
                )

        if flat_extents and len(flat_extents) >= len(segments):
            # We have per-flange extent data: accumulate positions using actual extents.
            # flat_extents are sorted largest-first; treat first as the base flange.
            # For n bends: flanges = [e0, e1, ..., en] with bends between them.
            x_pos_mm = flat_extents[0] if flat_extents else 0.0
            for i, seg in enumerate(segments):
                allowance = float(seg.get("allowance_mm") or 0)
                bend_x = rect_x + x_pos_mm * draw_scale
                _add_bend_line(bend_x)
                next_extent = flat_extents[i + 1] if i + 1 < len(flat_extents) else 0.0
                x_pos_mm += allowance + next_extent
        else:
            # Fallback: distribute segment lengths evenly
            seg_len_each = total_segs_mm / max(len(segments) + 1, 2) if segments else 0
            x_pos_mm = seg_len_each
            for seg in segments:
                allowance = float(seg.get("allowance_mm") or 0)
                bend_x = rect_x + x_pos_mm * draw_scale
                _add_bend_line(bend_x)
                x_pos_mm += allowance + seg_len_each

        # Arrow helper: filled polygon arrowhead (ISO 129-1)
        aw, ah = 2.5, 0.4  # arrow length and half-width in drawing units

        def _arrow(ax, ay, direction):
            if direction == "left":
                pts = f"{ax:.3f},{ay:.3f} {ax+aw:.3f},{ay-ah:.3f} {ax+aw:.3f},{ay+ah:.3f}"
            elif direction == "right":
                pts = f"{ax:.3f},{ay:.3f} {ax-aw:.3f},{ay-ah:.3f} {ax-aw:.3f},{ay+ah:.3f}"
            elif direction == "up":
                pts = f"{ax:.3f},{ay:.3f} {ax-ah:.3f},{ay+aw:.3f} {ax+ah:.3f},{ay+aw:.3f}"
            else:  # down
                pts = f"{ax:.3f},{ay:.3f} {ax-ah:.3f},{ay-aw:.3f} {ax+ah:.3f},{ay-aw:.3f}"
            return f'<polygon points="{pts}" fill="rgb(0,0,0)" />'

        # Horizontal dimension below the rect (flat length)
        dim_y_h = rect_y + rect_h + 8.0
        ext_y0 = rect_y + rect_h
        parts.append(  # extension line left
            f'<line x1="{rect_x:.3f}" y1="{ext_y0:.3f}" '
            f'x2="{rect_x:.3f}" y2="{dim_y_h:.3f}" '
            f'stroke="rgb(0,0,0)" stroke-width="0.18" />'
        )
        parts.append(  # extension line right
            f'<line x1="{rect_x + rect_w:.3f}" y1="{ext_y0:.3f}" '
            f'x2="{rect_x + rect_w:.3f}" y2="{dim_y_h:.3f}" '
            f'stroke="rgb(0,0,0)" stroke-width="0.18" />'
        )
        parts.append(  # dimension line
            f'<line x1="{rect_x:.3f}" y1="{dim_y_h:.3f}" '
            f'x2="{rect_x + rect_w:.3f}" y2="{dim_y_h:.3f}" '
            f'stroke="rgb(0,0,0)" stroke-width="0.18" />'
        )
        parts.append(_arrow(rect_x, dim_y_h, "left"))
        parts.append(_arrow(rect_x + rect_w, dim_y_h, "right"))
        parts.append(  # label
            f'<text x="{flat_cx:.3f}" y="{dim_y_h - 1.0:.3f}" '
            f'style="{dim_style}" text-anchor="middle">'
            f'{format_de_number(fl)}'
            f'</text>'
        )

        # Vertical dimension to the left of the rect (flat width)
        dim_x_v = rect_x - 8.0
        ext_x0 = rect_x
        rect_mid_y = rect_y + rect_h / 2
        parts.append(  # extension line top
            f'<line x1="{ext_x0:.3f}" y1="{rect_y:.3f}" '
            f'x2="{dim_x_v:.3f}" y2="{rect_y:.3f}" '
            f'stroke="rgb(0,0,0)" stroke-width="0.18" />'
        )
        parts.append(  # extension line bottom
            f'<line x1="{ext_x0:.3f}" y1="{rect_y + rect_h:.3f}" '
            f'x2="{dim_x_v:.3f}" y2="{rect_y + rect_h:.3f}" '
            f'stroke="rgb(0,0,0)" stroke-width="0.18" />'
        )
        parts.append(  # dimension line
            f'<line x1="{dim_x_v:.3f}" y1="{rect_y:.3f}" '
            f'x2="{dim_x_v:.3f}" y2="{rect_y + rect_h:.3f}" '
            f'stroke="rgb(0,0,0)" stroke-width="0.18" />'
        )
        parts.append(_arrow(dim_x_v, rect_y, "up"))
        parts.append(_arrow(dim_x_v, rect_y + rect_h, "down"))
        parts.append(  # rotated label
            f'<text x="{dim_x_v - 1.0:.3f}" y="{rect_mid_y:.3f}" '
            f'style="{dim_style}" text-anchor="middle" '
            f'transform="rotate(-90,{dim_x_v - 1.0:.3f},{rect_mid_y:.3f})">'
            f'{format_de_number(fw)}'
            f'</text>'
        )

        # Title: bold "ABWICKLUNG" + subtitle
        title_bold_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 4.0px; font-style: normal; font-weight: bold; fill: #000;"
        )
        subtitle_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 2.8px; font-style: normal; font-weight: normal; fill: #555;"
        )
        k_subtitle = f"berechnet \u2014 K={format_de_number(k_used, 2)}" if k_used is not None else "berechnet"
        if complex_geom:
            k_subtitle += " \u2014 bitte pr\u00fcfen"
        bend_count = len(segments)
        k_subtitle += f" \u2014 {bend_count} Biegung{'en' if bend_count != 1 else ''}" if bend_count else ""
        note_parts = [
            f'<text x="{title_anchor_x:.1f}" y="{title_y:.1f}" style="{title_bold_style}" text-anchor="middle">ABWICKLUNG</text>',
            f'<text x="{title_anchor_x:.1f}" y="{title_y + 5.0:.1f}" style="{subtitle_style}" text-anchor="middle">{escape(k_subtitle)}</text>',
        ]
        abwicklung_meta = {
            "source": "mathematical_fallback",
            "outline_bounds": [round(rect_x, 2), round(rect_y, 2),
                               round(rect_x + rect_w, 2), round(rect_y + rect_h, 2)],
            "dim_h_label_mm": round(fl, 2),
            "dim_v_label_mm": round(fw, 2),
            "model_fl_mm": round(fl_model, 2),
            "model_fw_mm": round(fw_model, 2),
            "plan_fl_mm": round(planned_flat_length, 2) if planned_flat_length else None,
            "plan_fw_mm": round(planned_flat_width, 2) if planned_flat_width else None,
            "bend_count": bend_count,
            "bend_line_count": bend_count,
            "bend_annotations": 0,
            "bend_legend_count": 0,
            "centerline_count": 0,
            "feature_callout_count": 0,
            "plan_dimension_types": ["flat_length", "flat_width"],
            "flange_dims": [],
        }
        return "\n".join(parts) + "\n" + "\n".join(note_parts), abwicklung_meta

    else:
        # Fallback: unfold failed — do NOT render as "ABWICKLUNG" (P0 quality gate).
        # Instead, emit a warning note and mark the result as a quality blocker.
        log("WARNING: Sheet metal unfold failed — skipping Abwicklung (no fallback projection)")
        error_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 3.6px; font-style: normal; font-weight: bold; fill: #c00;"
        )
        note_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 2.8px; font-style: normal; font-weight: normal; fill: #555;"
        )
        fb_note_parts = [
            f'<text x="{flat_cx:.1f}" y="{title_y:.1f}" style="{error_style}" text-anchor="middle">ABWICKLUNG NICHT VERFUEGBAR</text>',
            f'<text x="{flat_cx:.1f}" y="{title_y + 5.0:.1f}" style="{note_style}" text-anchor="middle">Unfold fehlgeschlagen — Zeichnung unvollstaendig</text>',
        ]
        return "\n".join(fb_note_parts), {"source": "fallback_projection", "quality_blocker": True}


def _collect_svg_text_entries(svg_text):
    entries = []
    for match in re.finditer(
        r'<text[^>]*x="([^"]+)"[^>]*y="([^"]+)"[^>]*>(.*?)</text>',
        svg_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        try:
            x = float(match.group(1))
            y = float(match.group(2))
        except (TypeError, ValueError):
            continue
        text = re.sub(r"\s+", " ", (match.group(3) or "")).strip()
        if not text:
            continue
        entries.append({"x": x, "y": y, "text": text})
    return entries


def evaluate_pre_export_quality(report, page_svg, dim_x, dim_y, dim_z, dim_tracking=None):
    issues = []       # warning-level issues
    blockers = []     # blocker-level issues (layout, collision, readability)
    failure_classes = []  # structured FailureClass instances (if module available)
    fc_mod = _get_failure_classes()
    dt = dim_tracking or {}
    text_entries = _collect_svg_text_entries(page_svg)
    dim_texts = []

    # --- P0: Detect fallback projection (fake Abwicklung) as blocker ---
    abw = report.get("abwicklung") or {}
    if abw.get("source") == "fallback_projection":
        blockers.append("Abwicklung nicht verfuegbar: Unfold fehlgeschlagen, keine echte Entfaltung vorhanden.")
        if fc_mod:
            failure_classes.append(fc_mod.FALLBACK_PROJECTION)
    if abw:
        has_flat_bend_legend = any(
            "NACH " in entry["text"]
            for entry in text_entries
        )
        if has_flat_bend_legend:
            issues.append("Unzulaessige Biegehinweise in der Abwicklung erkannt.")
            if fc_mod:
                failure_classes.append(fc_mod.INVALID_BEND_LEGEND)
    skip_markers = (
        "BENENNUNG",
        "FIRMA",
        "ZEICHN",
        "AEND",
        "GEZEICHNET",
        "DATUM",
        "MASSSTAB",
        "EINHEIT",
        "BLATT",
        "Norm:",
        "Projektion:",
        "Allgemeintoleranzen",
        "Alle Masse in",
        "MATERIAL",
        "KANTEN",
        "TOLERANZ",
        "Drawform",
        "DF-",
        "A3",
        "A2",
        "mm",
        "NACH ",       # Bend legends are handled separately and must not count as dimensions
        "Biegung",     # Bend count annotations
        "K=",          # K-factor subtitle
        "K-Faktor",    # K-factor process note
        "ABWICKLUNG",  # Flat pattern title
    )
    for entry in text_entries:
        text = entry["text"]
        if any(marker in text for marker in skip_markers):
            continue
        # Skip single-character zone labels (1-9, a-e) at sheet borders
        if len(text.strip()) <= 1:
            continue
        if re.search(r"\d", text):
            dim_texts.append(entry)

    # --- P1: Hard guard against title block overlap ---
    # Use tracked paper-space dimension boxes (from dim_tracking) instead of raw
    # SVG text parsing.  This avoids false positives from title-block fields
    # that contain digits (date, drawing number, scale, sheet size).
    sheet_name = str(report.get("sheet_name") or "A3").strip().upper()
    title_block_spec = SHEET_SPECS.get(sheet_name, SHEET_SPECS["A3"])
    tb_top_y = float(title_block_spec["height"]) - float(title_block_spec["title_block_h"])
    margin_px = 10.0
    title_block_zone = (margin_px, float(title_block_spec["width"]) - margin_px, tb_top_y, float(title_block_spec["height"]) - margin_px)
    dimension_paper_boxes = dt.get("dimension_paper_boxes") or []
    title_block_overlap_count = 0
    for dbox in dimension_paper_boxes:
        if (
            len(dbox) == 4
            and dbox[0] < title_block_zone[1]  # box left < zone right
            and dbox[1] > title_block_zone[0]  # box right > zone left
            and dbox[2] < title_block_zone[3]  # box top < zone bottom
            and dbox[3] > title_block_zone[2]  # box bottom > zone top
        ):
            title_block_overlap_count += 1
    if title_block_overlap_count:
        blockers.append(
            f"Masse ueberlagern das Schriftfeld ({title_block_overlap_count} Texte)."
        )
        if fc_mod:
            failure_classes.append(fc_mod.TITLE_BLOCK_OVERLAP(title_block_overlap_count))

    views = report.get("views", {}) or {}
    displayed_overall_count = sum(
        int(_optional_float(((view or {}).get("dimension_quality") or {}).get("overall_count")) or 0)
        for view in views.values()
        if isinstance(view, dict)
    )
    overall_tokens = [format_de_number(dim_x), format_de_number(dim_y), format_de_number(dim_z)]
    present_overall_count = sum(
        1 for token in overall_tokens if any(token in item["text"] for item in dim_texts)
    )
    if max(displayed_overall_count, present_overall_count) < 2:
        issues.append("Fehlende Aussenmasse: weniger als zwei Gesamtmasswerte gefunden.")
        if fc_mod:
            failure_classes.append(fc_mod.MISSING_OVERALL_DIMS)

    feature_block = report.get("features", {})
    hole_count = int(_optional_float(feature_block.get("hole_count")) or 0)
    if hole_count > 0:
        planned_hole_labels = []
        dim_plan = (report or {}).get("dimension_plan") or {}
        for view in (dim_plan.get("views") or []):
            if not isinstance(view, dict):
                continue
            for dim in (view.get("dimensions") or []):
                if not isinstance(dim, dict) or dim.get("dim_type") != "hole_diameter":
                    continue
                label = str(dim.get("label") or "").strip()
                if label:
                    planned_hole_labels.append(label)
        has_diameter_callout = any(
            re.match(r"^\s*(?:\d+\s*[xX\u00D7]\s*)?\u00D8\s*\d", item["text"])
            for item in dim_texts
        )
        if not has_diameter_callout:
            has_diameter_callout = any(
                re.match(r"^\s*(?:\d+\s*[xX\u00D7]\s*)?\u00D8\s*\d", label)
                for label in planned_hole_labels
            )
        if not has_diameter_callout:
            issues.append("Fehlende Lochdurchmesserangabe (\u00D8).")
            if fc_mod:
                failure_classes.append(fc_mod.MISSING_HOLE_CALLOUT)
        orthographic_circle_views = [
            name
            for name, view in views.items()
            if isinstance(view, dict)
            and name in ("Front", "Top", "Left")
            and int(_optional_float((view or {}).get("circle_count")) or 0) > 0
        ]
        centerline_total = int(_optional_float((report.get("quality", {}) or {}).get("centerline_total")) or 0)
        if orthographic_circle_views and centerline_total <= 0:
            issues.append("Keine Mittellinien bei vorhandenen Bohrungen erkannt.")
            if fc_mod:
                failure_classes.append(fc_mod.MISSING_CENTERLINES)

    # Duplicate dimension texts (exact duplicates) indicate redundant dimensioning.
    # Only flag as duplicate if the same text appears at NEARBY positions (same view).
    # The same dimension legitimately appears in different views (e.g., height in Front + Top).
    duplicate_values = {}
    for item in dim_texts:
        key = item["text"]
        duplicate_values[key] = duplicate_values.get(key, 0) + 1
    redundant = []
    for text, count in duplicate_values.items():
        if count <= 1 or text in overall_tokens:
            continue
        # Check if duplicates are spatially close (within same view, ~30mm)
        positions = [(it["x"], it["y"]) for it in dim_texts if it["text"] == text]
        has_nearby_pair = False
        for i, (x1, y1) in enumerate(positions):
            for x2, y2 in positions[i + 1:]:
                if abs(x1 - x2) < 30 and abs(y1 - y2) < 30:
                    has_nearby_pair = True
                    break
            if has_nearby_pair:
                break
        if has_nearby_pair:
            redundant.append(text)
    if redundant:
        issues.append(f"Doppelte Masse erkannt: {', '.join(sorted(redundant)[:4])}")
        if fc_mod:
            failure_classes.append(fc_mod.DUPLICATE_DIMENSIONS(sorted(redundant)[:4]))

    quality = report.get("quality", {}) or {}
    current_layout_profile = str((report or {}).get("layout_profile") or "").strip().lower()
    label_out_of_bounds_views = sorted(set(list(quality.get("label_out_of_bounds_views") or [])))
    dimension_out_of_bounds_views = sorted(set(list(quality.get("dimension_out_of_bounds_views") or [])))
    view_overlap_pairs = sorted(set(list(quality.get("view_overlap_pairs") or [])))
    dt["labels_in_bounds"] = not label_out_of_bounds_views
    dt["dimension_graphics_in_bounds"] = not dimension_out_of_bounds_views
    dt["label_out_of_bounds_views"] = label_out_of_bounds_views
    dt["dimension_out_of_bounds_views"] = dimension_out_of_bounds_views
    dt["view_overlap_pairs"] = view_overlap_pairs
    if label_out_of_bounds_views:
        blockers.append(
            "Masszahlen liegen ausserhalb des Zeichenfelds in: "
            + ", ".join(label_out_of_bounds_views)
        )
        if fc_mod:
            failure_classes.append(fc_mod.LABEL_OUT_OF_BOUNDS(label_out_of_bounds_views))
    if dimension_out_of_bounds_views:
        blockers.append(
            "Masslinien oder Massgrafik liegen ausserhalb des Zeichenfelds in: "
            + ", ".join(dimension_out_of_bounds_views)
        )
        if fc_mod:
            failure_classes.append(fc_mod.DIMENSION_OUT_OF_BOUNDS(dimension_out_of_bounds_views))
    if view_overlap_pairs:
        blockers.append(
            "Ansichten ueberlagern sich: " + ", ".join(view_overlap_pairs)
        )
        if fc_mod:
            failure_classes.append(fc_mod.VIEW_OVERLAP(view_overlap_pairs))

    overall_geom_overlap_views = sorted(
        name
        for name, view in views.items()
        if int(_optional_float(((view or {}).get("dimension_quality") or {}).get("overall_geom_overlap_count")) or 0) > 0
    )
    feature_geom_overlap_views = sorted(
        name
        for name, view in views.items()
        if int(_optional_float(((view or {}).get("dimension_quality") or {}).get("feature_geom_overlap_count")) or 0) > 0
    )
    feature_overall_overlap_views = sorted(
        name
        for name, view in views.items()
        if int(_optional_float(((view or {}).get("dimension_quality") or {}).get("feature_overall_overlap_count")) or 0) > 0
    )
    text_overlap_views = sorted(
        name
        for name, view in views.items()
        if int(_optional_float(((view or {}).get("dimension_quality") or {}).get("text_overlap_count")) or 0) > 0
        and not (
            current_layout_profile == "milling"
            and name == "Front"
            and int(_optional_float((view or {}).get("rotation_deg")) or 0) % 180 in {90}
            and str((view or {}).get("feature_dim_mode") or "none") == "outside"
            and int(_optional_float(((view or {}).get("dimension_quality") or {}).get("outside_feature_count")) or 0) >= 2
        )
    )
    if not text_overlap_views:
        has_view_quality = any(
            isinstance(view, dict) and isinstance(view.get("dimension_quality"), dict)
            for view in views.values()
        )
        if not has_view_quality:
            overlap_hits = 0
            for idx, left in enumerate(dim_texts):
                for right in dim_texts[idx + 1 :]:
                    if abs(left["x"] - right["x"]) <= 1.6 and abs(left["y"] - right["y"]) <= 1.2:
                        overlap_hits += 1
                        if overlap_hits >= 2:
                            break
                if overlap_hits >= 2:
                    break
            if overlap_hits > 0:
                blockers.append("Moegliche Ueberlagerung von Masszahlen erkannt.")
    if overall_geom_overlap_views:
        blockers.append(
            "Gesamtmasse liegen zu nah an der Geometrie in: " + ", ".join(overall_geom_overlap_views)
        )
        if fc_mod:
            failure_classes.append(fc_mod.GEOM_OVERLAP_OVERALL(overall_geom_overlap_views))
    if feature_geom_overlap_views:
        blockers.append(
            "Featuremasse kollidieren mit der Teilgeometrie in: " + ", ".join(feature_geom_overlap_views)
        )
        if fc_mod:
            failure_classes.append(fc_mod.GEOM_OVERLAP_FEATURE(feature_geom_overlap_views))
    if feature_overall_overlap_views:
        blockers.append(
            "Feature- und Gesamtmasse ueberlagern sich in: " + ", ".join(feature_overall_overlap_views)
        )
        if fc_mod:
            failure_classes.append(fc_mod.FEATURE_OVERALL_OVERLAP(feature_overall_overlap_views))
    if text_overlap_views:
        blockers.append(
            "Masszahlen ueberlagern sich innerhalb einer Ansicht in: " + ", ".join(text_overlap_views)
        )
        if fc_mod:
            failure_classes.append(fc_mod.TEXT_OVERLAP(text_overlap_views))

    # Views where outside was preferred but neither outside nor internal_fallback achieved it.
    # internal_fallback is a controlled degradation — features are present, just not outside.
    _outside_ok_modes = {"outside", "internal_fallback"}
    outside_preferred_feature_views = sorted(
        name
        for name, view in views.items()
        if int(_optional_float((view or {}).get("feature_dim_text_count")) or 0) > 0
        and bool((view or {}).get("feature_dim_outside_preferred"))
        and str((view or {}).get("feature_dim_mode") or "none") not in _outside_ok_modes
    )
    internal_feature_views = sorted(
        name
        for name, view in views.items()
        if int(_optional_float((view or {}).get("feature_dim_text_count")) or 0) > 0
        and str((view or {}).get("feature_dim_mode") or "none") in ("internal", "internal_fallback")
    )
    if outside_preferred_feature_views:
        issues.append(
            "Featuremasse liegen trotz Aussenpraeferenz noch nicht sauber ausserhalb der Geometrie: "
            + ", ".join(outside_preferred_feature_views)
        )
    dt["feature_dim_outside_views"] = list(dt.get("feature_dim_outside_views", []))
    dt["feature_dim_internal_views"] = sorted(set(list(dt.get("feature_dim_internal_views", [])) + internal_feature_views))
    dt["outside_preferred_feature_views"] = sorted(
        set(list(dt.get("outside_preferred_feature_views", [])) + outside_preferred_feature_views)
    )
    dt["overall_geom_overlap_views"] = overall_geom_overlap_views
    dt["feature_geom_overlap_views"] = feature_geom_overlap_views
    dt["feature_overall_overlap_views"] = feature_overall_overlap_views
    dt["text_overlap_views"] = text_overlap_views

    all_issues = blockers + issues
    if blockers:
        status = "FEHLER"
    elif issues:
        status = "WARNUNG"
    else:
        status = "OK"
    result = {
        "status": status,
        "blockers": blockers,
        "issues": all_issues,
        "dim_metrics": {
            "dim_text_count": int(dt.get("dim_text_count", 0)),
            "step_dim_count": int(dt.get("step_dim_count", 0)),
            "feature_dim_present": bool(dt.get("feature_dim_present", False)),
            "labels_in_bounds": bool(dt.get("labels_in_bounds", True)),
            "dimension_graphics_in_bounds": bool(dt.get("dimension_graphics_in_bounds", True)),
            "feature_dim_outside_views": list(dt.get("feature_dim_outside_views", [])),
            "feature_dim_internal_views": list(dt.get("feature_dim_internal_views", [])),
            "outside_preferred_feature_views": list(dt.get("outside_preferred_feature_views", [])),
            "label_out_of_bounds_views": list(dt.get("label_out_of_bounds_views", [])),
            "dimension_out_of_bounds_views": list(dt.get("dimension_out_of_bounds_views", [])),
            "overall_geom_overlap_views": list(dt.get("overall_geom_overlap_views", [])),
            "feature_geom_overlap_views": list(dt.get("feature_geom_overlap_views", [])),
            "feature_overall_overlap_views": list(dt.get("feature_overall_overlap_views", [])),
            "text_overlap_views": list(dt.get("text_overlap_views", [])),
            "view_overlap_pairs": list(dt.get("view_overlap_pairs", [])),
        },
    }
    if failure_classes:
        result["failure_classes"] = [fc.to_dict() for fc in failure_classes]
    return result


def format_scale(scale_value):
    closest = min(SCALE_CANDIDATES, key=lambda item: abs(item[0] - scale_value))
    return closest[1]


def _format_scale_component(value):
    text = f"{float(value):.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_actual_scale_label(scale_value, *, standard_tolerance=0.05):
    """Render the title-block scale label as the nearest ISO 5455 standard scale.

    Always snaps to the nearest ISO 5455 / DIN supplementary candidate so that
    the title block never displays a non-standard value like '1,65:1'.
    The actual render scale and labeled dimensions are the authoritative source;
    the scale field is informational (ISO 5455 §3).
    The standard_tolerance parameter is retained for API compatibility but is no
    longer used for the snap decision.
    """
    try:
        numeric_scale = float(scale_value)
    except (TypeError, ValueError):
        return "auto"
    if numeric_scale <= 0:
        return "auto"

    _, closest_label = min(SCALE_CANDIDATES, key=lambda item: abs(item[0] - numeric_scale))
    return closest_label


def main():
    if len(sys.argv) < 3:
        raise RuntimeError("Usage: step_to_pdf.py <input.step> <output.pdf>")

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    meta_path = os.getenv("DRAWFORM_META")
    raw_meta = read_metadata(meta_path)
    raw_meta.setdefault("input_path", input_path)  # used for part name extraction
    meta = normalize_export_metadata(raw_meta)
    requested_scale_label = str(meta.get("scale") or "auto")

    log(f"FreeCAD version: {App.Version()[0]}.{App.Version()[1]}.{App.Version()[2]}")
    doc = App.newDocument("DrawformDrawing")
    shape = load_shape(doc, input_path)
    points = collect_points(shape)

    bb = shape.BoundBox
    dim_x = bb.XLength
    dim_y = bb.YLength
    dim_z = bb.ZLength
    log(f"Bounds mm: X={dim_x:.2f} Y={dim_y:.2f} Z={dim_z:.2f}")

    # Mass estimation from shape volume (ISO 7200 title block field)
    # Density lookup by material name (g/cm³). Falls back to steel if unknown.
    _MATERIAL_DENSITY = {
        "steel": 7.85, "stahl": 7.85, "s235": 7.85, "s355": 7.85,
        "stainless": 7.90, "edelstahl": 7.90, "1.4301": 7.90, "1.4404": 7.90,
        "aluminum": 2.70, "aluminium": 2.70, "alu": 2.70,
        "al6061": 2.70, "al7075": 2.81, "almg3": 2.66,
        "copper": 8.96, "kupfer": 8.96, "cu": 8.96,
        "brass": 8.50, "messing": 8.50, "cuzn": 8.50,
        "titanium": 4.50, "titan": 4.50, "ti6al4v": 4.43,
        "plastic": 1.20, "kunststoff": 1.20, "pom": 1.41, "pa": 1.14,
    }
    try:
        volume_mm3 = shape.Volume  # mm³
        mat_raw = str(meta.get("material", "")).strip().lower()
        density_gcm3 = next(
            (d for key, d in _MATERIAL_DENSITY.items() if key in mat_raw),
            7.85,  # default: steel
        )
        density_g_mm3 = density_gcm3 * 1e-3  # g/mm³
        mass_g = volume_mm3 * density_g_mm3
        mass_kg = mass_g / 1000.0
        meta["mass_kg"] = round(mass_kg, 3)
        mat_name = mat_raw or "steel (default)"
        log(f"Mass estimate: {mass_kg:.3f} kg ({mat_name}, density={density_gcm3} g/cm³, volume={volume_mm3:.0f} mm³)")
    except (AttributeError, TypeError, ValueError):
        meta["mass_kg"] = None

    # Complexity scoring for safe_mode
    comp = complexity_score(shape)
    env_safe = os.getenv("DRAWFORM_SAFE_MODE", "").strip()
    safe_mode = env_safe == "1" or comp["score"] > 200
    degrade_steps = []
    if env_safe == "1":
        degrade_steps.append("env_forced")
    log(f"Complexity: faces={comp['faces']} edges={comp['edges']} "
        f"bspline_f={comp['bspline_faces']} score={comp['score']} safe_mode={safe_mode}")

    feature_payload = detect_feature_payload(shape, meta)
    if feature_payload.get("ok") is True:
        log(
            "Feature payload: holes={} hole_dia={} hole_pitch={} bend_r={}".format(
                feature_payload.get("hole_count"),
                feature_payload.get("hole_diameter_mm"),
                feature_payload.get("hole_pitch_mm"),
                feature_payload.get("bend_radius_mm"),
            )
        )
    else:
        log(f"Feature payload unavailable: {feature_payload.get('error', 'unknown')}")

    raw_plan = meta.get("dimension_plan")
    dim_plan = None
    dim_plan_source = "none"
    milling_subtype = None

    requested_sheet = str(os.getenv("DRAWFORM_SHEET_REQUESTED") or resolve_requested_sheet(meta)).strip()
    if requested_sheet.upper() in {"A2", "A3"}:
        requested_sheet = requested_sheet.upper()
    else:
        requested_sheet = "auto"
    layout_profile = select_layout_profile(input_path, feature_payload, dim_x, dim_y, dim_z)
    flat_pattern_mode = detect_flat_pattern_mode(layout_profile)

    # ---------- Run SheetMetal Unfold (subprocess) for sheet_metal parts ----------
    # include_flat_pattern=False means the user explicitly opted out of the Abwicklung view.
    include_flat_pattern = meta.get("include_flat_pattern", True)
    unfold_result = None
    if layout_profile == "sheet_metal" and include_flat_pattern:
        unfold_result = _run_unfold_subprocess(input_path, feature_payload)
        if unfold_result and unfold_result.get("ok"):
            log(f"SheetMetal unfold: {unfold_result['flat_length_mm']}x"
                f"{unfold_result['flat_width_mm']}mm, {unfold_result['bend_count']} bends")
            flat_pattern_mode = "sheetmetal_module"
        else:
            err = (unfold_result or {}).get("error", "unknown")
            log(f"SheetMetal unfold failed: {err} — using fallback")
    elif layout_profile == "sheet_metal" and not include_flat_pattern:
        log("Abwicklung skipped (include_flat_pattern=False)")

    # ---------- Sheet metal subtype: biegeteil vs laserteil ----------
    sheet_metal_subtype = None
    if layout_profile == "sheet_metal":
        if not include_flat_pattern:
            sheet_metal_subtype = "laserteil"  # no Abwicklung wanted → treat as flat/laser
        elif unfold_result and unfold_result.get("ok"):
            bend_count = unfold_result.get("bend_count", 0)
            sheet_metal_subtype = "biegeteil" if bend_count > 0 else "laserteil"
        else:
            sheet_metal_subtype = "biegeteil"  # Safer default — assume bends
        log(f"Sheet metal subtype: {sheet_metal_subtype} "
            f"({unfold_result.get('bend_count', '?') if unfold_result else '?'} bends)", level="DECISION")

    # P0: For sheet_metal, discard meta plans that were built without unfold data.
    # These plans lack correct FlatPattern views and must be rebuilt locally.
    use_meta_plan = isinstance(raw_plan, dict) and raw_plan.get("views")
    if use_meta_plan and layout_profile == "sheet_metal":
        has_flat_pattern_view = any(
            v.get("view_name") == "FlatPattern"
            for v in (raw_plan.get("views") or [])
            if isinstance(v, dict)
        )
        if not has_flat_pattern_view and unfold_result and unfold_result.get("ok"):
            log("Discarding meta dimension_plan for sheet_metal (missing FlatPattern view, unfold now available)")
            use_meta_plan = False

    if use_meta_plan:
        dim_plan = raw_plan
        dim_plan_source = "meta"
        log(f"Dimension plan loaded: part_type={dim_plan.get('part_type')}, "
            f"views={len(dim_plan.get('views', []))}", level="DECISION")
    else:
        dim_plan = build_local_dimension_plan(meta, feature_payload, layout_profile, unfold_result=unfold_result)
        if isinstance(dim_plan, dict) and dim_plan.get("views"):
            dim_plan_source = "local_dse"
            meta["dimension_plan"] = dim_plan
            log(f"Dimension plan built locally: part_type={dim_plan.get('part_type')}, "
                f"views={len(dim_plan.get('views', []))}")
        else:
            dim_plan = None
            log("No dimension plan in meta or local DSE — using hardcoded fallback logic")

    if isinstance(dim_plan, dict) and layout_profile == "milling":
        milling_subtype = str(dim_plan.get("milling_subtype") or "").strip() or None
        if milling_subtype:
            log(f"Milling subtype: {milling_subtype}")

    # Extract surface finish from dimension plan process notes (ISO 1302)
    if isinstance(dim_plan, dict):
        surface_finish = dim_plan.get("surface_finish")
        if isinstance(surface_finish, dict):
            surface_parameter = str(surface_finish.get("parameter") or "").strip().upper()
            surface_value = _optional_float(surface_finish.get("value"))
            if surface_parameter == "RA" and surface_value is not None:
                meta["surface_ra"] = float(surface_value)
            elif surface_parameter == "RZ" and surface_value is not None:
                meta["surface_rz"] = float(surface_value)
        for pn in dim_plan.get("process_notes", []):
            if pn.get("note_type") == "surface_finish":
                sf_text = str(pn.get("text", "")).strip()
                # Parse "Ra 3.2" or "Rz 12.5" format
                if sf_text.upper().startswith("RA"):
                    try:
                        meta["surface_ra"] = float(sf_text[2:].strip().replace(",", "."))
                    except ValueError:
                        pass
                elif sf_text.upper().startswith("RZ"):
                    try:
                        meta["surface_rz"] = float(sf_text[2:].strip().replace(",", "."))
                    except ValueError:
                        pass
                break  # use first surface_finish note

    normalized_sheet = str(meta.get("sheet") or "").strip().upper()
    if normalized_sheet in {"A2", "A3"}:
        sheet_resolved = normalized_sheet
    elif requested_sheet in {"A2", "A3"}:
        sheet_resolved = requested_sheet
    else:
        sheet_resolved = "A3"
    spec = sheet_spec(sheet_resolved)
    meta["sheet_requested"] = requested_sheet
    meta["sheet_resolved"] = sheet_resolved
    meta["layout_profile"] = layout_profile
    meta["flat_pattern_mode"] = flat_pattern_mode
    meta["sheet_metal_subtype"] = sheet_metal_subtype
    meta["milling_subtype"] = milling_subtype
    policy_hints = get_dimension_plan_policy_hints(dim_plan)
    log(
        f"Layout profile: {layout_profile} | Flat pattern mode: {flat_pattern_mode} | "
        f"Sheet requested={requested_sheet}, resolved={sheet_resolved}"
    )

    sheet_w = spec["width"]
    sheet_h = spec["height"]
    margin = 10.0
    title_block_h = spec["title_block_h"]
    origin_x = margin
    origin_y = margin
    avail_w = sheet_w - 2 * margin
    avail_h = sheet_h - title_block_h - 2 * margin
    layout_variant = select_view_layout_variant(
        layout_profile,
        sheet_metal_subtype,
        feature_payload,
        dim_x,
        dim_y,
        dim_z,
        dim_plan=dim_plan,
    )
    view_slots = build_view_slots(layout_variant, origin_x, origin_y, avail_w, avail_h)
    meta["view_layout_variant"] = layout_variant
    log(f"View layout variant: {layout_variant}")
    for view_name in ("Front", "Left", "Top", "Iso"):
        slot = view_slots[view_name]
        log(
            f"Layout slot {view_name}: {slot['w']:.1f} x {slot['h']:.1f} at "
            f"({slot['cx']:.1f}, {slot['cy']:.1f})"
        )

    view_dirs = None if safe_mode else compute_view_directions(
        shape,
        points=points,
        dim_plan=dim_plan,
        feature_payload=feature_payload,
    )
    if safe_mode:
        log("safe_mode: skipping TechDraw-based view scoring, using world axis fallback")
        degrade_steps.append("skip_view_scoring")
    if view_dirs is None:
        log("PCA view detection failed, falling back to world axes.")
        front_dir = App.Vector(0, -1, 0)
        fallback_frame = derive_view_frame(front_dir)
        if fallback_frame is None:
            top_dir = App.Vector(0, 0, 1)
            left_dir = App.Vector(-1, 0, 0)
            right_dir = App.Vector(1, 0, 0)
            iso_dir = App.Vector(1, -1, 1)
        else:
            right_dir, top_dir, iso_dir = fallback_frame
            left_dir = choose_side_direction(shape, right_dir, points=points)
        view_right = right_dir if 'right_dir' in dir() else App.Vector(1, 0, 0)
        view_up = top_dir
    else:
        front_dir = view_dirs["front"]
        top_dir = view_dirs["top"]
        left_dir = view_dirs["left"]
        right_dir = view_dirs.get("right", left_dir.negative())
        iso_dir = view_dirs["iso"]
        view_right = view_dirs.get("view_right", right_dir)
        view_up = view_dirs.get("view_up", top_dir)
        debug = view_dirs["debug"]
        confidence = view_dirs.get("confidence", 0.0)
        log(f"View selection method: {debug.get('method', 'unknown')}")
        log(f"Front selection: {debug.get('chosen_front', 'N/A')}")
        log(f"Confidence: {confidence:.2f}")
        if "candidates" in debug:
            log(f"Candidates: {debug['candidates']}")

    log(f"Front dir: {front_dir.x:.4f},{front_dir.y:.4f},{front_dir.z:.4f}")
    log(f"Top dir: {top_dir.x:.4f},{top_dir.y:.4f},{top_dir.z:.4f}")
    log(f"Right dir: {right_dir.x:.4f},{right_dir.y:.4f},{right_dir.z:.4f}")
    forward_dir = front_dir.negative()
    extent_right = axis_extent(points, right_dir)
    extent_top = axis_extent(points, top_dir)
    extent_forward = axis_extent(points, forward_dir)

    # Fixed projection layout:
    # FRONT at top-left, TOP below FRONT, LEFT to the right of FRONT, ISO bottom-right.
    views = [
        ("Front", front_dir, view_slots["Front"]["cx"], view_slots["Front"]["cy"]),
        ("Left", left_dir, view_slots["Left"]["cx"], view_slots["Left"]["cy"]),
        ("Top", top_dir, view_slots["Top"]["cx"], view_slots["Top"]["cy"]),
        ("Iso", iso_dir, view_slots["Iso"]["cx"], view_slots["Iso"]["cy"]),
    ]

    ortho_padding = 0.90 if layout_profile == "milling" else 0.88
    iso_padding = 0.84 if layout_profile == "milling" else 0.82
    view_data = []
    projection_failures = []
    for name, direction, cx, cy in views:
        svg_group, proj_ok, proj_degraded = safe_project_to_svg(shape, direction, use_safe_mode=safe_mode)
        if proj_degraded:
            if "bbox_wireframe" not in degrade_steps:
                degrade_steps.append("bbox_wireframe")
        if not proj_ok:
            projection_failures.append(name)
            log(f"View {name}: projection FAILED — using empty placeholder")
        svg_bounds = extract_svg_bounds(svg_group)
        proj_bounds = projected_bounds(points, direction) or svg_bounds
        svg_w, svg_h = bounds_size(svg_bounds)
        proj_w, proj_h = bounds_size(proj_bounds)
        proj_swap = abs(svg_w - proj_h) + abs(svg_h - proj_w) < abs(svg_w - proj_w) + abs(svg_h - proj_h)
        aligned_proj_bounds = rotate_bounds_90(proj_bounds) if proj_swap else proj_bounds
        # Neue Rotation: Vergleiche gewünschte Papierachsen mit FreeCADs SVG-Achsen
        svg_x, svg_y = freecad_svg_basis(direction)
        if name == "Front":
            desired_x, desired_y = view_right, view_up
        elif name == "Top":
            desired_x, desired_y = view_right, front_dir
        elif name == "Left":
            desired_x, desired_y = front_dir.negative(), view_up
        else:
            desired_x, desired_y = svg_x, svg_y
        # Finde die Rotation (0/90/180/270), die desired_x/y am besten mit svg_x/y ausrichtet
        best_rot = 0
        best_score = -1e9
        for rot in (0, 90, 180, 270):
            # Rotierte SVG-Achsen
            if rot == 0:
                rx, ry = svg_x, svg_y
            elif rot == 90:
                rx, ry = svg_y.multiply(-1), svg_x
            elif rot == 180:
                rx, ry = svg_x.multiply(-1), svg_y.multiply(-1)
            elif rot == 270:
                rx, ry = svg_y, svg_x.multiply(-1)
            score = desired_x.dot(rx) + desired_y.dot(ry)
            if score > best_score:
                best_score = score
                best_rot = rot
        if name in ("Front", "Top"):
            # Keep engineering convention: primary axis should read horizontally on paper.
            preview_bounds = rotate_bounds_90(svg_bounds) if best_rot % 180 != 0 else svg_bounds
            preview_w, preview_h = bounds_size(preview_bounds)
            if preview_h > preview_w:
                best_rot = (best_rot + 90) % 360
        if name == "Top" and abs(front_dir.x) > 0.9:
            # Disambiguate mirrored top orientation for front views along X:
            # both 90° and 270° can be dimensionally valid, but this keeps
            # feature orientation consistent with expected drawing convention.
            best_rot = (best_rot + 180) % 360
        rotation_deg = best_rot
        bounds_for_layout = rotate_bounds_90(svg_bounds) if rotation_deg % 180 != 0 else svg_bounds
        slot = view_slots[name]
        fit_show_horizontal, fit_show_vertical = resolve_overall_dimension_axes(name, dim_plan=dim_plan)
        enabled = bool(slot.get("enabled", True))
        if not enabled:
            bounds_for_scale = bounds_for_layout
            scale_fit = 0.0
        elif name != "Iso":
            feature_padding_fn = (
                lambda current_scale, _name=name, _plan=dim_plan, _features=feature_payload, _policy=policy_hints: estimate_feature_dimension_padding(
                    current_scale,
                    _name,
                    dim_plan=_plan,
                    feature_payload=_features,
                    policy_hints=_policy,
                )
            )
            bounds_for_scale, scale_fit = compute_dimension_padded_bounds(
                bounds_for_layout,
                slot["w"],
                slot["h"],
                padding=ortho_padding,
                iterations=2,
                show_horizontal=fit_show_horizontal,
                show_vertical=fit_show_vertical,
                extra_padding_fn=feature_padding_fn,
            )
        else:
            bounds_for_scale = bounds_for_layout
            scale_fit = compute_fit_scale(bounds_for_scale, slot["w"], slot["h"], padding=iso_padding)
        geom_w, geom_h = bounds_size(bounds_for_layout)
        fit_w, fit_h = bounds_size(bounds_for_scale)
        view_data.append(
            {
                "name": name,
                "svg": svg_group,
                "svg_bounds": svg_bounds,
                "proj_bounds": aligned_proj_bounds,
                "rotation_deg": rotation_deg,
                "layout_bounds": bounds_for_layout,
                "bounds_for_scale": bounds_for_scale,
                "scale_fit": scale_fit,
                "geom_w": geom_w,
                "geom_h": geom_h,
                "fit_w": fit_w,
                "fit_h": fit_h,
                "cx": slot["cx"],
                "cy": slot["cy"],
                "direction": direction,
                "slot": slot,
                "enabled": enabled,
                "proj_swap": proj_swap,
                "layout_density_escalated": view_requires_layout_escalation(
                    name,
                    dim_plan=dim_plan,
                    feature_payload=feature_payload,
                    policy_hints=policy_hints,
                ),
                "detail_view_recommended": view_prefers_detail_escalation(
                    name,
                    dim_plan=dim_plan,
                    feature_payload=feature_payload,
                    policy_hints=policy_hints,
                ),
            }
        )
        log(
            f"View {name} svg: {svg_w:.2f} x {svg_h:.2f}, proj: {proj_w:.2f} x {proj_h:.2f}, swap={proj_swap}, rotate={rotation_deg}"
        )

    if isinstance(dim_plan, dict):
        circle_counts = {
            item["name"]: int(count_svg_circles(item.get("svg", "")))
            for item in view_data
            if item["name"] in ("Front", "Top", "Left")
        }
        updated_plan = inject_folded_sheet_metal_feature_dims(
            dim_plan,
            feature_payload,
            circle_counts,
        )
        if isinstance(updated_plan, dict):
            if updated_plan != dim_plan:
                log(f"Injected sheet-metal feature dimensions into folded view using circle counts: {circle_counts}")
            dim_plan = updated_plan
            meta["dimension_plan"] = dim_plan

    if isinstance(dim_plan, dict):
        try:
            section_injected = _inject_section_view_into_iso_slot(
                view_data,
                shape,
                points,
                dim_plan,
                iso_padding=iso_padding,
            )
            if not section_injected:
                _inject_detail_view_into_iso_slot(
                    view_data,
                    dim_plan,
                    iso_padding=iso_padding,
                )
        except Exception as exc:
            log(f"Section/detail view injection failed: {exc}")

    ortho_scale = min(
        item["scale_fit"]
        for item in view_data
        if item["name"] in ("Top", "Front", "Left") and item.get("enabled", True)
    )

    # After rotation, width and height may swap.
    def get_paper_dimensions(item, scale, include_fit_padding=False):
        """Get width and height in paper space after rotation."""
        if include_fit_padding:
            return item["fit_w"] * scale, item["fit_h"] * scale
        return item["geom_w"] * scale, item["geom_h"] * scale

    # === BOUNDS CHECKING: Ensure all views fit within drawing area ===
    # Drawing area limits (excluding margin and title block)
    draw_left = margin
    draw_top = margin
    draw_right = sheet_w - margin
    draw_bottom = sheet_h - margin - title_block_h

    front_item = next((item for item in view_data if item["name"] == "Front"), None)
    top_item = next((item for item in view_data if item["name"] == "Top"), None)
    left_item = next((item for item in view_data if item["name"] == "Left"), None)
    iso_item = next((item for item in view_data if item["name"] == "Iso"), None)

    anchor_layout_variants = {"sheet_bent", "flat_dominant", "flat_round_dominant"}
    use_anchor_layout = layout_variant in anchor_layout_variants and front_item is not None
    cluster_left_anchor = None
    cluster_top_anchor = None
    cluster_fit_w_anchor = None
    cluster_fit_h_anchor = None
    if use_anchor_layout:
        anchor_gap_x = 10.0 if layout_variant != "sheet_bent" else 12.0
        anchor_gap_y = 10.0 if layout_variant == "flat_dominant" else 12.0
        if layout_variant == "sheet_bent":
            outer_margin_x = 14.0
            outer_margin_y = 14.0
            margin_factor_x = 0.18
            margin_factor_y = 0.16
            margin_cap_x = 32.0
            margin_cap_y = 28.0
            scale_growth_cap = 1.18
        else:
            outer_margin_x = 10.0
            outer_margin_y = 10.0
            margin_factor_x = 0.12
            margin_factor_y = 0.10
            margin_cap_x = 18.0
            margin_cap_y = 18.0
            scale_growth_cap = 1.25
        draw_w = draw_right - draw_left
        draw_h = draw_bottom - draw_top
        detail_view_requested = any(
            bool(item.get("detail_view_recommended", False))
            for item in view_data
            if item.get("enabled", True)
        )
        dense_flat_detail = layout_variant == "flat_dominant" and detail_view_requested
        iso_reserve_w = 0.0
        if iso_item is not None and iso_item.get("enabled", True):
            if layout_variant == "sheet_bent":
                iso_reserve_w = min(max(54.0, draw_w * 0.16), draw_w * 0.24)
            elif layout_variant == "flat_round_dominant":
                iso_reserve_w = min(max(68.0, draw_w * 0.18), draw_w * 0.24)
            else:
                if dense_flat_detail:
                    iso_reserve_w = min(max(42.0, draw_w * 0.12), draw_w * 0.16)
                else:
                    iso_reserve_w = min(max(60.0, draw_w * 0.17), draw_w * 0.24)

        top_enabled = bool(top_item and top_item.get("enabled", True))
        left_enabled = bool(left_item and left_item.get("enabled", True))
        front_fit_w = _optional_float(front_item.get("fit_w")) or 0.0
        front_fit_h = _optional_float(front_item.get("fit_h")) or 0.0
        top_fit_w = (_optional_float(top_item.get("fit_w")) or 0.0) if top_enabled else 0.0
        top_fit_h = (_optional_float(top_item.get("fit_h")) or 0.0) if top_enabled else 0.0
        left_fit_w = (_optional_float(left_item.get("fit_w")) or 0.0) if left_enabled else 0.0
        left_fit_h = (_optional_float(left_item.get("fit_h")) or 0.0) if left_enabled else 0.0
        if dense_flat_detail and left_enabled:
            left_width_ratio = left_fit_w / max(front_fit_w, 1e-6)
            if left_width_ratio <= 0.05:
                left_enabled = False
                left_fit_w = 0.0
                left_fit_h = 0.0
                left_item["enabled"] = False
        main_fit_w = max(front_fit_w, top_fit_w, 1e-6)
        main_fit_h = max(front_fit_h, left_fit_h, 1e-6)
        cluster_fit_w_units = main_fit_w + (left_fit_w if left_enabled else 0.0)
        cluster_fit_h_units = main_fit_h + (top_fit_h if top_enabled else 0.0)
        cluster_fit_w_mm = max(1e-6, draw_w - iso_reserve_w - outer_margin_x * 2.0 - (anchor_gap_x if left_enabled else 0.0))
        cluster_fit_h_mm = max(1e-6, draw_h - outer_margin_y * 2.0 - (anchor_gap_y if top_enabled else 0.0))
        anchor_scale = min(
            cluster_fit_w_mm / max(cluster_fit_w_units, 1e-6),
            cluster_fit_h_mm / max(cluster_fit_h_units, 1e-6),
        )
        # Promote scale only moderately; Welle 1b should improve density without destabilising dimensioning.
        ortho_scale = max(0.01, min(anchor_scale * 0.98, ortho_scale * scale_growth_cap))
        log(
            f"ALIGN ortho_scale slot={min(item['scale_fit'] for item in view_data if item['name'] in ('Top', 'Front', 'Left') and item.get('enabled', True)):.4f} "
            f"anchor={anchor_scale:.4f} final={ortho_scale:.4f}"
        )

        front_paper_w, front_paper_h = get_paper_dimensions(front_item, ortho_scale)
        front_fit_w_mm, front_fit_h_mm = get_paper_dimensions(front_item, ortho_scale, include_fit_padding=True)
        top_paper_w = top_paper_h = top_fit_w_mm = top_fit_h_mm = 0.0
        left_paper_w = left_paper_h = left_fit_w_mm = left_fit_h_mm = 0.0
        if top_enabled:
            top_paper_w, top_paper_h = get_paper_dimensions(top_item, ortho_scale)
            top_fit_w_mm, top_fit_h_mm = get_paper_dimensions(top_item, ortho_scale, include_fit_padding=True)
        if left_enabled:
            left_paper_w, left_paper_h = get_paper_dimensions(left_item, ortho_scale)
            left_fit_w_mm, left_fit_h_mm = get_paper_dimensions(left_item, ortho_scale, include_fit_padding=True)

        front_anchor_h_mm = front_fit_h_mm
        if dense_flat_detail:
            # Flat long-hole parts tend to over-reserve hidden fit padding below the
            # front view. Keep some safety margin for dimensions, but do not let the
            # top view drift into a visually empty band.
            front_anchor_h_mm = max(
                front_paper_h,
                min(front_fit_h_mm, front_paper_h + 28.0),
            )
        main_col_w_mm = max(front_fit_w_mm, top_fit_w_mm)
        main_col_h_mm = max(front_anchor_h_mm, left_fit_h_mm)
        projection_spread_y = 0.0
        if layout_variant == "flat_dominant" and top_enabled:
            remaining_h = max(0.0, draw_h - (main_col_h_mm + anchor_gap_y + top_fit_h_mm))
            top_height_ratio = top_fit_h_mm / max(front_fit_h_mm, 1e-6)
            if remaining_h > 20.0 and top_height_ratio < 0.22:
                projection_spread_y = min(58.0, max(18.0, remaining_h * 0.34))
                if dense_flat_detail:
                    projection_spread_y = min(projection_spread_y, max(10.0, remaining_h * 0.12))
        cluster_fit_w = main_col_w_mm + (anchor_gap_x + left_fit_w_mm if left_enabled else 0.0)
        cluster_fit_h = main_col_h_mm + (anchor_gap_y + projection_spread_y + top_fit_h_mm if top_enabled else 0.0)
        cluster_left = draw_left + max(
            outer_margin_x,
            min(margin_cap_x, (draw_w - iso_reserve_w - cluster_fit_w) * margin_factor_x),
        )
        cluster_top = draw_top + max(
            outer_margin_y,
            min(margin_cap_y, (draw_h - cluster_fit_h) * margin_factor_y),
        )
        cluster_left_anchor = cluster_left
        cluster_top_anchor = cluster_top
        cluster_fit_w_anchor = cluster_fit_w
        cluster_fit_h_anchor = cluster_fit_h
        front_item["cx"] = cluster_left + front_paper_w * 0.5
        front_item["cy"] = cluster_top + front_paper_h * 0.5

        if top_enabled:
            top_item["cx"] = cluster_left + top_paper_w * 0.5
            top_item["cy"] = cluster_top + front_anchor_h_mm + anchor_gap_y + projection_spread_y + top_paper_h * 0.5
        if left_enabled:
            left_item["cx"] = cluster_left + main_col_w_mm + anchor_gap_x + left_paper_w * 0.5
            left_item["cy"] = cluster_top + left_paper_h * 0.5

        if iso_item is not None and iso_item.get("enabled", True):
            iso_bounds = iso_item["layout_bounds"]
            iso_fit_area_w = max(40.0, draw_right - cluster_left - cluster_fit_w - outer_margin_x)
            iso_fit_area_h = max(40.0, draw_h - outer_margin_y * 2.0)
            iso_scale = compute_scale_for_area(
                iso_bounds,
                iso_fit_area_w,
                iso_fit_area_h,
                padding=iso_padding,
            )
            if layout_variant == "sheet_bent":
                iso_max_ratio = 0.45
            elif layout_variant == "flat_round_dominant":
                iso_max_ratio = 0.45
            elif layout_variant == "flat_dominant":
                iso_max_ratio = 0.28 if dense_flat_detail else 0.40
            else:
                iso_max_ratio = 0.75
            iso_scale = min(iso_scale, ortho_scale * iso_max_ratio)
            iso_item["scale"] = iso_scale
            iso_paper_w, iso_paper_h = get_paper_dimensions(iso_item, iso_scale)
            iso_fit_w_mm, iso_fit_h_mm = get_paper_dimensions(iso_item, iso_scale, include_fit_padding=True)
            iso_gap = 12.0
            pref_iso_left = cluster_left + cluster_fit_w + iso_gap
            pref_iso_top = max(cluster_top, cluster_top + cluster_fit_h - iso_fit_h_mm)
            if layout_variant == "flat_dominant":
                pref_iso_top = max(pref_iso_top, cluster_top + front_fit_h_mm + max(18.0, projection_spread_y * 0.65))
            if pref_iso_left + iso_fit_w_mm > draw_right - outer_margin_x:
                pref_iso_left = min(
                    draw_right - outer_margin_x - iso_fit_w_mm,
                    max(draw_left + outer_margin_x, cluster_left + cluster_fit_w - iso_fit_w_mm),
                )
                pref_iso_top = min(
                    draw_bottom - outer_margin_y - iso_fit_h_mm,
                    cluster_top + cluster_fit_h + iso_gap,
                )
            iso_item["cx"] = max(draw_left + outer_margin_x, pref_iso_left) + iso_paper_w * 0.5
            iso_item["cy"] = max(draw_top + outer_margin_y, pref_iso_top) + iso_paper_h * 0.5
    else:
        log(f"ALIGN ortho_scale={ortho_scale:.4f}")
        if iso_item is not None:
            iso_bounds = iso_item["layout_bounds"]
            iso_slot = iso_item.get("slot") or view_slots["Iso"]
            iso_scale = compute_scale_for_area(iso_bounds, iso_slot["w"], iso_slot["h"], padding=iso_padding)
            if layout_variant == "sheet_bent":
                iso_max_ratio = 0.45
            elif layout_variant == "flat_round_dominant":
                iso_max_ratio = 0.45
            elif layout_variant == "flat_dominant":
                iso_max_ratio = 0.40
            else:
                iso_max_ratio = 0.75
            iso_scale = min(iso_scale, ortho_scale * iso_max_ratio)
            iso_item["cx"] = iso_slot["cx"]
            iso_item["cy"] = iso_slot["cy"]
            iso_item["scale"] = iso_scale

        if front_item:
            front_paper_w, front_paper_h = get_paper_dimensions(front_item, ortho_scale)
            front_left = front_item["cx"] - front_paper_w / 2
            front_top = front_item["cy"] - front_paper_h / 2
            log(f"ALIGN Front: cx={front_item['cx']:.2f}, paper_w={front_paper_w:.2f}, left_edge={front_left:.2f}")

            if top_item and top_item.get("enabled", True):
                top_paper_w, _ = get_paper_dimensions(top_item, ortho_scale)
                new_top_cx = front_left + top_paper_w / 2
                log(f"ALIGN Top: paper_w={top_paper_w:.2f}, old_cx={top_item['cx']:.2f}, new_cx={new_top_cx:.2f}")
                top_item["cx"] = new_top_cx

            if left_item and left_item.get("enabled", True):
                _, left_paper_h = get_paper_dimensions(left_item, ortho_scale)
                new_left_cy = front_top + left_paper_h / 2
                log(f"ALIGN Left: paper_h={left_paper_h:.2f}, old_cy={left_item['cy']:.2f}, new_cy={new_left_cy:.2f}")
                left_item["cy"] = new_left_cy

    meta["scale"] = format_actual_scale_label(ortho_scale)
    
    def compute_view_bounds(item, scale):
        """Compute the bounding box of a view in paper coordinates."""
        paper_w, paper_h = get_paper_dimensions(item, scale, include_fit_padding=True)
        cx, cy = item["cx"], item["cy"]
        return {
            "left": cx - paper_w / 2,
            "top": cy - paper_h / 2,
            "right": cx + paper_w / 2,
            "bottom": cy + paper_h / 2,
        }
    
    def compute_all_views_bbox():
        """Compute the bounding box enclosing all rendered views."""
        all_left, all_top = float('inf'), float('inf')
        all_right, all_bottom = float('-inf'), float('-inf')

        for item in view_data:
            if not item.get("enabled", True):
                continue
            scale = item.get("scale", ortho_scale)
            vb = compute_view_bounds(item, scale)
            all_left = min(all_left, vb["left"])
            all_top = min(all_top, vb["top"])
            all_right = max(all_right, vb["right"])
            all_bottom = max(all_bottom, vb["bottom"])

        if all_left == float('inf'):
            return draw_left, draw_top, draw_left, draw_top
        return all_left, all_top, all_right, all_bottom
    
    # Check if all views fit within drawing area
    all_left, all_top, all_right, all_bottom = compute_all_views_bbox()
    log(f"BOUNDS: All views bbox: left={all_left:.2f}, top={all_top:.2f}, right={all_right:.2f}, bottom={all_bottom:.2f}")
    log(f"BOUNDS: Drawing area: left={draw_left:.2f}, top={draw_top:.2f}, right={draw_right:.2f}, bottom={draw_bottom:.2f}")
    
    # Calculate how much we need to shift
    shift_x, shift_y = 0.0, 0.0
    scale_reduction_needed = False
    
    if all_left < draw_left:
        shift_x = draw_left - all_left
        log(f"BOUNDS: Views extend past left edge by {-all_left + draw_left:.2f}mm, shifting right")
    elif all_right > draw_right:
        shift_x = draw_right - all_right
        log(f"BOUNDS: Views extend past right edge by {all_right - draw_right:.2f}mm, shifting left")
    
    if all_top < draw_top:
        shift_y = draw_top - all_top
        log(f"BOUNDS: Views extend past top edge by {-all_top + draw_top:.2f}mm, shifting down")
    elif all_bottom > draw_bottom:
        shift_y = draw_bottom - all_bottom
        log(f"BOUNDS: Views extend past bottom edge by {all_bottom - draw_bottom:.2f}mm, shifting up")
    
    # Apply shift to all views if needed
    if abs(shift_x) > 0.01 or abs(shift_y) > 0.01:
        log(f"BOUNDS: Applying shift: dx={shift_x:.2f}, dy={shift_y:.2f}")
        for item in view_data:
            item["cx"] += shift_x
            item["cy"] += shift_y
        
        # Recompute bbox after shift
        all_left, all_top, all_right, all_bottom = compute_all_views_bbox()
        log(f"BOUNDS: After shift: left={all_left:.2f}, top={all_top:.2f}, right={all_right:.2f}, bottom={all_bottom:.2f}")
        
        # Check if views still don't fit (need to reduce scale)
        if all_left < draw_left or all_right > draw_right or all_top < draw_top or all_bottom > draw_bottom:
            log("BOUNDS: WARNING - Views still don't fit after shift, scale reduction needed")
            scale_reduction_needed = True
            # Calculate required scale reduction
            views_w = all_right - all_left
            views_h = all_bottom - all_top
            avail_w = draw_right - draw_left
            avail_h = draw_bottom - draw_top
            
            scale_factor_w = avail_w / views_w if views_w > 0 else 1.0
            scale_factor_h = avail_h / views_h if views_h > 0 else 1.0
            scale_reduction = min(scale_factor_w, scale_factor_h, 1.0)
            
            if scale_reduction < 1.0:
                # Iteratively reduce scale until views fit (dimension padding
                # contains fixed-size elements that don't shrink linearly).
                for _pass in range(3):
                    safety = 0.96
                    reduction = scale_reduction * safety
                    log(f"BOUNDS: Pass {_pass+1} - reducing scale by factor {reduction:.3f}")
                    ortho_scale *= reduction
                    for item in view_data:
                        if item["name"] == "Iso":
                            item["scale"] = item.get("scale", ortho_scale) * reduction
                    # Recompute bbox and re-center in drawing area
                    all_left, all_top, all_right, all_bottom = compute_all_views_bbox()
                    views_cx = (all_left + all_right) / 2
                    views_cy = (all_top + all_bottom) / 2
                    draw_cx = (draw_left + draw_right) / 2
                    draw_cy = (draw_top + draw_bottom) / 2
                    recenter_dx = draw_cx - views_cx
                    recenter_dy = draw_cy - views_cy
                    if abs(recenter_dx) > 0.01 or abs(recenter_dy) > 0.01:
                        for item in view_data:
                            item["cx"] += recenter_dx
                            item["cy"] += recenter_dy
                    all_left, all_top, all_right, all_bottom = compute_all_views_bbox()
                    log(f"BOUNDS: After pass {_pass+1}: left={all_left:.2f}, top={all_top:.2f}, right={all_right:.2f}, bottom={all_bottom:.2f}")
                    # Check if views now fit
                    if (all_left >= draw_left - 0.5 and all_right <= draw_right + 0.5
                            and all_top >= draw_top - 0.5 and all_bottom <= draw_bottom + 0.5):
                        log(f"BOUNDS: Views fit after pass {_pass+1}")
                        break
                    # Recompute reduction for next pass
                    views_w = all_right - all_left
                    views_h = all_bottom - all_top
                    avail_w = draw_right - draw_left
                    avail_h = draw_bottom - draw_top
                    scale_reduction = min(
                        avail_w / views_w if views_w > 0 else 1.0,
                        avail_h / views_h if views_h > 0 else 1.0,
                        1.0,
                    )
                # Update title block scale label after effective fit correction.
                meta["scale"] = format_actual_scale_label(ortho_scale)

    # === JSON REPORT FOR AUTOMATED TESTING ===
    def build_report():
        """Build a JSON report with all computed values for verification."""
        debug = view_dirs.get("debug", {}) if view_dirs else {}
        report = {
            "input_file": os.path.basename(input_path),
            "sheet_requested": requested_sheet,
            "sheet_resolved": sheet_resolved,
            "layout_profile": layout_profile,
            "dimension_plan_source": dim_plan_source,
            "view_layout_variant": layout_variant,
            "sheet_metal_subtype": sheet_metal_subtype,
            "milling_subtype": milling_subtype,
            "flat_pattern_mode": flat_pattern_mode,
            "scale_requested": requested_scale_label,
            "scale_label": str(meta.get("scale") or "auto"),
            "mass_kg": meta.get("mass_kg"),
            "surface_ra": meta.get("surface_ra"),
            "surface_rz": meta.get("surface_rz"),
            "complexity_score": comp,
            "safe_mode_applied": safe_mode,
            "degrade_steps": degrade_steps,
            "projection_failures": projection_failures,
            "bounding_box": {
                "X": round(dim_x, 2),
                "Y": round(dim_y, 2),
                "Z": round(dim_z, 2),
            },
            "detection": {
                "method": debug.get("method", "unknown"),
                "longest_axis": debug.get("longest_axis", "unknown"),
                "is_flat": debug.get("is_flat", False),
                "flatness_ratio": debug.get("flatness_ratio", 0),
                "confidence": view_dirs.get("confidence", 0) if view_dirs else 0,
                "chosen_front": debug.get("chosen_front"),
                "candidates": debug.get("candidates", []),
                "candidate_score_gap": debug.get("candidate_score_gap"),
                "front_ambiguous": debug.get("front_ambiguous"),
                "front_view_rule_id": debug.get("front_view_rule_id"),
                "front_view_strategy": debug.get("front_view_strategy"),
                "prefer_low_hidden_edge_load": debug.get("prefer_low_hidden_edge_load"),
                "section_clutter_rule_id": debug.get("section_clutter_rule_id"),
                "section_recommended": debug.get("section_recommended"),
            },
            "features": {
                "ok": bool(feature_payload.get("ok")),
                "rotational_profile": feature_payload.get("rotational_profile"),
                "step_count": feature_payload.get("step_count"),
                "step_profile": feature_payload.get("step_profile"),
                "hole_count": feature_payload.get("hole_count"),
                "hole_diameter_mm": feature_payload.get("hole_diameter_mm"),
                "hole_pitch_mm": feature_payload.get("hole_pitch_mm"),
                "chamfer_count": len([item for item in (feature_payload.get("chamfers") or []) if isinstance(item, dict)]),
                "blind_hole_count": feature_payload.get("blind_hole_count"),
                "hole_groups": feature_payload.get("hole_groups"),
                "thread_label": feature_payload.get("thread_label"),
                "thread_depth_mm": feature_payload.get("thread_depth_mm"),
                "thread_through": feature_payload.get("thread_through"),
                "groove_count": feature_payload.get("groove_count"),
                "groove_groups": feature_payload.get("groove_groups"),
                "thread_relief_recommended": feature_payload.get("thread_relief_recommended"),
                "bend_radius_mm": feature_payload.get("bend_radius_mm"),
                "surface_finish": feature_payload.get("surface_finish"),
                "is_flat": feature_payload.get("is_flat"),
                "flat_ratio": feature_payload.get("flat_ratio"),
                "longest_axis": feature_payload.get("longest_axis"),
                "error": feature_payload.get("error"),
            },
            "directions": {
                "front": [round(front_dir.x, 4), round(front_dir.y, 4), round(front_dir.z, 4)],
                "top": [round(top_dir.x, 4), round(top_dir.y, 4), round(top_dir.z, 4)],
                "right": [round(right_dir.x, 4), round(right_dir.y, 4), round(right_dir.z, 4)],
            },
            "scale": ortho_scale,
            "views": {},
            "quality": {},
        }
        
        drawing_bounds = (draw_left, draw_right, draw_top, draw_bottom)
        rendered_view_bounds = {}

        for item in view_data:
            item_scale = ortho_scale if item["name"] != "Iso" else item.get("scale", ortho_scale)
            paper_w, paper_h = get_paper_dimensions(item, item_scale)
            left_edge = item["cx"] - paper_w / 2
            top_edge = item["cy"] - paper_h / 2
            geometry_bounds = transform_local_bounds_to_paper(
                item["svg_bounds"],
                item["svg_bounds"],
                item["cx"],
                item["cy"],
                item_scale,
                item["rotation_deg"],
            )
            dim_metadata = item.get("dimension_metadata") or {}
            dimension_boxes = []
            label_boxes = []
            for bucket in ("overall_dimensions", "feature_dimensions"):
                for entry in dim_metadata.get(bucket, []):
                    measurement_box = transform_local_bounds_to_paper(
                        entry.get("measurement_box"),
                        item["svg_bounds"],
                        item["cx"],
                        item["cy"],
                        item_scale,
                        item["rotation_deg"],
                    )
                    text_box = transform_local_bounds_to_paper(
                        entry.get("text_box"),
                        item["svg_bounds"],
                        item["cx"],
                        item["cy"],
                        item_scale,
                        item["rotation_deg"],
                    )
                    if measurement_box:
                        dimension_boxes.append(measurement_box)
                    if text_box:
                        dimension_boxes.append(text_box)
                        label_boxes.append(text_box)

            dimension_bounds = merge_bounds(*dimension_boxes)
            label_bounds = merge_bounds(*label_boxes)
            render_bounds = merge_bounds(geometry_bounds, dimension_bounds)
            dimension_overflow = compute_bounds_overflow(dimension_bounds, drawing_bounds)
            label_overflow = compute_bounds_overflow(label_bounds, drawing_bounds)
            rendered_view_bounds[item["name"]] = render_bounds

            report["views"][item["name"]] = {
                "enabled": bool(item.get("enabled", True)),
                "view_kind": str(item.get("view_kind") or "standard"),
                "view_title": str(item.get("view_title") or item["name"]),
                "rotation_deg": item["rotation_deg"],
                "center": [round(item["cx"], 2), round(item["cy"], 2)],
                "paper_size": [round(paper_w, 2), round(paper_h, 2)],
                "slot_size": [
                    round(_optional_float((item.get("slot") or {}).get("w")) or 0.0, 2),
                    round(_optional_float((item.get("slot") or {}).get("h")) or 0.0, 2),
                ],
                "left_edge": round(left_edge, 2),
                "top_edge": round(top_edge, 2),
                "svg_bounds": [round(b, 2) for b in item["svg_bounds"]],
                "circle_count": int(count_svg_circles(item.get("svg", ""))),
                "raw_circle_count": int(len(extract_svg_circles(item.get("svg", "")))),
                "centerline_count": int(item.get("centerline_count", 0)),
                "centerline_source": str(item.get("centerline_source", "none")),
                "overall_dim_axes": list(item.get("overall_dim_axes", [])),
                "feature_dim_mode": str(item.get("feature_dim_mode", "none")),
                "feature_dim_text_count": int(item.get("feature_dim_text_count", 0)),
                "feature_dim_types": list(item.get("feature_dim_types", [])),
                "feature_dim_outside_preferred": bool(item.get("feature_dim_outside_preferred", False)),
                "layout_density_escalated": bool(item.get("layout_density_escalated", False)),
                "detail_view_recommended": bool(item.get("detail_view_recommended", False)),
                "detail_parent_view": str(item.get("detail_parent_view") or ""),
                "detail_label": str(item.get("detail_label") or ""),
                "detail_zoom_factor": round(_optional_float(item.get("detail_zoom_factor")) or 0.0, 2),
                "dimension_quality": dict(item.get("dimension_quality") or {}),
                "geometry_bounds": bounds_to_rect_dict(geometry_bounds),
                "dimension_bounds": bounds_to_rect_dict(dimension_bounds),
                "label_bounds": bounds_to_rect_dict(label_bounds),
                "render_bounds": bounds_to_rect_dict(render_bounds),
                "dimensions_fit_inside_drawing_area": bool(dimension_overflow.get("max", 0.0) <= 0.5),
                "labels_fit_inside_drawing_area": bool(label_overflow.get("max", 0.0) <= 0.5),
                "dimension_overflow_mm": dict(dimension_overflow),
                "label_overflow_mm": dict(label_overflow),
                "line_profile": {
                    "visible": round(_optional_float((item.get("line_profile") or {}).get("visible")) or 0.0, 5),
                    "hidden": round(_optional_float((item.get("line_profile") or {}).get("hidden")) or 0.0, 5),
                    "centerline": round(_optional_float((item.get("line_profile") or {}).get("centerline")) or 0.0, 5),
                    "dimension": round(_optional_float((item.get("line_profile") or {}).get("dimension")) or 0.0, 5),
                    "section": round(_optional_float((item.get("line_profile") or {}).get("section")) or 0.0, 5),
                },
            }

        # Alignment checks
        report["alignment"] = {
            "front_top_left_match": False,
            "front_left_top_match": False,
            "front_left_edge": 0,
            "top_left_edge": 0,
            "left_top_edge": 0,
            "front_top_edge": 0,
        }
        
        if "Front" in report["views"] and "Top" in report["views"]:
            front_left = report["views"]["Front"]["left_edge"]
            top_left = report["views"]["Top"]["left_edge"]
            report["alignment"]["front_left_edge"] = front_left
            report["alignment"]["top_left_edge"] = top_left
            if not report["views"]["Top"].get("enabled", True):
                report["alignment"]["front_top_left_match"] = True
            else:
                report["alignment"]["front_top_left_match"] = abs(front_left - top_left) < 2.0
        
        if "Front" in report["views"] and "Left" in report["views"]:
            front_top = report["views"]["Front"]["top_edge"]
            left_top = report["views"]["Left"]["top_edge"]
            report["alignment"]["front_top_edge"] = front_top
            report["alignment"]["left_top_edge"] = left_top
            if not report["views"]["Left"].get("enabled", True):
                report["alignment"]["front_left_top_match"] = True
            else:
                report["alignment"]["front_left_top_match"] = abs(front_top - left_top) < 2.0

        overflow_left = max(0.0, draw_left - all_left)
        overflow_top = max(0.0, draw_top - all_top)
        overflow_right = max(0.0, all_right - draw_right)
        overflow_bottom = max(0.0, all_bottom - draw_bottom)
        max_overflow = max(overflow_left, overflow_top, overflow_right, overflow_bottom)
        report["quality"] = {
            "drawing_area": {
                "left": round(draw_left, 2),
                "top": round(draw_top, 2),
                "right": round(draw_right, 2),
                "bottom": round(draw_bottom, 2),
            },
            "views_bbox": {
                "left": round(all_left, 2),
                "top": round(all_top, 2),
                "right": round(all_right, 2),
                "bottom": round(all_bottom, 2),
            },
            "overflow_mm": {
                "left": round(overflow_left, 3),
                "top": round(overflow_top, 3),
                "right": round(overflow_right, 3),
                "bottom": round(overflow_bottom, 3),
                "max": round(max_overflow, 3),
            },
            "fits_inside_drawing_area": max_overflow <= 0.5,
            "scale_reduction_needed": bool(scale_reduction_needed),
            "centerline_total": int(sum(v.get("centerline_count", 0) for v in report["views"].values())),
            "layout_usage_ratio": round(
                compute_layout_usage(
                    {
                        "left": all_left,
                        "top": all_top,
                        "right": all_right,
                        "bottom": all_bottom,
                    },
                    {
                        "left": draw_left,
                        "top": draw_top,
                        "right": draw_right,
                        "bottom": draw_bottom,
                    },
                ),
                5,
            ),
        }

        dimension_out_of_bounds_views = sorted(
            name
            for name, view in report["views"].items()
            if not bool((view or {}).get("dimensions_fit_inside_drawing_area", True))
        )
        label_out_of_bounds_views = sorted(
            name
            for name, view in report["views"].items()
            if not bool((view or {}).get("labels_fit_inside_drawing_area", True))
        )

        overlap_sources = {
            name: bounds
            for name, bounds in rendered_view_bounds.items()
            if bounds is not None and bool((report["views"].get(name) or {}).get("enabled", True))
        }
        abwicklung_render_bounds = compute_abwicklung_render_bounds(abwicklung_meta) if abwicklung_meta else None
        if abwicklung_render_bounds is not None:
            overlap_sources["FlatPattern"] = abwicklung_render_bounds
            abwicklung_overflow = compute_bounds_overflow(abwicklung_render_bounds, drawing_bounds)
            if abwicklung_overflow.get("max", 0.0) > 0.5:
                dimension_out_of_bounds_views = sorted(set(dimension_out_of_bounds_views + ["FlatPattern"]))

        overlap_pairs = []
        max_view_overlap = 0.0
        ordered_sources = sorted(overlap_sources.items(), key=lambda item: item[0])
        for index, (left_name, left_bounds) in enumerate(ordered_sources):
            for right_name, right_bounds in ordered_sources[index + 1:]:
                overlap = compute_bounds_intersection(left_bounds, right_bounds)
                if overlap["x"] <= 0.5 or overlap["y"] <= 0.5:
                    continue
                overlap_pairs.append(f"{left_name} vs {right_name}")
                max_view_overlap = max(max_view_overlap, min(overlap["x"], overlap["y"]))

        report["quality"].update(
            {
                "dimension_out_of_bounds_views": dimension_out_of_bounds_views,
                "label_out_of_bounds_views": label_out_of_bounds_views,
                "view_overlap_pairs": overlap_pairs,
                "views_do_not_overlap": not overlap_pairs,
                "max_view_overlap_mm": round(max_view_overlap, 3),
            }
        )
        thread_relief_warning = str(policy_hints.get("thread_relief_warning") or "").strip()
        report["quality"]["warnings"] = [thread_relief_warning] if thread_relief_warning else []
        
        return report
    
    view_groups = []
    dim_tracking = {
        "dim_text_count": 0,
        "step_dim_count": 0,
        "feature_dim_present": False,
        "labels_in_bounds": True,
        "feature_dim_outside_views": [],
        "feature_dim_internal_views": [],
        "outside_preferred_feature_views": [],
        "dimension_paper_boxes": [],
    }
    feature_view_name = None
    feature_view_circle_count = 0
    view_circle_counts = {}
    projected_feature_target_counts = {}
    requested_feature_views = []
    fallback_feature_view_name = None
    fallback_feature_dim_types = None
    forced_feature_dim_types_by_view = {}
    view_data_by_name = {item.get("name"): item for item in view_data if isinstance(item, dict)}
    if isinstance(feature_payload, dict) and feature_payload.get("ok") is True:
        for candidate in view_data:
            if candidate["name"] == "Iso" or not candidate.get("enabled", True):
                continue
            circle_count = count_svg_circles(candidate["svg"])
            view_circle_counts[candidate["name"]] = int(circle_count)
            projected_targets = _project_feature_centerline_targets(
                feature_payload,
                candidate.get("direction"),
                ortho_scale,
                limit=40,
                allow_nonflat=True,
            )
            projected_feature_target_counts[candidate["name"]] = int(len(projected_targets))
            if circle_count > feature_view_circle_count:
                feature_view_circle_count = circle_count
                feature_view_name = candidate["name"]
        if feature_view_name:
            log(f"Feature dimension view: {feature_view_name} (circles={feature_view_circle_count})")
    if dim_plan and isinstance(feature_payload, dict) and feature_payload.get("ok") is True:
        requested_feature_views = [
            candidate["name"]
            for candidate in view_data
            if candidate["name"] != "Iso"
            and candidate.get("enabled", True)
            and view_requests_feature_dimensions(
                candidate["name"],
                dim_plan=dim_plan,
                feature_payload=feature_payload,
            )
        ]
        if (
            str(layout_profile or "").strip().lower() in ("milling", "sheet_metal")
            and requested_feature_views
            and feature_view_name
            and feature_view_circle_count > 0
            and max(view_circle_counts.get(name, 0) for name in requested_feature_views) <= 0
            and max(projected_feature_target_counts.get(name, 0) for name in requested_feature_views) <= 0
        ):
            fallback_feature_view_name = feature_view_name
            fallback_feature_dim_types = feature_dimension_types_for_view(
                requested_feature_views[0],
                dim_plan=dim_plan,
                feature_payload=feature_payload,
            )
            log(
                "Feature dimension fallback view: "
                f"{fallback_feature_view_name} (requested={requested_feature_views[0]})"
            )
        elif (
            requested_feature_views
            and feature_view_name
            and feature_view_name != requested_feature_views[0]
        ):
            requested_view_name = requested_feature_views[0]
            requested_item = view_data_by_name.get(requested_view_name) or {}
            requested_visible_circles = int(view_circle_counts.get(requested_view_name, 0))
            requested_projected_targets = int(projected_feature_target_counts.get(requested_view_name, 0))
            if should_fallback_feature_dims_to_visible_view(
                requested_view_name,
                feature_view_name,
                requested_visible_circles,
                requested_projected_targets,
                feature_view_circle_count,
                requested_item.get("layout_bounds"),
                requested_item.get("rotation_deg", 0),
                layout_profile=layout_profile,
            ):
                requested_feature_dim_types = set(feature_dimension_types_for_view(
                    requested_view_name,
                    dim_plan=dim_plan,
                    feature_payload=feature_payload,
                ) or [])
                relocated_feature_dim_types = {
                    "hole_pitch",
                    "hole_location_x",
                    "hole_location_y",
                }
                fallback_types = requested_feature_dim_types & relocated_feature_dim_types
                remaining_types = requested_feature_dim_types - fallback_types
                if fallback_types:
                    forced_feature_dim_types_by_view[feature_view_name] = sorted(fallback_types)
                    if remaining_types:
                        forced_feature_dim_types_by_view[requested_view_name] = sorted(remaining_types)
                    log(
                        "Feature dimension split fallback: "
                        f"{feature_view_name} gets {sorted(fallback_types)}, "
                        f"{requested_view_name} keeps {sorted(remaining_types)}"
                    )
                else:
                    fallback_feature_view_name = feature_view_name
                    fallback_feature_dim_types = sorted(requested_feature_dim_types)
                    log(
                        "Feature dimension visible-view fallback: "
                        f"{fallback_feature_view_name} (requested={requested_view_name})"
                    )

    for item in view_data:
        name = item["name"]
        if not item.get("enabled", True):
            continue

        # ISO view is always rendered (sheet_metal included — at reduced scale).

        svg_bounds = item["svg_bounds"]
        proj_bounds = item["proj_bounds"]
        proj_w, proj_h = bounds_size(proj_bounds)
        svg_w, svg_h = bounds_size(svg_bounds)

        # The dimension lines are drawn in SVG coordinates, then rotated with the view.
        # We want the labels to show the TRUE 3D dimensions as they appear on paper.
        #
        # proj_w = 3D projected width (what we want to show as HORIZONTAL on paper)
        # proj_h = 3D projected height (what we want to show as VERTICAL on paper)
        #
        # In SVG coordinates (before rotation):
        # - If proj_swap=False: SVG width = proj_w, SVG height = proj_h
        # - If proj_swap=True: SVG width = proj_h, SVG height = proj_w
        #
        # The dim lines are drawn in SVG space (before rotation):
        # - Horizontal dim line spans svg_w → labeled "label_width"
        # - Vertical dim line spans svg_h → labeled "label_height"
        #
        # proj_w/proj_h (from aligned_proj_bounds) already match svg_w/svg_h
        # (the proj_swap alignment ensures this).
        #
        # When the view rotates, the dim lines rotate WITH the content.
        # Each label stays with its line, so NO swap is needed for rotation.
        # The label always describes the 3D extent that its line visually spans.
        label_w = proj_w  # Horizontal dim line = right-axis extent
        label_h = proj_h  # Vertical dim line = up-axis extent
        
        is_section_view = bool(item.get("view_kind") == "section")
        is_detail_view = bool(item.get("view_kind") == "detail")
        if name == "Iso" and not is_section_view and not is_detail_view:
            scale = item.get("scale", ortho_scale * 0.75)
            dimension_svg = ""
            centerline_count = 0
            centerline_source = "none"
            line_profile = iso128_line_profile(scale)
            dimension_metadata = {
                "overall_dimensions": [],
                "feature_dimensions": [],
                "_shared_collision_boxes": [],
            }
        elif is_section_view:
            scale = item.get("scale", ortho_scale * 0.75)
            line_profile = iso128_line_profile(scale)
            dimension_metadata = {
                "overall_dimensions": [],
                "feature_dimensions": [],
                "_shared_collision_boxes": [],
            }
            centerline_count = 0
            centerline_source = "none"
            section_label = str(item.get("section_label") or "A").strip() or "A"
            section_min_x, section_max_x, _section_min_y, section_max_y = svg_bounds
            label_y = section_max_y + max(6.0 / max(scale, 0.05), 2.5)
            dimension_svg = _build_section_view_label_svg(
                (section_min_x + section_max_x) * 0.5,
                label_y,
                label=section_label,
                scale=scale,
            )
            item["overall_dim_axes"] = []
            item["feature_dim_mode"] = "none"
            item["feature_dim_text_count"] = 0
            item["feature_dim_types"] = []
            item["feature_dim_outside_preferred"] = False
            item["dimension_quality"] = summarize_view_dimension_quality(
                svg_bounds,
                [],
                [],
            )
        elif is_detail_view:
            scale = item.get("scale", ortho_scale * 0.75)
            line_profile = iso128_line_profile(scale)
            dimension_metadata = {
                "overall_dimensions": [],
                "feature_dimensions": [],
                "_shared_collision_boxes": [],
            }
            centerline_count = 0
            centerline_source = "none"
            detail_label = str(item.get("detail_label") or "Z").strip() or "Z"
            zoom_factor = _optional_float(item.get("detail_zoom_factor")) or 2.0
            detail_min_x, detail_max_x, _detail_min_y, detail_max_y = svg_bounds
            label_y = detail_max_y + max(6.0 / max(scale, 0.05), 2.5)
            dimension_svg = _build_detail_view_label_svg(
                (detail_min_x + detail_max_x) * 0.5,
                label_y,
                label=detail_label,
                zoom_factor=zoom_factor,
                scale=scale,
            )
            item["overall_dim_axes"] = []
            item["feature_dim_mode"] = "none"
            item["feature_dim_text_count"] = 0
            item["feature_dim_types"] = []
            item["feature_dim_outside_preferred"] = False
            item["dimension_quality"] = summarize_view_dimension_quality(
                svg_bounds,
                [],
                [],
            )
        else:
            scale = ortho_scale
            line_profile = iso128_line_profile(scale)
            stroke_width = float(line_profile.get("visible", compute_stroke_width(scale)))
            show_horizontal, show_vertical = resolve_overall_dimension_axes(name, dim_plan=dim_plan)
            if (
                str(layout_profile or "").strip().lower() == "milling"
                and name == "Front"
                and int(item.get("rotation_deg", 0)) % 180 in {90}
                and not bool((feature_payload or {}).get("is_flat"))
            ):
                # Rotated milling front views easily duplicate the long overall
                # size into the lower neighboring slot. Keep the functional
                # height on the front view and leave the global length to the
                # orthogonal companion views.
                show_horizontal = False
            if (
                str(layout_profile or "").strip().lower() == "sheet_metal"
                and name == "Front"
                and int(item.get("rotation_deg", 0)) % 180 in {90}
                and not bool((feature_payload or {}).get("is_flat"))
                and int(_optional_float((feature_payload or {}).get("hole_count")) or 0) >= 4
            ):
                # Folded sheet-metal fronts with dense projected hole callouts
                # become unreadable when the long overall height stays on the
                # same narrow front strip. The flat pattern already carries the
                # long overall, so keep only the short overall on Front.
                show_vertical = False
            dimension_metadata = {
                "overall_dimensions": [],
                "feature_dimensions": [],
                "_shared_collision_boxes": [],
            }
            neighbor_slot_bounds = []
            neighbor_view_bounds = []
            for candidate in view_data:
                if candidate is item or not candidate.get("enabled", True):
                    continue
                slot = candidate.get("slot") or {}
                slot_w = _optional_float(slot.get("w"))
                slot_h = _optional_float(slot.get("h"))
                if not slot_w or not slot_h:
                    continue
                neighbor_slot_bounds.append(
                    (
                        float(candidate["cx"]) - float(slot_w) * 0.5,
                        float(candidate["cx"]) + float(slot_w) * 0.5,
                        float(candidate["cy"]) - float(slot_h) * 0.5,
                        float(candidate["cy"]) + float(slot_h) * 0.5,
                    )
                )
                candidate_scale = ortho_scale if candidate["name"] != "Iso" else candidate.get("scale", ortho_scale)
                candidate_view_bounds = transform_local_bounds_to_paper(
                    candidate.get("svg_bounds"),
                    candidate.get("svg_bounds"),
                    candidate["cx"],
                    candidate["cy"],
                    candidate_scale,
                    candidate["rotation_deg"],
                )
                if candidate_view_bounds is not None:
                    neighbor_view_bounds.append(candidate_view_bounds)
            zone_guard_height = max(6.0, min(12.0, margin * 1.15))
            reserved_paper_boxes = [
                # Top margin guard
                (
                    float(draw_left),
                    float(draw_right),
                    float(draw_top),
                    float(min(draw_bottom, draw_top + zone_guard_height)),
                ),
                # Title block guard — prevent dimensions from overlapping the title block
                (
                    float(draw_left),
                    float(draw_right),
                    float(draw_bottom),
                    float(sheet_h - margin),
                ),
            ]
            dimension_metadata["_placement_context"] = {
                "paper_center": (float(item["cx"]), float(item["cy"])),
                "drawing_bounds": (
                    float(draw_left),
                    float(draw_right),
                    float(draw_top),
                    float(draw_bottom),
                ),
                "neighbor_slot_bounds": neighbor_slot_bounds,
                "neighbor_view_bounds": neighbor_view_bounds,
                "reserved_paper_boxes": reserved_paper_boxes,
            }
            item["overall_dim_axes"] = [
                axis
                for axis, enabled in (("H", show_horizontal), ("V", show_vertical))
                if enabled
            ]
            item["feature_dim_mode"] = "none"
            item["feature_dim_text_count"] = 0
            item["feature_dim_types"] = []
            item["feature_dim_outside_preferred"] = False
            # Dimension lines are drawn around the SVG geometry (svg_bounds)
            # but labels show the TRUE 3D dimensions (from proj_bounds)
            use_round_overall = (
                name == "Front"
                and show_horizontal
                and show_vertical
                and _is_round_flat_feature_case(feature_payload)
            )
            if use_round_overall:
                dimension_svg = build_round_overall_dimension_svg(
                    item["svg"],
                    svg_bounds,
                    scale,
                    stroke_width,
                    line_profile=line_profile,
                    metadata=dimension_metadata,
                )
            else:
                dimension_svg = ""
            if not dimension_svg:
                dimension_svg = build_dimension_svg(
                    svg_bounds,  # Use svg_bounds for LINE positions (around the geometry)
                    scale,
                    stroke_width,
                    line_profile=line_profile,
                    label_width=label_w,   # TRUE 3D dimension for horizontal
                    label_height=label_h,  # TRUE 3D dimension for vertical
                    rotation_deg=item["rotation_deg"],
                    show_horizontal=show_horizontal,
                    show_vertical=show_vertical,
                    svg_group=item["svg"],  # Used to anchor extension lines to actual part outline
                    metadata=dimension_metadata,
                )
                dim_tracking["dim_text_count"] += (1 if show_horizontal else 0) + (1 if show_vertical else 0)
            else:
                dim_tracking["dim_text_count"] += 1
            planned_feature_view = (
                view_requests_feature_dimensions(
                    name,
                    dim_plan=dim_plan,
                    feature_payload=feature_payload,
                )
                if dim_plan
                else (feature_view_name == name)
            )
            _show_features = planned_feature_view
            allowed_feature_dim_types = None
            if forced_feature_dim_types_by_view:
                forced_types = forced_feature_dim_types_by_view.get(name)
                _show_features = forced_types is not None
                if forced_types is not None:
                    allowed_feature_dim_types = set(forced_types or [])
            elif fallback_feature_view_name:
                _show_features = name == fallback_feature_view_name
                if _show_features:
                    allowed_feature_dim_types = set(fallback_feature_dim_types or [])
            current_projected_target_count = int(projected_feature_target_counts.get(name, 0))
            projected_feature_dimension_targets = bool(
                _show_features
                and not fallback_feature_view_name
                and current_projected_target_count > 0
            )
            projected_centerline_targets = bool(
                projected_feature_dimension_targets
                and should_allow_projected_centerlines(
                    name,
                    current_projected_target_count,
                    view_circle_counts,
                )
            )
            centerline_svg, centerline_count, centerline_source = build_centerline_svg(
                item["svg"],
                scale,
                stroke_width,
                limit=30,
                line_profile=line_profile,
                feature_payload=(
                    feature_payload
                    if projected_centerline_targets
                    else None
                ),
                direction=item.get("direction"),
                allow_projected_feature_targets=projected_centerline_targets,
            )
            if centerline_svg:
                dimension_svg = f"{dimension_svg}{centerline_svg}"

            if _show_features:
                if allowed_feature_dim_types is None:
                    allowed_feature_dim_types = (
                        feature_dimension_types_for_view(
                            name,
                            dim_plan=dim_plan,
                            feature_payload=feature_payload,
                        )
                        if dim_plan
                        else None
                    )
                outside_feature_placement = should_place_feature_dims_outside(
                    name,
                    allowed_feature_dim_types,
                )
                item["feature_dim_types"] = sorted(allowed_feature_dim_types or [])
                item["feature_dim_outside_preferred"] = bool(outside_feature_placement)
                feature_dim_count_before = len(dimension_metadata.get("feature_dimensions") or [])
                shared_collision_snapshot = list(dimension_metadata.get("_shared_collision_boxes") or [])
                feature_dimension_svg = build_feature_dimension_svg(
                    item["svg"],
                    svg_bounds,
                    feature_payload,
                    scale,
                    stroke_width,
                    line_profile=line_profile,
                    allowed_dim_types=allowed_feature_dim_types,
                    outside_placement=outside_feature_placement,
                    metadata=dimension_metadata,
                    direction=item.get("direction"),
                    rotation_deg=item.get("rotation_deg", 0),
                    view_name=name,
                    layout_profile=layout_profile,
                    allow_projected_feature_targets=projected_feature_dimension_targets,
                )
                # Post-check: discard feature dims that overflow or reintroduce
                # measurable readability collisions after placement.
                if feature_dimension_svg and outside_feature_placement:
                    _feat_boxes = []
                    for _fd in dimension_metadata.get("feature_dimensions", []):
                        for _bk in ("measurement_box", "text_box"):
                            _fb = _fd.get(_bk)
                            if _fb and len(_fb) == 4:
                                _feat_boxes.append(_fb)
                    _suppress_feature_dims = False
                    _suppress_reason = None
                    if _feat_boxes:
                        _feat_merged = merge_bounds(*_feat_boxes)
                        if _feat_merged:
                            _feat_paper = transform_local_bounds_to_paper(
                                _feat_merged, svg_bounds, item["cx"], item["cy"], scale, item["rotation_deg"]
                            )
                            if _feat_paper is not None:
                                _feat_overflow = compute_bounds_overflow(
                                    _feat_paper, (draw_left, draw_right, draw_top, draw_bottom)
                                )
                                if _feat_overflow.get("max", 0.0) > 50.0:
                                    _suppress_feature_dims = True
                                    _suppress_reason = (
                                        f"overflow {_feat_overflow['max']:.1f}mm"
                                    )
                    if not _suppress_feature_dims:
                        _paper_geometry_bounds = transform_local_bounds_to_paper(
                            svg_bounds,
                            svg_bounds,
                            item["cx"],
                            item["cy"],
                            scale,
                            item["rotation_deg"],
                        ) or svg_bounds
                        _paper_overall_dimensions = transform_dimension_entries_to_paper(
                            dimension_metadata.get("overall_dimensions"),
                            svg_bounds,
                            item["cx"],
                            item["cy"],
                            scale,
                            item["rotation_deg"],
                        )
                        _paper_feature_dimensions = transform_dimension_entries_to_paper(
                            dimension_metadata.get("feature_dimensions"),
                            svg_bounds,
                            item["cx"],
                            item["cy"],
                            scale,
                            item["rotation_deg"],
                        )
                        _feature_quality = summarize_view_dimension_quality(
                            _paper_geometry_bounds,
                            _paper_overall_dimensions,
                            _paper_feature_dimensions,
                        )
                        if should_suppress_feature_dims_postcheck(
                            layout_profile,
                            _feature_quality,
                        ):
                            _suppress_feature_dims = True
                            _suppress_reason = (
                                "post-check overlap "
                                f"(overall={int(_feature_quality.get('feature_overall_overlap_count') or 0)}, "
                                f"geom={int(_feature_quality.get('feature_geom_overlap_count') or 0)})"
                            )
                    if _suppress_feature_dims:
                        log(f"  {name}: suppressing feature dims ({_suppress_reason})")
                        feature_dimension_svg = ""
                        dimension_metadata["feature_dimensions"] = list(
                            (dimension_metadata.get("feature_dimensions") or [])[:feature_dim_count_before]
                        )
                        dimension_metadata["_shared_collision_boxes"] = shared_collision_snapshot
                # Fallback: if outside placement failed, retry with internal placement.
                _actual_mode = "outside" if outside_feature_placement else "internal"
                if not feature_dimension_svg and outside_feature_placement:
                    log(f"  {name}: outside feature dims empty, falling back to internal placement")
                    dimension_metadata["feature_dimensions"] = list(
                        (dimension_metadata.get("feature_dimensions") or [])[:feature_dim_count_before]
                    )
                    dimension_metadata["_shared_collision_boxes"] = shared_collision_snapshot
                    feature_dimension_svg = build_feature_dimension_svg(
                        item["svg"],
                        svg_bounds,
                        feature_payload,
                        scale,
                        stroke_width,
                        line_profile=line_profile,
                        allowed_dim_types=allowed_feature_dim_types,
                        outside_placement=False,
                        metadata=dimension_metadata,
                        direction=item.get("direction"),
                        rotation_deg=item.get("rotation_deg", 0),
                        view_name=name,
                        layout_profile=layout_profile,
                        allow_projected_feature_targets=projected_feature_dimension_targets,
                    )
                    _actual_mode = "internal_fallback"
                if feature_dimension_svg:
                    dimension_svg = f"{dimension_svg}{feature_dimension_svg}"
                    feature_dim_text_count = feature_dimension_svg.count("<text")
                    item["feature_dim_text_count"] = int(feature_dim_text_count)
                    item["feature_dim_mode"] = _actual_mode
                    dim_tracking["dim_text_count"] += feature_dim_text_count
                    dim_tracking["feature_dim_present"] = True
                    if _actual_mode == "outside":
                        dim_tracking["feature_dim_outside_views"].append(name)
                    else:
                        dim_tracking["feature_dim_internal_views"].append(name)
                elif outside_feature_placement:
                    dim_tracking["outside_preferred_feature_views"].append(name)
            turning_step_dims = (
                str(layout_profile or "").strip().lower() == "turning"
                and name == "Front"
                and int(_optional_float((feature_payload or {}).get("step_count")) or 0) >= 2
            )
            milling_step_dims = (
                str(layout_profile or "").strip().lower() == "milling"
                and name == "Left"
                and not bool((feature_payload or {}).get("rotational_profile"))
                and svg_detail_score(item["svg"]) > max(proj_w, proj_h) * 1.35
            )
            enable_step_dims = (
                (
                    name == "Front"
                    and show_horizontal
                    and bool((feature_payload or {}).get("is_flat"))
                    and svg_detail_score(item["svg"]) > max(proj_w, proj_h) * 2.0
                )
                or turning_step_dims
                or milling_step_dims
            )
            if enable_step_dims:
                milling_steps = str(layout_profile or "").strip().lower() == "milling"
                turning_steps = str(layout_profile or "").strip().lower() == "turning"
                max_step_dims = 5
                if turning_steps:
                    max_step_dims = min(
                        6,
                        max(3, int(_optional_float((feature_payload or {}).get("step_count")) or 0)),
                    )
                step_dim_svg = build_step_dimensions(
                    item["svg"],
                    svg_bounds,
                    scale,
                    stroke_width,
                    line_profile=line_profile,
                    label_width=label_w,
                    label_height=label_h,
                    max_steps=3 if milling_steps else max_step_dims,
                    show_horizontal_steps=(name == "Front" and not milling_steps),
                    show_vertical_steps=(milling_steps and name == "Left") or turning_steps,
                    horizontal_side="below",
                    horizontal_max_ratio=(
                        None
                        if milling_steps
                        else (0.68 if int((feature_payload or {}).get("hole_count") or 0) >= 6 else None)
                    ),
                )
                if step_dim_svg:
                    dimension_svg = f"{dimension_svg}{step_dim_svg}"
                    dim_tracking["step_dim_count"] += step_dim_svg.count("<text")
            section_line_plan = item.get("section_line_plan") or {}
            if section_line_plan:
                section_label = str(section_line_plan.get("label") or "A").strip() or "A"
                section_axis = str(section_line_plan.get("cut_axis") or "V").strip().upper()
                try:
                    section_ratio = float(section_line_plan.get("cut_position_ratio", 0.5))
                except (TypeError, ValueError):
                    section_ratio = 0.5
                section_ratio = min(max(section_ratio, 0.0), 1.0)
                min_x, max_x, min_y, max_y = svg_bounds
                if section_axis == "H":
                    cut_pos = min_y + (max_y - min_y) * section_ratio
                    section_line_svg = _build_section_line_svg(
                        cut_pos,
                        min_x,
                        max_x,
                        label=section_label,
                        scale=scale,
                        stroke_width=float(line_profile.get("section", stroke_width)),
                        cut_axis="H",
                    )
                else:
                    cut_pos = min_x + (max_x - min_x) * section_ratio
                    section_line_svg = _build_section_line_svg(
                        cut_pos,
                        min_y,
                        max_y,
                        label=section_label,
                        scale=scale,
                        stroke_width=float(line_profile.get("section", stroke_width)),
                        cut_axis="V",
                    )
                dimension_svg = f"{dimension_svg}{section_line_svg}"
            detail_circle_plan = item.get("detail_circle_plan") or {}
            if detail_circle_plan:
                detail_label = str(detail_circle_plan.get("label") or "Z").strip() or "Z"
                detail_center_x = _optional_float(detail_circle_plan.get("center_x"))
                detail_center_y = _optional_float(detail_circle_plan.get("center_y"))
                detail_radius = _optional_float(detail_circle_plan.get("radius_mm"))
                if None not in (detail_center_x, detail_center_y, detail_radius):
                    detail_circle_svg = _build_detail_circle_svg(
                        detail_center_x,
                        detail_center_y,
                        detail_radius,
                        label=detail_label,
                        scale=scale,
                        stroke_width=float(line_profile.get("dimension", stroke_width)),
                    )
                    dimension_svg = f"{dimension_svg}{detail_circle_svg}"
            paper_geometry_bounds = transform_local_bounds_to_paper(
                svg_bounds,
                svg_bounds,
                item["cx"],
                item["cy"],
                scale,
                item["rotation_deg"],
            ) or svg_bounds
            paper_overall_dimensions = transform_dimension_entries_to_paper(
                dimension_metadata.get("overall_dimensions"),
                svg_bounds,
                item["cx"],
                item["cy"],
                scale,
                item["rotation_deg"],
            )
            paper_feature_dimensions = transform_dimension_entries_to_paper(
                dimension_metadata.get("feature_dimensions"),
                svg_bounds,
                item["cx"],
                item["cy"],
                scale,
                item["rotation_deg"],
            )
            item["dimension_quality"] = summarize_view_dimension_quality(
                paper_geometry_bounds,
                paper_overall_dimensions,
                paper_feature_dimensions,
            )
            # Collect paper-space text boxes for title-block overlap check
            for _dim_entry in (paper_overall_dimensions or []) + (paper_feature_dimensions or []):
                _tb = _dim_entry.get("text_box") if isinstance(_dim_entry, dict) else None
                if _tb and len(_tb) == 4:
                    dim_tracking["dimension_paper_boxes"].append(tuple(float(v) for v in _tb))
        item["dimension_metadata"] = dimension_metadata
        item["centerline_count"] = int(centerline_count)
        item["centerline_source"] = str(centerline_source or "none")
        item["line_profile"] = dict(line_profile or {})
        stroke_width = float(line_profile.get("visible", compute_stroke_width(scale)))
        item["render_scale"] = float(scale)
        item["render_stroke_width"] = float(stroke_width)
        item["render_dimension_svg"] = dimension_svg
        item["view_group_index"] = len(view_groups)
        view_groups.append(
            build_view_group(
                item["svg"],
                svg_bounds,      # SVG content bounds (for rendering)
                proj_bounds,     # Projected bounds (for positioning - the truth!)
                item["cx"],
                item["cy"],
                scale,
                rotation_deg=item["rotation_deg"],
                stroke_width=stroke_width,
                line_profile=line_profile,
                dimension_svg=dimension_svg,
                view_name=name,
                show_coordinate_system=False,  # Disabled - enable for debugging
            )
        )
        # DIN-konform: Standardansichten werden NICHT beschriftet.
        # Nur Sonderansichten (Schnitte, Details, Abwicklung) erhalten Labels.

    flat_pattern_overlay, abwicklung_meta = build_flat_pattern_overlay(
        view_data,
        sheet_name=sheet_resolved,
        sheet_w=sheet_w,
        draw_bottom=draw_bottom,
        margin=margin,
        layout_profile=layout_profile,
        feature_payload=feature_payload,
        flat_pattern_mode=flat_pattern_mode,
        unfold_result=unfold_result,
        sheet_metal_subtype=sheet_metal_subtype,
        dim_plan=dim_plan,
    )
    if flat_pattern_overlay:
        view_groups.append(flat_pattern_overlay)
    if abwicklung_meta:
        dim_tracking["dim_text_count"] += int(abwicklung_meta.get("feature_callout_count", 0) or 0)
        if int(abwicklung_meta.get("feature_callout_count", 0) or 0) > 0:
            dim_tracking["feature_dim_present"] = True
        drawing_bounds = (draw_left, draw_right, draw_top, draw_bottom)
        abwicklung_render_bounds = compute_abwicklung_render_bounds(abwicklung_meta)
        if abwicklung_render_bounds:
            abwicklung_meta["render_bounds"] = bounds_to_rect_dict(abwicklung_render_bounds)
            abwicklung_meta["overflow_mm"] = compute_bounds_overflow(abwicklung_render_bounds, drawing_bounds)
            abwicklung_meta["fits_inside_drawing_area"] = bool(
                (abwicklung_meta.get("overflow_mm") or {}).get("max", 0.0) <= 0.5
            )
            if iso_item is not None and iso_item.get("enabled", True):
                iso_scale = float(iso_item.get("render_scale", iso_item.get("scale", ortho_scale)))
                iso_render_bounds = transform_local_bounds_to_paper(
                    iso_item["svg_bounds"],
                    iso_item["svg_bounds"],
                    iso_item["cx"],
                    iso_item["cy"],
                    iso_scale,
                    iso_item["rotation_deg"],
                )
                iso_overlap = compute_bounds_intersection(iso_render_bounds, abwicklung_render_bounds)
                if iso_overlap["x"] > 0.5 and iso_overlap["y"] > 0.5:
                    gap_mm = 8.0
                    iso_w = iso_render_bounds[1] - iso_render_bounds[0]
                    iso_h = iso_render_bounds[3] - iso_render_bounds[2]
                    other_bounds = []
                    for candidate in view_data:
                        if candidate["name"] == "Iso" or not candidate.get("enabled", True):
                            continue
                        candidate_scale = float(candidate.get("render_scale", ortho_scale))
                        candidate_bounds = transform_local_bounds_to_paper(
                            candidate["svg_bounds"],
                            candidate["svg_bounds"],
                            candidate["cx"],
                            candidate["cy"],
                            candidate_scale,
                            candidate["rotation_deg"],
                        )
                        if candidate_bounds:
                            other_bounds.append(candidate_bounds)

                    keep_x = min(
                        draw_right - gap_mm - iso_w * 0.5,
                        max(draw_left + gap_mm + iso_w * 0.5, float(iso_item["cx"])),
                    )
                    candidate_centers = []
                    if (
                        layout_variant == "sheet_bent"
                        and cluster_left_anchor is not None
                        and cluster_top_anchor is not None
                        and cluster_fit_w_anchor is not None
                        and cluster_fit_h_anchor is not None
                    ):
                        lower_band_x = min(
                            abwicklung_render_bounds[0] - gap_mm - iso_w * 0.5,
                            max(
                                draw_left + gap_mm + iso_w * 0.5,
                                cluster_left_anchor + min(cluster_fit_w_anchor * 0.68, max(iso_w * 0.6, 34.0)),
                            ),
                        )
                        lower_band_y = min(
                            draw_bottom - gap_mm - iso_h * 0.5,
                            max(
                                draw_top + gap_mm + iso_h * 0.5,
                                cluster_top_anchor + cluster_fit_h_anchor + gap_mm + iso_h * 0.5,
                            ),
                        )
                        candidate_centers.extend(
                            [
                                (
                                    lower_band_x,
                                    lower_band_y,
                                ),
                                (
                                    abwicklung_render_bounds[0] - gap_mm - iso_w * 0.5,
                                    min(
                                        draw_bottom - gap_mm - iso_h * 0.5,
                                        max(draw_top + gap_mm + iso_h * 0.5, float(iso_item["cy"])),
                                    ),
                                ),
                                (
                                    keep_x,
                                    draw_top + gap_mm + iso_h * 0.5,
                                ),
                            ]
                        )
                    else:
                        candidate_centers.extend(
                            [
                                (
                                    keep_x,
                                    abwicklung_render_bounds[2] - gap_mm - iso_h * 0.5,
                                ),
                                (
                                    abwicklung_render_bounds[0] - gap_mm - iso_w * 0.5,
                                    min(
                                        draw_bottom - gap_mm - iso_h * 0.5,
                                        max(draw_top + gap_mm + iso_h * 0.5, float(iso_item["cy"])),
                                    ),
                                ),
                                (
                                    keep_x,
                                    draw_top + gap_mm + iso_h * 0.5,
                                ),
                            ]
                        )

                    for cand_x, cand_y in candidate_centers:
                        candidate_box = bounds_from_center(cand_x, cand_y, iso_w, iso_h)
                        if compute_bounds_overflow(candidate_box, drawing_bounds).get("max", 0.0) > 0.5:
                            continue
                        if compute_bounds_intersection(candidate_box, abwicklung_render_bounds)["x"] > 0.5 and compute_bounds_intersection(candidate_box, abwicklung_render_bounds)["y"] > 0.5:
                            continue
                        if any(
                            compute_bounds_intersection(candidate_box, other_box)["x"] > 0.5
                            and compute_bounds_intersection(candidate_box, other_box)["y"] > 0.5
                            for other_box in other_bounds
                        ):
                            continue
                        iso_item["cx"] = float(cand_x)
                        iso_item["cy"] = float(cand_y)
                        iso_item["render_scale"] = iso_scale
                        iso_index = iso_item.get("view_group_index")
                        if isinstance(iso_index, int) and 0 <= iso_index < len(view_groups):
                            view_groups[iso_index] = build_view_group(
                                iso_item["svg"],
                                iso_item["svg_bounds"],
                                iso_item["proj_bounds"],
                                iso_item["cx"],
                                iso_item["cy"],
                                iso_scale,
                                rotation_deg=iso_item["rotation_deg"],
                                stroke_width=float(iso_item.get("render_stroke_width", compute_stroke_width(iso_scale))),
                                line_profile=iso_item.get("line_profile"),
                                dimension_svg=str(iso_item.get("render_dimension_svg") or ""),
                                view_name=iso_item["name"],
                                show_coordinate_system=False,
                            )
                        log(
                            "ISO repositioned to avoid FlatPattern overlap: "
                            f"cx={iso_item['cx']:.2f}, cy={iso_item['cy']:.2f}"
                        )
                        break

    def _rebuild_view_groups(target_names=None):
        target_filter = set(target_names or [])
        for item in view_data:
            if not item.get("enabled", True):
                continue
            if target_filter and item["name"] not in target_filter:
                continue
            item_scale = float(item.get("render_scale", item.get("scale", ortho_scale)))
            item_index = item.get("view_group_index")
            if not isinstance(item_index, int) or not (0 <= item_index < len(view_groups)):
                continue
            view_groups[item_index] = build_view_group(
                item["svg"],
                item["svg_bounds"],
                item["proj_bounds"],
                item["cx"],
                item["cy"],
                item_scale,
                rotation_deg=item["rotation_deg"],
                stroke_width=float(item.get("render_stroke_width", compute_stroke_width(item_scale))),
                line_profile=item.get("line_profile"),
                dimension_svg=str(item.get("render_dimension_svg") or ""),
                view_name=item["name"],
                show_coordinate_system=False,
            )

    def _shift_views(target_names, dx=0.0, dy=0.0):
        target_filter = set(target_names or [])
        if not target_filter:
            return
        for item in view_data:
            if not item.get("enabled", True):
                continue
            if item["name"] not in target_filter:
                continue
            item["cx"] = float(item["cx"]) + float(dx)
            item["cy"] = float(item["cy"]) + float(dy)

    def _rect_to_bounds(rect):
        if not isinstance(rect, dict):
            return None
        try:
            return (
                float(rect.get("left")),
                float(rect.get("right")),
                float(rect.get("top")),
                float(rect.get("bottom")),
            )
        except (TypeError, ValueError):
            return None

    def _materialize_report():
        current_report = build_report()
        if dim_plan:
            current_report["dimension_plan"] = dim_plan
        if abwicklung_meta:
            current_report["abwicklung"] = abwicklung_meta
            current_report["quality"]["centerline_total"] = int(
                _optional_float(current_report["quality"].get("centerline_total")) or 0
            ) + int(_optional_float(abwicklung_meta.get("centerline_count")) or 0)
        return current_report

    report = _materialize_report()
    if not abwicklung_meta:
        front_view = (report.get("views") or {}).get("Front") or {}
        front_label_overflow = (front_view.get("label_overflow_mm") or {})
        front_dim_overflow = (front_view.get("dimension_overflow_mm") or {})
        top_overflow = max(
            _optional_float(front_label_overflow.get("top")) or 0.0,
            _optional_float(front_dim_overflow.get("top")) or 0.0,
        )
        if top_overflow > 0.5:
            views_bbox = report.get("quality", {}).get("views_bbox") or {}
            available_bottom = float(draw_bottom) - float(views_bbox.get("bottom") or draw_bottom)
            shift_y = min(available_bottom, top_overflow + 2.0)
            if shift_y > 0.5:
                for item in view_data:
                    if item.get("enabled", True):
                        item["cy"] = float(item["cy"]) + float(shift_y)
                _rebuild_view_groups()
                report = _materialize_report()

        ortho_names = {"Front", "Top", "Left"}
        front_left_overflow = max(
            _optional_float(front_label_overflow.get("left")) or 0.0,
            _optional_float(front_dim_overflow.get("left")) or 0.0,
        )
        front_top_overflow = max(
            _optional_float(front_label_overflow.get("top")) or 0.0,
            _optional_float(front_dim_overflow.get("top")) or 0.0,
        )
        if front_left_overflow > 0.5 or front_top_overflow > 0.5:
            report_views = report.get("views") or {}
            ortho_bounds = [
                _rect_to_bounds((report_views.get(name) or {}).get("render_bounds"))
                for name in ortho_names
            ]
            ortho_bounds = [bounds for bounds in ortho_bounds if bounds is not None]
            if ortho_bounds:
                ortho_left = min(bounds[0] for bounds in ortho_bounds)
                ortho_right = max(bounds[1] for bounds in ortho_bounds)
                ortho_bottom = max(bounds[3] for bounds in ortho_bounds)
                shift_x = 0.0
                shift_y = 0.0
                if front_left_overflow > 0.5:
                    room_right = float(draw_right) - float(ortho_right)
                    shift_x = min(room_right, front_left_overflow + 1.0)
                if front_top_overflow > 0.5:
                    room_bottom = float(draw_bottom) - float(ortho_bottom)
                    shift_y = min(room_bottom, front_top_overflow + 1.0)
                if shift_x > 0.5 or shift_y > 0.5:
                    _shift_views(ortho_names, dx=shift_x, dy=shift_y)
                    _rebuild_view_groups(ortho_names)
                    report = _materialize_report()

        ortho_overlap_pairs = [
            pair
            for pair in list((report.get("quality") or {}).get("view_overlap_pairs") or [])
            if "Iso" not in pair and "FlatPattern" not in pair
        ]
        if ortho_overlap_pairs:
            report_views = report.get("views") or {}
            for _ in range(2):
                moved = False
                for pair in ortho_overlap_pairs:
                    try:
                        left_name, right_name = [part.strip() for part in str(pair).split("vs", 1)]
                    except ValueError:
                        continue
                    left_bounds = _rect_to_bounds((report_views.get(left_name) or {}).get("render_bounds"))
                    right_bounds = _rect_to_bounds((report_views.get(right_name) or {}).get("render_bounds"))
                    if left_bounds is None or right_bounds is None:
                        continue
                    overlap = compute_bounds_intersection(left_bounds, right_bounds)
                    if overlap["x"] <= 0.5 or overlap["y"] <= 0.5:
                        continue
                    gap_mm = 3.0
                    if {left_name, right_name} == {"Front", "Top"}:
                        top_item_ref = next((item for item in view_data if item.get("name") == "Top" and item.get("enabled", True)), None)
                        front_item_ref = next((item for item in view_data if item.get("name") == "Front" and item.get("enabled", True)), None)
                        if top_item_ref is None:
                            continue
                        top_bounds = right_bounds if right_name == "Top" else left_bounds
                        front_bounds = right_bounds if right_name == "Front" else left_bounds
                        shift_remaining = overlap["y"] + gap_mm
                        room_bottom = float(draw_bottom) - float(top_bounds[3])
                        shift_top = min(room_bottom, shift_remaining)
                        if shift_top > 0.5:
                            _shift_views({"Top"}, dy=shift_top)
                            shift_remaining -= shift_top
                        if shift_remaining > 0.5 and front_item_ref is not None:
                            room_top = float(front_bounds[2]) - float(draw_top)
                            shift_front = min(room_top, shift_remaining)
                            if shift_front > 0.5:
                                _shift_views({"Front", "Left"}, dy=-shift_front)
                                shift_remaining -= shift_front
                        if shift_remaining < overlap["y"] + gap_mm:
                            _rebuild_view_groups({"Front", "Left", "Top"})
                            report = _materialize_report()
                            report_views = report.get("views") or {}
                            moved = True
                            break
                    if {left_name, right_name} == {"Front", "Left"}:
                        left_item_ref = next((item for item in view_data if item.get("name") == "Left" and item.get("enabled", True)), None)
                        if left_item_ref is None:
                            continue
                        left_view_bounds = right_bounds if right_name == "Left" else left_bounds
                        room_right = float(draw_right) - float(left_view_bounds[1])
                        shift_x = min(room_right, overlap["x"] + gap_mm)
                        if shift_x > 0.5:
                            _shift_views({"Left"}, dx=shift_x)
                            _rebuild_view_groups({"Left"})
                            report = _materialize_report()
                            report_views = report.get("views") or {}
                            moved = True
                            break
                if not moved:
                    break
                ortho_overlap_pairs = [
                    pair
                    for pair in list((report.get("quality") or {}).get("view_overlap_pairs") or [])
                    if "Iso" not in pair and "FlatPattern" not in pair
                ]
                if not ortho_overlap_pairs:
                    break

        overlap_pairs = list((report.get("quality") or {}).get("view_overlap_pairs") or [])
        if iso_item is not None and iso_item.get("enabled", True) and any("Iso" in pair for pair in overlap_pairs):
            gap_mm = 3.0
            for _ in range(2):
                report_views = report.get("views") or {}
                iso_bounds = _rect_to_bounds(((report_views.get("Iso") or {}).get("render_bounds")))
                other_bounds = [
                    _rect_to_bounds((view or {}).get("render_bounds"))
                    for name, view in report_views.items()
                    if name != "Iso" and isinstance(view, dict)
                ]
                other_bounds = [bounds for bounds in other_bounds if bounds is not None]
                if not iso_bounds or not other_bounds:
                    break
                right_shift = 0.0
                down_shift = 0.0
                for bounds in other_bounds:
                    overlap = compute_bounds_intersection(iso_bounds, bounds)
                    if overlap["x"] > 0.5 and overlap["y"] > 0.5:
                        right_shift = max(right_shift, overlap["x"] + gap_mm)
                        down_shift = max(down_shift, overlap["y"] + gap_mm)
                draw_room_right = float(draw_right) - float(iso_bounds[1])
                draw_room_bottom = float(draw_bottom) - float(iso_bounds[3])
                moved = False
                if right_shift > 0.5 and right_shift <= draw_room_right:
                    iso_item["cx"] = float(iso_item["cx"]) + float(right_shift)
                    moved = True
                elif down_shift > 0.5 and down_shift <= draw_room_bottom:
                    iso_item["cy"] = float(iso_item["cy"]) + float(down_shift)
                    moved = True
                if not moved:
                    break
                _rebuild_view_groups({"Iso"})
                report = _materialize_report()
                if not any("Iso" in pair for pair in ((report.get("quality") or {}).get("view_overlap_pairs") or [])):
                    break

    if (
        should_promote_to_a2(report, dim_x, dim_y, dim_z, requested_sheet=requested_sheet, dim_plan=dim_plan)
        and sheet_resolved != "A2"
        and os.getenv("DRAWFORM_AUTO_SHEET_SECOND_PASS") != "1"
    ):
        log("Auto-sheet decision: promoting layout to A2 and rerunning export.")
        App.closeDocument(doc.Name)
        env = os.environ.copy()
        env["DRAWFORM_SHEET_FORCE"] = "A2"
        env["DRAWFORM_AUTO_SHEET_SECOND_PASS"] = "1"
        env["DRAWFORM_SHEET_REQUESTED"] = str(requested_sheet)
        rerun = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(input_path), str(output_path)],
            capture_output=True,
            text=True,
            env=env,
        )
        if rerun.returncode != 0:
            details = (rerun.stderr or rerun.stdout or "").strip()
            raise RuntimeError(f"Auto-sheet A2 rerun failed: {details}")
        return

    dimensions_text = "Gesamtmass: X={}, Y={}, Z={}".format(
        format_de_number(dim_x),
        format_de_number(dim_y),
        format_de_number(dim_z),
    )
    standard_line = str(meta.get("standard", "DIN EN ISO 128/129-1"))
    projection_line = str(meta.get("projection", "1. Winkel (DIN EN ISO 5456-2)"))
    unit_line = f"Alle Masse in {meta.get('unit', 'mm')} sofern nicht anders angegeben."
    feature_lines = build_feature_annotation_lines(feature_payload, layout_profile)
    process_lines = []
    if layout_profile == "sheet_metal":
        thickness = estimate_sheet_thickness(feature_payload, dim_x, dim_y, dim_z)
        flat_pattern = (feature_payload or {}).get("flat_pattern") or {}
        k_used = flat_pattern.get("k_factor_used") or 0.33
        process_lines = [f"Blechst\u00e4rke = {format_de_number(thickness)}"]
        if sheet_metal_subtype == "biegeteil":
            process_lines.append(f"K-Faktor = {format_de_number(k_used, 2)}")
        # "Scharfe Kanten entgraten" comes from build_feature_annotation_lines — no duplicate
    annotation_lines = [
        dimensions_text,
        unit_line,
        f"Norm: {standard_line} | Projektion: {projection_line}",
    ] + process_lines + feature_lines
    log("DEBUG: dimensions_text set")

    template_path = Path(__file__).resolve().parent.parent / "templates" / spec["template"]
    if not template_path.exists():
        raise RuntimeError(f"Template not found: {template_path}")

    views_svg = "\n".join(view_groups)
    annotation_y = origin_y + avail_h - 4
    page_svg = build_page_svg(template_path, meta, views_svg, annotation_lines, annotation_y)
    pre_export_check = evaluate_pre_export_quality(report, page_svg, dim_x, dim_y, dim_z, dim_tracking=dim_tracking)
    report["pre_export_check"] = pre_export_check
    if pre_export_check.get("status") != "OK":
        log(f"Pre-export quality: {pre_export_check.get('status')} -> {pre_export_check.get('issues')}", level="QUALITY")
    report["quality"]["line_hierarchy"] = {
        "visible_vs_dimension": "thick_vs_thin",
        "hidden_dash": True,
        "centerline_chain": True,
    }
    svg_path = Path(output_path).with_suffix(".svg")
    svg_path.write_text(page_svg, encoding="utf-8")

    # Always write debug artifacts (SVG + report JSON) before potential abort
    debug_dir = os.getenv("DRAWFORM_DEBUG_DIR")
    if debug_dir:
        try:
            debug_root = Path(debug_dir)
            debug_root.mkdir(parents=True, exist_ok=True)
            json_name = f"{Path(input_path).stem}_report.json"
            json_path = debug_root / json_name
            json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log(f"Report JSON written: {json_path}")
            debug_name = f"{Path(input_path).stem}_debug.svg"
            debug_path = debug_root / debug_name
            debug_path.write_text(page_svg, encoding="utf-8")
            log(f"Debug SVG written: {debug_path}")
        except (OSError, TypeError, ValueError) as exc:
            log(f"Failed to write debug SVG: {exc}")

    # P0: Hard abort when quality check detects issues
    if pre_export_check.get("status") != "OK":
        quality_issues = pre_export_check.get("issues", [])
        blocker_list = pre_export_check.get("blockers", [])
        status = pre_export_check["status"]
        msg_parts = [f"Quality gate {status}: Export blockiert."]
        if blocker_list:
            msg_parts.append(f"Blocker ({len(blocker_list)}): " + "; ".join(blocker_list))
        warnings_only = [i for i in quality_issues if i not in blocker_list]
        if warnings_only:
            msg_parts.append(f"Warnungen ({len(warnings_only)}): " + "; ".join(warnings_only))
        raise QualityGateError(" | ".join(msg_parts))

    log(f"Rendering PDF via svg2rlg: {output_path}")
    drawing = svg2rlg(str(svg_path))
    if drawing is None:
        raise RuntimeError("SVG parse failed.")
    renderPDF.drawToFile(drawing, output_path)

    if not os.path.exists(output_path):
        raise RuntimeError("PDF export failed (no output).")

    App.closeDocument(doc.Name)
    try:
        svg_path.unlink(missing_ok=True)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except QualityGateError as exc:
        sys.stderr.write(str(exc))
        sys.exit(3)
    except Exception as exc:
        sys.stderr.write(str(exc))
        sys.exit(1)

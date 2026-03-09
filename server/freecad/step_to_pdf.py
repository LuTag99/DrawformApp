import json
import os
import re
import sys
import math
import subprocess
import datetime as dt
from pathlib import Path
from xml.sax.saxutils import escape

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
ALLOWED_SCALE_LABELS = {
    "20:1",
    "10:1",
    "5:1",
    "2:1",
    "1:1",
    "1:2",
    "1:5",
    "1:10",
    "1:20",
    "1:50",
    "1:100",
}
TOLERANCE_2768_RE = re.compile(r"^(?:din\s+iso|iso)\s*2768-([fmcv])([hkl])?$", re.IGNORECASE)
DEFAULT_STANDARD = "DIN EN ISO 128/129-1"
DEFAULT_PROJECTION = "1. Winkel (DIN EN ISO 5456-2)"
DEFAULT_GENERAL_TOLERANCE = "DIN ISO 2768-mK"
SHEET_SPECS = {
    "A3": {"width": 420.0, "height": 297.0, "title_block_h": 55.0, "template": "iso7200_a3_landscape.svg"},
    "A2": {"width": 594.0, "height": 420.0, "title_block_h": 62.0, "template": "iso7200_a2_landscape.svg"},
}


def log(message):
    sys.stderr.write(f"[drawform] {message}\n")


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
        except Exception as exc:
            log(f"Bbox wireframe fallback also failed: {exc}")
            return '<g></g>', False, True
    try:
        svg = TechDraw.projectToSVG(shape, direction)
        return svg, True, False
    except Exception as exc:
        log(f"TechDraw.projectToSVG failed: {exc} — trying bbox wireframe fallback")
        try:
            svg = _bbox_wireframe_svg(shape, direction)
            return svg, True, True
        except Exception:
            return '<g></g>', False, True


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
    return stem.strip()


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
                          label_width=None, label_height=None, max_steps=5):
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

    # Horizontal step dimensions (below geometry):
    # Unique X positions along horizontal segments → step widths from left edge
    x_positions = set()
    for s in h_segs:
        x_positions.add(s["x1"])
        x_positions.add(s["x2"])
    for s in v_segs:
        x_positions.add(s["x1"])  # x1==x2 for vertical
    unique_x = _unique_positions(list(x_positions), tolerance=1.0 / scale)

    # Filter: only positions between min_x and max_x, exclude the reference edge (min_x) and the far edge (max_x)
    step_x = [x for x in unique_x if x > min_x + width * 0.05 and x < max_x - width * 0.05]
    step_x = step_x[:max_steps]

    # Draw horizontal step dimensions below geometry
    if step_x:
        for i, x_pos in enumerate(step_x):
            dim_y = max_y + gap + step_spacing * (i + 2)  # offset below overall dim
            step_val = (x_pos - min_x) / scale if scale > 0 else 0
            if label_width is not None:
                step_val = (x_pos - min_x) / (max_x - min_x) * label_width
            # Extension lines
            parts.append(f'<line x1="{x_pos:.3f}" y1="{max_y:.3f}" x2="{x_pos:.3f}" y2="{dim_y + ext_over:.3f}" stroke="rgb(0,0,0)" stroke-width="{dim_sw:.4f}" />')
            # Left reference extension (only first time)
            if i == 0:
                parts.append(f'<line x1="{min_x:.3f}" y1="{max_y:.3f}" x2="{min_x:.3f}" y2="{dim_y + ext_over + step_spacing * (len(step_x) - 1):.3f}" stroke="rgb(0,0,0)" stroke-width="{dim_sw:.4f}" />')
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
    unique_y = _unique_positions(list(y_positions), tolerance=1.0 / scale)

    step_y = [y for y in unique_y if y > min_y + height * 0.05 and y < max_y - height * 0.05]
    step_y = step_y[:max_steps]

    if step_y:
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


def bounds_size(bounds):
    min_x, max_x, min_y, max_y = bounds
    width = max(max_x - min_x, 0.1)
    height = max(max_y - min_y, 0.1)
    return width, height


def expand_bounds(bounds, pad):
    min_x, max_x, min_y, max_y = bounds
    return min_x - pad, max_x + pad, min_y - pad, max_y + pad


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
    gap_mm = 0.0  # Extension lines start at part edge (DIN ISO 129-1, $DIMEXO=0)
    ext_over_mm = max(0.6, min(2.0, offset_mm * 0.25))
    arrow_len_mm = max(0.6, min(2.2, offset_mm * 0.22))
    arrow_half_mm = max(0.3, arrow_len_mm * 0.35)
    text_size_mm = 3.6
    text_gap_mm = 1.6
    pad_mm = offset_mm + ext_over_mm + text_gap_mm + text_size_mm

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
    dim_stroke = max(0.0008, stroke_width * 0.6)
    if isinstance(line_profile, dict):
        dim_stroke = max(0.0008, float(line_profile.get("dimension", dim_stroke)))

    y_dim = max_y + offset
    x_dim = max_x + offset
    mid_x = (min_x + max_x) / 2
    mid_y = (min_y + max_y) / 2

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
    if show_vertical:
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

    lines = (
        f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
        f'stroke-linecap="butt" stroke-linejoin="miter" font-size="{text_size:.2f}" '
        f'font-family="Arial">'
        + "".join(line_parts)
        + "</g>"
    )
    width_x = mid_x
    width_y = -y_dim
    height_x = x_dim
    height_y = -mid_y
    char_w = text_size * 0.6
    width_text_w = max(len(label_w), 1) * char_w
    height_text_w = max(len(label_h), 1) * char_w
    rect_pad = text_size * 0.2
    width_rect_x = width_x - width_text_w * 0.5 - rect_pad
    width_rect_y = width_y - text_size * 0.7
    width_rect_w = width_text_w + rect_pad * 2
    width_rect_h = text_size * 1.4
    height_rect_x = height_x - height_text_w * 0.5 - rect_pad
    height_rect_y = height_y - text_size * 0.7
    height_rect_w = height_text_w + rect_pad * 2
    height_rect_h = text_size * 1.4
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


def build_round_overall_dimension_svg(svg_group, bounds, scale, stroke_width, line_profile=None):
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
    dim_stroke = max(0.0008, stroke_width * 0.6)
    if isinstance(line_profile, dict):
        dim_stroke = max(0.0008, float(line_profile.get("dimension", dim_stroke)))

    y_dim = max_y + offset
    mid_x = (min_x + max_x) / 2
    label = f"Ø{format_de_number(diameter)}"
    y_ext_left = _outline_start_y(svg_group, bounds, min_x, find_max=True)
    y_ext_right = _outline_start_y(svg_group, bounds, max_x, find_max=True)

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
    return lines + arrows + _feature_text_svg(label, mid_x, y_dim, text_size, anchor="middle")


def resolve_overall_dimension_axes(view_name, dim_plan=None):
    if dim_plan:
        view_plan = next((v for v in dim_plan.get("views", []) if v.get("view_name") == view_name), None)
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


def view_requests_feature_dimensions(view_name, dim_plan=None):
    if not dim_plan:
        return False
    view_plan = next((v for v in dim_plan.get("views", []) if v.get("view_name") == view_name), None)
    view_dims = (view_plan or {}).get("dimensions", [])
    return any(
        d.get("dim_type") in (
            "hole_diameter",
            "hole_pitch",
            "hole_location_x",
            "hole_location_y",
            "thread_callout",
            "bend_radius",
        )
        for d in view_dims
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


def compute_transformed_bounds(svg_bounds, center_x, center_y, scale, rotation_deg):
    """
    Compute the actual paper-space bounding box after the SVG transformation.
    This exactly mimics what build_view_group does.
    
    The SVG transform is: translate(cx,cy) scale(s) rotate(deg) translate(-local_cx, local_cy)
    Applied RIGHT TO LEFT: inner_translate -> rotate -> scale -> outer_translate
    """
    min_x, max_x, min_y, max_y = svg_bounds
    
    # IMPORTANT: build_view_group rotates bounds FIRST, then calculates local center
    if rotation_deg % 180 != 0:
        rotated = rotate_bounds_90(svg_bounds)
        min_x_r, max_x_r, min_y_r, max_y_r = rotated
        center_x_local = (min_x_r + max_x_r) / 2
        center_y_local = (min_y_r + max_y_r) / 2
    else:
        center_x_local = (min_x + max_x) / 2
        center_y_local = (min_y + max_y) / 2
    
    # The SVG inner translate is: translate(-center_x_local, center_y_local)
    # This means ADD (-center_x_local) to x, and ADD (center_y_local) to y
    inner_tx = -center_x_local
    inner_ty = center_y_local
    
    # Transform the four corners of the ORIGINAL SVG bounds
    corners = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]
    paper_corners = []
    
    for px, py in corners:
        # Step 1: inner translate - ADD the translation values
        x1 = px + inner_tx
        y1 = py + inner_ty
        
        # Step 2: rotate (SVG rotates clockwise for positive angles)
        rad = math.radians(rotation_deg)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        x2 = x1 * cos_r - y1 * sin_r
        y2 = x1 * sin_r + y1 * cos_r
        
        # Step 3: scale
        x3 = x2 * scale
        y3 = y2 * scale
        
        # Step 4: outer translate
        x4 = x3 + center_x
        y4 = y3 + center_y
        
        paper_corners.append((x4, y4))
    
    xs = [c[0] for c in paper_corners]
    ys = [c[1] for c in paper_corners]
    return min(xs), max(xs), min(ys), max(ys)


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
    
    # Transform: 
    # 1. translate to paper position (center_x, center_y)
    # 2. scale
    # 3. rotate (if needed)
    # 4. translate to center the geometry (using SVG center)
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
        scale = compute_fit_scale(padded_bounds, cell_w, cell_h, padding=padding)
    return padded_bounds, scale


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
    except Exception:
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


def first_angle_projection(shape, points):
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
        try:
            svg_pos = TechDraw.projectToSVG(shape, third_axis)
        except Exception:
            svg_pos = '<g></g>'
        try:
            svg_neg = TechDraw.projectToSVG(shape, third_axis.negative())
        except Exception:
            svg_neg = '<g></g>'
        score_pos = svg_detail_score(svg_pos)
        score_neg = svg_detail_score(svg_neg)
        candidate_scores = [
            (f"+{third_name}", score_pos),
            (f"-{third_name}", score_neg),
        ]
        score_eps = max(0.5, abs(score_pos) * 0.005, abs(score_neg) * 0.005)
        if score_neg > score_pos + score_eps:
            front_dir = third_axis.negative()
            best_name = f"-{third_name}"
            best_score = score_neg
        elif score_pos > score_neg + score_eps:
            front_dir = third_axis
            best_name = f"+{third_name}"
            best_score = score_pos
        else:
            # Tie: keep deterministic negative preference for mirrored views.
            front_dir = third_axis.negative()
            best_name = f"-{third_name}"
            best_score = max(score_pos, score_neg)
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
            try:
                svg = TechDraw.projectToSVG(shape, d)
                score = svg_detail_score(svg)
            except Exception:
                score = 0
            candidate_scores.append((name, score))
            log(f"[FirstAngle]   candidate {name}: score={score:.1f}")
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
            svg = TechDraw.projectToSVG(shape, d)
            scores.append(svg_detail_score(svg))
        except Exception:
            scores.append(0.0)
    confidence_basis = "all_candidates"
    confidence_values = scores
    # If available, prefer the exact candidates used for front selection.
    if candidate_scores:
        confidence_basis = "front_candidates"
        confidence_values = [value for _name, value in candidate_scores]

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
                "name": name,
                "score": round(score, 2),
            }
            for name, score in (candidate_scores if "candidate_scores" in locals() else [])
        ],
        "confidence_basis": confidence_basis,
        "candidate_score_gap": round(score_gap, 5),
        "front_ambiguous": bool(score_gap < 0.08),
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


def compute_view_directions(shape, points=None):
    """
    Use First-Angle Projection (ISO/DIN) for view selection.
    
    Returns dictionary with front, left, top, iso directions and debug info.
    """
    points = points or collect_points(shape)
    if len(points) < 3:
        return None
    
    result = first_angle_projection(shape, points)
    
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
        payload = probe_feature_payload(shape)
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log(f"Feature probe failed in PDF export: {exc}")
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "feature_probe_invalid_payload"}


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
        candidates = [
            server_root / ".venv" / "Scripts" / "python.exe",
            server_root.parent / ".venv" / "Scripts" / "python.exe",
            server_root / ".venv" / "bin" / "python",
            server_root.parent / ".venv" / "bin" / "python",
        ]
        helper_python = next((str(path) for path in candidates if path.exists()), None)
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


def select_layout_profile(input_path, feature_payload, dim_x, dim_y, dim_z):
    lower_input = str(input_path or "").lower()

    # Tier 0: Explicit path-based override (backward compatible)
    if "sheetmetals" in lower_input or "sheetmetal" in lower_input:
        return "sheet_metal"

    if isinstance(feature_payload, dict):
        measured_t = _optional_float(feature_payload.get("measured_thickness_mm"))

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
        # Guard: cone faces (chamfers/fillets) are a strong milling indicator.
        cone_count_t3 = int(feature_payload.get("cone_face_count") or 0)
        if cone_count_t3 == 0:
            thickness_axis = str(feature_payload.get("thickness_axis") or "").upper()
            dims = {"X": float(dim_x), "Y": float(dim_y), "Z": float(dim_z)}
            thickness = dims.get(thickness_axis, min(dims.values()))
            mid_dim = sorted(dims.values(), reverse=True)[1]
            if mid_dim > 0 and thickness / mid_dim < 0.15:
                return "sheet_metal"

    return "milling"


def detect_flat_pattern_mode(layout_profile):
    if layout_profile != "sheet_metal":
        return "not_applicable"
    for module_name in ("SheetMetal", "SheetMetalCmd", "SheetMetalUnfolder", "SMUnfold"):
        try:
            __import__(module_name)
            return "sheetmetal_module"
        except Exception:
            continue
    return "fallback_projected"


def compute_layout_usage(views_bbox, draw_bbox):
    views_w = max(0.0, float(views_bbox.get("right", 0.0)) - float(views_bbox.get("left", 0.0)))
    views_h = max(0.0, float(views_bbox.get("bottom", 0.0)) - float(views_bbox.get("top", 0.0)))
    draw_w = max(1e-6, float(draw_bbox.get("right", 0.0)) - float(draw_bbox.get("left", 0.0)))
    draw_h = max(1e-6, float(draw_bbox.get("bottom", 0.0)) - float(draw_bbox.get("top", 0.0)))
    return (views_w / draw_w) * (views_h / draw_h)


def select_view_layout_variant(layout_profile, sheet_metal_subtype, feature_payload, dim_x, dim_y, dim_z):
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
    return "grid_2x2"


def build_view_slots(layout_variant, origin_x, origin_y, avail_w, avail_h):
    if layout_variant == "sheet_bent":
        views_w = avail_w * 0.60
        cell_w = views_w / 2.0
        cell_h = avail_h / 2.0
        return {
            "Front": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 0.5, "cy": origin_y + cell_h * 0.5, "enabled": True},
            "Left": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 1.5, "cy": origin_y + cell_h * 0.5, "enabled": True},
            "Top": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 0.5, "cy": origin_y + cell_h * 1.5, "enabled": True},
            "Iso": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 1.5, "cy": origin_y + cell_h * 1.5, "enabled": True},
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
        side_w = max(84.0, avail_w * 0.28)
        bottom_h = max(36.0, avail_h * 0.24)
        side_w = min(side_w, avail_w * 0.38)
        bottom_h = min(bottom_h, avail_h * 0.34)
        front_w = avail_w - side_w
        front_h = avail_h - bottom_h
        return {
            "Front": {"w": front_w, "h": front_h, "cx": origin_x + front_w * 0.5, "cy": origin_y + front_h * 0.5, "enabled": True},
            "Left": {"w": side_w, "h": front_h, "cx": origin_x + front_w + side_w * 0.5, "cy": origin_y + front_h * 0.5, "enabled": True},
            "Top": {"w": front_w, "h": bottom_h, "cx": origin_x + front_w * 0.5, "cy": origin_y + front_h + bottom_h * 0.5, "enabled": True},
            "Iso": {"w": side_w, "h": bottom_h, "cx": origin_x + front_w + side_w * 0.5, "cy": origin_y + front_h + bottom_h * 0.5, "enabled": True},
        }

    cell_w = avail_w / 2.0
    cell_h = avail_h / 2.0
    return {
        "Front": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 0.5, "cy": origin_y + cell_h * 0.5, "enabled": True},
        "Left": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 1.5, "cy": origin_y + cell_h * 0.5, "enabled": True},
        "Top": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 0.5, "cy": origin_y + cell_h * 1.5, "enabled": True},
        "Iso": {"w": cell_w, "h": cell_h, "cx": origin_x + cell_w * 1.5, "cy": origin_y + cell_h * 1.5, "enabled": True},
    }


def should_promote_to_a2(report, dim_x, dim_y, dim_z, *, requested_sheet):
    if str(requested_sheet or "").lower() != "auto":
        return False
    quality = (report or {}).get("quality", {})
    overflow_max = _optional_float(((quality.get("overflow_mm") or {}).get("max"))) or 0.0
    if overflow_max > 0.5:
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
            if float(resolved["sweep_abs"]) >= math.radians(140.0):
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


def build_centerline_svg(svg_group, scale, stroke_width, limit=12, line_profile=None):
    """
    Build ISO-128 style centerlines (chain thin) for circular features.
    """
    circles = extract_svg_circular_features(svg_group)
    targets = _select_centerline_circles(circles, scale, limit=limit)
    if not targets:
        return "", 0

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
    return "".join(parts), len(targets)


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
):
    margin = max(0.15, text_size * 0.15)
    base = max(min_y + text_size, min(max_y - text_size, preferred_y))
    offsets = [0.0]
    for step in range(1, 10):
        delta = step * min_gap
        offsets.append(delta)
        offsets.append(-delta)
    for offset in offsets:
        y = max(min_y + text_size, min(max_y - text_size, base + offset))
        if any(abs(y - other) < min_gap * 0.85 for other in used_positions):
            continue
        bbox = _text_collision_box(text, x, y, text_size, anchor)
        if any(_bbox_overlaps(bbox, box, margin=margin) for box in collision_boxes):
            continue
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


def _feature_text_svg(text, x, y, text_size, anchor="middle"):
    # White background rectangle behind text for readability
    char_w = text_size * 0.6
    text_w = max(len(text), 1) * char_w
    rect_pad = text_size * 0.15
    if anchor == "middle":
        rect_x = x - text_w * 0.5 - rect_pad
    elif anchor == "start":
        rect_x = x - rect_pad
    else:
        rect_x = x - text_w - rect_pad
    rect_y = -y - text_size * 0.7
    rect_w = text_w + rect_pad * 2
    rect_h = text_size * 1.3
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


def _build_round_feature_dimension_svg(svg_group, svg_bounds, feature_payload, scale, dim_stroke, text_size, label_gap):
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
    text_offset = max(10.0 / max(scale, 0.05), outer["r"] * 0.18)
    knee_offset = max(4.0 / max(scale, 0.05), outer["r"] * 0.08)

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
        collision_boxes.append(_line_collision_box(start_x, start_y, knee_x, knee_y, line_pad))
        collision_boxes.append(_line_collision_box(knee_x, knee_y, end_x, end_y, line_pad))
        parts.append(_feature_text_svg(label, text_x, text_y, text_size, anchor=anchor))

    return "".join(parts)


def build_feature_dimension_svg(svg_group, svg_bounds, feature_payload, scale, stroke_width, line_profile=None):
    if not isinstance(feature_payload, dict) or feature_payload.get("ok") is not True:
        return ""
    circles = extract_svg_circular_features(svg_group)
    main_holes = []
    main_radius = 0.0
    if circles:
        circles = sorted(circles, key=lambda item: item["r"], reverse=True)
        buckets = {}
        for circle in circles:
            key = round(circle["r"] * 2.0) / 2.0
            buckets.setdefault(key, []).append(circle)
        main_bucket = max(buckets.items(), key=lambda item: (len(item[1]), item[0]))[0]
        tol = max(0.5, main_bucket * 0.15)
        main_holes = [circle for circle in circles if abs(circle["r"] - main_bucket) <= tol]
        main_radius = main_bucket

    min_x, max_x, min_y, max_y = svg_bounds
    dim_stroke = max(0.0008, stroke_width * 0.55)
    if isinstance(line_profile, dict):
        dim_stroke = max(0.0008, float(line_profile.get("dimension", dim_stroke)))
    # Use dimension_metrics for consistent sizing with overall dimensions
    _metrics = dimension_metrics(svg_bounds, scale)
    arrow_len = _metrics["arrow_len"]
    arrow_half = _metrics["arrow_half"]
    text_size = max(0.2, 2.8 / scale)  # slightly smaller than overall (3.6) but readable
    label_gap = max(1.8, 4.0 / max(scale, 0.05))
    round_feature_svg = _build_round_feature_dimension_svg(
        svg_group,
        svg_bounds,
        feature_payload,
        scale,
        dim_stroke,
        text_size,
        label_gap,
    )
    if round_feature_svg:
        return round_feature_svg
    used_label_y = []
    parts = []
    hole_pitch = _optional_float(feature_payload.get("hole_pitch_mm"))
    pitch_drawn = False
    used_dimension_labels = set()

    geom_pad = max(0.8, 1.8 / max(scale, 0.05))
    line_pad = max(0.25, 0.6 / max(scale, 0.05))
    arrow_pad = max(0.25, 0.7 / max(scale, 0.05))
    collision_boxes = [(min_x - geom_pad, max_x + geom_pad, min_y - geom_pad, max_y + geom_pad)]

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
            pref_above = float(circle["cy"]) - radius - max(4.0 / scale, label_gap * 0.55)
            pref_below = float(circle["cy"]) + radius + max(4.0 / scale, label_gap * 0.55)
            y_dim = pref_above
            if y_dim < min_y + (2.5 / scale):
                y_dim = pref_below
            y_dim = max(min_y + (2.5 / scale), min(max_y - (2.5 / scale), y_dim))
            parts.append(
                f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
                f'stroke-linecap="butt" stroke-linejoin="miter">'
                f'<line x1="{x0:.3f}" y1="{y_dim:.3f}" x2="{x1:.3f}" y2="{y_dim:.3f}" />'
                f'<line x1="{x0:.3f}" y1="{float(circle["cy"]):.3f}" x2="{x0:.3f}" y2="{y_dim:.3f}" />'
                f'<line x1="{x1:.3f}" y1="{float(circle["cy"]):.3f}" x2="{x1:.3f}" y2="{y_dim:.3f}" />'
                "</g>"
            )
            collision_boxes.append(_line_collision_box(x0, y_dim, x1, y_dim, line_pad))
            collision_boxes.append(_line_collision_box(x0, float(circle["cy"]), x0, y_dim, line_pad))
            collision_boxes.append(_line_collision_box(x1, float(circle["cy"]), x1, y_dim, line_pad))
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
                text_y = _reserve_feature_label_position(
                    label_text,
                    text_x,
                    y_dim + (1.8 / scale),
                    text_size,
                    "middle",
                    used_label_y,
                    label_gap,
                    min_y,
                    max_y,
                    collision_boxes,
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
        pref_right = float(circle["cx"]) + radius + max(4.0 / scale, label_gap * 0.55)
        pref_left = float(circle["cx"]) - radius - max(4.0 / scale, label_gap * 0.55)
        x_dim = pref_right
        if x_dim > max_x - (2.5 / scale):
            x_dim = pref_left
        x_dim = max(min_x + (2.5 / scale), min(max_x - (2.5 / scale), x_dim))
        parts.append(
            f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
            f'stroke-linecap="butt" stroke-linejoin="miter">'
            f'<line x1="{x_dim:.3f}" y1="{y0:.3f}" x2="{x_dim:.3f}" y2="{y1:.3f}" />'
            f'<line x1="{float(circle["cx"]):.3f}" y1="{y0:.3f}" x2="{x_dim:.3f}" y2="{y0:.3f}" />'
            f'<line x1="{float(circle["cx"]):.3f}" y1="{y1:.3f}" x2="{x_dim:.3f}" y2="{y1:.3f}" />'
            "</g>"
        )
        collision_boxes.append(_line_collision_box(x_dim, y0, x_dim, y1, line_pad))
        collision_boxes.append(_line_collision_box(float(circle["cx"]), y0, x_dim, y0, line_pad))
        collision_boxes.append(_line_collision_box(float(circle["cx"]), y1, x_dim, y1, line_pad))
        parts.append(
            f'<g fill="rgb(0, 0, 0)" stroke="none">'
            f'<polygon points="{x_dim:.3f},{y0:.3f} {x_dim - arrow_half:.3f},{y0 + arrow_len:.3f} {x_dim + arrow_half:.3f},{y0 + arrow_len:.3f}" />'
            f'<polygon points="{x_dim:.3f},{y1:.3f} {x_dim - arrow_half:.3f},{y1 - arrow_len:.3f} {x_dim + arrow_half:.3f},{y1 - arrow_len:.3f}" />'
            "</g>"
        )
        label_text = format_de_number(span)
        if label_text not in used_dimension_labels:
            used_dimension_labels.add(label_text)
            text_x = x_dim + (1.5 / scale)
            text_y = (y0 + y1) * 0.5
            parts.append(
                f'<g fill="rgb(0,0,0)" stroke="none" font-size="{text_size:.3f}" '
                f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
                f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
                f'<text x="{text_x:.3f}" y="{-text_y:.3f}" text-anchor="middle" '
                f'transform="rotate(90,{text_x:.3f},{-text_y:.3f})">{label_text}</text></g>'
            )

    edge_location_targets = []
    if circles:
        edge_location_targets = sorted(circles, key=lambda item: item["r"], reverse=True)
    elif main_holes:
        edge_location_targets = list(main_holes)

    # Hole pitch dimension between outer main-hole centers.
    if len(main_holes) >= 2:
        by_x = sorted(main_holes, key=lambda item: item["cx"])
        left_hole = by_x[0]
        right_hole = by_x[-1]
        span = abs(right_hole["cx"] - left_hole["cx"])
        if span > max(1.0, 5.0 / scale):
            if hole_pitch is None or hole_pitch <= 0:
                hole_pitch = span
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
            # Prefer positioning from one outer datum edge to avoid pure chain dimensioning.
            edge_span = abs(left_hole["cx"] - min_x)
            if edge_span > max(1.0, 4.0 / scale):
                edge_y = y_dim - max(2.5 / scale, label_gap * 0.55)
                if edge_y < min_y + (2.5 / scale):
                    edge_y = y_dim + max(2.5 / scale, label_gap * 0.55)
                ex0 = min_x
                ex1 = left_hole["cx"]
                parts.append(
                    f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
                    f'stroke-linecap="butt" stroke-linejoin="miter">'
                    f'<line x1="{ex0:.3f}" y1="{edge_y:.3f}" x2="{ex1:.3f}" y2="{edge_y:.3f}" />'
                    f'<line x1="{ex0:.3f}" y1="{left_hole["cy"]:.3f}" x2="{ex0:.3f}" y2="{edge_y:.3f}" />'
                    f'<line x1="{ex1:.3f}" y1="{left_hole["cy"]:.3f}" x2="{ex1:.3f}" y2="{edge_y:.3f}" />'
                    "</g>"
                )
                collision_boxes.append(_line_collision_box(ex0, edge_y, ex1, edge_y, line_pad))
                collision_boxes.append(_line_collision_box(ex0, left_hole["cy"], ex0, edge_y, line_pad))
                collision_boxes.append(_line_collision_box(ex1, left_hole["cy"], ex1, edge_y, line_pad))
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
                    edge_ty = _reserve_feature_label_position(
                        edge_text,
                        edge_tx,
                        edge_y + (1.8 / scale),
                        text_size,
                        "middle",
                        used_label_y,
                        label_gap,
                        min_y,
                        max_y,
                        collision_boxes,
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
            # Vertical hole-to-edge: distance from bottom edge to bottom-most hole
            by_y = sorted(main_holes, key=lambda item: item["cy"], reverse=True)
            bottom_hole = by_y[0]
            vert_edge_span = abs(max_y - bottom_hole["cy"])
            if vert_edge_span > max(1.0, 4.0 / scale):
                edge_x = max_x + max(2.5 / scale, label_gap * 0.55)
                ey0 = max_y
                ey1 = bottom_hole["cy"]
                parts.append(
                    f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
                    f'stroke-linecap="butt" stroke-linejoin="miter">'
                    f'<line x1="{edge_x:.3f}" y1="{ey0:.3f}" x2="{edge_x:.3f}" y2="{ey1:.3f}" />'
                    f'<line x1="{bottom_hole["cx"]:.3f}" y1="{ey0:.3f}" x2="{edge_x:.3f}" y2="{ey0:.3f}" />'
                    f'<line x1="{bottom_hole["cx"]:.3f}" y1="{ey1:.3f}" x2="{edge_x:.3f}" y2="{ey1:.3f}" />'
                    "</g>"
                )
                collision_boxes.append(_line_collision_box(edge_x, ey0, edge_x, ey1, line_pad))
                collision_boxes.append(_line_collision_box(bottom_hole["cx"], ey0, edge_x, ey0, line_pad))
                collision_boxes.append(_line_collision_box(bottom_hole["cx"], ey1, edge_x, ey1, line_pad))
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
                    vert_tx = edge_x + (1.5 / scale)
                    vert_ty = (ey0 + ey1) * 0.5
                    parts.append(
                        f'<g fill="rgb(0,0,0)" stroke="none" font-size="{text_size:.3f}" '
                        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
                        f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
                        f'<text x="{vert_tx:.3f}" y="{-vert_ty:.3f}" text-anchor="middle" '
                        f'transform="rotate(90,{vert_tx:.3f},{-vert_ty:.3f})">'
                        f'{vert_text}</text></g>'
                    )
            pitch_text = format_de_number(hole_pitch)
            if pitch_text not in used_dimension_labels:
                used_dimension_labels.add(pitch_text)
                text_x = (lx + rx) * 0.5
                text_y = _reserve_feature_label_position(
                    pitch_text,
                    text_x,
                    y_dim + (2.0 / scale),
                    text_size,
                    "middle",
                    used_label_y,
                    label_gap,
                    min_y,
                    max_y,
                    collision_boxes,
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
    if (not pitch_drawn) and hole_pitch and hole_pitch > 0:
        bbox = feature_payload.get("bbox_mm") or {}
        longest_axis = str(feature_payload.get("longest_axis", ""))
        longest_len = _optional_float(bbox.get(longest_axis)) or _optional_float(feature_payload.get("hole_pitch_mm")) or 1.0
        ratio = max(0.2, min(0.9, hole_pitch / max(longest_len, 1e-6)))
        span = (max_x - min_x) * ratio
        cx = (min_x + max_x) * 0.5
        lx = cx - span * 0.5
        rx = cx + span * 0.5
        y_dim = min_y + (7.0 / scale)
        y_dim = max(min_y + (2.5 / scale), min(max_y - (2.5 / scale), y_dim))
        parts.append(
            f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" '
            f'stroke-linecap="butt" stroke-linejoin="miter">'
            f'<line x1="{lx:.3f}" y1="{y_dim:.3f}" x2="{rx:.3f}" y2="{y_dim:.3f}" />'
            "</g>"
        )
        collision_boxes.append(_line_collision_box(lx, y_dim, rx, y_dim, line_pad))
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
        pitch_text = f"LOCHABSTAND {format_de_number(hole_pitch)}"
        if pitch_text not in used_dimension_labels:
            used_dimension_labels.add(pitch_text)
            text_x = (lx + rx) * 0.5
            text_y = _reserve_feature_label_position(
                pitch_text,
                text_x,
                y_dim + (2.0 / scale),
                text_size,
                "middle",
                used_label_y,
                label_gap,
                min_y,
                max_y,
                collision_boxes,
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

    if edge_location_targets:
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
        if horizontal_candidate:
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
        if vertical_candidate:
            _draw_edge_location_dimension("V", vertical_candidate[0], vertical_candidate[1])

    # Diameter annotation for dominant hole size.
    hole_dia = _optional_float(feature_payload.get("hole_diameter_mm"))
    if (hole_dia is None or hole_dia <= 0) and main_radius > 0:
        hole_dia = max(0.0, main_radius * 2.0)
    if hole_dia and hole_dia > 0:
        if main_holes:
            target = sorted(main_holes, key=lambda item: (item["cx"], item["cy"]))[0]
        else:
            target = {
                "cx": min_x + (max_x - min_x) * 0.2,
                "cy": min_y + (max_y - min_y) * 0.25,
                "r": max(0.8, 2.0 / scale),
            }
        sx = target["cx"] + target["r"] * 0.7
        sy = target["cy"] - target["r"] * 0.7
        kx = sx + (8.0 / scale)
        ky = sy - (6.0 / scale)
        ex = min(max_x - (2.0 / scale), kx + (14.0 / scale))
        ey = ky
        parts.append(
            f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" stroke-linecap="butt">'
            f'<line x1="{sx:.3f}" y1="{sy:.3f}" x2="{kx:.3f}" y2="{ky:.3f}" />'
            f'<line x1="{kx:.3f}" y1="{ky:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" />'
            "</g>"
        )
        collision_boxes.append(_line_collision_box(sx, sy, kx, ky, line_pad))
        collision_boxes.append(_line_collision_box(kx, ky, ex, ey, line_pad))
        dia_text = f"\u00D8 {format_de_number(hole_dia)}"
        text_x = ex + (1.0 / scale)
        text_y = _reserve_feature_label_position(
            dia_text,
            text_x,
            ey - (1.2 / scale),
            text_size,
            "start",
            used_label_y,
            label_gap,
            min_y,
            max_y,
            collision_boxes,
        )
        if dia_text not in used_dimension_labels:
            used_dimension_labels.add(dia_text)
            parts.append(
                _feature_text_svg(
                    dia_text,
                    text_x,
                    text_y,
                    text_size,
                    anchor="start",
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
    if thread_label:
        if thread_circle is None:
            thread_circle = {
                "cx": min_x + (max_x - min_x) * 0.55,
                "cy": min_y + (max_y - min_y) * 0.45,
                "r": max(0.8, 2.0 / scale),
            }
        sx = thread_circle["cx"] + thread_circle["r"] * 0.7
        sy = thread_circle["cy"] + thread_circle["r"] * 0.7
        kx = sx + (8.0 / scale)
        ky = sy + (5.0 / scale)
        ex = min(max_x - (2.0 / scale), kx + (12.0 / scale))
        ey = ky
        parts.append(
            f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" stroke-linecap="butt">'
            f'<line x1="{sx:.3f}" y1="{sy:.3f}" x2="{kx:.3f}" y2="{ky:.3f}" />'
            f'<line x1="{kx:.3f}" y1="{ky:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" />'
            "</g>"
        )
        collision_boxes.append(_line_collision_box(sx, sy, kx, ky, line_pad))
        collision_boxes.append(_line_collision_box(kx, ky, ex, ey, line_pad))
        thread_text = f"{thread_label} GEWINDE"
        text_x = ex + (1.0 / scale)
        text_y = _reserve_feature_label_position(
            thread_text,
            text_x,
            ey - (1.1 / scale),
            text_size,
            "start",
            used_label_y,
            label_gap,
            min_y,
            max_y,
            collision_boxes,
        )
        if thread_text not in used_dimension_labels:
            used_dimension_labels.add(thread_text)
            parts.append(
                _feature_text_svg(
                    thread_text,
                    text_x,
                    text_y,
                    text_size,
                    anchor="start",
                )
            )
    # Bend radius annotation (sheet metal only)
    bend_r = _optional_float(feature_payload.get("bend_radius_mm"))
    if bend_r and bend_r > 0:
        bend_text = f"R{format_de_number(bend_r)}"
        if bend_text not in used_dimension_labels:
            used_dimension_labels.add(bend_text)
            # Place near a bend area — approximate as the center-left of the view
            bx = min_x + (max_x - min_x) * 0.15
            by = min_y + (max_y - min_y) * 0.5
            # Leader line from bend region to text
            kx = bx - (8.0 / scale)
            ky = by - (6.0 / scale)
            ex = min_x - (2.0 / scale)
            ey = ky
            parts.append(
                f'<g fill="none" stroke="rgb(0, 0, 0)" stroke-width="{dim_stroke:.4f}" stroke-linecap="butt">'
                f'<line x1="{bx:.3f}" y1="{by:.3f}" x2="{kx:.3f}" y2="{ky:.3f}" />'
                f'<line x1="{kx:.3f}" y1="{ky:.3f}" x2="{ex:.3f}" y2="{ey:.3f}" />'
                "</g>"
            )
            collision_boxes.append(_line_collision_box(bx, by, kx, ky, line_pad))
            collision_boxes.append(_line_collision_box(kx, ky, ex, ey, line_pad))
            text_x = ex - (1.0 / scale)
            text_y = _reserve_feature_label_position(
                bend_text,
                text_x,
                ey - (1.2 / scale),
                text_size,
                "end",
                used_label_y,
                label_gap,
                min_y,
                max_y,
                collision_boxes,
            )
            parts.append(
                _feature_text_svg(
                    bend_text,
                    text_x,
                    text_y,
                    text_size,
                    anchor="end",
                )
            )

    return "".join(parts)


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
        "font-size: 3.2px; font-style: normal; font-weight: normal;"
    )
    annotation_chunks = []
    for index, line in enumerate(annotation_lines[:10]):
        y = annotation_y - (index * 3.4)
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
        "font-size: 2.6px; font-style: normal; font-weight: normal;"
    )
    title_info_style_value = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 3.0px; font-style: normal; font-weight: normal;"
    )
    is_first_angle = "1." in projection_value or "first" in projection_value.lower()
    info_rows = [
        ("MATERIAL", material_value),
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
    return svg.replace("</svg>", f"{views_svg}\n{annotation}\n{title_info}\n{projection_symbol}\n</svg>")


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
        "font-size: 3.0px; font-style: normal; font-weight: normal;"
    )
    dim_style = (
        "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
        "font-size: 2.6px; font-style: normal; font-weight: normal;"
    )
    title_x = flat_cx - area_w / 2
    title_y = flat_cy - area_h / 2 - 4.0

    flat_pattern = (feature_payload or {}).get("flat_pattern")

    # ---------- Priority 1: Real SheetMetal Unfold (SVG contour from addon) ----------
    if unfold_result and unfold_result.get("ok") and unfold_result.get("outline_svg"):
        fl = float(unfold_result["flat_length_mm"])
        fw = float(unfold_result["flat_width_mm"])
        k_used = float(((feature_payload or {}).get("flat_pattern") or {}).get("k_factor_used") or 0.40)

        outline_svg = unfold_result["outline_svg"]

        # Use extract_svg_bounds() to get the ACTUAL bounds of the outline SVG.
        # The outline is projected by TechDraw in model coordinates; without
        # normalization the origin may be at any offset and Y may be flipped.
        # extract_svg_bounds handles all SVG element types and gives (minX,maxX,minY,maxY).
        ob = extract_svg_bounds(outline_svg)
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
        part_bounds = extract_svg_bounds(outline_only_svg)
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

        # Actual outline corner positions in drawing coordinates.
        # Use the outline-only SVG bounds CENTER for accurate positioning (handles
        # asymmetric bend line overhangs), but use fl/fw for dimensions (the SVG bounds
        # may be slightly larger than the true part due to TechDraw projection artifacts).
        pb_cx_svg = (pb_x1 + pb_x2) / 2
        pb_cy_svg = (pb_y1 + pb_y2) / 2
        outline_cx = tx + pb_cx_svg * draw_scale
        outline_cy = ty + pb_cy_svg * draw_scale

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

        outline_w = dim_h_mm * draw_scale
        outline_h = dim_v_mm * draw_scale
        outline_x1 = outline_cx - outline_w / 2
        outline_y1 = outline_cy - outline_h / 2
        outline_x2 = outline_cx + outline_w / 2
        outline_y2 = outline_cy + outline_h / 2

        if os.environ.get("DRAWFORM_DEBUG_DIR"):
            print(f"[drawform] ABWICKLUNG: fl={fl:.1f} fw={fw:.1f} ob=({ob_x1:.1f},{ob_y1:.1f},{ob_w:.1f},{ob_h:.1f}) part=({pb_x1:.1f},{pb_y1:.1f},{pb_x2:.1f},{pb_y2:.1f}) outline=({outline_x1:.1f},{outline_y1:.1f},{outline_w:.1f},{outline_h:.1f})")

        parts: list[str] = []

        # Render the real outline SVG (bend lines are already embedded in outline_svg
        # as styled <g class="bend-lines"> elements from step_unfold.py)
        parts.append(
            f'<g transform="translate({tx:.3f},{ty:.3f}) scale({draw_scale:.6f})" '
            f'fill="none" stroke="rgb(0,0,0)" stroke-width="{0.35 / draw_scale:.4f}">'
            f'{outline_svg}'
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

        # Bend annotations: deduplicated legend block near flat pattern
        bend_lines_data = unfold_result.get("bend_lines") or []
        bend_segments = (flat_pattern or {}).get("bend_segments") or []
        bend_ann_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 2.5px; font-style: normal; font-weight: normal; fill: #000;"
        )
        # Collect unique annotations with counts
        bend_ann_seen = {}  # ann_text -> count
        for bi, bl in enumerate(bend_lines_data):
            if bi < len(bend_segments):
                bseg = bend_segments[bi]
                b_dir = bseg.get("direction", "OBEN")
                b_angle = format_de_number(bseg.get("angle_deg", 90), decimals=0)
                b_radius = format_de_number(bseg.get("radius_mm", 0))
                ann_text = f"NACH {b_dir} {b_angle}\u00B0 R {b_radius}"
            else:
                ann_text = f"Biegung {bi + 1}"
            bend_ann_seen[ann_text] = bend_ann_seen.get(ann_text, 0) + 1
        # Render legend block below the flat pattern outline
        if bend_ann_seen:
            legend_x = outline_x1  # left-aligned with flat pattern
            legend_y = outline_y2 + 14.0  # below outline + dim line clearance (dim_y_h at +8)
            for line_i, (ann_text, count) in enumerate(bend_ann_seen.items()):
                ly = legend_y + line_i * 3.5
                label = f"{count}\u00D7 {ann_text}" if count > 1 else ann_text
                parts.append(
                    f'<text x="{legend_x:.3f}" y="{ly:.3f}" style="{bend_ann_style}" '
                    f'text-anchor="start">{escape(label)}</text>'
                )

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

        # Boundaries: stay within the available drawing area
        max_x_bound = margin + avail_draw_w - 2.0   # right edge of drawing
        max_y_bound = draw_bottom - 2.0              # bottom edge of drawing

        # Flange dimension lines along X axis (below outline, stacked below overall dim)
        if bend_positions_x:
            bend_positions_x.sort(key=lambda item: item[0])
            # Build segment edges: outline_x1, bend1, bend2, ..., outline_x2
            seg_edges_x = [outline_x1] + [bp[0] for bp in bend_positions_x] + [outline_x2]
            flange_dim_y = min(outline_y2 + 18.0, max_y_bound - 4.0)
            flange_ext_y0 = outline_y2
            flange_dim_style = (
                "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
                "font-size: 2.2px; font-style: normal; font-weight: normal; fill: #000;"
            )
            for si in range(len(seg_edges_x) - 1):
                sx1 = seg_edges_x[si]
                sx2 = seg_edges_x[si + 1]
                seg_w_mm = abs(sx2 - sx1) / draw_scale
                if seg_w_mm < 1.0:
                    continue
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

        # Flange dimension lines along Y axis (right of outline, stacked right of overall dim)
        if bend_positions_y:
            bend_positions_y.sort(key=lambda item: item[0])
            seg_edges_y = [outline_y1] + [bp[0] for bp in bend_positions_y] + [outline_y2]
            flange_dim_x = min(outline_x2 + 18.0, max_x_bound - 4.0)
            flange_ext_x0 = outline_x2
            flange_dim_style = (
                "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
                "font-size: 2.2px; font-style: normal; font-weight: normal; fill: #000;"
            )
            for si in range(len(seg_edges_y) - 1):
                sy1 = seg_edges_y[si]
                sy2 = seg_edges_y[si + 1]
                seg_h_mm = abs(sy2 - sy1) / draw_scale
                if seg_h_mm < 1.0:
                    continue
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
        dim_y_h = outline_y2 + 8.0
        ext_y0 = outline_y2
        parts.append(f'<line x1="{outline_x1:.3f}" y1="{ext_y0:.3f}" x2="{outline_x1:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{outline_x2:.3f}" y1="{ext_y0:.3f}" x2="{outline_x2:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{outline_x1:.3f}" y1="{dim_y_h:.3f}" x2="{outline_x2:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(_arrow(outline_x1, dim_y_h, "left"))
        parts.append(_arrow(outline_x2, dim_y_h, "right"))
        parts.append(f'<text x="{outline_cx:.3f}" y="{dim_y_h - 1.0:.3f}" style="{dim_style}" text-anchor="middle">{format_de_number(dim_h_mm)}</text>')

        # Vertical dimension (flat width) to the right of outline
        dim_x_v = outline_x2 + 8.0
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
            f'<text x="{title_x:.1f}" y="{title_y:.1f}" style="{title_bold_style}">ABWICKLUNG</text>',
            f'<text x="{title_x:.1f}" y="{title_y + 5.0:.1f}" style="{subtitle_style}">{escape(k_subtitle)}</text>',
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
            "model_fl_mm": round(fl, 2),
            "model_fw_mm": round(fw, 2),
            "bend_count": bend_count,
            "bend_annotations": len(bend_lines_data),
            "drawing_area": [round(margin, 2), round(margin, 2),
                             round(margin + avail_draw_w, 2), round(draw_bottom, 2)],
        }

        # Flange dimension metadata
        flange_dims = []
        if bend_positions_x:
            seg_edges = [outline_x1] + [bp[0] for bp in sorted(bend_positions_x, key=lambda item: item[0])] + [outline_x2]
            for si in range(len(seg_edges) - 1):
                seg_w_mm = abs(seg_edges[si + 1] - seg_edges[si]) / draw_scale
                if seg_w_mm >= 1.0:
                    flange_dims.append({"axis": "x", "start": round(seg_edges[si], 2),
                                        "end": round(seg_edges[si + 1], 2),
                                        "label_mm": round(seg_w_mm, 2)})
        if bend_positions_y:
            seg_edges = [outline_y1] + [bp[0] for bp in sorted(bend_positions_y, key=lambda item: item[0])] + [outline_y2]
            for si in range(len(seg_edges) - 1):
                seg_h_mm = abs(seg_edges[si + 1] - seg_edges[si]) / draw_scale
                if seg_h_mm >= 1.0:
                    flange_dims.append({"axis": "y", "start": round(seg_edges[si], 2),
                                        "end": round(seg_edges[si + 1], 2),
                                        "label_mm": round(seg_h_mm, 2)})
        abwicklung_meta["flange_dims"] = flange_dims

        return "\n".join(parts) + "\n" + "\n".join(note_parts), abwicklung_meta

    # ---------- Priority 2: Mathematical fallback (simple geometry only) ----------
    if (flat_pattern and flat_pattern.get("flat_length_mm") and flat_pattern.get("flat_width_mm")
            and not flat_pattern.get("complex_geometry")):
        fl = float(flat_pattern["flat_length_mm"])
        fw = float(flat_pattern["flat_width_mm"])
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
        bend_ann_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 2.5px; font-style: normal; font-weight: normal; fill: #000;"
        )

        def _add_bend_line_and_annotation(bend_x, seg):
            """Draw dashed bend line and rotated annotation text at bend_x."""
            if rect_x < bend_x < rect_x + rect_w:
                parts.append(
                    f'<line x1="{bend_x:.3f}" y1="{rect_y:.3f}" '
                    f'x2="{bend_x:.3f}" y2="{rect_y + rect_h:.3f}" '
                    f'stroke="rgb(40,40,160)" stroke-width="0.18" '
                    f'stroke-dasharray="2.5,1.0" />'
                )
            direction = seg.get("direction", "OBEN")
            r_str = format_de_number(seg.get("radius_mm") or 0)
            angle_str = format_de_number(seg.get("angle_deg") or 90, decimals=0)
            ann_text = f"NACH {direction} {angle_str}\u00B0 R {r_str}"
            # Place rotated text above the bend line, offset 3mm to the left
            ann_x = bend_x - 3.0
            ann_y = rect_y + rect_h / 2
            parts.append(
                f'<text x="{ann_x:.3f}" y="{ann_y:.3f}" style="{bend_ann_style}" '
                f'text-anchor="middle" '
                f'transform="rotate(-90,{ann_x:.3f},{ann_y:.3f})">'
                f'{escape(ann_text)}</text>'
            )

        if flat_extents and len(flat_extents) >= len(segments):
            # We have per-flange extent data: accumulate positions using actual extents.
            # flat_extents are sorted largest-first; treat first as the base flange.
            # For n bends: flanges = [e0, e1, ..., en] with bends between them.
            x_pos_mm = flat_extents[0] if flat_extents else 0.0
            for i, seg in enumerate(segments):
                allowance = float(seg.get("allowance_mm") or 0)
                bend_x = rect_x + x_pos_mm * draw_scale
                _add_bend_line_and_annotation(bend_x, seg)
                next_extent = flat_extents[i + 1] if i + 1 < len(flat_extents) else 0.0
                x_pos_mm += allowance + next_extent
        else:
            # Fallback: distribute segment lengths evenly
            seg_len_each = total_segs_mm / max(len(segments) + 1, 2) if segments else 0
            x_pos_mm = seg_len_each
            for seg in segments:
                allowance = float(seg.get("allowance_mm") or 0)
                bend_x = rect_x + x_pos_mm * draw_scale
                _add_bend_line_and_annotation(bend_x, seg)
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
            f'<text x="{title_x:.1f}" y="{title_y:.1f}" style="{title_bold_style}">ABWICKLUNG</text>',
            f'<text x="{title_x:.1f}" y="{title_y + 5.0:.1f}" style="{subtitle_style}">{escape(k_subtitle)}</text>',
        ]
        abwicklung_meta = {
            "source": "mathematical_fallback",
            "outline_bounds": [round(rect_x, 2), round(rect_y, 2),
                               round(rect_x + rect_w, 2), round(rect_y + rect_h, 2)],
            "dim_h_label_mm": round(fl, 2),
            "dim_v_label_mm": round(fw, 2),
            "model_fl_mm": round(fl, 2),
            "model_fw_mm": round(fw, 2),
            "bend_count": bend_count,
            "bend_annotations": bend_count,
            "flange_dims": [],
        }
        return "\n".join(parts) + "\n" + "\n".join(note_parts), abwicklung_meta

    else:
        # Fallback: show projected top/front view with unavailability note
        top_view = next((item for item in view_data if item.get("name") == "Top"), None)
        front_view = next((item for item in view_data if item.get("name") == "Front"), None)
        candidate = top_view or front_view
        if candidate:
            scale = compute_fit_scale(candidate.get("bounds_for_scale", candidate["svg_bounds"]), area_w, area_h, padding=0.84)
            line_profile = iso128_line_profile(scale)
            stroke_width = float(line_profile.get("visible", compute_stroke_width(scale)))
            group = build_view_group(
                candidate["svg"],
                candidate["svg_bounds"],
                candidate["proj_bounds"],
                flat_cx,
                flat_cy,
                scale,
                rotation_deg=candidate.get("rotation_deg", 0),
                stroke_width=stroke_width,
                line_profile=line_profile,
                dimension_svg="",
                view_name="Abwicklung",
                show_coordinate_system=False,
            )
        else:
            group = ""

        title_bold_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 4.0px; font-style: normal; font-weight: bold; fill: #000;"
        )
        subtitle_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 2.8px; font-style: normal; font-weight: normal; fill: #555;"
        )
        note_item_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 2.8px; font-style: normal; font-weight: normal; fill: #000;"
        )
        fb_note_parts = [
            f'<text x="{title_x:.1f}" y="{title_y:.1f}" style="{title_bold_style}">ABWICKLUNG</text>',
            f'<text x="{title_x:.1f}" y="{title_y + 5.0:.1f}" style="{subtitle_style}">Kontur: manuelle Entfaltung</text>',
        ]
        if flat_pattern:
            k_fb = flat_pattern.get("k_factor_used")
            t_fb = _optional_float(flat_pattern.get("thickness_mm"))
            bend_count = len(flat_pattern.get("bend_segments") or [])
            extra_lines = []
            if t_fb:
                extra_lines.append(f"Blechst\u00e4rke = {format_de_number(t_fb)}")
            if k_fb is not None:
                extra_lines.append(f"K-Faktor = {format_de_number(k_fb, 2)}")
            if bend_count:
                extra_lines.append(f"Biegungen: {bend_count}\u00d7")
            for i, line in enumerate(extra_lines[:3]):
                fb_note_parts.append(
                    f'<text x="{title_x:.1f}" y="{title_y + 9.5 + i * 3.5:.1f}" '
                    f'style="{note_item_style}">{escape(line)}</text>'
                )
        return f"{group}\n" + "\n".join(fb_note_parts), {"source": "fallback_projection"}


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
    issues = []
    text_entries = _collect_svg_text_entries(page_svg)
    dim_texts = []
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
        "NACH ",       # Bend annotations ("NACH OBEN 90° R 4,2") — duplicates are intentional
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

    overall_tokens = {format_de_number(dim_x), format_de_number(dim_y), format_de_number(dim_z)}
    present_overall = {token for token in overall_tokens if any(token in item["text"] for item in dim_texts)}
    if len(present_overall) < 2:
        issues.append("Fehlende Aussenmasse: weniger als zwei Gesamtmasswerte gefunden.")

    feature_block = report.get("features", {})
    hole_count = int(_optional_float(feature_block.get("hole_count")) or 0)
    if hole_count > 0:
        has_diameter_callout = any(item["text"].startswith("\u00D8") for item in dim_texts)
        if not has_diameter_callout:
            issues.append("Fehlende Lochdurchmesserangabe (\u00D8).")
        centerline_total = int(_optional_float((report.get("quality", {}) or {}).get("centerline_total")) or 0)
        if centerline_total <= 0:
            issues.append("Keine Mittellinien bei vorhandenen Bohrungen erkannt.")

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

    # Heuristic overlap check for dimension labels.
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
        issues.append("Moegliche Ueberlagerung von Masszahlen erkannt.")

    status = "OK" if not issues else "WARNUNG"
    dt = dim_tracking or {}
    return {
        "status": status,
        "issues": issues,
        "dim_metrics": {
            "dim_text_count": int(dt.get("dim_text_count", 0)),
            "step_dim_count": int(dt.get("step_dim_count", 0)),
            "feature_dim_present": bool(dt.get("feature_dim_present", False)),
            "labels_in_bounds": bool(dt.get("labels_in_bounds", True)),
        },
    }


def format_scale(scale_value):
    scale_candidates = [
        (20, "20:1"),
        (10, "10:1"),
        (5, "5:1"),
        (2, "2:1"),
        (1, "1:1"),
        (0.5, "1:2"),
        (0.2, "1:5"),
        (0.1, "1:10"),
        (0.05, "1:20"),
        (0.02, "1:50"),
        (0.01, "1:100"),
    ]
    closest = min(scale_candidates, key=lambda item: abs(item[0] - scale_value))
    return closest[1]


def main():
    if len(sys.argv) < 3:
        raise RuntimeError("Usage: step_to_pdf.py <input.step> <output.pdf>")

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    meta_path = os.getenv("DRAWFORM_META")
    raw_meta = read_metadata(meta_path)
    raw_meta.setdefault("input_path", input_path)  # used for part name extraction
    meta = normalize_export_metadata(raw_meta)

    log(f"FreeCAD version: {App.Version()[0]}.{App.Version()[1]}.{App.Version()[2]}")
    doc = App.newDocument("DrawformDrawing")
    shape = load_shape(doc, input_path)
    points = collect_points(shape)

    bb = shape.BoundBox
    dim_x = bb.XLength
    dim_y = bb.YLength
    dim_z = bb.ZLength
    log(f"Bounds mm: X={dim_x:.2f} Y={dim_y:.2f} Z={dim_z:.2f}")

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

    requested_sheet = str(os.getenv("DRAWFORM_SHEET_REQUESTED") or resolve_requested_sheet(meta)).strip()
    if requested_sheet.upper() in {"A2", "A3"}:
        requested_sheet = requested_sheet.upper()
    else:
        requested_sheet = "auto"
    layout_profile = select_layout_profile(input_path, feature_payload, dim_x, dim_y, dim_z)
    flat_pattern_mode = detect_flat_pattern_mode(layout_profile)

    # ---------- Run SheetMetal Unfold (subprocess) for sheet_metal parts ----------
    unfold_result = None
    if layout_profile == "sheet_metal":
        unfold_result = _run_unfold_subprocess(input_path, feature_payload)
        if unfold_result and unfold_result.get("ok"):
            log(f"SheetMetal unfold: {unfold_result['flat_length_mm']}x"
                f"{unfold_result['flat_width_mm']}mm, {unfold_result['bend_count']} bends")
            flat_pattern_mode = "sheetmetal_module"
        else:
            err = (unfold_result or {}).get("error", "unknown")
            log(f"SheetMetal unfold failed: {err} — using fallback")

    # ---------- Sheet metal subtype: biegeteil vs laserteil ----------
    sheet_metal_subtype = None
    if layout_profile == "sheet_metal":
        if unfold_result and unfold_result.get("ok"):
            bend_count = unfold_result.get("bend_count", 0)
            sheet_metal_subtype = "biegeteil" if bend_count > 0 else "laserteil"
        else:
            sheet_metal_subtype = "biegeteil"  # Safer default — assume bends
        log(f"Sheet metal subtype: {sheet_metal_subtype} "
            f"({unfold_result.get('bend_count', '?') if unfold_result else '?'} bends)")

    if isinstance(raw_plan, dict) and raw_plan.get("views"):
        dim_plan = raw_plan
        dim_plan_source = "meta"
        log(f"Dimension plan loaded: part_type={dim_plan.get('part_type')}, "
            f"views={len(dim_plan.get('views', []))}")
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

    view_dirs = None if safe_mode else compute_view_directions(shape, points=points)
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

    ortho_padding = 0.85 if layout_profile == "milling" else 0.82
    iso_padding = 0.90 if layout_profile == "milling" else 0.88
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
            bounds_for_scale, scale_fit = compute_dimension_padded_bounds(
                bounds_for_layout,
                slot["w"],
                slot["h"],
                padding=ortho_padding,
                iterations=2,
                show_horizontal=fit_show_horizontal,
                show_vertical=fit_show_vertical,
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
                "slot": slot,
                "enabled": enabled,
                "proj_swap": proj_swap,
            }
        )
        log(
            f"View {name} svg: {svg_w:.2f} x {svg_h:.2f}, proj: {proj_w:.2f} x {proj_h:.2f}, swap={proj_swap}, rotate={rotation_deg}"
        )

    ortho_scale = min(
        item["scale_fit"]
        for item in view_data
        if item["name"] in ("Top", "Front", "Left") and item.get("enabled", True)
    )
    log(f"ALIGN ortho_scale={ortho_scale:.4f}")
    iso_item = next((item for item in view_data if item["name"] == "Iso"), None)
    if iso_item is not None:
        iso_bounds = iso_item["layout_bounds"]
        iso_slot = iso_item.get("slot") or view_slots["Iso"]
        iso_scale = compute_scale_for_area(iso_bounds, iso_slot["w"], iso_slot["h"], padding=iso_padding)
        if layout_variant == "sheet_bent":
            iso_max_ratio = 0.65
        elif layout_variant == "flat_round_dominant":
            iso_max_ratio = 0.45
        elif layout_variant == "flat_dominant":
            iso_max_ratio = 0.55
        else:
            iso_max_ratio = 0.75
        iso_scale = min(iso_scale, ortho_scale * iso_max_ratio)
        iso_item["cx"] = iso_slot["cx"]
        iso_item["cy"] = iso_slot["cy"]
        iso_item["scale"] = iso_scale
    if not meta.get("scale") or str(meta.get("scale")).lower() == "auto":
        meta["scale"] = format_scale(ortho_scale)

    front_item = next((item for item in view_data if item["name"] == "Front"), None)
    top_item = next((item for item in view_data if item["name"] == "Top"), None)
    left_item = next((item for item in view_data if item["name"] == "Left"), None)
    
    # Simple alignment based on scaled dimensions (like CAD software does)
    # After rotation, width and height may swap
    def get_paper_dimensions(item, scale, include_fit_padding=False):
        """Get width and height in paper space after rotation.
        include_fit_padding=True includes dimension margin for bounds/clipping checks."""
        if include_fit_padding:
            return item["fit_w"] * scale, item["fit_h"] * scale
        return item["geom_w"] * scale, item["geom_h"] * scale
    
    # Calculate Front's left edge position
    if front_item:
        front_paper_w, front_paper_h = get_paper_dimensions(front_item, ortho_scale)
        front_left = front_item["cx"] - front_paper_w / 2
        front_top = front_item["cy"] - front_paper_h / 2
        log(f"ALIGN Front: cx={front_item['cx']:.2f}, paper_w={front_paper_w:.2f}, left_edge={front_left:.2f}")
    
    # Align Top view: move cx so its left edge matches Front's left edge
    if front_item and top_item:
        top_paper_w, top_paper_h = get_paper_dimensions(top_item, ortho_scale)
        # Top's left edge = top_cx - top_paper_w / 2
        # We want: top_left = front_left
        # So: top_cx - top_paper_w / 2 = front_left
        # top_cx = front_left + top_paper_w / 2
        new_top_cx = front_left + top_paper_w / 2
        log(f"ALIGN Top: paper_w={top_paper_w:.2f}, old_cx={top_item['cx']:.2f}, new_cx={new_top_cx:.2f}")
        top_item["cx"] = new_top_cx
    
    # Align Left view: move cy so its top edge matches Front's top edge  
    if front_item and left_item:
        left_paper_w, left_paper_h = get_paper_dimensions(left_item, ortho_scale)
        # Left's top edge = left_cy - left_paper_h / 2
        # We want: left_top = front_top
        # So: left_cy - left_paper_h / 2 = front_top
        # left_cy = front_top + left_paper_h / 2
        new_left_cy = front_top + left_paper_h / 2
        log(f"ALIGN Left: paper_h={left_paper_h:.2f}, old_cy={left_item['cy']:.2f}, new_cy={new_left_cy:.2f}")
        left_item["cy"] = new_left_cy

    # === BOUNDS CHECKING: Ensure all views fit within drawing area ===
    # Drawing area limits (excluding margin and title block)
    draw_left = margin
    draw_top = margin
    draw_right = sheet_w - margin
    draw_bottom = sheet_h - margin - title_block_h
    
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
                log(f"BOUNDS: Reducing scale by factor {scale_reduction:.3f}")
                # This is a simplified approach - in production would need to recalculate positions
                # For now, just log the warning
                log("BOUNDS: Scale reduction not yet implemented - views may be clipped")

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
            "flat_pattern_mode": flat_pattern_mode,
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
            },
            "features": {
                "ok": bool(feature_payload.get("ok")),
                "hole_count": feature_payload.get("hole_count"),
                "hole_diameter_mm": feature_payload.get("hole_diameter_mm"),
                "hole_pitch_mm": feature_payload.get("hole_pitch_mm"),
                "bend_radius_mm": feature_payload.get("bend_radius_mm"),
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
        
        for item in view_data:
            paper_w, paper_h = get_paper_dimensions(item, ortho_scale if item["name"] != "Iso" else item.get("scale", ortho_scale))
            left_edge = item["cx"] - paper_w / 2
            top_edge = item["cy"] - paper_h / 2
            
            report["views"][item["name"]] = {
                "enabled": bool(item.get("enabled", True)),
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
                "centerline_count": int(item.get("centerline_count", 0)),
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
                report["alignment"]["front_top_left_match"] = abs(front_left - top_left) < 0.5
        
        if "Front" in report["views"] and "Left" in report["views"]:
            front_top = report["views"]["Front"]["top_edge"]
            left_top = report["views"]["Left"]["top_edge"]
            report["alignment"]["front_top_edge"] = front_top
            report["alignment"]["left_top_edge"] = left_top
            if not report["views"]["Left"].get("enabled", True):
                report["alignment"]["front_left_top_match"] = True
            else:
                report["alignment"]["front_left_top_match"] = abs(front_top - left_top) < 0.5

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
        
        return report
    
    view_groups = []
    dim_tracking = {
        "dim_text_count": 0,
        "step_dim_count": 0,
        "feature_dim_present": False,
        "labels_in_bounds": True,
    }
    feature_view_name = None
    feature_view_circle_count = 0
    if isinstance(feature_payload, dict) and feature_payload.get("ok") is True:
        for candidate in view_data:
            if candidate["name"] == "Iso" or not candidate.get("enabled", True):
                continue
            circle_count = count_svg_circles(candidate["svg"])
            if circle_count > feature_view_circle_count:
                feature_view_circle_count = circle_count
                feature_view_name = candidate["name"]
        if feature_view_name:
            log(f"Feature dimension view: {feature_view_name} (circles={feature_view_circle_count})")

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
        
        if name == "Iso":
            scale = item.get("scale", ortho_scale * 0.75)
            dimension_svg = ""
            centerline_count = 0
            line_profile = iso128_line_profile(scale)
        else:
            scale = ortho_scale
            line_profile = iso128_line_profile(scale)
            stroke_width = float(line_profile.get("visible", compute_stroke_width(scale)))
            show_horizontal, show_vertical = resolve_overall_dimension_axes(name, dim_plan=dim_plan)
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
                )
                dim_tracking["dim_text_count"] += (1 if show_horizontal else 0) + (1 if show_vertical else 0)
            else:
                dim_tracking["dim_text_count"] += 1
            centerline_svg, centerline_count = build_centerline_svg(
                item["svg"],
                scale,
                stroke_width,
                limit=30,
                line_profile=line_profile,
            )
            if centerline_svg:
                dimension_svg = f"{dimension_svg}{centerline_svg}"
            # Feature dimensions: plan-aware view selection
            _show_features = view_requests_feature_dimensions(name, dim_plan=dim_plan) if dim_plan else (feature_view_name == name)

            if _show_features:
                feature_dimension_svg = build_feature_dimension_svg(
                    item["svg"],
                    svg_bounds,
                    feature_payload,
                    scale,
                    stroke_width,
                    line_profile=line_profile,
                )
                if feature_dimension_svg:
                    dimension_svg = f"{dimension_svg}{feature_dimension_svg}"
                    dim_tracking["dim_text_count"] += feature_dimension_svg.count("<text")
                    dim_tracking["feature_dim_present"] = True
            # Step dimensions disabled: produces irrelevant edge-position values
            # that don't correspond to intentional design dimensions.
            # TODO: Replace with intelligent feature-based dimensioning.
            # if name == "Front" and show_horizontal and show_vertical:
            #     step_dim_svg = build_step_dimensions(
            #         item["svg"],
            #         svg_bounds,
            #         scale,
            #         stroke_width,
            #         line_profile=line_profile,
            #         label_width=label_w,
            #         label_height=label_h,
            #         max_steps=5,
            #     )
            #     if step_dim_svg:
            #         dimension_svg = f"{dimension_svg}{step_dim_svg}"
            #         dim_tracking["step_dim_count"] += step_dim_svg.count("<text")
        item["centerline_count"] = int(centerline_count)
        item["line_profile"] = dict(line_profile or {})
        stroke_width = float(line_profile.get("visible", compute_stroke_width(scale)))
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
    )
    if flat_pattern_overlay:
        view_groups.append(flat_pattern_overlay)

    report = build_report()
    if dim_plan:
        report["dimension_plan"] = dim_plan
    if abwicklung_meta:
        report["abwicklung"] = abwicklung_meta
    if (
        should_promote_to_a2(report, dim_x, dim_y, dim_z, requested_sheet=requested_sheet)
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
        log(f"Pre-export quality: {pre_export_check.get('status')} -> {pre_export_check.get('issues')}")
    report["quality"]["line_hierarchy"] = {
        "visible_vs_dimension": "thick_vs_thin",
        "hidden_dash": True,
        "centerline_chain": True,
    }
    svg_path = Path(output_path).with_suffix(".svg")
    svg_path.write_text(page_svg, encoding="utf-8")

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
        except Exception as exc:
            log(f"Failed to write debug SVG: {exc}")

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
    except Exception as exc:
        sys.stderr.write(str(exc))
        sys.exit(1)

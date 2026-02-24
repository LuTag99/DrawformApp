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


def read_metadata(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _run_unfold_subprocess(input_path, feature_payload):
    """Run step_unfold.py as a subprocess and return the result dict, or None."""
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
        result = _sp.run(
            [freecad_py, unfold_script, str(input_path), out_json],
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
        if hasattr(obj, "Shape"):
            shape = obj.Shape
            if shape and not shape.isNull():
                shapes.append(shape)
    if not shapes:
        raise RuntimeError("No solid geometry found in STEP file.")
    if len(shapes) == 1:
        return shapes[0]
    return Part.makeCompound(shapes)


def replace_text(svg, key, value):
    pattern = rf'(<text[^>]*id="{re.escape(key)}"[^>]*>)(.*?)(</text>)'
    def replacer(match):
        return f"{match.group(1)}{escape(str(value))}{match.group(3)}"
    return re.sub(pattern, replacer, svg, flags=re.DOTALL)


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
    
    # Extract from circle elements: <circle cx="X" cy="Y" r="R" />
    circles = re.findall(r'<circle[^>]+cx\s*=\s*"([^"]+)"[^>]+cy\s*=\s*"([^"]+)"[^>]+r\s*=\s*"([^"]+)"', svg_group)
    for cx, cy, r in circles:
        cx, cy, r = float(cx), float(cy), float(r)
        # Circle bounds: center ± radius
        coords.append((cx - r, cy - r))
        coords.append((cx + r, cy + r))
    
    # Also check for circles with attributes in different order
    circles2 = re.findall(r'<circle[^>]+>', svg_group)
    for circle in circles2:
        cx_match = re.search(r'cx\s*=\s*"([^"]+)"', circle)
        cy_match = re.search(r'cy\s*=\s*"([^"]+)"', circle)
        r_match = re.search(r'\br\s*=\s*"([^"]+)"', circle)
        if cx_match and cy_match and r_match:
            cx = float(cx_match.group(1))
            cy = float(cy_match.group(1))
            r = float(r_match.group(1))
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
                    coords.append((x - rx, y - ry))
                    coords.append((x + rx, y + ry))
                    coords.append((start_x - rx, start_y - ry))
                    coords.append((start_x + rx, start_y + ry))
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


def dimension_metrics(bounds, scale):
    width, height = bounds_size(bounds)
    max_dim_paper = max(width, height) * scale
    offset_mm = max(1.6, min(max_dim_paper * 0.1, 10.0))
    gap_mm = max(0.5, min(1.5, offset_mm * 0.2))
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

    line_parts = []
    arrow_parts = []
    show_horizontal = bool(show_horizontal)
    show_vertical = bool(show_vertical)
    if show_horizontal:
        line_parts.extend(
            [
                f'<line x1="{min_x:.3f}" y1="{y_dim:.3f}" x2="{max_x:.3f}" y2="{y_dim:.3f}" />',
                f'<line x1="{min_x:.3f}" y1="{max_y + gap:.3f}" x2="{min_x:.3f}" y2="{y_dim + ext_over:.3f}" />',
                f'<line x1="{max_x:.3f}" y1="{max_y + gap:.3f}" x2="{max_x:.3f}" y2="{y_dim + ext_over:.3f}" />',
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
                f'<line x1="{max_x + gap:.3f}" y1="{min_y:.3f}" x2="{x_dim + ext_over:.3f}" y2="{min_y:.3f}" />',
                f'<line x1="{max_x + gap:.3f}" y1="{max_y:.3f}" x2="{x_dim + ext_over:.3f}" y2="{max_y:.3f}" />',
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


def compute_dimension_padded_bounds(base_bounds, cell_w, cell_h, padding=0.85, iterations=2):
    scale = compute_fit_scale(base_bounds, cell_w, cell_h, padding=padding)
    padded_bounds = base_bounds
    for _ in range(max(1, iterations)):
        pad = dimension_metrics(base_bounds, scale)["pad"]
        padded_bounds = expand_bounds(base_bounds, pad)
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
        svg_pos = TechDraw.projectToSVG(shape, third_axis)
        svg_neg = TechDraw.projectToSVG(shape, third_axis.negative())
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
            except:
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

        # Tier 2: Measured wall thickness < 5mm (typical sheet metal range) combined
        # with non-zero flat_ratio (bent parts are not perfectly flat in bbox terms).
        if measured_t is not None and 0.3 <= measured_t <= 5.0:
            flat_ratio = _optional_float(feature_payload.get("flat_ratio"))
            if flat_ratio is not None and flat_ratio < 0.7:
                return "sheet_metal"

        # Tier 3 (FALLBACK): BBox ratio with tighter threshold (was 0.25, now 0.15).
        # Prevents thick milling parts from being misclassified.
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
    for path_data in re.findall(r'd="([^"]+)"', svg_group):
        for arc in _parse_svg_path_arcs(path_data):
            resolved = _resolve_circular_arc_center(arc)
            if not resolved:
                continue
            # Filter out tiny corner rounds; keep near-semi/full arcs used for hole contours.
            if resolved["sweep_abs"] < math.radians(140.0):
                continue
            circles.append(
                {
                    "cx": resolved["cx"],
                    "cy": resolved["cy"],
                    "r": resolved["r"],
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
    return (
        f'<g fill="rgb(0, 0, 0)" stroke="none" font-size="{text_size:.3f}" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
        f'<text x="{x:.3f}" y="{-y:.3f}" text-anchor="{anchor}">{escape(text)}</text>'
        "</g>"
    )


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
    arrow_len = max(0.8, 2.0 / scale)
    arrow_half = max(0.3, 0.8 / scale)
    text_size = max(0.2, 2.2 / scale)
    label_gap = max(1.8, 4.0 / max(scale, 0.05))
    used_label_y = []
    parts = []
    hole_pitch = _optional_float(feature_payload.get("hole_pitch_mm"))
    pitch_drawn = False
    used_dimension_labels = set()

    geom_pad = max(0.8, 1.8 / max(scale, 0.05))
    line_pad = max(0.25, 0.6 / max(scale, 0.05))
    arrow_pad = max(0.25, 0.7 / max(scale, 0.05))
    collision_boxes = [(min_x - geom_pad, max_x + geom_pad, min_y - geom_pad, max_y + geom_pad)]

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
                edge_text = f"ABSTAND {format_de_number(edge_span)}"
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
    thread_label = feature_payload.get("thread_label")
    thread_core = _optional_float(feature_payload.get("thread_core_diameter_mm"))
    if not thread_label and thread_core:
        thread_label = infer_metric_thread_label(thread_core)
    thread_circle = None
    if circles and main_radius > 0:
        thread_candidates = [circle for circle in circles if circle["r"] < main_radius * 0.78]
        if thread_candidates:
            thread_circle = sorted(thread_candidates, key=lambda item: item["r"])[0]
            if not thread_label:
                thread_label = infer_metric_thread_label(thread_circle["r"] * 2.0)
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
    info_rows = [
        ("MATERIAL", material_value),
        ("KANTEN", deburr_value),
        ("PROJEKTION", projection_short),
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
    title_info = "\n".join(info_chunks)
    return svg.replace("</svg>", f"{views_svg}\n{annotation}\n{title_info}\n</svg>")


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
):
    if layout_profile != "sheet_metal":
        return ""

    # Flat pattern area: right half of the drawing, lower half (where ISO view was).
    # For sheet_metal parts the ISO view is suppressed, so the Abwicklung gets
    # the full bottom-right cell.  For A2 sheets the allocation is proportionally larger.
    avail_draw_w = sheet_w - 2 * margin
    avail_draw_h = draw_bottom - margin
    if sheet_name == "A2":
        area_w = min(245.0, avail_draw_w * 0.48)
        area_h = min(90.0, avail_draw_h * 0.46)
    else:  # A3
        area_w = min(172.0, avail_draw_w * 0.48)
        area_h = min(72.0, avail_draw_h * 0.44)
    area_w = max(120.0, area_w)
    area_h = max(50.0, area_h)
    flat_cx = sheet_w - margin - area_w * 0.5
    flat_cy = margin + avail_draw_h * (0.62 if sheet_name == "A2" else 0.60)

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

        # Scale SVG contour to fit the allocated area
        scale_x = (area_w * 0.80) / max(ob_w, 1e-6)
        scale_y = (area_h * 0.65) / max(ob_h, 1e-6)
        draw_scale = min(scale_x, scale_y)
        svg_w = ob_w * draw_scale
        svg_h = ob_h * draw_scale
        svg_x = flat_cx - svg_w / 2
        svg_y = flat_cy - svg_h / 2

        # Transform: map SVG origin (ob_x1, ob_y1) → drawing (svg_x, svg_y).
        # This correctly handles any offset and Y-flip from TechDraw projection.
        tx = svg_x - ob_x1 * draw_scale
        ty = svg_y - ob_y1 * draw_scale

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

        # Horizontal dimension (flat length) below the SVG
        dim_y_h = svg_y + svg_h + 5.0
        ext_y0 = svg_y + svg_h + 1.2
        parts.append(f'<line x1="{svg_x:.3f}" y1="{ext_y0:.3f}" x2="{svg_x:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{svg_x + svg_w:.3f}" y1="{ext_y0:.3f}" x2="{svg_x + svg_w:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{svg_x:.3f}" y1="{dim_y_h:.3f}" x2="{svg_x + svg_w:.3f}" y2="{dim_y_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(_arrow(svg_x, dim_y_h, "left"))
        parts.append(_arrow(svg_x + svg_w, dim_y_h, "right"))
        parts.append(f'<text x="{flat_cx:.3f}" y="{dim_y_h - 1.0:.3f}" style="{dim_style}" text-anchor="middle">{format_de_number(fl)}</text>')

        # Vertical dimension (flat width) to the left
        dim_x_v = svg_x - 5.0
        ext_x0 = svg_x - 1.2
        mid_y = svg_y + svg_h / 2
        parts.append(f'<line x1="{ext_x0:.3f}" y1="{svg_y:.3f}" x2="{dim_x_v:.3f}" y2="{svg_y:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{ext_x0:.3f}" y1="{svg_y + svg_h:.3f}" x2="{dim_x_v:.3f}" y2="{svg_y + svg_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(f'<line x1="{dim_x_v:.3f}" y1="{svg_y:.3f}" x2="{dim_x_v:.3f}" y2="{svg_y + svg_h:.3f}" stroke="rgb(0,0,0)" stroke-width="0.18" />')
        parts.append(_arrow(dim_x_v, svg_y, "up"))
        parts.append(_arrow(dim_x_v, svg_y + svg_h, "down"))
        parts.append(
            f'<text x="{dim_x_v - 1.0:.3f}" y="{mid_y:.3f}" style="{dim_style}" text-anchor="middle" '
            f'transform="rotate(-90,{dim_x_v - 1.0:.3f},{mid_y:.3f})">{format_de_number(fw)}</text>'
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
        return "\n".join(parts) + "\n" + "\n".join(note_parts)

    # ---------- Priority 2: Mathematical fallback (simple geometry only) ----------
    if (flat_pattern and flat_pattern.get("flat_length_mm") and flat_pattern.get("flat_width_mm")
            and not flat_pattern.get("complex_geometry")):
        fl = float(flat_pattern["flat_length_mm"])
        fw = float(flat_pattern["flat_width_mm"])
        complex_geom = bool(flat_pattern.get("complex_geometry"))
        k_used = flat_pattern.get("k_factor_used")

        # Scale the blank rectangle to fit the allocated area (with padding)
        scale_x = (area_w * 0.80) / max(fl, 1e-6)
        scale_y = (area_h * 0.65) / max(fw, 1e-6)
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
        bend_notes: list[str] = []

        if flat_extents and len(flat_extents) >= len(segments):
            # We have per-flange extent data: accumulate positions using actual extents.
            # flat_extents are sorted largest-first; treat first as the base flange.
            # For n bends: flanges = [e0, e1, ..., en] with bends between them.
            x_pos_mm = flat_extents[0] if flat_extents else 0.0
            for i, seg in enumerate(segments):
                allowance = float(seg.get("allowance_mm") or 0)
                bend_x = rect_x + x_pos_mm * draw_scale
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
                dir_arrow = "\u2191" if direction in ("OBEN", "UP") else "\u2193" if direction in ("UNTEN", "DOWN") else "\u2194"
                bend_notes.append(f"{dir_arrow} {angle_str}\u00B0 R{r_str}")
                next_extent = flat_extents[i + 1] if i + 1 < len(flat_extents) else 0.0
                x_pos_mm += allowance + next_extent
        else:
            # Fallback: distribute segment lengths evenly
            seg_len_each = total_segs_mm / max(len(segments) + 1, 2) if segments else 0
            x_pos_mm = seg_len_each
            for seg in segments:
                allowance = float(seg.get("allowance_mm") or 0)
                bend_x = rect_x + x_pos_mm * draw_scale
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
                dir_arrow = "\u2191" if direction in ("OBEN", "UP") else "\u2193" if direction in ("UNTEN", "DOWN") else "\u2194"
                bend_notes.append(f"{dir_arrow} {angle_str}\u00B0 R{r_str}")
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
        dim_y_h = rect_y + rect_h + 5.0
        ext_y0 = rect_y + rect_h + 1.2
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
        dim_x_v = rect_x - 5.0
        ext_x0 = rect_x - 1.2
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

        # Title: bold "ABWICKLUNG" + subtitle + compact bend notes
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
        k_subtitle = f"berechnet \u2014 K={format_de_number(k_used, 2)}" if k_used is not None else "berechnet"
        if complex_geom:
            k_subtitle += " \u2014 bitte pr\u00fcfen"
        note_parts = [
            f'<text x="{title_x:.1f}" y="{title_y:.1f}" style="{title_bold_style}">ABWICKLUNG</text>',
            f'<text x="{title_x:.1f}" y="{title_y + 5.0:.1f}" style="{subtitle_style}">{escape(k_subtitle)}</text>',
        ]
        for i, bn in enumerate(bend_notes[:4]):
            note_parts.append(
                f'<text x="{title_x:.1f}" y="{title_y + 9.5 + i * 3.5:.1f}" '
                f'style="{note_item_style}">{escape(bn)}</text>'
            )
        return "\n".join(parts) + "\n" + "\n".join(note_parts)

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
        return f"{group}\n" + "\n".join(fb_note_parts)


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


def evaluate_pre_export_quality(report, page_svg, dim_x, dim_y, dim_z):
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
    )
    for entry in text_entries:
        text = entry["text"]
        if any(marker in text for marker in skip_markers):
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
    duplicate_values = {}
    for item in dim_texts:
        key = item["text"]
        duplicate_values[key] = duplicate_values.get(key, 0) + 1
    redundant = [text for text, count in duplicate_values.items() if count > 1 and text not in overall_tokens]
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
    return {"status": status, "issues": issues}


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
    log(
        f"Layout profile: {layout_profile} | Flat pattern mode: {flat_pattern_mode} | "
        f"Sheet requested={requested_sheet}, resolved={sheet_resolved}"
    )

    sheet_w = spec["width"]
    sheet_h = spec["height"]
    margin = 10.0
    title_block_h = spec["title_block_h"]
    avail_w = sheet_w - 2 * margin
    avail_h = sheet_h - title_block_h - 2 * margin
    cell_w = avail_w / 2
    cell_h = avail_h / 2

    center_left_x = margin + cell_w * 0.5
    center_right_x = margin + cell_w * 1.5
    origin_y = margin
    center_top_y = origin_y + cell_h * 0.5
    center_bottom_y = origin_y + cell_h * 1.5

    view_dirs = compute_view_directions(shape, points=points)
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
        ("Front", front_dir, center_left_x, center_top_y),
        ("Left", left_dir, center_right_x, center_top_y),
        ("Top", top_dir, center_left_x, center_bottom_y),
        ("Iso", iso_dir, center_right_x, center_bottom_y),
    ]

    ortho_padding = 0.74 if layout_profile == "milling" else 0.70
    iso_padding = 0.82 if layout_profile == "milling" else 0.78
    view_data = []
    for name, direction, cx, cy in views:
        svg_group = TechDraw.projectToSVG(shape, direction)
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
        if name != "Iso":
            bounds_for_scale, scale_fit = compute_dimension_padded_bounds(
                bounds_for_layout, cell_w, cell_h, padding=ortho_padding, iterations=3
            )
        else:
            bounds_for_scale = bounds_for_layout
            scale_fit = compute_fit_scale(bounds_for_scale, cell_w, cell_h, padding=iso_padding)
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
                "cx": cx,
                "cy": cy,
                "proj_swap": proj_swap,
            }
        )
        log(
            f"View {name} svg: {svg_w:.2f} x {svg_h:.2f}, proj: {proj_w:.2f} x {proj_h:.2f}, swap={proj_swap}, rotate={rotation_deg}"
        )

    ortho_scale = min(
        item["scale_fit"] for item in view_data if item["name"] in ("Top", "Front", "Left")
    )
    log(f"ALIGN ortho_scale={ortho_scale:.4f}")
    iso_item = next((item for item in view_data if item["name"] == "Iso"), None)
    if iso_item is not None:
        iso_bounds = iso_item["layout_bounds"]
        iso_scale = compute_scale_for_area(iso_bounds, cell_w, cell_h, padding=iso_padding)
        iso_scale = min(iso_scale, ortho_scale * 0.75)
        iso_cx, iso_cy = center_right_x, center_bottom_y
        iso_item["cx"] = iso_cx
        iso_item["cy"] = iso_cy
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
        """Compute the bounding box enclosing all rendered views.
        For sheet_metal layout the ISO view is not rendered, so exclude it."""
        all_left, all_top = float('inf'), float('inf')
        all_right, all_bottom = float('-inf'), float('-inf')

        for item in view_data:
            if layout_profile == "sheet_metal" and item["name"] == "Iso":
                continue  # Iso is skipped in the rendering loop for sheet_metal
            scale = item.get("scale", ortho_scale)
            vb = compute_view_bounds(item, scale)
            all_left = min(all_left, vb["left"])
            all_top = min(all_top, vb["top"])
            all_right = max(all_right, vb["right"])
            all_bottom = max(all_bottom, vb["bottom"])

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
            "flat_pattern_mode": flat_pattern_mode,
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
                "rotation_deg": item["rotation_deg"],
                "center": [round(item["cx"], 2), round(item["cy"], 2)],
                "paper_size": [round(paper_w, 2), round(paper_h, 2)],
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
            report["alignment"]["front_top_left_match"] = abs(front_left - top_left) < 0.5
        
        if "Front" in report["views"] and "Left" in report["views"]:
            front_top = report["views"]["Front"]["top_edge"]
            left_top = report["views"]["Left"]["top_edge"]
            report["alignment"]["front_top_edge"] = front_top
            report["alignment"]["left_top_edge"] = left_top
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
    feature_view_name = None
    feature_view_circle_count = 0
    if isinstance(feature_payload, dict) and feature_payload.get("ok") is True:
        for candidate in view_data:
            if candidate["name"] == "Iso":
                continue
            circle_count = count_svg_circles(candidate["svg"])
            if circle_count > feature_view_circle_count:
                feature_view_circle_count = circle_count
                feature_view_name = candidate["name"]
        if feature_view_name:
            log(f"Feature dimension view: {feature_view_name} (circles={feature_view_circle_count})")

    for item in view_data:
        name = item["name"]

        # For sheet_metal parts, skip the ISO view — the Abwicklung (flat pattern)
        # occupies that quadrant. Showing both would cause visual overlap.
        if layout_profile == "sheet_metal" and name == "Iso":
            continue

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
            # Dimension strategy: avoid redundant overall dimensions.
            show_horizontal = True
            show_vertical = True
            if name == "Left":
                show_horizontal = False
                show_vertical = False
            elif name == "Top":
                # Keep only one depth overall dimension (prefer vertical on Top view).
                show_horizontal = False
                show_vertical = True
            # Dimension lines are drawn around the SVG geometry (svg_bounds)
            # but labels show the TRUE 3D dimensions (from proj_bounds)
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
            )
            centerline_svg, centerline_count = build_centerline_svg(
                item["svg"],
                scale,
                stroke_width,
                limit=30,
                line_profile=line_profile,
            )
            if centerline_svg:
                dimension_svg = f"{dimension_svg}{centerline_svg}"
            if feature_view_name == name:
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
        # View label below each view (ISO 128 style)
        _view_label_map = {
            "Front": "VORDERANSICHT",
            "Left": "SEITENANSICHT",
            "Top": "DRAUFSICHT",
            "Iso": "ISO",
        }
        _label_text = _view_label_map.get(name, name.upper())
        _label_style = (
            "font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; "
            "font-size: 2.5px; font-style: normal; font-weight: normal; fill: #444;"
        )
        # Bottom of view in paper coords: cy + half view height (proj_h * scale / 2) + gap
        _view_bottom = item["cy"] + max(proj_w, proj_h) * scale / 2.0 + 3.5
        view_groups.append(
            f'<text x="{item["cx"]:.2f}" y="{_view_bottom:.2f}" '
            f'style="{_label_style}" text-anchor="middle">{escape(_label_text)}</text>'
        )

    flat_pattern_overlay = build_flat_pattern_overlay(
        view_data,
        sheet_name=sheet_resolved,
        sheet_w=sheet_w,
        draw_bottom=draw_bottom,
        margin=margin,
        layout_profile=layout_profile,
        feature_payload=feature_payload,
        flat_pattern_mode=flat_pattern_mode,
        unfold_result=unfold_result,
    )
    if flat_pattern_overlay:
        view_groups.append(flat_pattern_overlay)

    report = build_report()
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
    tolerance_line = str(meta.get("general_tolerance", DEFAULT_GENERAL_TOLERANCE))
    tolerance_note = f"Allgemeintoleranzen nach {tolerance_line}"
    unit_line = f"Alle Masse in {meta.get('unit', 'mm')} sofern nicht anders angegeben."
    feature_lines = build_feature_annotation_lines(feature_payload, layout_profile)
    process_lines = []
    if layout_profile == "sheet_metal":
        thickness = estimate_sheet_thickness(feature_payload, dim_x, dim_y, dim_z)
        flat_pattern = (feature_payload or {}).get("flat_pattern") or {}
        k_used = flat_pattern.get("k_factor_used") or 0.33
        process_lines = [
            f"Blechst\u00e4rke = {format_de_number(thickness)}",
            f"K-Faktor = {format_de_number(k_used, 2)}",
        ]
        # "Scharfe Kanten entgraten" comes from build_feature_annotation_lines — no duplicate
    annotation_lines = [
        dimensions_text,
        f"Norm: {standard_line}",
        f"Projektion: {projection_line}",
        tolerance_note,
        unit_line,
    ] + process_lines + feature_lines
    log("DEBUG: dimensions_text set")

    template_path = Path(__file__).resolve().parent.parent / "templates" / spec["template"]
    if not template_path.exists():
        raise RuntimeError(f"Template not found: {template_path}")

    views_svg = "\n".join(view_groups)
    annotation_y = origin_y + avail_h - 4
    page_svg = build_page_svg(template_path, meta, views_svg, annotation_lines, annotation_y)
    pre_export_check = evaluate_pre_export_quality(report, page_svg, dim_x, dim_y, dim_z)
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

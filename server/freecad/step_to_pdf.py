import json
import os
import re
import sys
import math
from pathlib import Path
from xml.sax.saxutils import escape

import FreeCAD as App
import Import
import Part
import TechDraw
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg


def log(message):
    sys.stderr.write(f"[drawform] {message}\n")


def read_metadata(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


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
    paths = re.findall(r'd="([^"]+)"', svg_group)
    coords = []
    for path in paths:
        numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", path)
        for index in range(0, len(numbers) - 1, 2):
            coords.append((float(numbers[index]), float(numbers[index + 1])))
    if not coords:
        return 0.0, 1.0, 0.0, 1.0
    xs = [point[0] for point in coords]
    ys = [point[1] for point in coords]
    return min(xs), max(xs), min(ys), max(ys)


def svg_detail_score(svg_group):
    paths = re.findall(r'd="([^"]+)"', svg_group)
    segments = []
    coords_all = []
    for path in paths:
        numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", path)
        if len(numbers) < 4:
            continue
        coords = [float(value) for value in numbers]
        for index in range(0, len(coords) - 3, 2):
            x1 = coords[index]
            y1 = coords[index + 1]
            x2 = coords[index + 2]
            y2 = coords[index + 3]
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
    text_size_mm = 2.5
    text_gap_mm = 1.2
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


def build_dimension_svg(
    bounds,
    scale,
    stroke_width,
    label_width=None,
    label_height=None,
    rotation_deg=0,
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

    y_dim = max_y + offset
    x_dim = max_x + offset
    mid_x = (min_x + max_x) / 2
    mid_y = (min_y + max_y) / 2

    label_w = f"{label_width:.1f} mm"
    label_h = f"{label_height:.1f} mm"

    line_parts = [
        f'<line x1="{min_x:.3f}" y1="{y_dim:.3f}" x2="{max_x:.3f}" y2="{y_dim:.3f}" />',
        f'<line x1="{min_x:.3f}" y1="{max_y + gap:.3f}" x2="{min_x:.3f}" y2="{y_dim + ext_over:.3f}" />',
        f'<line x1="{max_x:.3f}" y1="{max_y + gap:.3f}" x2="{max_x:.3f}" y2="{y_dim + ext_over:.3f}" />',
        f'<line x1="{max_x + gap:.3f}" y1="{min_y:.3f}" x2="{x_dim + ext_over:.3f}" y2="{min_y:.3f}" />',
        f'<line x1="{max_x + gap:.3f}" y1="{max_y:.3f}" x2="{x_dim + ext_over:.3f}" y2="{max_y:.3f}" />',
        f'<line x1="{x_dim:.3f}" y1="{min_y:.3f}" x2="{x_dim:.3f}" y2="{max_y:.3f}" />',
    ]

    arrow_parts = [
        f'<polygon points="{min_x:.3f},{y_dim:.3f} {min_x + arrow_len:.3f},{y_dim - arrow_half:.3f} {min_x + arrow_len:.3f},{y_dim + arrow_half:.3f}" />',
        f'<polygon points="{max_x:.3f},{y_dim:.3f} {max_x - arrow_len:.3f},{y_dim - arrow_half:.3f} {max_x - arrow_len:.3f},{y_dim + arrow_half:.3f}" />',
        f'<polygon points="{x_dim:.3f},{min_y:.3f} {x_dim - arrow_half:.3f},{min_y + arrow_len:.3f} {x_dim + arrow_half:.3f},{min_y + arrow_len:.3f}" />',
        f'<polygon points="{x_dim:.3f},{max_y:.3f} {x_dim - arrow_half:.3f},{max_y - arrow_len:.3f} {x_dim + arrow_half:.3f},{max_y - arrow_len:.3f}" />',
    ]

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
    text_group = (
        f'<g fill="rgb(0, 0, 0)" stroke="none" font-size="{text_size:.3f}" '
        f'font-family="ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace" '
        f'font-style="normal" font-weight="normal" transform="scale(1,-1)">'
        f'<rect x="{width_rect_x:.3f}" y="{width_rect_y:.3f}" '
        f'width="{width_rect_w:.3f}" height="{width_rect_h:.3f}" fill="white" />'
        f'<text x="{width_x:.3f}" y="{width_y:.3f}" text-anchor="middle">'
        f'{escape(label_w)}</text>'
        f'<g{height_rotate}>'
        f'<rect x="{height_rect_x:.3f}" y="{height_rect_y:.3f}" '
        f'width="{height_rect_w:.3f}" height="{height_rect_h:.3f}" fill="white" />'
        f'<text x="{height_x:.3f}" y="{height_y:.3f}" text-anchor="middle">'
        f'{escape(label_h)}</text>'
        f'</g>'
        "</g>"
    )
    arrows = f'<g fill="rgb(0, 0, 0)" stroke="none">' + "".join(arrow_parts) + "</g>"
    return lines + arrows + text_group


def compute_stroke_width(scale, stroke_base=0.12, min_width=0.001):
    return max(min_width, stroke_base / max(scale, 0.05))


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


def build_view_group(
    svg_group,
    bounds,
    center_x,
    center_y,
    scale,
    rotation_deg=0,
    stroke_width=None,
    stroke_base=0.006,
    dimension_svg="",
):
    # Always use the ORIGINAL bounds for calculating the local center
    # The geometry must be centered BEFORE rotation
    min_x, max_x, min_y, max_y = bounds
    center_x_local = (min_x + max_x) / 2
    center_y_local = (min_y + max_y) / 2
    
    if stroke_width is None:
        stroke_width = compute_stroke_width(scale, stroke_base=stroke_base)
    svg_group = re.sub(r'stroke-width="[^"]+"', f'stroke-width="{stroke_width:.4f}"', svg_group)
    svg_group = re.sub(r'stroke-width:\s*[^;"\']+', f'stroke-width:{stroke_width:.4f}', svg_group)
    svg_group = re.sub(r"<g\s", '<g vector-effect="non-scaling-stroke" ', svg_group, count=1)
    svg_group = append_to_group(svg_group, dimension_svg)
    rotate_clause = f" rotate({rotation_deg})" if rotation_deg else ""
    transform = (
        f"translate({center_x:.2f},{center_y:.2f}) "
        f"scale({scale:.4f},{scale:.4f}){rotate_clause} "
        f"translate({-center_x_local:.2f},{center_y_local:.2f})"
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


def choose_front_direction(shape, points, axes):
    e1, e2, e3 = axes
    candidates = [
        ("+e1", e1),
        ("-e1", e1.negative()),
        ("+e2", e2),
        ("-e2", e2.negative()),
        ("+e3", e3),
        ("-e3", e3.negative()),
    ]
    priority = {name: idx for idx, name in enumerate(["+e3", "-e3", "+e1", "-e1", "+e2", "-e2"])}
    scored = []
    for name, direction in candidates:
        area = projected_area(points, direction)
        detail = 0.0
        try:
            svg = TechDraw.projectToSVG(shape, direction)
            detail = svg_detail_score(svg)
        except Exception:
            detail = 0.0
        scored.append((name, direction, area, detail))
    max_area = max((item[2] for item in scored), default=0.0)
    max_detail = max((item[3] for item in scored), default=0.0)
    epsilon = max(1e-9, max_area * 1e-6)
    detail_eps = max(1e-9, max_detail * 1e-6)
    best = None
    for name, direction, area, detail in scored:
        if best is None or area > best[2] + epsilon:
            best = (name, direction, area, detail)
        elif abs(area - best[2]) <= epsilon:
            if detail > best[3] + detail_eps:
                best = (name, direction, area, detail)
            elif abs(detail - best[3]) <= detail_eps:
                if priority[name] < priority[best[0]]:
                    best = (name, direction, area, detail)
    return best, scored


def compute_view_directions(shape, points=None):
    points = points or collect_points(shape)
    if len(points) < 3:
        return None
    axes, centered = pca_axes(points)
    if axes is None or centered is None:
        return None
    best, scored = choose_front_direction(shape, centered, axes)
    if best is None:
        return None
    front_dir = normalize_vec(best[1])
    if front_dir is None:
        return None
    front_dir = snap_axis(front_dir)
    frame = derive_view_frame(front_dir)
    if frame is None:
        return None
    right_dir, top_dir, iso_dir = frame
    left_dir = choose_side_direction(shape, right_dir, points=points)
    return {
        "front": front_dir,
        "top": top_dir,
        "left": left_dir,
        "iso": iso_dir,
        "debug": {
            "candidate_directions": [item[0] for item in scored],
            "projected_areas": {item[0]: item[2] for item in scored},
            "detail_scores": {item[0]: item[3] for item in scored},
            "chosen_front": best[0],
        },
    }


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


def build_page_svg(template_path, meta, views_svg, dimensions_text, annotation_y):
    svg = template_path.read_text(encoding="utf-8")
    replacements = {
        "TITLE": meta.get("title", "Manufacturing Drawing"),
        "DRAWING_NO": meta.get("drawing_no", "DF-0001"),
        "REV": meta.get("revision", "A"),
        "DATE": meta.get("date", ""),
        "SCALE": meta.get("scale", "auto"),
        "UNIT": meta.get("unit", "mm"),
        "SHEET": meta.get("sheet", "A3"),
        "AUTHOR": meta.get("author", ""),
        "COMPANY": meta.get("company", ""),
    }
    for key, value in replacements.items():
        svg = replace_text(svg, key, value)
    annotation = (
        f'<text x="12" y="{annotation_y:.1f}" '
        f'style="font-family: ISOCP, ISO 3098, Hershey Simplex, Simplex, monospace; '
        f'font-size: 2.5px; font-style: normal; font-weight: normal;">'
        f"{escape(dimensions_text)}</text>"
    )
    return svg.replace("</svg>", f"{views_svg}\n{annotation}\n</svg>")


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
    meta = read_metadata(meta_path)

    log(f"FreeCAD version: {App.Version()[0]}.{App.Version()[1]}.{App.Version()[2]}")
    doc = App.newDocument("DrawformDrawing")
    shape = load_shape(doc, input_path)
    points = collect_points(shape)

    bb = shape.BoundBox
    dim_x = bb.XLength
    dim_y = bb.YLength
    dim_z = bb.ZLength
    log(f"Bounds mm: X={dim_x:.2f} Y={dim_y:.2f} Z={dim_z:.2f}")

    sheet_w = 420.0
    sheet_h = 297.0
    margin = 10.0
    title_block_h = 55.0
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
    else:
        front_dir = view_dirs["front"]
        top_dir = view_dirs["top"]
        left_dir = view_dirs["left"]
        right_dir = left_dir.negative()
        iso_dir = view_dirs["iso"]
        debug = view_dirs["debug"]
        log(f"Front selection: {debug['chosen_front']}")
        log(f"Projected areas: {debug['projected_areas']}")
        log(f"Detail scores: {debug['detail_scores']}")

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

    view_data = []
    for name, direction, cx, cy in views:
        svg_group = TechDraw.projectToSVG(shape, direction)
        svg_bounds = extract_svg_bounds(svg_group)
        proj_bounds = projected_bounds(points, direction) or svg_bounds
        svg_w, svg_h = bounds_size(svg_bounds)
        proj_w, proj_h = bounds_size(proj_bounds)
        proj_swap = abs(svg_w - proj_h) + abs(svg_h - proj_w) < abs(svg_w - proj_w) + abs(svg_h - proj_h)
        aligned_proj_bounds = rotate_bounds_90(proj_bounds) if proj_swap else proj_bounds
        expected_w = None
        expected_h = None
        if name == "Front":
            expected_w = extent_right
            expected_h = extent_top
        elif name == "Top":
            expected_w = extent_right
            expected_h = extent_forward
        elif name == "Left":
            expected_w = extent_forward
            expected_h = extent_top
        rotation_deg = 0
        if name == "Top":
            rotation_deg = rotation_for_view_with_expected(
                direction, forward_dir, svg_bounds, expected_w, expected_h
            )
        elif name == "Left":
            rotation_deg = rotation_for_view_with_expected(
                direction, top_dir, svg_bounds, expected_w, expected_h
            )
            rotation_deg = (rotation_deg + 180) % 360
        bounds_for_scale = rotate_bounds_90(aligned_proj_bounds) if rotation_deg % 180 != 0 else aligned_proj_bounds
        if name != "Iso":
            scale_hint = compute_fit_scale(bounds_for_scale, cell_w, cell_h, padding=0.85)
            pad = dimension_metrics(bounds_for_scale, scale_hint)["pad"]
            bounds_for_scale = expand_bounds(bounds_for_scale, pad)
        scale_fit = compute_fit_scale(bounds_for_scale, cell_w, cell_h, padding=0.85)
        view_data.append(
            {
                "name": name,
                "svg": svg_group,
                "svg_bounds": svg_bounds,
                "proj_bounds": aligned_proj_bounds,
                "rotation_deg": rotation_deg,
                "bounds_for_scale": bounds_for_scale,
                "scale_fit": scale_fit,
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
    iso_item = next(item for item in view_data if item["name"] == "Iso")
    iso_bounds = (
        rotate_bounds_90(iso_item["proj_bounds"])
        if iso_item["rotation_deg"] % 180 != 0
        else iso_item["proj_bounds"]
    )
    iso_scale = compute_scale_for_area(iso_bounds, cell_w, cell_h, padding=0.9)
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
    def get_paper_dimensions(item, scale):
        """Get width and height in paper space after rotation"""
        svg_w, svg_h = bounds_size(item["svg_bounds"])
        if item["rotation_deg"] % 180 != 0:
            # 90 or 270 degree rotation swaps width and height
            return svg_h * scale, svg_w * scale
        return svg_w * scale, svg_h * scale
    
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

    view_groups = []
    for item in view_data:
        name = item["name"]
        svg_bounds = item["svg_bounds"]
        proj_bounds = item["proj_bounds"]
        proj_w, proj_h = bounds_size(proj_bounds)
        label_w = proj_h if item["rotation_deg"] % 180 != 0 else proj_w
        label_h = proj_w if item["rotation_deg"] % 180 != 0 else proj_h
        if name == "Iso":
            scale = item.get("scale", ortho_scale * 0.75)
            dimension_svg = ""
        else:
            scale = ortho_scale
            stroke_width = compute_stroke_width(scale)
            dimension_svg = build_dimension_svg(
                svg_bounds,
                scale,
                stroke_width,
                label_width=label_w,
                label_height=label_h,
                rotation_deg=item["rotation_deg"],
            )
        stroke_width = compute_stroke_width(scale)
        view_groups.append(
            build_view_group(
                item["svg"],
                svg_bounds,
                item["cx"],
                item["cy"],
                scale,
                rotation_deg=item["rotation_deg"],
                stroke_width=stroke_width,
                dimension_svg=dimension_svg,
            )
        )

    dimensions_text = "Overall size: X={:.1f} mm, Y={:.1f} mm, Z={:.1f} mm".format(
        dim_x, dim_y, dim_z
    )
    log("DEBUG: dimensions_text set")

    template_path = Path(__file__).resolve().parent.parent / "templates" / "iso7200_a3_landscape.svg"
    if not template_path.exists():
        raise RuntimeError(f"Template not found: {template_path}")

    views_svg = "\n".join(view_groups)
    annotation_y = origin_y + avail_h - 4
    page_svg = build_page_svg(template_path, meta, views_svg, dimensions_text, annotation_y)
    svg_path = Path(output_path).with_suffix(".svg")
    svg_path.write_text(page_svg, encoding="utf-8")

    debug_dir = os.getenv("DRAWFORM_DEBUG_DIR")
    if debug_dir:
        try:
            debug_root = Path(debug_dir)
            debug_root.mkdir(parents=True, exist_ok=True)
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

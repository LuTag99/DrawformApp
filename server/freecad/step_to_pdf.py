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
    svg_bounds,
    proj_bounds,
    center_x,
    center_y,
    scale,
    rotation_deg=0,
    stroke_width=None,
    stroke_base=0.006,
    dimension_svg="",
):
    """
    Build SVG group for a view, using PROJ_BOUNDS for positioning (like professional CAD).
    
    The key insight: proj_bounds (from 3D projection) gives us the TRUE size and position.
    svg_bounds may contain artifacts (hidden lines, etc.) and should NOT be used for layout.
    
    We calculate the offset between SVG content center and proj_bounds center,
    then apply that offset to position the SVG correctly.
    """
    # Calculate centers
    svg_min_x, svg_max_x, svg_min_y, svg_max_y = svg_bounds
    svg_center_x = (svg_min_x + svg_max_x) / 2
    svg_center_y = (svg_min_y + svg_max_y) / 2
    
    proj_min_x, proj_max_x, proj_min_y, proj_max_y = proj_bounds
    proj_center_x = (proj_min_x + proj_max_x) / 2
    proj_center_y = (proj_min_y + proj_max_y) / 2
    
    # Use PROJ center for positioning (this is the truth)
    # The SVG content needs to be translated so its center aligns with proj center
    local_center_x = proj_center_x
    local_center_y = proj_center_y
    
    if stroke_width is None:
        stroke_width = compute_stroke_width(scale, stroke_base=stroke_base)
    svg_group = re.sub(r'stroke-width="[^"]+"', f'stroke-width="{stroke_width:.4f}"', svg_group)
    svg_group = re.sub(r'stroke-width:\s*[^;"\']+', f'stroke-width:{stroke_width:.4f}', svg_group)
    svg_group = re.sub(r"<g\s", '<g vector-effect="non-scaling-stroke" ', svg_group, count=1)
    svg_group = append_to_group(svg_group, dimension_svg)
    rotate_clause = f" rotate({rotation_deg})" if rotation_deg else ""
    
    # Transform: 
    # 1. translate to paper position (center_x, center_y)
    # 2. scale
    # 3. rotate (if needed)
    # 4. translate to center the geometry (using proj_bounds center)
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
    
    if is_flat_part:
        # Flat part: look from thin side to show large face
        log(f"[FirstAngle] FLAT part (ratio={flatness_ratio:.2f}) -> look from {third_name}")
        front_dir = third_axis
        # Check which direction shows more detail
        svg_pos = TechDraw.projectToSVG(shape, third_axis)
        svg_neg = TechDraw.projectToSVG(shape, third_axis.negative())
        if svg_detail_score(svg_neg) > svg_detail_score(svg_pos):
            front_dir = third_axis.negative()
        # For flat parts, longest is horizontal
        horizontal_axis = longest_axis
    else:
        # Normal part: look perpendicular to longest axis
        # Choose between second and third axis based on detail score
        # Priority order: prefer Z-axis directions (typical CAD "top" view)
        # This helps with L-shapes and brackets where looking from Z shows the shape better
        candidates = [
            (third_axis, f"+{third_name}"),
            (third_axis.negative(), f"-{third_name}"),
            (second_axis, f"+{second_name}"),
            (second_axis.negative(), f"-{second_name}"),
        ]
        best_dir = candidates[0][0]
        best_score = 0
        best_name = candidates[0][1]
        for d, name in candidates:
            try:
                svg = TechDraw.projectToSVG(shape, d)
                score = svg_detail_score(svg)
                # Use >= to prefer earlier candidates (Z-axis) when scores are equal
                if score > best_score:
                    best_score = score
                    best_dir = d
                    best_name = name
            except:
                pass
        front_dir = best_dir
        log(f"[FirstAngle] Chose front {best_name} with score {best_score:.1f}")
        # Longest axis will be horizontal
        horizontal_axis = longest_axis
    
    log(f"[FirstAngle] Front direction: ({front_dir.x:.2f}, {front_dir.y:.2f}, {front_dir.z:.2f})")
    log(f"[FirstAngle] Horizontal axis (longest): {longest_name}")
    
    # === STEP 2: Build View Coordinate System ===
    # FORWARD = direction camera looks INTO (opposite of front_dir)
    # RIGHT = horizontal_axis (longest axis, horizontal in view)
    # UP = perpendicular to both (vertical in view)
    
    forward = App.Vector(-front_dir.x, -front_dir.y, -front_dir.z)
    
    # Make sure horizontal_axis is perpendicular to forward
    if abs(forward.dot(horizontal_axis)) > 0.9:
        # Longest is parallel to view direction (shouldn't happen normally)
        horizontal_axis = second_axis
    
    # Gram-Schmidt: make right perpendicular to forward
    dot = horizontal_axis.dot(forward)
    view_right = App.Vector(
        horizontal_axis.x - dot * forward.x,
        horizontal_axis.y - dot * forward.y,
        horizontal_axis.z - dot * forward.z
    )
    view_right = normalize_vec(view_right)
    if view_right is None:
        view_right = App.Vector(1, 0, 0)
    
    # UP = FORWARD × RIGHT (cross product)
    view_up = App.Vector(
        forward.y * view_right.z - forward.z * view_right.y,
        forward.z * view_right.x - forward.x * view_right.z,
        forward.x * view_right.y - forward.y * view_right.x
    )
    view_up = normalize_vec(view_up)
    if view_up is None:
        view_up = App.Vector(0, 0, 1)
    
    # === Orientation normalization ===
    # Goal: Consistent "up" direction across all parts
    # Convention: Z+ is world up, Y+ is secondary up
    # We want view_up to point toward world up as much as possible
    
    # Score each direction by how well it aligns with world up (Z+) or secondary up (Y+)
    # Higher score = better alignment with "up"
    def up_score(v):
        return v.z * 2.0 + v.y * 1.0  # Z gets double weight
    
    current_score = up_score(view_up)
    flipped_score = up_score(App.Vector(-view_up.x, -view_up.y, -view_up.z))
    
    if flipped_score > current_score:
        view_up = App.Vector(-view_up.x, -view_up.y, -view_up.z)
        view_right = App.Vector(-view_right.x, -view_right.y, -view_right.z)
    
    log(f"[FirstAngle] Up score: current={current_score:.2f}, flipped={flipped_score:.2f}")
    
    # At this point view_up should point toward "world up" as much as possible
    should_flip_up = False
    if abs(view_up.z) > 0.5:
        if view_up.z < 0:
            should_flip_up = True
    elif abs(view_up.y) > 0.5:
        if view_up.y < 0:
            should_flip_up = True
    elif abs(view_up.x) > 0.5:
        if view_up.x < 0:
            should_flip_up = True
    
    if should_flip_up:
        view_up = App.Vector(-view_up.x, -view_up.y, -view_up.z)
        # When we flip UP, we must also flip RIGHT to maintain right-hand rule
        # But this may cause RIGHT to be negative. That's OK for now.
        view_right = App.Vector(-view_right.x, -view_right.y, -view_right.z)
    
    # Snap to world axes
    front_dir = snap_axis(front_dir)
    view_right = snap_axis(view_right)
    view_up = snap_axis(view_up)
    
    log(f"[FirstAngle] View coords: RIGHT={vec_str(view_right)}, UP={vec_str(view_up)}, FWD={vec_str(forward)}")
    
    # === STEP 3: Derive other views (First-Angle Projection) ===
    # LEFT view: Look from LEFT side = -view_right direction
    left_dir = App.Vector(-view_right.x, -view_right.y, -view_right.z)
    
    # TOP view: Look from ABOVE = view_up direction (looking down from above)
    top_dir = App.Vector(view_up.x, view_up.y, view_up.z)
    
    # ISO view: Diagonal from front-right-top
    iso_dir = normalize_vec(App.Vector(
        forward.x + view_right.x + view_up.x,
        forward.y + view_right.y + view_up.y,
        forward.z + view_right.z + view_up.z
    ))
    if iso_dir is None:
        iso_dir = App.Vector(1, 1, 1)
    
    log(f"[FirstAngle] FRONT={vec_str(front_dir)}, LEFT={vec_str(left_dir)}, TOP={vec_str(top_dir)}")
    
    # Calculate confidence (how clear was the front selection)
    confidence = 0.5  # Default medium confidence
    
    debug_info = {
        "longest_axis": longest_name,
        "is_flat": is_flat_part,
        "flatness_ratio": round(flatness_ratio, 3),
        "view_right": [round(view_right.x, 2), round(view_right.y, 2), round(view_right.z, 2)],
        "view_up": [round(view_up.x, 2), round(view_up.y, 2), round(view_up.z, 2)],
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


def hybrid_view_selection(shape, points):
    """
    Hybrid algorithm for automatic view selection:
    
    1. GEOMETRY ANALYSIS: Find the longest axis (Hauptachse) of the bounding box
       - This axis should appear HORIZONTAL in the Front view
    
    2. FRONT SELECTION: From the 2 perpendicular directions, choose the best one
       - Primary: Aspect ratio (prefer wider views)
       - Tie-breaker: Feature/detail score
    
    3. DERIVE OTHER VIEWS: Top and Left are derived automatically
    
    4. CONFIDENCE: Calculate how clear the decision was
    
    Returns: (front_dir, top_dir, right_dir, confidence, debug_info)
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
    
    log(f"[Hybrid] Bounding box: {longest_name}={longest_len:.2f}, {second_name}={second_len:.2f}, {third_name}={third_len:.2f}")
    
    # Detect flat parts: if one dimension is much smaller than the other two
    flatness_ratio = third_len / max(second_len, 1e-6)
    is_flat_part = flatness_ratio < 0.3  # Third dimension is less than 30% of second
    
    if is_flat_part:
        # For flat parts (sheets, flanges): look from the THIN side to show the large face
        log(f"[Hybrid] Detected FLAT part (ratio={flatness_ratio:.2f}) -> Front looks from thin side ({third_name})")
        # Front should look from the thin axis direction
        front_candidates = [
            (f"+{third_name}", third_axis, third_len),
            (f"-{third_name}", third_axis.negative(), third_len),
        ]
        # Longest axis still horizontal
        log(f"[Hybrid] Longest axis: {longest_name} -> will be HORIZONTAL in Front")
    else:
        # Normal parts: longest axis horizontal, choose from perpendicular directions
        log(f"[Hybrid] Longest axis: {longest_name} -> will be HORIZONTAL in Front")
        front_candidates = [
            (f"+{second_name}", second_axis, second_len),
            (f"-{second_name}", second_axis.negative(), second_len),
            (f"+{third_name}", third_axis, third_len),
            (f"-{third_name}", third_axis.negative(), third_len),
        ]
    
    scored_candidates = []
    for name, direction, depth in front_candidates:
        # Calculate projected dimensions when looking from this direction
        basis = view_basis(direction)
        if basis is None:
            continue
        right, up = basis
        
        # Project points to get actual view dimensions
        proj = [(p.dot(right), p.dot(up)) for p in points]
        if not proj:
            continue
        xs = [p[0] for p in proj]
        ys = [p[1] for p in proj]
        view_w = max(xs) - min(xs)
        view_h = max(ys) - min(ys)
        
        # Aspect ratio: prefer wider views (width > height)
        aspect = view_w / max(view_h, 1e-6)
        
        # Feature score as tie-breaker
        try:
            svg = TechDraw.projectToSVG(shape, direction)
            detail = svg_detail_score(svg)
        except Exception:
            detail = 0.0
        
        scored_candidates.append({
            "name": name,
            "direction": direction,
            "depth": depth,
            "view_w": view_w,
            "view_h": view_h,
            "aspect": aspect,
            "detail": detail,
        })
    
    if not scored_candidates:
        return None, None, None, 0.0, {"error": "No valid candidates"}
    
    # Normalize scores
    max_detail = max(c["detail"] for c in scored_candidates)
    for c in scored_candidates:
        c["detail_norm"] = c["detail"] / max(max_detail, 1e-6)
    
    # Combined score: 70% aspect ratio preference + 30% detail score
    # Aspect > 1 means wider than tall (good for most parts)
    for c in scored_candidates:
        aspect_score = min(c["aspect"], 2.0) / 2.0  # Cap at 2:1, normalize to 0-1
        c["combined_score"] = 0.7 * aspect_score + 0.3 * c["detail_norm"]
    
    # Sort by combined score
    scored_candidates.sort(key=lambda c: c["combined_score"], reverse=True)
    
    best = scored_candidates[0]
    second_best = scored_candidates[1] if len(scored_candidates) > 1 else None
    
    # Confidence: how much better is best vs second best
    if second_best:
        score_diff = best["combined_score"] - second_best["combined_score"]
        confidence = min(1.0, score_diff / 0.3)  # 0.3 diff = 100% confidence
    else:
        confidence = 1.0
    
    front_dir = best["direction"]
    
    # Derive Top and Right from Front
    # The longest axis should be HORIZONTAL in both Front and Top view
    # Forward = opposite of front_dir (camera looks into -front_dir)
    forward = front_dir.negative()
    
    # Right direction = longest axis (horizontal in view)
    # Check which direction of longest_axis aligns better with "screen right"
    # For a standard view, we prefer X+ or the direction that gives consistent layout
    right_dir = longest_axis
    
    # If longest_axis is parallel to forward, we need to use a different axis
    dot_forward = abs(right_dir.dot(forward))
    if dot_forward > 0.9:
        # Longest axis is parallel to view direction, use second longest
        right_dir = second_axis
    
    # Make right perpendicular to forward (Gram-Schmidt)
    proj = forward.multiply(right_dir.dot(forward))
    right_dir = right_dir.sub(proj)
    right_dir = normalize_vec(right_dir)
    if right_dir is None:
        right_dir = longest_axis
    
    # Ensure right points in a consistent direction (prefer positive components)
    if right_dir.x < -0.5 or (abs(right_dir.x) < 0.1 and right_dir.y < -0.5):
        right_dir = right_dir.negative()
    
    # Up = forward x right (cross product)
    up_dir = forward.cross(right_dir)
    up_dir = normalize_vec(up_dir)
    if up_dir is None:
        up_dir = App.Vector(0, 0, 1)
    
    # Ensure up points "upward" (prefer Z+, then Y+)
    if up_dir.z < -0.5 or (abs(up_dir.z) < 0.1 and up_dir.y < -0.5):
        up_dir = up_dir.negative()
        right_dir = right_dir.negative()  # Flip right too to maintain handedness
    
    # Top view looks from up_dir direction
    top_dir = up_dir
    
    debug_info = {
        "longest_axis": longest_name,
        "candidates": [
            {
                "name": c["name"],
                "aspect": round(c["aspect"], 2),
                "detail": round(c["detail"], 1),
                "combined": round(c["combined_score"], 3),
            }
            for c in scored_candidates
        ],
        "chosen_front": best["name"],
        "confidence": round(confidence, 2),
        "view_dimensions": f"{best['view_w']:.1f} x {best['view_h']:.1f}",
    }
    
    log(f"[Hybrid] Front candidates: {[(c['name'], round(c['combined_score'], 3)) for c in scored_candidates]}")
    log(f"[Hybrid] Selected Front: {best['name']} (confidence={confidence:.2f})")
    
    return front_dir, top_dir, right_dir, confidence, debug_info


def choose_front_direction(shape, points, axes):
    """Legacy function - now delegates to hybrid_view_selection for compatibility."""
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
    """
    Use First-Angle Projection (ISO/DIN) for view selection.
    
    Returns dictionary with front, left, top, iso directions and debug info.
    """
    points = points or collect_points(shape)
    if len(points) < 3:
        return None
    
    # Use First-Angle Projection algorithm
    result = first_angle_projection(shape, points)
    
    if result is None or result.get("front") is None:
        log("[FirstAngle] Failed, falling back to legacy PCA method")
        # Fallback to legacy method
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
                "method": "legacy_pca",
                "chosen_front": best[0],
            },
        }
    
    # Add method info to debug
    result["debug"]["method"] = "first_angle_projection"
    
    # Also add view_right for alignment calculations
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
        right_dir = view_dirs.get("right", left_dir.negative())
        iso_dir = view_dirs["iso"]
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
        if name == "Front":
            # Front: Ensure longest axis (extent_right) appears horizontal
            rotation_deg = rotation_to_make_horizontal(svg_bounds, extent_right)
        elif name == "Top":
            # Top: Also ensure longest axis (extent_right) appears horizontal
            # to align with Front view
            rotation_deg = rotation_to_make_horizontal(svg_bounds, extent_right)
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
        """Get width and height in paper space after rotation.
        Use projected bounds for accurate dimensions instead of SVG bounds
        which may include hidden lines or other artifacts."""
        # Prefer projected bounds over SVG bounds for accuracy
        bounds = item.get("proj_bounds") or item.get("svg_bounds")
        w, h = bounds_size(bounds)
        if item["rotation_deg"] % 180 != 0:
            # 90 or 270 degree rotation swaps width and height
            return h * scale, w * scale
        return w * scale, h * scale
    
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
        paper_w, paper_h = get_paper_dimensions(item, scale)
        cx, cy = item["cx"], item["cy"]
        return {
            "left": cx - paper_w / 2,
            "top": cy - paper_h / 2,
            "right": cx + paper_w / 2,
            "bottom": cy + paper_h / 2,
        }
    
    def compute_all_views_bbox():
        """Compute the bounding box enclosing all views."""
        all_left, all_top = float('inf'), float('inf')
        all_right, all_bottom = float('-inf'), float('-inf')
        
        for item in view_data:
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
            "directions": {
                "front": [round(front_dir.x, 4), round(front_dir.y, 4), round(front_dir.z, 4)],
                "top": [round(top_dir.x, 4), round(top_dir.y, 4), round(top_dir.z, 4)],
                "right": [round(right_dir.x, 4), round(right_dir.y, 4), round(right_dir.z, 4)],
            },
            "scale": ortho_scale,
            "views": {},
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
        
        return report
    
    report = build_report()
    
    # Write JSON report
    debug_dir = os.getenv("DRAWFORM_DEBUG_DIR")
    if debug_dir:
        try:
            debug_root = Path(debug_dir)
            debug_root.mkdir(parents=True, exist_ok=True)
            json_name = f"{Path(input_path).stem}_report.json"
            json_path = debug_root / json_name
            json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            log(f"Report JSON written: {json_path}")
        except Exception as exc:
            log(f"Failed to write report JSON: {exc}")

    view_groups = []
    for item in view_data:
        name = item["name"]
        svg_bounds = item["svg_bounds"]
        proj_bounds = item["proj_bounds"]
        proj_w, proj_h = bounds_size(proj_bounds)
        svg_w, svg_h = bounds_size(svg_bounds)
        
        # The dimension lines are drawn in SVG coordinates:
        # - Horizontal dimension line (above view) shows "label_width" 
        # - Vertical dimension line (right of view) shows "label_height"
        #
        # After rotation, these lines swap positions:
        # - 90° rotation: horizontal becomes right, vertical becomes top
        # - So after 90°, the original "label_width" appears on the RIGHT, 
        #   and original "label_height" appears on TOP
        #
        # We want:
        # - TOP (horizontal after rotation) to show the longer 3D dimension
        # - RIGHT (vertical after rotation) to show the shorter 3D dimension
        #
        # proj_w and proj_h are 3D projected bounds
        # svg_w and svg_h tell us which dimension is horizontal/vertical in SVG
        
        # Determine which 3D dimension corresponds to which SVG axis
        # If swap=True, SVG dimensions are swapped relative to proj dimensions
        if item.get("proj_swap", False):
            # SVG width corresponds to proj_h, SVG height corresponds to proj_w
            svg_horizontal_3d = proj_h  # What 3D dimension is horizontal in SVG
            svg_vertical_3d = proj_w    # What 3D dimension is vertical in SVG
        else:
            svg_horizontal_3d = proj_w
            svg_vertical_3d = proj_h
        
        if item["rotation_deg"] % 180 != 0:
            # After 90° rotation:
            # - Original vertical (svg_vertical_3d) becomes horizontal dimension
            # - Original horizontal (svg_horizontal_3d) becomes vertical dimension
            label_w = svg_vertical_3d    # Now shown on horizontal dim line (top)
            label_h = svg_horizontal_3d  # Now shown on vertical dim line (right)
        else:
            label_w = svg_horizontal_3d  # Shown on horizontal dim line (top)
            label_h = svg_vertical_3d    # Shown on vertical dim line (right)
        
        if name == "Iso":
            scale = item.get("scale", ortho_scale * 0.75)
            dimension_svg = ""
        else:
            scale = ortho_scale
            stroke_width = compute_stroke_width(scale)
            # Use proj_bounds for dimension lines (accurate size)
            dimension_svg = build_dimension_svg(
                proj_bounds,  # Use proj_bounds, not svg_bounds!
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
                svg_bounds,      # SVG content bounds (for rendering)
                proj_bounds,     # Projected bounds (for positioning - the truth!)
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

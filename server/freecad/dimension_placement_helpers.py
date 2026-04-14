from __future__ import annotations


ORTHOGRAPHIC_VIEWS = {"Front", "Top", "Left"}
FEATURE_DIMENSION_TYPES = {
    "hole_diameter",
    "hole_pitch",
    "hole_location_x",
    "hole_location_y",
    "thread_callout",
    "bend_radius",
}


def build_feature_outside_band_profile(
    svg_bounds,
    scale,
    rotation_deg=0,
    *,
    view_name=None,
    layout_profile=None,
    overall_dimensions=None,
):
    """Return deterministic outside-placement bands for feature callouts.

    The profile reserves a dedicated top band for horizontal feature dimensions
    and a dedicated side band for vertical/leader-based feature dimensions.
    It intentionally prefers the side opposite the default overall-height band
    when a vertical overall dimension is present.
    """
    try:
        min_x, max_x, min_y, max_y = [float(value) for value in (svg_bounds or (0, 0, 0, 0))]
    except (TypeError, ValueError):
        min_x = max_x = min_y = max_y = 0.0
    width = max(0.0, max_x - min_x)
    height = max(0.0, max_y - min_y)
    smallest_span = max(min(width, height), 1.0)
    aspect_ratio = max(width, height) / smallest_span if max(width, height) > 0 else 1.0

    scale_safe = max(float(scale or 0.0), 0.05)
    rotation_norm = int(round(float(rotation_deg or 0.0))) % 360
    view = str(view_name or "").strip()
    layout = str(layout_profile or "").strip().lower()
    overall_entries = [entry for entry in (overall_dimensions or []) if isinstance(entry, dict)]
    has_vertical_overall = any(str(entry.get("axis") or "").upper() == "V" for entry in overall_entries)

    slender_front = view == "Front" and aspect_ratio >= 1.8
    aggressive = layout == "sheet_metal" or slender_front or aspect_ratio >= 2.6

    top_base_mm = 5.4 if aggressive else 4.4
    top_step_mm = 3.2 if aggressive else 2.6
    side_base_mm = 5.8 if aggressive else 4.8
    side_step_mm = 3.6 if aggressive else 2.8
    if view == "Front" and rotation_norm in {90, 270}:
        if layout == "sheet_metal":
            side_base_mm *= 1.12
            side_step_mm *= 1.08
        else:
            side_base_mm *= 0.78
            side_step_mm *= 0.82

    preferred_vertical_side = "left" if has_vertical_overall else "right"
    if view == "Front" and rotation_norm == 90:
        preferred_vertical_side = "left" if layout == "sheet_metal" else "right"
    elif view == "Front" and rotation_norm == 270:
        preferred_vertical_side = "right" if layout == "sheet_metal" else "left"
    elif not has_vertical_overall and rotation_norm in {0, 180}:
        preferred_vertical_side = "right"
    preferred_leader_side = preferred_vertical_side
    if view == "Front" and rotation_norm == 90:
        preferred_leader_side = "right" if layout == "sheet_metal" else "left"
    elif view == "Front" and rotation_norm == 270:
        preferred_leader_side = "left" if layout == "sheet_metal" else "right"

    return {
        "preferred_vertical_side": preferred_vertical_side,
        "preferred_leader_side": preferred_leader_side,
        "top_base_offset": top_base_mm / scale_safe,
        "top_step": top_step_mm / scale_safe,
        "side_base_offset": side_base_mm / scale_safe,
        "side_step": side_step_mm / scale_safe,
        "label_band_depth": (top_base_mm + top_step_mm * 6.0) / scale_safe,
        "is_aggressive": aggressive,
    }


def minimum_overall_dimension_offset(scale, text_size, *, axis="H", summary_line_pad=0.0):
    """Return a local-space minimum clearance for overall dimensions.

    Clamp logic may pull overall dimensions inward to avoid neighbour slots or
    the title-block reserve. Without a lower bound, the dimension line or its
    text box can end up inside the geometry. The vertical case needs a larger
    floor because the rotated text box extends sideways around the dimension
    line, while the horizontal case only needs to keep the label's lower edge
    clear of the outline.
    """

    scale_safe = max(float(scale or 0.0), 0.05)
    text_extent = max(float(text_size or 0.0), 0.0)
    line_pad = max(float(summary_line_pad or 0.0), 0.0)
    base_clearance = max(1.6 / scale_safe, line_pad + 0.2 / scale_safe)
    axis_kind = str(axis or "H").strip().upper()
    if axis_kind == "V":
        return max(base_clearance, text_extent * 0.72 + line_pad)
    return max(base_clearance, text_extent * 0.34 + line_pad)


def should_place_feature_dims_outside(view_name, allowed_dim_types=None):
    """Prefer external feature dimensions on orthographic production views."""
    if str(view_name or "") not in ORTHOGRAPHIC_VIEWS:
        return False
    dim_types = {
        str(dim_type).strip()
        for dim_type in (allowed_dim_types or [])
        if str(dim_type).strip()
    }
    if not dim_types:
        return False
    return bool(dim_types & FEATURE_DIMENSION_TYPES)


def should_allow_projected_centerlines(
    view_name,
    projected_target_count,
    visible_circle_counts,
):
    """Allow projected centerlines only when no orthographic visible-circle view exists.

    Projected centerlines are a fallback for views where the hole pattern is not
    drawn as explicit circles. Once another orthographic view exposes the same
    circular features visibly, repeating projected centerlines in the feature
    view just inflates centerline totals and can enlarge render bounds enough to
    destabilise the layout.
    """

    if str(view_name or "") not in ORTHOGRAPHIC_VIEWS:
        return False
    try:
        projected_count = int(projected_target_count or 0)
    except (TypeError, ValueError):
        projected_count = 0
    if projected_count <= 0:
        return False

    visible_total = 0
    if isinstance(visible_circle_counts, dict):
        for candidate_name, candidate_count in visible_circle_counts.items():
            if str(candidate_name or "") not in ORTHOGRAPHIC_VIEWS:
                continue
            try:
                visible_total += max(0, int(candidate_count or 0))
            except (TypeError, ValueError):
                continue
    return visible_total <= 0


def should_fallback_feature_dims_to_visible_view(
    requested_view_name,
    visible_feature_view_name,
    requested_visible_circle_count,
    requested_projected_target_count,
    visible_feature_circle_count,
    layout_bounds,
    rotation_deg,
    *,
    layout_profile=None,
):
    """Prefer a visible-circle orthographic view over projected Front placement.

    Long, rotated Front strip views can technically host projected feature
    dimensions, but the resulting outside placement often consumes more paper
    height than the A3 grid can offer. In those cases it is more stable to
    render the feature dimensions in the orthographic view that already exposes
    visible circles.
    """

    profile = str(layout_profile or "").strip().lower()
    if profile not in ("milling", "sheet_metal"):
        return False
    requested_name = str(requested_view_name or "").strip()
    visible_name = str(visible_feature_view_name or "").strip()
    if requested_name not in ORTHOGRAPHIC_VIEWS:
        return False
    if visible_name not in ORTHOGRAPHIC_VIEWS or visible_name == requested_name:
        return False
    try:
        requested_visible = int(requested_visible_circle_count or 0)
    except (TypeError, ValueError):
        requested_visible = 0
    try:
        requested_projected = int(requested_projected_target_count or 0)
    except (TypeError, ValueError):
        requested_projected = 0
    try:
        visible_circles = int(visible_feature_circle_count or 0)
    except (TypeError, ValueError):
        visible_circles = 0
    if requested_visible > 0 or requested_projected <= 0 or visible_circles <= 0:
        return False

    rotation_norm = int(round(float(rotation_deg or 0.0))) % 360
    if rotation_norm not in {90, 270}:
        return False

    try:
        min_x, max_x, min_y, max_y = [float(value) for value in (layout_bounds or (0, 0, 0, 0))]
    except (TypeError, ValueError):
        return False
    width = max(0.0, max_x - min_x)
    height = max(0.0, max_y - min_y)
    short_span = max(1.0, min(width, height))
    long_span = max(width, height)
    aspect_ratio = long_span / short_span
    return aspect_ratio >= 3.5 and short_span <= 70.0


def should_suppress_feature_dims_postcheck(layout_profile, feature_quality):
    """Apply conservative post-check suppression only where it adds value.

    Geometric collisions remain a hard stop for every layout profile. Pure
    feature-vs-overall overlaps are currently only used as a suppression signal
    for milling views, where rotated strip layouts otherwise tend to spill
    callouts into neighbouring dimension bands. Sheet-metal fronts can tolerate
    single overall-band crossings without losing manufacturability.
    """

    if not isinstance(feature_quality, dict):
        return False
    try:
        geom_overlap_count = int(feature_quality.get("feature_geom_overlap_count") or 0)
    except (TypeError, ValueError):
        geom_overlap_count = 0
    try:
        overall_overlap_count = int(feature_quality.get("feature_overall_overlap_count") or 0)
    except (TypeError, ValueError):
        overall_overlap_count = 0
    if geom_overlap_count > 0:
        return True
    return (
        str(layout_profile or "").strip().lower() == "milling"
        and overall_overlap_count > 0
    )

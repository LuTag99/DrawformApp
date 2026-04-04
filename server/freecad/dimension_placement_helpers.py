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
        preferred_leader_side = "right"
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

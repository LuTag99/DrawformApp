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

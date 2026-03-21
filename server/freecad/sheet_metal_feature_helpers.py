from __future__ import annotations

from copy import deepcopy
from typing import Mapping


SUPPORTED_FEATURE_DIM_TYPES = {
    "hole_diameter",
    "hole_pitch",
    "hole_location_x",
    "hole_location_y",
}

ORTHOGRAPHIC_VIEWS = ("Front", "Top", "Left")
_VIEW_PRIORITY = {"Front": 0, "Top": 1, "Left": 2}


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_view_plan(dim_plan: Mapping[str, object] | None, view_name: str) -> dict | None:
    if not isinstance(dim_plan, Mapping):
        return None
    for view in dim_plan.get("views", []):
        if isinstance(view, Mapping) and str(view.get("view_name")) == view_name:
            return dict(view)
    return None


def plan_has_folded_feature_dims(dim_plan: Mapping[str, object] | None) -> bool:
    if not isinstance(dim_plan, Mapping):
        return False
    for view in dim_plan.get("views", []):
        if not isinstance(view, Mapping):
            continue
        if str(view.get("view_name")) not in ORTHOGRAPHIC_VIEWS:
            continue
        for dim in view.get("dimensions", []):
            if not isinstance(dim, Mapping):
                continue
            if str(dim.get("dim_type")) in SUPPORTED_FEATURE_DIM_TYPES:
                return True
    return False


def choose_folded_feature_view(view_circle_counts: Mapping[str, int] | None) -> str | None:
    if not isinstance(view_circle_counts, Mapping):
        return None
    candidates: list[tuple[int, int, str]] = []
    for view_name in ORTHOGRAPHIC_VIEWS:
        count = int(view_circle_counts.get(view_name, 0) or 0)
        if count <= 0:
            continue
        candidates.append((-count, _VIEW_PRIORITY.get(view_name, 99), view_name))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def build_folded_feature_dimensions(
    feature_payload: Mapping[str, object] | None,
    *,
    target_view: str,
    detail_level: int = 1,
) -> list[dict]:
    if not isinstance(feature_payload, Mapping):
        return []

    hole_count = int(feature_payload.get("hole_count", 0) or 0)
    if hole_count <= 0:
        return []

    dims: list[dict] = []
    hole_diameter = _as_float(feature_payload.get("hole_diameter_mm"))
    hole_pitch = _as_float(feature_payload.get("hole_pitch_mm"))
    hole_groups = feature_payload.get("hole_groups") or []

    if hole_diameter is not None and hole_diameter > 0:
        dims.append(
            {
                "dim_type": "hole_diameter",
                "target_view": target_view,
                "axis": None,
                "value_mm": hole_diameter,
                "label": None,
                "priority": "must",
                "rule_id": "hole_diameter_required",
                "detail_level": detail_level,
            }
        )

    if hole_count >= 2 and hole_pitch is not None and hole_pitch > 0:
        dims.append(
            {
                "dim_type": "hole_pitch",
                "target_view": target_view,
                "axis": "H",
                "value_mm": hole_pitch,
                "label": None,
                "priority": "must",
                "rule_id": "hole_pattern_spacing",
                "detail_level": detail_level,
            }
        )

    if hole_groups:
        dims.append(
            {
                "dim_type": "hole_location_x",
                "target_view": target_view,
                "axis": "H",
                "value_mm": None,
                "label": None,
                "priority": "must",
                "rule_id": "hole_location_required",
                "detail_level": detail_level,
            }
        )
        dims.append(
            {
                "dim_type": "hole_location_y",
                "target_view": target_view,
                "axis": "V",
                "value_mm": None,
                "label": None,
                "priority": "must",
                "rule_id": "hole_location_required",
                "detail_level": detail_level,
            }
        )

    return dims


def inject_folded_sheet_metal_feature_dims(
    dim_plan: Mapping[str, object] | None,
    feature_payload: Mapping[str, object] | None,
    view_circle_counts: Mapping[str, int] | None,
) -> dict | None:
    if not isinstance(dim_plan, Mapping):
        return None
    if str(dim_plan.get("part_type")) != "sheet_metal":
        return dict(dim_plan)
    if plan_has_folded_feature_dims(dim_plan):
        return dict(dim_plan)

    target_view = choose_folded_feature_view(view_circle_counts)
    if target_view is None:
        hole_count = int(feature_payload.get("hole_count", 0) or 0) if isinstance(feature_payload, Mapping) else 0
        if hole_count > 0:
            # Slot-like cut-outs and simplified folded views may not expose a
            # literal SVG circle. In that case, keep the folded feature
            # dimensioning in the Front view instead of dropping it entirely.
            target_view = "Front"
    if not target_view:
        return dict(dim_plan)

    detail_level = int(dim_plan.get("detail_level", 1) or 1)
    new_dims = build_folded_feature_dimensions(
        feature_payload,
        target_view=target_view,
        detail_level=detail_level,
    )
    if not new_dims:
        return dict(dim_plan)

    cloned = deepcopy(dict(dim_plan))
    views = cloned.setdefault("views", [])
    for view in views:
        if not isinstance(view, dict):
            continue
        if str(view.get("view_name")) != target_view:
            continue
        existing_types = {
            str(dim.get("dim_type"))
            for dim in view.get("dimensions", [])
            if isinstance(dim, Mapping)
        }
        for dim in new_dims:
            if dim["dim_type"] not in existing_types:
                view.setdefault("dimensions", []).append(dim)
        return cloned

    views.append(
        {
            "view_name": target_view,
            "dimensions": new_dims,
            "show_centerlines": True,
        }
    )
    return cloned

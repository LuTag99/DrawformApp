"""Shared hole-group helpers used by DSE planning and rendering."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _opt_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def match_feature_hole_groups(
    feature_payload: dict,
    diameter_mm: float | None = None,
) -> List[dict]:
    hole_groups = (feature_payload or {}).get("hole_groups") or []
    if diameter_mm is None:
        return [group for group in hole_groups if isinstance(group, dict)]

    tol = max(0.25, float(diameter_mm) * 0.08)
    matching = [
        group
        for group in hole_groups
        if isinstance(group, dict)
        and _opt_float(group.get("diameter_mm")) is not None
        and abs(float(group.get("diameter_mm")) - float(diameter_mm)) <= tol
    ]
    return matching or [group for group in hole_groups if isinstance(group, dict)]


def summarize_feature_hole_extent(
    feature_payload: dict,
    *,
    diameter_mm: float | None = None,
) -> Optional[Dict[str, Any]]:
    groups = match_feature_hole_groups(feature_payload, diameter_mm=diameter_mm)
    if not groups:
        return None

    classified = [
        group
        for group in groups
        if isinstance(group.get("through"), bool) or _opt_float(group.get("depth_mm")) is not None
    ]
    if not classified:
        return None

    through_flags = [group.get("through") for group in classified if isinstance(group.get("through"), bool)]
    if through_flags and all(flag is True for flag in through_flags):
        return {"through": True, "depth_mm": None, "count": len(classified)}

    blind_depths = [
        _opt_float(group.get("depth_mm"))
        for group in classified
        if group.get("through") is False and _opt_float(group.get("depth_mm")) is not None
    ]
    blind_depths = [depth for depth in blind_depths if depth is not None and depth > 0]
    if through_flags and all(flag is False for flag in through_flags) and blind_depths:
        ref_depth = float(blind_depths[0])
        tol = max(0.25, ref_depth * 0.08)
        if all(abs(float(depth) - ref_depth) <= tol for depth in blind_depths):
            return {
                "through": False,
                "depth_mm": float(sum(blind_depths) / len(blind_depths)),
                "count": len(classified),
            }
    return None

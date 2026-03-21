from __future__ import annotations

import re


_SCALE_Y_FLIP_RE = re.compile(
    r'transform\s*=\s*"[^"]*scale\(\s*1(?:\.0+)?\s*,\s*-1(?:\.0+)?\s*\)',
    re.IGNORECASE,
)


def svg_uses_y_flip(svg_text: str | None) -> bool:
    if not isinstance(svg_text, str) or not svg_text:
        return False
    return bool(_SCALE_Y_FLIP_RE.search(svg_text))


def transform_svg_bounds_for_display(
    bounds: tuple[float, float, float, float] | list[float] | None,
    *,
    flip_y: bool,
) -> tuple[float, float, float, float] | None:
    if not bounds or len(bounds) != 4:
        return None
    x1, x2, y1, y2 = (float(value) for value in bounds)
    if flip_y:
        y1, y2 = -y2, -y1
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, x2, y1, y2


def transform_svg_y_for_display(value: float | int, *, flip_y: bool) -> float:
    numeric = float(value)
    return -numeric if flip_y else numeric

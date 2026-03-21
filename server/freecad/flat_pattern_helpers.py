from __future__ import annotations

import math
from typing import Iterable


def _as_float(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _cluster_axis_positions(values: Iterable[float], tolerance: float) -> list[float]:
    clustered: list[float] = []
    parsed_values = [parsed for parsed in (_as_float(value) for value in values) if parsed is not None]
    for raw in sorted(parsed_values):
        if not clustered or abs(raw - clustered[-1]) > tolerance:
            clustered.append(raw)
        else:
            clustered[-1] = (clustered[-1] + raw) * 0.5
    return clustered


def build_flange_segment_metadata(
    positions: Iterable[float],
    *,
    lower: float,
    upper: float,
    total_mm: float | None,
    axis: str,
    min_segment_mm: float = 1.0,
    merge_tolerance: float | None = None,
) -> list[dict[str, float | str]]:
    low = _as_float(lower)
    high = _as_float(upper)
    total = _as_float(total_mm)
    if low is None or high is None or total is None:
        return []
    if high < low:
        low, high = high, low
    span = high - low
    if span <= 1e-6 or total <= 0.0:
        return []

    tolerance = merge_tolerance
    if tolerance is None:
        tolerance = max(span * 0.003, 0.35)

    filtered = []
    for raw in positions:
        value = _as_float(raw)
        if value is None:
            continue
        if value <= low + tolerance or value >= high - tolerance:
            continue
        filtered.append(value)

    interior_positions = _cluster_axis_positions(filtered, tolerance)
    if not interior_positions:
        return []
    edges = [low, *interior_positions, high]
    segments: list[dict[str, float | str]] = []
    for start, end in zip(edges, edges[1:]):
        segment_span = end - start
        if segment_span <= tolerance * 0.25:
            continue
        label_mm = total * (segment_span / span)
        if label_mm < min_segment_mm:
            continue
        segments.append(
            {
                "axis": axis,
                "start": start,
                "end": end,
                "label_mm": label_mm,
            }
        )
    return segments

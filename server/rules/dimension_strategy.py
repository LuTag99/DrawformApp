"""Dimension Strategy Engine (DSE) — deterministic rule-based dimension planning.

Consumes a feature_payload (from step_feature_probe.py) and produces a
DimensionPlan describing *what* to dimension.  The plan is serialized as
JSON and passed to step_to_pdf.py via meta.json.

LLM overrides are applied on top of the deterministic baseline via
``apply_overrides()``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .dimension_plan_schema import (
    DatumSystem,
    DimensionItem,
    DimensionPlan,
    ProcessNote,
    ViewPlan,
)
from .rule_engine import KnowledgeError, load_knowledge_base, select_applicable_rules

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DIAMETER_SYMBOL = "\u00D8"  # Ø (U+00D8) — renders correctly in FreeCAD PDF fonts


def _fmt(value: float, decimals: int = 1) -> str:
    """Format a number with German decimal comma."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _opt_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Knowledge-base helpers
# ---------------------------------------------------------------------------

_KB_CACHE: dict | None = None


def _get_kb() -> dict:
    """Lazy-load the knowledge base once per process; returns {} on failure."""
    global _KB_CACHE
    if _KB_CACHE is None:
        try:
            _KB_CACHE = load_knowledge_base()
        except Exception:
            _KB_CACHE = {}
    return _KB_CACHE


def _kb_wants_dimension(
    kb: dict,
    feature: str,
    dimension_key: str,
    context: dict,
) -> Optional[str]:
    """Return rule_id if the KB mandates or suggests this dimension, else None.

    Consults only 'must' and 'should' priority rules (not 'must_not').
    The ``dimension_key`` matches against ``action.dimension`` or
    ``action.parameter`` in approved KB rules for the given feature+context.

    Context note: the rule_engine ``_match_condition`` strips ``_min``/``_max``
    suffixes, so ``when: {count_min: 2}`` requires ``context={"count": N}``,
    NOT ``context={"count_min": N}``.

    Returns None when the KB is empty or no matching rule fires — callers
    must fall back to their existing hardcoded logic in that case.

    Note: 'global' feature rules are not queried here to avoid false matches
    from global forbid/validate actions that share dimension key names.
    """
    if not kb:
        return None
    for rule in select_applicable_rules(kb, feature=feature, context=context):
        if rule.get("priority") == "must_not":
            continue
        for action in rule.get("actions", []):
            action_dim = action.get("dimension") or action.get("parameter")
            if action_dim == dimension_key:
                return str(rule["id"])
    return None


_VIEW_FALLBACK_ORDER = ("Front", "Top", "Left", "FlatPattern", "Iso")
_DIMENSION_PRIMARY_VIEWS: Dict[str, tuple[str, ...]] = {
    "overall_length": ("Front", "Top", "Left"),
    "overall_height": ("Front", "Left", "Top"),
    "overall_depth": ("Top", "Left", "Front"),
    "hole_diameter": ("Front", "Top", "Left"),
    "hole_pitch": ("Front", "Top", "Left"),
    "hole_location_x": ("Front", "Top", "Left"),
    "hole_location_y": ("Front", "Top", "Left"),
    "thread_callout": ("Front", "Left", "Top"),
    "bend_radius": ("Front", "Left", "Top"),
    "sheet_thickness": ("Front", "Left", "Top"),
    "flat_length": ("FlatPattern", "Front", "Top"),
    "flat_width": ("FlatPattern", "Front", "Left"),
    "pocket_depth": ("Left", "Front", "Top"),
    "pocket_location": ("Front", "Top", "Left"),
    "step_height": ("Left", "Front", "Top"),
}

def _rule_by_id(kb: dict, feature: str, context: dict) -> Dict[str, dict]:
    return {
        str(rule.get("id")): rule
        for rule in select_applicable_rules(kb, feature=feature, context=context)
        if isinstance(rule, dict) and rule.get("id")
    }


def _collect_policy_hints(kb: dict) -> Dict[str, Any]:
    hints: Dict[str, Any] = {}
    view_rules = _rule_by_id(kb, "view_selection", {})
    dim_rules = _rule_by_id(kb, "dimension", {})
    section_rules = _rule_by_id(kb, "section_view", {})
    layout_rules = _rule_by_id(kb, "drawing_layout", {})
    detail_rules = _rule_by_id(kb, "detail_view", {})
    centerline_rules = _rule_by_id(kb, "centerline", {})
    hole_pattern_rules = _rule_by_id(kb, "hole_pattern", {})

    front_rule = view_rules.get("front_view_information_priority")
    if front_rule:
        hints["front_view_rule_id"] = front_rule["id"]
        for action in front_rule.get("actions", []):
            if action.get("parameter") == "front_view":
                hints["front_view_strategy"] = action.get("rule")
            if action.get("parameter") == "hidden_edge_load" and str(action.get("value")).lower() == "low":
                hints["prefer_low_hidden_edge_load"] = True

    front_tie_break_rule = view_rules.get("front_view_tie_break_function_before_axis_order")
    if front_tie_break_rule:
        hints["front_view_tie_break_rule_id"] = front_tie_break_rule["id"]
        hints["prefer_functional_front_tie_break"] = True

    addl_rule = view_rules.get("additional_views_only_as_needed")
    if addl_rule:
        hints["additional_views_rule_id"] = addl_rule["id"]
        hints["limit_additional_views"] = True

    view_dim_rule = dim_rules.get("dimension_in_most_descriptive_view")
    if view_dim_rule:
        hints["dimension_view_rule_id"] = view_dim_rule["id"]
        hints["prefer_true_shape_view_for_dimensions"] = True

    chain_rule = dim_rules.get("avoid_closed_dimension_chains")
    if chain_rule:
        hints["dimension_chain_rule_id"] = chain_rule["id"]
        hints["avoid_closed_dimension_chains"] = True

    section_pref_rule = section_rules.get("section_preferred_over_hidden_edge_clutter")
    if section_pref_rule:
        hints["section_clutter_rule_id"] = section_pref_rule["id"]
        hints["prefer_section_over_hidden_edge_clutter"] = True

    layout_density_rule = layout_rules.get("dimension_density_requires_layout_escalation")
    if layout_density_rule:
        hints["layout_density_rule_id"] = layout_density_rule["id"]
        hints["split_dimensions_before_crowding"] = True
        hints["escalate_layout_for_dimension_density"] = True

    detail_view_rule = detail_rules.get("detail_view_for_small_or_dense_features")
    if detail_view_rule:
        hints["detail_view_rule_id"] = detail_view_rule["id"]
        hints["prefer_detail_views_for_dense_features"] = True

    centerline_rule = centerline_rules.get("symmetric_features_reference_centerlines")
    if centerline_rule:
        hints["centerline_reference_rule_id"] = centerline_rule["id"]
        hints["prefer_centerline_as_reference"] = True

    hole_pattern_rule = hole_pattern_rules.get("hole_pattern_prefer_coordinate_dimensioning")
    if hole_pattern_rule:
        hints["hole_pattern_coordinate_rule_id"] = hole_pattern_rule["id"]
        hints["prefer_coordinate_dimensioning_for_patterns"] = True

    return hints


def _dimension_semantic_key(dim: DimensionItem) -> tuple[Any, ...]:
    return (
        dim.dim_type,
        dim.value_mm,
        dim.label,
    )


def _dimension_policy_rank(view_name: str, dim: DimensionItem) -> tuple[int, int, int, int]:
    preferred = _DIMENSION_PRIMARY_VIEWS.get(dim.dim_type, _VIEW_FALLBACK_ORDER)
    try:
        preferred_rank = preferred.index(view_name)
    except ValueError:
        preferred_rank = len(preferred)
    view_rank = _VIEW_FALLBACK_ORDER.index(view_name) if view_name in _VIEW_FALLBACK_ORDER else len(_VIEW_FALLBACK_ORDER)
    priority_rank = 0 if dim.priority == "must" else 1
    return (preferred_rank, priority_rank, dim.detail_level, view_rank)


def _apply_dimension_policies(views: List[ViewPlan], policy_hints: Dict[str, Any]) -> List[ViewPlan]:
    if not policy_hints:
        return views

    enforce_single_view = bool(
        policy_hints.get("avoid_closed_dimension_chains")
        or policy_hints.get("prefer_true_shape_view_for_dimensions")
    )
    if not enforce_single_view:
        return views

    grouped: Dict[tuple[Any, ...], List[tuple[ViewPlan, DimensionItem]]] = {}
    for view in views:
        for dim in view.dimensions:
            grouped.setdefault(_dimension_semantic_key(dim), []).append((view, dim))

    keep_ids: set[int] = set()
    for dim_key, items in grouped.items():
        dim_type = str(dim_key[0] or "")
        if len(items) == 1 or dim_type not in _DIMENSION_PRIMARY_VIEWS:
            keep_ids.update(id(dim) for _view, dim in items)
            continue
        chosen_view, chosen_dim = min(
            items,
            key=lambda item: _dimension_policy_rank(item[0].view_name, item[1]),
        )
        keep_ids.add(id(chosen_dim))

    for view in views:
        view.dimensions = [dim for dim in view.dimensions if id(dim) in keep_ids]
    return views


def _bbox_dims(fp: dict) -> Dict[str, float]:
    """Extract X/Y/Z dimensions from feature payload bbox_mm."""
    bbox = fp.get("bbox_mm") or {}
    return {
        "X": float(bbox.get("X", 0)),
        "Y": float(bbox.get("Y", 0)),
        "Z": float(bbox.get("Z", 0)),
    }


def _looks_like_turning_part(fp: dict, dims: Dict[str, float]) -> bool:
    """Detect simple rotational/coaxial parts that should not use sheet-metal logic."""
    if not isinstance(fp, dict):
        return False
    if fp.get("rotational_profile") is True:
        return True

    flat_ratio = _opt_float(fp.get("flat_ratio"))
    if flat_ratio is not None and flat_ratio < 0.55:
        return False

    longest_axis = str(fp.get("longest_axis") or "").upper()
    if longest_axis not in {"X", "Y", "Z"}:
        longest_axis = max(dims, key=dims.get) if dims else "X"
    transverse_axes = [axis for axis in ("X", "Y", "Z") if axis != longest_axis]
    if len(transverse_axes) != 2:
        return False

    cross_dims = [max(0.0, float(dims.get(axis, 0.0))) for axis in transverse_axes]
    cross_max = max(cross_dims) if cross_dims else 0.0
    cross_min = min(cross_dims) if cross_dims else 0.0
    if cross_max <= 0.0 or cross_min / cross_max < 0.85:
        return False

    cylindrical_faces = int(fp.get("cylinder_face_count") or fp.get("cylindrical_face_count") or 0)
    hole_groups = fp.get("hole_groups") or []
    if cylindrical_faces < 2 or len(hole_groups) < 2:
        return False

    unique_diameters = {
        round(float(group.get("diameter_mm") or 0.0), 3)
        for group in hole_groups
        if _opt_float(group.get("diameter_mm")) not in (None, 0.0)
    }
    if len(unique_diameters) < 2:
        return False

    transverse_spans = []
    for axis in transverse_axes:
        key = axis.lower()
        coords = []
        for group in hole_groups:
            center = group.get("center_mm") or {}
            if not isinstance(center, dict):
                return False
            value = _opt_float(center.get(key))
            if value is None:
                return False
            coords.append(value)
        transverse_spans.append(max(coords) - min(coords))

    center_tol = max(0.5, cross_max * 0.02)
    return all(span <= center_tol for span in transverse_spans)


def _looks_like_compact_flat_milling_part(
    fp: dict,
    dims: Dict[str, float],
    measured_t: float | None,
) -> bool:
    """Guard compact plates from the weak sheet-metal fallback."""
    if not isinstance(fp, dict):
        return False

    flat_ratio = _opt_float(fp.get("flat_ratio"))
    if flat_ratio is not None and flat_ratio >= 0.35:
        return True

    sorted_dims = sorted((max(0.0, float(value)) for value in dims.values()), reverse=True)
    if len(sorted_dims) < 3 or sorted_dims[1] <= 0.0:
        return False

    longest, mid_dim, thickness = sorted_dims[:3]

    # Thick plates (> 8mm) are always milling, regardless of aspect ratio
    if thickness > 8.0:
        return True

    plan_aspect = longest / max(mid_dim, 1e-6)
    thickness_ratio = thickness / max(mid_dim, 1e-6)
    return plan_aspect <= 1.35 and thickness_ratio >= 0.08


# ---------------------------------------------------------------------------
# Layout profile (pure-python, no FreeCAD dependency)
# ---------------------------------------------------------------------------


def select_layout_profile_standalone(
    input_path: str,
    fp: dict,
) -> str:
    """Classify part as 'milling', 'sheet_metal', or 'turning' without FreeCAD.

    This is a pure-python clone of step_to_pdf.select_layout_profile()
    that uses fp["bbox_mm"] instead of FreeCAD BoundBox dimensions.
    """
    lower_input = str(input_path or "").lower()

    # Tier 0: Explicit path-based override
    if "sheetmetals" in lower_input or "sheetmetal" in lower_input:
        return "sheet_metal"

    if not isinstance(fp, dict):
        return "milling"

    measured_t = _opt_float(fp.get("measured_thickness_mm"))
    dims = _bbox_dims(fp)
    dim_x, dim_y, dim_z = dims["X"], dims["Y"], dims["Z"]

    # Guard before sheet-metal tiers:
    # coaxial multi-diameter cylinders (shafts, stepped shafts) often create
    # false bend/flat-pattern signals in the lightweight probe.
    if _looks_like_turning_part(fp, dims):
        return "turning"

    if _looks_like_compact_flat_milling_part(fp, dims, measured_t):
        return "milling"

    # Tier 1: Face-type geometry + thickness guard
    if fp.get("is_sheet_metal_by_faces") is True and measured_t is not None and measured_t <= 5.0:
        return "sheet_metal"

    # Tier 1.5: Bend geometry (strongest sheet metal signal)
    flat_pattern = fp.get("flat_pattern") or {}
    probe_bend_count = int(flat_pattern.get("bend_count") or 0)
    if probe_bend_count > 0:
        return "sheet_metal"

    # Tier 2: Measured wall thickness + flat bbox
    if measured_t is not None and 0.3 <= measured_t <= 5.0:
        cone_count = int(fp.get("cone_face_count") or 0)
        if cone_count == 0:
            bbox_min_dim = min(dim_x, dim_y, dim_z)
            pocket_ratio = bbox_min_dim / max(measured_t, 0.01)
            if pocket_ratio <= 3.0:
                flat_ratio = _opt_float(fp.get("flat_ratio"))
                if flat_ratio is not None and flat_ratio < 0.7:
                    return "sheet_metal"

    # Tier 3: BBox ratio fallback
    # Guard: absolute thickness > 8mm is never sheet metal (max ~6mm in practice)
    bbox_min_dim = min(dim_x, dim_y, dim_z)
    if bbox_min_dim > 8.0:
        return "milling"
    cone_count_t3 = int(fp.get("cone_face_count") or 0)
    if cone_count_t3 == 0:
        thickness_axis = str(fp.get("thickness_axis") or "").upper()
        thickness = dims.get(thickness_axis, min(dims.values()))
        sorted_dims = sorted(dims.values(), reverse=True)
        mid_dim = sorted_dims[1] if len(sorted_dims) > 1 else 1.0
        if mid_dim > 0 and thickness / mid_dim < 0.15:
            return "sheet_metal"

    return "milling"


def classify_milling_subtype(fp: dict) -> str:
    """Classify milling parts into v1 subtypes using existing probe fields."""
    if not isinstance(fp, dict):
        return "block_prismatic"

    hole_count = int(_opt_float(fp.get("hole_count")) or 0)
    slot_count = int(_opt_float(fp.get("slot_count")) or 0)
    flat_ratio = _opt_float(fp.get("flat_ratio"))

    if hole_count >= 8 or slot_count >= 4 or (hole_count + slot_count) >= 6:
        return "feature_dense"
    if flat_ratio is not None and flat_ratio < 0.25:
        return "plate_2p5d"
    return "block_prismatic"


# ---------------------------------------------------------------------------
# Datum system inference
# ---------------------------------------------------------------------------


def _infer_datum_system(fp: dict) -> DatumSystem:
    """Infer implicit A/B/C datums from geometry axes.

    A = plane perpendicular to thickness_axis (largest planar clamping face)
    B = plane perpendicular to longest_axis (reference edge)
    C = remaining orthogonal axis
    """
    thickness_axis = str(fp.get("thickness_axis") or "Z").upper()
    longest_axis = str(fp.get("longest_axis") or "X").upper()
    all_axes = {"X", "Y", "Z"}
    remaining = all_axes - {thickness_axis, longest_axis}
    c_axis = remaining.pop() if remaining else "Y"
    return DatumSystem(A=thickness_axis, B=longest_axis, C=c_axis)


# ---------------------------------------------------------------------------
# Part-type-specific planners
# ---------------------------------------------------------------------------


def _dim(dim_type: str, view: str, **kwargs: Any) -> DimensionItem:
    """Shorthand for creating a DimensionItem."""
    return DimensionItem(dim_type=dim_type, target_view=view, **kwargs)


def _plan_milling(
    fp: dict,
    detail_level: int,
) -> List[ViewPlan]:
    """Dimension plan for milling parts."""
    dims = _bbox_dims(fp)
    sorted_axes = sorted(dims.items(), key=lambda kv: kv[1], reverse=True)
    longest_val = sorted_axes[0][1] if sorted_axes else 0
    mid_val = sorted_axes[1][1] if len(sorted_axes) > 1 else 0
    shortest_val = sorted_axes[2][1] if len(sorted_axes) > 2 else 0

    hole_count = int(fp.get("hole_count") or 0)
    thread_label = fp.get("thread_label")
    kb = _get_kb()

    # Overall dimensions — KB: overall_dimensions_required (ISO 129-1)
    outer_rule_id = _kb_wants_dimension(
        kb, "outer_contour", "overall_length", {"view_kind": "orthographic"}
    )
    front_dims: List[DimensionItem] = [
        _dim("overall_length", "Front", axis="H", value_mm=longest_val,
             rule_id=outer_rule_id),
        _dim("overall_height", "Front", axis="V", value_mm=mid_val,
             rule_id=outer_rule_id),
    ]
    top_dims: List[DimensionItem] = [
        _dim("overall_depth", "Top", axis="V", value_mm=shortest_val,
             rule_id=outer_rule_id),
    ]

    # Hole features
    hole_diameter = _opt_float(fp.get("hole_diameter_mm"))
    hole_pitch = _opt_float(fp.get("hole_pitch_mm"))
    hole_groups = fp.get("hole_groups") or []

    # Hole diameter — KB: hole_diameter_required (ISO 129-1)
    hd_rule_id = _kb_wants_dimension(kb, "hole", "diameter", {"visible": True})
    if hd_rule_id is not None and hole_diameter is not None:
        front_dims.append(
            _dim("hole_diameter", "Front", value_mm=hole_diameter,
                 label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}",
                 rule_id=hd_rule_id)
        )
    elif hole_count > 0 and hole_diameter is not None:  # fallback when KB absent
        front_dims.append(
            _dim("hole_diameter", "Front", value_mm=hole_diameter,
                 label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}")
        )

    # Hole pitch — KB: hole_location_required (count_min=2, ISO 129-1)
    hp_rule_id = _kb_wants_dimension(
        kb, "hole_pattern", "pitch_or_spacing", {"count": hole_count}
    )
    if hp_rule_id is not None and hole_pitch is not None and hole_pitch > 0:
        front_dims.append(
            _dim("hole_pitch", "Front", axis="H", value_mm=hole_pitch,
                 rule_id=hp_rule_id)
        )
    elif hole_count >= 2 and hole_pitch is not None and hole_pitch > 0:  # fallback when KB absent
        front_dims.append(
            _dim("hole_pitch", "Front", axis="H", value_mm=hole_pitch)
        )

    # Hole locations from datum — KB: hole_location_required (count_min=2, ISO 129-1)
    # Fallback retains original ≥1 threshold when KB is absent (single-hole parts still get located)
    hl_rule_id = _kb_wants_dimension(
        kb, "hole_pattern", "position_from_datums", {"count": hole_count}
    )
    if hl_rule_id is not None and hole_groups:
        front_dims.append(_dim("hole_location_x", "Front", axis="H", rule_id=hl_rule_id))
        front_dims.append(_dim("hole_location_y", "Front", axis="V", rule_id=hl_rule_id))
    elif hole_count >= 1 and hole_groups:  # fallback when KB absent
        front_dims.append(_dim("hole_location_x", "Front", axis="H"))
        front_dims.append(_dim("hole_location_y", "Front", axis="V"))

    # Thread callout — KB: thread_callout_required (ISO 261/965)
    tc_rule_id = (
        _kb_wants_dimension(kb, "thread", "thread_designation", {})
        if thread_label else None
    )
    if tc_rule_id is not None and thread_label:
        front_dims.append(
            _dim("thread_callout", "Front",
                 label=f"{thread_label} GEWINDE",
                 rule_id=tc_rule_id)
        )
    elif thread_label:  # fallback when KB absent
        front_dims.append(_dim("thread_callout", "Front", label=f"{thread_label} GEWINDE"))

    # Slot features — KB: slot_complete_definition (ISO 129-1)
    slot_groups = fp.get("slot_groups") or []
    slot_count = int(fp.get("slot_count") or len(slot_groups))

    # Milling parts need a third orthographic overall size to expose the
    # remaining stock / thickness axis even at detail level 1.
    left_dims: List[DimensionItem] = [
        _dim("overall_depth", "Left", axis="H", value_mm=mid_val, priority="should")
    ]

    if slot_count > 0 and slot_groups:
        representative = slot_groups[0]
        sw = _opt_float(representative.get("width_mm"))
        sl = _opt_float(representative.get("length_mm"))
        orientation = str(representative.get("orientation") or "H")
        sw_rule_id = _kb_wants_dimension(kb, "slot", "width", {})
        sl_rule_id = _kb_wants_dimension(kb, "slot", "length", {})
        loc_rule_id = _kb_wants_dimension(kb, "slot", "location_from_datums", {})
        view = "Front" if orientation == "H" else "Left"
        slot_dims = front_dims if view == "Front" else left_dims
        if sw is not None:
            slot_dims.append(
                _dim("slot_width", view, axis="V", value_mm=sw,
                     rule_id=sw_rule_id, priority="should")
            )
        if sl is not None:
            slot_dims.append(
                _dim("slot_length", view, axis="H", value_mm=sl,
                     rule_id=sl_rule_id, priority="should")
            )
        slot_dims.append(
            _dim("slot_location", view, axis="H",
                 rule_id=loc_rule_id, priority="should")
        )
        if slot_count >= 2:
            front_dims.append(
                _dim("feature_count", "Front",
                     label=f"{slot_count}× LANGLOCH",
                     value_mm=float(slot_count), priority="should")
            )
    if detail_level >= 2:
        left_dims.append(
            _dim("overall_height", "Left", axis="V", value_mm=shortest_val,
                 detail_level=2, priority="should")
        )

    views = [
        ViewPlan(view_name="Front", dimensions=front_dims),
        ViewPlan(view_name="Top", dimensions=top_dims),
        ViewPlan(view_name="Left", dimensions=left_dims),
        ViewPlan(view_name="Iso", dimensions=[], show_centerlines=False),
    ]
    return views


def _plan_sheet_metal(
    fp: dict,
    unfold_result: Optional[dict],
    detail_level: int,
) -> List[ViewPlan]:
    """Dimension plan for sheet metal parts."""
    dims = _bbox_dims(fp)
    sorted_axes = sorted(dims.items(), key=lambda kv: kv[1], reverse=True)
    longest_val = sorted_axes[0][1] if sorted_axes else 0
    mid_val = sorted_axes[1][1] if len(sorted_axes) > 1 else 0

    kb = _get_kb()

    # Overall dimensions — KB: overall_dimensions_required (ISO 129-1)
    outer_rule_id = _kb_wants_dimension(
        kb, "outer_contour", "overall_length", {"view_kind": "orthographic"}
    )
    # 3D folded views — always present
    front_dims: List[DimensionItem] = [
        _dim("overall_length", "Front", axis="H", value_mm=longest_val,
             rule_id=outer_rule_id),
        _dim("overall_height", "Front", axis="V", value_mm=mid_val,
             rule_id=outer_rule_id),
    ]

    top_dims: List[DimensionItem] = []

    # Flat pattern (Abwicklung) — primary dimensioning surface for sheet metal
    flat_dims: List[DimensionItem] = []
    has_unfold = isinstance(unfold_result, dict) and unfold_result.get("ok") is True

    # flat_length / flat_width — KB: flat_pattern_dimensions_required
    fl_rule_id = _kb_wants_dimension(kb, "sheet_metal", "flat_length", {"has_unfold": has_unfold})
    fw_rule_id = _kb_wants_dimension(kb, "sheet_metal", "flat_width",  {"has_unfold": has_unfold})
    if has_unfold:
        fl = _opt_float(unfold_result.get("flat_length_mm"))
        fw = _opt_float(unfold_result.get("flat_width_mm"))
        if fl is not None:
            flat_dims.append(
                _dim("flat_length", "FlatPattern", axis="H", value_mm=fl,
                     rule_id=fl_rule_id)
            )
        if fw is not None:
            flat_dims.append(
                _dim("flat_width", "FlatPattern", axis="V", value_mm=fw,
                     rule_id=fw_rule_id)
            )

    # Bend radius only belongs on real bent parts. Flat laser-cut plates often
    # contain cylindrical hole walls that the feature probe reports as a
    # candidate radius, but they should not create a bend callout.
    flat_pattern = fp.get("flat_pattern") or {}
    if isinstance(unfold_result, dict) and unfold_result.get("ok") is True:
        has_real_bends = int(unfold_result.get("bend_count") or 0) > 0
    else:
        has_real_bends = int(flat_pattern.get("bend_count") or 0) > 0
    bend_radius = _opt_float(fp.get("bend_radius_mm"))

    # Bend radius — KB: bend_radius_required (has_real_bends guard)
    br_rule_id = _kb_wants_dimension(
        kb, "sheet_metal", "bend_radius", {"has_real_bends": has_real_bends}
    )
    if br_rule_id is not None and bend_radius is not None and bend_radius > 0:
        front_dims.append(
            _dim("bend_radius", "Front", value_mm=bend_radius,
                 label=f"R{_fmt(bend_radius)}",
                 priority="should", rule_id=br_rule_id)
        )
    elif has_real_bends and bend_radius is not None and bend_radius > 0:  # fallback when KB absent
        front_dims.append(
            _dim("bend_radius", "Front", value_mm=bend_radius,
                 label=f"R{_fmt(bend_radius)}",
                 priority="should")
        )

    # Sheet metal thickness ("s = X,X") — KB: sheet_thickness_required
    measured_t = _opt_float(fp.get("measured_thickness_mm"))
    has_thickness = measured_t is not None and 0 < measured_t <= 10.0
    st_rule_id = _kb_wants_dimension(
        kb, "sheet_metal", "sheet_thickness", {"has_thickness": has_thickness}
    )
    if st_rule_id is not None and has_thickness:
        front_dims.append(
            _dim("sheet_thickness", "Front", value_mm=measured_t,
                 label=f"s = {_fmt(measured_t)}",
                 priority="must", rule_id=st_rule_id)
        )
    elif has_thickness:  # fallback when KB absent
        front_dims.append(
            _dim("sheet_thickness", "Front", value_mm=measured_t,
                 label=f"s = {_fmt(measured_t)}",
                 priority="must")
        )

    # Hole features — sheet metal (Prio B in Blechteil-Leitlinie)
    hole_count = int(fp.get("hole_count") or 0)
    hole_diameter = _opt_float(fp.get("hole_diameter_mm"))
    hole_pitch = _opt_float(fp.get("hole_pitch_mm"))
    hole_groups = fp.get("hole_groups") or []

    # Hole diameter
    hd_rule_id = _kb_wants_dimension(kb, "hole", "diameter", {"visible": True})
    if hd_rule_id is not None and hole_diameter is not None:
        front_dims.append(
            _dim("hole_diameter", "Front", value_mm=hole_diameter,
                 label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}",
                 rule_id=hd_rule_id)
        )
    elif hole_count > 0 and hole_diameter is not None:  # fallback when KB absent
        front_dims.append(
            _dim("hole_diameter", "Front", value_mm=hole_diameter,
                 label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}")
        )

    # Hole pitch
    hp_rule_id = _kb_wants_dimension(
        kb, "hole_pattern", "pitch_or_spacing", {"count": hole_count}
    )
    if hp_rule_id is not None and hole_pitch is not None and hole_pitch > 0:
        front_dims.append(
            _dim("hole_pitch", "Front", axis="H", value_mm=hole_pitch,
                 rule_id=hp_rule_id)
        )
    elif hole_count >= 2 and hole_pitch is not None and hole_pitch > 0:
        front_dims.append(
            _dim("hole_pitch", "Front", axis="H", value_mm=hole_pitch)
        )

    # Hole locations from datum
    hl_rule_id = _kb_wants_dimension(
        kb, "hole_pattern", "position_from_datums", {"count": hole_count}
    )
    if hl_rule_id is not None and hole_groups:
        front_dims.append(_dim("hole_location_x", "Front", axis="H", rule_id=hl_rule_id))
        front_dims.append(_dim("hole_location_y", "Front", axis="V", rule_id=hl_rule_id))
    elif hole_count >= 1 and hole_groups:
        front_dims.append(_dim("hole_location_x", "Front", axis="H"))
        front_dims.append(_dim("hole_location_y", "Front", axis="V"))

    # Thread callout
    thread_label = fp.get("thread_label")
    tc_rule_id = (
        _kb_wants_dimension(kb, "thread", "thread_designation", {})
        if thread_label else None
    )
    if tc_rule_id is not None and thread_label:
        front_dims.append(
            _dim("thread_callout", "Front",
                 label=f"{thread_label} GEWINDE",
                 rule_id=tc_rule_id)
        )
    elif thread_label:
        front_dims.append(_dim("thread_callout", "Front", label=f"{thread_label} GEWINDE"))

    views = [
        ViewPlan(view_name="Front", dimensions=front_dims),
        ViewPlan(view_name="Top", dimensions=top_dims),
        ViewPlan(view_name="Left", dimensions=[]),
        ViewPlan(view_name="Iso", dimensions=[], show_centerlines=False),
    ]
    if flat_dims:
        views.append(ViewPlan(view_name="FlatPattern", dimensions=flat_dims))

    return views


def _plan_turning(
    fp: dict,
    detail_level: int,
) -> List[ViewPlan]:
    """Dimension plan for turning parts (placeholder)."""
    dims = _bbox_dims(fp)
    sorted_axes = sorted(dims.items(), key=lambda kv: kv[1], reverse=True)
    longest_val = sorted_axes[0][1] if sorted_axes else 0
    mid_val = sorted_axes[1][1] if len(sorted_axes) > 1 else 0

    kb = _get_kb()

    # Overall dimensions — KB: overall_dimensions_required (ISO 129-1)
    outer_rule_id = _kb_wants_dimension(
        kb, "outer_contour", "overall_length", {"view_kind": "orthographic"}
    )
    # Ø-label on overall_height — KB: turning_diameter_overall_required
    diam_rule_id = _kb_wants_dimension(kb, "turning", "overall_diameter", {})
    front_dims: List[DimensionItem] = [
        _dim("overall_length", "Front", axis="H", value_mm=longest_val,
             rule_id=outer_rule_id),
        _dim("overall_height", "Front", axis="V", value_mm=mid_val,
             label=f"{_DIAMETER_SYMBOL}{_fmt(mid_val)}",
             rule_id=diam_rule_id or outer_rule_id),
    ]

    # Hole diameter — KB: hole_diameter_required (ISO 129-1)
    hole_count = int(fp.get("hole_count") or 0)
    hole_diameter = _opt_float(fp.get("hole_diameter_mm"))
    hd_rule_id = _kb_wants_dimension(kb, "hole", "diameter", {"visible": True})
    if hd_rule_id is not None and hole_diameter is not None:
        front_dims.append(
            _dim("hole_diameter", "Front", value_mm=hole_diameter,
                 label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}",
                 rule_id=hd_rule_id)
        )
    elif hole_count > 0 and hole_diameter is not None:  # fallback when KB absent
        front_dims.append(
            _dim("hole_diameter", "Front", value_mm=hole_diameter,
                 label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}")
        )

    # Thread callout — KB: thread_callout_required (ISO 261/965)
    thread_label = fp.get("thread_label")
    tc_rule_id = (
        _kb_wants_dimension(kb, "thread", "thread_designation", {})
        if thread_label else None
    )
    if tc_rule_id is not None and thread_label:
        front_dims.append(
            _dim("thread_callout", "Front",
                 label=f"{thread_label} GEWINDE",
                 rule_id=tc_rule_id)
        )
    elif thread_label:  # fallback when KB absent
        front_dims.append(_dim("thread_callout", "Front", label=f"{thread_label} GEWINDE"))

    return [
        ViewPlan(view_name="Front", dimensions=front_dims),
        ViewPlan(view_name="Top", dimensions=[]),
        ViewPlan(view_name="Left", dimensions=[]),
        ViewPlan(view_name="Iso", dimensions=[], show_centerlines=False),
    ]


# ---------------------------------------------------------------------------
# Process notes
# ---------------------------------------------------------------------------


def _collect_process_notes(
    fp: dict,
    layout_profile: str,
    unfold_result: Optional[dict],
    detail_level: int,
) -> List[ProcessNote]:
    notes: List[ProcessNote] = []

    if layout_profile == "sheet_metal":
        measured_t = _opt_float(fp.get("measured_thickness_mm"))
        if measured_t is not None:
            notes.append(ProcessNote(
                note_type="thickness",
                text=f"t = {_fmt(measured_t)} mm",
            ))

        bend_radius = _opt_float(fp.get("bend_radius_mm"))
        if bend_radius is not None and bend_radius > 0:
            notes.append(ProcessNote(
                note_type="inner_radius",
                text=f"Ri = {_fmt(bend_radius)} mm",
            ))

        flat_pattern = fp.get("flat_pattern") or {}
        k_factor = _opt_float(flat_pattern.get("k_factor_used"))
        if k_factor is not None:
            notes.append(ProcessNote(
                note_type="k_factor",
                text=f"K = {_fmt(k_factor, 2)}",
            ))

    # General tolerance note — driven by KB rule general_tolerance_required (ISO 2768)
    kb = _get_kb()
    for rule in select_applicable_rules(kb, "global", {"view_kind": "any"}):
        if rule["id"] == "general_tolerance_required":
            for action in rule.get("actions", []):
                if action.get("type") == "add_annotation":
                    fmt_str = action.get(
                        "format",
                        "Allgemeintoleranzen nach DIN ISO 2768-{format_class}{form_class}",
                    )
                    tol_text = fmt_str.replace("{format_class}", "m").replace("{form_class}", "K")
                    notes.append(ProcessNote(note_type="tolerance", text=tol_text, detail_level=1))
            break

    # Edge deburring note — driven by KB rule edge_state_indication (ISO 13715), detail_level >= 2
    if detail_level >= 2:
        for rule in select_applicable_rules(kb, "edge", {}):
            if rule["id"] == "edge_state_indication":
                for action in rule.get("actions", []):
                    if action.get("type") == "add_annotation":
                        fmt_str = action.get("format", "Alle Kanten {min}-{max} entgraten")
                        edge_text = fmt_str.replace("{min}", "0,2").replace("{max}", "0,5")
                        notes.append(ProcessNote(
                            note_type="edge_note", text=edge_text, detail_level=2,
                        ))
                break

    return notes


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate(views: List[ViewPlan]) -> List[ViewPlan]:
    """Remove redundant dimensions across views.

    A dimension is considered redundant if the same (dim_type, value_mm) pair
    appears in multiple views.  The first occurrence (highest priority view)
    is kept.
    """
    seen: set = set()
    for view in views:
        kept: List[DimensionItem] = []
        for dim in view.dimensions:
            key = (dim.dim_type, dim.value_mm)
            # Allow None-value dims (they're placeholders like hole_location)
            if dim.value_mm is not None and key in seen:
                continue
            if dim.value_mm is not None:
                seen.add(key)
            kept.append(dim)
        view.dimensions = kept
    return views


# ---------------------------------------------------------------------------
# Override application
# ---------------------------------------------------------------------------


def apply_overrides(
    plan: DimensionPlan,
    overrides: List[dict],
) -> DimensionPlan:
    """Apply structured LLM overrides to a dimension plan.

    Each override is a dict with:
      - "action": "add" | "remove" | "modify"
      - "target_view": str (for add/remove)
      - "dim_type": str (for remove)
      - "dimension": dict (for add — fields of DimensionItem)
      - "changes": dict (for modify — partial update fields)
    """
    plan = plan.model_copy(deep=True)
    for ovr in overrides:
        action = ovr.get("action", "")
        plan.overrides_applied.append(ovr)

        if action == "add":
            target_view = ovr.get("target_view", "Front")
            dim_data = ovr.get("dimension", {})
            dim_data.setdefault("target_view", target_view)
            new_dim = DimensionItem(**dim_data)
            for view in plan.views:
                if view.view_name == target_view:
                    view.dimensions.append(new_dim)
                    break
            else:
                plan.views.append(ViewPlan(
                    view_name=target_view,
                    dimensions=[new_dim],
                ))

        elif action == "remove":
            target_view = ovr.get("target_view")
            dim_type = ovr.get("dim_type")
            for view in plan.views:
                if target_view and view.view_name != target_view:
                    continue
                view.dimensions = [
                    d for d in view.dimensions if d.dim_type != dim_type
                ]

        elif action == "modify":
            target_view = ovr.get("target_view")
            dim_type = ovr.get("dim_type")
            changes = ovr.get("changes", {})
            if not target_view:
                import logging
                logging.getLogger("drawform.dse").warning(
                    "modify override without target_view — skipping to avoid modifying all views"
                )
                continue
            for view in plan.views:
                if view.view_name != target_view:
                    continue
                for dim in view.dimensions:
                    if dim.dim_type == dim_type:
                        for k, v in changes.items():
                            if hasattr(dim, k):
                                setattr(dim, k, v)

    return plan


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def build_dimension_plan(
    feature_payload: dict,
    layout_profile: str = "milling",
    unfold_result: Optional[dict] = None,
    detail_level: int = 1,
    overrides: Optional[List[dict]] = None,
) -> DimensionPlan:
    """Build a deterministic dimension plan from feature payload + context.

    Parameters
    ----------
    feature_payload : dict
        Output of step_feature_probe.compute_payload().
    layout_profile : str
        Part type: "milling", "sheet_metal", or "turning".
    unfold_result : dict | None
        Output of step_unfold (for sheet metal).
    detail_level : int
        1 = manufacturing-minimal, 2 = inspection-ready, 3 = customer-spec.
    overrides : list[dict] | None
        Structured LLM overrides to apply on top of deterministic baseline.

    Returns
    -------
    DimensionPlan
        Serializable plan describing all dimension intents.
    """
    detail_level = max(1, min(3, detail_level))
    fp = feature_payload if isinstance(feature_payload, dict) else {}
    kb = _get_kb()
    policy_hints = _collect_policy_hints(kb)

    datum_system = _infer_datum_system(fp)

    if layout_profile == "sheet_metal":
        views = _plan_sheet_metal(fp, unfold_result, detail_level)
    elif layout_profile == "turning":
        views = _plan_turning(fp, detail_level)
    else:
        views = _plan_milling(fp, detail_level)

    # Remove dimensions above requested detail level
    for view in views:
        view.dimensions = [d for d in view.dimensions if d.detail_level <= detail_level]

    views = _apply_dimension_policies(views, policy_hints)
    views = _deduplicate(views)

    process_notes = _collect_process_notes(fp, layout_profile, unfold_result, detail_level)
    process_notes = [n for n in process_notes if n.detail_level <= detail_level]

    plan = DimensionPlan(
        part_type=layout_profile,
        detail_level=detail_level,
        datum_system=datum_system,
        views=views,
        process_notes=process_notes,
        policy_hints=policy_hints,
    )
    if layout_profile == "milling":
        plan.milling_subtype = classify_milling_subtype(fp)

    if overrides:
        plan = apply_overrides(plan, overrides)

    return plan

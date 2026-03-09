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


def _action_rule_map(kb: dict, feature: str, context: dict) -> Dict[str, str]:
    """Return {action_dimension_key -> rule_id} for the given feature+context.

    Only approved rules are considered (select_applicable_rules filters drafts).
    Used to populate DimensionItem.rule_id with traceability back to ISO norms.
    """
    mapping: Dict[str, str] = {}
    for rule in select_applicable_rules(kb, feature=feature, context=context):
        for action in rule.get("actions", []):
            key = action.get("dimension") or action.get("parameter") or action.get("type")
            if key and key not in mapping:
                mapping[key] = rule["id"]
    return mapping


def _bbox_dims(fp: dict) -> Dict[str, float]:
    """Extract X/Y/Z dimensions from feature payload bbox_mm."""
    bbox = fp.get("bbox_mm") or {}
    return {
        "X": float(bbox.get("X", 0)),
        "Y": float(bbox.get("Y", 0)),
        "Z": float(bbox.get("Z", 0)),
    }


# ---------------------------------------------------------------------------
# Layout profile (pure-python, no FreeCAD dependency)
# ---------------------------------------------------------------------------


def select_layout_profile_standalone(
    input_path: str,
    fp: dict,
) -> str:
    """Classify part as 'milling' or 'sheet_metal' without FreeCAD.

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
    cone_count_t3 = int(fp.get("cone_face_count") or 0)
    if cone_count_t3 == 0:
        thickness_axis = str(fp.get("thickness_axis") or "").upper()
        thickness = dims.get(thickness_axis, min(dims.values()))
        sorted_dims = sorted(dims.values(), reverse=True)
        mid_dim = sorted_dims[1] if len(sorted_dims) > 1 else 1.0
        if mid_dim > 0 and thickness / mid_dim < 0.15:
            return "sheet_metal"

    return "milling"


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

    # Knowledge-base rule lookups — runtime traceability for rule_id fields
    hole_count = int(fp.get("hole_count") or 0)
    thread_label = fp.get("thread_label")
    kb = _get_kb()
    outer_map   = _action_rule_map(kb, "outer_contour", {"view_kind": "orthographic"})
    hole_map    = _action_rule_map(kb, "hole", {"visible": True})
    pattern_map = _action_rule_map(kb, "hole_pattern", {"count": hole_count})
    thread_map  = _action_rule_map(kb, "thread", {}) if thread_label else {}
    outer_rule  = outer_map.get("overall_length") or outer_map.get("overall_height")

    front_dims: List[DimensionItem] = [
        _dim("overall_length", "Front", axis="H", value_mm=longest_val,
             rule_id=outer_rule),
        _dim("overall_height", "Front", axis="V", value_mm=mid_val,
             rule_id=outer_rule),
    ]

    top_dims: List[DimensionItem] = [
        _dim("overall_depth", "Top", axis="V", value_mm=shortest_val,
             rule_id=outer_rule),
    ]

    # Hole features
    hole_diameter = _opt_float(fp.get("hole_diameter_mm"))
    hole_pitch = _opt_float(fp.get("hole_pitch_mm"))
    hole_groups = fp.get("hole_groups") or []

    if hole_count > 0 and hole_diameter is not None:
        front_dims.append(
            _dim("hole_diameter", "Front", value_mm=hole_diameter,
                 label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}",
                 rule_id=hole_map.get("diameter"))
        )

    if hole_count >= 2 and hole_pitch is not None and hole_pitch > 0:
        front_dims.append(
            _dim("hole_pitch", "Front", axis="H", value_mm=hole_pitch,
                 rule_id=pattern_map.get("pitch_or_spacing"))
        )

    # Hole locations from datum (coordinate dimensioning)
    if hole_count >= 1 and hole_groups:
        front_dims.append(
            _dim("hole_location_x", "Front", axis="H",
                 rule_id=pattern_map.get("position_from_datums"))
        )
        front_dims.append(
            _dim("hole_location_y", "Front", axis="V",
                 rule_id=pattern_map.get("position_from_datums"))
        )

    if thread_label:
        front_dims.append(
            _dim("thread_callout", "Front",
                 label=f"{thread_label} GEWINDE",
                 rule_id=thread_map.get("thread_designation"))
        )

    # Detail level 2+: add depth dimensions on Left view
    left_dims: List[DimensionItem] = []
    if detail_level >= 2:
        left_dims.append(
            _dim("overall_depth", "Left", axis="H", value_mm=shortest_val,
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

    # Knowledge-base rule lookups — runtime traceability for rule_id fields
    hole_count_ctx = int(fp.get("hole_count") or 0)
    kb = _get_kb()
    outer_map   = _action_rule_map(kb, "outer_contour", {"view_kind": "orthographic"})
    hole_map    = _action_rule_map(kb, "hole", {"visible": True})
    pattern_map = _action_rule_map(kb, "hole_pattern", {"count": hole_count_ctx})
    outer_rule  = outer_map.get("overall_length") or outer_map.get("overall_height")

    # 3D folded views — always present
    front_dims: List[DimensionItem] = [
        _dim("overall_length", "Front", axis="H", value_mm=longest_val,
             rule_id=outer_rule),
        _dim("overall_height", "Front", axis="V", value_mm=mid_val,
             rule_id=outer_rule),
    ]

    top_dims: List[DimensionItem] = []

    # Flat pattern (Abwicklung) — primary dimensioning surface for sheet metal
    flat_dims: List[DimensionItem] = []
    has_unfold = isinstance(unfold_result, dict) and unfold_result.get("ok") is True
    if has_unfold:
        fl = _opt_float(unfold_result.get("flat_length_mm"))
        fw = _opt_float(unfold_result.get("flat_width_mm"))
        if fl is not None:
            flat_dims.append(
                _dim("flat_length", "FlatPattern", axis="H", value_mm=fl)
            )
        if fw is not None:
            flat_dims.append(
                _dim("flat_width", "FlatPattern", axis="V", value_mm=fw)
            )

        # Hole positions on flat pattern
        hole_count = int(fp.get("hole_count") or 0)
        if hole_count >= 1:
            hole_diameter = _opt_float(fp.get("hole_diameter_mm"))
            if hole_diameter is not None:
                flat_dims.append(
                    _dim("hole_diameter", "FlatPattern", value_mm=hole_diameter,
                         label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}",
                         rule_id=hole_map.get("diameter"))
                )
            if hole_count >= 2:
                flat_dims.append(
                    _dim("hole_location_x", "FlatPattern", axis="H",
                         rule_id=pattern_map.get("position_from_datums"))
                )
                flat_dims.append(
                    _dim("hole_location_y", "FlatPattern", axis="V",
                         rule_id=pattern_map.get("position_from_datums"))
                )

    # Bend radius — as reference on front view, not over-dimensioned
    bend_radius = _opt_float(fp.get("bend_radius_mm"))
    if bend_radius is not None and bend_radius > 0:
        front_dims.append(
            _dim("bend_radius", "Front", value_mm=bend_radius,
                 label=f"R{_fmt(bend_radius)}",
                 priority="should")
        )

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

    # Knowledge-base rule lookups — runtime traceability for rule_id fields
    kb = _get_kb()
    outer_map  = _action_rule_map(kb, "outer_contour", {"view_kind": "orthographic"})
    hole_map   = _action_rule_map(kb, "hole", {"visible": True})
    outer_rule = outer_map.get("overall_length") or outer_map.get("overall_height")

    front_dims: List[DimensionItem] = [
        _dim("overall_length", "Front", axis="H", value_mm=longest_val,
             rule_id=outer_rule),
        _dim("overall_height", "Front", axis="V", value_mm=mid_val,
             label=f"{_DIAMETER_SYMBOL}{_fmt(mid_val)}",
             rule_id=outer_rule),
    ]

    hole_diameter = _opt_float(fp.get("hole_diameter_mm"))
    if hole_diameter is not None:
        front_dims.append(
            _dim("hole_diameter", "Front", value_mm=hole_diameter,
                 label=f"{_DIAMETER_SYMBOL}{_fmt(hole_diameter)}",
                 rule_id=hole_map.get("diameter"))
        )

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

    views = _deduplicate(views)

    process_notes = _collect_process_notes(fp, layout_profile, unfold_result, detail_level)
    process_notes = [n for n in process_notes if n.detail_level <= detail_level]

    plan = DimensionPlan(
        part_type=layout_profile,
        detail_level=detail_level,
        datum_system=datum_system,
        views=views,
        process_notes=process_notes,
    )

    if overrides:
        plan = apply_overrides(plan, overrides)

    return plan

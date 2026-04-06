"""Pydantic data models for the Dimension Strategy Engine (DSE).

The DimensionPlan describes *what* to dimension (intents), not *how* to render.
step_to_pdf.py consumes the serialized plan as a plain dict.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class DatumSystem(BaseModel):
    """Implicit A/B/C datum system inferred from part geometry."""

    A: Optional[str] = None  # axis of largest planar face (clamping surface)
    B: Optional[str] = None  # axis of longest orthogonal extent
    C: Optional[str] = None  # third orthogonal axis


class DimensionItem(BaseModel):
    """A single dimension intent to be rendered on a specific view."""

    dim_type: Literal[
        "overall_length",
        "overall_height",
        "overall_depth",
        "hole_diameter",
        "hole_pitch",
        "hole_location_x",
        "hole_location_y",
        "thread_callout",
        "bend_radius",
        "sheet_thickness",
        "flat_length",
        "flat_width",
        "pocket_depth",
        "pocket_location",
        "step_height",
        "chamfer",
        "angle",
        "diagonal",
        "slot_width",
        "slot_length",
        "slot_location",
        "feature_count",
        "total_span",
    ]
    target_view: str  # "Front", "Top", "Left", "FlatPattern"
    axis: Optional[Literal["H", "V", "D"]] = None  # horizontal, vertical, or diagonal
    angle_deg: Optional[float] = None  # angle in degrees for diagonal/chamfer dims
    value_mm: Optional[float] = None  # computed dimension value
    label: Optional[str] = None  # formatted label (e.g. "Ø14", "M6 GEWINDE", "2×45°")
    priority: Literal["must", "should"] = "must"
    rule_id: Optional[str] = None  # traceability to knowledge_base rule
    detail_level: int = Field(default=1, ge=1, le=3)


class ProcessNote(BaseModel):
    """Manufacturing process annotation (thickness, k-factor, etc.)."""

    note_type: Literal[
        "thickness",
        "inner_radius",
        "k_factor",
        "material",
        "tolerance",
        "edge_note",
        "surface_finish",
        "weld",
    ]
    text: str
    detail_level: int = Field(default=1, ge=1, le=3)


class GDTCallout(BaseModel):
    """A single GD&T feature control frame (ISO 1101)."""

    characteristic: Literal[
        "straightness",       # —
        "flatness",           # ▭
        "circularity",        # ○
        "cylindricity",       # ⌭
        "line_profile",       # ⌒
        "surface_profile",    # ⌓
        "perpendicularity",   # ⊥
        "angularity",         # ∠
        "parallelism",        # ∥
        "position",           # ⊕
        "concentricity",      # ◎
        "symmetry",           # ≡
        "circular_runout",    # ↗ (single arrow)
        "total_runout",       # ↗↗ (double arrow)
    ]
    tolerance_value: float  # in mm
    tolerance_modifier: Optional[Literal["M", "L", "S", "P"]] = None  # MMC, LMC, RFS, projected
    datum_refs: list[str] = []  # e.g. ["A", "B"] — ordered primary, secondary, tertiary
    target_view: str = "Front"
    target_feature: Optional[str] = None  # "hole_1", "face_top", etc.
    priority: Literal["must", "should"] = "should"
    detail_level: int = Field(default=2, ge=1, le=3)


class ViewPlan(BaseModel):
    """Dimension plan for a single drawing view."""

    view_name: str
    dimensions: list[DimensionItem] = []
    gdt_callouts: list[GDTCallout] = []
    show_centerlines: bool = True


class SectionViewPlan(BaseModel):
    """Plan for a section view (ISO 128-40)."""

    label: str = "A"  # "A" → rendered as "A-A"
    parent_view: str = "Front"  # which view the cutting line appears on
    cut_axis: Literal["H", "V"] = "V"  # H=horizontal cut, V=vertical cut
    cut_position_ratio: float = Field(default=0.5, ge=0.0, le=1.0)  # 0..1 along the axis
    reason: Optional[str] = None  # e.g. "hidden internal pocket"


class DetailViewPlan(BaseModel):
    """Plan for a detail view (ISO 128-40 detail circle)."""

    label: str = "Z"  # "Z" → rendered as "Detail Z"
    parent_view: str = "Front"
    center_ratio: tuple[float, float] = (0.5, 0.5)  # (x_ratio, y_ratio) on parent
    zoom_factor: float = Field(default=2.0, ge=1.5, le=10.0)
    radius_mm: float = 10.0  # circle radius on parent view
    reason: Optional[str] = None


class DimensionPlan(BaseModel):
    """Complete dimension plan for a part — the output of the DSE."""

    part_type: Literal["milling", "sheet_metal", "turning"]
    milling_subtype: Optional[Literal["plate_2p5d", "block_prismatic", "feature_dense"]] = None
    detail_level: int = Field(default=1, ge=1, le=3)
    datum_system: DatumSystem = Field(default_factory=DatumSystem)
    views: list[ViewPlan] = []
    section_views: list[SectionViewPlan] = []
    detail_views: list[DetailViewPlan] = []
    process_notes: list[ProcessNote] = []
    policy_hints: dict = Field(default_factory=dict)
    overrides_applied: list[dict] = []

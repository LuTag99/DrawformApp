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
        "flat_length",
        "flat_width",
        "pocket_depth",
        "pocket_location",
        "step_height",
    ]
    target_view: str  # "Front", "Top", "Left", "FlatPattern"
    axis: Optional[Literal["H", "V"]] = None  # horizontal or vertical
    value_mm: Optional[float] = None  # computed dimension value
    label: Optional[str] = None  # formatted label (e.g. "Ø14", "M6 GEWINDE")
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
    ]
    text: str
    detail_level: int = Field(default=1, ge=1, le=3)


class ViewPlan(BaseModel):
    """Dimension plan for a single drawing view."""

    view_name: str
    dimensions: list[DimensionItem] = []
    show_centerlines: bool = True


class DimensionPlan(BaseModel):
    """Complete dimension plan for a part — the output of the DSE."""

    part_type: Literal["milling", "sheet_metal", "turning"]
    detail_level: int = Field(default=1, ge=1, le=3)
    datum_system: DatumSystem = Field(default_factory=DatumSystem)
    views: list[ViewPlan] = []
    process_notes: list[ProcessNote] = []
    overrides_applied: list[dict] = []

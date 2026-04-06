"""Shared error taxonomy for Drawform.

The enums inherit from ``str`` so legacy string comparisons keep working.
"""

from __future__ import annotations

from enum import Enum


class DrawformErrorClass(str, Enum):
    DIMENSION_MISSING = "DIMENSION_MISSING"
    DIMENSION_REDUNDANT = "DIMENSION_REDUNDANT"
    DIMENSION_POOR_PLACEMENT = "DIMENSION_POOR_PLACEMENT"
    HOLE_PATTERN_UNCLEAR = "HOLE_PATTERN_UNCLEAR"
    VIEW_SELECTION_ERROR = "VIEW_SELECTION_ERROR"
    PROJECTION_INCONSISTENT = "PROJECTION_INCONSISTENT"
    TITLEBLOCK_INCOMPLETE = "TITLEBLOCK_INCOMPLETE"
    SHOWSTOPPER = "SHOWSTOPPER"


class DrawformSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    MAJOR = "MAJOR"
    SHOWSTOPPER = "SHOWSTOPPER"

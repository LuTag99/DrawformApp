"""Structured failure classification for the drawing pipeline.

Each failure class encodes:
- A severity (BLOCKER, WARNING, INFO)
- A category (LAYOUT, DIMENSION, FEATURE, RENDERING, QUALITY)
- A machine-readable code for programmatic handling
- A human-readable message template

Used by: evaluate_pre_export_quality(), quality gate, orchestrator, report.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional


class Severity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


class Category(str, Enum):
    LAYOUT = "LAYOUT"
    DIMENSION = "DIMENSION"
    FEATURE = "FEATURE"
    RENDERING = "RENDERING"
    QUALITY = "QUALITY"


class FailureClass:
    """A structured failure with severity, category, code, and message."""

    __slots__ = ("severity", "category", "code", "message", "details")

    def __init__(
        self,
        severity: Severity,
        category: Category,
        code: str,
        message: str,
        details: Optional[str] = None,
    ):
        self.severity = severity
        self.category = category
        self.code = code
        self.message = message
        self.details = details

    def __repr__(self) -> str:
        return f"FailureClass({self.severity.value}/{self.category.value}: {self.code} — {self.message})"

    def to_dict(self) -> dict:
        d = {
            "severity": self.severity.value,
            "category": self.category.value,
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            d["details"] = self.details
        return d

    @property
    def is_blocker(self) -> bool:
        return self.severity == Severity.BLOCKER


# ---------------------------------------------------------------------------
# Pre-defined failure classes (use these instead of free-text strings)
# ---------------------------------------------------------------------------

# LAYOUT failures
LABEL_OUT_OF_BOUNDS = lambda views: FailureClass(
    Severity.BLOCKER, Category.LAYOUT, "LABEL_OUT_OF_BOUNDS",
    f"Masszahlen liegen ausserhalb des Zeichenfelds in: {', '.join(views)}",
)
DIMENSION_OUT_OF_BOUNDS = lambda views: FailureClass(
    Severity.BLOCKER, Category.LAYOUT, "DIMENSION_OUT_OF_BOUNDS",
    f"Masslinien oder Massgrafik liegen ausserhalb des Zeichenfelds in: {', '.join(views)}",
)
VIEW_OVERLAP = lambda pairs: FailureClass(
    Severity.BLOCKER, Category.LAYOUT, "VIEW_OVERLAP",
    f"Ansichten ueberlagern sich: {', '.join(pairs)}",
)
TITLE_BLOCK_OVERLAP = lambda count: FailureClass(
    Severity.BLOCKER, Category.LAYOUT, "TITLE_BLOCK_OVERLAP",
    f"Masse ueberlagern das Schriftfeld ({count} Texte).",
)
TEXT_OVERLAP = lambda views: FailureClass(
    Severity.BLOCKER, Category.DIMENSION, "TEXT_OVERLAP",
    f"Masszahlen ueberlagern sich innerhalb einer Ansicht in: {', '.join(views)}",
)

# DIMENSION failures
MISSING_OVERALL_DIMS = FailureClass(
    Severity.WARNING, Category.DIMENSION, "MISSING_OVERALL_DIMS",
    "Fehlende Aussenmasse: weniger als zwei Gesamtmasswerte gefunden.",
)
MISSING_HOLE_CALLOUT = FailureClass(
    Severity.WARNING, Category.DIMENSION, "MISSING_HOLE_CALLOUT",
    "Fehlende Lochdurchmesserangabe (\u00d8).",
)
MISSING_CENTERLINES = FailureClass(
    Severity.WARNING, Category.DIMENSION, "MISSING_CENTERLINES",
    "Keine Mittellinien bei vorhandenen Bohrungen erkannt.",
)
DUPLICATE_DIMENSIONS = lambda texts: FailureClass(
    Severity.WARNING, Category.DIMENSION, "DUPLICATE_DIMENSIONS",
    f"Doppelte Masse erkannt: {', '.join(sorted(texts)[:4])}",
)

# FEATURE failures
GEOM_OVERLAP_OVERALL = lambda views: FailureClass(
    Severity.BLOCKER, Category.DIMENSION, "GEOM_OVERLAP_OVERALL",
    f"Gesamtmasse liegen zu nah an der Geometrie in: {', '.join(views)}",
)
GEOM_OVERLAP_FEATURE = lambda views: FailureClass(
    Severity.BLOCKER, Category.DIMENSION, "GEOM_OVERLAP_FEATURE",
    f"Featuremasse kollidieren mit der Teilgeometrie in: {', '.join(views)}",
)
FEATURE_OVERALL_OVERLAP = lambda views: FailureClass(
    Severity.BLOCKER, Category.DIMENSION, "FEATURE_OVERALL_OVERLAP",
    f"Feature- und Gesamtmasse ueberlagern sich in: {', '.join(views)}",
)

# RENDERING failures
FALLBACK_PROJECTION = FailureClass(
    Severity.BLOCKER, Category.RENDERING, "FALLBACK_PROJECTION",
    "Abwicklung nicht verfuegbar: Unfold fehlgeschlagen, keine echte Entfaltung vorhanden.",
)
INVALID_BEND_LEGEND = FailureClass(
    Severity.WARNING, Category.RENDERING, "INVALID_BEND_LEGEND",
    "Unzulaessige Biegehinweise in der Abwicklung erkannt.",
)
FREECAD_CRASH = lambda detail: FailureClass(
    Severity.BLOCKER, Category.RENDERING, "FREECAD_CRASH",
    "FreeCAD-Subprozess abgestuerzt (Stack Overflow / Access Violation).",
    details=detail,
)
FREECAD_TIMEOUT = lambda timeout_s: FailureClass(
    Severity.BLOCKER, Category.RENDERING, "FREECAD_TIMEOUT",
    f"FreeCAD-Subprozess hat das Zeitlimit ueberschritten ({timeout_s}s).",
)
FREECAD_EXIT_ERROR = lambda exit_code, detail: FailureClass(
    Severity.BLOCKER, Category.RENDERING, "FREECAD_EXIT_ERROR",
    f"FreeCAD-Subprozess fehlgeschlagen (Exit {exit_code}).",
    details=detail,
)

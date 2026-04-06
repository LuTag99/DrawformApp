# Drawform Error Taxonomy

Stand: 2026-04-04

## Zweck

Dieses Dokument beschreibt die gemeinsame Fehlerklassen- und Severity-Taxonomie
fuer Drawform.

Ziel:

- dieselben Fehlerklassen in Leitlinien, Quality Checks und Reports verwenden
- Python-seitig eine importierbare Quelle der Wahrheit haben
- rueckwaertskompatibel zu bestehenden String-Vergleichen bleiben

## Python-Quelle

Die kanonische Python-Definition liegt in:

- `server/rules/error_classes.py`

Die Enums erben von `str, Enum`.
Dadurch bleiben bestehende String-Vergleiche kompatibel.

## Fehlerklassen

- `DIMENSION_MISSING`
- `DIMENSION_REDUNDANT`
- `DIMENSION_POOR_PLACEMENT`
- `HOLE_PATTERN_UNCLEAR`
- `VIEW_SELECTION_ERROR`
- `PROJECTION_INCONSISTENT`
- `TITLEBLOCK_INCOMPLETE`
- `SHOWSTOPPER`

## Severity-Stufen

- `INFO`
- `WARNING`
- `MAJOR`
- `SHOWSTOPPER`

## v1-Regel

- neue Regeln und Reports sollen bevorzugt diese Taxonomie referenzieren
- bestehende String-basierte Issues muessen nicht migriert werden
- die Enum-Schicht ist additiv und darf bestehende Pipelines nicht brechen

# Drawform Local Backend (STEP -> PDF)

This service converts STEP files into DIN/ISO-style manufacturing drawings (PDF) using FreeCAD.

## Requirements

- FreeCAD 1.0+ installed
- Python 3.10+ for FastAPI

## Setup (Windows)

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Set the FreeCAD Python path (adjust the version as needed):

```powershell
setx FREECAD_PYTHON "C:\Program Files\FreeCAD 1.0\bin\python.exe"
```

## Run

```powershell
uvicorn main:app --reload --port 8000
```

## Health check

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

## Debug SVG (wenn PDF leer ist)

Das Backend schreibt eine Debug-SVG nach `server/_debug`.
Oeffne die Datei im Browser, um zu sehen, ob die Ansichten gerendert wurden.

## Docker (empfohlen)

```powershell
# im Repo-Root
docker compose up --build
```

Der Service laeuft danach auf `http://localhost:8000`.

## Export

```powershell
curl -F "file=@C:\path\model.step" -F "format=pdf" http://localhost:8000/api/export -o drawing.pdf
```

Alle optionalen Parameter (werden validiert):

```powershell
curl -F "file=@C:\path\model.step" -F "format=pdf" `
  -F "scale=1:2" `
  -F "projection=1. Winkel (DIN EN ISO 5456-2)" `
  -F "standard=DIN EN ISO 128/129-1" `
  -F "general_tolerance=DIN ISO 2768-mK" `
  -F "unit=mm" `
  -F "sheet=auto" `
  -F "k_factor=0.33" `
  -F "detail_level=1" `
  -F "include_flat_pattern=1" `
  http://localhost:8000/api/export -o drawing.pdf
```

**`include_flat_pattern`** (Default: `1` = aktiviert):
- `1` — Abwicklung (Flat Pattern) wird erzeugt und auf dem Blatt dargestellt (nur bei Blechteilen)
- `0` — Unfold-Subprozess wird uebersprungen; das Blatt zeigt keine Abwicklungs-Column

**`k_factor`** (0.1–0.8, optional):
- Neutralfaserlagenkoeffizient fuer Abwicklungsberechnung
- Richtwerte: Baustahl/St37 ≈ 0.33, Edelstahl/V2A ≈ 0.36, Aluminium ≈ 0.31
- Wenn nicht gesetzt, verwendet der Shop seinen Standard-K-Faktor

**`detail_level`** (1–3, Default: 1):
- `1` Manufacturing-minimal: L × B × H + Loecher + Biegeradius
- `2` Inspection-ready: + Tiefen, Bezugsmasze, Left-View
- `3` Customer-spec: + alle Prozessnotizen

**`general_tolerance`** — erlaubte Werte:
- `DIN ISO 2768-fH`, `DIN ISO 2768-mK` (Standard), `DIN ISO 2768-cL`
- `ISO 22081 (allgemein)` — neuere Alternative zu DIN ISO 2768-2

## Testing

Fast gate (complete Python unittest suite):

```powershell
cd server
.venv\Scripts\python.exe -m unittest discover
```

DSE unit tests (Dimension Strategy Engine):

```powershell
cd server
.venv\Scripts\python.exe -m pytest tests/test_dimension_strategy.py -v
# 64 Tests: milling, sheet_metal, turning, slots, KB-Traceability
```

View regression tests against golden baseline:

```powershell
cd server
.venv\Scripts\python.exe test_views.py --sample-set baseline          # 20 baseline parts
.venv\Scripts\python.exe test_views.py --sample-set real_priority     # curated real-priority gate
.venv\Scripts\python.exe test_views.py --sample-set real              # 91 real customer parts
.venv\Scripts\python.exe test_views.py --sample-set all               # all 111 parts
.venv\Scripts\python.exe test_views.py --sample-set baseline --parallel 4
```

Reference-learning gate for curated real parts:

```powershell
cd server
.venv\Scripts\python.exe reference_learning_gate.py --priority-only
```

Create/update golden baseline (after intentional layout changes):

```powershell
cd server
.venv\Scripts\python.exe test_views.py --sample-set all --update-golden
```

Run full local quality gate:

```powershell
cd server
.venv\Scripts\python.exe run_quality_gate.py --mode fast
.venv\Scripts\python.exe run_quality_gate.py --mode full --stability-runs 2
```

`--mode fast` runs the Python unit/integration suite without view rendering.
`--mode full` adds baseline regression, curated `real_priority` regression, the reference-learning gate, and checklist generation.

## Dimension Strategy Engine (DSE)

The DSE is a deterministic, knowledge-base-driven rule engine that decides **what** to dimension on a drawing before the FreeCAD subprocess runs.

**Pipeline position:**

```
main.py
  └─ run_feature_probe()                  → feature_payload (bbox, holes, threads, chamfers, slots)
  └─ select_layout_profile_standalone()   → "milling" | "sheet_metal" | "turning"
  └─ build_dimension_plan()               → DimensionPlan (JSON)
        └─ _plan_milling()    — KB-driven: overall dims, holes, threads, slots
        └─ _plan_sheet_metal() — KB-driven: folded dims, flat pattern, bend radius, thickness
        └─ _plan_turning()    — KB-driven: overall dims, Ø-label, hole diameters
  └─ write meta.json (features + dimension_plan + include_flat_pattern)
  └─ FreeCAD subprocess (step_to_pdf.py)
        └─ reads dimension_plan from meta → plan-driven rendering
        └─ reads include_flat_pattern → skips unfold subprocess if false
        └─ fallback: hardcoded logic if no plan present
```

**Key files:**

| File | Purpose |
|------|---------|
| `rules/dimension_plan_schema.py` | Pydantic models: `DimensionPlan`, `ViewPlan`, `DimensionItem`, `ProcessNote`, `GDTCallout` |
| `rules/dimension_strategy.py` | `build_dimension_plan()`, `_kb_wants_dimension()`, `select_layout_profile_standalone()`, `apply_overrides()` |
| `tests/test_dimension_strategy.py` | 64 unit tests |

**LLM-Overrides** — structured JSON on top of the deterministic baseline:

```python
from rules.dimension_strategy import apply_overrides
plan = apply_overrides(plan, [
    {"action": "add",    "target_view": "Front", "dimension": {"dim_type": "pocket_depth", "value_mm": 5.0}},
    {"action": "remove", "target_view": "Front", "dim_type": "hole_pitch"},
])
```

Every override is logged in `plan.overrides_applied` for auditability.

## Knowledge Base & Rule Engine

Rules in `knowledge_base.json` (v0.2.1 — 21 sources, 50 rules):

```powershell
cd server
.venv\Scripts\python.exe rules/rule_engine.py --validate
.venv\Scripts\python.exe rules/rule_engine.py --feature hole --ctx visible=true
.venv\Scripts\python.exe rules/rule_engine.py --feature sheet_metal --ctx has_real_bends=true
```

Knowledge data and quality process:
- Data file: `server/knowledge/knowledge_base.json`
- Quality guide: `server/knowledge/QUALITY_GUIDE.md`
- Rule engine: `server/rules/rule_engine.py`
- DSE: `server/rules/dimension_strategy.py`

Key rule categories: outer_contour, hole, hole_pattern, thread, slot, sheet_metal, turning, critical_feature, surface, title_block, weld_joint, global

## Blechteil-Klassifizierung

Ein Teil wird als `sheet_metal` klassifiziert wenn:
1. Wanddicke ≤ 10 mm
2. ≥ 60 % Planflaechen
3. Optional: Biegungen detektiert (bend_count > 0)

Teile mit > 8 mm Mindestausdehnung → immer `milling`. Koaxiale Mehrdurchmesser-Zylinder → `turning`.

**Zwei synchrone Codepfade** (muessen identisch gehalten werden):
- `rules/dimension_strategy.py:select_layout_profile_standalone()` — Python/main.py
- `freecad/step_to_pdf.py:_legacy_select_layout_profile()` — FreeCAD-Subprozess

## Notes

- Views: Front / Top / Left / Iso + Abwicklung-Column fuer Biegeteile (wenn `include_flat_pattern=1`)
- Abwicklung: XMin=YMin=0 normalisiert, Biegelinien in outline_svg eingebettet
- Durchmessersymbol: `Ø` (U+00D8) — NICHT `⌀` (U+2300, rendert als ■ in FreeCAD PDF-Fonts)
- Standardtoleranz: `DIN ISO 2768-mK` (ISO 2768-2 ist withdrawn; Nachfolger ISO 22081:2021)
- K-Faktor Default im Shop: 0.33–0.40 je nach Maschineneinstellung
- Norm-Baseline fuer DE/AT Technische Zeichnungen: `server/docs/DIN_ISO_BASELINE_TECHNISCHE_ZEICHNUNG.md`

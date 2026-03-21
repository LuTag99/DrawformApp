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

Norm profile parameters (optional, validated):

```powershell
curl -F "file=@C:\path\model.step" -F "format=pdf" `
  -F "scale=1:2" `
  -F "projection=1. Winkel (DIN EN ISO 5456-2)" `
  -F "standard=DIN EN ISO 128/129-1" `
  -F "general_tolerance=DIN ISO 2768-mK" `
  -F "unit=mm" `
  -F "sheet=auto" `
  http://localhost:8000/api/export -o drawing.pdf
```

## Testing

Unit tests (norm profile, sample catalog, API endpoints):

```powershell
cd server
python -m unittest test_norm_profile
python -m unittest test_sample_catalog
python -m unittest test_api_endpoints
```

DSE unit tests (Dimension Strategy Engine):

```powershell
cd server
python -m unittest tests.test_dimension_strategy -v
```

View regression tests against golden baseline:

```powershell
cd server
python test_views.py --sample-set baseline          # 20 baseline parts
python test_views.py --sample-set real              # real customer parts
python test_views.py --sample-set all               # all 48 parts
```

Create/update golden baseline (after intentional layout changes):

```powershell
cd server
python test_views.py --sample-set all --update-golden
```

View stability loop (repeat marked samples N times, check drift):

```powershell
cd server
python test_views.py --sample-set baseline --stability-runs 3
```

Run full local quality gate (self-check loop):

```powershell
cd server
python run_quality_gate.py --mode fast
python run_quality_gate.py --mode full --stability-runs 2
python run_quality_gate.py --mode full --stability-runs 2 --iterations 2
```

`run_quality_gate.py` uses `server/.venv/Scripts/python.exe` automatically when available.
`--mode fast` runs the Python unit/integration suite without view rendering.
`--mode full` adds baseline view regression, stability loop, and checklist generation.

## Dimension Strategy Engine (DSE)

The DSE is a deterministic rule engine that decides **what** to dimension on a drawing before the FreeCAD subprocess runs.

**Pipeline position:**

```
main.py
  └─ run_feature_probe()          → feature_payload (FreeCAD subprocess)
  └─ select_layout_profile_standalone()  → "milling" | "sheet_metal"
  └─ build_dimension_plan()       → DimensionPlan (JSON)
  └─ write meta.json (features + dimension_plan)
  └─ FreeCAD subprocess (step_to_pdf.py)
        └─ reads dimension_plan from meta → plan-driven rendering
        └─ fallback: hardcoded logic if no plan present
```

**Key files:**

| File | Purpose |
|------|---------|
| `rules/dimension_plan_schema.py` | Pydantic models: `DimensionPlan`, `ViewPlan`, `DimensionItem`, `ProcessNote` |
| `rules/dimension_strategy.py` | `build_dimension_plan()`, `select_layout_profile_standalone()`, `apply_overrides()` |
| `tests/test_dimension_strategy.py` | 35 unit tests |

**Detail levels** — pass `detail_level=1|2|3` in export metadata:
- `1` Manufacturing-minimal (default): L × B × H + Löcher + Biegeradius
- `2` Inspection-ready: + Tiefen, Bezugsmaße, Left-view
- `3` Customer-spec: + alle Prozessnotizen

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

Rules that inform the DSE live in `knowledge_base.json`:

```powershell
cd server
python knowledge/validate_knowledge_base.py
python rules/rule_engine.py --feature hole --ctx visible=true
python rules/rule_engine.py --validate
```

Knowledge data and quality process:
- Data file: `server/knowledge/knowledge_base.json`
- Quality guide: `server/knowledge/QUALITY_GUIDE.md`
- Rule engine: `server/rules/rule_engine.py`
- DSE: `server/rules/dimension_strategy.py`

## Analyzer (Feature-Erkennung)

```powershell
curl -F "file=@C:\path\model.step" -F "units=mm" -F "scale=1" http://localhost:8000/api/analyze
```

`/api/analyze` supports backend jobs (pending/processing/completed/failed).

Generate complex regression samples (5 feature-rich parts):

```powershell
& "C:\Program Files\FreeCAD 1.0\bin\python.exe" server\freecad\generate_complex_reference_parts.py
```

## Notes

- The export layout supports `sheet=auto|A3|A2`; `auto` starts with A3 and promotes to A2 for large/low-scale parts.
- Views: Front / Top / Left / Iso + Abwicklung column for Biegeteile.
- The drawing includes an ISO 7200 title block, overall dimensions, and feature callouts.
- Flat pattern (Abwicklung) coordinate system: XMin=YMin=0, bend lines embedded in outline SVG.
- Diameter symbol: `Ø` (U+00D8) — NOT `⌀` (U+2300, renders as ■ in FreeCAD PDF fonts).
- Default tolerance: `DIN ISO 2768-mK`.
- Norm baseline for DE/AT technical drawings: `server/docs/DIN_ISO_BASELINE_TECHNISCHE_ZEICHNUNG.md`.
- For CAD files (`.step/.stp/.iges/.igs`) a FreeCAD feature probe derives dimensions, hole/bend hints, and feeds the DSE.

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

## Auth-Modi

Die geschuetzten Endpunkte (`/api/export`, `/api/analyze`,
`/api/reconstruct`, `/api/ai-insight`) kennen genau zwei Modi. Welcher Modus
aktiv ist, entscheidet `DRAWFORM_REQUIRE_FIREBASE_AUTH`:

- **Produktion / Standardentwicklung** — `DRAWFORM_REQUIRE_FIREBASE_AUTH=1`
  (Default). Jeder Aufruf braucht einen
  `Authorization: Bearer <Firebase ID Token>`-Header. Das Backend verifiziert
  den Token via Firebase Admin SDK; ohne gueltiges Service-Account-Setup
  liefert das Backend `503 Firebase Admin SDK ist nicht initialisiert`.

  ```powershell
  $token = "<Firebase ID Token>"
  curl -X POST http://localhost:8000/api/export `
       -H "Authorization: Bearer $token" `
       -F "file=@bauteil.step" -F "format=pdf" -o drawing.pdf
  ```

- **Lokaler Dev/Test ohne Firebase Auth** — `DRAWFORM_REQUIRE_FIREBASE_AUTH=0`.
  Authentifizierung wird komplett deaktiviert; statt 503 haengt das Backend
  einen stabilen Stub-User ein
  (`uid=local-dev`, `email=dev@drawform.local`, ueberschreibbar via
  `DRAWFORM_LOCAL_DEV_UID` / `DRAWFORM_LOCAL_DEV_EMAIL`). Aufrufe gehen ohne
  Token durch. Dieser Modus ist ausschliesslich fuer lokale Entwicklung und
  Tests gedacht und darf in Produktion **nicht** gesetzt sein.

  ```powershell
  $env:DRAWFORM_REQUIRE_FIREBASE_AUTH="0"
  uvicorn main:app --reload --port 8000
  curl -X POST http://localhost:8000/api/ai-insight `
       -H "Content-Type: application/json" `
       -d '{"statusSummary":"Fast gate ok"}'
  ```

Der Auth-Vertrag wird durch `server/test_api_endpoints.py::AuthContractTests`
abgesichert (Stub-User-Modus + 401 ohne Token im strict-Modus).

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

Die folgenden Beispiele gelten fuer den Default-Modus
`DRAWFORM_REQUIRE_FIREBASE_AUTH=1`. Im lokalen Dev-Modus mit
`DRAWFORM_REQUIRE_FIREBASE_AUTH=0` kann der Header bewusst weggelassen werden.

```powershell
$token = "<Firebase ID Token>"
curl -X POST http://localhost:8000/api/export `
  -H "Authorization: Bearer $token" `
  -F "file=@C:\path\model.step" `
  -F "format=pdf" `
  -o drawing.pdf
```

Alle optionalen Parameter (werden validiert):

```powershell
$token = "<Firebase ID Token>"
curl -X POST http://localhost:8000/api/export `
  -H "Authorization: Bearer $token" `
  -F "file=@C:\path\model.step" `
  -F "format=pdf" `
  -F "scale=1:2" `
  -F "projection=1. Winkel (DIN EN ISO 5456-2)" `
  -F "standard=DIN EN ISO 128/129-1" `
  -F "general_tolerance=DIN ISO 2768-mK" `
  -F "unit=mm" `
  -F "sheet=auto" `
  -F "k_factor=0.33" `
  -F "detail_level=1" `
  -F "include_flat_pattern=1" `
  -o drawing.pdf
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
# DSE unit tests: milling, sheet_metal, turning, slots, KB traceability
```

View regression tests against golden baseline:

```powershell
cd server
.venv\Scripts\python.exe test_views.py --sample-set baseline
.venv\Scripts\python.exe test_views.py --sample-set real20
.venv\Scripts\python.exe test_views.py --sample-set real_priority
.venv\Scripts\python.exe test_views.py --sample-set real
.venv\Scripts\python.exe test_views.py --sample-set all
.venv\Scripts\python.exe test_views.py --sample-set baseline --parallel 4
.venv\Scripts\python.exe test_views.py --compare-reviews before_review.json after_review.json
```

If a task iteration produces fresh `*_preview.png` or `*_debug.svg` artifacts,
run the mandatory visual review handoff before treating the result as Critic-ready.
If the run is relevant for learning or release quality, follow with a knowledge-capture
decision and preserve the latest `visual_review` / `delta_review` artifacts.

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

Repository sync check:

```powershell
cd ..
python scripts/validate_repo_sync.py
```

Live status discipline:

- Do not trust hardcoded pass/fail counts in mirror docs.
- Use the commands above, CI in `.github/workflows/quality-gate.yml`, and the
  active `server/_debug/agent_runs/<run_id>/run_state.json`.
- See `REPO_SYNC_POLICY.md` for source ownership.

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
| `tests/test_dimension_strategy.py` | DSE unit tests |
| `sample_catalog.py` | Sample discovery: baseline (category subdirs), real, real_priority, all |
| `reference_learning_gate.py` | Real-part reference learning gate |
| `_golden/views_baseline.json` | Golden baseline |
| `_golden/views_real_priority.json` | Real-priority golden |

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

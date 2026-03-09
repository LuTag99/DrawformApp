# Copilot Instructions — DrawformApp

## Architecture

Two decoupled parts share one repo:

- **Frontend** (`src/`): React 19 + TypeScript SPA (Vite 7). Glassmorphism "iOS 26 Glass Look" UI. Routes: `/` (Dashboard), `/analyzer`, `/reconstruct`, `/projects`, `/export`, `/profile`, plus auth pages. Entry: `src/main.tsx` → `BrowserRouter` → `AuthProvider` → `App`.
- **Backend** (`server/`): FastAPI service. Key endpoints: `POST /api/export` (STEP → PDF), `POST /api/export-dxf` (STEP → DXF flat pattern), `POST /api/analyze` (CAD/image feature analysis), `POST /api/reconstruct` (5-photo → STL → STEP), `GET /api/logs/last`. Internally shells out to FreeCAD's Python for geometry processing via `subprocess.run`.

Vite proxies `/api` → `http://localhost:8000` in dev (`vite.config.ts`). In production the frontend is static files served alongside or behind a reverse proxy to the backend.

## Key Data Flows

1. **STEP → PDF Export**: `ExportPage` → `exportService.requestPdfExport()` → `POST /api/export` (multipart) → `main.py` → FreeCAD subprocess → returns `application/pdf`. Blob URL shown in iframe preview.
2. **STEP → DXF Export**: `ExportPage` → `exportService.requestDxfExport()` → `POST /api/export-dxf` → returns DXF flat pattern as `application/octet-stream`.
3. **AI Insights**: `DashboardPage` → `aiService.fetchAiInsight()` → OpenAI API (`gpt-4.1-mini`) directly from browser. Falls back to hardcoded German insights if `VITE_OPENAI_API_KEY` is missing. **Security note:** Key is bundled in the browser; use a server-side proxy for production.
4. **Analyzer Jobs**: `analyzerService.ts` manages jobs in `localStorage` with pub/sub (`subscribeToJobs`). On subscribe it calls `refreshJobsFromBackend()` → `GET /api/analyze` to sync with server. Uploads go to `POST /api/analyze`. Polling via `setInterval` every 1200ms. Falls back to a local worker simulation if the backend is unavailable.
5. **Reconstruct Jobs**: `reconstructService.ts` — `POST /api/reconstruct` (multipart: 5 photos + dimensions). Status polling via `GET /api/reconstruct/{id}` every 1500ms. Download via `GET /api/reconstruct/{id}/download?type=stl|step|pdf`.
6. **Auth**: Entirely `localStorage`-based (`AuthProvider` → `AuthContext`). Credentials (incl. password in cleartext) stored in `drawform-auth` key. Designed to be replaced with real OAuth/JWT later.

## Dev Commands

```powershell
npm run dev          # Vite dev server on :5173 (proxies /api → :8000)
npm run build        # tsc -b && vite build → dist/
npm run lint         # ESLint

# Backend (separate terminal)
cd server; .venv\Scripts\Activate.ps1
$env:FREECAD_PYTHON="C:\Program Files\FreeCAD 1.0\bin\python.exe"
uvicorn main:app --reload --port 8000

# Docker alternative (from repo root)
docker compose up --build
```

## Backend Testing

```powershell
cd server

# Unit tests
python -m unittest test_norm_profile
python -m unittest test_sample_catalog
python -m unittest test_api_endpoints
python -m unittest tests.test_dimension_strategy -v   # DSE: 35 tests

# View regression (golden baseline)
python test_views.py --sample-set baseline   # 20 baseline parts
python test_views.py --sample-set all        # all 48 parts (baseline + real)
python test_views.py --sample-set all --update-golden   # refresh baseline

# Quality gate
python run_quality_gate.py --stability-runs 2
```

Sample STEP files are in `server/_samples/` (baseline: `*.stp`; real: `Sheetmetals/`, `milling parts/`). Debug SVGs, PNG previews, and JSON reports go to `server/_debug/`.

## Conventions & Patterns

- **Language**: UI text, comments, and AI prompts are in **German**. Code identifiers and docs are English. Maintain this split.
- **Styling**: No CSS framework — custom CSS with CSS custom properties (`globals.css`). Use `--bg-card`, `--glass-border`, `--accent-primary`, `--gradient-accent`, etc. Apply `glass-panel` class for glassmorphism cards. Use `clsx` for conditional classnames.
- **Components**: Shared UI in `src/components/` (`GradientButton`, `InputField`, `SectionHeader`, `StatWidget`, `AiBackground`). Pages in `src/pages/<feature>/`. One component per file, named export matching filename.
- **State**: No Redux/Zustand. React Context for auth (`providers/AuthContext.ts` + `AuthProvider.tsx`), localStorage pub/sub for analyzer and reconstruct jobs, local `useState` elsewhere.
- **Services**: `src/services/` holds API clients. Each service is a plain module with exported async functions — no classes. `exportService` → FastAPI export endpoints; `aiService` → OpenAI; `analyzerService` → `/api/analyze` with localStorage cache and fallback; `reconstructService` → `/api/reconstruct`.
- **Icons**: `react-icons/hi2` (Heroicons v2 outline). Import individual icons, e.g. `HiOutlineArrowUpTray`.
- **Backend**: `server/main.py` is the FastAPI app. `server/freecad/step_to_pdf.py` runs inside FreeCAD's embedded Python (imports `FreeCAD`, `Part`, `TechDraw`). These are separate Python environments — don't mix dependencies.
- **Known frontend issues**: `<InputField>` label not linked to input via `htmlFor`/`id`; password stored in cleartext in localStorage; `VITE_OPENAI_API_KEY` is browser-visible. Fix before production.

## Environment Variables

| Variable | Where | Required | Purpose |
|---|---|---|---|
| `VITE_OPENAI_API_KEY` | Frontend `.env.local` | No | OpenAI dashboard insights |
| `FREECAD_PYTHON` | Backend shell | Yes | Path to FreeCAD's `python.exe` |
| `DRAWFORM_DEBUG_DIR` | Backend (set by `main.py`) | Auto | Debug SVG/log output dir |
| `DRAWFORM_META` | Backend (set by `main.py`) | Auto | Temp metadata JSON path |

## FreeCAD Pipeline (`server/freecad/step_to_pdf.py`)

This is the most complex file (~3600 lines). It runs inside FreeCAD's Python, not the venv. Key flow:
1. Read `DimensionPlan` from `meta["dimension_plan"]` (generated by DSE in `main.py`)
2. Load STEP → `Part.Shape`; compute bounding box, feature probe, layout profile
3. Generate 4 TechDraw views (Front, Top, Left, Iso) + optional Abwicklung column for Biegeteile
4. Render dimensions **from the plan** (plan-driven); falls back to hardcoded logic if no plan present
5. Assemble A3/A2 SVG with ISO 7200 title block from `server/templates/`
6. Convert SVG → PDF via `svglib` + `reportlab`

When modifying this file, test with `python test_views.py --sample-set all` and check output in `server/_debug/`.

## Dimension Strategy Engine (DSE)

The DSE runs in `main.py` **before** the FreeCAD subprocess and produces a `DimensionPlan` JSON that controls what gets dimensioned.

```
main.py → run_feature_probe() → select_layout_profile_standalone() → build_dimension_plan()
       → writes features + dimension_plan to meta.json
       → FreeCAD subprocess reads plan → plan-driven rendering
```

Key files: `server/rules/dimension_plan_schema.py`, `server/rules/dimension_strategy.py`.
LLM overrides: structured JSON (`add`/`remove`/`modify`), logged in `plan.overrides_applied`.
Detail levels: `1` = manufacturing-minimal, `2` = inspection-ready, `3` = customer-spec.

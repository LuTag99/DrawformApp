
# Copilot Instructions - DrawformApp

## Architecture

Two decoupled parts share one repo:

- Frontend (`src/`): React 19 + TypeScript SPA on Vite 7. Main routes are `/`, `/analyzer`, `/reconstruct`, `/projects`, `/export`, `/profile`, plus auth pages. Entry path: `src/main.tsx` -> `BrowserRouter` -> `AuthProvider` -> `App`.
- Backend (`server/`): FastAPI service in `server/main.py`. Primary endpoints are `/api/export`, `/api/export-dxf`, `/api/analyze`, `/api/reconstruct`, `/api/health`, `/api/ai-insight`, and `/api/logs/last`. Geometry work is delegated to FreeCAD subprocess scripts in `server/freecad/`.

Vite proxies `/api` to `http://localhost:8000` in dev via `vite.config.ts`.

## Working Contract

- Read `AGENTS.md` first for path selection and quality gates.
- Use `FAST-PATH` only for changes without meaningful drawing-quality or benchmark impact.
- Use `MEDIUM-PATH` for predictable output changes (title block, labels, annotations).
- Use `FULL-PATH` for drawing logic, heuristics, scoring, benchmark behavior, and agent workflow changes.
- Use `LONG-RUN` when the work must be stable across repeated runs or is release-facing.
- From `FULL-PATH` onward, keep a shared `RUN CONTEXT` with one `run_id`, exact commands, and artifacts under `server/_debug/agent_runs/<run_id>/`.

## Current Status (2026-03-26)

- `server/sample_catalog.py` resolves `20` baseline, `91` real, `111` total samples.
- `server/freecad/step_to_pdf.py` is ~9100 lines and remains the highest-risk hotspot.
- DSE Unit Tests: `46/46` passed.
- Baseline Regression: `20/20` passed (golden regenerated 2026-03-22).
- All-Samples: `~105/111` (6 known failures).
- AI insights use backend proxy `POST /api/ai-insight` — no API keys in browser.

## Key Data Flows

1. STEP -> PDF export: `ExportPage` -> `exportService.requestPdfExport()` -> `POST /api/export` -> `server/main.py` -> feature probe + DSE -> FreeCAD renderer `server/freecad/step_to_pdf.py` -> PDF response.
2. STEP -> DXF export: `ExportPage` -> `exportService.requestDxfExport()` -> `POST /api/export-dxf`.
3. Analyzer jobs: `analyzerService.ts` persists jobs in `localStorage`, syncs from `GET /api/analyze`, uploads to `POST /api/analyze`, polls `GET /api/analyze/{job_id}`, and falls back to a local worker simulation if the backend is unavailable.
4. Reconstruction jobs: `reconstructService.ts` posts 5 photos to `POST /api/reconstruct`, polls `GET /api/reconstruct/{job_id}`, and downloads via `GET /api/reconstruct/{job_id}/download`.
5. AI insights: `aiService.ts` calls backend proxy `POST /api/ai-insight` (no browser-side API key).
6. Auth: `AuthProvider.tsx` keeps credentials and session state in `localStorage` (not production-safe).

## Important Files

- `server/main.py`: FastAPI app, validation, DSE orchestration, subprocess control
- `server/freecad/step_to_pdf.py`: main drawing renderer (~9100 lines), normative annotations (GD&T, Section, Detail, Surface, Weld)
- `server/freecad/step_feature_probe.py`: geometry feature extraction (holes, threads, chamfers, sheet metal indicators)
- `server/freecad/step_unfold.py`: sheet-metal unfold subprocess
- `server/rules/dimension_strategy.py`: `select_layout_profile_standalone()`, `build_dimension_plan()`, `apply_overrides()`
- `server/rules/dimension_plan_schema.py`: Pydantic models (DimensionPlan, GDTCallout, SectionViewPlan, DetailViewPlan)
- `server/test_views.py`: view regression, drawing-quality checks, `--parallel N` flag
- `server/tests/test_dimension_strategy.py`: 46 DSE unit tests
- `server/_golden/views_baseline.json`: golden baseline (20 parts)
- `server/sample_catalog.py`: sample sets (baseline=20, real=91, all=111)
- `server/run_quality_gate.py`: unit + regression + stability runner
- `src/services/exportService.ts`: PDF and DXF requests
- `src/services/analyzerService.ts`: backend-backed analyzer store with local fallback
- `src/services/reconstructService.ts`: reconstruction polling/download flow
- `src/services/aiService.ts`: AI insights via backend proxy
- `src/providers/AuthProvider.tsx`: local auth stub

## Dev Commands

```powershell
npm run dev
npm run build
npm run lint

cd server
.venv\Scripts\python.exe -m unittest discover
.venv\Scripts\python.exe -m unittest tests.test_dimension_strategy
.venv\Scripts\python.exe -m unittest test_sample_catalog
.venv\Scripts\python.exe -m unittest test_norm_profile.py
.venv\Scripts\python.exe -m unittest test_api_endpoints.py
.venv\Scripts\python.exe test_views.py --sample-set baseline
.venv\Scripts\python.exe test_views.py --sample-set baseline --single complex_bracket
.venv\Scripts\python.exe test_views.py --sample-set baseline --parallel 4
.venv\Scripts\python.exe test_views.py --sample-set all
.venv\Scripts\python.exe run_quality_gate.py --mode fast
.venv\Scripts\python.exe run_quality_gate.py --iterations 1 --stability-runs 2
```

Prefer the project `.venv` for backend commands.

## Working Rules

- UI copy is German. Keep code identifiers and most technical docs in English.
- For drawing-quality work, inspect `server/_debug/*_debug.svg`, `*_preview.png`, and `*_report.json` before claiming success.
- For `FULL-PATH` and `LONG-RUN`, also persist the latest artifacts and a `run_state.json` under `server/_debug/agent_runs/<run_id>/`.
- Do not describe the analyzer as "local-only". It has a real backend path plus a local fallback.
- Do not claim the current view baseline is green unless you have rerun it.
- Treat `step_to_pdf.py` edits as high-risk. Re-run at least a targeted `test_views.py` case after touching it.
- Auth credentials are stored in `localStorage` — this is a known MVP shortcut, not production-safe.

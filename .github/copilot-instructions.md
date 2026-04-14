# Copilot Instructions - DrawformApp

## Architecture

Two decoupled parts share one repo:

- Frontend (`src/`): React 19 + TypeScript SPA on Vite 7. Main routes are `/`, `/analyzer`, `/reconstruct`, `/projects`, `/export`, `/profile`, plus auth pages. Entry path: `src/main.tsx` -> `BrowserRouter` -> `AuthProvider` -> `App`.
- Backend (`server/`): FastAPI service in `server/main.py`. Primary endpoints are `/api/export`, `/api/export-dxf`, `/api/analyze`, `/api/reconstruct`, `/api/health`, `/api/ai-insight`, and `/api/logs/last`. Geometry work is delegated to FreeCAD subprocess scripts in `server/freecad/`.

Vite proxies `/api` to `http://localhost:8000` in dev via `vite.config.ts`.

## Working Contract

- Read `AGENTS.md` first for path selection and quality gates.
- Read `REPO_SYNC_POLICY.md` for ownership and sync rules across docs and hidden repo folders.
- Use `FAST-PATH` only for changes without meaningful drawing-quality or benchmark impact.
- Use `MEDIUM-PATH` for predictable output changes.
- Use `FULL-PATH` for drawing logic, heuristics, scoring, benchmark behavior, and agent workflow changes.
- Use `LONG-RUN` when the work must be stable across repeated runs or is release-facing.
- From `FULL-PATH` onward, keep a shared `RUN CONTEXT` with one `run_id`, exact commands, and artifacts under `server/_debug/agent_runs/<run_id>/`.
- Any iteration that produces fresh drawing artifacts must get a visual review before the final Critic verdict.

## Status Discipline

- Do not trust hardcoded pass/fail counts in this file.
- Use `server/README.md` for commands, `AGENTS.md` for gates, and `REPO_SYNC_POLICY.md` for source ownership.
- Live quality status must come from current command output, CI, or the active `server/_debug/agent_runs/<run_id>/run_state.json`.

## Important Files

- `AGENTS.md`: workflow, path types, gates, failure classes
- `REPO_SYNC_POLICY.md`: source ownership and sync rules across docs, `.claude`, `.github`, and `.vscode`
- `DEVELOPER_DOCS.md`: technical architecture and stable system contracts
- `server/main.py`: FastAPI app, validation, DSE orchestration, subprocess control
- `server/freecad/step_to_pdf.py`: main drawing renderer and highest-risk hotspot
- `server/freecad/step_feature_probe.py`: geometry feature extraction
- `server/freecad/step_unfold.py`: sheet-metal unfold subprocess
- `server/rules/dimension_strategy.py`: `select_layout_profile_standalone()`, `build_dimension_plan()`, `apply_overrides()`
- `server/rules/dimension_plan_schema.py`: plan models
- `server/test_views.py`: view regression and drawing-quality checks
- `server/tests/test_dimension_strategy.py`: DSE unit tests
- `server/run_quality_gate.py`: unit + regression + stability runner
- `Agent_visual_review.md`: mandatory visual delta review before Critic on artifact-producing iterations
- `server/README.md`: canonical backend commands

## Dev Commands

Prefer the project `.venv` for backend commands and use the canonical command
list in `server/README.md`.

## Working Rules

- UI copy is German. Keep code identifiers and most technical docs in English.
- For drawing-quality work, inspect `server/_debug/*_debug.svg`, `*_preview.png`, and `*_report.json` before claiming success.
- For `FULL-PATH` and `LONG-RUN`, also persist the latest artifacts and a `run_state.json` under `server/_debug/agent_runs/<run_id>/`.
- If you generated fresh render or preview artifacts, document the visual delta before the final Critic handoff.
- Do not describe the analyzer as "local-only". It has a real backend path plus a local fallback.
- Do not claim the current view baseline is green unless you have rerun it.
- Treat `step_to_pdf.py` edits as high-risk. Re-run at least a targeted `test_views.py` case after touching it.
- Auth credentials are stored in `localStorage`; this is a known MVP shortcut, not production-safe.
- Keep mirror docs free of live status counters; the sync validator enforces this.

<!-- agent-architect:start -->
# Repository Instructions fuer GitHub Copilot

Hinweis: Der Block unten wird vom Agent Architect verwaltet.

## Tech-Stack
- frontend: React 19 + TypeScript (Vite 7)
- backend: FastAPI (Python)
- rendering: FreeCAD subprocess pipeline

## Command Policy
- Frontend: `npm install`, `npm run dev`, `npm run build`, `npm run lint`
- Backend Tests: `cd server && python -m pytest tests/`
- View Regression: `cd server && python test_views.py`
- Quality Gate: `cd server && python run_quality_gate.py`

## Output Policy
- Bevor du Code schreibst: Plan + betroffene Dateien nennen.
- Pro Task: kleine Aenderungen + Tests/Checks gemaess Command Policy.
- Workflow und Gates: siehe `AGENTS.md`.
<!-- agent-architect:end -->


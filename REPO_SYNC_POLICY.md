# Repository Sync Policy

## Purpose

This file defines which repository files own which kind of truth.
The goal is simple: workflow, status, commands, and local-tool behavior must not
drift apart again.

## Canonical Sources

| Topic | Canonical source | Mirrors | Rule |
| --- | --- | --- | --- |
| Workflow, path types, gates, failure classes | `AGENTS.md` | `Developer.md`, `.github/copilot-instructions.md` | Mirrors may summarize, but must not redefine rules. |
| Cross-doc ownership and sync rules | `REPO_SYNC_POLICY.md` | all repo docs | This file defines what may be duplicated. |
| Technical architecture and code contracts | `DEVELOPER_DOCS.md` | `Developer.md`, `README.md`, `server/README.md`, `.github/copilot-instructions.md` | Mirrors keep only stable orientation, not live metrics. |
| Live verification status | command output + active `server/_debug/agent_runs/<run_id>/run_state.json` | none | Do not hardcode live pass/fail numbers into mirror docs. |
| Backend and local dev commands | `server/README.md` | `README.md`, `.github/copilot-instructions.md` | Mirrors may point to commands, not carry their own live status tables. |
| Project-wide Claude permissions | `.claude/settings.json` | `.claude/settings.local.json` | `settings.local.json` may add machine-local overrides, but must not become the canonical project source. |
| Local Claude overrides | `.claude/settings.local.json` | none | Local only. Keep machine- or user-specific differences here. |
| GitHub CI behavior | `.github/workflows/quality-gate.yml` | docs may mention it | CI is authoritative for automated repo gates. |
| VS Code editor behavior | `.vscode/*` | none | Local editor configuration only. Do not treat it as workflow authority. |
| Versioned-vs-local artifact boundaries | `.gitignore`, `.gitattributes` | docs may mention them | Ignore rules are canonical for what stays local. |
| TODO lifecycle and archive rules | `server/docs/todos/README.md` | archived TODO files under `server/docs/todos/archive/` | Active TODOs stay in `server/docs/todos/`; completed TODOs move to `archive/` with `Status: erledigt`. |

## Sync Rules

1. `AGENTS.md` is the workflow authority.
2. Live numbers such as `20/20`, `64/64`, `96/111`, sample totals, or current
   failure counts must not be duplicated in mirror docs.
3. If a change affects workflow or release gates, update `AGENTS.md` first and
   then update mirrors in the same change.
4. If a change affects dev commands or CI, update the canonical command source
   and the CI workflow in the same change.
5. If a doc only mirrors another file, it must link to the canonical file
   instead of re-stating volatile status.
6. `settings.local.json` may differ locally, but it must not be used as the
   project source of truth.
7. Active TODOs belong in `server/docs/todos/`; archived TODOs belong in
   `server/docs/todos/archive/` and must clearly state `Status: erledigt`.

## Live Status Sources

Use these sources instead of hardcoded snapshots:

- `git status --short`
- `python scripts/validate_repo_sync.py`
- `server/.venv/Scripts/python.exe -m pytest server/tests/test_dimension_strategy.py -q`
- `server/.venv/Scripts/python.exe server/test_views.py`
- `server/_debug/agent_runs/<run_id>/run_state.json`

## Enforcement

Run:

```powershell
python scripts/validate_repo_sync.py
```

The GitHub quality gate should run the same validator so drift is caught before
merge.

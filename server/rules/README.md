# Rules

This folder contains the **Dimension Strategy Engine (DSE)** — a deterministic rule engine that decides what to dimension on a drawing.

## Files

| File | Purpose |
|------|---------|
| `rule_engine.py` | Loads `knowledge_base.json`, validates it, evaluates rules per feature/context |
| `dimension_plan_schema.py` | Pydantic models: `DimensionPlan`, `ViewPlan`, `DimensionItem`, `ProcessNote`, `DatumSystem` |
| `dimension_strategy.py` | Main DSE: `build_dimension_plan()`, `select_layout_profile_standalone()`, `apply_overrides()` |

## How it works

```
feature_payload  +  layout_profile  +  detail_level
        ↓
  build_dimension_plan()
        ↓
  DimensionPlan (JSON) — describes *what* to dimension, not *how* to render
        ↓
  step_to_pdf.py reads plan from meta.json → plan-driven SVG rendering
```

The baseline is **deterministic**: same input always produces the same plan. LLMs may supply structured overrides (add/remove/modify) on top — every override is logged in `plan.overrides_applied`.

## Detail levels

| Level | Name | Content |
|-------|------|---------|
| 1 | Manufacturing-minimal | L × B × H, hole Ø, pitch, Biegeradius |
| 2 | Inspection-ready | + Left-view depth, hole locations from datum |
| 3 | Customer-spec | + all process notes (thickness, k-factor, Ri) |

## Part types

- **milling** — overall dims on Front+Top, hole callouts on Front
- **sheet_metal** — Abwicklung primary (flat_length, flat_width, hole X/Y), process notes (t, Ri, K)
- **turning** — placeholder (Ø-dominant, lengths from face)

## Usage examples

```powershell
cd server

# Validate knowledge base
python knowledge/validate_knowledge_base.py

# Query a rule decision directly
python rules/rule_engine.py --feature hole --ctx visible=true
python rules/rule_engine.py --validate

# DSE unit tests
python -m unittest tests.test_dimension_strategy -v
```

## LLM override format

```json
[
  {"action": "add",    "target_view": "Front",
   "dimension": {"dim_type": "pocket_depth", "target_view": "Front", "value_mm": 5.0}},
  {"action": "remove", "target_view": "Front", "dim_type": "hole_pitch"},
  {"action": "modify", "target_view": "Front", "dim_type": "hole_diameter",
   "changes": {"label": "Ø14 H7"}}
]
```

## Regression integration

`check_dimension_plan()` in `test_views.py` validates DSE output per part.
Enable for a part by adding `"dse_check": True` to its entry in the `EXPECTED` dict.

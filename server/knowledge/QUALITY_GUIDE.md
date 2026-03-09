# Knowledge Base Guide: Dimensioning Decisions

This guide explains where rule data should come from and how to keep quality high.

## 1. Source hierarchy (highest to lowest trust)

1. `tier_1`: official standard catalogs and licensed standards metadata
- Example: ISO and DIN catalog entries, official publication status.
- Use for: naming, scope, status, and internal rule derivation references.

2. `tier_2`: approved internal artifacts
- Example: `server/docs/DIN_ISO_BASELINE_TECHNISCHE_ZEICHNUNG.md`, reviewed golden sample checklists, released company design manuals.
- Use for: concrete implementation defaults and practical constraints.

3. `tier_3`: observational evidence
- Example: manufacturing NCR findings, QA inspection issues, workshop feedback.
- Use for: prioritization and continuous improvement, never as single-source norm truth.

## 1a. Practical data sources to feed now

1. Existing released drawings from your company (best immediate source).
- Prefer parts with known good production history.
- Capture: which dimensions were used, which were missing, and why.

2. Internal reviews of generated PDFs against the baseline.
- Use `server/_debug/PDF_REVIEW_CHECKLIST.md`.
- Log every rejected dimension decision into `feedback_log.jsonl`.

3. Shopfloor and QA findings.
- Track recurring defects caused by ambiguous or missing dimensions.
- Promote a finding to a rule only after 2-person review.

## 2. What to collect for each rule

Each rule in `knowledge_base.json` must include:
- `source_refs`: one or more source IDs.
- `quality.status`: `approved` only for production use.
- `quality.reviewers`: at least two independent reviewers.
- `quality.last_reviewed`: date of latest review.

## 3. Data ingestion workflow

1. Add or update source in `sources` with `verified_on` date.
2. Add or update rule in `rules` with traceable `source_refs`.
3. Run validator:
- `python server/knowledge/validate_knowledge_base.py`
4. Run drawing regression:
- `python server/test_views.py`
5. Review visual checklist for complex parts:
- `server/_debug/PDF_REVIEW_CHECKLIST.md`
6. If accepted, update baseline:
- `python server/test_views.py --update-golden`

## 4. Quality gates

A rule is production-eligible only if:
- It references at least one `tier_1` or `tier_2` source.
- It has at least two independent reviewers.
- It is marked `approved`.
- It does not conflict with existing `must_not` constraints.

## 5. Audit trail

For each applied dimension decision, store a decision log item:
- rule ID
- source references
- chosen view/feature
- accepted/rejected candidates
- timestamp

This makes decisions explainable for design, QA, and customers.

## 6. Quality metrics (weekly)

- `rule_coverage`: percentage of feature types with at least one approved `must` rule.\n
- `review_pass_rate`: accepted decisions / total reviewed decisions.\n
- `ncr_link_rate`: percentage of severe NCR issues linked to at least one rule update.\n
- `false_positive_rate`: dimensions removed manually after generation.\n

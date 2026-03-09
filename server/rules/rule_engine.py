#!/usr/bin/env python
"""Small rule engine for knowledge-driven dimensioning decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_KB_PATH = Path(__file__).resolve().parent.parent / "knowledge" / "knowledge_base.json"
PRIORITY_ORDER = {"must": 0, "should": 1, "must_not": 2}
TIER_RANK = {"tier_1": 3, "tier_2": 2, "tier_3": 1}


class KnowledgeError(RuntimeError):
    pass


def load_knowledge_base(path: Path | str = DEFAULT_KB_PATH) -> Dict[str, Any]:
    kb_path = Path(path)
    if not kb_path.exists():
        raise KnowledgeError(f"Knowledge base file not found: {kb_path}")
    try:
        return json.loads(kb_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise KnowledgeError(f"Knowledge base is not valid JSON: {exc}") from exc


def _minimum_tier_rank(policy: Dict[str, Any]) -> int:
    minimum = str((policy or {}).get("minimum_source_tier", "tier_2"))
    if minimum not in TIER_RANK:
        return TIER_RANK["tier_2"]
    return TIER_RANK[minimum]


def validate_knowledge_base(kb: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    for top_key in ("sources", "rules", "quality_policy"):
        if top_key not in kb:
            errors.append(f"Missing top-level key: {top_key}")

    sources = kb.get("sources") or []
    rules = kb.get("rules") or []
    policy = kb.get("quality_policy") or {}

    if not isinstance(sources, list):
        errors.append("sources must be a list")
        sources = []
    if not isinstance(rules, list):
        errors.append("rules must be a list")
        rules = []

    source_by_id: Dict[str, Dict[str, Any]] = {}
    for idx, source in enumerate(sources):
        sid = str((source or {}).get("id", "")).strip()
        if not sid:
            errors.append(f"Source #{idx} has no id")
            continue
        if sid in source_by_id:
            errors.append(f"Duplicate source id: {sid}")
            continue
        tier = str((source or {}).get("tier", "")).strip()
        if tier not in TIER_RANK:
            errors.append(f"Source '{sid}' has invalid tier '{tier}'")
        source_by_id[sid] = source

    minimum_tier_rank = _minimum_tier_rank(policy)
    minimum_reviewers = int((policy or {}).get("minimum_independent_reviewers", 2) or 2)

    seen_rule_ids = set()
    for idx, rule in enumerate(rules):
        rid = str((rule or {}).get("id", "")).strip()
        if not rid:
            errors.append(f"Rule #{idx} has no id")
            continue
        if rid in seen_rule_ids:
            errors.append(f"Duplicate rule id: {rid}")
            continue
        seen_rule_ids.add(rid)

        feature = str((rule or {}).get("feature", "")).strip()
        if not feature:
            errors.append(f"Rule '{rid}' has no feature")

        priority = str((rule or {}).get("priority", "")).strip()
        if priority not in PRIORITY_ORDER:
            errors.append(f"Rule '{rid}' has invalid priority '{priority}'")

        actions = rule.get("actions")
        if not isinstance(actions, list) or not actions:
            errors.append(f"Rule '{rid}' has no actions")

        source_refs = rule.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            errors.append(f"Rule '{rid}' has no source_refs")
            source_refs = []

        max_tier_rank = 0
        for ref in source_refs:
            sid = str(ref)
            source = source_by_id.get(sid)
            if source is None:
                errors.append(f"Rule '{rid}' references unknown source '{sid}'")
                continue
            max_tier_rank = max(max_tier_rank, TIER_RANK.get(str(source.get("tier", "")), 0))

        if max_tier_rank < minimum_tier_rank:
            errors.append(
                f"Rule '{rid}' does not meet minimum source tier requirement"
            )

        quality = rule.get("quality") or {}
        status = str(quality.get("status", "")).strip().lower()
        if status != "approved":
            errors.append(f"Rule '{rid}' is not approved (status='{status or 'missing'}')")
        reviewers = quality.get("reviewers") or []
        if not isinstance(reviewers, list) or len(reviewers) < minimum_reviewers:
            errors.append(
                f"Rule '{rid}' has too few reviewers (min {minimum_reviewers})"
            )

    return errors


def _match_condition(key: str, expected: Any, context: Dict[str, Any]) -> bool:
    if key.endswith("_min"):
        ctx_key = key[:-4]
        actual = context.get(ctx_key)
        return actual is not None and float(actual) >= float(expected)
    if key.endswith("_max"):
        ctx_key = key[:-4]
        actual = context.get(ctx_key)
        return actual is not None and float(actual) <= float(expected)

    actual = context.get(key)
    if isinstance(expected, list):
        return actual in expected
    return actual == expected


def _when_matches(rule: Dict[str, Any], context: Dict[str, Any]) -> bool:
    when = rule.get("when") or {}
    if not isinstance(when, dict):
        return False
    for key, expected in when.items():
        try:
            if not _match_condition(key, expected, context):
                return False
        except (TypeError, ValueError):
            return False
    return True


def select_applicable_rules(
    kb: Dict[str, Any], feature: str, context: Dict[str, Any] | None = None
) -> List[Dict[str, Any]]:
    context = context or {}
    selected = []
    for rule in kb.get("rules", []):
        if (rule.get("quality") or {}).get("status") != "approved":
            continue
        rule_feature = str(rule.get("feature", "")).strip()
        if rule_feature not in {"global", feature}:
            continue
        if not _when_matches(rule, context):
            continue
        selected.append(rule)
    selected.sort(key=lambda r: (PRIORITY_ORDER.get(str(r.get("priority")), 99), str(r.get("id"))))
    return selected


def build_dimension_decision(
    kb: Dict[str, Any], feature: str, context: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    rules = select_applicable_rules(kb, feature=feature, context=context)
    bucket = {"must": [], "should": [], "must_not": []}
    evidence = []

    for rule in rules:
        priority = str(rule.get("priority"))
        for action in rule.get("actions", []):
            encoded = json.dumps(action, sort_keys=True)
            if encoded not in {json.dumps(x, sort_keys=True) for x in bucket[priority]}:
                bucket[priority].append(action)
        evidence.append(
            {
                "rule_id": rule.get("id"),
                "priority": priority,
                "source_refs": rule.get("source_refs", []),
            }
        )

    return {
        "feature": feature,
        "context": context or {},
        "must_add": bucket["must"],
        "should_add": bucket["should"],
        "must_not_add": bucket["must_not"],
        "evidence": evidence,
    }


def _parse_scalar(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_ctx_pairs(raw: str) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {}
    if not raw.strip():
        return ctx
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise KnowledgeError(f"Invalid ctx entry '{item}', expected key=value")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise KnowledgeError(f"Invalid ctx entry '{item}', empty key")
        ctx[key] = _parse_scalar(value.strip())
    return ctx


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Knowledge-driven dimensioning rule engine")
    parser.add_argument("--kb", default=str(DEFAULT_KB_PATH), help="Path to knowledge_base.json")
    parser.add_argument("--validate", action="store_true", help="Validate the knowledge base and exit")
    parser.add_argument("--feature", default="hole", help="Feature type for decision query")
    parser.add_argument(
        "--context",
        default="{}",
        help="JSON object with context values, e.g. '{\"visible\": true}'",
    )
    parser.add_argument(
        "--ctx",
        default="",
        help="PowerShell-friendly key=value list, e.g. visible=true,count=3",
    )
    args = parser.parse_args(argv)

    kb = load_knowledge_base(args.kb)
    errors = validate_knowledge_base(kb)
    if errors:
        print("Knowledge base validation FAILED:")
        for err in errors:
            print(f"- {err}")
        return 1

    if args.validate:
        print("Knowledge base validation OK")
        return 0

    context: Dict[str, Any] = {}
    try:
        context = json.loads(args.context)
    except json.JSONDecodeError as exc:
        if args.context.strip() not in {"", "{}"}:
            raise KnowledgeError(f"Invalid JSON for --context: {exc}") from exc
    context.update(_parse_ctx_pairs(args.ctx))

    decision = build_dimension_decision(kb, feature=args.feature, context=context)
    print(json.dumps(decision, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

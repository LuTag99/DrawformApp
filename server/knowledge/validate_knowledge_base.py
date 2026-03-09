#!/usr/bin/env python
"""Validate the structured dimensioning knowledge base."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rules.rule_engine import load_knowledge_base, validate_knowledge_base


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate knowledge_base.json")
    parser.add_argument(
        "--kb",
        default=str(Path(__file__).resolve().parent / "knowledge_base.json"),
        help="Path to knowledge_base.json",
    )
    args = parser.parse_args()

    kb = load_knowledge_base(args.kb)
    errors = validate_knowledge_base(kb)
    if errors:
        print("Knowledge base validation FAILED:")
        for err in errors:
            print(f"- {err}")
        return 1
    print("Knowledge base validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

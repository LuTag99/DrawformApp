from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


FILE_RULES = {
    "Developer.md": {
        "require": ["REPO_SYNC_POLICY.md"],
        "forbid": [
            r"## Verifizierter Snapshot",
            r"DSE Unit Tests: \*\*64/64\*\*",
            r"Baseline Regression: `20/20`",
            r"All-Samples: `96/111`",
        ],
    },
    "DEVELOPER_DOCS.md": {
        "require": ["REPO_SYNC_POLICY.md", "AGENTS.md", "server/README.md"],
        "forbid": [
            r"## 3\) Verifizierter Snapshot",
            r"\| DSE Unit Tests \| \*\*64/64\*\*",
            r"\| Baseline Regression \| `20/20`",
            r"\| All-Samples \| `96/111`",
        ],
    },
    "README.md": {
        "require": ["REPO_SYNC_POLICY.md", "server/README.md"],
        "forbid": [
            r"20/20 Baseline-Regression",
            r"\*\*64/64 DSE Unit Tests\*\*",
            r"96/111 All-Samples",
        ],
    },
    "server/README.md": {
        "require": ["REPO_SYNC_POLICY.md"],
        "forbid": [
            r"### Current test results",
            r"\*\*64/64\*\*",
            r"\*\*20/20\*\*",
            r"96/111",
            r"# 64 Tests",
        ],
    },
    ".github/copilot-instructions.md": {
        "require": ["AGENTS.md", "REPO_SYNC_POLICY.md", "server/README.md"],
        "forbid": [
            r"## Current Status",
            r"46/46",
            r"20/20",
            r"105/111",
            r"96/111",
        ],
    },
    "server/rules/README.md": {
        "require": [],
        "forbid": [
            r"DSE unit tests \(46 tests\)",
        ],
    },
    ".github/workflows/quality-gate.yml": {
        "require": ["validate_repo_sync.py"],
        "forbid": [],
    },
}


def main() -> int:
    errors: list[str] = []

    if not (ROOT / "REPO_SYNC_POLICY.md").exists():
        errors.append("Missing canonical sync policy: REPO_SYNC_POLICY.md")

    for rel_path, rules in FILE_RULES.items():
        path = ROOT / rel_path
        if not path.exists():
            errors.append(f"Missing required file: {rel_path}")
            continue

        text = path.read_text(encoding="utf-8")

        for needle in rules["require"]:
            if needle not in text:
                errors.append(f"{rel_path}: missing required reference '{needle}'")

        for pattern in rules["forbid"]:
            if re.search(pattern, text):
                errors.append(f"{rel_path}: forbidden sync-drift pattern '{pattern}'")

    if errors:
        print("Repo sync validation FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Repo sync validation OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

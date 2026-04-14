from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TODO_ROOT = ROOT / "server" / "docs" / "todos"
TODO_ARCHIVE_ROOT = TODO_ROOT / "archive"


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

    errors.extend(validate_todo_lifecycle())

    if errors:
        print("Repo sync validation FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Repo sync validation OK")
    return 0


def validate_todo_lifecycle() -> list[str]:
    errors: list[str] = []

    if not TODO_ROOT.exists():
        return errors

    active_readme = TODO_ROOT / "README.md"
    archive_readme = TODO_ARCHIVE_ROOT / "README.md"
    if not active_readme.exists():
        errors.append("Missing TODO lifecycle guide: server/docs/todos/README.md")
    if not archive_readme.exists():
        errors.append("Missing TODO archive guide: server/docs/todos/archive/README.md")

    active_todos = sorted(path for path in TODO_ROOT.glob("TODO*.md") if path.is_file())
    archived_todos = sorted(path for path in TODO_ARCHIVE_ROOT.glob("TODO*.md") if path.is_file())

    for path in active_todos:
        text = path.read_text(encoding="utf-8")
        if re.search(r"^Status:\s*erledigt\s*$", text, flags=re.IGNORECASE | re.MULTILINE):
            errors.append(
                f"{path.relative_to(ROOT).as_posix()}: completed TODO must be moved to server/docs/todos/archive/"
            )

    for path in archived_todos:
        text = path.read_text(encoding="utf-8")
        if not re.search(r"^Status:\s*erledigt\s*$", text, flags=re.IGNORECASE | re.MULTILINE):
            errors.append(
                f"{path.relative_to(ROOT).as_posix()}: archived TODO must declare 'Status: erledigt'"
            )

    return errors


if __name__ == "__main__":
    sys.exit(main())

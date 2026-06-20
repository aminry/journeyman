#!/usr/bin/env python3
"""Definition-of-Done: docs-in-sync check.

Enforces ADR-0001/ADR-0006 discipline: a change touching architectural paths must
either add a new ADR or update ARCHITECTURE.md in the same change, unless it
explicitly declares `architecture-impact: none`.

Reads the `docs-in-sync` gate from ci/definition_of_done.yaml so the rule lives in
one place. Compares the working change against a base ref (default: origin/main).

Exit codes: 0 = pass, 1 = violation, 2 = usage/config error.

Dependencies: PyYAML. Git available on PATH.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("docs_sync: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

REPO = Path(__file__).resolve().parent.parent
GATE_FILE = REPO / "ci" / "definition_of_done.yaml"
BASE_REF = os.environ.get("DOD_BASE_REF", "origin/main")
# The change description / PR body is read from here so the escape hatch is auditable.
CHANGE_DESC = os.environ.get("DOD_CHANGE_DESC", "")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def changed_files() -> list[str]:
    # Prefer a diff against the base ref; fall back to staged changes.
    out = git("diff", "--name-only", f"{BASE_REF}...HEAD")
    if not out:
        out = git("diff", "--name-only", "--cached")
    return [f for f in out.splitlines() if f.strip()]


def load_gate() -> dict:
    if not GATE_FILE.exists():
        print(f"docs_sync: gate file not found at {GATE_FILE}", file=sys.stderr)
        sys.exit(2)
    spec = yaml.safe_load(GATE_FILE.read_text())
    for gate in spec.get("gates", []):
        if gate.get("id") == "docs-in-sync":
            return gate
    print("docs_sync: no 'docs-in-sync' gate in config", file=sys.stderr)
    sys.exit(2)


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in patterns)


def main() -> int:
    gate = load_gate()
    arch_patterns: list[str] = gate.get("architectural_paths", [])
    files = changed_files()
    if not files:
        print("docs_sync: no changed files detected; pass")
        return 0

    architectural = [f for f in files if matches_any(f, arch_patterns)]
    if not architectural:
        print("docs_sync: no architectural paths changed; pass")
        return 0

    # Escape hatch: explicit declaration in the change description.
    declaration = gate.get("escape_hatch", {}).get("declaration", "")
    max_files = gate.get("escape_hatch", {}).get("blocked_if_changed_files_exceed", 10**9)
    if declaration and declaration in CHANGE_DESC:
        if len(files) > int(max_files):
            print(
                f"docs_sync: '{declaration}' declared but {len(files)} files changed "
                f"(> {max_files}); an ADR is required for changes this large.",
                file=sys.stderr,
            )
            return 1
        print(f"docs_sync: '{declaration}' declared; pass")
        return 0

    # Otherwise require a new ADR or an ARCHITECTURE.md update.
    added_adr = any(fnmatch.fnmatch(f, "docs/adr/*.md") and "template" not in f for f in files)
    touched_arch = any(f == "ARCHITECTURE.md" for f in files)
    if added_adr or touched_arch:
        print("docs_sync: architectural change documented (ADR or ARCHITECTURE.md); pass")
        return 0

    print(
        "docs_sync: FAIL — architectural paths changed:\n  "
        + "\n  ".join(architectural)
        + "\nAdd a new docs/adr/NNNN-*.md (copy docs/adr/template.md) or update "
        "ARCHITECTURE.md in this change, or declare 'architecture-impact: none' "
        "in the change description.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

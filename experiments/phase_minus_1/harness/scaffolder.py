"""Scaffold a fresh per-instance repo from project/project-template/.

domain.md §1: each instance is built in its own fresh repo scaffolded from the
canonical template, so we measure portable craft (Plane B), not project-brain
accumulation. The scaffolder copies the template, fills the ``{{PLACEHOLDERS}}``,
creates the stub tree, writes the instance spec as Plane-A project knowledge, and
initialises git so the effector's changes are diffable.

It copies ONLY the template — never the harness or contract tests (held-out
integrity, domain.md §1).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import yaml

from harness.specschema import InstanceSpec

_TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "project" / "project-template"
_PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")
_TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".txt"}


def _placeholders(spec: InstanceSpec) -> dict[str, str]:
    return {
        "{{PROJECT_NAME}}": spec.id,
        "{{PROJECT_PURPOSE}}": f"{spec.title}: a spec-described CRUD service (Phase -1 instance).",
        "{{STACK}}": "Python 3.11 + FastAPI + SQLite",
        "{{PROJECT_STATUS}}": "scaffolding",
        "{{INSTALL_CMD}}": "pip install -r requirements.txt",
        "{{TEST_UNIT_CMD}}": "pytest tests -q",
        "{{TEST_INTEGRATION_CMD}}": "pytest tests -q",
        "{{COVERAGE_CMD}}": "pytest --cov -q",
        "{{BUILD_CMD}}": 'python -c "import app"',
        "{{LINT_CMD}}": "ruff check . && black --check .",
        "{{CODEGRAPH_CMD}}": "true  # code-graph indexer wired during seed build",
        "{{SECRET_SCAN_CMD}}": "true  # secret scanner wired during seed build",
        "{{SAST_CMD}}": "true",
        "{{SCA_CMD}}": "true",
        "{{DOD_CMD}}": "bash hooks/run_dod.sh",
        "{{EVAL_HARNESS_CMD}}": "true",
        "{{DEPENDENCY_MANIFEST}}": "requirements.txt",
        "{{YYYY-MM-DD}}": "2026-06-19",
        "{{WHO_DECIDED}}": "Phase -1 harness scaffolder",
    }


def _fill(text: str, mapping: dict[str, str]) -> str:
    for k, v in mapping.items():
        text = text.replace(k, v)
    return _PLACEHOLDER_RE.sub("", text)  # blank any unmapped placeholders


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def scaffold_repo(
    dest: str | Path, spec: InstanceSpec, *, instance_spec_path: str | None = None
) -> Path:
    """Create a fresh repo for ``spec`` at ``dest`` and return its path."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(_TEMPLATE_ROOT, dest)

    mapping = _placeholders(spec)
    for path in dest.rglob("*"):
        if path.is_file() and path.suffix in _TEXT_SUFFIXES:
            path.write_text(_fill(path.read_text(), mapping))

    # Stub tree the scaffolder is responsible for (template README).
    for d in ("src", "tests", "build", "hooks", "docs/knowledge", "codegraph"):
        (dest / d).mkdir(parents=True, exist_ok=True)
    (dest / "ARCHITECTURE.md").write_text(
        f"# {spec.id} — architecture\n\n(stub, kept current by the gate)\n"
    )
    (dest / "DESIGN.md").write_text(f"# {spec.id} — design\n\n(stub)\n")
    (dest / "docs" / "knowledge" / "index.md").write_text("# Project knowledge\n")
    (dest / "codegraph" / "graph.json").write_text("{}\n")
    # pytest.ini pins the instance's rootdir so its DoD never picks up the harness config.
    (dest / "pytest.ini").write_text("[pytest]\n")

    # Plane-A project knowledge: the instance spec lives in the repo (NOT the tests).
    spec_src = (
        Path(instance_spec_path).read_text()
        if instance_spec_path
        else yaml.safe_dump(
            {"id": spec.id, "title": spec.title, "tier": spec.tier}, sort_keys=False
        )
    )
    (dest / "docs").mkdir(exist_ok=True)
    (dest / "docs" / "instance.spec.yaml").write_text(spec_src)

    _git(dest, "init", "-q")
    _git(dest, "config", "user.email", "harness@journeyman.local")
    _git(dest, "config", "user.name", "phase-minus-1-harness")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", f"scaffold {spec.id} from project-template")
    return dest

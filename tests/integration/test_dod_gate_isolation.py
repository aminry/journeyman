"""DoD gate must run the instance's own tests under the project venv, not the
ambient interpreter (T-1.4 root cause).

The full-run treatment arm's apparent "quality collapse" was a measurement artifact:
``run_instance_dod`` shelled out to a bare ``python -m pytest`` (the ambient interpreter)
instead of the ``.venv`` the service actually boots from. Every treatment repo that
adopted the craft-prescribed SQLAlchemy stack therefore failed DoD on
``ModuleNotFoundError: sqlalchemy`` even though its contract suite — booted via ``run.sh``
under the venv — passed 17/17. The gate must mirror the service's environment. These tests
lock that in; the last one reproduces the exact artifact and asserts it no longer fires.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from harness.runner import _gate_python, run_instance_dod


def test_gate_python_prefers_project_venv(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".venv" / "bin").mkdir(parents=True)
    vpy = repo / ".venv" / "bin" / "python"
    vpy.write_text("")  # presence is the signal _gate_python keys on
    assert _gate_python(repo) == str(vpy)


def test_gate_python_falls_back_to_harness_interpreter_not_bare_python(tmp_path: Path) -> None:
    """No project venv -> use the harness interpreter, never a bare ``python`` off PATH
    (the bare path is what resolved to a deps-less interpreter in the full run)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    chosen = _gate_python(repo)
    assert chosen == (sys.executable or "python")
    assert chosen != "python"


def _build_repo_with_venv_only_dep(repo: Path, module: str) -> Path:
    """A repo whose tests import ``module``, which exists ONLY inside the repo's venv
    (the SQLAlchemy situation, minus the pip install). Returns the venv interpreter."""
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_dep.py").write_text(
        f"import {module}\n\n\ndef test_dep_present():\n    assert {module}.OK\n"
    )
    venv = repo / ".venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
        check=True,
        capture_output=True,
    )
    vpy = venv / "bin" / "python"
    if subprocess.run([str(vpy), "-c", "import pytest"], capture_output=True).returncode != 0:
        pytest.skip("pytest not importable from a --system-site-packages venv in this environment")
    purelib = subprocess.run(
        [str(vpy), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    (Path(purelib) / f"{module}.py").write_text("OK = True\n")
    return vpy


def test_dod_passes_when_dependency_lives_only_in_the_project_venv(tmp_path: Path) -> None:
    """The exact full-run artifact, now guarded: a repo whose tests need a venv-only
    dependency passes DoD under the fix, and would fail under the ambient interpreter."""
    repo = tmp_path / "repo"
    module = "venv_only_dep_t14"
    _build_repo_with_venv_only_dep(repo, module)

    # Fixed gate runs under the venv -> the venv-only dependency is importable -> pass.
    result = run_instance_dod(repo)
    assert result.passed, f"gate should pass under the project venv; detail:\n{result.detail}"

    # The old behavior (ambient interpreter) cannot import the venv-only dep -> fails.
    ambient = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    assert ambient.returncode != 0, "ambient interpreter should NOT see the venv-only dep"
    assert module in (ambient.stdout + ambient.stderr)

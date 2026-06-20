"""Render the contract suite as a standalone, human-runnable pytest module.

The harness executes the suite in-process for structured metrics
(:func:`harness.compiler.run_suite`), but domain.md §3 and the T-1.1 deliverable
call for an emitted black-box ``httpx``/``pytest`` suite. This renders that
artifact: one parametrised test per contract case, driving ``$BASE_URL``.

The single source of truth stays :func:`compile_contract_suite` — the rendered
module imports the harness and runs the same cases, so the file and the in-process
run can never disagree. It is written to the harness's run artifacts (never into
the effector's repo — held-out integrity).
"""

from __future__ import annotations

from pathlib import Path

from harness.specschema import InstanceSpec

_HARNESS_PARENT = str(Path(__file__).resolve().parents[1])

_TEMPLATE = '''"""GENERATED — do not edit. Black-box contract suite for instance {instance_id!r}.

Held-out acceptance tests (domain.md §3). The effector never sees this file.
Run against a booted service:

    BASE_URL=http://127.0.0.1:$PORT python -m pytest {this_file}
"""
import os
import sys

import httpx
import pytest

sys.path.insert(0, {harness_parent!r})

from harness.compiler import Api, compile_contract_suite  # noqa: E402
from harness.specschema import load_spec  # noqa: E402

SPEC_PATH = {spec_path!r}
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000")

_SPEC = load_spec(SPEC_PATH)
_CASES = compile_contract_suite(_SPEC)


@pytest.mark.parametrize("case", _CASES, ids=[c.id for c in _CASES])
def test_contract(case):
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        result = case.run(Api(client, _SPEC))
    assert result.passed, f"{{case.id}}: {{result.detail}}"
'''


def render_pytest_module(
    spec: InstanceSpec, *, spec_path: str, this_file: str = "test_contract_suite.py"
) -> str:
    return _TEMPLATE.format(
        instance_id=spec.id,
        harness_parent=_HARNESS_PARENT,
        spec_path=spec_path,
        this_file=this_file,
    )


def write_pytest_module(spec: InstanceSpec, spec_path: str, dest: str | Path) -> Path:
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_pytest_module(spec, spec_path=spec_path, this_file=p.name))
    return p

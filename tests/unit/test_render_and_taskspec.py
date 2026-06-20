"""Unit tests for the pytest renderer and the TaskSpec builder.

The renderer emits the auditable, human-runnable contract suite. The TaskSpec
builder composes the effector's prompt from the SPEC + retrieved craft only —
NEVER the contract tests (held-out integrity, domain.md §1).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.craft import CraftItem
from harness.render import render_pytest_module
from harness.specschema import load_spec
from harness.taskspec import api_conventions, build_taskspec

REPO = Path(__file__).resolve().parents[2]
BOOKS = REPO / "experiments" / "phase_minus_1" / "instances" / "example_books.spec.yaml"


@pytest.fixture
def spec():
    return load_spec(BOOKS)


def test_rendered_module_is_valid_python(spec) -> None:
    src = render_pytest_module(spec, spec_path=str(BOOKS))
    compile(src, "<generated_contract_suite>", "exec")  # must parse


def test_rendered_module_references_cases_and_base_url(spec) -> None:
    src = render_pytest_module(spec, spec_path=str(BOOKS))
    assert "def test_contract" in src
    assert "BASE_URL" in src
    assert "compile_contract_suite" in src


def test_taskspec_includes_spec_and_conventions_and_boot(spec) -> None:
    ts = build_taskspec(spec, retrieved_craft=[])
    assert "books" in ts
    assert "/healthz" in ts  # boot contract surfaced
    assert "422" in ts and "errors" in ts  # validation envelope conveyed
    assert "?sort=" in ts or "sort=" in ts  # sort convention conveyed


def test_taskspec_injects_retrieved_craft(spec) -> None:
    craft = CraftItem(
        id="fastapi-sqlite-scaffold",
        kind="orchestration",
        summary="scaffold playbook",
        when_to_use="building CRUD",
        body="REMEMBER: use file-based sqlite and a single worker.",
    )
    ts = build_taskspec(spec, retrieved_craft=[craft])
    assert "fastapi-sqlite-scaffold" in ts
    assert "file-based sqlite" in ts


def test_taskspec_never_contains_contract_tests(spec) -> None:
    ts = build_taskspec(spec, retrieved_craft=[])
    # held-out integrity: the prompt must not leak the oracle internals
    for forbidden in (
        "compile_contract_suite",
        "run_suite",
        "ContractCase",
        "list:max_limit",
        "assert res.passed",
    ):
        assert forbidden not in ts


def test_api_conventions_cover_filters_and_sort(spec) -> None:
    conv = api_conventions(spec)
    assert "genre" in conv and "in_stock" in conv
    assert "published_year" in conv

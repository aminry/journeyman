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
from harness.specschema import load_spec, parse_spec
from harness.taskspec import api_conventions, build_taskspec

HARD_SPEC = {
    "id": "orders",
    "title": "Orders",
    "tier": "hard",
    "resource": {
        "name": "order",
        "path": "/orders",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {
                "name": "status",
                "type": "enum",
                "values": ["pending", "paid", "shipped"],
                "default": "pending",
            },
            {"name": "total_cents", "type": "integer", "required": True, "min": 0},
            {"name": "discount_cents", "type": "integer", "required": True, "min": 0},
            {"name": "customer_id", "type": "ref", "ref": "customer", "required": True},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/orders", "success": 201},
        "update": {
            "method": "PATCH",
            "path": "/orders/{id}",
            "success": 200,
            "missing": 404,
            "partial": True,
        },
    },
    "related": {
        "name": "customer",
        "path": "/customers",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 80},
        ],
        "endpoints": {"create": {"method": "POST", "path": "/customers", "success": 201}},
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [
        {
            "kind": "state_machine",
            "field": "status",
            "initial": "pending",
            "transitions": {"pending": ["paid"], "paid": ["shipped"], "shipped": []},
            "on_illegal": 409,
        },
        {"kind": "cross_field", "fields": ["discount_cents", "total_cents"], "op": "lte"},
        {
            "kind": "relationship",
            "parent": "customer",
            "child": "order",
            "ref_field": "customer_id",
            "on_missing_parent": 422,
            "on_parent_delete": "restrict",
        },
    ],
}

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


def test_taskspec_conveys_business_rules_and_related_resource() -> None:
    hard = parse_spec(HARD_SPEC)
    ts = build_taskspec(hard, retrieved_craft=[])
    # business rules drive the effector (not the held-out tests)
    assert "Business rules" in ts
    assert "State machine" in ts and "transitions" in ts
    assert "Cross-field" in ts and "discount_cents" in ts
    assert "Relationship" in ts and "customer_id" in ts
    # the second (related) resource is conveyed with its endpoints
    assert "/customers" in ts and "customer" in ts
    # held-out integrity still holds for hard specs
    for forbidden in ("compile_contract_suite", "run_suite", "ContractCase", "state_machine:"):
        assert forbidden not in ts


def test_taskspec_without_business_rules_has_no_business_section(spec) -> None:
    ts = build_taskspec(spec, retrieved_craft=[])  # books = medium, no business rules
    assert "## Business rules" not in ts

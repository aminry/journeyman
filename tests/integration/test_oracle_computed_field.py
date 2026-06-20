"""Oracle validation for the computed_field dimension (ADR-0022).

computed_field is the read-side dimension none of the four write-side rules test:
the server derives a field's value rather than storing what the client sent. Two
sub-kinds, both validated the same way as the other dimensions — a correct reference
service passes every case; a surgically-broken one (BUG_WRONG_COMPUTED) fails on
EXACTLY the computed_field cases:

1. same-row derived   — available = on_hand − reserved;
2. aggregate-over-children — balance = Σ child.amount; total = Σ(child.amount × qty).

The decisive case is recompute-on-mutation: a static-cache implementation (compute
once, never refresh) is exactly the headroom this dimension exposes.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from harness.compiler import compile_contract_suite, run_suite
from harness.reference.service import BUG_WRONG_COMPUTED, build_app
from harness.specschema import parse_spec

SAME_ROW = {
    "id": "fx_inventory_c",
    "title": "Inventory (same-row computed fixture)",
    "tier": "hard",
    "resource": {
        "name": "item",
        "path": "/items",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "on_hand", "type": "integer", "required": True, "min": 0},
            {"name": "reserved", "type": "integer", "required": True, "min": 0},
            {"name": "available", "type": "integer", "readonly": True},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/items", "success": 201},
        "get": {"method": "GET", "path": "/items/{id}", "success": 200, "missing": 404},
        "update": {
            "method": "PATCH",
            "path": "/items/{id}",
            "success": 200,
            "missing": 404,
            "partial": True,
        },
        "delete": {"method": "DELETE", "path": "/items/{id}", "success": 204, "missing": 404},
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [
        {
            "kind": "computed_field",
            "field": "available",
            "compute": "subtract",
            "operands": ["on_hand", "reserved"],
        }
    ],
}

AGGREGATE = {
    "id": "fx_accounts_c",
    "title": "Accounts (aggregate computed fixture)",
    "tier": "hard",
    "resource": {
        "name": "account",
        "path": "/accounts",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 80},
            {"name": "balance", "type": "integer", "readonly": True},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/accounts", "success": 201},
        "get": {"method": "GET", "path": "/accounts/{id}", "success": 200, "missing": 404},
        "delete": {"method": "DELETE", "path": "/accounts/{id}", "success": 204, "missing": 404},
    },
    "related": {
        "name": "entry",
        "path": "/entries",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "account_id", "type": "ref", "ref": "account", "required": True},
            {"name": "amount_cents", "type": "integer", "required": True},
        ],
        "endpoints": {
            "create": {"method": "POST", "path": "/entries", "success": 201},
            "get": {"method": "GET", "path": "/entries/{id}", "success": 200, "missing": 404},
            "delete": {"method": "DELETE", "path": "/entries/{id}", "success": 204, "missing": 404},
        },
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [
        {
            "kind": "relationship",
            "parent": "account",
            "child": "entry",
            "ref_field": "account_id",
            "on_missing_parent": 422,
            "on_parent_delete": "restrict",
        },
        {
            "kind": "computed_field",
            "field": "balance",
            "compute": "sum_children",
            "child": "entry",
            "child_fields": ["amount_cents"],
        },
    ],
}

AGGREGATE_PRODUCT = {
    "id": "fx_invoices_c",
    "title": "Invoices (aggregate-of-product computed fixture)",
    "tier": "hard",
    "resource": {
        "name": "invoice",
        "path": "/invoices",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "customer", "type": "string", "required": True, "min_len": 1, "max_len": 80},
            {"name": "total_cents", "type": "integer", "readonly": True},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/invoices", "success": 201},
        "get": {"method": "GET", "path": "/invoices/{id}", "success": 200, "missing": 404},
        "delete": {"method": "DELETE", "path": "/invoices/{id}", "success": 204, "missing": 404},
    },
    "related": {
        "name": "line",
        "path": "/lines",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "invoice_id", "type": "ref", "ref": "invoice", "required": True},
            {"name": "amount_cents", "type": "integer", "required": True, "min": 0},
            {"name": "quantity", "type": "integer", "required": True, "min": 1, "max": 1000},
        ],
        "endpoints": {
            "create": {"method": "POST", "path": "/lines", "success": 201},
            "get": {"method": "GET", "path": "/lines/{id}", "success": 200, "missing": 404},
            "delete": {"method": "DELETE", "path": "/lines/{id}", "success": 204, "missing": 404},
        },
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [
        {
            "kind": "relationship",
            "parent": "invoice",
            "child": "line",
            "ref_field": "invoice_id",
            "on_missing_parent": 422,
            "on_parent_delete": "restrict",
        },
        {
            "kind": "computed_field",
            "field": "total_cents",
            "compute": "sum_children",
            "child": "line",
            "child_fields": ["amount_cents", "quantity"],
        },
    ],
}


def _run(spec_dict, bugs=frozenset()):
    spec = parse_spec(copy.deepcopy(spec_dict))
    app = build_app(copy.deepcopy(spec_dict), bugs=bugs)
    with TestClient(app) as client:
        return spec, run_suite(spec, client)


def _ids(spec, predicate):
    return {c.id for c in compile_contract_suite(spec) if predicate(c)}


def test_same_row_cases_present_and_correct_passes():
    spec, result = _run(SAME_ROW)
    case_ids = {c.id for c in compile_contract_suite(spec)}
    assert {
        "computed_field:value:available",
        "computed_field:client_ignored:available",
        "computed_field:recompute:available",
    } <= case_ids
    assert result.all_passed, [r for r in result.results if not r[1]]


def test_aggregate_cases_present_and_correct_passes():
    spec, result = _run(AGGREGATE)
    case_ids = {c.id for c in compile_contract_suite(spec)}
    assert {
        "computed_field:initial:balance",
        "computed_field:aggregate:balance",
        "computed_field:recompute:balance",
        "computed_field:client_ignored:balance",
    } <= case_ids
    assert result.all_passed, [r for r in result.results if not r[1]]


def test_aggregate_of_product_correct_passes():
    spec, result = _run(AGGREGATE_PRODUCT)
    assert any(
        c.id.startswith("computed_field:aggregate:total_cents")
        for c in compile_contract_suite(spec)
    )
    assert result.all_passed, [r for r in result.results if not r[1]]


@pytest.mark.parametrize("fixture", [SAME_ROW, AGGREGATE, AGGREGATE_PRODUCT])
def test_wrong_computed_bug_fails_exactly_computed_field(fixture):
    spec, result = _run(fixture, bugs=frozenset({BUG_WRONG_COMPUTED}))
    expected = _ids(spec, lambda c: c.category == "computed_field")
    assert expected
    assert set(result.failed_ids) == expected, (
        f"{fixture['id']}: BUG_WRONG_COMPUTED not isolated to computed_field.\n"
        f"  expected: {sorted(expected)}\n  actual:   {sorted(result.failed_ids)}"
    )

"""Oracle validation for the business-rule compiler dimensions (T-1.2 (b)).

The decisive proof for the hard tier: for each of the four business-rule
dimensions, a correct reference service passes every contract case, and a
surgically-broken one fails on EXACTLY that dimension's cases — never fewer
(lenient = silently invalid hard tier), never more (false alarm).

Broken variants (mirroring the prompt's hard constraint):
* state_machine    — allows an illegal state transition;
* cross_field      — accepts end_at < start_at (a violating combination);
* relationship     — lets a child reference a non-existent parent;
* composite_unique — accepts a duplicate composite key.
"""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from harness.compiler import compile_contract_suite, run_suite
from harness.reference.service import (
    BUG_ALLOW_ILLEGAL_TRANSITION,
    BUG_SKIP_COMPOSITE_UNIQUE,
    BUG_SKIP_CROSS_FIELD,
    BUG_SKIP_PARENT_CHECK,
    build_app,
)
from harness.specschema import parse_spec

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
STATE_AND_CROSS = {
    "id": "fx_orders",
    "title": "Orders (state_machine + cross_field fixture)",
    "tier": "hard",
    "resource": {
        "name": "order",
        "path": "/orders",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {
                "name": "status",
                "type": "enum",
                "values": ["pending", "paid", "shipped", "delivered", "cancelled"],
                "default": "pending",
            },
            {"name": "total_cents", "type": "integer", "required": True, "min": 0},
            {"name": "discount_cents", "type": "integer", "required": True, "min": 0},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/orders", "success": 201},
        "get": {"method": "GET", "path": "/orders/{id}", "success": 200, "missing": 404},
        "update": {
            "method": "PATCH",
            "path": "/orders/{id}",
            "success": 200,
            "missing": 404,
            "partial": True,
        },
        "delete": {"method": "DELETE", "path": "/orders/{id}", "success": 204, "missing": 404},
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [
        {
            "kind": "state_machine",
            "field": "status",
            "initial": "pending",
            "transitions": {
                "pending": ["paid", "cancelled"],
                "paid": ["shipped", "cancelled"],
                "shipped": ["delivered"],
                "delivered": [],
                "cancelled": [],
            },
            "on_illegal": 409,
        },
        {"kind": "cross_field", "fields": ["discount_cents", "total_cents"], "op": "lte"},
    ],
}

COMPOSITE = {
    "id": "fx_inventory",
    "title": "Inventory (composite_unique fixture)",
    "tier": "hard",
    "resource": {
        "name": "inventory_item",
        "path": "/inventory",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "sku", "type": "string", "required": True, "min_len": 1, "max_len": 40},
            {"name": "warehouse", "type": "string", "required": True, "min_len": 1, "max_len": 40},
            {"name": "on_hand", "type": "integer", "required": True, "min": 0},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/inventory", "success": 201},
        "get": {"method": "GET", "path": "/inventory/{id}", "success": 200, "missing": 404},
        "update": {
            "method": "PATCH",
            "path": "/inventory/{id}",
            "success": 200,
            "missing": 404,
            "partial": True,
        },
        "delete": {"method": "DELETE", "path": "/inventory/{id}", "success": 204, "missing": 404},
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [
        {"kind": "composite_unique", "fields": ["sku", "warehouse"], "on_conflict": 409}
    ],
}

# Relationship — primary is the PARENT (restrict-on-delete); child is the related resource.
REL_PARENT = {
    "id": "fx_projects",
    "title": "Projects (relationship parent-primary fixture)",
    "tier": "hard",
    "resource": {
        "name": "project",
        "path": "/projects",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 80},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/projects", "success": 201},
        "get": {"method": "GET", "path": "/projects/{id}", "success": 200, "missing": 404},
        "delete": {"method": "DELETE", "path": "/projects/{id}", "success": 204, "missing": 404},
    },
    "related": {
        "name": "task",
        "path": "/tasks",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "project_id", "type": "ref", "ref": "project", "required": True},
            {"name": "title", "type": "string", "required": True, "min_len": 1, "max_len": 120},
        ],
        "endpoints": {
            "create": {"method": "POST", "path": "/tasks", "success": 201},
            "get": {"method": "GET", "path": "/tasks/{id}", "success": 200, "missing": 404},
            "delete": {"method": "DELETE", "path": "/tasks/{id}", "success": 204, "missing": 404},
        },
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [
        {
            "kind": "relationship",
            "parent": "project",
            "child": "task",
            "ref_field": "project_id",
            "on_missing_parent": 422,
            "on_parent_delete": "restrict",
        }
    ],
}

# Relationship — primary is the CHILD (holds the ref to a related parent).
REL_CHILD = {
    "id": "fx_reservations",
    "title": "Reservations (relationship child-primary fixture)",
    "tier": "hard",
    "resource": {
        "name": "reservation",
        "path": "/reservations",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "room_id", "type": "ref", "ref": "room", "required": True},
            {"name": "guest", "type": "string", "required": True, "min_len": 1, "max_len": 80},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/reservations", "success": 201},
        "get": {"method": "GET", "path": "/reservations/{id}", "success": 200, "missing": 404},
        "delete": {
            "method": "DELETE",
            "path": "/reservations/{id}",
            "success": 204,
            "missing": 404,
        },
    },
    "related": {
        "name": "room",
        "path": "/rooms",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "name", "type": "string", "required": True, "min_len": 1, "max_len": 80},
        ],
        "endpoints": {
            "create": {"method": "POST", "path": "/rooms", "success": 201},
            "get": {"method": "GET", "path": "/rooms/{id}", "success": 200, "missing": 404},
        },
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [
        {
            "kind": "relationship",
            "parent": "room",
            "child": "reservation",
            "ref_field": "room_id",
            "on_missing_parent": 422,
        }
    ],
}


def _run(spec_dict, bugs=frozenset()):
    spec = parse_spec(copy.deepcopy(spec_dict))
    app = build_app(copy.deepcopy(spec_dict), bugs=bugs)
    with TestClient(app) as client:
        return spec, run_suite(spec, client)


def _ids(spec, predicate):
    return {c.id for c in compile_contract_suite(spec) if predicate(c)}


# --------------------------------------------------------------------------- #
# state_machine
# --------------------------------------------------------------------------- #
def test_state_machine_correct_passes():
    spec, result = _run(STATE_AND_CROSS)
    case_ids = {c.id for c in compile_contract_suite(spec)}
    assert {
        "state_machine:create_initial:status",
        "state_machine:legal_path:status",
        "state_machine:illegal_transition:status",
        "state_machine:terminal_rejects:status",
    } <= case_ids
    assert result.all_passed, [r for r in result.results if not r[1]]


def test_allow_illegal_transition_bug_fails_exactly_state_machine():
    spec, result = _run(STATE_AND_CROSS, bugs=frozenset({BUG_ALLOW_ILLEGAL_TRANSITION}))
    expected = _ids(spec, lambda c: c.category == "state_machine" and ":illegal" in c.id) | _ids(
        spec, lambda c: c.id.startswith("state_machine:terminal_rejects")
    )
    assert set(result.failed_ids) == expected
    assert expected  # non-empty (the bug is actually caught)


# --------------------------------------------------------------------------- #
# cross_field
# --------------------------------------------------------------------------- #
def test_cross_field_correct_passes():
    spec, result = _run(STATE_AND_CROSS)
    assert "cross_field:violation:discount_cents" in {c.id for c in compile_contract_suite(spec)}
    assert result.all_passed, [r for r in result.results if not r[1]]


def test_skip_cross_field_bug_fails_exactly_cross_field_violation():
    spec, result = _run(STATE_AND_CROSS, bugs=frozenset({BUG_SKIP_CROSS_FIELD}))
    assert set(result.failed_ids) == _ids(spec, lambda c: c.id.startswith("cross_field:violation:"))
    assert result.failed_ids


# --------------------------------------------------------------------------- #
# composite_unique
# --------------------------------------------------------------------------- #
def test_composite_unique_correct_passes():
    spec, result = _run(COMPOSITE)
    case_ids = {c.id for c in compile_contract_suite(spec)}
    assert any(c.startswith("composite_unique:conflict") for c in case_ids)
    assert any(c.startswith("composite_unique:partial_overlap") for c in case_ids)
    assert result.all_passed, [r for r in result.results if not r[1]]


def test_skip_composite_unique_bug_fails_exactly_conflict():
    spec, result = _run(COMPOSITE, bugs=frozenset({BUG_SKIP_COMPOSITE_UNIQUE}))
    assert set(result.failed_ids) == _ids(
        spec, lambda c: c.id.startswith("composite_unique:conflict")
    )
    assert result.failed_ids


# --------------------------------------------------------------------------- #
# relationship (both directions)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("fixture", [REL_PARENT, REL_CHILD])
def test_relationship_correct_passes(fixture):
    spec, result = _run(fixture)
    assert any(c.id.startswith("relationship:missing_parent") for c in compile_contract_suite(spec))
    assert result.all_passed, [r for r in result.results if not r[1]]


def test_relationship_parent_primary_has_restrict_delete():
    spec, result = _run(REL_PARENT)
    assert any(
        c.id.startswith("relationship:restrict_delete") for c in compile_contract_suite(spec)
    )
    assert result.all_passed


@pytest.mark.parametrize("fixture", [REL_PARENT, REL_CHILD])
def test_skip_parent_check_bug_fails_exactly_relationship(fixture):
    spec, result = _run(fixture, bugs=frozenset({BUG_SKIP_PARENT_CHECK}))
    expected = _ids(spec, lambda c: c.id.startswith("relationship:missing_parent")) | _ids(
        spec, lambda c: c.id.startswith("relationship:restrict_delete")
    )
    assert set(result.failed_ids) == expected
    assert expected

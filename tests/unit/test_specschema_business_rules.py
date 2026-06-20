"""Unit tests for typed business-rule + second-resource parsing (T-1.2 (b))."""

from __future__ import annotations

from harness.specschema import (
    CompositeUniqueRule,
    CrossFieldRule,
    RelationshipRule,
    StateMachineRule,
    business_rules_of,
    parse_spec,
)

STATE_SPEC = {
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
                "values": ["pending", "paid", "shipped", "delivered", "cancelled"],
                "default": "pending",
            },
            {"name": "total_cents", "type": "integer", "required": True, "min": 0},
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

REL_SPEC = {
    "id": "reservations",
    "title": "Reservations",
    "tier": "hard",
    "resource": {
        "name": "reservation",
        "path": "/reservations",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "room_id", "type": "ref", "ref": "room", "required": True},
            {"name": "slot", "type": "integer", "required": True, "min": 0},
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
            "delete": {"method": "DELETE", "path": "/rooms/{id}", "success": 204, "missing": 404},
        },
    },
    "business_rules": [
        {
            "kind": "relationship",
            "parent": "room",
            "child": "reservation",
            "ref_field": "room_id",
            "on_missing_parent": 422,
            "on_parent_delete": "restrict",
        },
        {"kind": "composite_unique", "fields": ["room_id", "slot"], "on_conflict": 409},
    ],
}


def test_parses_state_machine_and_cross_field():
    spec = parse_spec(STATE_SPEC)
    rules = business_rules_of(spec)
    sm = next(r for r in rules if isinstance(r, StateMachineRule))
    assert sm.field == "status"
    assert sm.initial == "pending"
    assert sm.transitions["pending"] == ["paid", "cancelled"]
    assert sm.on_illegal == 409
    cf = next(r for r in rules if isinstance(r, CrossFieldRule))
    assert cf.fields == ("discount_cents", "total_cents")
    assert cf.op == "lte"
    assert cf.on_violation == 422  # default


def test_parses_relationship_and_composite_unique_and_related_resource():
    spec = parse_spec(REL_SPEC)
    assert spec.related is not None
    assert spec.related.resource.name == "room"
    assert spec.related.endpoints.create is not None
    assert spec.related.endpoints.delete is not None
    rules = business_rules_of(spec)
    rel = next(r for r in rules if isinstance(r, RelationshipRule))
    assert rel.parent == "room" and rel.child == "reservation"
    assert rel.ref_field == "room_id"
    assert rel.on_parent_delete == "restrict"
    cu = next(r for r in rules if isinstance(r, CompositeUniqueRule))
    assert cu.fields == ("room_id", "slot")


def test_business_rules_raw_list_preserved_for_serialization():
    # the raw dict list stays intact (runner._spec_to_dict / fake effector serialize it)
    spec = parse_spec(STATE_SPEC)
    assert isinstance(spec.business_rules, list)
    assert spec.business_rules[0]["kind"] == "state_machine"

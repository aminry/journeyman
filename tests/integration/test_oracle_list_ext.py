"""Oracle validation for the list-dimension compiler extensions (T-1.2 (b)).

Same discipline as tests/integration/test_oracle.py, applied to the NEW list cases:

* ``list:basic`` — the easy-tier list endpoint (no pagination) returns the created
  rows as a JSON array;
* ``list:filter:multi`` — a conjunction of ≥2 filters (AND semantics);
* ``list:sort:multi`` — a composite ``?sort=a,-b`` tie-break.

For each new dimension: a correct service passes every case, and a surgically-broken
service fails on EXACTLY that dimension's case(s) — never more, never fewer. A lenient
list oracle would silently let a filter-/sort-skipping service pass.
"""

from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from harness.compiler import compile_contract_suite, run_suite
from harness.reference.service import (
    BUG_IGNORE_SECONDARY_FILTER,
    BUG_IGNORE_SECONDARY_SORT,
    BUG_LIST_NOT_ARRAY,
    build_app,
)
from harness.specschema import parse_spec

# --------------------------------------------------------------------------- #
# Fixtures (inline dicts so both parse_spec and build_app see the same source)
# --------------------------------------------------------------------------- #
EASY_LIST = {
    "id": "fx_items",
    "title": "Items (easy list fixture)",
    "tier": "easy",
    "resource": {
        "name": "item",
        "path": "/items",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "label", "type": "string", "required": True, "min_len": 1, "max_len": 80},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/items", "success": 201},
        "get": {"method": "GET", "path": "/items/{id}", "success": 200, "missing": 404},
        "list": {"method": "GET", "path": "/items", "success": 200},
        "delete": {"method": "DELETE", "path": "/items/{id}", "success": 204, "missing": 404},
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [],
}

LIST_RICH = {
    "id": "fx_widgets",
    "title": "Widgets (multi-filter/sort fixture)",
    "tier": "hard",
    "resource": {
        "name": "widget",
        "path": "/widgets",
        "fields": [
            {"name": "id", "type": "uuid", "generated": True, "readonly": True},
            {"name": "kind", "type": "enum", "required": True, "values": ["a", "b", "c"]},
            {"name": "active", "type": "boolean", "default": True},
            {"name": "rank", "type": "integer", "required": True, "min": 0, "max": 100},
            {"name": "score", "type": "integer", "required": True, "min": 0, "max": 100},
        ],
    },
    "endpoints": {
        "create": {"method": "POST", "path": "/widgets", "success": 201},
        "get": {"method": "GET", "path": "/widgets/{id}", "success": 200, "missing": 404},
        "list": {
            "method": "GET",
            "path": "/widgets",
            "success": 200,
            "pagination": {
                "limit_param": "limit",
                "offset_param": "offset",
                "default_limit": 20,
                "max_limit": 100,
            },
            "filters": ["kind", "active"],
            "sort": ["rank", "score"],
        },
        "delete": {"method": "DELETE", "path": "/widgets/{id}", "success": 204, "missing": 404},
    },
    "rules": {"on_validation_error": 422, "on_unique_conflict": 409},
    "business_rules": [],
}


def _run(spec_dict, bugs=frozenset()):
    spec = parse_spec(copy.deepcopy(spec_dict))
    app = build_app(copy.deepcopy(spec_dict), bugs=bugs)
    with TestClient(app) as client:
        return spec, run_suite(spec, client)


def _ids(spec, predicate):
    return {c.id for c in compile_contract_suite(spec) if predicate(c)}


def test_easy_list_basic_case_present_and_passes():
    spec, result = _run(EASY_LIST)
    assert "list:basic" in {c.id for c in compile_contract_suite(spec)}
    assert result.all_passed, [r for r in result.results if not r[1]]


def test_list_not_array_bug_fails_exactly_list_basic():
    spec, result = _run(EASY_LIST, bugs=frozenset({BUG_LIST_NOT_ARRAY}))
    assert set(result.failed_ids) == {"list:basic"}


def test_rich_list_has_multi_filter_and_multi_sort_and_passes():
    spec, result = _run(LIST_RICH)
    case_ids = {c.id for c in compile_contract_suite(spec)}
    assert "list:filter:multi" in case_ids
    assert "list:sort:multi" in case_ids
    # a paginated list has no list:basic (pagination cases cover the endpoint)
    assert "list:basic" not in case_ids
    assert result.all_passed, [r for r in result.results if not r[1]]


def test_ignore_secondary_filter_bug_fails_exactly_multi_filter():
    spec, result = _run(LIST_RICH, bugs=frozenset({BUG_IGNORE_SECONDARY_FILTER}))
    assert set(result.failed_ids) == {"list:filter:multi"}


def test_ignore_secondary_sort_bug_fails_exactly_multi_sort():
    spec, result = _run(LIST_RICH, bugs=frozenset({BUG_IGNORE_SECONDARY_SORT}))
    assert set(result.failed_ids) == {"list:sort:multi"}

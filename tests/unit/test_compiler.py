"""Unit tests for the spec -> contract-suite compiler (domain.md §3).

These assert the *coverage* the compiler must emit from example_books.spec.yaml.
Whether the cases actually pass/fail correctly against a service is proven
separately by the oracle integration test (tests/integration/test_oracle.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.compiler import compile_contract_suite
from harness.specschema import load_spec

REPO = Path(__file__).resolve().parents[2]
BOOKS = REPO / "experiments" / "phase_minus_1" / "instances" / "example_books.spec.yaml"


@pytest.fixture
def suite():
    return compile_contract_suite(load_spec(BOOKS))


def ids(suite):
    return {c.id for c in suite}


def categories(suite):
    return {c.category for c in suite}


def test_covers_all_top_level_categories(suite) -> None:
    assert {
        "create",
        "validation",
        "unique",
        "get",
        "update",
        "delete",
        "list",
        "default",
        "server_managed",
    } <= categories(suite)


def test_create_valid_case_present(suite) -> None:
    c = next(c for c in suite if c.id == "create:valid")
    assert c.expected_status == 201


def test_missing_required_field_cases(suite) -> None:
    s = ids(suite)
    for fname in ("title", "author", "isbn", "price_cents", "published_year", "genre"):
        assert f"create:missing:{fname}" in s
    # in_stock has a default and is NOT required -> no missing case
    assert "create:missing:in_stock" not in s
    # each missing-required case asserts a 422
    for c in suite:
        if c.category == "create" and c.id.startswith("create:missing:"):
            assert c.expected_status == 422


def test_validation_boundary_cases(suite) -> None:
    s = ids(suite)
    assert "validation:min_len:title:invalid" in s
    assert "validation:max_len:title:invalid" in s
    assert "validation:min:published_year:invalid" in s
    assert "validation:max:published_year:invalid" in s
    assert "validation:pattern:isbn:invalid" in s
    assert "validation:enum:genre:invalid" in s
    # every invalid probe expects 422; the matching valid probe expects success
    for c in suite:
        if c.category == "validation":
            assert c.expected_status in (422, 201)


def test_default_and_server_managed_cases(suite) -> None:
    s = ids(suite)
    assert "default:in_stock" in s
    assert "server_managed:id" in s
    assert "server_managed:created_at" in s


def test_unique_conflict_case(suite) -> None:
    c = next(c for c in suite if c.id == "unique:conflict:isbn")
    assert c.expected_status == 409
    assert c.field == "isbn"


def test_get_cases(suite) -> None:
    s = ids(suite)
    assert "get:found" in s
    assert next(c for c in suite if c.id == "get:missing").expected_status == 404


def test_update_cases(suite) -> None:
    s = ids(suite)
    assert any(i.startswith("update:partial:") for i in s)
    assert "update:missing" in s
    assert any(i.startswith("update:readonly:") for i in s)
    assert next(c for c in suite if c.id == "update:missing").expected_status == 404


def test_delete_cases(suite) -> None:
    s = ids(suite)
    assert "delete:ok" in s
    assert next(c for c in suite if c.id == "delete:missing").expected_status == 404


def test_list_pagination_filter_sort_cases(suite) -> None:
    s = ids(suite)
    assert {"list:default_limit", "list:limit", "list:offset", "list:max_limit"} <= s
    assert "list:filter:genre" in s
    assert "list:filter:in_stock" in s
    assert "list:sort:published_year:asc" in s
    assert "list:sort:published_year:desc" in s
    assert "list:sort:price_cents:asc" in s


def test_case_ids_are_unique(suite) -> None:
    all_ids = [c.id for c in suite]
    assert len(all_ids) == len(set(all_ids))


def test_every_case_is_runnable(suite) -> None:
    for c in suite:
        assert callable(c.run)

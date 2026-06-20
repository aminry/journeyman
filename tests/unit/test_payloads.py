"""Unit tests for valid/boundary payload generation (domain.md §3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.payloads import boundary_cases, valid_payload, valid_value
from harness.specschema import Field, load_spec

REPO = Path(__file__).resolve().parents[2]
BOOKS = REPO / "experiments" / "phase_minus_1" / "instances" / "example_books.spec.yaml"


@pytest.fixture
def books():
    return load_spec(BOOKS)


def test_valid_value_respects_integer_range() -> None:
    f = Field(name="n", type="integer", min=1450, max=2026)
    for seed in range(5):
        v = valid_value(f, seed)
        assert isinstance(v, int) and 1450 <= v <= 2026


def test_valid_value_respects_string_length() -> None:
    f = Field(name="s", type="string", min_len=1, max_len=3)
    for seed in range(5):
        v = valid_value(f, seed)
        assert isinstance(v, str) and 1 <= len(v) <= 3


def test_valid_value_respects_pattern() -> None:
    f = Field(name="isbn", type="string", pattern="^[0-9]{13}$")
    for seed in range(5):
        v = valid_value(f, seed)
        assert re.match("^[0-9]{13}$", v), v


def test_valid_value_enum_from_values() -> None:
    f = Field(name="g", type="enum", values=["a", "b", "c"])
    assert valid_value(f, 0) in {"a", "b", "c"}


def test_valid_payload_has_writable_required_fields(books) -> None:
    p = valid_payload(books)
    for name in ("title", "author", "isbn", "price_cents", "published_year", "genre"):
        assert name in p
    # server-managed fields are never sent by a client
    assert "id" not in p and "created_at" not in p


def test_valid_payload_satisfies_constraints(books) -> None:
    p = valid_payload(books)
    assert re.match("^[0-9]{13}$", p["isbn"])
    assert 1450 <= p["published_year"] <= 2026
    assert p["genre"] in ["fiction", "nonfiction", "sci_fi", "biography"]
    assert p["price_cents"] >= 0


def test_distinct_seeds_give_distinct_unique_values(books) -> None:
    a = valid_payload(books, seed=1)
    b = valid_payload(books, seed=2)
    assert a["isbn"] != b["isbn"]


def test_boundary_cases_for_length_field() -> None:
    f = Field(name="title", type="string", required=True, min_len=1, max_len=200)
    cases = boundary_cases(f)
    kinds = {(c.kind, c.valid) for c in cases}
    assert ("min_len", False) in kinds  # "" rejected
    assert ("max_len", False) in kinds  # 201 chars rejected
    # an over-length violating value really is over length
    over = next(c for c in cases if c.kind == "max_len" and not c.valid)
    assert len(over.value) == 201


def test_boundary_cases_for_int_range() -> None:
    f = Field(name="published_year", type="integer", required=True, min=1450, max=2026)
    cases = boundary_cases(f)
    kinds = {(c.kind, c.valid) for c in cases}
    assert ("min", False) in kinds and ("min", True) in kinds
    assert ("max", False) in kinds and ("max", True) in kinds
    lo_bad = next(c for c in cases if c.kind == "min" and not c.valid)
    lo_ok = next(c for c in cases if c.kind == "min" and c.valid)
    assert lo_bad.value == 1449 and lo_ok.value == 1450


def test_boundary_cases_for_pattern_and_enum() -> None:
    isbn = Field(name="isbn", type="string", pattern="^[0-9]{13}$")
    assert any(c.kind == "pattern" and not c.valid for c in boundary_cases(isbn))
    genre = Field(name="genre", type="enum", values=["a", "b"])
    bad = next(c for c in boundary_cases(genre) if c.kind == "enum" and not c.valid)
    assert bad.value not in ["a", "b"]


def test_field_without_constraints_has_no_boundary_cases() -> None:
    f = Field(name="plain", type="string")
    assert boundary_cases(f) == []


def test_valid_value_number_respects_range() -> None:
    f = Field(name="amt", type="number", min=0, max=10)
    for seed in range(5):
        v = valid_value(f, seed)
        assert isinstance(v, float) and 0.0 <= v <= 10.0


def test_valid_value_datetime_is_isoish() -> None:
    f = Field(name="when", type="datetime")
    v = valid_value(f, 3)
    assert isinstance(v, str) and v.startswith("2026-") and v.endswith("Z")


def test_valid_value_uuid_and_ref_shape() -> None:
    assert valid_value(Field(name="id", type="uuid"), 1).count("-") == 4
    assert valid_value(Field(name="parent", type="ref", ref="x"), 2).count("-") == 4


def test_boundary_min_len_zero_only_valid_edge() -> None:
    f = Field(name="opt", type="string", min_len=0)
    kinds = {(c.kind, c.valid) for c in boundary_cases(f)}
    # min_len 0 has no "below" edge; only the at-min (valid) edge
    assert ("min_len", True) in kinds
    assert ("min_len", False) not in kinds

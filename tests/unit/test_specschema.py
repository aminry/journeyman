"""Unit tests for the instance-spec loader (domain.md §2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.specschema import InstanceSpec, SpecError, load_spec

REPO = Path(__file__).resolve().parents[2]
BOOKS = REPO / "experiments" / "phase_minus_1" / "instances" / "example_books.spec.yaml"


@pytest.fixture
def books() -> InstanceSpec:
    return load_spec(BOOKS)


def test_loads_top_level_identity(books: InstanceSpec) -> None:
    assert books.id == "books"
    assert books.tier == "medium"
    assert books.resource.name == "book"
    assert books.resource.path == "/books"


def test_parses_field_constraints(books: InstanceSpec) -> None:
    isbn = books.resource.field("isbn")
    assert isbn.required is True
    assert isbn.unique is True
    assert isbn.pattern == "^[0-9]{13}$"

    title = books.resource.field("title")
    assert title.required is True
    assert title.min_len == 1
    assert title.max_len == 200

    year = books.resource.field("published_year")
    assert year.type == "integer"
    assert year.min == 1450
    assert year.max == 2026


def test_parses_generated_and_default_fields(books: InstanceSpec) -> None:
    pk = books.resource.field("id")
    assert pk.generated is True
    assert pk.readonly is True

    in_stock = books.resource.field("in_stock")
    assert in_stock.type == "boolean"
    assert in_stock.default is True

    genre = books.resource.field("genre")
    assert genre.type == "enum"
    assert genre.values == ["fiction", "nonfiction", "sci_fi", "biography"]


def test_parses_endpoints(books: InstanceSpec) -> None:
    assert books.endpoints.create.success == 201
    assert books.endpoints.get.missing == 404
    assert books.endpoints.update.partial is True
    assert books.endpoints.delete.success == 204

    pag = books.endpoints.list.pagination
    assert pag.default_limit == 20
    assert pag.max_limit == 100
    assert pag.limit_param == "limit"
    assert pag.offset_param == "offset"
    assert books.endpoints.list.filters == ["genre", "in_stock"]
    assert books.endpoints.list.sort == ["published_year", "price_cents"]


def test_parses_rules(books: InstanceSpec) -> None:
    assert books.rules.on_validation_error == 422
    assert books.rules.on_unique_conflict == 409
    assert books.rules.timestamps_immutable is True
    assert books.business_rules == []


def test_required_writable_fields_excludes_generated(books: InstanceSpec) -> None:
    names = [f.name for f in books.resource.required_writable_fields()]
    assert "title" in names and "isbn" in names
    assert "id" not in names and "created_at" not in names


def test_unknown_path_raises(books: InstanceSpec) -> None:
    with pytest.raises(KeyError):
        books.resource.field("nope")


def test_missing_file_raises() -> None:
    with pytest.raises(SpecError):
        load_spec(REPO / "does" / "not" / "exist.spec.yaml")

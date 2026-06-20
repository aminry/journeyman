"""Oracle validation (the prompt's hard constraint "VALIDATE THE ORACLE").

Proves the generated contract suite is neither too lenient nor too strict:

* against a deliberately-correct reference service -> ALL cases pass;
* against a deliberately-broken one -> it fails on EXACTLY the cases that
  correspond to the injected bugs, and passes everything else.

A lenient oracle would silently invalidate the whole Phase -1 gate, so this test
is the linchpin. It runs in-process via FastAPI's TestClient (no real port, no
spend).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from harness.compiler import compile_contract_suite, run_suite
from harness.reference.service import (
    BUG_ACCEPT_CLIENT_FIELDS,
    BUG_IGNORE_DEFAULT,
    BUG_IGNORE_FILTER,
    BUG_IGNORE_MAX_LIMIT,
    BUG_IGNORE_SECONDARY_FILTER,
    BUG_IGNORE_SECONDARY_SORT,
    BUG_NO_404,
    BUG_SKIP_CONSTRAINTS,
    BUG_SKIP_REQUIRED,
    BUG_SKIP_UNIQUE,
    BUG_WRONG_ENVELOPE,
    build_app,
)
from harness.specschema import load_spec

REPO = Path(__file__).resolve().parents[2]
BOOKS = REPO / "experiments" / "phase_minus_1" / "instances" / "example_books.spec.yaml"


@pytest.fixture(scope="module")
def spec_obj():
    return load_spec(BOOKS)


@pytest.fixture(scope="module")
def spec_dict():
    return yaml.safe_load(BOOKS.read_text())


def test_correct_service_passes_every_case(spec_obj, spec_dict) -> None:
    app = build_app(spec_dict)
    with TestClient(app) as client:
        result = run_suite(spec_obj, client)
    failures = [(cid, detail) for cid, ok, detail in result.results if not ok]
    assert result.all_passed, f"correct service failed {len(failures)} cases:\n" + "\n".join(
        f"  {cid}: {detail}" for cid, detail in failures
    )
    # sanity: the suite is non-trivial
    assert result.total >= 30


def test_broken_service_fails_exactly_the_buggy_cases(spec_obj, spec_dict) -> None:
    bugs = frozenset({BUG_SKIP_REQUIRED, BUG_IGNORE_MAX_LIMIT})
    app = build_app(spec_dict, bugs=bugs)
    with TestClient(app) as client:
        result = run_suite(spec_obj, client)

    required = [f.name for f in spec_obj.resource.required_writable_fields()]
    expected_failures = {f"create:missing:{name}" for name in required} | {"list:max_limit"}

    assert set(result.failed_ids) == expected_failures, (
        "broken service did not fail on exactly the buggy cases.\n"
        f"  expected: {sorted(expected_failures)}\n"
        f"  actual:   {sorted(result.failed_ids)}"
    )


def test_broken_service_still_passes_everything_else(spec_obj, spec_dict) -> None:
    """A surgical bug must not silently break unrelated cases (no false alarms)."""
    bugs = frozenset({BUG_SKIP_REQUIRED, BUG_IGNORE_MAX_LIMIT})
    app = build_app(spec_dict, bugs=bugs)
    with TestClient(app) as client:
        result = run_suite(spec_obj, client)
    # every non-buggy case still passes
    buggy = set(result.failed_ids)
    for cid, ok, detail in result.results:
        if cid not in buggy:
            assert ok, f"unexpected failure on {cid}: {detail}"


def test_single_injected_bug_is_isolated(spec_obj, spec_dict) -> None:
    """Each bug, alone, fails only its own cases — proves per-case attribution."""
    app = build_app(spec_dict, bugs=frozenset({BUG_IGNORE_MAX_LIMIT}))
    with TestClient(app) as client:
        result = run_suite(spec_obj, client)
    assert set(result.failed_ids) == {"list:max_limit"}


def _ids(spec_obj, predicate):
    return {c.id for c in compile_contract_suite(spec_obj) if predicate(c)}


def test_suite_catches_a_bug_in_every_dimension(spec_obj, spec_dict) -> None:
    """The decisive oracle proof: inject a surgical bug in each spec dimension and
    assert the suite fails on EXACTLY the cases for that dimension — no misses
    (lenient = invalid experiment) and no collateral failures (false alarms)."""
    required = [f.name for f in spec_obj.resource.required_writable_fields()]

    expectations = {
        BUG_SKIP_REQUIRED: {f"create:missing:{n}" for n in required},
        BUG_IGNORE_MAX_LIMIT: {"list:max_limit"},
        BUG_SKIP_CONSTRAINTS: _ids(
            spec_obj, lambda c: c.category == "validation" and c.id.endswith(":invalid")
        ),
        BUG_ACCEPT_CLIENT_FIELDS: (
            _ids(spec_obj, lambda c: c.category == "server_managed")
            | _ids(spec_obj, lambda c: c.id.startswith("update:readonly:"))
        ),
        BUG_IGNORE_FILTER: _ids(spec_obj, lambda c: c.id.startswith("list:filter:")),
        BUG_IGNORE_SECONDARY_FILTER: {"list:filter:multi"},
        BUG_IGNORE_SECONDARY_SORT: {"list:sort:multi"},
        BUG_SKIP_UNIQUE: _ids(spec_obj, lambda c: c.category == "unique"),
        BUG_IGNORE_DEFAULT: _ids(spec_obj, lambda c: c.category == "default"),
        BUG_NO_404: {"get:missing", "update:missing", "delete:missing", "delete:ok"},
        # wrong 422 envelope -> only the field-naming (missing-required) cases fail;
        # constraint/type :invalid cases only assert the 422 status, so they pass.
        BUG_WRONG_ENVELOPE: _ids(spec_obj, lambda c: c.id.startswith("create:missing:")),
    }

    for bug, expected in expectations.items():
        app = build_app(spec_dict, bugs=frozenset({bug}))
        with TestClient(app) as client:
            result = run_suite(spec_obj, client)
        assert set(result.failed_ids) == expected, (
            f"bug {bug!r} did not fail exactly its dimension.\n"
            f"  expected: {sorted(expected)}\n"
            f"  actual:   {sorted(result.failed_ids)}"
        )

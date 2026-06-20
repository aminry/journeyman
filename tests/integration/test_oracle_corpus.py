"""Oracle validation over the REAL 30-instance corpus (T-1.2 (a)+(c)).

Two guarantees, on the actual specs the experiment will run (not just fixtures):

1. Every instance spec compiles to a contract suite that a CORRECT reference
   service passes in full — the corpus is internally consistent and buildable.
2. For each hard spec, a surgically-broken reference service fails on EXACTLY the
   broken dimension's cases — the hard-tier oracle is strict, not lenient (a
   lenient business-rules oracle silently invalidates the tier with the headroom).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from harness.compiler import compile_contract_suite, run_suite
from harness.payloads import valid_value
from harness.reference.service import (
    BUG_ALLOW_ILLEGAL_TRANSITION,
    BUG_IGNORE_SECONDARY_FILTER,
    BUG_IGNORE_SECONDARY_SORT,
    BUG_SKIP_COMPOSITE_UNIQUE,
    BUG_SKIP_CROSS_FIELD,
    BUG_SKIP_PARENT_CHECK,
    BUG_SKIP_REQUIRED,
    build_app,
)
from harness.specschema import load_spec

REPO = Path(__file__).resolve().parents[2]
INSTANCES = REPO / "experiments" / "phase_minus_1" / "instances"
SPEC_PATHS = sorted(INSTANCES.glob("*.spec.yaml"))


def _spec_and_result(path: Path, bugs=frozenset()):
    spec = load_spec(path)
    spec_dict = yaml.safe_load(path.read_text())
    app = build_app(spec_dict, bugs=bugs)
    with TestClient(app) as client:
        return spec, run_suite(spec, client)


def _ids(spec, predicate):
    return {c.id for c in compile_contract_suite(spec) if predicate(c)}


def test_corpus_is_complete():
    # 10 easy + 10 medium (incl. example_books) + 10 hard = 30
    assert len(SPEC_PATHS) == 30
    tiers = [load_spec(p).tier for p in SPEC_PATHS]
    assert tiers.count("easy") == 10
    assert tiers.count("medium") == 10
    assert tiers.count("hard") == 10


@pytest.mark.parametrize("path", SPEC_PATHS, ids=[p.stem for p in SPEC_PATHS])
def test_correct_service_passes_every_case(path):
    spec, result = _spec_and_result(path)
    failures = [(cid, d) for cid, ok, d in result.results if not ok]
    assert result.all_passed, f"{path.name} failed {len(failures)}:\n" + "\n".join(
        f"  {cid}: {d}" for cid, d in failures
    )
    assert result.total >= 12  # every instance exercises a non-trivial suite


# -- per-dimension surgical strictness on the real hard specs ----------------- #
def _check(spec_name: str, bug: str, expected_predicate) -> None:
    path = INSTANCES / spec_name
    spec, result = _spec_and_result(path, bugs=frozenset({bug}))
    expected = _ids(spec, expected_predicate)
    assert expected, f"{spec_name}: no cases matched the dimension predicate"
    assert set(result.failed_ids) == expected, (
        f"{spec_name} + {bug}: failures not exactly the broken dimension.\n"
        f"  expected: {sorted(expected)}\n  actual:   {sorted(result.failed_ids)}"
    )


def test_orders_state_machine_strict():
    _check(
        "h01_orders.spec.yaml",
        BUG_ALLOW_ILLEGAL_TRANSITION,
        lambda c: c.id.startswith("state_machine:illegal_transition")
        or c.id.startswith("state_machine:terminal_rejects"),
    )


def test_invoices_immutability_strict():
    # locked_after=[paid] adds an immutability case alongside illegal/terminal
    _check(
        "h10_invoices.spec.yaml",
        BUG_ALLOW_ILLEGAL_TRANSITION,
        lambda c: c.id.startswith("state_machine:illegal_transition")
        or c.id.startswith("state_machine:terminal_rejects")
        or c.id.startswith("state_machine:immutable"),
    )


def test_orders_cross_field_strict():
    _check(
        "h01_orders.spec.yaml",
        BUG_SKIP_CROSS_FIELD,
        lambda c: c.id.startswith("cross_field:violation:"),
    )


def test_reservations_relationship_strict():
    _check(
        "h02_reservations.spec.yaml",
        BUG_SKIP_PARENT_CHECK,
        lambda c: c.id.startswith("relationship:missing_parent")
        or c.id.startswith("relationship:restrict_delete"),
    )


def test_accounts_relationship_strict():
    _check(
        "h03_accounts.spec.yaml",
        BUG_SKIP_PARENT_CHECK,
        lambda c: c.id.startswith("relationship:missing_parent")
        or c.id.startswith("relationship:restrict_delete"),
    )


def test_inventory_composite_unique_strict():
    _check(
        "h08_inventory.spec.yaml",
        BUG_SKIP_COMPOSITE_UNIQUE,
        lambda c: c.id.startswith("composite_unique:conflict"),
    )


def test_playlists_child_composite_unique_strict():
    # composite_unique lives on the CHILD (track) resource here
    _check(
        "h05_playlists.spec.yaml",
        BUG_SKIP_COMPOSITE_UNIQUE,
        lambda c: c.id.startswith("composite_unique:conflict"),
    )


def test_hard_multi_filter_and_multi_sort_strict():
    _check(
        "h01_orders.spec.yaml", BUG_IGNORE_SECONDARY_FILTER, lambda c: c.id == "list:filter:multi"
    )
    _check("h01_orders.spec.yaml", BUG_IGNORE_SECONDARY_SORT, lambda c: c.id == "list:sort:multi")


def test_datetime_cross_field_patch_null_escape_is_caught():
    # A PATCH that NULLs a required datetime cross-field operand must be rejected; a
    # service that skips required-validation (and so allows the null) is caught by the
    # cross_field:patch_null case (the escape the adversarial review surfaced).
    for spec_name, ref in (
        ("h02_reservations.spec.yaml", "end_at"),
        ("h09_appointments.spec.yaml", "end_at"),
    ):
        _, result = _spec_and_result(INSTANCES / spec_name, bugs=frozenset({BUG_SKIP_REQUIRED}))
        assert f"cross_field:patch_null:{ref}" in set(result.failed_ids)


def test_all_corpus_patterns_are_generator_satisfiable():
    # Regression guard: every declared regex pattern must be one the payload generator
    # can satisfy, else the "valid" boundary probe sends a non-matching value and a
    # correct service would (wrongly) fail it. Also confirm the invalid probe is rejected.
    import re

    for path in SPEC_PATHS:
        spec = load_spec(path)
        resources = [spec.resource] + ([spec.related.resource] if spec.related else [])
        for res in resources:
            for f in res.fields:
                if f.pattern:
                    val = valid_value(f, 7)
                    assert re.match(f.pattern, str(val)), (
                        f"{path.name}:{f.name} pattern {f.pattern!r} not satisfied by "
                        f"generated value {val!r}"
                    )
                    assert not re.match(f.pattern, "!!not-matching!!")

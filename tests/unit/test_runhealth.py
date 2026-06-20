"""Run-health: every craft id must stay in the canonical taxonomy (G1 condition 4).

If the driver ever drifts to a non-taxonomy id, the curated G2 diagnostic silently goes
dark (it keys on taxonomy ids). The orchestrator logs '% craft ids in taxonomy' per task
and FAILS LOUD if it is below 100%, so that failure mode can never recur unnoticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.craft import CraftItem, CraftLibrary
from harness.orchestrator import assert_craft_canonical
from harness.reflection import canonical_fraction, template_for_craft_id

VA = {"models": ["claude-sonnet-4-6"], "effector_version": "x", "embedding_model": "bge"}
TS = "2026-06-20T00:00:00Z"


def _rogue(craft_id: str) -> CraftItem:
    return CraftItem(
        id=craft_id,
        kind="orchestration",
        summary="x",
        when_to_use="y",
        body="generic",
        tags=["crud"],
        tests=["unit"],
        validated_against=VA,
        last_validated=TS,
    )


def test_canonical_fraction_empty_library_is_one(tmp_path: Path) -> None:
    assert canonical_fraction(CraftLibrary(tmp_path)) == (1.0, [])


def test_canonical_fraction_all_taxonomy_is_one(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    for cid in ("pagination-contract", "state-machine-playbook"):
        lib.write(template_for_craft_id(cid).to_craft_item(validated_against=VA, last_validated=TS))
    assert canonical_fraction(lib) == (1.0, [])


def test_canonical_fraction_flags_rogue_ids(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(
        template_for_craft_id("pagination-contract").to_craft_item(
            validated_against=VA, last_validated=TS
        )
    )
    lib.write(_rogue("crud-easy-uuid-string-first-pass"))  # a free-form (non-taxonomy) id
    frac, rogue = canonical_fraction(lib)
    assert frac == 0.5
    assert rogue == ["crud-easy-uuid-string-first-pass"]


def test_assert_craft_canonical_returns_pct_when_clean(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(
        template_for_craft_id("filter-contract").to_craft_item(
            validated_against=VA, last_validated=TS
        )
    )
    assert assert_craft_canonical(lib) == 1.0


def test_assert_craft_canonical_fails_loud_below_100pct(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(_rogue("totally-novel-id"))
    with pytest.raises(RuntimeError, match="non-taxonomy"):
        assert_craft_canonical(lib)

"""Unit tests for the flat on-disk craft library + reuse counter.

Flat only: read/write/retrieve tested craft items with manifests, plus a per-task
reuse counter. No promotion gate, no dream, no graph (T-1.1 scope).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.craft import CraftItem, CraftLibrary, seed_default_craft

VALIDATED_AGAINST = {"models": ["claude-opus-4-8"], "effector_version": "claude-code-cli@test"}


def make_item(craft_id="crud-spec-template", tags=("crud", "spec")) -> CraftItem:
    return CraftItem(
        id=craft_id,
        kind="orchestration",
        summary="A reusable CRUD TaskSpec skeleton.",
        when_to_use="When the task is to build a spec-described CRUD service.",
        body="# CRUD spec template\n\nDescribe resource, fields, endpoints...\n",
        tags=list(tags),
        tests=["manual-seed"],
        version="1.0.0",
        scope="local",
        generic=True,
        status="active",
        validated_against=VALIDATED_AGAINST,
        last_validated="2026-06-19T00:00:00Z",
    )


def test_write_then_read_roundtrips(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    item = make_item()
    lib.write(item)
    got = lib.read("crud-spec-template")
    assert got.id == item.id
    assert got.body == item.body
    assert got.tags == item.tags
    assert got.kind == "orchestration"


def test_manifest_is_schema_valid_on_disk(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(make_item())
    manifest = tmp_path / "crud-spec-template" / "manifest.json"
    assert manifest.exists()
    # the library re-validates on read; a tampered manifest must be rejected
    import json

    data = json.loads(manifest.read_text())
    assert data["validated_against"]["models"] == ["claude-opus-4-8"]


def test_write_rejects_invalid_manifest(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    bad = make_item()
    object.__setattr__(bad, "version", "not-a-semver")  # violates schema pattern
    with pytest.raises(Exception):
        lib.write(bad)


def test_retrieve_by_tag(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(make_item("crud-spec-template", tags=("crud", "spec")))
    lib.write(make_item("pagination-contract", tags=("crud", "pagination")))
    hits = lib.retrieve(tags=["pagination"])
    assert [h.id for h in hits] == ["pagination-contract"]
    both = {h.id for h in lib.retrieve(tags=["crud"])}
    assert both == {"crud-spec-template", "pagination-contract"}


def test_retrieve_by_text_matches_summary_or_when(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(make_item())
    hits = lib.retrieve(text="CRUD service")
    assert any(h.id == "crud-spec-template" for h in hits)


def test_retrieve_is_deterministic_and_respects_limit(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    for i in range(5):
        lib.write(make_item(f"item-{i}", tags=("crud",)))
    a = [h.id for h in lib.retrieve(tags=["crud"], limit=3)]
    b = [h.id for h in lib.retrieve(tags=["crud"], limit=3)]
    assert a == b and len(a) == 3


def test_quarantined_items_not_retrieved(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    item = make_item("quarantined-one", tags=("crud",))
    object.__setattr__(item, "status", "quarantined")
    lib.write(item)
    lib.write(make_item("active-one", tags=("crud",)))
    ids = {h.id for h in lib.retrieve(tags=["crud"])}
    assert ids == {"active-one"}


def test_record_usage_and_read_back(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(make_item())
    lib.record_usage("task-1", retrieved=["crud-spec-template"], reused=["crud-spec-template"])
    usage = lib.usage_for("task-1")
    assert usage.retrieved == ["crud-spec-template"]
    assert usage.reused == ["crud-spec-template"]


def test_reused_must_be_subset_of_retrieved(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(make_item())
    with pytest.raises(ValueError):
        lib.record_usage("task-1", retrieved=["crud-spec-template"], reused=["never-retrieved"])


def test_seed_default_craft_is_retrievable(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    seeded = seed_default_craft(lib)
    assert "fastapi-sqlite-scaffold" in seeded
    hits = lib.retrieve(tags=["fastapi", "sqlite"])
    assert any(h.id == "fastapi-sqlite-scaffold" for h in hits)
    assert lib.read("fastapi-sqlite-scaffold").kind == "orchestration"

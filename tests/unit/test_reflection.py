"""Unit tests for reflection guardrails (ADR-0020 §4; T-1.3).

Reflection (Step E) is the linchpin: it decides WRITE / UPDATE / SKIP a per-feature
craft item. The harness-enforced anti-rot guardrails are tested here:

* reflect-on-signal trigger (locked decision 1);
* project-stripping lint (reject instance identifiers in craft bodies);
* dedupe (one canonical item per feature tag; evolve via UPDATE, not proliferate);
* the per-feature craft taxonomy (the ~13 items ADR-0020 §4 lists), each generic.
"""

from __future__ import annotations

from pathlib import Path

from harness.craft import CraftItem, CraftLibrary
from harness.reflection import (
    TAXONOMY,
    canonical_for_feature,
    craft_templates_to_write,
    feature_tag_to_craft_id,
    is_canonical,
    nearest_canonical_id,
    project_strip_lint,
    reflect_on_signal,
    taxonomy_catalog,
    template_for_craft_id,
    uncovered_relevant_craft_ids,
)
from harness.specschema import load_spec

REPO = Path(__file__).resolve().parents[2]
INSTANCES = REPO / "experiments" / "phase_minus_1" / "instances"
NOTES = INSTANCES / "e01_notes.spec.yaml"
BOOKS = INSTANCES / "example_books.spec.yaml"
ORDERS = INSTANCES / "h01_orders.spec.yaml"
VA = {"models": ["claude-sonnet-4-6"], "effector_version": "claude-code-cli@test"}


# --- reflect-on-signal ----------------------------------------------------- #
def test_signal_fires_on_effector_retry() -> None:
    assert reflect_on_signal(effector_retries=1, first_pass=True, uncovered_tags=[]) is True


def test_signal_fires_on_first_pass_failure() -> None:
    assert reflect_on_signal(effector_retries=0, first_pass=False, uncovered_tags=[]) is True


def test_signal_fires_on_new_uncovered_feature_tag() -> None:
    assert (
        reflect_on_signal(effector_retries=0, first_pass=True, uncovered_tags=["pagination"])
        is True
    )


def test_signal_skips_when_clean_and_fully_covered() -> None:
    assert reflect_on_signal(effector_retries=0, first_pass=True, uncovered_tags=[]) is False


# --- project-stripping lint ------------------------------------------------ #
def test_lint_flags_resource_name_and_field_name() -> None:
    spec = load_spec(ORDERS)
    leaky = "When building the orders service, set discount_cents below total_cents."
    violations = project_strip_lint(leaky, spec)
    assert "orders" in violations
    assert any("discount_cents" == v for v in violations)


def test_lint_passes_a_generic_body() -> None:
    spec = load_spec(ORDERS)
    generic = (
        "Enforce the lifecycle state machine: reject illegal transitions with the "
        "configured conflict code; terminal states are immutable."
    )
    assert project_strip_lint(generic, spec) == []


def test_lint_ignores_ultra_generic_tokens() -> None:
    spec = load_spec(BOOKS)
    # 'name', 'id', 'title' are generic English even if they are field names.
    text = "Echo the id and title back on create; populate server-managed fields."
    assert project_strip_lint(text, spec) == []


# --- taxonomy -------------------------------------------------------------- #
def test_taxonomy_has_the_thirteen_items() -> None:
    expected = {
        "crud-spec-template",
        "fastapi-sqlite-scaffold",
        "validation-422-shape",
        "server-managed-fields-recipe",
        "pagination-contract",
        "unique-409-recipe",
        "sort-contract",
        "filter-contract",
        "state-machine-playbook",
        "cross-field-rule-recipe",
        "relationship-ref-recipe",
        "composite-unique-recipe",
        "computed-field-recipe",
    }
    assert set(TAXONOMY) == expected


def test_every_taxonomy_template_is_project_stripped_against_all_instances() -> None:
    specs = [load_spec(p) for p in sorted(INSTANCES.glob("*.spec.yaml"))]
    for tpl in TAXONOMY.values():
        text = f"{tpl.summary}\n{tpl.when_to_use}\n{tpl.body}"
        for spec in specs:
            assert (
                project_strip_lint(text, spec) == []
            ), f"craft '{tpl.craft_id}' leaks an identifier of instance '{spec.id}'"


def test_feature_tag_maps_to_expected_craft() -> None:
    assert feature_tag_to_craft_id("pagination") == "pagination-contract"
    assert feature_tag_to_craft_id("rule:state_machine") == "state-machine-playbook"
    assert feature_tag_to_craft_id("multi-sort") == "sort-contract"
    assert feature_tag_to_craft_id("nonexistent-tag") is None


def test_template_for_craft_id_builds_a_schema_valid_item() -> None:
    tpl = template_for_craft_id("pagination-contract")
    item = tpl.to_craft_item(validated_against=VA, last_validated="2026-06-20T00:00:00Z")
    assert isinstance(item, CraftItem)
    assert item.id == "pagination-contract"
    assert item.generic is True
    CraftLibrary  # the item must be writable; library write validates the schema


# --- uncovered / dedupe ---------------------------------------------------- #
def test_uncovered_relevant_includes_universals_for_a_fresh_library(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    feature_tags = ["tier:easy", "crud", "endpoint:create", "type:string"]
    ids = uncovered_relevant_craft_ids(feature_tags, lib)
    # universals are relevant to every instance even though no distinguishing tag names them
    assert "crud-spec-template" in ids
    assert "fastapi-sqlite-scaffold" in ids
    assert "validation-422-shape" in ids
    # a pagination item is NOT relevant to an easy instance with no pagination tag
    assert "pagination-contract" not in ids


def test_uncovered_excludes_already_present_active_craft(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    tpl = template_for_craft_id("crud-spec-template")
    lib.write(tpl.to_craft_item(validated_against=VA, last_validated="2026-06-20T00:00:00Z"))
    ids = uncovered_relevant_craft_ids(["crud"], lib)
    assert "crud-spec-template" not in ids


def test_craft_templates_to_write_are_relevant_and_missing(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    spec_tags = ["tier:hard", "crud", "pagination", "unique", "rule:state_machine"]
    tpls = craft_templates_to_write(spec_tags, lib)
    written = {t.craft_id for t in tpls}
    assert "state-machine-playbook" in written
    assert "pagination-contract" in written
    assert "unique-409-recipe" in written


# --- canonical-id constraint + remap backstop (G1 Option A) ---------------- #
def test_is_canonical_matches_only_taxonomy_ids() -> None:
    assert is_canonical("pagination-contract") is True
    assert is_canonical("crud-easy-uuid-string-first-pass") is False  # a free-form driver id


def test_taxonomy_catalog_lists_all_thirteen_with_guidance() -> None:
    cat = taxonomy_catalog()
    assert len(cat) == 13
    ids = {c["id"] for c in cat}
    assert ids == set(TAXONOMY)
    for c in cat:
        assert c["when_to_use"] and "feature_keys" in c and "universal" in c


def test_nearest_canonical_passes_through_a_canonical_id() -> None:
    assert nearest_canonical_id("state-machine-playbook") == "state-machine-playbook"


def test_nearest_canonical_remaps_via_tag_mapping() -> None:
    # a free-form id whose tags name a feature -> the canonical item for that feature
    assert (
        nearest_canonical_id("crud-medium-integer-validation-min", tags=["pagination"])
        == "pagination-contract"
    )


def test_nearest_canonical_always_returns_a_taxonomy_id_never_drops() -> None:
    # an utterly unknown id with no mapping tag still remaps (never None / never dropped)
    out = nearest_canonical_id(
        "totally-novel-thing", tags=[], summary="server health check boot route", when_to_use="boot"
    )
    assert out in TAXONOMY


def test_canonical_for_feature_finds_existing_item(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    tpl = template_for_craft_id("pagination-contract")
    lib.write(tpl.to_craft_item(validated_against=VA, last_validated="2026-06-20T00:00:00Z"))
    found = canonical_for_feature("pagination", lib)
    assert found is not None and found.id == "pagination-contract"
    assert canonical_for_feature("rule:state_machine", lib) is None

"""Unit tests for the retrieval-precision diagnostic (ADR-0020 gate G2; T-1.3).

G2 is what lets a flat reuse curve be diagnosed as a RETRIEVAL MISS vs ABSENT
COMPOUNDING — the decisive false negative (domain.md §6). Two gold sets:

* CURATED (primary) — the pre-registered, retriever-independent key in
  ``retrieval_gold.yaml`` (universals + list items + rule recipes).
* AUTO (cross-check) — tag-overlap between craft tags and instance feature tags; blind
  to universally-relevant craft that no distinguishing tag names. Reported alongside,
  with divergence flagged.

Relevance is intersected with the craft PRESENT in the library at that position — the
library is emergent, so craft reflection hasn't written yet is not counted as a "miss".
"""

from __future__ import annotations

from pathlib import Path

from harness.gold import (
    GoldMap,
    auto_relevant_craft_ids,
    retrieval_diagnostic,
    summarize_diagnostics,
)

REPO = Path(__file__).resolve().parents[2]
GOLD = REPO / "experiments" / "phase_minus_1" / "retrieval_gold.yaml"


def test_gold_map_loads_all_thirty_instances() -> None:
    gm = GoldMap.load(GOLD)
    assert len(gm.instances) == 30
    assert set(gm.curated_relevant("orders")) >= {
        "state-machine-playbook",
        "cross-field-rule-recipe",
        "crud-spec-template",
    }
    # an easy instance: universals only
    assert set(gm.curated_relevant("notes")) == {
        "crud-spec-template",
        "fastapi-sqlite-scaffold",
        "validation-422-shape",
        "server-managed-fields-recipe",
    }


def test_auto_map_misses_universals_that_no_tag_names() -> None:
    # books has 'crud' (-> crud-spec-template) and 'pagination' etc., but no tag names
    # validation-422-shape / server-managed-fields-recipe / fastapi-sqlite-scaffold.
    feature_tags = ["tier:medium", "crud", "pagination", "unique", "filters", "sort"]
    auto = auto_relevant_craft_ids(feature_tags)
    assert "pagination-contract" in auto
    assert "crud-spec-template" in auto
    # the blind spot G2's curated key exists to cover:
    assert "validation-422-shape" not in auto
    assert "server-managed-fields-recipe" not in auto


def test_diagnostic_perfect_retrieval_scores_one() -> None:
    gm = GoldMap.load(GOLD)
    present = set(gm.curated_relevant("notes"))  # all relevant craft present
    d = retrieval_diagnostic(
        gold=gm,
        instance_id="notes",
        feature_tags=["tier:easy", "crud"],
        retrieved_ids=list(present),
        incorporated_ids=list(present),
        present_ids=present,
    )
    assert d.curated_recall == 1.0
    assert d.curated_precision == 1.0


def test_diagnostic_counts_only_craft_present_at_position() -> None:
    """Relevant craft that reflection has not written yet is NOT a miss (emergent lib)."""
    gm = GoldMap.load(GOLD)
    # only crud-spec-template exists so far; it is retrieved -> recall over PRESENT is 1.0
    present = {"crud-spec-template"}
    d = retrieval_diagnostic(
        gold=gm,
        instance_id="orders",
        feature_tags=["tier:hard", "crud", "rule:state_machine"],
        retrieved_ids=["crud-spec-template"],
        incorporated_ids=["crud-spec-template"],
        present_ids=present,
    )
    assert d.curated_recall == 1.0
    assert d.curated_relevant_present == ["crud-spec-template"]


def test_diagnostic_detects_a_retrieval_miss() -> None:
    gm = GoldMap.load(GOLD)
    # state-machine-playbook IS present and relevant but was NOT retrieved -> recall < 1
    present = {"crud-spec-template", "state-machine-playbook"}
    d = retrieval_diagnostic(
        gold=gm,
        instance_id="orders",
        feature_tags=["tier:hard", "crud", "rule:state_machine"],
        retrieved_ids=["crud-spec-template"],
        incorporated_ids=["crud-spec-template"],
        present_ids=present,
    )
    assert d.curated_recall == 0.5  # 1 of 2 relevant-present retrieved
    assert "state-machine-playbook" in d.curated_missed


def test_diagnostic_reports_divergence_between_curated_and_auto() -> None:
    gm = GoldMap.load(GOLD)
    present = {"crud-spec-template", "validation-422-shape", "server-managed-fields-recipe"}
    d = retrieval_diagnostic(
        gold=gm,
        instance_id="notes",
        feature_tags=["tier:easy", "crud"],
        retrieved_ids=["crud-spec-template"],
        incorporated_ids=["crud-spec-template"],
        present_ids=present,
    )
    assert d.diverges is True
    # curated counts the universals the auto map cannot see
    assert "validation-422-shape" in d.divergence


def test_diagnostic_reports_retrieved_vs_incorporated() -> None:
    gm = GoldMap.load(GOLD)
    present = {"crud-spec-template", "pagination-contract"}
    d = retrieval_diagnostic(
        gold=gm,
        instance_id="books",
        feature_tags=["tier:medium", "crud", "pagination"],
        retrieved_ids=["crud-spec-template", "pagination-contract"],
        incorporated_ids=["pagination-contract"],  # driver dropped one as not useful
        present_ids=present,
    )
    assert d.n_retrieved == 2
    assert d.n_incorporated == 1
    assert d.incorporation_precision == 0.5  # incorporated / retrieved (selective vs dump)


def test_diagnostic_scores_driver_incorporation_judgment_vs_gold() -> None:
    """At k=full-library, retrieval recall saturates; the real G2 signal is whether the
    DRIVER incorporated the gold-relevant craft (recall) and avoided the irrelevant
    (precision). books gold = universals + pagination/unique/sort/filter."""
    gm = GoldMap.load(GOLD)
    present = {"crud-spec-template", "pagination-contract", "state-machine-playbook"}
    # driver incorporated one gold-relevant (crud) + one NOT gold-relevant for books
    # (state-machine), and missed pagination (gold-relevant, present).
    d = retrieval_diagnostic(
        gold=gm,
        instance_id="books",
        feature_tags=["tier:medium", "crud", "pagination"],
        retrieved_ids=["crud-spec-template", "pagination-contract", "state-machine-playbook"],
        incorporated_ids=["crud-spec-template", "state-machine-playbook"],
        present_ids=present,
    )
    # books gold present = {crud-spec-template, pagination-contract}
    # incorporated ∩ gold = {crud-spec-template} -> precision 1/2, recall 1/2
    assert d.incorporation_curated_precision == 0.5
    assert d.incorporation_curated_recall == 0.5


def test_diagnostic_incorporation_vs_gold_undefined_when_nothing_incorporated() -> None:
    gm = GoldMap.load(GOLD)
    d = retrieval_diagnostic(
        gold=gm,
        instance_id="notes",
        feature_tags=["tier:easy", "crud"],
        retrieved_ids=[],
        incorporated_ids=[],
        present_ids=set(),
    )
    assert d.incorporation_curated_precision is None
    assert d.incorporation_curated_recall is None


def test_summarize_reports_mean_per_position_recall() -> None:
    gm = GoldMap.load(GOLD)
    present = set(gm.curated_relevant("notes"))
    good = retrieval_diagnostic(
        gold=gm,
        instance_id="notes",
        feature_tags=["crud"],
        retrieved_ids=list(present),
        incorporated_ids=list(present),
        present_ids=present,
    )
    half_present = {"crud-spec-template", "state-machine-playbook"}
    miss = retrieval_diagnostic(
        gold=gm,
        instance_id="orders",
        feature_tags=["rule:state_machine"],
        retrieved_ids=["crud-spec-template"],
        incorporated_ids=["crud-spec-template"],
        present_ids=half_present,
    )
    summary = summarize_diagnostics([good, miss])
    assert summary["mean_curated_recall"] == 0.75  # mean of 1.0 and 0.5
    assert summary["positions"] == 2

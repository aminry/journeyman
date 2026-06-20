"""Retrieval-precision diagnostic (ADR-0020 gate G2; T-1.3).

G2 separates a flat reuse curve that is a **retrieval miss** from one that is **absent
compounding** — the decisive false negative (domain.md §6). The control run (Run B)
cannot tell these apart, so this diagnostic is REQUIRED, not optional.

Two gold sets per instance:

* **curated** (primary) — the pre-registered, retriever-independent key in
  ``retrieval_gold.yaml``;
* **auto** (cross-check) — tag-overlap between a craft item's tags and the instance's
  feature tags; blind to universally-relevant craft no distinguishing tag names.

Both are intersected with the craft **present in the library at that position** (the
library is emergent — craft reflection hasn't written yet is not a "miss"). Per-position
**recall** against the curated key is the decisive metric: low recall against true
relevance ⇒ a retrieval problem, not absent compounding.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from harness.reflection import TAXONOMY


@dataclass(frozen=True)
class GoldMap:
    instances: dict[str, list[str]]

    @classmethod
    def load(cls, path: str | Path) -> "GoldMap":
        data = yaml.safe_load(Path(path).read_text())
        return cls(instances={k: list(v) for k, v in data["instances"].items()})

    def curated_relevant(self, instance_id: str) -> list[str]:
        return list(self.instances.get(instance_id, []))


def auto_relevant_craft_ids(feature_tags: list[str]) -> set[str]:
    """The AUTO cross-check: a craft item is relevant iff its tags overlap the instance's
    feature tags. Deliberately retriever-shaped — it misses universally-relevant craft
    that no distinguishing feature tag names (the blind spot the curated key covers)."""
    fts = set(feature_tags)
    return {cid for cid, tpl in TAXONOMY.items() if set(tpl.tags) & fts}


def _precision(retrieved: set[str], relevant: set[str]) -> float:
    return len(retrieved & relevant) / len(retrieved) if retrieved else 0.0


def _recall(retrieved: set[str], relevant: set[str]) -> float | None:
    # No relevant craft present at this position -> recall is undefined (nothing to miss).
    return len(retrieved & relevant) / len(relevant) if relevant else None


@dataclass(frozen=True)
class RetrievalDiagnostic:
    instance_id: str
    # curated (primary)
    curated_relevant_present: list[str]
    curated_retrieved_relevant: list[str]
    curated_missed: list[str]
    curated_precision: float
    curated_recall: float | None
    # auto (cross-check) + divergence
    auto_relevant_present: list[str]
    auto_recall: float | None
    diverges: bool
    divergence: list[str]
    # retrieved-vs-incorporated
    n_retrieved: int
    n_incorporated: int
    incorporation_precision: float


def retrieval_diagnostic(
    *,
    gold: GoldMap,
    instance_id: str,
    feature_tags: list[str],
    retrieved_ids: list[str],
    incorporated_ids: list[str],
    present_ids: set[str],
) -> RetrievalDiagnostic:
    retrieved = set(retrieved_ids)
    curated = set(gold.curated_relevant(instance_id)) & present_ids
    auto = auto_relevant_craft_ids(feature_tags) & present_ids

    return RetrievalDiagnostic(
        instance_id=instance_id,
        curated_relevant_present=sorted(curated),
        curated_retrieved_relevant=sorted(retrieved & curated),
        curated_missed=sorted(curated - retrieved),
        curated_precision=_precision(retrieved, curated),
        curated_recall=_recall(retrieved, curated),
        auto_relevant_present=sorted(auto),
        auto_recall=_recall(retrieved, auto),
        diverges=curated != auto,
        divergence=sorted(curated ^ auto),
        n_retrieved=len(retrieved_ids),
        n_incorporated=len(incorporated_ids),
        incorporation_precision=(
            len(incorporated_ids) / len(retrieved_ids) if retrieved_ids else 0.0
        ),
    )


def summarize_diagnostics(diags: list[RetrievalDiagnostic]) -> dict:
    """Aggregate per-position diagnostics. Mean recall is taken over positions where the
    metric is defined (relevant craft was present)."""
    curated_recalls = [d.curated_recall for d in diags if d.curated_recall is not None]
    auto_recalls = [d.auto_recall for d in diags if d.auto_recall is not None]
    mean = lambda xs: round(sum(xs) / len(xs), 6) if xs else None  # noqa: E731
    return {
        "positions": len(diags),
        "mean_curated_recall": mean(curated_recalls),
        "mean_auto_recall": mean(auto_recalls),
        "mean_curated_precision": mean([d.curated_precision for d in diags]),
        "mean_incorporation_precision": mean([d.incorporation_precision for d in diags]),
        "divergent_positions": sum(1 for d in diags if d.diverges),
        "per_position_curated_recall": [d.curated_recall for d in diags],
    }

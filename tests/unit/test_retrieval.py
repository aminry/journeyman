"""Unit tests for craft retrieval (ADR-0020 §5; T-1.3).

The protocol's "simple vector retrieval": embed each craft item's
(summary + when_to_use + tags + body), build the query from the instance's feature
tags + a short spec digest, return cosine top-k. A keyword/tag retriever is the
documented fallback when the embedding model is unavailable. Both honor the
library's retrieval discipline (quarantined/deprecated items are never returned).
"""

from __future__ import annotations

from pathlib import Path

from harness.craft import CraftItem, CraftLibrary
from harness.embedding import DeterministicHashEmbedder
from harness.retrieval import (
    KeywordCraftRetriever,
    VectorCraftRetriever,
    build_retriever,
)
from harness.runconfig import orchestrator_run_config

VA = {"models": ["claude-sonnet-4-6"], "effector_version": "claude-code-cli@test"}


def _item(craft_id: str, summary: str, body: str, tags: list[str]) -> CraftItem:
    return CraftItem(
        id=craft_id,
        kind="orchestration",
        summary=summary,
        when_to_use=f"When the instance has {', '.join(tags)}.",
        body=body,
        tags=tags,
        tests=["unit"],
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
    )


def _seed(lib: CraftLibrary) -> None:
    lib.write(
        _item(
            "pagination-contract",
            "How to implement list pagination correctly.",
            "Pagination: respect limit and offset query params; cap page size at max_limit; "
            "default page size; stable ordering across pages.",
            ["pagination", "list", "limit", "offset"],
        )
    )
    lib.write(
        _item(
            "state-machine-playbook",
            "How to implement a status state machine.",
            "State machine: enforce allowed transitions between states; reject illegal "
            "transitions with 409; terminal states are locked and immutable.",
            ["rule:state_machine", "status", "transition"],
        )
    )
    lib.write(
        _item(
            "validation-422-shape",
            "The validation-error response shape.",
            "Validation errors return 422 with body errors array of field and message.",
            ["validation", "422", "required"],
        )
    )


def test_vector_retrieve_ranks_relevant_item_first(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    _seed(lib)
    r = VectorCraftRetriever(lib, DeterministicHashEmbedder(dim=512), k=2)
    hits = r.retrieve(
        feature_tags=["pagination", "list", "limit", "offset"],
        spec_digest="list endpoint with pagination limit offset max_limit",
    )
    assert hits[0].id == "pagination-contract"
    assert len(hits) <= 2


def test_vector_retrieve_respects_top_k(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    _seed(lib)
    r = VectorCraftRetriever(lib, DeterministicHashEmbedder(dim=256), k=1)
    assert len(r.retrieve(feature_tags=["validation", "422"], spec_digest="")) == 1


def test_vector_retrieve_excludes_quarantined(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    _seed(lib)
    q = _item("bad-one", "harmful", "pagination limit offset", ["pagination"])
    object.__setattr__(q, "status", "quarantined")
    lib.write(q)
    r = VectorCraftRetriever(lib, DeterministicHashEmbedder(dim=512), k=5)
    ids = {h.id for h in r.retrieve(feature_tags=["pagination"], spec_digest="")}
    assert "bad-one" not in ids


def test_vector_retrieve_empty_library_returns_empty(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    r = VectorCraftRetriever(lib, DeterministicHashEmbedder(dim=64), k=5)
    assert r.retrieve(feature_tags=["pagination"], spec_digest="") == []


def test_vector_retrieve_scored_is_sorted_desc_and_deterministic(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    _seed(lib)
    r = VectorCraftRetriever(lib, DeterministicHashEmbedder(dim=512), k=3)
    scored = r.retrieve_scored(feature_tags=["pagination", "limit"], spec_digest="pagination")
    scores = [s.score for s in scored]
    assert scores == sorted(scores, reverse=True)
    again = r.retrieve_scored(feature_tags=["pagination", "limit"], spec_digest="pagination")
    assert [s.item.id for s in scored] == [s.item.id for s in again]


def test_retriever_reports_its_method(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    assert VectorCraftRetriever(lib, DeterministicHashEmbedder(dim=8)).method == "vector"
    assert KeywordCraftRetriever(lib).method == "keyword"


def test_keyword_fallback_retrieves_by_tag(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    _seed(lib)
    r = KeywordCraftRetriever(lib, k=5)
    ids = {h.id for h in r.retrieve(feature_tags=["rule:state_machine"], spec_digest="")}
    assert ids == {"state-machine-playbook"}


def test_build_retriever_falls_back_to_keyword_without_sentence_transformers(
    tmp_path: Path,
) -> None:
    """With the bge pin set but sentence-transformers absent (CI), the factory must
    degrade to keyword retrieval rather than crash — the documented fallback."""
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        lib = CraftLibrary(tmp_path)
        r = build_retriever(lib, orchestrator_run_config())
        assert r.method == "keyword"
    else:  # pragma: no cover
        import pytest

        pytest.skip("sentence-transformers installed; fallback path not exercised")

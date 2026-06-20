"""Unit tests for the embedder layer (ADR-0020 §5; T-1.3).

Two implementations behind one interface:

* ``DeterministicHashEmbedder`` — zero-dependency, fully deterministic; used by every
  test and by CI so the vector-retrieval machinery is proven WITHOUT pulling torch.
* ``BGEEmbedder`` — the pinned local model (BAAI/bge-small-en-v1.5) used only in the
  real pilot; lazy-imports sentence-transformers so importing this module is free.
"""

from __future__ import annotations

import math

import pytest

from harness.embedding import BGEEmbedder, DeterministicHashEmbedder, cosine


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def test_cosine_identical_is_one_orthogonal_is_zero() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_handles_zero_vector_without_dividing_by_zero() -> None:
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_hash_embedder_is_deterministic_across_instances() -> None:
    a = DeterministicHashEmbedder(dim=128).embed_query("pagination contract max_limit")
    b = DeterministicHashEmbedder(dim=128).embed_query("pagination contract max_limit")
    assert a == b


def test_hash_embedder_returns_unit_vectors_of_fixed_dim() -> None:
    emb = DeterministicHashEmbedder(dim=64)
    vecs = emb.embed_documents(["alpha beta", "gamma"])
    assert len(vecs) == 2
    assert all(len(v) == 64 for v in vecs)
    assert _norm(vecs[0]) == pytest.approx(1.0)


def test_hash_embedder_similar_text_scores_higher_than_dissimilar() -> None:
    emb = DeterministicHashEmbedder(dim=512)
    q = emb.embed_query("pagination limit offset max_limit sort filter")
    near = emb.embed_documents(["pagination contract limit offset max_limit cap"])[0]
    far = emb.embed_documents(["state machine transition pending paid shipped"])[0]
    assert cosine(q, near) > cosine(q, far)


def test_hash_embedder_empty_text_is_zero_vector() -> None:
    v = DeterministicHashEmbedder(dim=16).embed_query("")
    assert v == [0.0] * 16


def test_bge_embedder_raises_clear_error_without_sentence_transformers() -> None:
    """In CI/fakes sentence-transformers is intentionally absent; the error must name
    the missing optional dependency rather than fail obscurely (it is a pilot-only dep)."""
    pytest.importorskip  # noqa: B018 - sanity that pytest is importable
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="sentence-transformers"):
            BGEEmbedder()
    else:  # pragma: no cover - only when the optional dep happens to be installed
        pytest.skip("sentence-transformers installed; the no-dep error path is not exercised")

"""Craft retrieval: simple vector retrieval + keyword/tag fallback (ADR-0020 §5).

The orchestrator (T-1.3) queries the craft library per task from the instance's
**feature tags** + a short **spec digest**. The protocol specifies *simple vector
retrieval*: embed each craft item's (summary + when_to_use + tags + body), embed the
query, return cosine top-k. The spine's keyword/tag retrieval (``CraftLibrary.retrieve``)
remains the documented fallback when the embedding model is unavailable.

Both retrievers honor the library's retrieval discipline: only ``active`` items are
returned (quarantined/deprecated are skipped, as ``CraftLibrary.retrieve`` already does).
``reuse`` is decided later by the driver (verified-incorporated), not here — retrieval
only *surfaces* candidates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from harness.craft import CraftItem, CraftLibrary
from harness.embedding import Embedder, cosine
from harness.runconfig import RunConfig


@dataclass(frozen=True)
class RetrievalResult:
    item: CraftItem
    score: float


class Retriever(Protocol):
    method: str

    def retrieve(self, *, feature_tags: list[str], spec_digest: str = "") -> list[CraftItem]: ...


def build_query_text(feature_tags: list[str], spec_digest: str) -> str:
    """The query side of retrieval: the instance's feature tags + a short spec digest.

    Kept deterministic and order-stable so the same instance always yields the same
    query (retrieval stays out of the experiment's variance budget)."""
    tags = " ".join(feature_tags)
    return f"{tags}\n{spec_digest}".strip()


def _doc_text(item: CraftItem) -> str:
    """What we embed for a craft item (ADR-0020 §5): summary + when_to_use + tags + body."""
    return f"{item.summary}\n{item.when_to_use}\n{' '.join(item.tags)}\n{item.body}"


class VectorCraftRetriever:
    """Cosine top-k over embedded craft items. Embeddings are cached by (id, version,
    content) so re-embedding only happens when an item actually changes."""

    method = "vector"

    def __init__(self, library: CraftLibrary, embedder: Embedder, *, k: int = 5):
        self.library = library
        self.embedder = embedder
        self.k = k
        self._cache: dict[tuple[str, str, int], list[float]] = {}

    def _embedding_for(self, item: CraftItem) -> list[float]:
        text = _doc_text(item)
        key = (item.id, item.version, hash(text))
        cached = self._cache.get(key)
        if cached is None:
            cached = self.embedder.embed_documents([text])[0]
            self._cache[key] = cached
        return cached

    def retrieve_scored(
        self, *, feature_tags: list[str], spec_digest: str = ""
    ) -> list[RetrievalResult]:
        active = [self.library.read(cid) for cid in self.library.ids()]
        active = [it for it in active if it.status == "active"]
        if not active:
            return []
        qvec = self.embedder.embed_query(build_query_text(feature_tags, spec_digest))
        scored = [RetrievalResult(it, cosine(qvec, self._embedding_for(it))) for it in active]
        # Deterministic: highest score first, ties broken by id.
        scored.sort(key=lambda r: (-r.score, r.item.id))
        return scored[: self.k]

    def retrieve(self, *, feature_tags: list[str], spec_digest: str = "") -> list[CraftItem]:
        return [
            r.item for r in self.retrieve_scored(feature_tags=feature_tags, spec_digest=spec_digest)
        ]


class KeywordCraftRetriever:
    """The documented fallback: the spine's keyword/tag retrieval (zero cost, no model)."""

    method = "keyword"

    def __init__(self, library: CraftLibrary, *, k: int = 5):
        self.library = library
        self.k = k

    def retrieve(self, *, feature_tags: list[str], spec_digest: str = "") -> list[CraftItem]:
        text = spec_digest or None
        return self.library.retrieve(tags=feature_tags, text=text, limit=self.k)


def build_retriever(library: CraftLibrary, config: RunConfig) -> Retriever:
    """Build the configured retriever, degrading to keyword/tag if the embedding model
    is unavailable (ADR-0020 §5 fallback). Tests inject a retriever directly; this is the
    production wiring used by the orchestrator CLI."""
    if config.embedding_model is None:
        return KeywordCraftRetriever(library, k=config.retrieval_k)
    try:
        from harness.embedding import BGEEmbedder

        embedder = BGEEmbedder(
            config.embedding_model,
            revision=config.embedding_revision,
            query_prefix=config.embedding_query_prefix,
            normalize=config.embedding_normalize,
        )
    except RuntimeError:
        # sentence-transformers not installed (e.g. CI/fakes): documented fallback.
        return KeywordCraftRetriever(library, k=config.retrieval_k)
    return VectorCraftRetriever(library, embedder, k=config.retrieval_k)

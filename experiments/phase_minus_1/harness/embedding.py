"""Embedder layer for vector craft retrieval (ADR-0020 §5; T-1.3).

The protocol's "simple vector retrieval" needs an embedding model. Two
implementations sit behind one :class:`Embedder` interface:

* :class:`DeterministicHashEmbedder` — a zero-dependency, fully deterministic
  hashing embedder. It exists so the *retrieval machinery* (cosine top-k, the
  precision diagnostic, the orchestrator A/B harness) can be proven in CI with
  ZERO spend and NO heavy dependency (no torch). It is NOT the real model.
* :class:`BGEEmbedder` — the pinned local model ``BAAI/bge-small-en-v1.5``
  (operator decision, T-1.3): deterministic, zero per-call cost, no network at
  query time. It lazy-imports ``sentence-transformers`` so merely importing this
  module costs nothing; it is used only in the real pilot/experiment run. The
  bge query-instruction prefix is applied to the QUERY ONLY, never to documents.

Cosine similarity is implemented in pure Python so the deterministic path needs
no numpy.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
# bge-small-en-v1.5 asks for this instruction on retrieval QUERIES (not passages).
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages:"


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors; 0.0 if either is the zero vector."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _resolve_hf_revision(model_id: str) -> str | None:  # pragma: no cover - real-model path
    """Best-effort: the resolved commit hash of the locally-cached snapshot, so the
    pin records the exact weights used. Returns None if it cannot be determined
    (the run then records just the model id + the sentence-transformers version)."""
    try:
        from huggingface_hub import HfApi

        return HfApi().model_info(model_id).sha
    except Exception:
        return None


@runtime_checkable
class Embedder(Protocol):
    """Embeds documents (craft) and queries (instance feature tags + spec digest)."""

    @property
    def model_id(self) -> str: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class DeterministicHashEmbedder:
    """A deterministic bag-of-tokens hashing embedder (the "feature hashing" trick).

    Each token is hashed (stably, via blake2b — NOT Python's salted ``hash``) into a
    bucket with a sign, accumulated, then L2-normalized. Shared tokens land in shared
    dimensions, so texts that share vocabulary score higher under cosine. Fully
    reproducible across processes and machines — the property the experiment needs to
    keep retrieval out of the variance budget.
    """

    def __init__(self, dim: int = 256):
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim

    @property
    def model_id(self) -> str:
        return f"deterministic-hash-{self.dim}"

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            h = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
            n = int.from_bytes(h, "big")
            bucket = n % self.dim
            sign = 1.0 if (n >> 16) & 1 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            return vec
        return [x / norm for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class BGEEmbedder:
    """The pinned local model ``BAAI/bge-small-en-v1.5`` (T-1.3 pilot path).

    Lazy-imports sentence-transformers; raises a clear, actionable error when the
    optional dependency is absent (it is intentionally not in the CI/fakes env). The
    resolved HF revision and the sentence-transformers version are captured so they
    can be recorded into ``pins`` and frozen for the run.
    """

    def __init__(
        self,
        model_id: str = "BAAI/bge-small-en-v1.5",
        *,
        revision: str | None = None,
        query_prefix: str = BGE_QUERY_PREFIX,
        normalize: bool = True,
    ):
        try:
            import sentence_transformers  # noqa: F401
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - exercised only without the dep
            raise RuntimeError(
                "BGEEmbedder needs the optional dependency 'sentence-transformers' "
                "(pilot/experiment only). Install it before the real run, e.g. "
                "`pip install sentence-transformers`. CI and the fakes path use "
                "DeterministicHashEmbedder and never import this."
            ) from exc
        self._model_id = model_id
        self.query_prefix = query_prefix
        self.normalize = normalize
        self._model = SentenceTransformer(model_id, revision=revision)
        self.sentence_transformers_version = sentence_transformers.__version__
        try:
            import torch

            self.torch_version = torch.__version__
        except ImportError:  # pragma: no cover - torch ships with sentence-transformers
            self.torch_version = None
        # Record the concrete revision actually loaded so the pin is reproducible.
        self.revision = revision or _resolve_hf_revision(model_id)

    @property
    def model_id(self) -> str:
        return self._model_id

    def embed_documents(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        out = self._model.encode(list(texts), normalize_embeddings=self.normalize)
        return [list(map(float, v)) for v in out]

    def embed_query(self, text: str) -> list[float]:  # pragma: no cover - real-model path
        prefixed = f"{self.query_prefix} {text}" if self.query_prefix else text
        out = self._model.encode([prefixed], normalize_embeddings=self.normalize)
        return [float(x) for x in out[0]]

"""Run config: pins for model ids, token prices, cache policy, effector command.

protocol.md "Model And Pricing Pins" requires these be recorded before task 1.
:meth:`RunConfig.to_pins` produces the ``pins`` object that goes verbatim into
``results.json`` (and validates against results.schema.json).

Pricing is the ``claude-api`` cached snapshot (2026-05-26), pinned at the
operator's instruction (not fetched live), so the cost accounting is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# claude-api reference, cached 2026-05-26. USD per 1M tokens.
_PRICING_SNAPSHOT_LABEL = "claude-api reference, cached 2026-05-26"
_TOKEN_PRICES = {
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
}


@dataclass
class RunConfig:
    protocol_version: str = "v3"  # v3: computed_field dimension added (see CHANGELOG.md)
    effector_model: str = "claude-opus-4-8"
    fallback_model: str = "claude-haiku-4-5"
    # The effector here is Claude Code CLI driven in headless mode (ADR-0005).
    effector_version: str = "claude-code-cli (headless -p, --output-format json)"
    token_prices: dict[str, dict[str, float]] = field(default_factory=lambda: dict(_TOKEN_PRICES))
    pricing_snapshot: str = _PRICING_SNAPSHOT_LABEL
    cache_policy: str = (
        "effector default (ephemeral prompt cache); harness makes no model calls in the spine"
    )
    # Spine retrieval is keyword/tag (deterministic, zero cost). protocol's
    # "simple vector retrieval" is swapped in at T-1.3 without touching the runner.
    retrieval_config: str = "flat keyword/tag retrieval (spine); vector retrieval deferred to T-1.3"
    embedding_model: str | None = None
    # --- Driver / orchestrator pins (ADR-0020 §3; T-1.3). None on the spine, which
    # makes no driver model calls. The orchestrator factory sets these. Pinned
    # BYTE-IDENTICALLY across Run A and Run B so A-B isolates craft, not decoding.
    driver_model: str | None = None
    driver_fallback_model: str | None = None
    driver_temperature: float = 0.0
    driver_max_tokens: int = 8000
    # --- Embedding / vector-retrieval pins (ADR-0020 §5; operator decision T-1.3).
    # bge query-instruction prefix is applied to the QUERY ONLY (feature tags + spec
    # digest), never to craft documents. ``embedding_revision`` / version are recorded
    # at first download and frozen thereafter (local, deterministic, zero per-call cost).
    embedding_revision: str | None = None
    sentence_transformers_version: str | None = None
    torch_version: str | None = None
    embedding_normalize: bool = True
    embedding_similarity: str = "cosine"
    # k = the craft library size (the full taxonomy, ~13), NOT a small constant. At k=5
    # every medium (8 relevant) / hard (up to 11) instance is capped — it caps the reuse
    # counter at 5 and G2 recall at ~0.45 once the library fills (positions ~15-30), which
    # the cold-start pilot can't reveal. With k=full-library nothing relevant is dropped,
    # so G2 measures the driver's INCORPORATION judgment vs the gold, not retrieval cap
    # artifacts (operator decision T-1.3; see ADR-0023). Revisit if the library ever grows
    # past the taxonomy (a driver inventing novel craft ids).
    retrieval_k: int = 5
    embedding_query_prefix: str = "Represent this sentence for searching relevant passages:"
    # Effector invocation template. {prompt} is substituted by render_effector_command.
    # Scoped permissions preferred over --dangerously-skip-permissions: the effector
    # already runs in an isolated, network/credential-scoped worktree
    # (tools/coding-effector-sandbox.yaml). If non-interactive Bash steps require
    # auto-approval, the operator may switch permission_mode to "bypassPermissions"
    # (documented experiment-only relaxation).
    effector_allowed_tools: tuple[str, ...] = ("Read", "Write", "Edit", "Bash")
    permission_mode: str = "acceptEdits"
    max_turns: int = 60
    budget_cap_usd: float = 10.0
    # Per-tier per-task budget caps so one pathological instance can't distort the curve
    # (manifest.md: E≈$3, M≈$5, H≈$8; tuned after the first triplet).
    tier_budget_caps: dict[str, float] = field(
        default_factory=lambda: {"easy": 3.0, "medium": 5.0, "hard": 8.0}
    )
    sandbox_profile: str = "coding-effector-default"
    network_policy: str = (
        "deny-by-default; allowlist PyPI + Anthropic API for the real run (experiment-only)"
    )

    @property
    def model_ids(self) -> list[str]:
        """Every pinned model id, de-duped in declaration order (effector first).

        The driver model(s) are included only when a driver is configured (the
        spine makes no driver calls), so faithful pins record all models actually
        used without changing the spine's recorded pins.
        """
        ids = [self.effector_model, self.fallback_model]
        for m in (self.driver_model, self.driver_fallback_model):
            if m and m not in ids:
                ids.append(m)
        return ids

    def price_for(self, model: str) -> dict[str, float]:
        return self.token_prices.get(model, {"input": 0.0, "output": 0.0})

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        p = self.price_for(model)
        return round(tokens_in / 1_000_000 * p["input"] + tokens_out / 1_000_000 * p["output"], 6)

    def budget_cap_for(self, tier: str) -> float:
        return self.tier_budget_caps.get(tier, self.budget_cap_usd)

    def render_effector_command(self, prompt: str) -> list[str]:
        return [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            self.effector_model,
            "--allowedTools",
            " ".join(self.effector_allowed_tools),
            "--permission-mode",
            self.permission_mode,
            "--max-turns",
            str(self.max_turns),
        ]

    def to_pins(self) -> dict[str, Any]:
        """The ``pins`` object recorded into results.json (results.schema.json)."""
        pins: dict[str, Any] = {
            "model_ids": self.model_ids,
            "effector_version": self.effector_version,
            "pricing_snapshot": self.pricing_snapshot,
            "cache_policy": self.cache_policy,
            "retrieval_config": self.retrieval_config,
            # extra (additionalProperties: true) — full reproducibility record
            "effector_model": self.effector_model,
            "fallback_model": self.fallback_model,
            "token_prices": self.token_prices,
            "embedding_model": self.embedding_model,
            "effector_allowed_tools": list(self.effector_allowed_tools),
            "permission_mode": self.permission_mode,
            "budget_cap_usd": self.budget_cap_usd,
            "sandbox_profile": self.sandbox_profile,
            "network_policy": self.network_policy,
        }
        if self.driver_model is not None:
            pins["driver"] = {
                "model": self.driver_model,
                "fallback_model": self.driver_fallback_model,
                "temperature": self.driver_temperature,
                "max_tokens": self.driver_max_tokens,
            }
        if self.embedding_model is not None:
            # Full embedding pin (ADR-0020 §5 + operator decision). The compact
            # ``<id>@<revision>`` string also goes into craft.validated_against,
            # whose schema only allows a string embedding_model.
            pins["embedding"] = {
                "model_id": self.embedding_model,
                "revision": self.embedding_revision,
                "sentence_transformers_version": self.sentence_transformers_version,
                "torch_version": self.torch_version,
                "normalize": self.embedding_normalize,
                "similarity": self.embedding_similarity,
                "k": self.retrieval_k,
                "query_prefix": self.embedding_query_prefix,
            }
        return pins

    def embedding_pin_string(self) -> str:
        """Compact ``<model>@<revision>`` for craft.validated_against (schema: string)."""
        if self.embedding_model is None:
            return "none"
        if self.embedding_revision:
            return f"{self.embedding_model}@{self.embedding_revision}"
        return self.embedding_model


def default_run_config() -> RunConfig:
    return RunConfig()


def orchestrator_run_config() -> RunConfig:
    """Run config for the T-1.3 driver loop (ADR-0020): Sonnet 4.6 driver + bge vector
    retrieval. Effector stays Opus 4.8. Driver decoding (temp 0) is pinned identically
    for Run A and Run B (the parity invariant); the bge revision + sentence-transformers
    version are filled in at first model load and frozen for the run."""
    return RunConfig(
        driver_model="claude-sonnet-4-6",
        driver_fallback_model="claude-haiku-4-5",
        driver_temperature=0.0,
        embedding_model="BAAI/bge-small-en-v1.5",
        # k = full library size (the 13-item taxonomy), so retrieval never caps the reuse
        # counter or G2 recall once the library fills (operator decision; see ADR-0023).
        retrieval_k=13,
        retrieval_config=(
            "vector retrieval (BAAI/bge-small-en-v1.5, normalized, cosine top-k=13 = full "
            "library; bge query-prefix on the query only); keyword/tag fallback (ADR-0020 §5)"
        ),
    )


DEFAULT_RUN_CONFIG = default_run_config()

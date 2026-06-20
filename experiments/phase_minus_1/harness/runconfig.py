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
    protocol_version: str = "v2"  # v2: results.schema run_kind amendment (see CHANGELOG.md)
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
    sandbox_profile: str = "coding-effector-default"
    network_policy: str = (
        "deny-by-default; allowlist PyPI + Anthropic API for the real run (experiment-only)"
    )

    @property
    def model_ids(self) -> list[str]:
        return [self.effector_model, self.fallback_model]

    def price_for(self, model: str) -> dict[str, float]:
        return self.token_prices.get(model, {"input": 0.0, "output": 0.0})

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        p = self.price_for(model)
        return round(tokens_in / 1_000_000 * p["input"] + tokens_out / 1_000_000 * p["output"], 6)

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
        return {
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


def default_run_config() -> RunConfig:
    return RunConfig()


DEFAULT_RUN_CONFIG = default_run_config()

"""Unit tests for the run config / pins (protocol.md 'Model and Pricing Pins')."""

from __future__ import annotations

from harness.runconfig import (
    DEFAULT_RUN_CONFIG,
    RunConfig,
    default_run_config,
    orchestrator_run_config,
)


def test_default_models_pinned() -> None:
    cfg = default_run_config()
    assert cfg.effector_model == "claude-opus-4-8"
    assert cfg.fallback_model == "claude-haiku-4-5"
    assert cfg.model_ids == ["claude-opus-4-8", "claude-haiku-4-5"]


def test_cached_pricing_snapshot_values() -> None:
    cfg = default_run_config()
    assert cfg.token_prices["claude-opus-4-8"] == {"input": 5.0, "output": 25.0}
    assert cfg.token_prices["claude-haiku-4-5"] == {"input": 1.0, "output": 5.0}
    assert "2026-05-26" in cfg.pricing_snapshot


def test_to_pins_has_required_schema_keys() -> None:
    pins = default_run_config().to_pins()
    for key in (
        "model_ids",
        "effector_version",
        "pricing_snapshot",
        "cache_policy",
        "retrieval_config",
    ):
        assert key in pins
    assert pins["model_ids"] == ["claude-opus-4-8", "claude-haiku-4-5"]
    # spine retrieval is keyword/tag, recorded honestly
    assert "keyword" in pins["retrieval_config"].lower()


def test_effector_command_is_scoped_and_parametrised() -> None:
    cfg = default_run_config()
    cmd = cfg.render_effector_command("BUILD THE THING")
    assert cmd[0] == "claude"
    assert "BUILD THE THING" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--model" in cmd and "claude-opus-4-8" in cmd
    # scoped permissions preferred over a blanket skip
    assert "--dangerously-skip-permissions" not in cmd


def test_estimate_cost() -> None:
    cfg = default_run_config()
    # 1M in + 1M out on Opus 4.8 = $5 + $25
    assert cfg.estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000) == 30.0
    assert cfg.estimate_cost("claude-haiku-4-5", 2_000_000, 0) == 2.0


def test_default_run_config_is_a_runconfig() -> None:
    assert isinstance(DEFAULT_RUN_CONFIG, RunConfig)
    assert DEFAULT_RUN_CONFIG.protocol_version == "v3"


# --------------------------------------------------------------------------- #
# T-1.3: driver + embedding pins (ADR-0020 §3/§5, locked decisions)
# --------------------------------------------------------------------------- #
def test_spine_default_has_no_driver_or_vector_pins() -> None:
    """The spine config is unchanged: keyword retrieval, no driver model calls."""
    cfg = default_run_config()
    assert cfg.driver_model is None
    assert cfg.model_ids == ["claude-opus-4-8", "claude-haiku-4-5"]
    pins = cfg.to_pins()
    assert "driver" not in pins
    assert "keyword" in pins["retrieval_config"].lower()


def test_orchestrator_config_pins_driver_sonnet_haiku_temp0() -> None:
    cfg = orchestrator_run_config()
    assert cfg.driver_model == "claude-sonnet-4-6"
    assert cfg.driver_fallback_model == "claude-haiku-4-5"
    assert cfg.driver_temperature == 0.0
    # effector stays Opus 4.8 (ADR-0020 §3)
    assert cfg.effector_model == "claude-opus-4-8"
    # all four models are recorded as pinned model ids (faithful accounting)
    assert cfg.model_ids == [
        "claude-opus-4-8",
        "claude-haiku-4-5",
        "claude-sonnet-4-6",
    ]


def test_orchestrator_config_pins_bge_embedding() -> None:
    cfg = orchestrator_run_config()
    assert cfg.embedding_model == "BAAI/bge-small-en-v1.5"
    assert cfg.embedding_normalize is True
    assert cfg.embedding_similarity == "cosine"
    # k = full library size (the 13-item taxonomy), so retrieval never caps reuse / G2
    assert cfg.retrieval_k == 13
    # bge query-instruction prefix, applied to the QUERY only (operator decision)
    assert cfg.embedding_query_prefix.startswith("Represent this sentence")


def test_orchestrator_to_pins_records_driver_and_embedding() -> None:
    pins = orchestrator_run_config().to_pins()
    # driver block (byte-identical across A/B; recorded before task 1)
    assert pins["driver"]["model"] == "claude-sonnet-4-6"
    assert pins["driver"]["fallback_model"] == "claude-haiku-4-5"
    assert pins["driver"]["temperature"] == 0.0
    # embedding block: full reproducibility record
    assert pins["embedding_model"] == "BAAI/bge-small-en-v1.5"
    emb = pins["embedding"]
    assert emb["model_id"] == "BAAI/bge-small-en-v1.5"
    assert emb["normalize"] is True
    assert emb["similarity"] == "cosine"
    assert emb["k"] == 13
    assert "revision" in emb and "sentence_transformers_version" in emb
    assert "torch_version" in emb  # recorded at first model load for the pilot
    assert emb["query_prefix"].startswith("Represent this sentence")
    # retrieval_config now names the vector retriever
    assert "vector" in pins["retrieval_config"].lower()
    assert "bge" in pins["retrieval_config"].lower()


def test_driver_cost_uses_pinned_prices() -> None:
    cfg = orchestrator_run_config()
    # 1M in + 1M out on Sonnet 4.6 = $3 + $15
    assert cfg.estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0

"""Unit tests for the run config / pins (protocol.md 'Model and Pricing Pins')."""

from __future__ import annotations

from harness.runconfig import DEFAULT_RUN_CONFIG, RunConfig, default_run_config


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
    assert DEFAULT_RUN_CONFIG.protocol_version == "v1"

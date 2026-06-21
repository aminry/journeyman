"""A-then-B full-run driver proofs (Fix #4, fakes only, zero spend).

Gated proofs for the 30x2:
  * the prompt/decoding parity assert FIRES on a mismatch (A-B delta can't be confounded);
  * the control run physically CANNOT read Run A's craft dir (separate dirs, B frozen-empty);
  * one invocation runs A (accumulates) then B (frozen-empty + discard) over the same order.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from harness.craft import CraftLibrary
from harness.driver import FakeDriver
from harness.effector import FakeEffector
from harness.embedding import DeterministicHashEmbedder
from harness.experiment_cli import assert_prompt_parity, run_experiment
from harness.gold import GoldMap
from harness.runconfig import orchestrator_run_config

REPO = Path(__file__).resolve().parents[2]
GOLD = GoldMap.load(REPO / "experiments" / "phase_minus_1" / "retrieval_gold.yaml")
VA = {"models": ["claude-sonnet-4-6"], "effector_version": "fake@test", "embedding_model": "det"}


def _driver() -> FakeDriver:
    return FakeDriver(validated_against=VA, last_validated="2026-06-20T00:00:00Z")


# --- parity assert FIRES --------------------------------------------------- #
def test_parity_assert_fires_on_prompt_mismatch() -> None:
    cfg = orchestrator_run_config()
    a, b = _driver(), _driver()
    object.__setattr__(b, "system_prompt", a.system_prompt + " (tampered)")
    with pytest.raises(AssertionError, match="prompt parity"):
        assert_prompt_parity(a, b, cfg, cfg)


def test_parity_assert_fires_on_decoding_mismatch() -> None:
    a, b = _driver(), _driver()
    cfg_a = orchestrator_run_config()
    cfg_b = dataclasses.replace(cfg_a, driver_temperature=0.7)  # decoding drift
    with pytest.raises(AssertionError, match="decoding parity"):
        assert_prompt_parity(a, b, cfg_a, cfg_b)


def test_parity_holds_for_identical_drivers() -> None:
    cfg = orchestrator_run_config()
    assert_prompt_parity(_driver(), _driver(), cfg, cfg) is None


# --- control isolation ----------------------------------------------------- #
def test_same_craft_dir_for_a_and_b_is_rejected(tmp_path: Path) -> None:
    cfg = orchestrator_run_config()
    with pytest.raises(ValueError, match="separate craft dirs"):
        run_experiment(
            positions=[1],
            cfg=cfg,
            embedder=DeterministicHashEmbedder(dim=64),
            gold=GOLD,
            workdir=tmp_path / "wd",
            craft_dir_a=tmp_path / "c",
            craft_dir_b=tmp_path / "c",
            out_dir=tmp_path / "out",
            driver_factory=_driver,
            effector_factory=lambda arm: FakeEffector(cfg, artifact_dir=tmp_path / arm),
        )


def test_run_experiment_control_cannot_read_treatment_craft(tmp_path: Path) -> None:
    cfg = orchestrator_run_config()

    def effector_factory(arm: str) -> FakeEffector:
        return FakeEffector(cfg, artifact_dir=tmp_path / f"run{arm}" / "eff")

    res_a, res_b = run_experiment(
        positions=[1, 2, 3],
        cfg=cfg,
        embedder=DeterministicHashEmbedder(dim=512),
        gold=GOLD,
        workdir=tmp_path / "wd",
        craft_dir_a=tmp_path / "craft_A",
        craft_dir_b=tmp_path / "craft_B",
        out_dir=tmp_path / "out",
        driver_factory=_driver,
        effector_factory=effector_factory,
        global_budget_cap_usd=350.0,
    )
    # Run A accumulated craft; Run B's craft dir is physically EMPTY (frozen-empty control).
    assert CraftLibrary(tmp_path / "craft_A").ids()  # A has craft
    assert CraftLibrary(tmp_path / "craft_B").ids() == []  # B has NONE — cannot read A
    # every B task retrieved/reused nothing (frozen-empty), every A task is treatment
    assert all(
        not r["craft_items_retrieved"] and not r["craft_items_reused"] for r in res_b.records
    )
    assert res_a.run_mode == "treatment" and res_b.run_mode == "control"
    # both arms ran the full order; both results docs were written
    assert {r["position"] for r in res_a.records} == {1, 2, 3}
    assert {r["position"] for r in res_b.records} == {1, 2, 3}
    assert (tmp_path / "out" / "runA.results.json").exists()
    assert (tmp_path / "out" / "runB.results.json").exists()


def test_non_empty_control_craft_dir_is_rejected(tmp_path: Path) -> None:
    cfg = orchestrator_run_config()
    # pre-seed B's dir so it's non-empty -> frozen-empty control violated
    lib_b = CraftLibrary(tmp_path / "craft_B")
    from harness.reflection import template_for_craft_id

    lib_b.write(
        template_for_craft_id("crud-spec-template").to_craft_item(
            validated_against=VA, last_validated="2026-06-20T00:00:00Z"
        )
    )
    with pytest.raises(ValueError, match="frozen-empty control"):
        run_experiment(
            positions=[1],
            cfg=cfg,
            embedder=DeterministicHashEmbedder(dim=64),
            gold=GOLD,
            workdir=tmp_path / "wd",
            craft_dir_a=tmp_path / "craft_A",
            craft_dir_b=tmp_path / "craft_B",
            out_dir=tmp_path / "out",
            driver_factory=_driver,
            effector_factory=lambda arm: FakeEffector(cfg, artifact_dir=tmp_path / arm),
        )

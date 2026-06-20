"""A/B orchestrator harness proof on the pilot triplet, fakes only (ADR-0020 §1-§6).

This is the T-1.3 build acceptance (staging step 1): drive the full per-task loop
(retrieve → compose → drive effector → gate → reflect) over positions 1-3
([E1,M1,H1] = notes/books/orders) with a FakeDriver + FakeEffector — ZERO spend — and
prove the invariants:

* Run A composes WITH craft and the library accumulates + is reused on later tasks;
* Run B is frozen-empty + run-and-discard reflection (no craft ever persists);
* both produce schema-valid records (run_kind=experiment);
* the driver prompt is BYTE-IDENTICAL across A and B (parity invariant);
* the driver carries NO cross-task state (fresh context; only the on-disk library persists);
* faithful cost: model_cost (driver) and effector_cost are both first-class and > 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.craft import CraftLibrary
from harness.driver import DRIVER_SYSTEM_PROMPT, FakeDriver
from harness.effector import FakeEffector
from harness.embedding import DeterministicHashEmbedder
from harness.gold import GoldMap
from harness.orchestrator import RunInputs, run_sequence
from harness.results import is_real_experiment_decision, validate_results
from harness.retrieval import VectorCraftRetriever
from harness.runconfig import orchestrator_run_config

REPO = Path(__file__).resolve().parents[2]
P1 = REPO / "experiments" / "phase_minus_1"
GOLD = GoldMap.load(P1 / "retrieval_gold.yaml")
VA = {
    "models": ["claude-sonnet-4-6"],
    "effector_version": "fake-effector@test",
    "embedding_model": "deterministic-hash-512",
}
PILOT = [1, 2, 3]  # notes (E1), books (M1), orders (H1)


def _inputs(workdir: Path, run_mode: str) -> RunInputs:
    cfg = orchestrator_run_config()
    library = CraftLibrary(workdir / f"craft_{run_mode}")
    driver = FakeDriver(validated_against=VA, last_validated="2026-06-20T00:00:00Z")
    retriever = VectorCraftRetriever(library, DeterministicHashEmbedder(dim=512), k=cfg.retrieval_k)
    effector = FakeEffector(cfg, artifact_dir=workdir / f"eff_{run_mode}")
    return RunInputs(
        config=cfg,
        driver=driver,
        effector=effector,
        retriever=retriever,
        library=library,
        gold=GOLD,
        workdir=workdir,
    )


@pytest.fixture(scope="module")
def run_a(tmp_path_factory):
    wd = tmp_path_factory.mktemp("ab")
    inp = _inputs(wd, "treatment")
    res = run_sequence(PILOT, run_mode="treatment", inputs=inp, run_id="pilot_A")
    return res, inp


@pytest.fixture(scope="module")
def run_b(tmp_path_factory):
    wd = tmp_path_factory.mktemp("ab")
    inp = _inputs(wd, "control")
    res = run_sequence(PILOT, run_mode="control", inputs=inp, run_id="pilot_B")
    return res, inp


def test_run_a_results_validate_as_experiment(run_a) -> None:
    res, _ = run_a
    validate_results(res.results_doc)
    assert res.results_doc["run_kind"] == "experiment"
    assert len(res.records) == 3
    # a 3-task pilot is NOT a real experimental decision (needs 30 + control)
    assert is_real_experiment_decision(res.results_doc) is False


def test_run_a_accumulates_and_reuses_craft(run_a) -> None:
    res, inp = run_a
    # the library grew via reflection (one per task here)
    assert len(inp.library.ids()) >= 3
    # reuse rises: task 1 has nothing to retrieve, later tasks reuse accumulated craft
    reused_counts = [len(r["craft_items_reused"]) for r in res.records]
    assert reused_counts[0] == 0
    assert reused_counts[2] >= 1
    # reuse is verified-incorporated, hence a subset of retrieved
    for r in res.records:
        assert set(r["craft_items_reused"]) <= set(r["craft_items_retrieved"])


def test_run_a_costs_are_faithful_and_separated(run_a) -> None:
    res, _ = run_a
    for r in res.records:
        assert r["model_cost_usd"] > 0  # the driver made compose + reflect calls
        assert r["effector_cost_usd"] > 0
        assert r["total_cost_usd"] == pytest.approx(r["model_cost_usd"] + r["effector_cost_usd"])


def test_run_b_is_frozen_empty_and_discards_reflection(run_b) -> None:
    res, inp = run_b
    # the control library never accumulates craft
    assert inp.library.ids() == []
    for r in res.records:
        assert r["craft_items_retrieved"] == []
        assert r["craft_items_reused"] == []
    # ...yet the driver still ran compose + reflect (driver-cost parity with A)
    assert all(r["model_cost_usd"] > 0 for r in res.records)
    validate_results(res.results_doc)


def test_driver_prompt_is_byte_identical_across_a_and_b(run_a, run_b) -> None:
    (_, inp_a), (_, inp_b) = run_a, run_b
    assert inp_a.driver.system_prompt == inp_b.driver.system_prompt == DRIVER_SYSTEM_PROMPT


def test_driver_holds_no_cross_task_state(run_a) -> None:
    """Fresh context: the only thing that persists across tasks is the on-disk library.
    The driver instance must expose no per-task/per-instance attributes."""
    _, inp = run_a
    state_keys = set(vars(inp.driver))
    # only run-level constants — no spec, no retrieved, no messages, no counters
    assert state_keys == {"system_prompt", "_validated_against", "_last_validated"}


def test_run_a_emits_retrieval_precision_diagnostic(run_a) -> None:
    res, _ = run_a
    assert len(res.diagnostics) == 3
    # the diagnostic reports per-position curated recall + the curated/auto divergence
    summary = res.diagnostic_summary
    assert "mean_curated_recall" in summary
    assert "per_position_curated_recall" in summary
    # orders (pos 3) is hard: curated key includes universals the auto map cannot see
    orders_diag = res.diagnostics[2]
    assert orders_diag.instance_id == "orders"


def test_held_out_integrity_repo_has_no_contract_tests(run_a) -> None:
    res, _ = run_a
    for art in res.tasks:
        for path in art.repo_dir.rglob("*.py"):
            if ".git" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            assert "compile_contract_suite" not in text and "import harness" not in text

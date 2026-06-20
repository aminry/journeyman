"""End-to-end spine test with the FAKE effector (zero spend, CI-safe).

Exercises the whole pipeline: retrieve craft -> scaffold fresh repo -> drive
effector (spec only) -> boot real service on $PORT -> wait /healthz -> run the
generated contract suite + instance DoD -> teardown -> validated results.json +
trace. This is the T-1.1 acceptance shape, with the effector faked so it costs
nothing; the single REAL run is identical but with ClaudeCodeEffector.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.craft import CraftLibrary, seed_default_craft
from harness.effector import FakeEffector
from harness.results import validate_results
from harness.runconfig import default_run_config
from harness.runner import run_instance

REPO = Path(__file__).resolve().parents[2]
BOOKS = REPO / "experiments" / "phase_minus_1" / "instances" / "example_books.spec.yaml"


@pytest.fixture(scope="module")
def run_result(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("spine")
    cfg = default_run_config()
    craft_lib = CraftLibrary(workdir / "craft")
    seed_default_craft(craft_lib)
    eff = FakeEffector(cfg, artifact_dir=workdir / "eff_artifacts")
    return run_instance(
        BOOKS,
        config=cfg,
        effector=eff,
        workdir=workdir,
        craft_lib=craft_lib,
        run_id="spine_books",
        position=1,
    )


def test_results_json_validates(run_result) -> None:
    validate_results(run_result.results_doc)  # must not raise
    assert run_result.results_path.exists()


def test_run_is_labeled_self_test_not_a_decision(run_result) -> None:
    from harness.results import is_real_experiment_decision

    assert run_result.results_doc["run_kind"] == "harness_selftest"
    # never reads as a pass, and the analysis guard ignores it
    assert run_result.results_doc["decision"]["status"] not in {"pass", "provisional_pass"}
    assert is_real_experiment_decision(run_result.results_doc) is False


def test_contract_suite_all_passed(run_result) -> None:
    failures = [(cid, d) for cid, ok, d in run_result.suite_result.results if not ok]
    assert run_result.suite_result.all_passed, f"contract failures: {failures}"
    assert run_result.suite_result.total >= 30
    assert run_result.record["contract_passed"] is True


def test_effector_cost_is_nonzero_and_complete(run_result) -> None:
    rec = run_result.record
    assert rec["effector_cost_usd"] > 0
    assert rec["model_cost_usd"] == 0.0  # spine driver makes no model calls (first-class)
    assert rec["total_cost_usd"] == pytest.approx(rec["effector_cost_usd"])


def test_dod_passed(run_result) -> None:
    assert run_result.record["dod_passed"] is True


def test_craft_retrieved_and_reused(run_result) -> None:
    assert "fastapi-sqlite-scaffold" in run_result.record["craft_items_retrieved"]
    assert "fastapi-sqlite-scaffold" in run_result.record["craft_items_reused"]


def test_craft_library_usage_recorded(run_result, tmp_path_factory) -> None:
    # the reuse counter persisted what was retrieved/reused for this task
    rec = run_result.record
    assert rec["craft_items_reused"]  # non-empty -> counter exercised end to end


def test_held_out_repo_has_no_contract_tests(run_result) -> None:
    repo = run_result.repo_dir
    assert (repo / "app.py").exists() and (repo / "run.sh").exists()
    for path in repo.rglob("*.py"):
        if ".git" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        assert "compile_contract_suite" not in text
        assert "import harness" not in text


def test_trace_has_effector_session_span(run_result) -> None:
    kinds = {s["kind"] for s in run_result.trace["spans"]}
    assert "effector_session" in kinds
    eff = next(s for s in run_result.trace["spans"] if s["kind"] == "effector_session")
    assert eff["cost_usd"] > 0 and "diff_ref" in eff


def test_first_pass_contract_success(run_result) -> None:
    assert run_result.record["first_pass_contract_success"] is True
    assert run_result.record["effector_retries"] == 0


def test_runs_with_relative_workdir(tmp_path, monkeypatch) -> None:
    """Regression: a relative workdir must still boot the service.

    run.sh `cd`s into the repo, so any relative path the runner hands the service
    (e.g. SERVICE_DB) would resolve against the wrong dir and fail to open the
    database. The runner must use absolute paths.
    """
    monkeypatch.chdir(tmp_path)
    cfg = default_run_config()
    craft_lib = CraftLibrary("craft_rel")
    seed_default_craft(craft_lib)
    result = run_instance(
        BOOKS,
        config=cfg,
        effector=FakeEffector(cfg),
        workdir="relwork",
        craft_lib=craft_lib,
        run_id="rel",
        position=1,
    )
    assert result.record["contract_passed"] is True
    assert result.record["dod_passed"] is True

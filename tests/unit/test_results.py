"""Unit tests for per-task records + single-task results.json (results.schema.json)."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.results import (
    build_results,
    build_task_record,
    spine_aggregate,
    spine_decision,
    validate_results,
    write_results,
)
from harness.runconfig import default_run_config

REPO = Path(__file__).resolve().parents[2]


def sample_record(**over):
    base = dict(
        position=1,
        task_id="books",
        tier="medium",
        model_cost_usd=0.0,
        effector_cost_usd=0.525,
        tool_cost_usd=0.0,
        wall_clock_seconds=12.3,
        dod_passed=True,
        contract_tests_passed=44,
        contract_tests_total=44,
        effector_retries=0,
        first_pass_contract_success=True,
        craft_retrieved=["fastapi-sqlite-scaffold"],
        craft_reused=["fastapi-sqlite-scaffold"],
        trace_id="tr_books",
    )
    base.update(over)
    return build_task_record(**base)


def test_task_record_has_required_keys() -> None:
    rec = sample_record()
    required = {
        "position",
        "task_id",
        "tier",
        "total_cost_usd",
        "wall_clock_seconds",
        "dod_passed",
        "contract_passed",
        "contract_tests_passed",
        "contract_tests_total",
        "effector_retries",
        "first_pass_contract_success",
        "craft_items_retrieved",
        "craft_items_reused",
        "trace_id",
    }
    assert required <= set(rec)


def test_total_cost_is_complete_sum() -> None:
    rec = sample_record(model_cost_usd=0.10, effector_cost_usd=0.50, tool_cost_usd=0.05)
    # faithful cost: model + effector + tool, nothing hidden
    assert rec["total_cost_usd"] == pytest.approx(0.65)
    assert rec["model_cost_usd"] == 0.10
    assert rec["effector_cost_usd"] == 0.50


def test_contract_passed_derived_from_counts() -> None:
    assert (
        sample_record(contract_tests_passed=44, contract_tests_total=44)["contract_passed"] is True
    )
    assert (
        sample_record(contract_tests_passed=43, contract_tests_total=44)["contract_passed"] is False
    )


def test_full_results_validates_against_schema() -> None:
    cfg = default_run_config()
    rec = sample_record()
    agg = spine_aggregate([rec])
    decision = spine_decision([rec])
    results = build_results(
        run_id="run_spine_books",
        started_at="2026-06-19T10:00:00Z",
        completed_at="2026-06-19T10:00:12Z",
        pins=cfg.to_pins(),
        tasks=[rec],
        aggregate=agg,
        decision=decision,
    )
    # must not raise
    validate_results(results)
    assert results["decision"]["status"] != "pass"  # no control run -> never a full pass


def test_spine_decision_is_not_a_full_pass_and_flags_residuals() -> None:
    rec = sample_record()
    d = spine_decision([rec])
    assert d["status"] in {"provisional_pass", "fail", "invalid", "stopped"}
    assert d["residual_risks"]  # must name what's missing (control run, n=1, ...)


def test_aggregate_marks_control_absent() -> None:
    agg = spine_aggregate([sample_record()])
    assert agg["control_run_present"] is False
    for key in (
        "warmup_tasks",
        "cost_slope_after_warmup",
        "cost_slope_ci",
        "min_detectable_slope",
        "treatment_vs_control_delta",
        "quality_holds",
        "reuse_is_real",
        "security_controls_held",
    ):
        assert key in agg


def test_validate_results_rejects_bad_record() -> None:
    cfg = default_run_config()
    bad = sample_record()
    del bad["trace_id"]  # required by schema
    results = build_results(
        run_id="r",
        started_at="2026-06-19T10:00:00Z",
        completed_at="2026-06-19T10:00:12Z",
        pins=cfg.to_pins(),
        tasks=[bad],
        aggregate=spine_aggregate([bad]),
        decision=spine_decision([bad]),
    )
    with pytest.raises(Exception):
        validate_results(results)


def test_write_results_validates_then_writes(tmp_path) -> None:
    cfg = default_run_config()
    rec = sample_record()
    results = build_results(
        run_id="r",
        started_at="2026-06-19T10:00:00Z",
        completed_at="2026-06-19T10:00:12Z",
        pins=cfg.to_pins(),
        tasks=[rec],
        aggregate=spine_aggregate([rec]),
        decision=spine_decision([rec]),
    )
    out = write_results(results, tmp_path / "nested" / "results.json")
    assert out.exists()
    import json

    assert json.loads(out.read_text())["run_id"] == "r"


def test_write_results_rejects_invalid(tmp_path) -> None:
    cfg = default_run_config()
    bad = sample_record()
    del bad["task_id"]
    results = build_results(
        run_id="r",
        started_at="2026-06-19T10:00:00Z",
        completed_at="2026-06-19T10:00:12Z",
        pins=cfg.to_pins(),
        tasks=[bad],
        aggregate=spine_aggregate([bad]),
        decision=spine_decision([bad]),
    )
    with pytest.raises(Exception):
        write_results(results, tmp_path / "results.json")

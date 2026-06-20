"""Build and validate per-task records and the single-task results.json.

Every record is validated against ``results.schema.json`` before it is written
(the prompt's "Validate every per-task record ... before writing it"). Two
invariants are enforced here:

* **Faithful cost** — ``total_cost_usd = model + effector + tool`` spend, nothing
  hidden (SPEC §14, ADR-0015). ``model_cost_usd`` is kept first-class even though
  it is 0 in the deterministic spine (the driver/orchestrator at T-1.3 will make
  model calls; the field must already exist and be accounted separately).
* **No false pass** — a single-arm run can never report ``decision.status ==
  "pass"`` (results.schema.json requires the mandatory control run for that). The
  spine reports an explicitly lower-confidence, residual-flagged decision.

The task record obeys the schema's ``additionalProperties: false`` — only
schema-allowed keys are emitted (tool spend is folded into ``total_cost_usd``,
since the per-task schema has no separate tool field; it lives on the trace span).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "results.schema.json"


def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def build_task_record(
    *,
    position: int,
    task_id: str,
    tier: str,
    model_cost_usd: float,
    effector_cost_usd: float,
    tool_cost_usd: float,
    wall_clock_seconds: float,
    dod_passed: bool,
    contract_tests_passed: int,
    contract_tests_total: int,
    effector_retries: int,
    first_pass_contract_success: bool,
    craft_retrieved: list[str],
    craft_reused: list[str],
    trace_id: str,
    human_interventions: int = 0,
    security_events: list[str] | None = None,
    excluded_from_slope: bool | None = None,
    exclusion_reason: str | None = None,
) -> dict[str, Any]:
    total = round(model_cost_usd + effector_cost_usd + tool_cost_usd, 6)
    record: dict[str, Any] = {
        "position": position,
        "task_id": task_id,
        "tier": tier,
        "model_cost_usd": round(model_cost_usd, 6),
        "effector_cost_usd": round(effector_cost_usd, 6),
        "total_cost_usd": total,
        "wall_clock_seconds": round(wall_clock_seconds, 3),
        "dod_passed": dod_passed,
        "contract_passed": contract_tests_passed == contract_tests_total,
        "contract_tests_passed": contract_tests_passed,
        "contract_tests_total": contract_tests_total,
        "effector_retries": effector_retries,
        "first_pass_contract_success": first_pass_contract_success,
        "craft_items_retrieved": list(craft_retrieved),
        "craft_items_reused": list(craft_reused),
        "human_interventions": human_interventions,
        "security_events": list(security_events or []),
        "trace_id": trace_id,
    }
    if excluded_from_slope is not None:
        record["excluded_from_slope"] = excluded_from_slope
    if exclusion_reason is not None:
        record["exclusion_reason"] = exclusion_reason
    return record


def spine_aggregate(tasks: list[dict]) -> dict[str, Any]:
    """Aggregate block for a spine run.

    At n=1 no slope is computable; the fields are present (schema requires them)
    but explicitly neutral, and ``control_run_present`` is false — so this can
    never satisfy the schema's full-pass branch.
    """
    quality = all(t["contract_passed"] and t["dod_passed"] for t in tasks)
    reuse = any(t["craft_items_reused"] for t in tasks)
    security_ok = all(not t.get("security_events") for t in tasks)
    return {
        "warmup_tasks": 5,
        "cost_slope_after_warmup": 0.0,
        "cost_slope_ci": [0.0, 0.0],
        "min_detectable_slope": 0.0,
        "control_run_present": False,
        "treatment_vs_control_delta": 0.0,
        "quality_holds": quality,
        "reuse_is_real": reuse,
        "security_controls_held": security_ok,
        "note": (
            "Spine smoke run: n too small for a slope; warm-up/slope/CI are placeholders. "
            "Real values come from T-1.3 (30-task Run A + mandatory control Run B)."
        ),
    }


def spine_decision(tasks: list[dict]) -> dict[str, Any]:
    """A harness self-test makes NO experimental decision.

    Paired with ``run_kind="harness_selftest"``, the status is deliberately
    ``"invalid"`` (not ``provisional_pass``, which reads too close to a pass): as an
    *experimental* decision this run is not valid — it only proves the machinery
    works. The real decision requires ``run_kind="experiment"`` over the full task
    set with the control run (T-1.4); see :func:`is_real_experiment_decision`.
    """
    return {
        "status": "invalid",
        "rationale": (
            "HARNESS SELF-TEST (run_kind=harness_selftest), NOT an experimental "
            "decision and must not be read or aggregated as one. The T-1.1 spine is "
            "validated end-to-end on one instance (books): scaffold -> drive effector "
            "(spec only) -> boot -> contract suite -> DoD -> per-task record. A real "
            "Phase -1 decision requires run_kind=experiment over the full 30-task set "
            "with Run A + the mandatory control Run B and the pre-registered "
            "statistical test (ADR-0017, T-1.3/T-1.4)."
        ),
        "residual_risks": [
            "Single task (n=1): no cost slope, no warm-up exclusion, no statistical test.",
            "No control run (Run B): treatment-vs-control delta not yet measured.",
            "Spine uses keyword/tag retrieval; protocol's vector retrieval lands at T-1.3.",
            "Instance DoD is the minimal wired subset; full typed-gate DoD is Phase-0 (T0.7).",
            "Driver/orchestrator not yet present: craft was hand-seeded, not agent-written.",
        ],
    }


# The full Phase -1 task set a real experimental decision is computed over.
EXPERIMENT_TASK_COUNT = 30


def build_results(
    *,
    run_id: str,
    run_kind: str,
    started_at: str,
    completed_at: str,
    pins: dict,
    tasks: list[dict],
    aggregate: dict,
    decision: dict,
    protocol_version: str = "v3",
) -> dict[str, Any]:
    if run_kind not in ("experiment", "harness_selftest"):
        raise ValueError(f"run_kind must be 'experiment' or 'harness_selftest', got {run_kind!r}")
    return {
        "protocol_version": protocol_version,
        "run_id": run_id,
        "run_kind": run_kind,
        "started_at": started_at,
        "completed_at": completed_at,
        "pins": pins,
        "tasks": tasks,
        "aggregate": aggregate,
        "decision": decision,
    }


def is_real_experiment_decision(results: dict) -> bool:
    """Guard for T-1.4 analysis: only a full experiment run yields a real decision.

    True only when the run is an ``experiment`` (not a harness self-test), covers the
    full task set, and has the mandatory control run. Anything else — including every
    spine/smoke artifact under ``results/_selftest/`` — must be ignored by the
    pass/stop analysis.
    """
    return (
        results.get("run_kind") == "experiment"
        and len(results.get("tasks", [])) >= EXPERIMENT_TASK_COUNT
        and bool(results.get("aggregate", {}).get("control_run_present"))
    )


def validate_results(results: dict) -> None:
    """Validate a results document against results.schema.json (fail-closed)."""
    jsonschema.validate(results, _schema())


def write_results(results: dict, path: str | Path) -> Path:
    """Validate then write a results document."""
    validate_results(results)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(results, indent=2))
    return p

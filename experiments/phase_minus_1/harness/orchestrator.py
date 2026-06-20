"""The Phase −1 orchestrator: the per-task driver loop + Run A/B (ADR-0020).

This is what the T-1.1 spine deliberately lacked: the driver/orchestrator that, per task,
turns the instance spec + retrieved craft into the effector's TaskSpec and reflects
afterward to grow the craft library. The kernel (this module), not the model, moves data,
runs the effector, and writes durable stores (SPEC §12).

Per task (ADR-0020 §1):

  A. retrieve craft (vector; control = frozen-empty)         -> retrieved
  B. driver.compose(spec, retrieved)                         -> taskspec_text, incorporated
     reuse = verified-incorporated (markers actually present)
  C. drive the coding effector (boundary instrumented)       -> effector_session
  D. boot -> /healthz -> contract suite + instance DoD        -> gate
  E. driver.reflect(...) — ALWAYS runs (driver-cost parity); treatment persists the
     craft mutation, control discards it.

Invariants (ADR-0020 §2/§6):

* **Fresh context per task** — the driver is stateless; the ONLY state persisting across
  tasks is the on-disk craft library (treatment) — never in control.
* **Byte-identical driver prompt across A/B** — both runs use the same driver + decoding;
  B differs ONLY by a frozen-empty library + run-and-discard reflection.
* **Held-out integrity** — the effector receives the composed spec, never the tests.
* **Faithful cost** — model_cost (driver) + effector_cost, both first-class; every record
  validates against results.schema.json (protocol v3).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from harness.compiler import SuiteResult, run_suite
from harness.craft import CraftItem, CraftLibrary
from harness.craftimpact import RunningBaseline, quarantine_harmful, update_craft_metrics
from harness.driver import Driver, GateOutcome, verify_incorporated
from harness.effector import Effector, EffectorTask, drive_coding_effector
from harness.gold import GoldMap, RetrievalDiagnostic, retrieval_diagnostic, summarize_diagnostics
from harness.render import write_pytest_module
from harness.results import build_results, build_task_record, validate_results
from harness.retrieval import Retriever
from harness.reflection import project_strip_lint
from harness.runconfig import RunConfig
from harness.runner import (
    DodResult,
    _boot,
    _spec_to_dict,
    _teardown,
    _wait_for_health,
    assert_held_out,
    build_trace,
    free_port,
    run_instance_dod,
    validate_trace,
)
from harness.scaffolder import scaffold_repo
from harness.specschema import InstanceSpec, load_spec
from harness.taskspec import spec_digest

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_TASKSET = _REPO / "experiments" / "phase_minus_1" / "taskset.json"
DEFAULT_GOLD = _REPO / "experiments" / "phase_minus_1" / "retrieval_gold.yaml"

TREATMENT = "treatment"
CONTROL = "control"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Task set
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TaskInfo:
    position: int
    id: str
    tier: str
    spec_path: str
    feature_tags: list[str]


def load_taskset(path: str | Path = DEFAULT_TASKSET) -> list[TaskInfo]:
    data = json.loads(Path(path).read_text())
    return [
        TaskInfo(
            position=t["position"],
            id=t["id"],
            tier=t["tier"],
            spec_path=t["spec_path"],
            feature_tags=list(t["feature_tags"]),
        )
        for t in data["task_order"]
    ]


# --------------------------------------------------------------------------- #
# Inputs + outputs
# --------------------------------------------------------------------------- #
@dataclass
class RunInputs:
    config: RunConfig
    driver: Driver
    effector: Effector
    retriever: Retriever  # bound to ``library``
    library: CraftLibrary
    gold: GoldMap
    workdir: Path


@dataclass
class TaskArtifacts:
    record: dict
    trace: dict
    taskspec_text: str
    retrieved: list[str]
    reused: list[str]
    incorporated: list[str]
    reflect_action: str
    reflect_rationale: str
    craft_written: str | None
    diagnostic: RetrievalDiagnostic
    suite: SuiteResult
    dod: DodResult
    repo_dir: Path
    artifacts_dir: Path


@dataclass
class OrchestratorResult:
    run_id: str
    run_mode: str
    results_doc: dict
    records: list[dict]
    diagnostics: list[RetrievalDiagnostic]
    diagnostic_summary: dict
    tasks: list[TaskArtifacts]
    library: CraftLibrary
    baseline: RunningBaseline


# --------------------------------------------------------------------------- #
# Cost
# --------------------------------------------------------------------------- #
def _driver_cost(config: RunConfig, calls: list[tuple[str, int, int]]) -> float:
    return round(sum(config.estimate_cost(m, ti, to) for m, ti, to in calls), 6)


# --------------------------------------------------------------------------- #
# One task
# --------------------------------------------------------------------------- #
def run_one_task(
    *,
    inputs: RunInputs,
    task: TaskInfo,
    run_mode: str,
    run_id: str,
    baseline: RunningBaseline,
) -> TaskArtifacts:
    cfg = inputs.config
    spec: InstanceSpec = load_spec(_REPO / task.spec_path)
    workdir = Path(inputs.workdir).resolve()
    inst_dir = workdir / run_id / spec.id
    repo_dir = inst_dir / "repo"
    artifacts_dir = inst_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    if hasattr(inputs.effector, "artifact_dir"):
        inputs.effector.artifact_dir = artifacts_dir
    trace_id = f"tr_{run_id}_{spec.id}".replace("-", "_")
    started_at = _now()
    t0 = time.monotonic()

    # --- A. retrieve (control = frozen-empty library, no retrieval) --------- #
    present_ids = {
        cid for cid in inputs.library.ids() if inputs.library.read(cid).status == "active"
    }
    if run_mode == CONTROL:
        retrieved_items: list[CraftItem] = []
    else:
        retrieved_items = inputs.retriever.retrieve(
            feature_tags=task.feature_tags, spec_digest=spec_digest(spec)
        )
    retrieved_ids = [it.id for it in retrieved_items]

    # --- B. compose (driver model call) ------------------------------------ #
    compose = inputs.driver.compose(spec=spec, retrieved=retrieved_items)
    reused_ids = verify_incorporated(compose.taskspec_text, compose.incorporated)
    inputs.library.record_usage(spec.id, retrieved=retrieved_ids, reused=reused_ids)

    # --- C. drive the effector (boundary instrumented) --------------------- #
    scaffold_repo(repo_dir, spec, instance_spec_path=str(_REPO / task.spec_path))
    effector_task = EffectorTask(
        task_id=spec.id,
        repo_dir=repo_dir,
        taskspec_text=compose.taskspec_text,
        spec_dict={"id": spec.id, "title": spec.title, "tier": spec.tier, **_spec_to_dict(spec)},
        budget_cap_usd=cfg.budget_cap_for(spec.tier),
        allowed_tools=list(cfg.effector_allowed_tools),
        sandbox_profile=cfg.sandbox_profile,
        trace_id=trace_id,
    )
    session = drive_coding_effector(effector_task, inputs.effector)

    # held-out integrity: the effector repo must contain no harness/contract code.
    assert_held_out(repo_dir)

    # --- D. boot + health + contract suite + instance DoD ------------------ #
    write_pytest_module(spec, str(_REPO / task.spec_path), artifacts_dir / "test_contract_suite.py")
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = _boot(repo_dir, port, artifacts_dir / "service.log")
    try:
        if _wait_for_health(base_url, proc):
            with httpx.Client(base_url=base_url, timeout=30.0) as client:
                suite = run_suite(spec, client)
        else:
            suite = SuiteResult(
                total=1,
                passed=0,
                results=[("boot:healthz", False, "service did not become healthy in 30s")],
            )
        dod = run_instance_dod(repo_dir)
    finally:
        _teardown(proc)

    first_pass = suite.all_passed and session.retries == 0
    failing = [cid for cid, ok, _ in suite.results if not ok]
    gate = GateOutcome(
        contract_passed=suite.all_passed,
        dod_passed=dod.passed,
        effector_retries=session.retries,
        first_pass=first_pass,
        failing_case_ids=failing,
    )

    # --- E. reflect (ALWAYS runs -> driver-cost parity) -------------------- #
    reflect = inputs.driver.reflect(
        spec=spec,
        feature_tags=task.feature_tags,
        retrieved=retrieved_items,
        incorporated=reused_ids,
        gate=gate,
        library=inputs.library,
    )
    craft_written: str | None = None
    if run_mode == TREATMENT and reflect.action in ("WRITE", "UPDATE") and reflect.craft_item:
        leaks = project_strip_lint(reflect.craft_item.body, spec)
        if leaks:  # defense in depth: never persist craft that leaks identifiers
            reflect.action = "SKIP"
            reflect.rationale += f" [rejected by lint: {leaks}]"
        else:
            inputs.library.write(reflect.craft_item)
            craft_written = reflect.craft_item.id
    # (control: reflection ran for cost parity; its writes are discarded — nothing persists)

    # --- per-craft impact + harmful-craft quarantine (treatment only) ------ #
    if run_mode == TREATMENT:
        baseline.update(first_pass=first_pass, effector_retries=session.retries)
        update_craft_metrics(
            inputs.library, reused_ids, first_pass=first_pass, effector_retries=session.retries
        )
        quarantine_harmful(inputs.library, baseline)

    wall = time.monotonic() - t0
    completed_at = _now()

    # --- cost + record ----------------------------------------------------- #
    model_cost = _driver_cost(
        cfg,
        [
            (compose.model, compose.tokens_in, compose.tokens_out),
            (reflect.model, reflect.tokens_in, reflect.tokens_out),
        ],
    )
    effector_cost = session.cost_usd
    record = build_task_record(
        position=task.position,
        task_id=spec.id,
        tier=spec.tier,
        model_cost_usd=model_cost,
        effector_cost_usd=effector_cost,
        tool_cost_usd=0.0,
        wall_clock_seconds=wall,
        dod_passed=dod.passed,
        contract_tests_passed=suite.passed,
        contract_tests_total=suite.total,
        effector_retries=session.retries,
        first_pass_contract_success=first_pass,
        craft_retrieved=retrieved_ids,
        craft_reused=reused_ids,
        trace_id=trace_id,
    )

    status = "succeeded" if (suite.all_passed and dod.passed) else "failed"
    trace = build_trace(
        trace_id,
        spec.id,
        started_at,
        completed_at,
        status,
        session,
        dod,
        suite,
        record["total_cost_usd"],
        effector_cost,
        model_cost,
    )
    validate_trace(trace)
    (artifacts_dir / "trace.json").write_text(json.dumps(trace, indent=2))

    diagnostic = retrieval_diagnostic(
        gold=inputs.gold,
        instance_id=spec.id,
        feature_tags=task.feature_tags,
        retrieved_ids=retrieved_ids,
        incorporated_ids=compose.incorporated,
        present_ids=present_ids,
    )

    return TaskArtifacts(
        record=record,
        trace=trace,
        taskspec_text=compose.taskspec_text,
        retrieved=retrieved_ids,
        reused=reused_ids,
        incorporated=list(compose.incorporated),
        reflect_action=reflect.action,
        reflect_rationale=reflect.rationale,
        craft_written=craft_written,
        diagnostic=diagnostic,
        suite=suite,
        dod=dod,
        repo_dir=repo_dir,
        artifacts_dir=artifacts_dir,
    )


# --------------------------------------------------------------------------- #
# A run over a sequence of positions
# --------------------------------------------------------------------------- #
def run_sequence(
    positions: list[int],
    *,
    run_mode: str,
    inputs: RunInputs,
    run_id: str,
    taskset_path: str | Path = DEFAULT_TASKSET,
) -> OrchestratorResult:
    if run_mode not in (TREATMENT, CONTROL):
        raise ValueError(f"run_mode must be {TREATMENT!r} or {CONTROL!r}, got {run_mode!r}")
    by_pos = {t.position: t for t in load_taskset(taskset_path)}
    started_at = _now()
    baseline = RunningBaseline()
    tasks: list[TaskArtifacts] = []
    for pos in positions:
        tasks.append(
            run_one_task(
                inputs=inputs, task=by_pos[pos], run_mode=run_mode, run_id=run_id, baseline=baseline
            )
        )
    completed_at = _now()

    records = [a.record for a in tasks]
    diagnostics = [a.diagnostic for a in tasks]
    diag_summary = summarize_diagnostics(diagnostics)

    results_doc = build_results(
        run_id=run_id,
        run_kind="experiment",
        started_at=started_at,
        completed_at=completed_at,
        pins=inputs.config.to_pins(),
        tasks=records,
        aggregate=_aggregate(records, run_mode, diag_summary),
        decision=_pilot_decision(records, run_mode),
        protocol_version=inputs.config.protocol_version,
    )
    validate_results(results_doc)

    return OrchestratorResult(
        run_id=run_id,
        run_mode=run_mode,
        results_doc=results_doc,
        records=records,
        diagnostics=diagnostics,
        diagnostic_summary=diag_summary,
        tasks=tasks,
        library=inputs.library,
        baseline=baseline,
    )


def _aggregate(records: list[dict], run_mode: str, diag_summary: dict) -> dict:
    quality = all(r["contract_passed"] and r["dod_passed"] for r in records)
    reuse = any(r["craft_items_reused"] for r in records)
    security_ok = all(not r.get("security_events") for r in records)
    return {
        "warmup_tasks": 5,
        "cost_slope_after_warmup": 0.0,
        "cost_slope_ci": [0.0, 0.0],
        "min_detectable_slope": 0.0,
        # A single arm over a partial set is never a full pass: the mandatory control
        # delta is a T-1.4 concern (this runs ONE arm).
        "control_run_present": False,
        "treatment_vs_control_delta": 0.0,
        "quality_holds": quality,
        "reuse_is_real": reuse,
        "security_controls_held": security_ok,
        "run_mode": run_mode,
        "retrieval_diagnostic": diag_summary,
        "note": (
            "Pilot/partial single-arm run (G1 gate): n too small for a slope; warm-up/"
            "slope/CI are placeholders. The real decision is the 30-task Run A + the "
            "mandatory control Run B with the pre-registered test (ADR-0017, T-1.4)."
        ),
    }


def _pilot_decision(records: list[dict], run_mode: str) -> dict:
    return {
        "status": "stopped",
        "rationale": (
            f"PILOT/PARTIAL run (run_mode={run_mode}), stopped at the ADR-0020 G1 gate. "
            f"{len(records)} task(s); not a full experimental decision (requires 30 tasks "
            "+ the mandatory control run, ADR-0017/T-1.4). Reviewed for craft quality, "
            "reuse, and retrieval precision before authorizing the full run."
        ),
        "residual_risks": [
            "Single arm, partial task set: no cost slope, no warm-up exclusion, no test.",
            "Control delta (Run A vs Run B) is computed in T-1.4, not here.",
            "Craft quality is judged at the G1 review, not asserted by the harness.",
        ],
    }

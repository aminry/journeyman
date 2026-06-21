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
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from harness.compiler import SuiteResult, run_suite
from harness.craft import CraftItem, CraftLibrary
from harness.craftimpact import RunningBaseline, quarantine_harmful, update_craft_metrics
from harness.driver import Driver, GateOutcome, ReflectResult, verify_incorporated
from harness.errors import TransientInfraError
from harness.effector import Effector, EffectorTask, drive_coding_effector
from harness.gold import GoldMap, RetrievalDiagnostic, retrieval_diagnostic, summarize_diagnostics
from harness.render import write_pytest_module
from harness.results import build_results, build_task_record, validate_results
from harness.retrieval import Retriever
from harness.reflection import canonical_fraction, project_strip_lint
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


def _service_log_excerpt(path: Path, max_chars: int = 1500) -> str:
    """The tail of the booted service's OWN log (uvicorn startup, tracebacks, boot errors)
    for the driver's reflect context — the effector's output, never the contract suite, so
    held-out integrity holds. Truncated to keep the driver call cheap."""
    if not path.exists():
        return ""
    text = path.read_text(errors="ignore").strip()
    return text[-max_chars:] if len(text) > max_chars else text


def assert_craft_canonical(library) -> float:
    """Run-health guard (G1 condition 4): return the fraction of craft ids in the canonical
    taxonomy, and FAIL LOUD if any non-taxonomy id slipped in — a drift would silently blind
    the curated G2 diagnostic, so we crash rather than spend a run with G2 dark."""
    pct, rogue = canonical_fraction(library)
    if rogue:
        raise RuntimeError(
            f"run-health: {len(rogue)} non-taxonomy craft id(s) in the library {rogue} "
            f"({pct:.0%} canonical) — this would blind the curated G2 diagnostic. Failing "
            "loud (G1 condition 4): align the driver to the taxonomy before proceeding."
        )
    return pct


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
    craft_canonical_pct: float
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
        service_log_excerpt=_service_log_excerpt(artifacts_dir / "service.log"),
    )

    # --- E. reflect (ALWAYS runs -> driver-cost parity) -------------------- #
    # A transient/infra error in reflect must NOT lose the task: the gate already ran, so
    # the task's result + cost are valid — record them, just skip reflection this task.
    # (A transient in compose/effector, above, has no valid result and propagates to the
    # orchestrator, which excludes the task.)
    try:
        reflect = inputs.driver.reflect(
            spec=spec,
            feature_tags=task.feature_tags,
            retrieved=retrieved_items,
            incorporated=reused_ids,
            gate=gate,
            library=inputs.library,
        )
    except TransientInfraError as exc:
        reflect = ReflectResult(
            "SKIP",
            None,
            None,
            0,
            0,
            cfg.driver_model or "unknown",
            f"reflection skipped (transient infra error, task result retained): {exc}",
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

    # --- run-health: every craft id must stay canonical (fail loud, G1 condition 4) -- #
    craft_canonical_pct = assert_craft_canonical(inputs.library)

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
        craft_canonical_pct=craft_canonical_pct,
        diagnostic=diagnostic,
        suite=suite,
        dod=dod,
        repo_dir=repo_dir,
        artifacts_dir=artifacts_dir,
    )


# --------------------------------------------------------------------------- #
# A run over a sequence of positions
# --------------------------------------------------------------------------- #
def _append_record(records_path: Path | None, record: dict) -> None:
    """Append one per-task record as a JSON line (fsync) — a durable, tail-able ledger so a
    crash loses at most the in-flight task and ``--resume`` can skip what completed."""
    if records_path is None:
        return
    records_path.parent.mkdir(parents=True, exist_ok=True)
    with records_path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _load_prior_records(records_path: Path | None) -> list[dict]:
    """Read the durable ledger, tolerating a torn final line (a crash mid-write) by skipping
    unparseable lines, and de-duplicating by position (keep the last record for a position) so
    an accidental re-append never double-counts. Order follows first appearance."""
    if records_path is None or not records_path.exists():
        return []
    by_pos: dict[int, dict] = {}
    order: list[int] = []
    for ln in records_path.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue  # torn/partial line from a crash mid-write — skip it, keep the rest
        pos = rec["position"]
        if pos not in by_pos:
            order.append(pos)
        by_pos[pos] = rec
    return [by_pos[p] for p in order]


def _excluded_record(
    task: TaskInfo, *, reason: str, cost_usd: float, kind: str = "transient"
) -> dict:
    """A per-task record for an INFRASTRUCTURE/unexpected failure — marked excluded_from_slope
    so T-1.4 never counts it as a real first-pass/contract failure (ADR-0017: exclude only
    failures unrelated to the agent). ``kind`` is 'transient' (gateway/credential) or 'error'
    (an unexpected exception we caught so one task can't crash a 10h run)."""
    return build_task_record(
        position=task.position,
        task_id=task.id,
        tier=task.tier,
        model_cost_usd=0.0,
        effector_cost_usd=round(cost_usd, 6),
        tool_cost_usd=0.0,
        wall_clock_seconds=0.0,
        dod_passed=False,
        contract_tests_passed=0,
        contract_tests_total=1,
        effector_retries=0,
        first_pass_contract_success=False,
        craft_retrieved=[],
        craft_reused=[],
        trace_id=f"tr_excluded_{task.id}",
        excluded_from_slope=True,
        exclusion_reason=f"infrastructure ({kind}): {reason}",
    )


def run_sequence(
    positions: list[int],
    *,
    run_mode: str,
    inputs: RunInputs,
    run_id: str,
    taskset_path: str | Path = DEFAULT_TASKSET,
    records_path: Path | None = None,
    resume: bool = False,
    global_budget_cap_usd: float | None = None,
    max_consecutive_infra_failures: int = 3,
) -> OrchestratorResult:
    if run_mode not in (TREATMENT, CONTROL):
        raise ValueError(f"run_mode must be {TREATMENT!r} or {CONTROL!r}, got {run_mode!r}")
    # Fresh run must not append to an existing ledger (that would duplicate positions + double
    # count spend on a later resume). Require --resume, or a fresh path/run_id.
    if not resume and records_path is not None and _load_prior_records(records_path):
        raise ValueError(
            f"{records_path} already has records — refusing to append (would duplicate positions). "
            "Pass resume=True to continue this run, or use a fresh path/run_id."
        )
    by_pos = {t.position: t for t in load_taskset(taskset_path)}
    started_at = _now()

    # Resume: skip positions already in the durable ledger; carry their spend + records, and
    # REBUILD the baseline from prior (non-excluded) records so quarantine decisions match an
    # uninterrupted run (craft metrics are persisted on disk; the baseline must be too).
    prior_records = _load_prior_records(records_path) if resume else []
    done_positions = {r["position"] for r in prior_records}
    spent = sum(r["total_cost_usd"] for r in prior_records)
    baseline = RunningBaseline()
    for r in prior_records:
        if not r.get("excluded_from_slope"):
            baseline.update(
                first_pass=r["first_pass_contract_success"], effector_retries=r["effector_retries"]
            )

    tasks: list[TaskArtifacts] = []
    extra_records: list[dict] = []  # excluded records, not tied to a TaskArtifacts
    stop_reason: str | None = None
    consecutive_infra = 0

    # In-flight marker: written before each task, cleared after its record is durable. On
    # resume, a position with a live marker but no record crashed mid-task — its craft may be
    # half-mutated, so we record it EXCLUDED and do NOT re-run it (closing the craft
    # double-mutation window the audit flagged). It can be re-run later by clearing the record.
    inflight_path = records_path.with_suffix(".inflight") if records_path is not None else None
    if resume and inflight_path is not None and inflight_path.exists():
        crashed = inflight_path.read_text().strip()
        if crashed.isdigit() and int(crashed) not in done_positions and int(crashed) in by_pos:
            rec = _excluded_record(
                by_pos[int(crashed)],
                reason="crashed mid-task before its record was durable; not re-run (craft may be "
                "partially mutated)",
                cost_usd=0.0,
                kind="error",
            )
            _append_record(records_path, rec)
            prior_records.append(rec)
            done_positions.add(int(crashed))
            spent += rec["total_cost_usd"]
        inflight_path.unlink()

    def _mark_inflight(pos: int) -> None:
        if inflight_path is None:
            return
        inflight_path.parent.mkdir(parents=True, exist_ok=True)
        inflight_path.write_text(str(pos))

    def _clear_inflight() -> None:
        if inflight_path is not None and inflight_path.exists():
            inflight_path.unlink()

    def _exclude(pos: int, *, reason: str, cost_usd: float, kind: str) -> bool:
        """Record an excluded task; return True if the run should stop (K consecutive)."""
        nonlocal spent, consecutive_infra
        rec = _excluded_record(by_pos[pos], reason=reason, cost_usd=cost_usd, kind=kind)
        _append_record(records_path, rec)
        extra_records.append(rec)
        spent += rec["total_cost_usd"]
        consecutive_infra += 1
        return consecutive_infra >= max_consecutive_infra_failures

    for pos in positions:
        if pos in done_positions:
            continue  # already completed in a prior run (resume) — never re-run / re-spend
        if global_budget_cap_usd is not None and spent >= global_budget_cap_usd:
            stop_reason = (
                f"global budget cap ${global_budget_cap_usd:.2f} reached (spent ${spent:.2f})"
            )
            break
        _mark_inflight(pos)
        try:
            art = run_one_task(
                inputs=inputs, task=by_pos[pos], run_mode=run_mode, run_id=run_id, baseline=baseline
            )
        except TransientInfraError as exc:
            _clear_inflight()
            # Persistent transient (gateway/credential) -> EXCLUDE (infra), not a false failure;
            # stop if it is down for K in a row.
            if _exclude(pos, reason=str(exc), cost_usd=exc.cost_usd, kind="transient"):
                stop_reason = f"{consecutive_infra} consecutive infrastructure failures: {exc}"
                break
            continue
        except Exception as exc:  # noqa: BLE001 - never let ONE task crash a 10h unattended run
            # An unexpected (non-transient) error is caught + excluded so the run survives; it
            # is flagged for T-1.4 and counts toward the consecutive-failure stop (a real bug
            # that recurs will halt the run rather than burn the budget).
            _clear_inflight()
            if _exclude(pos, reason=f"{type(exc).__name__}: {exc}", cost_usd=0.0, kind="error"):
                stop_reason = f"{consecutive_infra} consecutive task errors: {exc}"
                break
            continue
        consecutive_infra = 0
        tasks.append(art)
        _append_record(records_path, art.record)
        _clear_inflight()
        spent += art.record["total_cost_usd"]
        if global_budget_cap_usd is not None and spent >= global_budget_cap_usd:
            stop_reason = (
                f"global budget cap ${global_budget_cap_usd:.2f} reached after task "
                f"{pos} (spent ${spent:.2f})"
            )
            break
    completed_at = _now()

    new_records = [a.record for a in tasks] + extra_records
    records = prior_records + new_records
    diagnostics = [a.diagnostic for a in tasks]
    diag_summary = summarize_diagnostics(diagnostics)
    diag_summary["craft_canonical_pct_min"] = min(
        (a.craft_canonical_pct for a in tasks), default=1.0
    )
    diag_summary["resumed_prior_tasks"] = len(prior_records)
    diag_summary["excluded_infra_tasks"] = sum(1 for r in records if r.get("excluded_from_slope"))
    diag_summary["total_spend_usd"] = round(spent, 4)
    # structured stop signal for an unattended monitor (not just free-text rationale)
    diag_summary["stopped_early"] = stop_reason is not None
    diag_summary["stop_reason"] = stop_reason

    if records:
        results_doc = build_results(
            run_id=run_id,
            run_kind="experiment",
            started_at=started_at,
            completed_at=completed_at,
            pins=inputs.config.to_pins(),
            tasks=records,
            aggregate=_aggregate(records, run_mode, diag_summary),
            decision=_pilot_decision(records, run_mode, stop_reason=stop_reason),
            protocol_version=inputs.config.protocol_version,
        )
        validate_results(results_doc)
    else:
        # Degenerate: nothing ran (e.g. resumed with the budget already exhausted). Don't
        # crash on the schema's tasks>=1 — emit an explicit, unvalidated zero-task stop doc.
        results_doc = {
            "protocol_version": inputs.config.protocol_version,
            "run_id": run_id,
            "run_kind": "experiment",
            "started_at": started_at,
            "completed_at": completed_at,
            "pins": inputs.config.to_pins(),
            "tasks": [],
            "aggregate": _aggregate([], run_mode, diag_summary),
            "decision": _pilot_decision([], run_mode, stop_reason=stop_reason or "no tasks ran"),
        }

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
    # Quality/reuse are computed over SCORED tasks only — excluded (infra/error) records must
    # not drag quality_holds down or be read as real outcomes.
    scored = [r for r in records if not r.get("excluded_from_slope")]
    quality = all(r["contract_passed"] and r["dod_passed"] for r in scored)
    reuse = any(r["craft_items_reused"] for r in scored)
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


def _pilot_decision(records: list[dict], run_mode: str, *, stop_reason: str | None = None) -> dict:
    rationale = (
        f"Single-arm run (run_mode={run_mode}), {len(records)} task(s). This harness emits "
        "DATA ONLY — it never writes a pass/stop experimental decision; the treatment-vs-"
        "control delta + the pre-registered test are computed in T-1.4 (ADR-0017). "
    )
    if stop_reason:
        rationale += f"Run halted early by a runtime guard: {stop_reason}."
    return {
        "status": "stopped",
        "rationale": rationale,
        "residual_risks": [
            "Data-only artifact: no pass/stop decision is made here (that is T-1.4).",
            "Control delta (Run A vs Run B) + the slope test are computed in T-1.4.",
            *([f"Early stop: {stop_reason}"] if stop_reason else []),
        ],
    }

"""The Phase -1 measurement spine: run one instance end-to-end (T-1.1).

Per instance:

1. retrieve craft (keyword/tag) and record the reuse counter;
2. scaffold a fresh repo from project/project-template/;
3. build the effector TaskSpec from the SPEC + retrieved craft (never the tests);
4. drive the coding effector (boundary instrumented: cost, retries, diff);
5. assert held-out integrity (no harness/contract tests leaked into the repo);
6. boot the service via ./run.sh on $PORT, wait for GET /healthz (30s);
7. run the generated contract suite + the instance Definition-of-Done;
8. tear down;
9. assemble a per-task record (faithful total_cost = model + effector + tool),
   validate it against results.schema.json, and write results.json + a trace.

The driver/orchestrator (model calls, reflection, craft-writing) is deliberately
absent (T-1.3): ``model_cost_usd`` is first-class and accounted at 0 here.
"""

from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jsonschema

from harness.compiler import SuiteResult, run_suite
from harness.craft import CraftLibrary
from harness.effector import Effector, EffectorSession, EffectorTask, drive_coding_effector
from harness.render import write_pytest_module
from harness.results import (
    build_results,
    build_task_record,
    spine_aggregate,
    spine_decision,
    validate_results,
)
from harness.runconfig import RunConfig
from harness.scaffolder import scaffold_repo
from harness.specschema import InstanceSpec, load_spec
from harness.taskspec import build_taskspec

_TRACE_SCHEMA = Path(__file__).resolve().parents[3] / "observability" / "trace-schema.json"
_HEALTH_TIMEOUT_S = 30.0
_FORBIDDEN_IN_REPO = ("import harness", "compile_contract_suite", "ContractCase", "run_suite(")


# --------------------------------------------------------------------------- #
# Boot / health / teardown
# --------------------------------------------------------------------------- #
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _boot(repo_dir: Path, port: int, log_path: Path) -> subprocess.Popen:
    env = {
        **_clean_env(),
        "PORT": str(port),
        "SERVICE_DB": str(repo_dir / "service.db"),
    }
    log = log_path.open("w")
    proc = subprocess.Popen(
        ["bash", "run.sh"], cwd=str(repo_dir), env=env, stdout=log, stderr=subprocess.STDOUT
    )
    proc._harness_log = log  # closed in _teardown so the fd doesn't leak across a 30-run loop
    return proc


def _clean_env() -> dict:
    import os

    return dict(os.environ)


def _wait_for_health(
    base_url: str, proc: subprocess.Popen, timeout: float = _HEALTH_TIMEOUT_S
) -> bool:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            if proc.poll() is not None:  # process died -> never healthy
                return False
            with contextlib.suppress(httpx.HTTPError):
                if client.get(f"{base_url}/healthz").status_code == 200:
                    return True
            time.sleep(0.15)
    return False


def _teardown(proc: subprocess.Popen) -> None:
    with contextlib.suppress(Exception):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log = getattr(proc, "_harness_log", None)
    if log is not None:
        with contextlib.suppress(Exception):
            log.close()


# --------------------------------------------------------------------------- #
# Instance Definition-of-Done (minimal wired subset; full typed gate is T0.7)
# --------------------------------------------------------------------------- #
@dataclass
class DodResult:
    passed: bool
    gates: dict[str, bool]
    detail: str = ""


def run_instance_dod(repo_dir: Path) -> DodResult:
    """Run the instance's OWN tests (the wired, in-scope gate for the spine).

    The full typed-gate DoD (lint/build/coverage/security/code-graph for the
    instance) is Phase-0 (T0.7); the spine records ``dod_passed`` from the
    instance's unit tests, which is the load-bearing acceptance signal here.
    """
    if not (repo_dir / "tests").exists():
        return DodResult(False, {"tests": False}, "no tests/ in instance repo")
    proc = subprocess.run(
        ["python", "-m", "pytest", "tests", "-q", "--rootdir", str(repo_dir)],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
    )
    passed = proc.returncode == 0
    return DodResult(passed, {"tests-unit": passed}, proc.stdout[-500:])


def assert_held_out(repo_dir: Path) -> None:
    """Defense in depth: the effector repo must contain no harness/contract code."""
    for path in repo_dir.rglob("*.py"):
        if ".git" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        for marker in _FORBIDDEN_IN_REPO:
            if marker in text:
                raise AssertionError(f"held-out integrity breach: {marker!r} found in {path}")


# --------------------------------------------------------------------------- #
# Trace
# --------------------------------------------------------------------------- #
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_trace(
    trace_id: str,
    task_id: str,
    started: str,
    completed: str,
    status: str,
    session: EffectorSession,
    dod: DodResult,
    suite: SuiteResult,
    total_cost: float,
    effector_cost: float,
    model_cost: float,
) -> dict:
    eff_span = session.to_span()
    eff_span.update(
        {
            "span_id": "sp_effector",
            "started_at": started,
            "completed_at": completed,
            "redaction_state": "redacted",
        }
    )
    dod_span = {
        "span_id": "sp_dod",
        "kind": "dod_gate",
        "actor": "harness:dod",
        "started_at": started,
        "completed_at": completed,
        "redaction_state": "not_needed",
        "decision": "pass" if dod.passed else "fail",
        "details": {"gates": dod.gates, "contract_passed": f"{suite.passed}/{suite.total}"},
    }
    return {
        "trace_id": trace_id,
        "task_id": task_id,
        "started_at": started,
        "completed_at": completed,
        "status": status,
        "spans": [eff_span, dod_span],
        "redaction": {
            "policy_version": 1,
            "scanner_version": "spine-1",
            "result": "passed",
            "findings_count": 0,
        },
        "cost_rollup": {
            "total_cost_usd": total_cost,
            "model_cost_usd": model_cost,
            "effector_cost_usd": effector_cost,
            "tool_cost_usd": 0.0,
        },
    }


def validate_trace(trace: dict) -> None:
    jsonschema.validate(trace, json.loads(_TRACE_SCHEMA.read_text()))


# --------------------------------------------------------------------------- #
# Run result
# --------------------------------------------------------------------------- #
@dataclass
class RunResult:
    record: dict
    results_doc: dict
    suite_result: SuiteResult
    session: EffectorSession
    dod: DodResult
    repo_dir: Path
    artifacts_dir: Path
    results_path: Path
    trace: dict
    retrieved: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)


def run_instance(
    spec_path: str | Path,
    *,
    config: RunConfig,
    effector: Effector,
    workdir: str | Path,
    craft_lib: CraftLibrary,
    run_id: str,
    position: int = 1,
) -> RunResult:
    spec: InstanceSpec = load_spec(spec_path)
    # Absolute paths: run.sh `cd`s into the repo, so any relative path handed to
    # the booted service (e.g. SERVICE_DB) would resolve against the wrong dir.
    workdir = Path(workdir).resolve()
    inst_dir = workdir / run_id / spec.id
    repo_dir = inst_dir / "repo"
    artifacts_dir = inst_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    # The runner owns boundary-artifact persistence: ensure the effector writes its
    # transcript/diff into this run's artifacts dir (SPEC §14, ADR-0005).
    if hasattr(effector, "artifact_dir"):
        effector.artifact_dir = artifacts_dir
    trace_id = f"tr_{run_id}_{spec.id}".replace("-", "_")
    started_at = _now()
    t0 = time.monotonic()

    # 1. retrieve craft + record reuse counter
    retrieved_items = craft_lib.retrieve(tags=["crud", "fastapi", "sqlite", spec.tier, spec.id])
    retrieved_ids = [c.id for c in retrieved_items]
    reused_ids = list(retrieved_ids)  # spine injects all retrieved craft into the TaskSpec
    craft_lib.record_usage(spec.id, retrieved=retrieved_ids, reused=reused_ids)

    # 2. scaffold + 3. build TaskSpec (spec + craft only)
    scaffold_repo(repo_dir, spec, instance_spec_path=str(spec_path))
    taskspec_text = build_taskspec(spec, retrieved_items)

    # 4. drive the effector (boundary instrumented)
    task = EffectorTask(
        task_id=spec.id,
        repo_dir=repo_dir,
        taskspec_text=taskspec_text,
        spec_dict={"id": spec.id, "title": spec.title, "tier": spec.tier, **_spec_to_dict(spec)},
        budget_cap_usd=config.budget_cap_usd,
        allowed_tools=list(config.effector_allowed_tools),
        sandbox_profile=config.sandbox_profile,
        trace_id=trace_id,
    )
    session = drive_coding_effector(task, effector)

    # 5. held-out integrity
    assert_held_out(repo_dir)

    # 6. boot + health, 7. acceptance, 8. teardown
    write_pytest_module(spec, str(spec_path), artifacts_dir / "test_contract_suite.py")
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    proc = _boot(repo_dir, port, artifacts_dir / "service.log")
    try:
        healthy = _wait_for_health(base_url, proc)
        if healthy:
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

    wall = time.monotonic() - t0
    completed_at = _now()

    # 9. assemble + validate record
    effector_cost = session.cost_usd
    model_cost = 0.0  # spine: the driver makes no model calls (kept first-class, ADR-0015)
    tool_cost = 0.0
    first_pass = suite.all_passed and session.retries == 0
    record = build_task_record(
        position=position,
        task_id=spec.id,
        tier=spec.tier,
        model_cost_usd=model_cost,
        effector_cost_usd=effector_cost,
        tool_cost_usd=tool_cost,
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

    results_doc = build_results(
        run_id=run_id,
        run_kind="harness_selftest",  # the spine is a self-test, never an experiment decision
        started_at=started_at,
        completed_at=completed_at,
        pins=config.to_pins(),
        tasks=[record],
        aggregate=spine_aggregate([record]),
        decision=spine_decision([record]),
        protocol_version=config.protocol_version,
    )
    validate_results(results_doc)
    results_path = artifacts_dir / "results.json"
    results_path.write_text(json.dumps(results_doc, indent=2))

    return RunResult(
        record=record,
        results_doc=results_doc,
        suite_result=suite,
        session=session,
        dod=dod,
        repo_dir=repo_dir,
        artifacts_dir=artifacts_dir,
        results_path=results_path,
        trace=trace,
        retrieved=retrieved_ids,
        reused=reused_ids,
    )


def _spec_to_dict(spec: InstanceSpec) -> dict:
    """Re-serialise the spec for the effector task (fields/endpoints/rules)."""
    return {
        "resource": {
            "name": spec.resource.name,
            "path": spec.resource.path,
            "fields": [
                {
                    k: v
                    for k, v in {
                        "name": f.name,
                        "type": f.type,
                        "required": f.required,
                        "readonly": f.readonly,
                        "generated": f.generated,
                        "unique": f.unique,
                        "default": f.default,
                        "min": f.min,
                        "max": f.max,
                        "min_len": f.min_len,
                        "max_len": f.max_len,
                        "pattern": f.pattern,
                        "values": f.values,
                        "ref": f.ref,
                    }.items()
                    if v is not None
                }
                for f in spec.resource.fields
            ],
        },
        "endpoints": {
            e.kind: {
                "method": e.method,
                "path": e.path,
                "success": e.success,
                **({"missing": e.missing} if e.missing is not None else {}),
                **({"partial": e.partial} if e.partial else {}),
                **(
                    {
                        "pagination": {
                            "limit_param": e.pagination.limit_param,
                            "offset_param": e.pagination.offset_param,
                            "default_limit": e.pagination.default_limit,
                            "max_limit": e.pagination.max_limit,
                        }
                    }
                    if e.pagination
                    else {}
                ),
                **({"filters": e.filters} if e.filters else {}),
                **({"sort": e.sort} if e.sort else {}),
            }
            for e in spec.endpoints.present()
        },
        "rules": {
            "on_validation_error": spec.rules.on_validation_error,
            "on_unique_conflict": spec.rules.on_unique_conflict,
            "timestamps_immutable": spec.rules.timestamps_immutable,
        },
        "business_rules": spec.business_rules,
    }

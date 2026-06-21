"""Deterministic proofs of the 4 full-run operational fixes (fakes only, zero spend).

The 30x2 run is GATED on these passing:
  #1 resumability   — kill->resume skips completed positions, NO craft re-mutation, no re-spend
  #2 global budget  — cumulative spend over the cap aborts the run with a recorded stop
  #3 transient/502  — a transient/infra error -> excluded_from_slope, NOT a first-pass failure;
                       K consecutive infra failures stop the run; the run never crashes
  #4 A/B + parity   — covered in test_experiment_runner.py (B can't read A's craft dir; the
                       prompt/decoding parity assert FIRES on mismatch)
"""

from __future__ import annotations

from pathlib import Path

from harness.craft import CraftLibrary
from harness.driver import FakeDriver
from harness.effector import FakeEffector
from harness.embedding import DeterministicHashEmbedder
from harness.errors import TransientEffectorError
from harness.gold import GoldMap
from harness.orchestrator import RunInputs, run_sequence
from harness.retrieval import VectorCraftRetriever
from harness.runconfig import orchestrator_run_config

REPO = Path(__file__).resolve().parents[2]
GOLD = GoldMap.load(REPO / "experiments" / "phase_minus_1" / "retrieval_gold.yaml")
VA = {"models": ["claude-sonnet-4-6"], "effector_version": "fake@test", "embedding_model": "det"}


def _inputs(workdir: Path, craft_dir: Path, effector=None) -> RunInputs:
    cfg = orchestrator_run_config()
    lib = CraftLibrary(craft_dir)
    return RunInputs(
        config=cfg,
        driver=FakeDriver(validated_against=VA, last_validated="2026-06-20T00:00:00Z"),
        effector=effector or FakeEffector(cfg, artifact_dir=workdir / "eff"),
        retriever=VectorCraftRetriever(lib, DeterministicHashEmbedder(dim=512), k=cfg.retrieval_k),
        library=lib,
        gold=GOLD,
        workdir=workdir,
    )


class _RaisingEffector:
    """Delegates to a real FakeEffector except for target task_ids, where it raises a
    transient (simulating a gateway 502/token-refresh that survives the effector's retries)."""

    def __init__(self, fake: FakeEffector, raise_for: set[str]):
        self._fake = fake
        self._raise_for = raise_for
        self.artifact_dir = fake.artifact_dir

    def run(self, task):
        if task.task_id in self._raise_for:
            raise TransientEffectorError(
                "502 token refresh failed; re-run /login", stage="effector"
            )
        self._fake.artifact_dir = self.artifact_dir
        return self._fake.run(task)


# --- #1 resumability ------------------------------------------------------- #
def test_kill_then_resume_skips_completed_no_remutation_no_respend(tmp_path: Path) -> None:
    craft = tmp_path / "craft"
    records = tmp_path / "runA.records.jsonl"

    # First run: positions 1-2 (simulating a crash before position 3).
    r1 = _inputs(tmp_path / "wd1", craft)
    run_sequence([1, 2], run_mode="treatment", inputs=r1, run_id="runA", records_path=records)
    assert records.read_text().count("\n") == 2  # two durable records
    lib_after_2 = CraftLibrary(craft)
    snapshot = {cid: lib_after_2.read(cid).version for cid in lib_after_2.ids()}
    craft_bodies = {cid: lib_after_2.read(cid).body for cid in lib_after_2.ids()}

    # Resume over 1-3: positions 1,2 must be SKIPPED (no re-run), only 3 executes.
    r2 = _inputs(tmp_path / "wd2", craft)  # same craft dir (persisted), new workdir
    res = run_sequence(
        [1, 2, 3], run_mode="treatment", inputs=r2, run_id="runA", records_path=records, resume=True
    )
    # exactly one NEW task ran this invocation (position 3); 1 & 2 were skipped
    assert len(res.tasks) == 1 and res.tasks[0].record["position"] == 3
    # the durable ledger now has all 3, and the final results doc covers all 3
    assert records.read_text().count("\n") == 3
    assert {r["position"] for r in res.records} == {1, 2, 3}
    # NO craft re-mutation: the items written by tasks 1-2 are byte-identical (not bumped/rewritten)
    lib_final = CraftLibrary(craft)
    for cid, ver in snapshot.items():
        assert lib_final.read(cid).version == ver
        assert lib_final.read(cid).body == craft_bodies[cid]


# --- #2 global budget cap -------------------------------------------------- #
def test_global_budget_cap_aborts_run_with_recorded_stop(tmp_path: Path) -> None:
    inp = _inputs(tmp_path / "wd", tmp_path / "craft")
    # FakeEffector costs ~$0.5/task; a $0.40 cap trips after the first task.
    res = run_sequence(
        [1, 2, 3],
        run_mode="treatment",
        inputs=inp,
        run_id="capA",
        records_path=tmp_path / "capA.records.jsonl",
        global_budget_cap_usd=0.40,
    )
    assert len(res.records) == 1  # stopped before positions 2 and 3
    assert "budget cap" in res.results_doc["decision"]["rationale"].lower()
    assert res.diagnostic_summary["total_spend_usd"] >= 0.40


# --- #3 transient/502 -> excluded, not a false failure --------------------- #
def test_transient_error_excludes_task_not_first_pass_failure(tmp_path: Path) -> None:
    fake = FakeEffector(orchestrator_run_config(), artifact_dir=tmp_path / "eff")
    eff = _RaisingEffector(fake, raise_for={"books"})  # position 2
    inp = _inputs(tmp_path / "wd", tmp_path / "craft", effector=eff)
    res = run_sequence(
        [1, 2, 3],
        run_mode="treatment",
        inputs=inp,
        run_id="trA",
        records_path=tmp_path / "trA.records.jsonl",
    )
    by_id = {r["task_id"]: r for r in res.records}
    assert set(by_id) == {"notes", "books", "orders"}  # run did NOT crash; all 3 recorded
    books = by_id["books"]
    assert books["excluded_from_slope"] is True
    assert "infrastructure" in books["exclusion_reason"].lower()
    # the real tasks were NOT excluded and ran normally
    assert by_id["notes"].get("excluded_from_slope") is None
    assert by_id["orders"].get("excluded_from_slope") is None


def test_consecutive_infra_failures_stop_the_run(tmp_path: Path) -> None:
    fake = FakeEffector(orchestrator_run_config(), artifact_dir=tmp_path / "eff")
    eff = _RaisingEffector(fake, raise_for={"notes", "books", "orders", "bookmarks"})
    inp = _inputs(tmp_path / "wd", tmp_path / "craft", effector=eff)
    res = run_sequence(
        [1, 2, 3, 4],
        run_mode="treatment",
        inputs=inp,
        run_id="infraA",
        records_path=tmp_path / "infraA.records.jsonl",
        max_consecutive_infra_failures=3,
    )
    assert len(res.records) == 3  # stopped after 3 consecutive infra failures (4th not attempted)
    assert all(r["excluded_from_slope"] for r in res.records)
    assert "consecutive infrastructure failures" in res.results_doc["decision"]["rationale"].lower()

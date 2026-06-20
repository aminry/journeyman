"""Unit tests for per-craft impact tracking + harmful-craft quarantine (ADR-0020 §4 G3).

The mandatory control run (Run B) catches *absent* craft (craft adds nothing). It does
NOT catch *harmful* craft — a bad reflection whose reuse makes the effector worse. So we
track, per reused craft item, the outcomes of tasks where it was reused (uses,
mean_effector_retries, first_pass_gate_rate) against a running baseline, and quarantine
an item whose reuse correlates with worse-than-baseline outcomes.
"""

from __future__ import annotations

from pathlib import Path

from harness.craft import CraftItem, CraftLibrary
from harness.craftimpact import RunningBaseline, quarantine_harmful, update_craft_metrics

VA = {"models": ["claude-sonnet-4-6"], "effector_version": "claude-code-cli@test"}


def _item(craft_id: str) -> CraftItem:
    return CraftItem(
        id=craft_id,
        kind="orchestration",
        summary="x",
        when_to_use="y",
        body="generic guidance",
        tags=["crud"],
        tests=["unit"],
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
    )


def test_update_metrics_increments_uses_and_running_means(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(_item("c1"))
    update_craft_metrics(lib, ["c1"], first_pass=True, effector_retries=0)
    update_craft_metrics(lib, ["c1"], first_pass=False, effector_retries=2)
    m = lib.read("c1").metrics
    assert m["uses"] == 2
    assert m["mean_effector_retries"] == 1.0  # mean of 0 and 2
    assert m["first_pass_gate_rate"] == 0.5  # 1 of 2 first-pass


def test_update_metrics_only_touches_reused_items(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(_item("c1"))
    lib.write(_item("c2"))
    update_craft_metrics(lib, ["c1"], first_pass=True, effector_retries=0)
    assert lib.read("c1").metrics.get("uses") == 1
    assert lib.read("c2").metrics.get("uses", 0) == 0


def test_update_metrics_preserves_body_and_schema(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(_item("c1"))
    update_craft_metrics(lib, ["c1"], first_pass=True, effector_retries=0)
    assert lib.read("c1").body == "generic guidance"  # write round-trips body + manifest


def test_running_baseline_tracks_overall_outcomes() -> None:
    b = RunningBaseline()
    b.update(first_pass=True, effector_retries=0)
    b.update(first_pass=False, effector_retries=4)
    assert b.n == 2
    assert b.mean_retries == 2.0
    assert b.first_pass_rate == 0.5


def test_quarantine_flags_worse_than_baseline_high_use_item(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(_item("harmful"))
    lib.write(_item("helpful"))
    # harmful: reused 3x, always retried, never first-pass (worse than baseline)
    for _ in range(3):
        update_craft_metrics(lib, ["harmful"], first_pass=False, effector_retries=3)
    # helpful: reused 3x, clean first-pass (better than baseline)
    for _ in range(3):
        update_craft_metrics(lib, ["helpful"], first_pass=True, effector_retries=0)
    baseline = RunningBaseline(mean_retries=1.0, first_pass_rate=0.7, n=10)
    quarantined = quarantine_harmful(lib, baseline, min_uses=3)
    assert quarantined == ["harmful"]
    assert lib.read("harmful").status == "quarantined"
    assert lib.read("helpful").status == "active"


def test_quarantine_ignores_low_use_items(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    lib.write(_item("new-and-bad"))
    update_craft_metrics(lib, ["new-and-bad"], first_pass=False, effector_retries=5)
    baseline = RunningBaseline(mean_retries=0.5, first_pass_rate=0.9, n=10)
    # only 1 use < min_uses=3 -> not enough evidence to quarantine
    assert quarantine_harmful(lib, baseline, min_uses=3) == []
    assert lib.read("new-and-bad").status == "active"

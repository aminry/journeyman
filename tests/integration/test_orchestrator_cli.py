"""Smoke test for the orchestrator CLI (fake path, zero spend).

The real pilot path (``--driver anthropic --effector claude``) is held for the explicit
go-ahead and is never exercised in CI; here we prove the wiring + artifact writing with
the deterministic fakes.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.orchestrator_cli import main, parse_positions


def test_parse_positions_range_and_list() -> None:
    assert parse_positions("1-3") == [1, 2, 3]
    assert parse_positions("1,3,5") == [1, 3, 5]
    assert parse_positions("2") == [2]
    assert parse_positions("1-3,7") == [1, 2, 3, 7]


def test_cli_fake_run_writes_experiment_results(tmp_path: Path) -> None:
    out = tmp_path / "out"
    rc = main(
        [
            "--positions",
            "1",
            "--mode",
            "treatment",
            "--driver",
            "fake",
            "--effector",
            "fake",
            "--retriever",
            "deterministic",
            "--run-id",
            "cli_smoke",
            "--workdir",
            str(tmp_path / "wd"),
            "--craft-dir",
            str(tmp_path / "craft"),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    results = json.loads((out / "cli_smoke.results.json").read_text())
    assert results["run_kind"] == "experiment"
    assert len(results["tasks"]) == 1
    assert results["tasks"][0]["task_id"] == "notes"
    # a human-readable summary is emitted alongside
    assert (out / "cli_smoke.summary.md").exists()

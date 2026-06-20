"""Unit tests for the coding-effector boundary (SPEC §11A.2, ADR-0005).

The fake effector is exercised fully (it writes a working service into a repo and
emits a complete effector_session). The real Claude Code CLI adapter is NOT
invoked here (no spend) — only its pure pieces (command rendering, JSON parsing,
secret redaction) are tested.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from harness.effector import (
    ClaudeCodeEffector,
    EffectorSession,
    EffectorTask,
    FakeEffector,
    capture_git_diff,
    drive_coding_effector,
    parse_cli_result,
    redact_secrets,
)
from harness.runconfig import default_run_config

REPO = Path(__file__).resolve().parents[2]
BOOKS = REPO / "experiments" / "phase_minus_1" / "instances" / "example_books.spec.yaml"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("scaffold\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "scaffold")
    return repo


def _task(repo: Path) -> EffectorTask:
    return EffectorTask(
        task_id="books",
        repo_dir=repo,
        taskspec_text="Build the books service per the spec.",
        spec_dict=yaml.safe_load(BOOKS.read_text()),
        budget_cap_usd=10.0,
        allowed_tools=["Read", "Write", "Edit", "Bash"],
        sandbox_profile="coding-effector-default",
        trace_id="tr_test",
    )


def test_fake_effector_writes_runnable_service(git_repo: Path) -> None:
    cfg = default_run_config()
    session = FakeEffector(cfg).run(_task(git_repo))
    assert (git_repo / "app.py").exists()
    assert (git_repo / "run.sh").exists()
    assert (git_repo / "spec.json").exists()
    # the copied service body must be standalone (no harness import) — held-out integrity
    assert "import harness" not in (git_repo / "app.py").read_text()
    assert session.success is True
    assert session.files_changed  # non-empty


def test_fake_effector_reports_nonzero_cost(git_repo: Path) -> None:
    cfg = default_run_config()
    session = FakeEffector(cfg).run(_task(git_repo))
    assert session.cost_usd > 0
    assert session.tokens_in > 0 and session.tokens_out > 0
    assert session.model == cfg.effector_model


def test_drive_coding_effector_dispatches(git_repo: Path) -> None:
    cfg = default_run_config()
    session = drive_coding_effector(_task(git_repo), FakeEffector(cfg))
    assert isinstance(session, EffectorSession)


def test_effector_session_to_span_shape(git_repo: Path, tmp_path: Path) -> None:
    cfg = default_run_config()
    session = FakeEffector(cfg, artifact_dir=tmp_path / "art").run(_task(git_repo))
    span = session.to_span()
    assert span["kind"] == "effector_session"
    assert span["cost_usd"] == session.cost_usd
    assert span["retry_count"] == session.retries
    # refs are present once persisted (the runner always persists to the run dir)
    assert "diff_ref" in span and "transcript_ref" in span


def test_to_span_omits_unpersisted_refs(git_repo: Path) -> None:
    cfg = default_run_config()
    session = FakeEffector(cfg).run(_task(git_repo))  # no artifact_dir
    span = session.to_span()
    assert "diff_ref" not in span and "transcript_ref" not in span


def test_capture_git_diff_sees_changes(git_repo: Path) -> None:
    (git_repo / "new_file.py").write_text("x = 1\n")
    diff, files = capture_git_diff(git_repo)
    assert "new_file.py" in diff
    assert "new_file.py" in files


def test_parse_cli_result_extracts_cost_and_tokens() -> None:
    cfg = default_run_config()
    sample = {
        "type": "result",
        "is_error": False,
        "total_cost_usd": 0.4213,
        "num_turns": 7,
        "usage": {"input_tokens": 120000, "output_tokens": 9000},
        "result": "done",
        "session_id": "sess_abc",
    }
    parsed = parse_cli_result(sample, cfg)
    assert parsed.cost_usd == 0.4213
    assert parsed.tokens_in == 120000
    assert parsed.tokens_out == 9000
    assert parsed.success is True


def test_parse_cli_result_without_cost_falls_back_to_pricing() -> None:
    cfg = default_run_config()
    sample = {
        "is_error": False,
        "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    }
    parsed = parse_cli_result(sample, cfg)
    # no total_cost_usd -> compute from pinned prices (Opus 4.8 = $5 + $25)
    assert parsed.cost_usd == 30.0


def test_redact_secrets() -> None:
    text = "key=sk-ant-abc123 and token THE_SECRET here"
    out = redact_secrets(text, secrets=["THE_SECRET"])
    assert "THE_SECRET" not in out
    assert "sk-ant-abc123" not in out
    assert "REDACTED" in out


def test_claude_code_effector_command_is_built_not_run() -> None:
    cfg = default_run_config()
    eff = ClaudeCodeEffector(cfg)
    cmd = eff.build_command("PROMPT TEXT")
    assert cmd[0] == "claude" and "PROMPT TEXT" in cmd and "--output-format" in cmd

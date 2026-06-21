"""Coding-effector boundary: stable interface + fake + Claude Code CLI adapter.

SPEC §11A.2 / ADR-0005: the effector runs its own loop you don't fully see, so the
*boundary* is instrumented — token/dollar cost, transcript, internal retries, and
the git diff — and attached to the trace as an ``effector_session`` span. The
effector's "done" is untrusted; only the gate decides acceptance.

The capability is ``drive_coding_effector(task) -> EffectorSession`` behind a
stable :class:`Effector` interface, so the harness is effector-agnostic:

* :class:`FakeEffector` — deterministic, zero-spend; used by every test and by CI.
  It writes a correct, standalone service into the scaffolded repo (the reference
  service copied verbatim, so the repo never imports ``harness`` — held-out
  integrity) and reports a synthetic but non-zero cost.
* :class:`ClaudeCodeEffector` — drives the real ``claude`` CLI in headless mode
  for the single explicit real run. Never invoked by tests/CI.

Secret hygiene: transcripts and diffs are secret-scanned and redacted before they
are persisted (coding-effector-contract.md "redaction scan before persistence").
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from harness.errors import TransientEffectorError, is_transient_message
from harness.runconfig import RunConfig

_REFERENCE_SERVICE = Path(__file__).resolve().parent / "reference" / "service.py"
_SK_ANT_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")


# --------------------------------------------------------------------------- #
# Boundary records
# --------------------------------------------------------------------------- #
@dataclass
class EffectorTask:
    task_id: str
    repo_dir: Path
    taskspec_text: str
    spec_dict: dict
    budget_cap_usd: float
    allowed_tools: list[str]
    sandbox_profile: str
    trace_id: str


@dataclass
class EffectorSession:
    """The instrumented effector boundary (an ``effector_session`` span)."""

    model: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    retries: int
    success: bool
    files_changed: list[str] = field(default_factory=list)
    commands_run: list[str] = field(default_factory=list)
    num_turns: int = 0
    diff_ref: str | None = None
    transcript_ref: str | None = None
    sandbox_profile: str = "coding-effector-default"
    raw: dict = field(default_factory=dict)

    def to_span(self) -> dict[str, Any]:
        """A trace-schema ``effector_session`` span (observability/trace-schema.json)."""
        span = {
            "kind": "effector_session",
            "actor": "tool:coding_effector",
            "model": self.model,
            "tool_name": "drive_coding_effector",
            "cost_usd": self.cost_usd,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "retry_count": self.retries,
            "sandbox_profile": self.sandbox_profile,
            "cost_category": "task_time",
            "details": {
                "files_changed": self.files_changed,
                "num_turns": self.num_turns,
                "success_claimed": self.success,
            },
        }
        # Optional refs: include only when persisted (schema types them as strings).
        if self.diff_ref is not None:
            span["diff_ref"] = self.diff_ref
        if self.transcript_ref is not None:
            span["transcript_ref"] = self.transcript_ref
        return span


@dataclass
class ParsedResult:
    cost_usd: float
    tokens_in: int
    tokens_out: int
    success: bool
    num_turns: int


# --------------------------------------------------------------------------- #
# Helpers (pure / testable without spend)
# --------------------------------------------------------------------------- #
def capture_git_diff(repo_dir: Path) -> tuple[str, list[str]]:
    """Stage everything and return (unified diff, changed file list) vs HEAD."""
    subprocess.run(["git", "-C", str(repo_dir), "add", "-A"], check=True, capture_output=True)
    diff = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--cached"], capture_output=True, text=True, check=True
    ).stdout
    names = subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = [f for f in names.splitlines() if f.strip()]
    return diff, files


def redact_secrets(text: str, secrets: list[str] | None = None) -> str:
    """Remove known secret values and sk-ant tokens before persistence."""
    out = text
    for s in secrets or []:
        if s:
            out = out.replace(s, "***REDACTED***")
    out = _SK_ANT_RE.sub("***REDACTED***", out)
    return out


def parse_cli_result(obj: dict, config: RunConfig) -> ParsedResult:
    """Parse a Claude Code ``--output-format json`` result object.

    Prefers the CLI's own ``total_cost_usd``; if absent, computes cost from the
    pinned token prices so the boundary cost is never silently zero.
    """
    usage = obj.get("usage") or {}
    tin = (
        int(usage.get("input_tokens", 0))
        + int(usage.get("cache_read_input_tokens", 0))
        + int(usage.get("cache_creation_input_tokens", 0))
    )
    tout = int(usage.get("output_tokens", 0))
    cost = obj.get("total_cost_usd")
    if cost is None:
        cost = config.estimate_cost(config.effector_model, tin, tout)
    return ParsedResult(
        cost_usd=float(cost),
        tokens_in=tin,
        tokens_out=tout,
        success=not bool(obj.get("is_error", False)),
        num_turns=int(obj.get("num_turns", 0)),
    )


def _write_artifacts(
    artifact_dir: Path, task_id: str, transcript: str, diff: str, secrets: list[str]
) -> tuple[str, str]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    t_path = artifact_dir / f"{task_id}.transcript.txt"
    d_path = artifact_dir / f"{task_id}.diff.patch"
    t_path.write_text(redact_secrets(transcript, secrets))
    d_path.write_text(redact_secrets(diff, secrets))
    return str(t_path), str(d_path)


# --------------------------------------------------------------------------- #
# Interface
# --------------------------------------------------------------------------- #
class Effector(Protocol):
    def run(self, task: EffectorTask) -> EffectorSession: ...


def drive_coding_effector(task: EffectorTask, effector: Effector) -> EffectorSession:
    """The stable capability: spec-in, verified-artifact-candidate-out (untrusted)."""
    return effector.run(task)


# --------------------------------------------------------------------------- #
# Fake effector (deterministic, zero spend)
# --------------------------------------------------------------------------- #
_RUN_SH = """#!/usr/bin/env bash
# Boot the service on $PORT; GET /healthz returns 200 when ready (domain.md §1).
set -euo pipefail
cd "$(dirname "$0")"
exec python app.py
"""

_SMOKE_TEST = '''"""Smoke test for the generated service (instance-owned DoD)."""
import json
from pathlib import Path

from app import build_app


def test_app_builds():
    spec = json.loads((Path(__file__).resolve().parent.parent / "spec.json").read_text())
    app = build_app(spec)
    assert app is not None
'''


class FakeEffector:
    """Writes a correct standalone service into the repo; reports synthetic cost."""

    def __init__(
        self,
        config: RunConfig,
        *,
        synthetic_tokens: tuple[int, int] = (60_000, 9_000),
        artifact_dir: Path | None = None,
    ):
        self.config = config
        self.synthetic_tokens = synthetic_tokens
        self.artifact_dir = artifact_dir

    def run(self, task: EffectorTask) -> EffectorSession:
        repo = Path(task.repo_dir)
        # 1. Implement the spec: copy the reference service verbatim (standalone).
        (repo / "app.py").write_text(_REFERENCE_SERVICE.read_text())
        (repo / "spec.json").write_text(json.dumps(task.spec_dict, indent=2))
        run_sh = repo / "run.sh"
        run_sh.write_text(_RUN_SH)
        run_sh.chmod(0o755)
        (repo / "requirements.txt").write_text("fastapi\nuvicorn\n")
        tests_dir = repo / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_smoke.py").write_text(_SMOKE_TEST)

        # 2. Instrument the boundary.
        diff, files = capture_git_diff(repo)
        tin, tout = self.synthetic_tokens
        cost = self.config.estimate_cost(self.config.effector_model, tin, tout)
        transcript = (
            f"[fake effector] implemented {task.task_id} per spec; {len(files)} files changed."
        )
        diff_ref = transcript_ref = None
        if self.artifact_dir is not None:
            transcript_ref, diff_ref = _write_artifacts(
                self.artifact_dir, task.task_id, transcript, diff, secrets=[]
            )
        return EffectorSession(
            model=self.config.effector_model,
            cost_usd=cost,
            tokens_in=tin,
            tokens_out=tout,
            retries=0,
            success=True,
            files_changed=files,
            commands_run=["<fake: wrote app.py, run.sh, spec.json, tests/>"],
            num_turns=1,
            diff_ref=diff_ref,
            transcript_ref=transcript_ref,
            sandbox_profile=task.sandbox_profile,
            raw={"fake": True},
        )


# --------------------------------------------------------------------------- #
# Real effector: Claude Code CLI (headless). Never invoked by tests/CI.
# --------------------------------------------------------------------------- #
def is_transient_cli_result(obj: dict, returncode: int, stderr: str) -> bool:
    """True if a claude-CLI result looks like a transient/infra failure (gateway 429/529/
    502 token-refresh, timeout, connection) rather than a real build attempt — so it can be
    retried, and ultimately EXCLUDED, not recorded as a genuine first-pass failure."""
    errored = bool(obj.get("is_error")) or returncode != 0
    text = f"{obj.get('result', '')} {obj.get('stderr', '')} {stderr or ''}"
    return errored and is_transient_message(text)


class ClaudeCodeEffector:
    """Drives the real ``claude`` CLI in headless mode. Retries transient API/infra errors
    (gateway 429/529/502 token-refresh, timeouts) with backoff — mirroring the driver — so a
    long unattended run survives blips; a persistent transient raises TransientEffectorError
    so the orchestrator EXCLUDES the task instead of recording a false failure. The CLI
    invocation is injectable (``invoker``) so the retry/exclusion logic is testable with zero
    spend; the real path uses subprocess."""

    def __init__(
        self,
        config: RunConfig,
        *,
        artifact_dir: Path | None = None,
        timeout_s: int = 3600,
        max_retries: int = 4,
        backoff_base: float = 2.0,
        sleep: Any = None,
        invoker: Any = None,
    ):
        self.config = config
        self.artifact_dir = artifact_dir
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep if sleep is not None else time.sleep
        self._invoker = invoker

    def build_command(self, prompt: str) -> list[str]:
        return self.config.render_effector_command(prompt)

    def _invoke(self, cmd: list[str], cwd: str, env: dict) -> tuple[dict, int, str]:
        """Run the CLI once -> (parsed result obj, returncode, stderr). Injectable for tests."""
        if self._invoker is not None:
            return self._invoker(cmd, cwd, env)
        proc = subprocess.run(  # pragma: no cover - real spend path
            cmd, cwd=cwd, capture_output=True, text=True, timeout=self.timeout_s, env=env
        )
        try:
            obj = json.loads(proc.stdout)
        except json.JSONDecodeError:
            obj = {"is_error": True, "result": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
        return obj, proc.returncode, proc.stderr

    def run(self, task: EffectorTask) -> EffectorSession:
        cmd = self.build_command(task.taskspec_text)
        env = dict(os.environ)  # ANTHROPIC_API_KEY passes through; never logged/committed
        obj: dict = {}
        returncode = 0
        for attempt in range(self.max_retries + 1):
            try:
                obj, returncode, stderr = self._invoke(cmd, str(task.repo_dir), env)
            except subprocess.TimeoutExpired as exc:
                if attempt < self.max_retries:
                    self._sleep(self.backoff_base**attempt)
                    continue
                raise TransientEffectorError(
                    f"effector timed out after {self.max_retries} retries", stage="effector"
                ) from exc
            if is_transient_cli_result(obj, returncode, stderr):
                if attempt < self.max_retries:
                    self._sleep(self.backoff_base**attempt)
                    continue
                raise TransientEffectorError(
                    f"effector hit a transient API/infra error after {self.max_retries} retries: "
                    f"{str(obj.get('result') or obj.get('stderr') or stderr)[:160]}",
                    stage="effector",
                )
            break  # a non-transient result (real success or a real build failure) -> evaluate it
        parsed = parse_cli_result(obj, self.config)
        diff, files = capture_git_diff(Path(task.repo_dir))
        secrets = [v for k, v in os.environ.items() if "KEY" in k or "TOKEN" in k]
        diff_ref = transcript_ref = None
        if self.artifact_dir is not None:
            transcript_ref, diff_ref = _write_artifacts(
                self.artifact_dir, task.task_id, json.dumps(obj, indent=2), diff, secrets
            )
        return EffectorSession(
            model=self.config.effector_model,
            cost_usd=parsed.cost_usd,
            tokens_in=parsed.tokens_in,
            tokens_out=parsed.tokens_out,
            retries=0,
            success=parsed.success and returncode == 0,
            files_changed=files,
            commands_run=[" ".join(cmd[:6]) + " ..."],
            num_turns=parsed.num_turns,
            diff_ref=diff_ref,
            transcript_ref=transcript_ref,
            sandbox_profile=task.sandbox_profile,
            raw={k: obj.get(k) for k in ("session_id", "num_turns", "is_error")},
        )

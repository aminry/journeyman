"""Transient/infra-error handling at the effector + driver boundaries (Fix #3).

A long unattended run WILL hit gateway 429/529/502-token-refresh/timeout blips. These must
RETRY and, if persistent, raise TransientInfraError so the orchestrator EXCLUDES the task
(infra) — never record a false first-pass/contract failure (which would corrupt the signal).
Proven deterministically with zero spend (injected CLI invoker / fake client).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.driver import AnthropicDriver, GateOutcome
from harness.effector import ClaudeCodeEffector, EffectorTask, is_transient_cli_result
from harness.errors import TransientDriverError, TransientEffectorError, TransientInfraError
from harness.runconfig import orchestrator_run_config
from harness.specschema import load_spec

REPO = Path(__file__).resolve().parents[2]
ORDERS = REPO / "experiments" / "phase_minus_1" / "instances" / "h01_orders.spec.yaml"
VA = {"models": ["claude-sonnet-4-6"], "effector_version": "x"}


def _task(repo: Path) -> EffectorTask:
    return EffectorTask(
        task_id="t",
        repo_dir=repo,
        taskspec_text="build it",
        spec_dict={},
        budget_cap_usd=5.0,
        allowed_tools=["Read"],
        sandbox_profile="x",
        trace_id="tr_t",
    )


# --- classifier ------------------------------------------------------------ #
def test_is_transient_cli_result_flags_token_refresh_502() -> None:
    obj = {"is_error": True, "result": "Error code: 502 - token refresh failed; re-run /login"}
    assert is_transient_cli_result(obj, 1, "") is True


def test_is_transient_cli_result_ignores_a_real_build_result() -> None:
    obj = {"is_error": False, "result": "built the service, tests pass"}
    assert is_transient_cli_result(obj, 0, "") is False


def test_is_transient_cli_result_does_not_misclassify_a_real_build_failure() -> None:
    """False-positive guard (review finding): a genuine build failure that merely MENTIONS
    'timeout'/'connection' must NOT be excluded as transient — it's a real failure."""
    obj = {"is_error": True, "result": "test failed: requests.get timeout on the wrong port"}
    assert is_transient_cli_result(obj, 1, "") is False  # bare 'timeout' is not a transient marker
    obj2 = {"is_error": True, "result": "ConnectionRefused to the app's own db"}
    assert is_transient_cli_result(obj2, 1, "") is False


def test_is_transient_cli_result_flags_gateway_5xx_and_credential() -> None:
    for txt in ("503 service unavailable", "500 internal", "unauthorized", "invalid_api_key"):
        assert is_transient_cli_result({"is_error": True, "result": txt}, 1, "") is True


# --- effector retry + exclusion -------------------------------------------- #
def test_effector_retries_transient_then_recovers(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    calls = {"n": 0}
    sleeps: list[float] = []

    def invoker(cmd, cwd, env):
        calls["n"] += 1
        if calls["n"] <= 2:
            return {"is_error": True, "result": "529 overloaded"}, 1, ""
        return {"is_error": False, "result": "ok", "usage": {}, "num_turns": 1}, 0, ""

    eff = ClaudeCodeEffector(
        orchestrator_run_config(), max_retries=4, sleep=lambda d: sleeps.append(d), invoker=invoker
    )
    session = eff.run(_task(tmp_path))
    assert calls["n"] == 3  # 2 transient + 1 success
    assert len(sleeps) == 2
    assert session.retries == 0  # transient retries are NOT effector build retries


def test_effector_raises_transient_after_exhausting_retries(tmp_path: Path) -> None:
    eff = ClaudeCodeEffector(
        orchestrator_run_config(),
        max_retries=2,
        sleep=lambda d: None,
        invoker=lambda cmd, cwd, env: (
            {"is_error": True, "result": "502 token refresh failed; re-run /login"},
            1,
            "",
        ),
    )
    with pytest.raises(TransientEffectorError):
        eff.run(_task(tmp_path))


def test_effector_retries_on_timeout_then_raises(tmp_path: Path) -> None:
    def invoker(cmd, cwd, env):
        raise subprocess.TimeoutExpired(cmd, 1)

    eff = ClaudeCodeEffector(
        orchestrator_run_config(), max_retries=1, sleep=lambda d: None, invoker=invoker
    )
    with pytest.raises(TransientEffectorError):
        eff.run(_task(tmp_path))


# --- driver transient-raise ------------------------------------------------ #
class _RateLimit(Exception):
    pass


class _AlwaysRateLimitMessages:
    def create(self, **kwargs):
        raise _RateLimit("Error code: 502 - token refresh failed; re-run /login")


class _AlwaysRateLimitClient:
    def __init__(self):
        self.messages = _AlwaysRateLimitMessages()


def test_driver_raises_transient_when_primary_and_fallback_both_blip() -> None:
    """The pilot_A3 crash: a persistent 502 in reflect. Must surface as TransientInfraError
    (so the orchestrator excludes the task), NOT a raw crash that kills the run."""
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=_AlwaysRateLimitClient(),
        fallback_client=_AlwaysRateLimitClient(),
        max_retries=1,
        sleep=lambda d: None,
    )
    gate = GateOutcome(False, True, 0, False, ["boot:healthz"], "502 token refresh failed")
    with pytest.raises(TransientInfraError):  # TransientDriverError is a subclass
        drv.reflect(
            spec=load_spec(ORDERS),
            feature_tags=["rule:state_machine"],
            retrieved=[],
            incorporated=[],
            gate=gate,
            library=type("L", (), {"ids": lambda self: []})(),
        )
    assert issubclass(TransientDriverError, TransientInfraError)

"""Shared error types for the Phase −1 orchestrator (T-1.3 full-run hardening).

A long unattended run WILL hit transient API/infra failures (gateway 429/529/502
token-refresh, timeouts, connection resets). These are *infrastructure*, not the agent
failing the task — so they must never be recorded as a real first-pass/contract failure
(which would corrupt the experiment's primary signal). The driver and the effector raise
:class:`TransientInfraError` when they exhaust retries on such a condition; the
orchestrator catches it and records the task as ``excluded_from_slope`` (ADR-0017 warm-up/
exclusion: "exclude only infrastructure failures unrelated to the agent").
"""

from __future__ import annotations

# Substrings that mark a transient/infra failure in an API error or CLI result: gateway
# rate limits, overload, 5xx, the 502 token-refresh seen in the pilot, and credential
# expiry. Deliberately SPECIFIC (HTTP codes + distinctive phrases) — bare "timeout"/
# "connection" are omitted because a real build's output can contain them, which would
# wrongly EXCLUDE a genuine failure; true SDK timeouts/connection resets are caught by the
# driver's exception-type names and the effector's subprocess.TimeoutExpired handler.
TRANSIENT_MARKERS = (
    "rate_limit",
    "overloaded",
    "429",
    "500",
    "502",
    "503",
    "504",
    "529",
    "token refresh",
    "service unavailable",
    "unauthorized",
    "invalid_api_key",
)


def is_transient_message(text: str) -> bool:
    """True if ``text`` looks like a transient/infra failure (case-insensitive)."""
    low = text.lower()
    return any(m in low for m in TRANSIENT_MARKERS)


class TransientInfraError(Exception):
    """A transient/infrastructure failure (not an agent/build failure). Carries the stage
    it occurred in and any spend already incurred, so the orchestrator can record an
    excluded task with faithful cost."""

    def __init__(self, message: str, *, stage: str, cost_usd: float = 0.0):
        super().__init__(message)
        self.stage = stage
        self.cost_usd = cost_usd


class TransientDriverError(TransientInfraError):
    """Raised by the driver when compose/reflect exhausts retries on a transient API error."""


class TransientEffectorError(TransientInfraError):
    """Raised by the effector when it exhausts retries on a transient API/infra error."""

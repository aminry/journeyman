"""Generate valid and boundary-violating payloads from a spec (domain.md §3).

Two jobs:

* :func:`valid_payload` / :func:`valid_value` — deterministic, constraint-
  satisfying values a client may send. ``seed`` produces distinct values so list
  tests can seed many rows and uniqueness tests can avoid accidental collisions.
* :func:`boundary_cases` — for each declared constraint, the just-outside
  (rejected) and just-inside (accepted) value. This is what makes the oracle
  *strict*: a lenient service that accepts an over-length string or an
  out-of-range int must fail the corresponding case.

Determinism matters: the harness must be reproducible across runs, so nothing
here uses randomness or wall-clock time.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any

from harness.specschema import Field, InstanceSpec

# A fixed digit pool keeps generated values reproducible.
_LETTERS = string.ascii_lowercase


@dataclass(frozen=True)
class BoundaryCase:
    """One constraint probe: ``value`` for ``field`` is expected to be accepted
    (``valid=True``) or rejected with a 422 (``valid=False``)."""

    kind: str  # min | max | min_len | max_len | pattern | enum | type
    value: Any
    valid: bool
    description: str


def _digits(n: int, seed: int) -> str:
    """A reproducible n-digit numeric string keyed by seed."""
    base = str(abs(seed) % (10**n)).rjust(n, "0")
    return base[-n:]


def _pattern_value(pattern: str, seed: int) -> str:
    """Best-effort generator for the patterns used by the Phase -1 corpus.

    The corpus uses ``^[0-9]{N}$`` (ISBN/codes), hex colours, simple URL/email
    shapes. We special-case the common ones and fall back to a plain token.
    """
    p = pattern
    # ^[0-9]{N}$  -> N digits
    import re

    m = re.fullmatch(r"\^\[0-9\]\{(\d+)\}\$", p)
    if m:
        return _digits(int(m.group(1)), seed)
    m = re.fullmatch(r"\^#\[0-9a-fA-F\]\{(\d+)\}\$", p)
    if m:
        hexchars = "0123456789abcdef"
        n = int(m.group(1))
        return "#" + "".join(hexchars[(seed + i) % 16] for i in range(n))
    if "http" in p:
        return f"https://example.com/{seed}"
    if "@" in p or "email" in p.lower():
        return f"user{seed}@example.com"
    # Generic fallback: a lowercase token (callers should special-case stricter
    # patterns in the spec rather than rely on this).
    return f"val{seed}"


def valid_value(field: Field, seed: int = 0) -> Any:
    """A constraint-satisfying value for ``field`` keyed by ``seed``."""
    t = field.type
    if t == "enum":
        vals = field.values or []
        return vals[seed % len(vals)] if vals else f"v{seed}"
    if t == "boolean":
        # Alternate by seed so seeded rows have real variety — a constant value
        # would let a filter-ignoring service pass the boolean filter case
        # undetected (the default is still exercised by the omit-it default case).
        return seed % 2 == 0
    if t == "integer":
        lo = field.min if field.min is not None else 0
        hi = field.max if field.max is not None else (lo + 1000)
        span = hi - lo
        return int(lo + (seed % (span + 1))) if span >= 0 else int(lo)
    if t == "number":
        lo = float(field.min) if field.min is not None else 0.0
        hi = float(field.max) if field.max is not None else (lo + 1000.0)
        span = hi - lo
        return round(lo + (seed % 100) / 100.0 * (span if span > 0 else 1.0), 4)
    if t == "datetime":
        # ISO 8601; vary by seed within a safe range.
        day = 1 + (seed % 27)
        return f"2026-01-{day:02d}T00:00:00Z"
    if t == "uuid":
        return f"00000000-0000-0000-0000-{seed:012d}"
    if t == "ref":
        return f"00000000-0000-0000-0000-{seed:012d}"
    # string
    if field.pattern:
        return _pattern_value(field.pattern, seed)
    min_len = field.min_len or 1
    max_len = field.max_len or max(min_len, 8)
    token = (field.name[:3] or "x") + _LETTERS[seed % 26] + str(seed)
    if len(token) < min_len:
        token = token + "x" * (min_len - len(token))
    if len(token) > max_len:
        token = token[:max_len]
    return token


def valid_payload(spec: InstanceSpec, seed: int = 0) -> dict[str, Any]:
    """A complete, constraint-satisfying create payload (writable fields only)."""
    payload: dict[str, Any] = {}
    for f in spec.resource.writable_fields():
        payload[f.name] = valid_value(f, seed)
    return payload


def boundary_cases(field: Field) -> list[BoundaryCase]:
    """The reject/accept probes implied by ``field``'s declared constraints."""
    cases: list[BoundaryCase] = []

    if field.min is not None:
        cases.append(BoundaryCase("min", field.min - 1, False, f"{field.name} below min"))
        cases.append(BoundaryCase("min", field.min, True, f"{field.name} at min"))
    if field.max is not None:
        cases.append(BoundaryCase("max", field.max + 1, False, f"{field.name} above max"))
        cases.append(BoundaryCase("max", field.max, True, f"{field.name} at max"))
    if field.min_len is not None:
        below = "" if field.min_len == 0 else "x" * (field.min_len - 1)
        if field.min_len >= 1:
            cases.append(BoundaryCase("min_len", below, False, f"{field.name} under min_len"))
        cases.append(BoundaryCase("min_len", "x" * field.min_len, True, f"{field.name} at min_len"))
    if field.max_len is not None:
        cases.append(
            BoundaryCase("max_len", "x" * (field.max_len + 1), False, f"{field.name} over max_len")
        )
        cases.append(BoundaryCase("max_len", "x" * field.max_len, True, f"{field.name} at max_len"))
    if field.pattern is not None:
        # A value guaranteed not to match the corpus patterns.
        cases.append(
            BoundaryCase("pattern", "!!not-matching!!", False, f"{field.name} violates pattern")
        )
        cases.append(
            BoundaryCase("pattern", valid_value(field, 0), True, f"{field.name} matches pattern")
        )
    if field.type == "enum" and field.values:
        bad = "___not_a_valid_enum_member___"
        cases.append(BoundaryCase("enum", bad, False, f"{field.name} not in enum"))
        cases.append(BoundaryCase("enum", field.values[0], True, f"{field.name} valid enum"))

    # Type-mismatch probe (domain.md §3 "each type/constraint"): a wrong-typed value
    # must be rejected (422). The probe is chosen to catch *loose coercion* — a value
    # whose coerced form would otherwise be accepted — not just a value that crashes.
    if field.type in ("integer", "number"):
        # a numeric STRING: a strict service rejects (wrong type); a coercing one accepts.
        cases.append(
            BoundaryCase(
                "type",
                str(valid_value(field, 0)),
                False,
                f"{field.name} numeric string for {field.type}",
            )
        )
    elif field.type == "boolean":
        # a string "true": a strict service rejects; a coercing one accepts.
        cases.append(BoundaryCase("type", "true", False, f"{field.name} string for boolean"))
    elif field.type == "enum" and field.values:
        cases.append(BoundaryCase("type", 999999, False, f"{field.name} non-string for enum"))

    return cases

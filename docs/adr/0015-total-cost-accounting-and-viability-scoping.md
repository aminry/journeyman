# ADR-0015: Total-cost-of-ownership accounting + viability-gate scoping

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** governance, economics, observability

## Context

The master metric is the cost-per-task curve, watched forever as a viability gate
(ADR-0007). But cost-per-task as written counts task-time tokens (model +
effector); the system *also* spends continuously on **dreaming** (replaying the
episodic log, re-embedding), the **regression guard** (run on every
self-modification), **eval suites**, and **library maintenance**. If that overhead
is excluded, the curve can bend while true total cost is flat or rising — the
accounting-level version of "measurement can lie." Separately, the viability gate
assumes *repeated tasks within a domain*; Phase 1's self-build backlog is
heterogeneous one-off tooling with no within-domain repetition, so applying the
compounding slope there would spuriously halt.

## Decision

- Define the viability metric as **total system spend ÷ completed tasks over a
  window**, including off-duty dream, eval, regression-guard, and maintenance
  overhead — not only task-time tokens. Traces carry a **cost category** so
  overhead is attributable, and an **overhead ratio** (overhead ÷ task-time) is
  reported alongside the curve.
- **Scope the compounding gate** to repeated within-domain task streams. Phase 1's
  heterogeneous self-build is governed by **absolute budget caps and milestone
  gates**, not the compounding slope. The standing compounding gate applies in
  Phase 2 product work and any domain with task repetition.

## Consequences

- **Positive:** the economics close on a complete ledger; the gate stops
  mis-firing on one-off work; overhead becomes visible and controllable.
- **Negative / costs:** cost attribution requires the trace cost-category; the
  windowed metric is slightly more complex than a per-task number.
- **Risks & mitigations:** overhead hidden in the effector black box → already
  instrumented at the boundary (ADR-0005); window choice gamed → operator-set and
  logged (SPEC §23).

## Alternatives considered

- **Count task-time tokens only** — rejected: hides the dream/eval/maintenance
  spend most able to sink the economics.
- **Apply the slope gate everywhere** — rejected: a category error on
  heterogeneous one-off work.

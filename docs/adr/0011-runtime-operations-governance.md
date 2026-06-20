# ADR-0011: Phase 2 runtime / operations governance

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** security, governance, operations, phase-2

## Context

Everything specified about the coding effector and its sandbox is **build-time**:
fresh worktree, no ambient credentials, bounded network egress. Phase 2 runs a
**live revenue product**, which needs production credentials, deploys, schema
migrations, network egress, and a persistent runtime answering real traffic —
the opposite of the build-time sandbox. The human approval queue handles discrete
publish/payment events, but continuous operation can neither route every action
through a human (that kills the product and invites rubber-stamping) nor run fully
sandboxed (it serves users). The spec did not say where production runs, under
whose credentials, or how the autonomous loop touches production safely. This is
the highest-real-money phase and was the least specified.

## Decision

Adopt **scoped autonomous operations** for Phase 2, governed by a new
`security/runtime-ops-policy.md`, separating build-time from run-time:

- Production is a **separate environment** with its own least-privilege,
  revocable run-time credentials held by the kernel/ops policy layer — never
  ambient to the model or effector.
- The agent may take **reversible** operational actions autonomously — deploy
  behind a **canary with automated health checks and automated rollback**, scale,
  restart, toggle feature flags — within explicit **blast-radius limits** (max %
  traffic, max spend delta, rate limits).
- **Irreversible / high-impact classes stay human-gated** with parameter-bound
  approval (ADR-0007 path): schema/data migrations, data deletion, payments,
  billing, DNS, credential mutation, and anything outside blast-radius limits.
- An operator **kill switch / global halt** is always available; canary failure
  auto-rolls-back and escalates.
- Every production action is traced with cost and a rollback reference; prod
  actions influenced by untrusted content are screened first.

Per the bootstrap philosophy, the **policy and this ADR land now**; the
canary/rollback/observability **mechanism is deferred** until Phase 2 begins —
a defined contract with a deferred implementation.

## Consequences

- **Positive:** Phase 2 has an actual operations governance model; reversible
  velocity without exposing irreversible blast radius; prod credentials are
  scoped and revocable.
- **Negative / costs:** safe canary/rollback/observability is real work deferred
  to Phase 2; some legitimate ops wait on approval.
- **Risks & mitigations:** mis-classifying an action as "reversible" → default to
  human-gate when uncertain (ADR-0016 escalation); canary blind spots → health
  checks plus post-deploy canary monitoring plus the operator kill switch.

## Alternatives considered

- **Propose-only (human executes every prod action)** — rejected: too slow for a
  live product and it just relocates the bottleneck to a human who rubber-stamps.
- **Full continuous deploy with post-hoc review** — rejected: post-hoc review
  cannot prevent an irreversible production incident.

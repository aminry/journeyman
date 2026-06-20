# Runtime / Operations Policy (Phase 2)

Everything in the coding-effector sandbox (`tools/coding-effector-sandbox.yaml`)
governs **build-time**: a fresh worktree, no ambient credentials, bounded egress.
A live product in Phase 2 also has a **run-time**: it serves real users, holds
production credentials, deploys, migrates data, and answers traffic continuously.
Build-time controls do not fit run-time. This policy governs run-time. See
ADR-0011.

> **Status: defined now, mechanism deferred.** This contract lands in the seed so
> Phase 2 cannot start without it. The canary/rollback/observability machinery is
> built when Phase 2 begins (per the bootstrap philosophy: define the contract,
> defer the mechanism).

## Environment & Credential Custody

- Production is a **separate environment** from build/sandbox.
- Run-time credentials are **least-privilege, revocable, and held by the
  kernel/ops policy layer** — never ambient to the model or the coding effector,
  never written to memory or traces.
- The model may *propose* an operational action; the ops policy layer authorizes
  and executes it, exactly as the tool-policy layer does for tools.

## Action Classes

| Class | Examples | Authorization |
|---|---|---|
| Reversible autonomous | deploy behind canary, scale, restart, toggle a feature flag, roll back | autonomous **within blast-radius limits**, fully traced, auto-rollback armed |
| Human-gated (irreversible / high-impact) | schema or data migration, data deletion, payment, billing, DNS, credential mutation, anything outside blast-radius limits | parameter-bound human approval + step-up (ADR-0007 / `approval-policy.md`) |

When a class is **ambiguous, default to human-gated** (ADR-0016).

## Blast-Radius Limits (operator-set)

- max % of production traffic a single autonomous change may affect;
- max spend delta per action and per window;
- request/rate ceilings;
- a canary cohort size and minimum bake time before full rollout.

Exceeding any limit reclassifies the action as human-gated.

## Canary, Health, Rollback

- Autonomous deploys go to a **canary cohort** with automated health checks
  (error rate, latency, key product signals) over a minimum bake time.
- **Canary failure auto-rolls-back and escalates** to the operator.
- Every deploy records a **rollback reference**; rollback is itself a reversible
  autonomous action.
- Post-deploy canary monitoring continues after full rollout.

## Kill Switch

An operator **global halt / kill switch** is always available and stops
autonomous operational action immediately, independent of the model.

## Untrusted Content

Any operational action whose inputs were influenced by untrusted content
(web, user data, tool output) is screened by
`security/untrusted-content-pipeline.md` before execution — production actions are
never driven by un-screened external content.

## Tracing

Every operational action emits a trace span with cost, the authorizing policy
version, the blast-radius decision, and the rollback reference. Production
incidents and rollbacks are recorded as `security_event` spans.

## Change Control

This file is security-critical: changes require human review and re-run the
`tool-abuse` and `approval-bypass` red-team suites (`evals/eval-governance.md`).

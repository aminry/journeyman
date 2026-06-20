# ADR-0008: Dream job and regression guard are seed-owned and conservative

- **Status:** Accepted
- **Date:** {{YYYY-MM-DD}}
- **Deciders:** {{WHO_DECIDED}}
- **Tags:** safety, self-modification

## Context

The dream/consolidation job rewrites the system's own memory and skills, and the regression guard is the gate protecting against self-degradation. These are the highest-blast-radius components, and letting an unproven system author them is a documented risk (emergent misevolution).

## Decision

The **dream job and the regression guard are seed-owned, hand-written, and conservative** — not on the self-build backlog. The dream job makes only small, reversible, eval-gated, versioned (git-snapshotted) changes. The **regression guard uses a rotating, partly held-out, growing, adversarial eval harness with human spot-checks**; unverifiable work routes to a human judge. The **kernel is protected**: the system may propose changes to kernel/dream/guard but applying them requires human sign-off.

## Consequences

- **Positive:** self-modification cannot silently corrupt memory or degrade the system; everything is revertible.
- **Negative / costs:** slower evolution of these components; human in the loop for their changes.
- **Risks & mitigations:** eval-harness overfit (Goodhart) — mitigated by rotation, held-out sets, and human spot-checks.

## Alternatives considered

- **Let the system build its own dream/guard in Phase 1** — rejected: a buggy self-built consolidation can corrupt all downstream memory.

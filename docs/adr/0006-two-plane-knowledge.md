# ADR-0006: Two-plane knowledge separation

- **Status:** Accepted
- **Date:** {{YYYY-MM-DD}}
- **Deciders:** {{WHO_DECIDED}}
- **Tags:** architecture, memory, knowledge

## Context

For agents to be portable across projects — deployable onto new systems, getting better each time — the craft they carry must be separated from the specifics of any one system. A senior engineer carries their craft between jobs but does not memorize the last employer's schema.

## Decision

Maintain **two knowledge planes**. *Plane A — project knowledge* (CLAUDE.md, ARCHITECTURE.md, DESIGN.md, ADRs, the code knowledge graph, tests/build/CI) lives in each project repo, is regenerable, and is disposable. *Plane B — agent knowledge* (generic skills, heuristics, semantic memory) is portable and holds **only** generic, project-stripped craft. The sole crossing is the **distillation boundary** in `dream/`: a candidate entering agent memory must pass "would this help on a different, unrelated system?" Project-scoped identifiers are rejected or abstracted. The agent loads project context into *working memory* at build time but never persists it durably.

## Consequences

- **Positive:** agents are portable and improve across projects without dragging prior designs; a fresh agent onboards from the repo alone.
- **Negative / costs:** the distillation step must be enforced, not assumed.
- **Risks & mitigations:** knowledge leakage (project specifics polluting portable memory) — mitigated by project-stripping enforcement at the boundary.

## Alternatives considered

- **One unified memory store** — rejected: agents accumulate non-portable baggage and cannot be cleanly redeployed.

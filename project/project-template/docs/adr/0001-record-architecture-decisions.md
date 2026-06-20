# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** {{YYYY-MM-DD}}
- **Deciders:** {{WHO_DECIDED}}
- **Tags:** process, documentation

## Context

This repository is built and maintained largely by autonomous agents, and any agent (or human) may be dropped into it without prior context. Decisions about structure, interfaces, and trade-offs must therefore be legible from the repo alone — the rationale cannot live only in someone's (or some model's) memory, because that memory is intentionally not carried between projects. We need a lightweight, durable, append-only record of significant decisions and *why* they were made.

## Decision

We will record every significant architectural decision as an **Architecture Decision Record (ADR)** in `docs/adr/`, using the format in `docs/adr/template.md`. ADRs are numbered sequentially, are append-only, and a superseded decision is replaced by a new ADR that links back to it. The Definition-of-Done gate requires an ADR for any change with architectural impact (or an explicit `architecture-impact: none` declaration).

## Consequences

- **Positive:** decisions and their rationale are discoverable from the repo; onboarding cost drops; settled questions are not silently re-litigated; the docs-in-sync gate has a concrete artifact to check for.
- **Negative / costs:** a small per-change overhead to write the ADR for architectural changes.
- **Risks & mitigations:** ADRs could rot or be skipped — mitigated by enforcing them in the Definition-of-Done gate rather than relying on discipline.
- **Follow-ups required:** none; the template and gate ship with this repo.

## Alternatives considered

- **No formal record (rely on commit messages / code comments)** — rejected: not discoverable as a body of decisions, and rationale gets lost.
- **A single growing DESIGN.md** — rejected: hard to supersede cleanly and becomes an unreviewable monolith; ADRs keep each decision atomic and append-only. `DESIGN.md` is retained for high-level design that links out to ADRs.

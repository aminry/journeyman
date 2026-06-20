# DESIGN.md — High-level design

This document gives the high-level design narrative and links out to the detailed specification and the decision records. It is intentionally short; depth lives in `docs/SPEC.md`, and each significant decision lives in `docs/adr/`.

## Thesis

Treat the LLM as a fixed CPU and put all durable, growing competence in external, versioned stores. The Journeyman's distinctive value is the layer *above* a strong coder: lifelong portable craft, a milestone-budget economic loop, and the governance that keeps self-modification safe. A subsystem is worth building only if it makes the *Nth* task in a domain cheaper and better than the 1st — and that claim is **tested in Phase −1 before the rest is built**.

## The bet, stated plainly

Competence compounds *as portable judgment*, not as reusable code. Because coding is delegated to an effector that writes fresh code each task, what accumulates in agent memory is orchestration craft — better specs, decomposition recipes, review checklists, known effector failure modes. Phase −1 measures exactly this.

## Shape of the system

- A **single agent** runs a tight work loop, driving a **coding effector** as its most powerful tool.
- It reads each project's **brain** (Plane A) to orient, and carries only **generic craft** (Plane B) between projects.
- It **dreams** to consolidate, distill, and prune — eval-gated and revertible.
- It operates under a **budget** that real milestones and revenue refill, with hard ceilings and a cost-per-task viability gate.
- Everything is **traced with cost attached**; the total-cost-per-task curve (amortized overhead included) is the master metric.
- It is **hardened at the boundaries** agentic systems actually fail at: code-security scanning of effector output, independent verification of specs and tests, execution-grounded memory promotion with unlearning, model-version-scoped craft, scalable oversight, and a separate Phase-2 runtime-ops surface (ADRs 0010–0017).

## What is deliberately deferred

Multi-agent coordination, agent-level graph memory, custom model training, and an automatic curriculum are all deferred until a concrete, measured need appears. See ADRs 0003–0004 and `docs/SPEC.md` §5.

## Decision records

- ADR-0001 — Record architecture decisions
- ADR-0002 — Validate compounding before building (Phase −1 gate)
- ADR-0003 — Single agent first; defer multi-agent
- ADR-0004 — Vector-first agent memory; defer agent graph memory
- ADR-0005 — Delegate coding to an effector driven as a tool
- ADR-0006 — Two-plane knowledge separation
- ADR-0007 — Milestone-gated budget + cost-per-task viability gate
- ADR-0008 — Dream job and regression guard are seed-owned and conservative
- ADR-0009 — Require assurance artifacts and security gates
- ADR-0010 — Code-security gate on effector-produced code
- ADR-0011 — Phase 2 runtime / operations governance
- ADR-0012 — Durable-memory robustness (misevolution, poisoning, unlearning, forgetting)
- ADR-0013 — Portable craft is model/effector-version-scoped
- ADR-0014 — Independent verification of specs and acceptance tests
- ADR-0015 — Total-cost-of-ownership accounting + viability-gate scoping
- ADR-0016 — Scalable human oversight
- ADR-0017 — Phase −1 statistical rigor
- ADR-0018 — Agent↔operator communication contract (human interface)

## Phases

−1 Validate → 0 Seed → 1 Dogfood → 2 Product. See `README.md` and `tasks/BACKLOG.md`.

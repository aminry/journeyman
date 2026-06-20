# ARCHITECTURE.md — Journeyman component map

This is the **living** map of the Journeyman's structure, kept current by the Definition-of-Done gate. For full rationale and detail, see `docs/SPEC.md`. For decisions and their reasoning, see `docs/adr/`.

## Layers and components

| Component (dir) | Responsibility | Status |
|---|---|---|
| `kernel/` | Agent runtime (work loop), model router, tool registry, execution sandbox, event bus / trace log. **Protected** — human sign-off required to change. | Seed |
| `memory/` | Agent knowledge (Plane B): episodic log, vector semantic + summary memory, generic skill library (model/effector-`validated_against` manifests), promotion gates with execution-grounded corroboration, unlearning + protected-class forgetting. | Seed (agent graph deferred) |
| `governance/` | Budget ledger, cost ceiling, total-cost-per-task gate (amortized overhead), scalable human oversight (risk-weighted sampling, fail-closed), credential/capability scoping, regression guard + rotating eval harness. | Seed |
| `dream/` | Consolidation, the distillation boundary (Plane A↔B), skill-library maintenance. **Seed-owned, conservative.** | Seed |
| `cognition/` | Retrieval, immediate reflection. | Seed (curriculum deferred) |
| `tools/` | Primitive tools (shell, file, web fetch, code exec) and the **coding-effector adapter** (Claude Code, spec-in/verified-out, instrumented). | Seed |
| `project/` | Project scaffolder, the code-graph indexer interface, and the Definition-of-Done logic. Contains `project-template/`. | Seed |
| `observability/` | Trace queries and dashboards over the event log. | Seed schema; dashboards Phase 1 |
| `evals/` | The rotating, partly held-out regression harness + held-out sets. | Seed |
| `experiments/` | The Phase −1 validation harness and results. | Phase −1 |
| `tasks/` | The TaskSpec backlog. | — |
| `coordination/` | Multi-agent messaging, contract-net, roles. **DEFERRED** — placeholder only; do not build until a task provably requires it. | Deferred |

## Knowledge planes (ADR-0006)

- **Plane B — Agent knowledge** (`memory/`): portable, generic engineering craft. Travels with the agent across projects.
- **Plane A — Project knowledge** (in each project repo): `CLAUDE.md`, `ARCHITECTURE.md`, `DESIGN.md`, ADRs, the code knowledge graph, tests/build/CI. Disposable; stays in the repo.
- The **distillation boundary** (`dream/`) is the only crossing: generic, project-stripped lessons go B-ward; project specifics never enter agent memory.

## Primary control flows

- **Work loop** (`kernel/`): pull task → load project brain into working memory → retrieve generic skills/memory → route to model → act (reuse skill / drive coding effector / model call / enqueue approval) → Definition-of-Done gate → record trace + cost → reflect on failure → promote generic candidates → update cost-per-task. One step per model decision; the kernel moves money, runs code, and writes durable stores.
- **Dream loop** (`dream/`): off-duty consolidation → distillation (generic vs project-specific) → skill-library maintenance → memory maintenance → forgetting → eval-gated, versioned commit (revertible).
- **Budget loop** (`governance/`): spend → milestone/revenue tops up budget; floor or daily ceiling trips the circuit breaker; cost-per-task gate halts if cost isn't falling.

## Coding effector boundary

Coding is delegated to a coding effector driven as a tool (ADR-0005). The agent sends a TaskSpec + acceptance tests; the effector works inside the target repo; output is accepted only when the Definition-of-Done gate passes; the boundary is instrumented (cost, transcript, retries, git diff) as an `effector_session` span. The gate also runs **code-security scanning** (SAST + SCA, ADR-0010) on what the effector writes, and the TaskSpec + acceptance tests are **independently verified by a different source class** before the effector runs on risk/cost-gated tasks (ADR-0014) — the spec/tests are the trust anchor, so they are checked, not assumed.

## Runtime operations boundary (Phase 2)

Build-time controls (sandbox, no ambient credentials) do not fit a live product. `security/runtime-ops-policy.md` (ADR-0011) governs run-time: reversible ops (canary deploy, scale, rollback) are autonomous within blast-radius limits with automated rollback; irreversible ops (migrations, deletes, payments, billing, DNS, credential mutation) are human-gated; production credentials are scoped, revocable, and never ambient; an operator kill switch is always live.

> Keep this file accurate. If a change alters a component's responsibility, status, or a control flow, update the relevant row/section in the same change (enforced by the docs-in-sync gate).

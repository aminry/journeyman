# memory/  (SEED — agent graph deferred)

Agent knowledge, **Plane B**: portable, generic engineering craft only — never project specifics (ADR-0006). Vector-first (ADR-0004).

Build here:
- **Episodic log** — append-only task/step/outcome/lesson; source of truth for replay and dreaming.
- **Semantic + summary memory** — vector store; adopt an existing runtime (Mem0/Zep/Letta/Hindsight) unless there's reason not to.
- **Generic skill library** — two kinds: `orchestration` (specs, playbooks, checklists, effector failure modes) and `code` (reusable utilities). Tested, manifested, versioned.
- **Promotion gates** — skills: tests + generality + dedupe + project-stripped; facts: corroboration by a *different source class* (ADR-0004/0006).

Deferred: agent-level graph memory (earn it when a task needs multi-hop/temporal recall).

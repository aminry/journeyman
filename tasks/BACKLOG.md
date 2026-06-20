# tasks/BACKLOG.md — Ordered work for the initial run

Work top to bottom. **Do not start Phase 0 until Phase −1 passes its gate.** Every task is a spec with **acceptance tests**; "done" means the acceptance tests and the Definition-of-Done gate pass — never an assertion. Machine-readable examples live in `tasks/phase_minus_1/` and `tasks/phase_0_seed/`; add the rest in the same format as you go.

Each task: set `budget_cap_usd`, mark `verifiable`, and mark `requires_human_approval` for anything irreversible. Reference the ADR(s) that constrain it.

---

## Phase −1 — Validate the premise  (GATE: the cost curve bends)

**T−1.1 — Build the minimal validation harness** (`experiments/phase_minus_1/`)
One agent, one model + one cheap fallback, a flat skill/craft library on disk, simple vector retrieval, the coding-effector adapter, the Definition-of-Done gate, and trace+cost logging **instrumented across the effector boundary**. No dream, no agent graph, no second agent, no promotion gate beyond "passes the gate."
- *Acceptance:* runs one end-to-end task in the chosen domain; emits per-task cost (incl. effector), wall-clock, gate pass/fail, effector retries, and prior-craft reuse count.

**T−1.2 — Run the 30-task sequence and produce the report**
- *Acceptance:* a results file showing the three pass criteria evaluated: (1) cost-per-task slope clearly negative after warm-up; (2) gate pass-rate non-decreasing and effector retries/task trending down; (3) measurable reuse of earlier orchestration craft.
- *Decision:* **pass → proceed to Phase 0; flat/negative → stop and diagnose** (retrieval misses, over-specific playbooks, or thin specs). Do not build the seed on a flat curve. (ADR-0002)

---

## Phase 0 — Seed  (single agent; build in dependency order)

**T0.1 — Event bus + trace log + cost accounting** (`kernel/`, `observability/`)
- *Acceptance:* every tool/model/store call emits a span with cost; a task trace can be replayed; cost-per-task is computable. (SPEC §14)

**T0.2 — Model router** (`kernel/`)
- *Acceptance:* ≥2 endpoints registered with measured capability scores + cost; `select()` picks the cheapest endpoint clearing the bar; failures escalate; every routing decision is logged.

**T0.3 — Tool registry + execution sandbox** (`kernel/`, `tools/`)
- *Acceptance:* tools register with declared capabilities; code runs sandboxed with no ambient credentials; a capability-scoped credential bundle is injected per task.

**T0.4 — Coding-effector adapter** (`tools/`, ADR-0005)
- *Acceptance:* `drive_coding_effector(spec)` runs the effector in a target repo against a TaskSpec; result accepted only when the Definition-of-Done gate passes; boundary instrumented (cost, transcript, retries, git diff) as an `effector_session` span; effector is swappable behind the interface.

**T0.5 — Agent memory: episodic + vector semantic/summary** (`memory/`, ADR-0004)
- *Acceptance:* write/read episodes and generic facts; vector retrieval returns relevant items; **no project-specific identifiers stored** (boundary checked).

**T0.6 — Flat generic skill library + promotion gates** (`memory/`)
- *Acceptance:* skills (`orchestration` and `code` kinds) written with manifests + tests; promotion requires tests + generality + dedupe + project-stripped; facts require different-source-class corroboration. (ADR-0006)

**T0.7 — Project scaffolder + Definition-of-Done logic + code-graph indexer interface** (`project/`, SPEC §11)
- *Acceptance:* `scaffold_project` produces a repo from `project-template/` with placeholders filled; CI wired to the gate; the gate runs each `type` in `definition_of_done.yaml`; the code graph regenerates and the `code-graph-fresh` check works.

**T0.8 — Governance: budget ledger + cost ceiling + cost-per-task gate + approval queue + credential scoping** (`governance/`, ADR-0007)
- *Acceptance:* spend is charged per task; ceiling/floor trips the circuit breaker; the cost-per-task gate halts when cost isn't falling; irreversible actions queue for human approval by task class.

**T0.9 — Cognition: retrieval + immediate reflection** (`cognition/`)
- *Acceptance:* retrieval injects relevant skills/memory + the active project's brain into working memory; on failure, reflection adjusts and retries.

**T0.10 — Regression guard + rotating eval harness** (`governance/`, `evals/`, ADR-0008)
- *Acceptance:* a held-out, growing, adversarial harness runs; any self-modification must pass before commit; failures roll back; unverifiable tasks route to a human judge.

**T0.11 — Dream / consolidation / distillation job** (`dream/`, ADR-0008)
- *Acceptance:* a conservative off-duty job consolidates episodes, applies the distillation boundary, maintains the skill library, prunes/forgets, and commits an eval-gated, versioned, revertible snapshot. Post-cycle: retrieval precision up, skill count down with coverage held, contradictions down.

**T0.12 — Wire the full single-agent work loop** (`kernel/`, SPEC §12)
- *Acceptance (Phase 0 exit):* the system can take a task, load a project brain, retrieve, route, **drive the coding effector under the verified contract**, run sandboxed code, write & test a generic skill, write agent memory, scaffold a project, pass the Definition-of-Done gate, dream conservatively, pass the regression guard, emit traces (including the effector boundary), and enqueue an approval.

---

## Phase 1 — Dogfood  (the seed builds these; non-critical only)

In order: observability dashboard → retrieval ranker → routing learner → one trivial internal tool end-to-end → curriculum (if needed). The dream job, regression guard, scaffolder, and Definition-of-Done are **not** here — they are seed-owned. (SPEC §19)

## Phase 2 — Product

One web product; milestone- and revenue-gated budget. Operator sets the product and its first three verifiable milestones (see `docs/SPEC.md` §23).

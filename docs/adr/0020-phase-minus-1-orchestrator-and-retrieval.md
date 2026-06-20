# ADR-0020: Phase −1 orchestrator (driver loop) + craft retrieval

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator (Amin), Claude Code (Opus 4.8)
- **Tags:** experiments, phase-minus-1, orchestration, memory, retrieval, evals

> This is the **locked design** T-1.3 (Run A + control Run B) is built against — no
> code yet. The T-1.1 spine (ADR-0019) deliberately had no driver: craft was
> hand-seeded and retrieval was keyword/tag. This ADR specifies the driver loop, how
> external-only competence is enforced, the driver model, what craft is and when it's
> written, vector retrieval + reuse measurement, and the control run. All five forks
> are resolved in **Locked decisions**; the **Required gates** are hard gates T-1.3/
> T-1.4 must enforce (not advisories).

## Context

Phase −1 (ADR-0002) tests one claim: in `spec → CRUD service`, the Nth task gets
cheaper/better because the agent reuses **portable orchestration craft** — not
because code is reused (the effector writes fresh code each task). SPEC §4 is
explicit that what must compound is *orchestration judgment* (better specs,
decomposition recipes, known effector failure modes), **not static injected text**
and **not in-context learning**. The decisive failure signal (domain.md §6): if
cost falls but the **reuse counter stays ~0**, that is the effector being good on
its own, not compounding.

The spine proved the measurement machinery end-to-end (oracle, fresh-repo scaffold,
instrumented effector boundary, faithful cost, flat craft library + reuse counter,
results/trace schemas) and that the live effector seam works (the real run passed
52/52 held-out cases from the spec + craft alone). What remains undefined is the
**driver/orchestrator**: the agent that, per task, turns the instance spec + prior
craft into the effector's TaskSpec and reflects afterward to grow the craft library.
That is the locus of "judgment that compounds," so its design determines whether the
experiment measures the right curve.

## Decision (proposed)

### 1. Per-task driver loop

A single **driver LLM** runs this loop per task; the kernel (not the model) moves
data, runs the effector, and writes durable stores (SPEC §12). Each step's I/O:

| Step | Inputs | Action | Outputs |
|---|---|---|---|
| **A. Retrieve** | instance spec → derived **feature tags** (tier; endpoints present; field types; rules: unique/pagination/filters/sort; business_rules) | query the craft library (vector; §5) | `retrieved`: top-k craft items (id + manifest + body) |
| **B. Compose** | instance spec + `retrieved` | driver composes the effector **TaskSpec**: intent restatement, the spec, pinned API conventions + boot/DoD contract (as today), **plus** the craft guidance it judges relevant | `taskspec_text`; **`incorporated`**: the craft ids actually woven into the TaskSpec (structured output) |
| **C. Drive** | `taskspec_text` | `drive_coding_effector` (unchanged; boundary instrumented) | `effector_session` (cost, retries, diff) |
| **D. Gate** | effector repo | boot `./run.sh` → `/healthz` → contract suite + instance DoD (unchanged) | `SuiteResult`, `DodResult` |
| **E. Reflect** | spec, `retrieved`/`incorporated`, gate outcome (pass/fail, retries, failing case ids, diff) | driver decides **WRITE / UPDATE / SKIP** a craft item, **project-stripped + generic** (§4) | craft mutation (or none) + manifest |

The reuse counter records `craft_items_retrieved` (Step A) and
`craft_items_reused` = `incorporated` (Step B). Steps B and E are the only driver
**model calls** → `model_cost_usd`; Step C is `effector_cost_usd`. Both are
first-class and separately accounted (ADR-0015); the spine already keeps
`model_cost_usd` as a field (0 there).

### 2. Externalized-competence constraint (the load-bearing control)

To measure **external craft** compounding and *not* in-context learning, each task
starts with a **fresh driver context**; the only thing that persists across tasks is
the **on-disk craft library**. Enforced by:

- **Fresh invocation per task** — a new driver session/`messages[]` with no prior
  conversation; tasks never share a context window. (If the driver is a sub-agent,
  it is spawned fresh per task and torn down.)
- **Inputs are closed** — the driver's *only* inputs are the instance spec and what
  Step A retrieves from the library. No global scratchpad, no episodic log, no
  cross-task notes. (Prompt caching may cache the **fixed** system prompt for cost,
  but must never carry prior-task *content* — verified via `cache_read` containing
  only the frozen prefix.)
- **Sequential, library-only state transfer** — between tasks the only mutated state
  is `craft/` + the metrics log; the runner asserts no other carryover.
- **Auditable** — the trace logs the driver's full input per task (spec digest +
  retrieved/incorporated craft ids) and a `decision` provenance span, so a reviewer
  can confirm nothing else entered the context.

This is exactly what makes the treatment−control delta (§6) attributable to craft.

### 3. Driver model + cost

The driver's job is reasoning-over-text (compose a structured TaskSpec; distill a
generic playbook), not heavy coding. Driver spend is **`model_cost_usd`**, separate
from the effector's `effector_cost_usd`; both roll into `total_cost_usd`. The driver
model is part of craft's `validated_against` (ADR-0013) alongside the effector and
embedding model.

**Pinned identically across Run A and Run B** (§6): the driver model, its full
prompt, **and its decoding settings**. Pin the driver's **sampling params** with the
model and record them in `pins.driver` — for the Sonnet 4.6 driver, **`temperature ≈
0`** (one sampling param, per Claude-4 rules) for reproducible composition/reflection.
(If escalated to Opus 4.8, which removes sampling params, pin adaptive-thinking +
`effort` instead and record those.) **Always report the effector-cost slope alongside
the total-cost slope** so a rising driver cost can never mask a falling effector
signal (the compounding may show first in effector cost).

**Driver model: Sonnet 4.6 (primary) + Haiku 4.5 (cheap fallback)**, effector stays
Opus 4.8. Rationale: strong enough for spec composition + reflection, materially
cheaper than Opus, keeps the *total*-cost signal clean and the economics realistic
(SPEC §4: "one model + one cheap fallback"). **Hard gate (not advisory):** the
pilot-triplet craft-quality check (see Required gates) **must** pass before the full
run — if the first triplet's craft is weak/over-fit **or** reuse ≈ 0 for retrieval
reasons, **bump the driver to Opus 4.8 (re-pinning its decoding) before the full run**.
Don't start on Opus; escalate on evidence.

### 4. Craft items

A Phase −1 craft item is an **orchestration playbook** (`kind: orchestration`),
keyed by **feature tags**, stored per `memory/skill-manifest.schema.json` (as the
spine already does). Examples: `crud-spec-template`, `validation-422-shape`,
`pagination-contract`, `unique-409-recipe`, `sort-contract`, `filter-contract`,
`server-managed-fields-recipe`, `state-machine-playbook`, `cross-field-rule-recipe`,
`relationship-ref-recipe`, `composite-unique-recipe`, plus the seeded
`fastapi-sqlite-scaffold`. Content is generic, project-stripped guidance the driver
weaves into the TaskSpec to reduce effector retries / raise first-pass success.

Reflection (Step E) decides:

- **WRITE (new)** — the task exercised a feature/failure-mode not covered by existing
  craft **and** yielded a generalizable, project-stripped lesson.
- **UPDATE (existing)** — a retrieved item was used but the outcome revealed a
  refinement (e.g. the effector still missed `max_limit` despite
  `pagination-contract`); bump `version`, refresh `validated_against`/`last_validated`.
- **SKIP** — the task added nothing new (covered by existing craft that worked
  first-pass). The default, to prevent bloat.

**Anti-rot guardrails (harness-enforced, since Phase −1 has no promotion gate):**
(a) **project-stripping lint** rejects instance identifiers (resource names, paths,
field names from the spec) in craft bodies; (b) **dedupe** — a WRITE must justify
itself against retrieval of existing craft for the same tags (≈one canonical item
per feature tag, evolved via UPDATE, not proliferated); (c) **manifest validation**
against the schema, fail-closed; (d) reflection writes are logged with provenance.

**Craft-impact tracking (harmful-craft detection — required).** The mandatory
control run (§6) catches *absent* craft (craft adds nothing), but **not *harmful*
craft** — a bad reflection that writes a misleading playbook which, when reused,
makes the effector *worse*. So per craft item, track the outcomes of tasks where it
was **reused**: `mean_effector_retries`, `first_pass_gate_rate`, `uses` (the
`metrics` block already exists in `memory/skill-manifest.schema.json`), against the
running baseline. Flag an item as **harmful** when its reuse correlates with *more*
effector retries / lower first-pass than baseline, and **quarantine** it
(`status: quarantined` → retrieval skips it, as the library already does) so it can
be pruned/repaired. This ties to SPEC §9 (skill-library maintenance) and ADR-0013
(quarantine). T-1.4 reports per-craft impact.

**Fork (granularity) — recommendation: per-feature items (strong).** Alternative is
one evolving monolithic playbook. Per-feature wins because it is what makes
**retrieval and reuse measurable** — the reuse counter is per craft id, and the
whole experiment turns on "which craft was retrieved *and* incorporated." A monolith
collapses that signal (you always "retrieve" the one doc), bloats the TaskSpec, and
hides rot. Recommend per-feature.

### 5. Retrieval (real runs)

Replace the spine's keyword/tag retrieval with the protocol's **simple vector
retrieval**, behind the existing swappable `CraftLibrary.retrieve` interface:

- **Embedding model:** pin one and record it in `pins.embedding_model` (already a
  field) and in craft `validated_against` (ADR-0013). **Recommendation: a pinned
  *local* embedding model** (e.g. a `sentence-transformers` model) for determinism,
  zero per-call cost (so retrieval adds no `model_cost` noise), and no extra network
  confound. A hosted embedding API is the alternative if local quality is
  insufficient.
- **Index/query:** embed each craft item's (`summary` + `when_to_use` + `tags` +
  body); build the query from the instance's **feature tags** + a short spec
  digest; cosine top-k (k pinned, e.g. 5).
- **Reuse measurement:** an item is **retrieved** if returned by the query;
  **reused** if the driver **incorporates** it into the composed TaskSpec. Reuse is
  the driver's structured `incorporated` list **verified** against the TaskSpec
  (the guidance must actually appear), not a substring guess and not mere retrieval
  — this is the decisive, gameable metric, so it is checked.
- **Keyword fallback:** if the embedding model is unavailable, fall back to the
  spine's keyword/tag retrieval (interface already supports it). A retrieval
  diagnostic (precision of retrieved-vs-incorporated) is logged so a flat reuse
  curve can be diagnosed as *retrieval miss* vs *absent compounding* (domain.md §6).

### 6. Control run (Run B) — what's disabled

Run B isolates the craft contribution. It uses the **same driver model, the same
byte-identical driver prompt, and the same Step-B composition step** as Run A. The
only difference: the craft library is **frozen empty** —

- **No retrieval** (Step A returns nothing) → the driver composes from the instance
  spec + the fixed conventions/boot/DoD contract alone (identical base TaskSpec to A);
- **No reflection-write** (Step E still *runs*, but its writes are **discarded**, not
  persisted) → the library never accumulates.

Running Step E in B (and discarding) keeps **driver-cost parity** with A, so the
treatment−control delta isolates craft's effect on the effector (fewer retries,
richer specs) rather than conflating it with "B skipped reflection." Everything else
— effector, spec, gate, task order, pricing, pins — is identical. Result: a
treatment−control delta on the cost slope attributable to **craft**, per ADR-0017.

## Locked decisions (accepted 2026-06-20)

1. **Reflection trigger = reflect-on-signal** — reflect only when `effector_retries
   > 0` OR `first_pass_contract_success` is false OR the task introduced an uncovered
   feature tag. (Escalate to reflect-every-task only if the pilot shows under-capture.)
2. **Driver model = Sonnet 4.6** (primary) **+ Haiku 4.5** (cheap fallback); effector
   stays Opus 4.8. Decoding pinned (`temperature ≈ 0`) and recorded in `pins.driver`.
   **Escalation to Opus 4.8 is a hard, evidence-triggered gate** (see Required gates).
3. **Craft granularity = per-feature items** (not a monolith) — keeps reuse measurable.
4. **Embedding model = a pinned local model** (deterministic, zero per-call cost),
   recorded in `pins.embedding_model` + craft `validated_against`.
5. **Run B reflection = run-and-discard** (driver-cost parity with A), not skip.

**Invariants (locked):** (i) fresh driver context per task — only the on-disk craft
library persists across tasks (no in-context learning); (ii) reuse = retrieved **and
verified-incorporated** into the TaskSpec (not gameable); (iii) Run A and B share a
**byte-identical pinned driver model + prompt + decoding**, differing only by whether
the craft library accumulates and is retrieved.

## Required gates (hard, not advisories)

These **must** be enforced by T-1.3/T-1.4; a failure blocks proceeding to (or
trusting) the full run:

- **G1 — Pilot-triplet review (before the full run).** Run the first interleaved
  triplet `[E1, M1, H1]`, then review the craft written and the reuse outcomes. If
  craft is weak/over-fit/non-generic **or** reuse ≈ 0 for *retrieval* reasons,
  **bump the driver to Opus 4.8** (re-pin decoding) and/or fix retrieval **before**
  the full 30-task spend. A broken orchestrator must be caught here, not after the run.
- **G2 — Retrieval-precision diagnostic (every run).** Log, per task,
  retrieved-vs-incorporated and an offline retrieval precision/recall on the craft
  that *should* have matched the instance's features. This is what lets a flat reuse
  curve be diagnosed as **retrieval miss vs absent compounding** — the decisive
  false-negative risk (domain.md §6). Required because the control run does **not**
  separate a retrieval miss from genuinely-absent craft value.
- **G3 — Craft-impact / harmful-craft gate (every run).** Track per-craft reuse
  impact (§4) and quarantine harmful items. The control run catches *absent* craft,
  not *harmful* craft.
- **G4 — Effector-cost slope reported alongside total-cost slope (every run).** So a
  rising driver `model_cost_usd` can never mask a falling `effector_cost_usd` signal.
- **G5 — T-1.4 reuse-trend report + no-headroom flag.** T-1.4 must explicitly report
  the reuse trend over positions and **flag the `first-pass ≈ 100% / reuse ≈ 0`
  case** as *no headroom for craft* (the effector is good on its own) — the decisive
  non-compounding signal (domain.md §6), distinct from a craft-driven improvement.

## Consequences

- **Positive:** measures *external orchestration craft* compounding (not in-context
  learning, not code reuse); reuse is per-feature and verified; the control run gives
  a clean treatment−control delta; driver/effector costs are separable; craft is
  model/embedding/effector-version-scoped (ADR-0013).
- **Negative / costs:** a driver model loop adds `model_cost_usd` per task; reflection
  + project-stripping + dedupe are real engineering; vector retrieval adds an
  embedding-model pin.
- **Risks & mitigations (honest residual gaps):**
  - *Reflection quality is the linchpin* — vague/over-fit craft mis-states
    compounding → project-stripping lint, dedupe, signal-gated writes, **pilot-triplet
    review before the full run**.
  - *Reuse over-claim* — the driver could declare incorporation it didn't make →
    verify the craft guidance actually appears in the TaskSpec.
  - *False negative (the decisive risk, domain.md §6)* — retrieval misses make
    reuse≈0 and look like "no compounding" → vector retrieval + a logged retrieval-
    precision diagnostic; the control run only *partly* separates this (it can't
    distinguish a retrieval miss from absent craft value), so the diagnostic is
    required, not optional.
  - *Driver-cost swamping* — if reflection is expensive, *total* cost may not fall
    even if *effector* cost compounds → signal-gated reflection + a cheap driver +
    report the effector-cost slope alongside total.
  - *Driver too capable* — Opus could one-shot good specs without craft (reuse≈0, cost
    low) → that is exactly what the **mandatory control run** catches (B would also be
    low-cost).
- **Follow-ups required:** compiler support for `business_rules` (state_machine,
  cross_field, relationship/`ref`, composite_unique) and multi-filter/multi-sort is a
  **prerequisite for the hard tier** and is not in the spine — needed for T-1.2's
  hard specs and T-1.3. Pin the embedding model + driver model in the run config.

## Alternatives considered

- **No driver (static craft injection)** — rejected: SPEC §4 requires *judgment* to
  compound; static text injection isn't the hypothesis and can't reflect/improve.
- **Persistent driver context across tasks** — rejected: that measures in-context
  learning, not external craft; defeats the experiment.
- **Monolithic evolving playbook** — rejected: collapses the per-id reuse signal and
  bloats context (see §4).
- **Skip reflection in Run B** — rejected: breaks driver-cost parity and conflates
  "no reflection cost" with "no craft benefit" in the delta (see §6).
- **Driver = Opus 4.8 by default** — deferred: start cheaper (Sonnet 4.6); escalate
  only if reflection quality demands it.

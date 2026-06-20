# ADR-0019: Phase −1 validation-harness architecture (measurement spine)

- **Status:** Accepted
- **Date:** 2026-06-19
- **Deciders:** Human operator (Amin), Claude Code (Opus 4.8)
- **Tags:** experiments, phase-minus-1, coding-effector, evals

## Context

ADR-0002 makes Phase −1 the gate that decides whether the rest of the system is
worth building: does orchestration **craft** compound so the Nth `spec → CRUD
service` task is cheaper and better? The protocol, domain, instance manifest, and
result/taskset schemas are pre-registered (`experiments/phase_minus_1/`). What did
not yet exist is the machinery that *executes* them. T-1.1 builds that
measurement spine and proves it end-to-end on the single existing `books`
instance, before any other spec is written or any full run happens.

Two properties dominate the design, because getting either wrong silently
invalidates the experiment:

1. **Held-out integrity** — the effector must receive the spec and never the
   acceptance tests, or it can teach-to-the-test (domain.md §1, SPEC §11A).
2. **A strict oracle** — a lenient contract suite that accepts wrong behaviour
   would manufacture a passing curve. The compiler is the oracle, so it must be
   provably strict.

## Decision

We will build the harness as a standalone package at
`experiments/phase_minus_1/harness/`, **not** part of the shipped `journeyman`
package (it is experiment code), with these components and seams:

- **specschema** — load/validate an instance `*.spec.yaml` into typed objects.
- **payloads** — deterministic valid values + per-constraint boundary probes
  (reject/accept edges); no randomness or wall-clock, so runs are reproducible.
- **compiler** — compile a spec into black-box `httpx` contract cases per
  domain.md §3; it is the **oracle**. It pins the conventions the spec leaves
  open (filter `?field=value`, sort `?sort=field`/`-field`, list returns a JSON
  array, validation envelope `422 {errors:[{field,message}]}`). A single per-suite
  seed counter makes every value unique so unique fields never collide.
- **render** — emit the same cases as a standalone, human-runnable pytest module
  (auditable artifact); single source of truth stays the compiler.
- **reference/service.py** — a spec-driven FastAPI+SQLite service that imports
  **nothing from `harness`**, used two ways: (a) the oracle boots correct and
  deliberately-broken variants in-process to validate the suite; (b) the fake
  effector copies it verbatim into a scaffolded repo (so the repo is standalone —
  held-out integrity).
- **craft** — a flat on-disk craft library (manifests validated against
  `memory/skill-manifest.schema.json`) + a per-task reuse counter. Retrieval is
  keyword/tag for the spine, behind a swappable interface (protocol's vector
  retrieval lands at T-1.3). Flat only: no promotion gate, no dream, no graph.
- **effector** — the stable capability `drive_coding_effector(task) ->
  EffectorSession` behind an `Effector` interface, with a `FakeEffector`
  (deterministic, zero spend; used by all tests/CI) and a `ClaudeCodeEffector`
  (real `claude` CLI, headless `-p --output-format json`; never run by tests).
  The boundary is instrumented — cost, tokens, retries, git diff, transcript —
  and secret-scanned before persistence.
- **runconfig** — pins model ids (`claude-opus-4-8` + fallback
  `claude-haiku-4-5`), the 2026-05-26 token-price snapshot, cache policy, the
  effector command, and retrieval config, recorded into `results.json`.
- **results** — build/validate per-task records and the single-task results
  document against `results.schema.json` (faithful `total_cost = model +
  effector + tool`); `model_cost_usd` is first-class even though the spine driver
  makes no model calls (0 now).
- **scaffolder** — fresh repo per instance from `project/project-template/`.
- **runner** — orchestrates: retrieve craft → scaffold → build TaskSpec (spec +
  craft only) → drive effector → assert held-out → boot `./run.sh` on `$PORT` →
  wait `GET /healthz` (30s) → run contract suite + instance DoD → teardown →
  validated record + a trace-schema `effector_session` span.

**Scope boundaries (deliberately out for T-1.1):** no driver/orchestrator (model
calls, reflection, craft-writing); no second agent, dream, graph, or promotion
gate; no 30-spec corpus, no full Run A / control Run B, no slope/CI/decision —
those are T-1.2/T-1.3. The instance Definition-of-Done is the minimal wired
subset (the instance's own unit tests); the full typed-gate DoD is Phase-0
(T0.7). The orchestrator/craft seam is designed to plug in cleanly at T-1.3.

**Self-test vs experiment (pre-run schema amendment).** Because a spine/smoke run
must never be mistaken for an experimental decision, `results.schema.json` gains a
required `run_kind` discriminator (`experiment` | `harness_selftest`) with a
constraint that a `harness_selftest` can never carry a `pass`/`provisional_pass`
status; the spine's records are `harness_selftest` with `decision.status =
"invalid"` and live under `results/_selftest/`. `harness.results.is_real_
experiment_decision()` is the guard the T-1.4 analysis uses — only `run_kind ==
"experiment"` over the full task set with a control run counts. This is an
*additive, pre-run* amendment to a pre-registered schema (no real experimental run
has started; it strengthens validity rather than changing the design).

## Consequences

- **Positive:** the spine runs `books` end-to-end with zero model spend (fake
  effector), the oracle is proven strict (correct service passes all; a broken
  one fails on exactly its bugs), cost accounting is complete and reproducible,
  and the effector is swappable behind a stable interface.
- **Negative / costs:** the harness duplicates a little CRUD logic in the
  reference service; instance DoD is a subset until T0.7; keyword retrieval could
  bias the reuse signal toward a false negative if used for the real runs — hence
  vector retrieval is mandated for T-1.3.
- **Risks & mitigations:** a lenient oracle → the oracle-validation suite gates
  every change; held-out leakage → the runner asserts no harness/contract code in
  the repo, and the reference service imports nothing from `harness`; hidden cost
  → the boundary is instrumented and `total_cost` is validated complete.
- **Follow-ups required:** wire the Phase-0 DoD gates currently stubbed in this
  repo (`tasks/phase_0_seed/T0_wire_dod_gates.taskspec.json`); design the
  driver/orchestrator and swap in vector retrieval before T-1.3; the single real
  `books` run awaits an explicit operator go-ahead (budget cap $10).

## Alternatives considered

- **Put the harness inside the `journeyman` package** — rejected: it is
  experiment code; shipping it would blur Plane-A/Plane-B and the seed boundary.
- **Run the contract suite only as a generated pytest file (subprocess)** —
  rejected as the primary path: in-process execution yields structured per-case
  metrics; the rendered file is still emitted as an auditable artifact.
- **A books-specific reference service** — rejected: a spec-driven one serves the
  oracle *and* the fake effector for any instance, with little extra code.
- **Skip the fake effector and only test against the real CLI** — rejected: that
  spends money on every CI run and makes tests non-deterministic; the fake keeps
  CI free and reproducible, the real adapter is exercised only on the go-ahead run.

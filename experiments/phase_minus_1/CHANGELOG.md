# Phase −1 pre-registration changelog

Auditable trail of changes to the pre-registered Phase −1 artifacts (`protocol.md`,
`domain.md`, `instances/manifest.md`, `taskset.schema.json`, `results.schema.json`).
The experiment's credibility rests on pre-registration discipline: a change is only
legitimate **before the first experimental run** (`run_kind: experiment`) starts,
should be **additive** where possible, and is recorded here. `protocol_version`
(carried in every `results.json` and `taskset.json`) is bumped on each change.

## T-1.2 corpus build — 2026-06-20 (additive; pre-first-experimental-run; still protocol v2)

- Authored the 30 instance specs (`instances/*.spec.yaml`) and `taskset.json` the
  pre-registration always anticipated, in the manifest's fixed interleaved [E, M, H]
  order. Extended the compiler/oracle (code, not a pre-registered artifact) to the
  four business-rule dimensions named in domain.md §3 / ADR-0020 — state_machine,
  cross_field, relationship (+ a second `related` resource), composite_unique — plus
  multi-filter/multi-sort and an easy-tier basic-list case. See ADR-0021.
- **`computed_field` (manifest H3/H8/H10) and same-resource `overlap` (H2/H9) are
  deferred from the oracle.** They are outside domain.md §3's spec→test mapping; every
  hard instance still declares ≥1 of the four supported, oracle-tested rules, and the
  manifest entities/fields are preserved. No change to `protocol.md`, `domain.md`,
  `instances/manifest.md`, `taskset.schema.json`, or `results.schema.json` semantics;
  `protocol_version` stays **v2**. If the operator wants computed_field/overlap tested,
  they become new pre-registered dimensions (oracle-validated) before the run.

## protocol v2 — 2026-06-19 (additive; pre-first-experimental-run)

- `results.schema.json`: add a **required** `run_kind` discriminator
  (`experiment` | `harness_selftest`), and a constraint that a `harness_selftest`
  run can never carry a `pass`/`provisional_pass` decision. This distinguishes
  harness self-tests (the T-1.1 spine/smoke runs) from real experimental runs so a
  self-test can never be read or aggregated as a decision (ADR-0019; enforced by
  the guard `harness.results.is_real_experiment_decision`).
- **Scope: additive only.** `protocol.md`'s hypothesis, metrics, warm-up/exclusion
  rules, statistical test, and pass/stop criteria are **unchanged**. No
  experimental run had started; no prior *experimental* result is invalidated. The
  only artifacts that existed were T-1.1 harness self-tests, which are relabeled to
  `v2` (metadata only — no measured value changed).

## protocol v1 — initial pre-registration

- `protocol.md`, `domain.md`, `instances/manifest.md`, `taskset.schema.json`, and
  `results.schema.json` as originally committed.

# Phase −1 pre-registration changelog

Auditable trail of changes to the pre-registered Phase −1 artifacts (`protocol.md`,
`domain.md`, `instances/manifest.md`, `taskset.schema.json`, `results.schema.json`).
The experiment's credibility rests on pre-registration discipline: a change is only
legitimate **before the first experimental run** (`run_kind: experiment`) starts,
should be **additive** where possible, and is recorded here. `protocol_version`
(carried in every `results.json` and `taskset.json`) is bumped on each change.

## protocol v3 — 2026-06-20 (additive; pre-first-experimental-run)

- **New oracle dimension: `computed_field`** (the read-side dimension; ADR-0022).
  Adds a spec→test row to `domain.md` §3 for server-derived read-only fields — two
  sub-kinds: same-row (`available = on_hand − reserved`, H8) and aggregate-over-children
  (`balance = Σ transaction.amount_cents`, H3; `total = Σ(line_item.amount_cents ×
  quantity)`, H10). Restores H3/H8 to genuinely-hard and adds derive/aggregate +
  recompute-on-mutation headroom that none of the four write-side rules test.
- Oracle-validated the same way as the other dimensions: a correct two-resource
  reference service passes all cases; the surgical `BUG_WRONG_COMPUTED` fails on EXACTLY
  the `computed_field` cases on the real H3/H8/H10 (`test_oracle_corpus.py`). The
  decisive case is **recompute-on-mutation** (add/mutate/delete a child → re-GET →
  value refreshes), which exposes static-cache implementations.
- **Scope: additive only.** `protocol.md`'s hypothesis/metrics/warm-up/criteria are
  unchanged; the four prior dimensions and the corpus order/pilot triplet are
  untouched. `overlap` (H2/H9) stays deferred. `protocol_version` bumped **v2 → v3**
  (carried in `taskset.json` and every new `results.json`); H3/H8/H10 gain the
  `rule:computed_field` feature_tag and updated `expected_contract_tests_min`. No
  experimental run had started; no prior experimental result is invalidated. The
  T-1.1 `results/_selftest/` artifacts remain labelled v2 (historical; not regenerated).

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

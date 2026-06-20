# ADR-0021: Phase −1 business-rule compiler extension + the 30-instance corpus

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator (Amin), Claude Code (Opus 4.8)
- **Tags:** experiments, phase-minus-1, compiler, oracle, corpus

## Context

ADR-0019 built the T-1.1 measurement spine and proved the oracle strict on the
single worked `books` (medium) instance. ADR-0020 named, as a hard prerequisite for
the hard tier (and T-1.3), "compiler support for `business_rules` (state_machine,
cross_field, relationship/`ref`, composite_unique) and multi-filter/multi-sort."
T-1.2 authors the full 30-instance corpus (`instances/manifest.md`) and extends the
compiler/oracle so the easy and hard tiers are tested as strictly as the medium one.

Two pre-registration constraints bound the design. (1) **Held-out integrity**: the
instance spec — now including its business rules and any second resource — drives
the effector; the compiled contract suite stays the harness's private oracle and is
never handed to the effector. (2) **A strict oracle is load-bearing**: a lenient
business-rules oracle would silently invalidate the hard tier, which is exactly where
the experiment's craft headroom lives. domain.md §3's spec→test mapping table
enumerates test rows for exactly four business-rule dimensions; §2/§4 additionally
list `computed_field` as a permissible rule kind, and the manifest's prose mentions
`computed_field` (H3/H8/H10) and same-resource `overlap` (H2/H9).

## Decision

We will extend the compiler, the spec schema, the reference service, and the
effector-facing TaskSpec composer to support **exactly the four pre-registered
business-rule dimensions** — `state_machine`, `cross_field`, `relationship` (with an
optional second `related` resource via `ref`), and `composite_unique` — plus
**multi-filter conjunction**, **composite multi-sort**, and a **basic easy-tier list**
case. Each new dimension is **oracle-validated the same way the medium compiler was**:
a correct reference service passes every case, and a surgically-broken variant fails
on EXACTLY that dimension's cases (`tests/integration/test_oracle_list_ext.py`,
`test_oracle_business_rules.py`, and — on the real corpus — `test_oracle_corpus.py`).

Specifics:

- **Spec schema** (`harness/specschema.py`): typed `StateMachineRule`,
  `CrossFieldRule`, `RelationshipRule`, `CompositeUniqueRule` (via `business_rules_of`)
  plus an optional top-level `related` second resource. The raw `business_rules` list
  is preserved for serialization to the effector/reference service.
- **Reference service** (`harness/reference/service.py`): refactored to serve a
  primary and an optional `related` resource over shared SQLite storage; field-based
  rules apply to their **owning** resource (so `composite_unique` can live on a child,
  e.g. playlists' tracks). New surgical bug flags: `BUG_ALLOW_ILLEGAL_TRANSITION`,
  `BUG_SKIP_CROSS_FIELD`, `BUG_SKIP_PARENT_CHECK`, `BUG_SKIP_COMPOSITE_UNIQUE`,
  `BUG_IGNORE_SECONDARY_FILTER`, `BUG_IGNORE_SECONDARY_SORT`, `BUG_LIST_NOT_ARRAY`.
- **Compiler** (`harness/compiler.py`): the `Api` builds create payloads that satisfy
  the spec's rules by construction — state-machine fields start at `initial`
  (server-set), cross-field constraints are satisfied, and `ref` fields point at a
  real lazily-created parent — so the standard CRUD cases never trip a rule by
  accident; rule-governed fields are excluded from generic partial-update targets.
- **Conveyance** (`harness/taskspec.py`, `harness/runner.py`): the deterministic
  TaskSpec and `spec.json` carry the business rules and the second resource (structured
  + a prose status-code contract) — "specs drive the effector" for the hard tier —
  while the contract suite stays out of both.
- **Corpus**: 30 specs under `instances/` and `taskset.json` in the manifest's fixed
  interleaved [E, M, H] order, validating `taskset.schema.json`.

**Scope boundary — `computed_field` and `overlap` are deferred from the oracle.**
They are outside domain.md §3's test mapping and ADR-0020's named compiler-support
list, so adding them would expand the pre-registered oracle surface and is an
explicit operator/ADR decision rather than implicit T-1.2 scope. Every hard instance
still declares ≥1 of the four supported, oracle-tested rules (most declare two), and
the manifest entities/fields stay faithful (e.g. inventory keeps `on_hand`/`reserved`,
invoices keep line items). The manifest→spec realization map is recorded in the spec
file headers and the T-1.2 design note. This is an additive, pre-first-run change; the
hypothesis, metrics, warm-up, and pass/stop criteria are unchanged (CHANGELOG protocol
note).

## Consequences

- **Positive:** the easy and hard tiers are now tested as strictly as medium; the
  oracle's strictness is proven per-dimension on the real corpus, not just fixtures;
  the reference service doubles as a correct two-resource fake effector, so the full
  pipeline runs green end-to-end on a hard relationship spec with zero spend.
- **Negative / costs:** the reference service is larger (two resources, six new bug
  flags); the compiler's `Api` now creates parent rows and reasons about rule-governed
  fields; payload generation must satisfy cross-field rules by construction.
- **Risks & mitigations:** a lenient hard-tier oracle → per-dimension surgical-bug
  tests over the real specs (`test_oracle_corpus.py`) gate every change;
  held-out leakage of a richer spec → the TaskSpec/`spec.json` conveyance is tested to
  contain the rules but not the suite, and the runner's `assert_held_out` still scans
  the effector repo; reduced hard-tier richness from deferring computed_field/overlap →
  flagged here and in the final report for an operator decision before T-1.3.
- **Follow-ups required:** if the operator wants `computed_field`/`overlap` tested,
  add them as new pre-registered dimensions (oracle-validated, CHANGELOG note) before
  the run. T-1.3 wires the driver/orchestrator and vector retrieval (ADR-0020) over
  this corpus; the feature_tags in `taskset.json` are the retrieval keys.

## Alternatives considered

- **Implement all six manifest dimensions (add computed_field + overlap)** — rejected
  for T-1.2: expands the pre-registered §3 oracle surface beyond the named four without
  operator sign-off; deferred as an explicit follow-up instead of silent scope creep.
- **Author hard specs that diverge from the manifest entities** — rejected: the
  manifest is the fixed spec source; entities/fields stay faithful, only the
  untested-rule *realization* is deferred.
- **Tie business rules only to the primary resource** — rejected: H5's
  `composite_unique` is naturally on the child (a track's position within a playlist),
  so rules apply to their owning resource.
- **Run the contract suite as the effector's tests** — rejected (as in ADR-0019):
  destroys held-out integrity; the suite remains private to the harness.

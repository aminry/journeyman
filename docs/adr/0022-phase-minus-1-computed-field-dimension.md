# ADR-0022: Phase −1 computed_field dimension (read-side derive/aggregate oracle)

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator (Amin), Claude Code (Opus 4.8)
- **Tags:** experiments, phase-minus-1, compiler, oracle, computed-field

## Context

ADR-0021 scoped the T-1.2 compiler to the four business-rule dimensions named in
`domain.md` §3 (state_machine, cross_field, relationship, composite_unique) and
**deferred** `computed_field` and `overlap`, flagging both for an explicit operator
decision before the first experimental run. The operator's decision: **promote
`computed_field`; keep `overlap` deferred.**

The four shipped dimensions are all *write-side* — they reject or constrain what the
client sends. None tests the *read-side*: a server that **derives** a field's value
rather than storing it. That is real, common CRUD headroom — and it is where the
subtle, oft-wrong behaviour lives: recomputing a derived value as its inputs change
(an operand is edited; a child row is added or removed). Promoting `computed_field`
restores H3 (accounts) and H8 (inventory) to genuinely-hard (their manifest headline
feature) and gives the hard tier a dimension a static-cache implementation fails.

This is an additive, pre-first-run change: no experimental run has started.

## Decision

We will add `computed_field` as a fifth pre-registered, oracle-validated business-rule
dimension, with two sub-kinds, and bump `protocol_version` v2 → v3.

- **Schema** (`harness/specschema.py`): `ComputedFieldRule(field, compute, operands,
  child, child_fields)`. `compute ∈ {subtract, sum_children}`:
  - `subtract` — same-row: `field = operands[0] − operands[1]` (H8 `available =
    on_hand − reserved`).
  - `sum_children` — aggregate: `field = Σ`, over every `child` row referencing this
    parent, of the product of `child_fields` (H3 `balance = Σ transaction.amount_cents`;
    H10 `total_cents = Σ(line_item.amount_cents × quantity)`).
  The computed field is declared `readonly` (server-managed, client cannot set it).
- **Reference service** (`harness/reference/service.py`): a computed field is **never
  stored** — `_apply_computed` derives it live on every read (create response, GET,
  PATCH response, and each list row), so it is never stale. Reuses the two-resource
  storage + `_owner` machinery from ADR-0021; the child→parent ref is found by the
  child's `ref` field. Surgical bug `BUG_WRONG_COMPUTED` returns a wrong/stale value
  (correct + 1).
- **Compiler** (`harness/compiler.py`): `_computed_field_cases` emits, per rule —
  same-row: `value`, `client_ignored`, `recompute` (PATCH an operand → re-GET);
  aggregate: `initial` (no children → 0), `aggregate` (Σ over created children),
  `recompute` (**add then delete a child → re-GET → value refreshes**),
  `client_ignored`. Computed fields are excluded from the generic "server-managed field
  populated" checks (they can legitimately be 0) — the dedicated cases verify them.
- **Pre-registration**: `domain.md` §3 gains a `computed_field` row (§2/§4 already
  enumerate the kind); CHANGELOG records protocol v3; `taskset.json` is v3 with
  `rule:computed_field` on H3/H8/H10 and refreshed `expected_contract_tests_min`.

**Scope boundary:** `computed_field` only. The four prior dimensions, the corpus order,
the pilot triplet (positions 1–3: notes/books/orders), and `overlap` (H2/H9, still
deferred) are **untouched**. Held-out integrity is unchanged: the spec — including the
computed rule — drives the effector via the TaskSpec/`spec.json`; the contract suite
stays the harness's private oracle.

## Consequences

- **Positive:** the hard tier now tests read-side derive/aggregate and the
  recompute-on-mutation path (the static-cache headroom); H3/H8/H10 match their manifest
  headline features; same per-dimension oracle rigor (correct passes all; the surgical
  bug fails exactly the computed_field cases on the real specs).
- **Negative / costs:** the reference service computes aggregates on every read
  (O(children) per parent row — fine at experiment scale); one more protocol version to
  track; H10 carries both a client-set `amount_cents` (sortable) and a computed
  `total_cents`.
- **Risks & mitigations:** a stale/lenient computed oracle → `BUG_WRONG_COMPUTED`
  per-dimension strictness on the real H3/H8/H10 + an explicit add/delete-child recompute
  case; held-out leakage of the richer spec → the TaskSpec conveys the rule but not the
  suite (existing held-out tests still hold).
- **Follow-ups required:** none for computed_field. `overlap` remains deferred (a future
  ADR if promoted). T-1.3 orchestrator proceeds against fakes (separate session).

## Alternatives considered

- **Keep computed_field deferred** — rejected by the operator: leaves H3/H8 thin and
  the read-side dimension untested.
- **Store the computed value and trust it** — rejected: stale storage is the exact bug
  the dimension must expose; deriving live (and a surgical wrong-value bug) is what makes
  the recompute case meaningful.
- **Promote overlap too** — rejected (out of scope this PR): overlap stays deferred.
- **Model aggregate without reusing the relationship/second-resource machinery** —
  rejected: H3/H10 already declare the parent↔child relationship; the aggregate reuses
  the child ref and two-resource storage from ADR-0021.

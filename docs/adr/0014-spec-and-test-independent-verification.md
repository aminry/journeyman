# ADR-0014: Independent verification of specs and acceptance tests

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** architecture, verification, coding-effector, quality

## Context

The effector contract accepts output only when the Definition-of-Done gate passes
(ADR-0005) — but the acceptance tests are authored from a TaskSpec the agent
itself wrote, and the gate verifies the code against *those* tests. If the spec
misencodes operator intent, or the tests assert the wrong property, the system
produces confidently-wrong "verified" output and every gate reads green. The MAST
taxonomy finds **specification problems (~42%) and verification gaps (~21%)** are
the two largest production failure classes — together the majority of breakdowns.
The spec's own principle forbids a "self-judge" for unverifiable work, yet
authoring a spec and its tests is exactly such a judgment. The verified-out
contract is only as trustworthy as the spec and tests it verifies against, and
those were unverified.

## Decision

Add **independent verification of the spec and acceptance tests**, risk/cost-gated:

- For any task above an operator-set risk/cost threshold, or that is
  irreversible, externally visible, or a Phase-2 product change: the TaskSpec and
  its acceptance tests are reviewed by a **different source class** (a different
  model family or a human) **before** the effector runs, checking that the tests
  encode the stated intent and include adequate negative cases. Recorded as a
  `verification` span.
- For **all** effector tasks: acceptance tests must include negative/failure and
  property/metamorphic cases (not happy-path only), and the TaskSpec must carry a
  short **intent restatement** that can be checked against the original goal.
- The instance that authors the tests may not be the instance that reviews them.

## Consequences

- **Positive:** closes the dominant MAST failure surface; the trust anchor (the
  tests) is itself checked; cheap tasks stay fast.
- **Negative / costs:** added latency/cost on gated tasks; requires a second
  source class to be available.
- **Risks & mitigations:** threshold set too high → operator-tuned and revisited
  (SPEC §23); reviewer rubber-stamps → ADR-0016 automation-bias controls apply to
  this review too.

## Alternatives considered

- **Review every task** — rejected: unjustified cost on trivial mechanical work.
- **Trust the DoD gate alone** — rejected: the gate cannot detect a faithful
  implementation of a wrong spec.
- **Human-only review of all specs** — rejected: does not scale; reserve humans
  for the gated tier and use a different model family below it.

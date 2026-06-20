# ADR-0017: Phase −1 statistical rigor (mandatory control + pre-specified test)

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** process, risk, evals, experiment

## Context

Phase −1 greenlights the entire architecture on whether cost-per-task bends over
~30 tasks (ADR-0002). The protocol already pre-registers pins, warm-up, and
exclusions, and defines a control run (Run B, memory disabled). But n ≈ 25 after
warm-up is thin and autocorrelated; "slope is negative" was qualitative with no
minimum detectable effect, no variance/significance criterion, and the control —
the only thing that attributes a bend to *craft* rather than caching, task
ordering, or effector drift — was **optional**.

## Decision

Strengthen the pre-registered protocol (`experiments/phase_minus_1/protocol.md`,
`results.schema.json`):

- The **control run (Run B) is mandatory** for a full "pass." A single-arm run may
  only yield a **provisional, explicitly lower-confidence** decision, recorded as
  such.
- **Pre-specify the statistical test:** a minimum detectable slope (effect size)
  the run is powered to detect; an autocorrelation-aware estimate (regression with
  lagged-residual handling, or a pre-registered nonparametric trend test); a
  reported slope **confidence interval**; and the **treatment-minus-control
  delta** as the primary evidence that craft, not environment, drove the change.
- `results.schema.json` **requires** these fields (control presence,
  treatment-vs-control delta, minimum detectable slope, significance/CI) for a
  `pass` decision.

## Consequences

- **Positive:** the foundational go/no-go is causal and powered, not a noisy
  eyeball; a flat-but-noisy curve cannot masquerade as a bend.
- **Negative / costs:** the mandatory control roughly doubles Phase −1 compute
  (still a few hundred dollars) and adds modest analysis.
- **Risks & mitigations:** single-domain external validity is unchanged — stated
  as a residual in the decision; underpowered at n = 30 → the effect-size
  pre-registration makes that explicit rather than hidden, and the operator can
  extend the task count.

## Alternatives considered

- **Keep the control optional** — rejected: without it, a bend cannot be
  attributed to craft rather than caching/ordering/effector drift.
- **Qualitative slope only** — rejected: invites confirmation bias on the riskiest
  decision in the program.

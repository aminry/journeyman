# ADR-0016: Scalable human oversight (sampling, automation-bias, novel-action escalation)

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** governance, safety, oversight

## Context

The safety model leans on humans exactly where load scales with throughput — the
approval queue, spot-checks on self-modification commits, and the human judge for
unverifiable work. As task volume rises (the point of the system), a **fixed-count**
spot-check reviews a *shrinking fraction* of commits, and the documented failure
mode is **automation bias / rubber-stamping**: reviewers defer to confident
machine output, especially when they believe the system knows more than they do.
Queue-overflow behavior (block vs auto-proceed) was unspecified.

## Decision

Make oversight scale and resist automation bias:

- **Risk-weighted fractional sampling.** Spot-checks are a *fraction*, not a fixed
  count: sampling probability rises with action risk, novelty, blast radius, and
  cost; high-risk classes are always reviewed.
- **Bounded review rate + fail-closed overflow.** A maximum human-review rate is
  declared; if the approval/review queue exceeds capacity, high-impact work
  **blocks and escalates** — it does not auto-proceed.
- **Anti-automation-bias step.** For sampled self-modifications and high-impact
  approvals, the reviewer records an independent judgment *before* seeing the
  agent's rationale; the agent surfaces its own uncertainty and any dissenting
  signal.
- **Novel/ambiguous-action escalation.** A registered tool invoked with parameters
  that do not match a known-safe pattern, or any action whose risk class is
  ambiguous, **escalates to approval** rather than executing. (The tool registry
  is already `default_action: deny` for *unregistered* tools; this closes the
  *registered-but-used-novelly* case.)

Sampling weights, the review-rate ceiling, and escalation patterns are
operator-set, human-reviewed, and logged (SPEC §23).

## Consequences

- **Positive:** oversight quality no longer silently degrades with volume;
  rubber-stamping is structurally discouraged; queue overflow is safe by default.
- **Negative / costs:** more reviews on high-risk/novel actions; throughput is
  bounded by review capacity *by design*.
- **Risks & mitigations:** sampling weights gamed → operator-set, reviewed,
  logged; residual reviewer fatigue → fractional + risk-weighting concentrates
  scarce attention where it matters most.

## Alternatives considered

- **Fixed-count spot-checks** — rejected: the reviewed fraction trends to zero as
  volume grows.
- **Trust model confidence to route approvals** — rejected: confidence is poorly
  calibrated (SPEC §1).
- **Auto-proceed on queue overflow** — rejected: trades safety for throughput at
  the worst possible moment.

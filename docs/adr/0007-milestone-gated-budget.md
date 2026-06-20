# ADR-0007: Milestone-gated budget + cost-per-task viability gate

- **Status:** Accepted
- **Date:** {{YYYY-MM-DD}}
- **Deciders:** {{WHO_DECIDED}}
- **Tags:** governance, economics

## Context

The work loop is a token multiplier (reflection, dreaming, retrieval, effector sessions). Without economic discipline the budget can evaporate before any compounding appears, and an autonomous system with money needs a circuit breaker.

## Decision

Operate under a **budget ledger** with a **hard daily/weekly cost ceiling** and a **cost-per-task viability gate**: if cost-per-completed-task is not trending down while quality holds by week N, halt and escalate. Verified milestones and **real revenue** refill the budget (the faucet); a budget floor trips a circuit breaker that halts and escalates. Real money is the system's "energy."

## Consequences

- **Positive:** the economics are forced to close; runaway loops are bounded; a natural circuit breaker exists.
- **Negative / costs:** some genuinely-improving runs may halt on a strict gate and need human re-funding.
- **Risks & mitigations:** premature halts — mitigated by operator-tuned thresholds and a milestone top-up schedule.

## Alternatives considered

- **Unbounded budget, monitor manually** — rejected: token multiplication makes silent overspend likely; cf. real-world autonomous-business experiments that lost money.

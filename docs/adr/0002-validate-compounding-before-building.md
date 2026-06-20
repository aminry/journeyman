# ADR-0002: Validate compounding before building (Phase −1 gate)

- **Status:** Accepted
- **Date:** {{YYYY-MM-DD}}
- **Deciders:** {{WHO_DECIDED}}
- **Tags:** process, risk

## Context

The entire architecture is justified by one claim: competence compounds, so the Nth task in a domain is cheaper and better than the 1st. This is demonstrated by skill-library work in closed domains, but not yet for open-ended software work. Building the full system (memory, dream, governance, effector orchestration) before testing this risks an elaborate machine around an effect that may not exist.

## Decision

Before building the seed, run a **Phase −1** experiment: one agent, a flat skill/craft library, a coding effector, no dream/graph/second-agent. Run ~30 real tasks in one narrow verifiable domain and measure whether cost-per-task falls while quality holds and reuse is real. Proceed to Phase 0 only if the curve bends. A standing cost-per-task viability gate keeps this test running forever in production.

## Consequences

- **Positive:** the riskiest assumption is falsified cheaply, before large investment.
- **Negative / costs:** a few hundred dollars of compute and a short delay before "real" building.
- **Risks & mitigations:** measuring the wrong curve — mitigated by measuring orchestration-craft reuse and effector retries, not code-snippet reuse (ADR-0005).

## Alternatives considered

- **Build the seed first, measure later** — rejected: discovers a flat curve only after the expensive part is built.

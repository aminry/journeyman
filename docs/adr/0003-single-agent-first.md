# ADR-0003: Single agent first; defer multi-agent

- **Status:** Accepted
- **Date:** {{YYYY-MM-DD}}
- **Deciders:** {{WHO_DECIDED}}
- **Tags:** architecture, coordination

## Context

Multi-agent LLM systems frequently fail on coordination (role/task ambiguity, agents overstepping, step-repetition loops, lost context) and often show minimal gains over a single strong agent; empirical taxonomies find these are architectural failures not fixed by better base models. Coordination is a real, recurring cost.

## Decision

The seed is a **single agent**. Multi-agent coordination (`coordination/`) is a deferred placeholder, built only when a specific task provably cannot be done by one agent. When earned, it must use addressed (non-broadcast) messaging, blackboard-async coordination, message budgets, and contract-net delegation.

## Consequences

- **Positive:** avoids the largest known failure surface; simpler, cheaper, more legible.
- **Negative / costs:** no parallel-agent throughput until earned.
- **Risks & mitigations:** the agent↔coding-effector seam is itself a two-party surface — mitigated by the spec-in/verified-out contract (ADR-0005).

## Alternatives considered

- **Role-based multi-agent team from the start (CEO/coder/tester)** — rejected: this is precisely the pattern with documented coordination failures and minimal measured benefit.

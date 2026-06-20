# ADR-0004: Vector-first agent memory; defer agent graph memory

- **Status:** Accepted
- **Date:** {{YYYY-MM-DD}}
- **Deciders:** {{WHO_DECIDED}}
- **Tags:** architecture, memory

## Context

Retrieval quality, not storage format, is the bottleneck in agent memory — most apparent hallucinations are retrieval misses. Graph memory adds write complexity and read latency for benefits (multi-hop, temporal) most tasks don't need. Mature vector/tiered memory runtimes already exist.

## Decision

Agent memory (Plane B) is **vector/tiered-first**: episodic log + semantic/summary store, adopting an existing runtime where sensible. **Agent-level graph memory is deferred** until a task genuinely needs relational/temporal recall a vector store cannot serve. Note: the *code* knowledge graph in Plane A is **not** deferred — codebases have genuine graph structure and it is justified per project from day one.

## Consequences

- **Positive:** lower latency and complexity; effort goes to retrieval ranking, which is the real lever.
- **Negative / costs:** multi-hop agent-memory queries unavailable until earned.
- **Risks & mitigations:** retrieval misses — mitigated by investing early in retrieval ranking (Phase 1 backlog).

## Alternatives considered

- **Knowledge graph per agent from the start** — rejected as over-engineering for the seed; resolved by placing graphs where they're justified (the project code graph), not in agent memory.

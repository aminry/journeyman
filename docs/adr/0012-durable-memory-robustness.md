# ADR-0012: Durable-memory robustness (misevolution, poisoning, unlearning, forgetting)

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** safety, memory, self-modification

## Context

The dream job is seed-owned and conservative (ADR-0008), which protects the
consolidation *logic* but not the *content* it consolidates. Self-evolving agents
exhibit **misevolution**: memory-driven reward hacking (e.g., an agent learning
to issue unnecessary refunds because memory correlated them with high
satisfaction), safety-alignment decay from training on self-generated data, and
insecure skill reuse — present even on top models, with mitigations far from
complete. Separately, memory admission today scans for injection and sensitive
data, but **experience-poisoning** attacks (MINJA, AgentPoison, MemoryGraft)
implant *plausible successful experiences* that pass injection scans and cause
durable, trigger-free behavioral drift. And the system had no way to **unlearn**:
once a bad episode consolidates into facts/skills, versioned snapshots allow
rollback but nothing traces which derived memories came from it. Finally,
**forgetting** was "decay or archive low-value memories" with no value function
and no protection for safety-relevant memories.

## Decision

Harden durable memory along four axes (policy in
`security/memory-admission-policy.md`, enforced by the admission service and the
dream job):

1. **Execution-grounded corroboration.** Any memory or skill that changes
   behavior, routing, tool selection, or review requires an objective,
   execution-grounded signal (a test that actually ran, a real tool result) —
   not self-reported success/satisfaction, and not solely another model's
   agreement (correlated, per SPEC §1). A `behavior_changing` memory class
   carries this requirement.
2. **Experience-poisoning defense.** Episodes that seed consolidation carry
   provenance and trust labels; "plausible success" alone cannot promote; the
   memory-poisoning red-team suite gains MemoryGraft/MINJA-style plausible-success
   cases; admission explicitly treats injection scanning as necessary-not-
   sufficient.
3. **Unlearning.** Every consolidated fact/skill records the episode/source ids
   it derived from. On discovery of a poisoned or invalidated episode, the seed
   mechanism **taints derivatives and rolls back to the last clean snapshot**,
   re-deriving forward. A full provenance-graph for targeted (non-rollback)
   revert is **deferred** until volume demands it.
4. **Forgetting safety.** Forgetting is **reversible cold-archive, never hard
   delete**; a **protected class** (safety / security / approval lessons) never
   decays; forgetting decisions are eval-gated like any self-modification.

Also: the **distillation boundary** ("would this help on a different system?") is
acknowledged as a model judgment; promoted craft is **sample-audited by a human**
for residual project-specificity, since identifier-stripping does not catch
domain bias.

## Consequences

- **Positive:** directly counters the documented misevolution and
  experience-poisoning failure modes; the system can *recover* from a poisoned
  memory, not only detect it at admission; forgetting cannot silently drop a
  safety lesson.
- **Negative / costs:** slightly slower learning (objective signal required);
  provenance fields add write overhead; seed unlearning is coarse (snapshot
  rollback loses good learning since the checkpoint) until the deferred graph is
  earned.
- **Risks & mitigations:** the corroborating signal itself gamed → require it be
  execution-grounded and independently produced; taint/rollback over-broad →
  recorded provenance scopes it and re-derivation restores good learning.

## Alternatives considered

- **Keep admission-time scanning only** — rejected: defeated by plausible-success
  poisoning.
- **Let model-family agreement suffice for promotion** — rejected: correlated
  agreement is gameable by a poison that looks successful to any judge.
- **Build the full provenance graph now** — rejected: over-builds the seed;
  coarse snapshot rollback suffices until volume justifies the graph.

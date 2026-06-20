# ADR-0009: Require assurance artifacts and security gates

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Codex
- **Tags:** security, governance, evals, observability

## Context

The architecture already has strong principles: validate compounding before
building, stay single-agent until proven otherwise, treat the coding effector as
an untrusted tool, separate project and agent memory, and gate self-modification
with regression tests. Those principles are necessary but not enough. Agentic
systems fail at the boundaries: untrusted content becomes instructions, tool
calls exceed authority, memory persists hostile payloads, approvals are vague,
evals are weakened, and trace logs silently collect secrets.

We need concrete, versioned artifacts that turn those principles into reviewable
and enforceable controls before Phase 0 begins.

## Decision

We will require a seed set of assurance artifacts:

- a threat model;
- a pre-registered Phase -1 protocol and result schemas;
- tool authorization policy;
- parameter-bound approval policy and approval-record schema;
- untrusted-content pipeline;
- memory-admission policy;
- data-classification policy;
- eval governance and red-team suites;
- trace schema, redaction policy, and retention policy;
- coding-effector contract and sandbox profile;
- Definition-of-Done gates that reference these artifacts.

These artifacts are part of the architecture contract, not optional background
docs. Phase -1 cannot be accepted, Phase 0 cannot start, and self-modification
cannot land unless the relevant artifact exists and the gate can produce
evidence.

## Consequences

- **Positive:** security and evaluation controls are explicit, reviewable, and
  testable. Future agents do not have to infer policy from prose. The riskiest
  boundaries now have schemas, policies, or red-team fixtures.
- **Negative / costs:** more files must be maintained, and early implementation
  has additional CI/policy work before feature work can proceed.
- **Risks & mitigations:** stale artifacts can become false reassurance. Mitigate
  by making changes to tools, memory, retrieval, prompts, evals, approvals, and
  traces update the relevant artifacts and run matching regression suites.
- **Follow-ups required:** implement the CI runners behind the declared
  `ci/definition_of_done.yaml` gate types during Phase 0.

## Alternatives considered

- **Keep the principles only in `docs/SPEC.md`** - rejected because prose does
  not enforce tool authorization, memory admission, approval binding, or trace
  redaction.
- **Build the controls later after the seed works** - rejected because these are
  seed safety boundaries. Retrofitting them after memory, tools, and traces exist
  risks contaminating the system before the controls are active.
- **Use one generic security checklist** - rejected because the failure modes are
  boundary-specific. Tool policy, memory admission, approval binding, eval
  governance, and trace retention need separate contracts.

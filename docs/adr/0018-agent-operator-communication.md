# ADR-0018: Agent↔operator communication contract (human interface)

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** governance, safety, human-in-the-loop, observability

## Context

The design leans heavily on the human — approvals, the judge for unverifiable
work, spot-checks, milestone re-funding, the kill switch. Yet only **one**
agent→human direction is rigorously specified: the approval queue
(`approval-policy.md`, `approval-record.schema.json`). Escalation, milestone
review, and human-as-judge are specified as state-machine triggers and roles, not
as a communication protocol; there is no message schema for them, no push
status/notification, and — notably — **no channel for the agent to ask a
clarifying question before acting on an ambiguous spec**, even though
specification ambiguity is the largest documented agent-failure class (ADR-0014).
The threat model has the operator→agent *input* boundary and the
approval→execution boundary, but no general agent→operator *output* boundary,
which also leaves the manipulated-summary vector (a human deciding on a poisoned
agent summary) ungeneralized.

## Decision

Add a unified **agent↔operator communication contract** that generalizes the
approval channel to all agent→human messages:

- `security/human-comms.schema.json` — an envelope for every agent→human message
  with a `kind` enum: `approval` | `escalation` | `milestone_claim` |
  `judge_request` | `clarifying_question` | `status`; common fields for
  `evidence_refs`, target/urgency, expiry/SLA, no-response behavior, and
  untrusted-content labeling; kind-specific payloads. Approvals still bind to
  `approval-record.schema.json`.
- `security/human-comms-policy.md` — anti-manipulation (evidence-linked; untrusted
  content labeled and never an instruction), a **bounded clarifying-question
  path** (disambiguates the operator's own spec only; the answer is operator
  instruction; rate/budget-limited), routing/urgency/SLA, and **fail-closed
  liveness** on no-response for high-impact kinds.
- A `human_comms` trace span so these are audited like approvals.

Seed-light: the schema and policy land now; the medium/UI (queue, chat, email) is
an operator choice (SPEC §23).

## Consequences

- **Positive:** the load-bearing human boundary is contracted in *both*
  directions; ambiguous specs can be resolved by asking (the cheap fix for the top
  failure class); the manipulated-summary vector is bounded everywhere, not just at
  approvals; no-response liveness is defined.
- **Negative / costs:** more surface; a clarifying channel risks becoming a chat
  back-channel if unbounded.
- **Risks & mitigations:** clarifying questions reopening the instruction-source
  boundary → they disambiguate the operator's *own* spec only, cannot import
  untrusted instructions, and are rate/budget-limited; selecting an
  agent-presented option grants no new authority (a high-impact action still needs
  its approval record).

## Alternatives considered

- **Keep only the approval channel** — rejected: escalation/judge/milestone stay
  unstructured, there is no way to ask before failing, and no liveness rule.
- **A free-form operator chat** — rejected: reopens the instruction-source
  boundary and the manipulation surface the approval discipline closes.

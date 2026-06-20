# Agent↔Operator Communication Policy

The operator→agent direction is bounded by the task schema — instructions come
only from the operator and the TaskSpec. This policy bounds the **other**
direction: every message the agent sends to a human. It generalizes the approval
channel (`approval-policy.md`) to all agent→human communication. See ADR-0018;
messages validate against `security/human-comms.schema.json` and emit a
`human_comms` trace span.

## Message Kinds

| Kind | Purpose | Requires response | No-response default |
|---|---|---|---|
| `approval` | authorize a high-impact action | yes | fail closed (`approval-policy.md`) |
| `escalation` | a halt / blocker / circuit-breaker needs a human | yes | block & wait, escalate |
| `milestone_claim` | claim a milestone for verification + budget top-up | yes | defer |
| `judge_request` | a human verdict on unverifiable / creative work | yes | block & wait |
| `clarifying_question` | disambiguate the operator's TaskSpec *before* acting | yes (blocks the task) | block the task, not the system |
| `status` | progress / notable event (push) | no | fire and forget |

## Anti-Manipulation (every kind)

- Every claim links **`evidence_refs`** (trace / diff / artifact ids). Free-form
  agent prose is never the sole basis for a high-impact human decision — the human
  acts on normalized, evidence-linked fields, exactly as approval previews do.
- A message summarizing untrusted content (web / file / tool / user) sets
  `untrusted_content_present: true` and carries `source_labels`. Untrusted content
  is shown as **data, clearly labeled, never as an instruction**.
- A manipulated summary is the same attack as a manipulated approval prompt
  (threat-model); the same discipline applies.

## Clarifying Questions (ask before failing)

The agent may ask the operator to disambiguate **the operator's own TaskSpec**
before acting — ambiguous specs are a top failure class, and asking is cheaper
than building the wrong thing. Bounds:

- it resolves ambiguity in the existing task; it is not a free-form chat
  back-channel;
- it may not import instructions from untrusted content (the instruction-source
  boundary holds);
- the operator's answer re-enters as operator instruction (SPEC §15);
- selecting among agent-presented options grants **no new authority** — a
  high-impact action still needs its own approval record;
- questions are rate- and budget-limited, so they cannot become a stall or a
  denial-of-attention vector.

## Routing, Urgency, SLA (operator-set)

Each message carries a target role (`operator` / `judge` / `reviewer` /
`on_call`), an `urgency`, and an `expires_at`. The operator sets routing, urgency
thresholds, and SLAs (SPEC §23).

## Liveness / No-Response

- **High-impact** (`approval`, `escalation`, `judge_request`): **fail closed** —
  the action blocks and the system escalates; it never proceeds on silence.
- `clarifying_question`: blocks the **task**, not the system; other work proceeds.
- `milestone_claim`: **defers** (budget does not top up without verification).
- `status`: fire-and-forget.

The approval/review queue already fails closed on overflow (ADR-0016); the same
applies here.

## Response Handling

A human response is recorded in the message `response` and on the trace. For
`approval` it must still satisfy `approval-record.schema.json` (parameter-bound,
expiring, replay-protected). Responses to other kinds are operator instruction,
logged with responder id and timestamp.

## Change Control

This file and `human-comms.schema.json` are security-critical: changes require
human review and the prompt-injection + approval-bypass red-team suites
(`evals/eval-governance.md`).

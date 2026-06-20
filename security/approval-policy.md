# Approval Policy

The model cannot approve its own actions. High-impact execution requires a
valid approval record that is bound to the exact action being executed.

## Risk Classes

| Class | Examples | Approval |
|---|---|---|
| Low | read files, query memory, run deterministic local checks | no approval |
| Medium | edit local files, write memory, run tests, build artifacts | no approval unless policy escalates |
| High | send external messages, broad shell, networked effector, credential use | human approval |
| Critical | deploy, publish, payment, contract, production delete, credential mutation, kernel/dream/guard change | human approval plus step-up authentication |

## Approval Binding

An approval is valid only for the exact action previewed to the human. The
record must include:

- actor id;
- task id and trace id;
- tool name;
- risk class;
- target resource;
- normalized parameters;
- SHA-256 hash of normalized parameters;
- approval reason;
- policy version;
- approver id;
- issued timestamp;
- expiry timestamp;
- replay nonce.

Execution fails if any field differs from the approval record.

## Expiry And Replay Protection

- High approvals expire after 30 minutes.
- Critical approvals expire after 10 minutes.
- A nonce can be used once.
- Expired, reused, missing, or malformed approvals fail closed.

## Preview Requirements

Approval prompts must show:

- the exact tool and target;
- normalized parameters;
- expected side effects;
- rollback plan, if any;
- data that may leave the system;
- credentials or scopes requested;
- cost ceiling for the action.

## Step-Up Authentication

Critical actions require the operator to re-authenticate outside the model
conversation. The execution component validates the step-up result, not the
model.

## Scalable Oversight And Spot-Checks

Human review must not silently degrade as task volume grows (ADR-0016).

- **Risk-weighted fractional sampling.** Spot-checks of self-modifications and
  medium-risk actions are a *fraction*, not a fixed count; sampling probability
  rises with risk, novelty, blast radius, and cost. High and critical classes are
  always reviewed.
- **Bounded review rate, fail-closed overflow.** A maximum human-review rate is
  declared. If the queue exceeds capacity, high-impact work blocks and escalates;
  it never auto-proceeds.
- **Anti-automation-bias.** For sampled self-modifications and high-impact
  approvals, the reviewer records an independent judgment *before* seeing the
  agent's rationale; the preview surfaces the agent's own uncertainty and any
  dissenting signal.

## Novel / Ambiguous Actions

A registered tool invoked with parameters that do not match a known-safe pattern,
or any action whose risk class is ambiguous, escalates to approval rather than
executing. The tool registry is already default-deny for *unregistered* tools;
this closes the *registered-but-used-novelly* case (ADR-0016,
`security/tool-policy.yaml`).

## Policy Changes

Changes to this file, `approval-record.schema.json`, or any tool risk
classification require human review and the approval-bypass red-team suite.

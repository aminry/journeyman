# Memory Admission Policy

Durable memory is a privilege boundary. It can influence future tasks, so writes
must be validated before persistence.

## Memory Classes

| Class | Purpose | Allows project specifics | Default TTL |
|---|---|---:|---:|
| episodic_trace | replay current task and dream job input | yes, restricted storage | 90 days |
| project_memory | Plane A project knowledge in repo | yes | repo policy |
| semantic_agent_memory | Plane B generic craft | no | until superseded |
| skill_library | tested reusable skill or playbook | no | until deprecated |
| rejection_log | rejected memory candidates | minimal metadata only | 30 days |

## Admission Checks

Every durable memory write must include:

- source references;
- source trust level;
- proposed memory class;
- statement or artifact hash;
- reason the memory is useful;
- retention class or TTL;
- data classification;
- project-specific leakage scan result;
- prompt-injection scan result;
- sensitive-data scan result;
- experience-poisoning check (an episode is not admitted as "successful" on a
  self-reported or model-judged signal alone);
- `derived_from`: the source/episode ids, so consolidated memories can be tainted
  and unlearned later;
- corroboration or test evidence when promoting to Plane B — execution-grounded
  for behavior-changing memories.

## Rejection Rules

Reject or route to human review if:

- content contains instructions to the agent, tools, memory system, or approval
  system;
- content contains secrets, credentials, private keys, payment data, or restricted
  PII that is not explicitly allowed for that memory class;
- a Plane B candidate references project names, file paths, domains, schemas,
  customer data, credentials, or environment-specific behavior;
- source trust level is untrusted and no independent corroboration exists;
- retention class is missing;
- provenance is missing;
- the write would exceed memory size or duplicate-rate limits;
- the candidate is a "successful experience" whose only support is a self-reported
  or model-judged success signal, with no execution-grounded corroboration
  (plausible-success / experience-poisoning defense — injection scanning is
  necessary, not sufficient);
- a behavior-changing memory (one that changes routing, tool selection, review, or
  action) lacks an objective, execution-grounded signal (a test that ran, a tool
  result) or a human sign-off.

## Promotion To Plane B

Promotion requires:

- project-specific identifiers removed or abstracted, plus a sampled human audit
  of promoted craft for residual project-specificity — identifier stripping does
  not catch domain bias, and the distillation boundary is a model judgment, not a
  proof;
- corroboration by a different source class; for behavior-changing craft the
  corroboration must be execution-grounded (a test that actually ran or a real
  tool result), since a second model's agreement is correlated, not independent;
- for skills, a `validated_against` record (model/effector/embedding) per ADR-0013;
- retrieval summary that explains when to use it;
- conflict check against existing memories and skills;
- regression/eval pass if the memory changes routing, tool selection, or review
  behavior.

## Retrieval Requirements

Memory retrieval must return:

- memory id;
- source class;
- confidence;
- last verified timestamp;
- data classification;
- reason retrieved;
- any restrictions on use.

The model must not receive raw rejected memory candidates.

## Forgetting (Decay)

Forgetting keeps the retrieval surface small, but it is constrained (ADR-0012):

- forgetting is reversible cold-archive, never hard delete;
- a protected class — safety, security, and approval lessons, and discovered
  failures promoted to regression — never decays;
- forgetting decisions are eval-gated like any other self-modification, and
  recorded so they can be reversed.

## Unlearning

Durable memories carry `derived_from` (the episode/source ids they consolidated
from). When an episode is found poisoned, wrong, or invalidated:

- its derivatives are tainted via `derived_from`;
- the system rolls back to the last clean versioned snapshot and re-derives
  forward (the seed mechanism);
- a full provenance graph for targeted, non-rollback revert is deferred until
  volume justifies it.

Admission scanning catches injection and sensitive data; unlearning is the
recovery path for poison that looked benign at admission.

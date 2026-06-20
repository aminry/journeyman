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
- corroboration or test evidence, when promoting to Plane B.

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
- the write would exceed memory size or duplicate-rate limits.

## Promotion To Plane B

Promotion requires:

- project-specific identifiers removed or abstracted;
- test, tool, different model family, or human corroboration;
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

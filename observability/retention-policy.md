# Retention Policy

Retention defaults can be shortened by a project policy or operator request.
They cannot be lengthened for restricted data without human approval.

## Retention Windows

| Artifact | Default retention | Notes |
|---|---:|---|
| trace metadata | 180 days | no raw restricted data |
| redacted model transcript | 180 days | schema-validated |
| raw transcript reference | 30 days | restricted storage only |
| effector transcript | 30 days raw, 180 days redacted | must pass scanner |
| effector diff reference | repo lifetime | diff itself lives in git |
| approval records | 1 year | required for audit |
| budget ledger | 1 year | no raw prompts |
| security events | 1 year | redacted |
| rejected memory metadata | 30 days | no raw payload |
| eval evidence | 1 year | synthetic fixtures preferred |

## Access Control

- Raw restricted references require human-approved access.
- Redacted traces are readable by the kernel, evaluator, and observability tools.
- Held-out eval content is readable only by the eval runner and human reviewers.
- Approval records are append-only.

## Deletion

Delete or archive artifacts when:

- retention expires;
- a project is deleted;
- an operator requests deletion;
- a security incident requires credential purging.

Deletion events are logged as metadata only. Do not log the deleted content.

## Replay Limits

Offline replay must use redacted traces by default. Raw restricted references may
be loaded only in an approved incident/debug session with expiry.

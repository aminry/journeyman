# Data Classification Policy

This policy controls what may enter prompts, memory, traces, eval fixtures, and
operator-visible reports.

## Classes

| Class | Examples | Prompt use | Trace logging | Memory |
|---|---|---|---|---|
| public | OSS docs, public web pages, generated examples | allowed with source label | allowed after scan | allowed if useful |
| internal | repo paths, local design docs, task traces | allowed for current task | allowed with retention | project-scoped only unless abstracted |
| confidential | business plans, private repos, unreleased product data | minimize and label | redact where possible | project-scoped only |
| restricted | credentials, tokens, PII, payment data, health data, private keys | deny unless explicitly required by tool policy | never raw | deny except approved secure vault reference |

## Handling Rules

- Restricted data is never written raw to traces, evals, or Plane B memory.
- Confidential data must be summarized or minimized before prompt use.
- Internal project data may enter working context but must not cross into Plane B
  unless abstracted and stripped.
- Public data remains untrusted for instruction purposes.
- Eval fixtures must use synthetic data unless a human approves a restricted
  fixture with a retention and deletion plan.

## Secret-Like Values

Secret scanners must flag:

- API keys and tokens;
- private keys and certificates;
- password assignments;
- connection strings with credentials;
- cloud provider keys;
- payment provider keys;
- session cookies.

Detected values are redacted before trace persistence and block commit unless a
human approves a false positive.

## Retention Defaults

| Data | Retention |
|---|---:|
| task trace metadata | 180 days |
| raw model transcript reference | 30 days |
| redacted transcript | 180 days |
| effector diff | repo history plus trace ref |
| approval records | 1 year |
| rejected memory metadata | 30 days |
| security events | 1 year |

Retention can be shortened by project policy, legal requirement, or operator
request.

# Threat Model

This threat model covers the Journeyman seed system described in `docs/SPEC.md`.
It is a living artifact: update it when tool scopes, memory behavior, approval
rules, retrieval sources, model providers, or effector capabilities change.

## Assets

- Operator authority: approvals, budgets, credentials, and deployment rights.
- Project repositories: source code, tests, docs, ADRs, code graph, and history.
- Plane B agent knowledge: skills, semantic memory, summaries, evals, and traces.
- Plane A project knowledge: per-project docs, task specs, tests, generated code.
- Trace data: model inputs/outputs, tool calls, transcripts, diffs, costs.
- Credentials: provider API keys, repo tokens, deployment credentials, payment keys.
- Eval integrity: held-out tests, red-team suites, pass/fail evidence.

## Trust Boundaries

| Boundary | Trusted side | Untrusted side | Required control |
|---|---|---|---|
| User/operator to model | operator task spec | arbitrary user text | task schema and approval routing |
| External content to working context | kernel policy layer | web pages, files, issues, docs, tool output | untrusted-content pipeline |
| Model to tool execution | policy service | model-proposed tool call | tool policy and schema validation |
| Model to durable memory | memory admission service | model summary or extracted fact | memory admission policy |
| Agent to coding effector | kernel adapter | effector session internals | sandbox and verified-artifact contract |
| Approval to execution | execution policy | approval prompt text | parameter-bound approval record |
| Trace writer to storage | redaction policy | raw transcripts, diffs, tool output | redaction, encryption, retention |
| Self-modification to mainline | regression guard | modified memory, skills, prompts, evals | held-out evals and human review |

## Attacker Profiles

- Malicious external content author who plants instructions in web pages, docs,
  issues, code comments, emails, or retrieved documents.
- Malicious or compromised dependency/tool provider returning hostile output.
- Prompt-injection attacker attempting system prompt extraction, tool misuse,
  data exfiltration, memory poisoning, or approval bypass.
- Accidental operator mistake: approving the wrong action or providing secrets in
  a task.
- Self-modification failure: the system weakens its own evals, policies, memory,
  prompts, or tool scopes.
- Denial-of-wallet attacker or bug causing unbounded loops, retries, or tool use.

## Abuse Cases And Controls

| Abuse case | Impact | Primary controls | Evidence |
|---|---|---|---|
| Direct prompt override | model follows attacker instructions | structured task specs, input screening, red-team evals | `evals/redteam/prompt-injection.jsonl` |
| Indirect prompt injection | hostile web/file/tool content drives action | quarantine, action screening, untrusted labels | `security/untrusted-content-pipeline.md` |
| Tool misuse | unauthorized write, delete, deploy, spend | `security/tool-policy.yaml`, schema validation, fail closed | tool-call trace span |
| Approval bypass | high-impact action executes without exact approval | approval policy, parameter hash, expiry, nonce | approval record span |
| Memory poisoning | malicious payload persists across sessions | memory admission, TTL, source trust, injection scan | memory write span |
| Data exfiltration | secrets/PII leak via output, URL, log, trace | data classification, redaction, output validation | redaction report |
| Eval weakening | unsafe self-modification passes | eval governance, protected held-out sets, human review | eval evidence bundle |
| Effector overreach | coding effector changes outside task scope | sandbox profile, diff review, DoD gate | effector session span |
| Denial of wallet | runaway loop drains budget | cost ceilings, retry limits, recursion limits | budget ledger trace |

## Residual Risks

- Prompt-injection defenses are not complete against persistent attackers. Treat
  them as defense in depth, not proof of safety.
- Automated tests can miss product-level regressions. Human review remains
  required for irreversible, externally visible, or unverifiable work.
- Redaction can miss novel secret formats. Secret scanning must be updated as
  providers and credential formats change.
- The coding effector remains a high-capability subsystem. It must run with no
  ambient credentials and a bounded sandbox.

## Review Triggers

Review this file when:

- a new tool or credential scope is added;
- a model provider, memory backend, or coding effector changes;
- an eval, prompt, retrieval, or memory policy changes;
- a security incident, injection attempt, approval failure, or trace leak occurs;
- Phase -1 or regression-guard thresholds change.

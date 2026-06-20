# Redaction Policy

Traces must be useful for replay and debugging without becoming a secret or PII
repository.

## Never Persist Raw

- credentials, tokens, session cookies, private keys, certificates;
- payment data;
- government identifiers;
- health data;
- passwords;
- environment files;
- unrestricted raw browser pages, issue bodies, emails, or tool outputs that
  have not passed the untrusted-content pipeline.

## Redaction Methods

| Data | Method |
|---|---|
| secret-like values | replace with `[REDACTED_SECRET]` |
| PII | replace with `[REDACTED_PII]` or stable salted hash if correlation is needed |
| large tool output | store truncated redacted summary plus raw restricted reference if approved |
| diffs | scan before trace persistence; block if secrets present |
| approval params | store normalized params and hash; redact restricted values |
| external content | store source label and summary, not raw content, unless restricted storage is approved |

## Scanner Requirements

Before persistence, scan:

- model inputs and outputs;
- tool parameters and results;
- effector transcripts;
- diffs;
- approval previews;
- memory candidates.

If scanning fails, persistence fails closed and emits a `security_event` span.

## Manual Review

Manual review is required when:

- a finding may be a false positive blocking a required trace;
- restricted data is needed for replay;
- a new secret format is detected;
- redaction would destroy evidence for an incident.

Manual exceptions must include expiry and reviewer id.

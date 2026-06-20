# ADR-0010: Code-security gate on effector-produced code

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** security, ci, coding-effector

## Context

The Definition-of-Done gate (`ci/definition_of_done.yaml`) verifies tests,
coverage, build, lint/format, docs-sync, code-graph freshness, and secret
scanning of committed files and traces. None of these reliably detect *security
vulnerabilities in the product code the coding effector writes*. The evidence is
strong that LLM-generated code is frequently functional yet vulnerable: roughly
45% of tasks across 80 scenarios and 100+ models introduced CWE-class weaknesses,
and ~40% of analyzed Copilot code carried vulnerabilities. Passing functional
tests is necessary but not sufficient for "secure." For Phase 2 — a live product
with real users and revenue — this is the single gap most likely to cause a
real-world incident.

## Decision

Add a required **code-security gate** to the Definition-of-Done for both the
Journeyman repo and the standard project template:

- **SAST** over changed product code, failing on findings at or above an
  operator-set severity (reusing `max_high_severity_security_events: 0`).
- **SCA / dependency audit** over the dependency manifest and lockfile, failing
  on known-vulnerable dependencies at or above the configured severity and
  flagging newly added dependencies for review.
- **Secret scanning extended to the product code and diff**, not only traces.

The tool choice, severity thresholds, and a reviewed, time-boxed suppression
process live in `security/code-security-policy.md`. Findings emit as
`dod_gate` / `security_event` spans. The gate **fails closed** if the scanner
cannot run.

## Consequences

- **Positive:** functional-but-insecure code can no longer pass as "done"; the
  ~45% base-rate vulnerability gap is closed at the gate; product repos inherit
  the control through the template.
- **Negative / costs:** scanner runtime per change; false positives need a
  managed suppression path; SAST/SCA tools must be wired during the seed build
  (placeholders today, like the secret-scan command).
- **Risks & mitigations:** suppression abuse → suppressions are time-boxed,
  reasoned, and human-reviewed; scanner/database staleness → updated like any
  dependency; tool lock-in → depend on the capability, configure the scanner in
  `security/code-security-policy.md`.
- **Follow-ups required:** wire the concrete SAST/SCA commands in Phase 0.

## Alternatives considered

- **Rely on tests + lint + review** — rejected: tests verify function not
  security; lint is style; human review does not scale and misses CWE classes.
- **Add security scanning only in Phase 2** — rejected: the effector writes code
  from Phase 0; the control must exist before the code it protects.

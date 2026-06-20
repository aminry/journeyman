# Code-Security Policy

Functional tests verify that code *works*; they do not verify that it is *secure*.
LLM-written code is frequently functional yet vulnerable, so every change that
adds or modifies product code — whether written by the coding effector or a human
— passes static and dependency security scanning before the Definition-of-Done
gate accepts it. This policy governs that scanning. See ADR-0010.

## Scope

Applies to the Journeyman repo and to every repo scaffolded from
`project/project-template/`. It scans **product code and its dependencies**, and
is distinct from `observability/redaction-policy.md` (which scans *traces*) and
the `no-secrets` gate (which scans *committed files for secrets*).

## Required Scans

| Scan | Target | Fails the gate when |
|---|---|---|
| SAST | changed/added source in the diff | a finding at or above `block_severity` (default: high) |
| SCA / dependency audit | dependency manifest + lockfile | a known-vulnerable dependency at or above `block_severity`, or a newly added dependency not yet reviewed |
| Secret-in-code | the product diff (not just traces) | a credential, key, or token appears in source |

All three run in the `code-security` gate in `ci/definition_of_done.yaml` and emit
`security_event` spans on the task trace.

## Thresholds (operator-tunable)

- `block_severity`: minimum severity that blocks merge (default **high**).
- `max_high_severity_security_events`: **0** (reused from the DoD thresholds).
- `new_dependency_requires_review`: **true** — a new third-party dependency is
  flagged for human review (supply-chain control).

## Suppressions

A finding may be suppressed only with: a written rationale, an owner, an expiry
date (time-boxed, default 90 days), and human review. Suppressions live in
`security/code-security-suppressions.yaml`, are part of the diff, and expire —
an expired suppression re-opens the finding and re-blocks. Blanket or
non-expiring suppressions are rejected.

## Fail-Closed

If a scanner cannot run, its database is unreachable, or its output cannot be
parsed, the gate **fails closed** (blocks merge). A green result requires a scan
that actually executed.

## Maintenance

SAST rulesets and the SCA vulnerability database are dependencies: they are
updated on a schedule and on advisory of a relevant CVE. A change to this policy,
to `block_severity`, or to the suppressions file requires human review (it is a
security-policy change under `evals/eval-governance.md`).

## Implementation Note

The concrete scanners are wired during the Phase 0 seed build (e.g. a SAST tool
appropriate to the stack and an SCA/audit tool), behind the `code-security` gate's
`{{SAST_CMD}}` / `{{SCA_CMD}}` placeholders — depend on the capability, configure
the specific tool here.

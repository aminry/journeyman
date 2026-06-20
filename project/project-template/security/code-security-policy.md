# Code-Security Policy (project template)

Functional tests verify that code *works*; they do not verify that it is *secure*.
Every change that adds or modifies product code passes static and dependency
security scanning before the Definition-of-Done gate accepts it. Scaffolding wires
the concrete tools for this repo's stack. (Mirrors the Journeyman's
`security/code-security-policy.md`; see ADR-0010.)

## Required Scans

| Scan | Target | Fails the gate when |
|---|---|---|
| SAST | changed/added source in the diff | a finding at or above `block_severity` (default: high) |
| SCA / dependency audit | dependency manifest + lockfile | a known-vulnerable dependency at or above `block_severity`, or a new dependency not yet reviewed |
| Secret-in-code | the product diff | a credential, key, or token appears in source |

All three run in the `code-security` gate in `ci/definition_of_done.yaml`.

## Thresholds (operator-tunable)

- `block_severity`: minimum severity that blocks merge (default **high**).
- `max_high_severity_security_events`: **0**.
- `new_dependency_requires_review`: **true** (supply-chain control).

## Suppressions

A finding may be suppressed only with a written rationale, an owner, an expiry
date (time-boxed), and review. Suppressions live in
`security/code-security-suppressions.yaml`, are part of the diff, and expire.

## Fail-Closed

If a scanner cannot run or its output cannot be parsed, the gate fails closed.

## Implementation Note

Scaffolding fills `{{SAST_CMD}}` / `{{SCA_CMD}}` with tools appropriate to
`{{STACK}}`.

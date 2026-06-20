# Eval Governance

The regression harness protects the system from self-degradation. Treat evals,
red-team fixtures, held-out sets, graders, and thresholds as security-critical.

## Suite Classes

| Class | Purpose | Visibility |
|---|---|---|
| public_regression | known bugs and expected behavior | agent-readable |
| redteam | adversarial prompt, memory, tool, approval cases | agent-readable fixtures, expected outcomes protected by review |
| held_out | overfit-resistant gate for self-modification | eval runner and human reviewers only |
| discovered_failure | every new failure converted to regression | agent-readable after triage |
| human_judged | unverifiable or product-quality checks | human reviewer |

## Change Controls

Human review is required for changes to:

- `evals/**`;
- `security/**`;
- `observability/trace-schema.json`;
- model router capability scores;
- prompt templates;
- retrieval ranking;
- memory admission;
- tool policy or credential scopes;
- coding-effector sandbox permissions.

The same change cannot weaken evals and rely on those weakened evals to pass.
If eval weakening is intentional, it requires a separate reviewed change with a
clear rationale.

## Required Evidence Per Eval Run

- agent version or commit;
- model ids and settings;
- tool policy version;
- approval policy version;
- memory policy version;
- retrieval config version;
- sandbox profile;
- dataset ids and versions;
- pass/fail counts;
- failed case ids;
- cost and duration;
- reviewer id for human-judged cases.

## Held-Out Policy

- Held-out cases are not exposed to the model as context or memory.
- Held-out cases rotate periodically.
- Self-modification changes must pass held-out and public suites.
- If a held-out case fails, the failure is triaged. A sanitized version may be
  promoted to public regression after a fix lands.

## Blocking Conditions

Block merge or release when:

- any required suite fails;
- eval evidence is missing or schema-invalid;
- expected-denial cases are allowed;
- a high-risk policy changed without the matching red-team suites;
- held-out pass rate drops below the configured threshold;
- grader behavior changes without review.

# Coding Effector Contract

The coding effector is a tool, not a trusted peer agent. It receives a TaskSpec
and returns a diff that is accepted only after independent verification.

## Input Contract

Every effector session receives:

- task id;
- repo path or fresh worktree path;
- project brain references (`CLAUDE.md`, architecture docs, ADRs);
- explicit goal;
- acceptance tests or contract tests;
- constraints and non-goals;
- budget cap;
- allowed files or path scopes;
- sandbox profile id;
- required Definition-of-Done command;
- trace id.

The input must be structured. Free-form chat is not a valid effector contract.

## Spec & Test Verification (before the effector runs)

The TaskSpec and its acceptance tests are the trust anchor — a gate that checks
code against tests the agent wrote cannot catch a faithful build of a *wrong*
spec. Therefore, before a session starts:

- the TaskSpec carries a short **intent restatement** checked against the original
  goal;
- acceptance tests include **negative/property** cases, not happy-path only;
- for tasks above the operator-set risk/cost threshold — and anything
  irreversible, externally visible, or in the Phase 2 product — the spec and tests
  are **reviewed by a different source class** (a different model family or a
  human), recorded as a `verification` span; the instance that authored the tests
  does not review them (ADR-0014).

## Output Contract

The effector must return:

- git diff reference;
- files changed;
- commands run;
- tests run and results;
- transcript reference;
- token and cost usage if available;
- retry count;
- failures encountered;
- any requested permission escalation.

The effector's claim of completion is not accepted as evidence. Only the
Definition-of-Done gate and task acceptance tests decide completion.

## Acceptance Rules

Accept the effector output only if:

- diff is limited to the task scope or approved escalation;
- secret scan passes;
- redaction scan passes before transcript persistence;
- acceptance tests pass;
- Definition-of-Done gate passes;
- code graph is fresh when code changed;
- docs/ADR requirements are satisfied when architecture changed;
- effector session span includes cost, retry count, transcript ref, sandbox
  profile, and diff ref.

## Rejection Rules

Reject or escalate if:

- the effector touches protected paths without approval;
- the effector requests credentials not in the task policy;
- the effector uses network egress outside sandbox policy;
- the diff weakens tests, evals, security policy, approval policy, or DoD gates
  without explicit human-reviewed approval;
- the effector hides failures or omits command/test evidence;
- the effector output contains unredacted restricted data.

## Retry Policy

- First failure: agent refines TaskSpec using observed failures.
- Second failure: agent may narrow scope or add acceptance examples.
- Third failure: escalate to human with trace, diff, cost, and failure summary.

Retries count toward task cost. Failed sessions are not free.

## Swappability

The kernel depends on the capability `drive_coding_effector(spec) ->
verified_artifact_candidate`, not on one vendor. Any replacement effector must
satisfy this contract and `tools/coding-effector-sandbox.yaml`.

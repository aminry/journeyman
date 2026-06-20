# Phase -1 Experimental Protocol

This is the pre-registered protocol for deciding whether competence compounds
enough to justify Phase 0. Do not change this file after the first run starts.
If the protocol must change, close the current run as invalid and start a new
run with a new protocol version.

## Hypothesis

Within the fixed `spec -> CRUD service` domain, later tasks become cheaper and
better because the agent reuses portable orchestration craft: TaskSpec patterns,
effector prompts, checklists, decomposition recipes, and known failure-mode
preventions.

## Null Hypothesis

Observed cost or quality improvement is explained by task ordering, task
difficulty, model/provider changes, cache effects, pricing changes, effector
improvements, or random variation rather than reusable craft.

## Fixed Inputs

- Domain: `experiments/phase_minus_1/domain.md`
- Task manifest schema: `experiments/phase_minus_1/taskset.schema.json`
- Result schema: `experiments/phase_minus_1/results.schema.json`
- Task order: fixed interleaved order from `instances/manifest.md`
- Stack: Python 3.11, FastAPI, SQLite, black-box HTTP contract tests
- Project scaffold: `project/project-template/`
- DoD gate: `ci/definition_of_done.yaml`

## Run Modes

Run A is the treatment run. Run B is the baseline/control and is **mandatory for
a full pass** (ADR-0017).

| Run | Memory/skill reuse | Purpose |
|---|---|---|
| A: treatment | enabled after each passed task | measure compounding |
| B: control | disabled or frozen from task 1 | estimate effector-only improvement |

The **treatment-minus-control delta** is the primary evidence that *craft* — not
caching, task ordering, or effector drift — drove any improvement. A single-arm
run (A only) may yield only a **provisional, explicitly lower-confidence**
decision, recorded as such; it cannot be a full pass.

## Model And Pricing Pins

Record these before task 1:

- model provider and model ids;
- model settings that affect cost or output;
- embedding model and retrieval configuration;
- coding effector version;
- prompt templates and tool definitions;
- cache policy and whether prompt caching is enabled;
- token prices used for accounting;
- local machine and sandbox profile.

If any pinned item changes mid-run, record the event. A material model, price,
effector, or cache-policy change invalidates the slope calculation unless the
human operator explicitly accepts the residual risk.

## Metrics

Per task:

- `model_cost_usd`
- `effector_cost_usd`
- `total_cost_usd`
- `wall_clock_seconds`
- `dod_passed`
- `contract_passed`
- `contract_tests_passed`
- `contract_tests_total`
- `effector_retries`
- `first_pass_contract_success`
- `craft_items_retrieved`
- `craft_items_reused`
- `human_interventions`
- `security_events`

Aggregate:

- slope of total cost after warm-up (with confidence interval, per the
  pre-registered statistical test);
- slope of effector retries after warm-up;
- first-pass contract success trend;
- reuse trend;
- treatment-minus-control delta (required; the control run is mandatory).

`total_cost_usd` includes all task-attributable spend (model + effector). The
standing production viability gate additionally amortizes off-duty overhead
(dream, eval, regression guard, maintenance) into cost-per-task — see ADR-0015;
Phase −1 has no dream job, so that overhead is not yet present here.

## Warm-Up And Exclusions

- Exclude the first 5 tasks from the slope calculation, but still report them.
- Do not exclude failed tasks from cost; failed work is real cost.
- Exclude only infrastructure failures unrelated to the agent, such as local
  network outage or runner crash before task execution. Record every exclusion
  with a reason.
- Do not exclude high-cost tasks merely because they look anomalous.

## Statistical Test (pre-registered)

Decide the slope with a pre-specified test, not a visual read (ADR-0017):

- **Effect size:** state the minimum detectable cost-per-task slope the run is
  powered to detect; if n (post-warm-up) cannot detect it, extend the task count
  or report the result as underpowered.
- **Autocorrelation:** sequential tasks are correlated; estimate the slope with a
  method that accounts for it (e.g. OLS of cost on position with a lagged-residual
  correction, or a pre-registered nonparametric trend test such as Mann–Kendall).
- **Uncertainty:** report the slope point estimate with a confidence interval.
- **Attribution:** report the treatment-minus-control delta and its interval; a
  bend in A that is matched in B is environment, not craft.

A "pass" on cost requires the slope CI to exclude zero in the improving direction
and the treatment-vs-control delta to favor treatment.

## Pass Criteria

All must hold:

1. Cost slope after warm-up is negative by the pre-registered statistical test
   (slope CI excludes zero in the improving direction), the treatment-vs-control
   delta favors treatment, and the result is not explained by task difficulty,
   pricing, cache, or provider changes.
2. Quality holds or improves: contract pass rate non-decreasing, DoD pass rate
   non-decreasing, retries trending down or first-pass success trending up.
3. Reuse is real: craft reuse count rises, and traces show retrieved craft
   materially changed specs, reviews, or effector instructions.
4. Security controls hold: no high-severity security event, no policy bypass,
   and no unapproved high-impact action.

## Stop Criteria

Stop before task 30 if:

- budget ceiling is reached;
- a high-severity security control fails;
- the effector or kernel obtains ambient credentials outside policy;
- the run can no longer satisfy the pinned-model/pricing/cache assumptions.

## Evidence Bundle

At the end, produce:

- `results.json` validating against `results.schema.json`;
- `results.md` with pass/stop decision and residual risks;
- trace references for every task;
- craft items created and reused;
- excluded runs, if any;
- security events and approvals, if any.

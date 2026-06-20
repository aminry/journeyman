# results/_selftest/ — harness self-test artifacts (NOT experiment results)

Everything in this directory is a **harness self-test** (`run_kind:
"harness_selftest"`), produced by running the T-1.1 spine on a single instance to
prove the machinery works end-to-end. These are **not** Phase −1 experimental
results and must never be read, aggregated, or reported as a decision:

- `run_kind` is `harness_selftest` (the schema forbids a `pass`/`provisional_pass`
  decision for these — see `../../results.schema.json`);
- `decision.status` is `invalid` ("not a valid experimental decision");
- they cover one instance, not the pre-registered task set, with no control run.

The T-1.4 analysis treats a result as a real decision only when
`harness.results.is_real_experiment_decision(...)` is true — i.e. `run_kind ==
"experiment"`, the full 30-task set, and a present control run. Real experiment
results (Run A + control Run B) live in `experiments/phase_minus_1/results/`
(the parent directory), not here.

Files:

- `spine_books.fake.results.json` — fake-effector spine run (zero model spend; the
  effector body is the reference service). Proves the pipeline.
- `spine_books.real.results.json` — real Claude Code CLI run (T-1.1 go-ahead);
  proves the live adapter seam (CLI call, cost/usage parsing, boot/egress,
  git-diff capture). The model built the service from the spec + craft only and
  passed all 52 held-out contract cases + the instance DoD; effector cost $2.66.

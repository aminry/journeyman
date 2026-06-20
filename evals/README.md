# evals/  (SEED)

The rotating regression harness that the regression guard runs (ADR-0008). Properties: rotating, partly **held-out**, **growing** (every discovered failure becomes a test), and **adversarial**. Verifiable tasks are auto-graded; unverifiable work routes to a human judge. Entry point referenced by the gate: `python -m evals.run --rotating --held-out`.

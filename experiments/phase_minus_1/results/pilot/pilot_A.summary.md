# Orchestrator run `pilot_A` (treatment)

## Per-task cost (driver vs effector)
| pos | task | tier | model$ | effector$ | total$ | retries | first_pass | retrieved | reused |
|--|--|--|--|--|--|--|--|--|--|
| 1 | notes | easy | 0.0198 | 3.8149 | 3.8347 | 0 | True | 0 | 0 |
| 2 | books | medium | 0.0244 | 3.2582 | 3.2825 | 0 | False | 1 | 1 |
| 3 | orders | hard | 0.0259 | 2.7095 | 2.7354 | 0 | False | 2 | 1 |

## Reflections (craft written/updated)
- **notes**: WRITE (crud-easy-uuid-string-first-pass) — This was a clean first-pass success (no retries, all gates passed) on a minimal CRUD service with uuid + string fields. Worth capturing the canonical contract recipe and common effector pitfalls for this pattern so future easy-tier CRUD tasks stay green on the first pass.
- **books**: WRITE (crud-medium-integer-validation-min) — The gate shows contract_passed=False with exactly the failing case `validation:min:price_cents:invalid`, while dod_passed=True. This is a clean, recurring effector failure mode: integer fields with implicit non-negative semantics are left unconstrained. The existing craft `crud-easy-uuid-string-first-pass` covers easy-tier UUID/string basics and does not address integer min validation. This new playbook is generic (no project names, no field names), portable, and directly targets the observed failure mode to prevent recurrence on any medium+ spec with integer fields.
- **orders**: WRITE (crud-hard-healthz-contract-boot-failure) — The gate shows contract_passed=False with the sole failing case being boot:healthz, while dod_passed=True. This is a recurring, project-agnostic failure mode (missing or misconfigured health-check route) that is not covered by any existing craft. It is specific enough to be actionable and generic enough to apply to any CRUD service. Writing a new playbook will directly reduce this class of effector mistake on future hard-tier (and medium-tier) specs.

## Selectivity — did the driver incorporate selectively or dump all retrieved?
| task | retrieved | incorporated | incorp/retrieved | incorp∩gold prec | incorp∩gold recall |
|--|--|--|--|--|--|
| notes | [] | [] | — | — | — |
| books | ['crud-easy-uuid-string-first-pass'] | ['crud-easy-uuid-string-first-pass'] | 1.00 | 0.00 | — |
| orders | ['crud-easy-uuid-string-first-pass', 'crud-medium-integer-validation-min'] | ['crud-medium-integer-validation-min'] | 0.50 | 0.00 | — |

## Retrieval-precision diagnostic (G2)
```json
{
  "positions": 3,
  "mean_curated_recall": null,
  "mean_auto_recall": null,
  "mean_curated_precision": 0.0,
  "mean_incorporation_precision": 0.5,
  "mean_incorporation_curated_precision": 0.0,
  "mean_incorporation_curated_recall": null,
  "divergent_positions": 0,
  "per_position_curated_recall": [
    null,
    null,
    null
  ],
  "per_position_incorporation_curated_recall": [
    null,
    null,
    null
  ]
}
```

Craft library now: ['crud-easy-uuid-string-first-pass', 'crud-hard-healthz-contract-boot-failure', 'crud-medium-integer-validation-min']

Decision: **stopped** — PILOT/PARTIAL run (run_mode=treatment), stopped at the ADR-0020 G1 gate. 3 task(s); not a full experimental decision (requires 30 tasks + the mandatory control run, ADR-0017/T-1.4). Reviewed for craft quality, reuse, and retrieval precision before authorizing the full run.
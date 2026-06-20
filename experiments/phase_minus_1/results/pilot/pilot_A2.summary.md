# Orchestrator run `pilot_A2` (treatment)

## Per-task cost (driver vs effector)
| pos | task | tier | model$ | effector$ | total$ | retries | first_pass | retrieved | reused |
|--|--|--|--|--|--|--|--|--|--|
| 1 | notes | easy | 0.0332 | 1.8172 | 1.8504 | 0 | True | 0 | 0 |
| 2 | books | medium | 0.0313 | 2.9085 | 2.9398 | 0 | False | 1 | 1 |
| 3 | orders | hard | 0.0293 | 4.1037 | 4.1330 | 0 | False | 1 | 1 |

## Reflections (craft written/updated)
- **notes**: WRITE (fastapi-sqlite-scaffold) — First pass, no retries, no failures — the effector succeeded cleanly on the baseline stack. This is the right moment to capture the canonical FastAPI + SQLite scaffold pattern so future effectors have a concrete, reusable reference for the fixed Phase-1 stack.
- **books**: SKIP (—) — reflection rejected: craft would leak instance identifiers ['created_at']
- **orders**: UPDATE (fastapi-sqlite-scaffold) — The gate failed on boot:healthz with retries=0 and first_pass=False. This is a fundamental scaffold issue — the health check endpoint is either missing or misconfigured. The fastapi-sqlite-scaffold playbook should be updated to explicitly mandate the /healthz (or /health) endpoint as a required boot-time check, since this is a recurring failure mode that the effector misses.

## Selectivity — did the driver incorporate selectively or dump all retrieved?
| task | retrieved | incorporated | incorp/retrieved | incorp∩gold prec | incorp∩gold recall |
|--|--|--|--|--|--|
| notes | [] | [] | — | — | — |
| books | ['fastapi-sqlite-scaffold'] | ['fastapi-sqlite-scaffold'] | 1.00 | 1.00 | 1.00 |
| orders | ['fastapi-sqlite-scaffold'] | ['fastapi-sqlite-scaffold'] | 1.00 | 1.00 | 1.00 |

## Run-health: % craft ids in canonical taxonomy (must be 100%)
- **notes**: 100% canonical
- **books**: 100% canonical
- **orders**: 100% canonical

## Retrieval-precision diagnostic (G2)
```json
{
  "positions": 3,
  "mean_curated_recall": 1.0,
  "mean_auto_recall": null,
  "mean_curated_precision": 0.666667,
  "mean_incorporation_precision": 0.666667,
  "mean_incorporation_curated_precision": 1.0,
  "mean_incorporation_curated_recall": 1.0,
  "divergent_positions": 2,
  "per_position_curated_recall": [
    null,
    1.0,
    1.0
  ],
  "per_position_incorporation_curated_recall": [
    null,
    1.0,
    1.0
  ],
  "craft_canonical_pct_min": 1.0
}
```

Craft library now: ['fastapi-sqlite-scaffold']

Decision: **stopped** — PILOT/PARTIAL run (run_mode=treatment), stopped at the ADR-0020 G1 gate. 3 task(s); not a full experimental decision (requires 30 tasks + the mandatory control run, ADR-0017/T-1.4). Reviewed for craft quality, reuse, and retrieval precision before authorizing the full run.
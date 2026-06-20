# experiments/phase_minus_1 — Validate that competence compounds

**This gate decides whether the rest of the system is worth building (ADR-0002).** Run it first. If it fails, stop and diagnose — do not build the seed on a flat curve.

## Hypothesis

In a narrow, verifiable domain, the *Nth* task gets cheaper and better than the 1st because the agent reuses accumulated **orchestration craft** (better specs, decomposition recipes, checklists, known effector failure modes) — not because code is reused. Coding is delegated to the effector, which writes fresh code each time (ADR-0005), so the bet is on **portable judgment**, and that is what we measure.

## Setup (deliberately minimal)

- One agent, one model + one cheap fallback.
- A flat skill/craft library on disk (orchestration playbooks + any genuinely reusable utility code, with manifests).
- Simple vector retrieval. **No** dream phase, **no** agent graph, **no** second agent, **no** promotion gate beyond "passes the gate."
- The coding-effector adapter, with the boundary instrumented for cost/retries/diff.
- The Definition-of-Done gate for the chosen domain.
- Trace + cost logging.

## Domain (operator picks one — see `docs/SPEC.md` §23)

Choose one narrow, **verifiable** domain so the cost/quality signal is clean. Examples: "scaffold + deploy a small CRUD service from a spec," or "extract structured records from a class of messy documents." Record the choice and the 30 task instances here.

## Protocol

Run ~30 real tasks in sequence. Each completed task may write a tested orchestration-craft skill (or utility) the next can retrieve and reuse. Per task, log:

- total cost (model + **effector**) and wall-clock
- Definition-of-Done gate pass/fail
- effector retries
- count of prior craft items retrieved and reused

## Pass criteria (all three)

1. **Cost-per-task trends down** across the 30 tasks — fit a line; slope clearly negative after warm-up (include effector spend).
2. **Quality holds or improves** — gate pass-rate non-decreasing; effector retries/task trending down.
3. **Reuse is real** — later tasks measurably retrieve and reuse earlier orchestration craft (fewer effector round-trips, richer specs), not regenerate from scratch.

## Outcome

- **Pass** → proceed to Phase 0 (`tasks/BACKLOG.md`).
- **Flat / negative** → diagnose (usually retrieval misses, over-specific playbooks, or thin specs that make the effector burn retries) and fix cheaply here, or conclude the premise doesn't hold for this domain.

## Artifacts to produce here

- `domain.md` — the chosen domain and the 30 task instances.
- `results.json` / `results.md` — per-task metrics and the three-criteria evaluation.
- `harness/` — the minimal runner (T−1.1).

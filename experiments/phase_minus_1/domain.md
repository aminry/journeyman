# Phase −1 domain: spec → CRUD service

The chosen Phase −1 domain (see `README.md` for the gate). Each task gives the agent **one instance spec** describing a REST resource; the agent drives the coding effector to build a tested service in a **fresh repo**; the harness then verifies it against a **held-out, black-box HTTP contract suite generated from the same spec**. This is the closest stepping-stone to the Phase 2 web-product target, and it is richly and objectively verifiable.

Why this domain meets the criteria: pass/fail comes from a test suite (no LLM judge); naive delegation leaves real headroom (validation shapes, pagination, conflict codes, state rules are easy to get subtly wrong, so craft has something to reduce); 30 instances share a CRUD skeleton but escalate in difficulty so craft transfers without being copy-paste; each runs in a fresh repo so we measure **portable craft (Plane B)**, not project-brain accumulation.

## 1. Fixed implementation contract

To keep variance attributable to **craft and difficulty** rather than stack choice, fix the stack and the boot/verify contract for the experiment:

- **Stack:** Python 3.11 + FastAPI + SQLite (file or in-memory). (Verification is black-box HTTP, so the stack can be varied later as a *separate* experiment — don't vary it here.)
- **Boot contract:** the scaffolded repo exposes `./run.sh` that starts the service listening on `$PORT`, and a `GET /healthz` returning 200 when ready. The harness boots it, waits for health (timeout 30s), runs the contract suite, then tears it down.
- **Isolation:** each instance is built in its own fresh repo scaffolded from `project/project-template/`. No project knowledge carries between instances; only Plane-B craft does.
- **Held-out tests:** the agent receives the **spec**, not the harness contract tests. The agent still writes its own tests (the Definition-of-Done gate requires them); acceptance is the harness's independent suite. This prevents teaching-to-the-test.

## 2. Instance spec schema (single source of truth)

Each instance is one YAML file under `instances/`. The **same file** drives the agent's task *and* generates the gold contract tests — so verification is objective and pre-committed. Schema:

```
id:            short slug (repo name + resource path)
title:         human title
tier:          easy | medium | hard
resource:
  name:        singular resource name
  path:        collection path, e.g. /books
  fields:      list of:
    name, type (uuid|string|integer|number|boolean|enum|datetime|ref),
    required, readonly, generated, default,
    constraints: min/max, min_len/max_len, pattern, values (enum), ref (target resource)
endpoints:     which of create/get/list/update/delete are present, with:
    success status, missing status (404), partial (PATCH),
    pagination {limit_param, offset_param, default_limit, max_limit},
    filters [field...], sort [field...]
rules:         on_validation_error (422 + {errors:[{field,message}]}),
               on_unique_conflict (409), timestamps_immutable, ...
business_rules: list (hard tier): state_machine | computed_field | cross_field | relationship | composite_unique
```

The worked example is `instances/example_books.spec.yaml` (a **medium** instance). A **hard** exemplar is `orders` — same skeleton plus a `status` state machine (`pending → paid → shipped → delivered`, with `cancel` allowed only before `shipped`; invalid transition → 409) and a cross-field rule (`discount_cents ≤ total_cents`).

## 3. Verification approach

The harness compiles each spec into a black-box `httpx`/`pytest` contract suite and runs it against the booted service. Acceptance is **binary: all contract tests pass.** The mapping from spec → tests:

| Spec element | Generated contract tests |
|---|---|
| `create` endpoint | POST valid payload → success status; response echoes input + generated/readonly fields populated |
| each `required` field | POST omitting it → 422 with an error naming that field |
| each `type`/constraint (`min/max`, `min_len/max_len`, `pattern`, enum `values`) | POST a boundary-violating value → 422; a boundary-valid value → success |
| `default` field | POST without it → response has the default |
| `readonly`/`generated` field | POST trying to set it → ignored or 422; server populates it |
| `unique` field | POST a duplicate → 409 |
| `get` | GET created id → 200 + same entity; GET unknown id → 404 |
| `update` (`partial`) | PATCH one field → 200, only that field changes; PATCH unknown id → 404; PATCH a readonly field → ignored/422 |
| `delete` | DELETE → 204; subsequent GET → 404; DELETE unknown id → 404 |
| `list` pagination | seed N>limit rows → respects `default_limit`, `limit`/`offset`, `max_limit` cap; stable ordering |
| `list` filters | filter by each declared field → only matching rows |
| `list` sort | sort by each declared field asc/desc → correctly ordered |
| `business_rules.state_machine` | each legal transition → 200; each illegal transition → 409; terminal state rejects further transitions |
| `business_rules.cross_field` | violating combination → 422 |
| `business_rules.relationship` (`ref`) | create child with non-existent parent → 404/422; cascade/restrict on parent delete as specified |
| `business_rules.composite_unique` | duplicate of the composite key → 409 |

In addition to the contract suite, the instance must pass its own **Definition-of-Done gate** (the project's unit tests, lint, build, docs-sync, code-graph-fresh). Both must pass for the task to count as done.

## 4. The 30-instance generation scheme

Three tiers × 10 instances. Same CRUD skeleton; escalating features so orchestration craft transfers but reuse isn't trivial.

- **Easy (10):** 3–5 scalar fields; validation = required + type + simple range/length; endpoints create/get/list(no pagination)/delete; **no** uniqueness, filters, sort, partial-update, or relationships.
- **Medium (10):** 6–9 fields incl. one `enum`, one `datetime`, one `boolean` w/ default; **one** `unique` field (→ 409); full CRUD incl. partial PATCH; `list` with pagination + 1–2 filters + 1 sort.
- **Hard (10):** all of medium **plus at least one** business rule: `state_machine`, `computed_field`, `cross_field`, `relationship` (a second resource via `ref`), or `composite_unique`; pagination + multiple filters + multi-sort.

The concrete 30 (entity + tier + distinguishing feature) and their **run order** are in `instances/manifest.md`.

### Ordering matters (read this)

**Do not run easy→hard.** That confounds "craft accumulating" with "tasks getting easier" and will produce a misleading downward slope. Instead **interleave** so difficulty is roughly stationary: run in repeating triplets `[Easy_k, Medium_k, Hard_k]` for k = 1..10, so every window of three contains one of each tier. The manifest lists this fixed order (positions 1–30). With difficulty stationary, a downward cost-per-task slope is attributable to craft, which is the whole point.

## 5. Per-task metrics (logged by the harness)

For each of the 30 tasks, log: model cost, **effector cost**, wall-clock, contract-suite result (binary pass + count of sub-tests passed for diagnostics), Definition-of-Done result, **effector retries**, **first-pass contract success** (passed before any retry?), and **craft items retrieved and reused** (by id). Tag craft skills so reuse is traceable — e.g. `crud-spec-template`, `validation-422-shape`, `pagination-contract`, `unique-409-recipe`, `state-machine-playbook`, `fastapi-sqlite-scaffold`.

## 6. Evaluating the gate (ties to README pass criteria)

- **Cost-per-task down:** fit a line to cost-per-task over positions; **exclude the first ~5 (warm-up)**; slope must be clearly negative.
- **Quality holds:** contract pass-rate non-decreasing; **effector retries/task trending down** and **first-pass contract success trending up**.
- **Reuse is real:** the reuse counter is **> 0 and rising**, and the cost drop traces to retrieved-and-reused craft.

> **The decisive failure signal:** if cost falls but the **reuse counter stays ~0**, that is *not* compounding — it's the effector being good on its own, meaning the domain has no headroom for craft. Pick a harder/more varied tier mix and re-run, or conclude the premise doesn't hold for this domain. Conversely, all three criteria met → proceed to Phase 0.

## 7. Artifacts to produce here

- `instances/*.spec.yaml` — the 30 specs (start from `example_books.spec.yaml`).
- `instances/manifest.md` — the 30 instances, tiers, features, and fixed run order.
- `harness/` — the runner (Task **T−1.1**): scaffolds a fresh repo per instance, drives the effector with the spec, boots the service, runs the generated contract suite + DoD gate, logs metrics.
- `results.json` / `results.md` — per-task metrics and the three-criteria evaluation with the pass/stop decision.

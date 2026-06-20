# Phase −1 validation harness (T-1.1 measurement spine)

Executes the pre-registered Phase −1 protocol (`../protocol.md`, `../domain.md`)
for the `spec → CRUD service` domain. T-1.1 builds the measurement spine and
proves it end-to-end on the single `books` instance. See `docs/adr/0019` for the
architecture and scope boundaries.

## What it does, per instance

1. retrieve craft (keyword/tag) and record the reuse counter;
2. scaffold a fresh repo from `project/project-template/`;
3. build the effector **TaskSpec from the SPEC + retrieved craft only** (never the
   contract tests — held-out integrity);
4. drive the coding effector (boundary instrumented: cost, retries, git diff);
5. assert held-out integrity (no harness/contract code in the repo);
6. boot the service via `./run.sh` on `$PORT`, wait for `GET /healthz` (30s);
7. run the generated black-box contract suite **+** the instance Definition-of-Done;
8. tear down;
9. write a per-task record (faithful `total_cost = model + effector + tool`)
   validated against `../results.schema.json`, plus a trace.

## Components

| Module | Role |
|---|---|
| `specschema.py` | Load/validate an instance `*.spec.yaml`. |
| `payloads.py` | Deterministic valid + boundary payloads. |
| `compiler.py` | Spec → black-box contract cases (the **oracle**); pinned API conventions. |
| `render.py` | Emit the cases as a standalone pytest module (auditable). |
| `reference/service.py` | Spec-driven FastAPI+SQLite service; standalone (no `harness` import). |
| `craft.py` | Flat on-disk craft library + reuse counter. |
| `effector.py` | `drive_coding_effector` interface + `FakeEffector` + `ClaudeCodeEffector`. |
| `runconfig.py` | Pins: models, token prices, cache policy, effector command. |
| `results.py` | Build/validate per-task records + results.json. |
| `scaffolder.py` | Fresh per-instance repo from the template. |
| `runner.py` | Orchestrates the whole spine; writes the validated record + trace. |
| `cli.py` | `python -m harness.cli` entrypoint. |

## Run it

The harness is imported as the top-level `harness` package; tests find it via the
repo-root `conftest.py`. For the CLI, put it on `PYTHONPATH`:

```bash
# FAKE effector — deterministic, ZERO model spend (CI-safe):
PYTHONPATH=experiments/phase_minus_1 python -m harness.cli \
  --instance experiments/phase_minus_1/instances/example_books.spec.yaml \
  --effector fake \
  --results-out experiments/phase_minus_1/results/spine_books.fake.results.json

# Tests (unit + oracle validation + end-to-end, all zero-spend):
python -m pytest tests/unit tests/integration -q
```

### The single REAL run (needs an explicit go-ahead)

```bash
export ANTHROPIC_API_KEY=...        # injected from the environment; never committed
PYTHONPATH=experiments/phase_minus_1 python -m harness.cli \
  --instance experiments/phase_minus_1/instances/example_books.spec.yaml \
  --effector claude
```

This drives the real Claude Code CLI (`claude -p ... --output-format json
--model claude-opus-4-8`, scoped `--allowedTools`, budget cap $10). It spends real
money — hold it for an explicit operator go-ahead. The harness secret-scans
transcripts/diffs before persisting them; `.context/` and any `.env`/`*.db` are
gitignored.

## Scope (T-1.1 only)

No driver/orchestrator, no dream/graph/second agent/promotion gate, no 30-spec
corpus, no Run A/control Run B, no slope/CI/decision. Retrieval is keyword/tag
(vector retrieval lands at T-1.3). Run artifacts (scaffolded repos, generated
suites, results, traces) are written under `.context/phase_minus_1_runs/`
(gitignored); a committed example lives in `../results/`.

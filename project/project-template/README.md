# project-template

The canonical scaffold for **every** repository the system builds — and for the platform's own repository. `scaffold_project` copies this tree into a new repo and fills the `{{PLACEHOLDERS}}` below. Building from one template is what guarantees every project (and the platform itself) starts with the same professional-engineering discipline: documented decisions, a regenerable code knowledge graph, tests, a build system, and an enforced Definition-of-Done gate.

## Contents

```
project-template/
  CLAUDE.md                                  operating contract for any agent in the repo
  README.md                                  this file
  ARCHITECTURE.md                            (stub) component map + data flow, kept current by the gate
  DESIGN.md                                  (stub) high-level design; links out to ADRs
  docs/
    adr/template.md                          copy this for each architectural decision
    adr/0001-record-architecture-decisions.md   adopts ADRs (already accepted)
    knowledge/index.md                       (stub) project knowledge wiki (linked markdown)
  codegraph/graph.json                       generated, regenerable, git-union-merged
  src/                                       source
  tests/unit/  tests/integration/            tests
  build/                                     build system config
  ci/definition_of_done.yaml                 the merge gate (tests, coverage, build, lint, docs-sync, graph-fresh)
  hooks/                                     pre-commit / CI hooks (regenerate graph, run docs-sync)
```

(Only the three load-bearing files — `CLAUDE.md`, `docs/adr/template.md`, `ci/definition_of_done.yaml` — plus `docs/adr/0001` and this README are provided here as starting content; the remaining stubs are created empty by the scaffolder.)

## Placeholders the scaffolder fills

| Placeholder | Meaning |
|---|---|
| `{{PROJECT_NAME}}` | Repository / project name |
| `{{PROJECT_PURPOSE}}` | One-line statement of what the system does |
| `{{STACK}}` | Primary language and frameworks |
| `{{PROJECT_STATUS}}` | e.g. scaffolding, active, maintenance |
| `{{INSTALL_CMD}}` | Install dependencies |
| `{{TEST_UNIT_CMD}}` | Run unit tests |
| `{{TEST_INTEGRATION_CMD}}` | Run integration tests |
| `{{COVERAGE_CMD}}` | Produce a parseable coverage percentage |
| `{{BUILD_CMD}}` | Build the project |
| `{{LINT_CMD}}` | Lint / format check |
| `{{CODEGRAPH_CMD}}` | Regenerate `codegraph/graph.json` |
| `{{SECRET_SCAN_CMD}}` | Scan the diff for committed secrets |
| `{{DOD_CMD}}` | Run the full Definition-of-Done gate locally |
| `{{EVAL_HARNESS_CMD}}` | (platform repo only) run the rotating regression eval harness |
| `{{DEPENDENCY_MANIFEST}}` | Dependency manifest path (e.g. `pyproject.toml`, `package.json`) |
| `{{YYYY-MM-DD}}`, `{{WHO_DECIDED}}` | ADR metadata |

## How it's used

1. `scaffold_project` copies this tree, fills the placeholders for the chosen stack, and initializes git + the code-graph indexer (with watch mode).
2. CI is wired to `ci/definition_of_done.yaml`; nothing merges unless the gate passes.
3. For the **platform's own repo**, enable the `regression-guard` gate in `definition_of_done.yaml` (it is disabled by default for built-product repos).
4. Coding work — including anything delegated to the coding effector — is accepted only when this gate passes.

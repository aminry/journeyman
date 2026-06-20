# hooks/

Scripts the Definition-of-Done gate and git hooks call.

- `regenerate_code_graph.sh` — (re)builds `codegraph/graph.json` via the configured indexer; `--check` mode fails if the committed graph is stale.
- `check_docs_sync.py` — enforces "architectural change requires an ADR or ARCHITECTURE.md update" by reading the `docs-in-sync` gate in `ci/definition_of_done.yaml` and diffing changed files. Honors the `architecture-impact: none` escape hatch (set `DOD_CHANGE_DESC` to the PR/commit body).
- `run_dod.sh` — runs the full gate locally.
- `pre-commit` — git hook: regenerate graph + docs-sync check. Install: `ln -s ../../hooks/pre-commit .git/hooks/pre-commit`.

Environment: `CODEGRAPH_CMD` (indexer command), `DOD_BASE_REF` (diff base, default `origin/main`), `DOD_CHANGE_DESC` (change description for the escape hatch).

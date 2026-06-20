# project/  (SEED)

The machinery that imposes engineering discipline on every project the platform builds (SPEC §11), and on this repo itself.

- **Scaffolder** (`scaffold_project`) — copies `project-template/`, fills placeholders per stack, initializes git + the code-graph indexer (watch mode), wires CI to the gate.
- **Definition-of-Done logic** — runs `ci/definition_of_done.yaml` by gate `type`.
- **Code-graph indexer interface** — a stable interface over a graphify-style indexer (depend on the capability, not the tool).
- **`project-template/`** — the canonical template (also used to scaffold this platform repo). See its `README.md`.

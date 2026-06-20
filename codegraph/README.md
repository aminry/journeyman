# codegraph/

The code knowledge graph for THIS repo (Plane A). `graph.json` is generated, regenerable,
and committed so agents orient by querying the graph (then reading only the files it points
to) instead of reading the whole tree. Regenerate with `hooks/regenerate_code_graph.sh`.
The Definition-of-Done gate fails if it is stale. Depend on the indexer *capability* behind
a stable interface (see `project/`), not a specific tool.

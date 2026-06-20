#!/usr/bin/env bash
# Regenerate the code knowledge graph (Plane A) for this repo.
#
# Depends on a code-graph indexer behind a stable interface (see project/ and SPEC §11).
# Set CODEGRAPH_CMD to your chosen indexer (e.g. a graphify-style tool). The indexer
# must write codegraph/graph.json.
#
#   regenerate_code_graph.sh           # regenerate and (re)write graph.json
#   regenerate_code_graph.sh --check   # CI mode: fail if graph.json would change
#
set -euo pipefail
cd "$(dirname "$0")/.."

CODEGRAPH_CMD="${CODEGRAPH_CMD:-}"
if [[ -z "$CODEGRAPH_CMD" ]]; then
  echo "regenerate_code_graph: set CODEGRAPH_CMD to your code-graph indexer." >&2
  echo "  (left unset until the seed build wires the indexer — SPEC §11)" >&2
  # Do not hard-fail before the indexer is wired; CI enables this once it exists.
  exit 0
fi

if [[ "${1:-}" == "--check" ]]; then
  tmp="$(mktemp)"
  CODEGRAPH_OUT="$tmp" $CODEGRAPH_CMD
  if ! diff -q "$tmp" codegraph/graph.json >/dev/null 2>&1; then
    echo "code-graph-fresh: FAIL — codegraph/graph.json is stale. Run hooks/regenerate_code_graph.sh and commit." >&2
    rm -f "$tmp"; exit 1
  fi
  rm -f "$tmp"; echo "code-graph-fresh: pass"
else
  $CODEGRAPH_CMD
  echo "code graph regenerated -> codegraph/graph.json (commit it)"
fi

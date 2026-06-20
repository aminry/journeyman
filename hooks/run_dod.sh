#!/usr/bin/env bash
# Run the full Definition-of-Done gate locally. Mirrors ci/definition_of_done.yaml.
# During the seed build, a generic runner should parse the YAML and execute each
# gate by `type`. This script runs the platform's concrete commands directly so the
# gate is usable from day one.
set -uo pipefail
cd "$(dirname "$0")/.."
fail=0
run() { echo "==> $1"; bash -c "$2"; if [[ $? -ne 0 ]]; then echo "FAILED: $1"; fail=1; fi; }

run "tests-unit"         "pytest tests/unit -q"
run "tests-integration"  "pytest tests/integration -q"
run "coverage"           "pytest --cov --cov-report=term-missing -q"
run "build"              "python -m build"
run "lint"               "ruff check . && black --check ."
run "docs-in-sync"       "python hooks/check_docs_sync.py"
run "code-graph-fresh"   "hooks/regenerate_code_graph.sh --check"
run "regression-guard"   "python -m evals.run --rotating --held-out"

if [[ $fail -ne 0 ]]; then echo; echo "Definition of Done: NOT met."; exit 1; fi
echo; echo "Definition of Done: met."

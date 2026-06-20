"""CLI to run one Phase -1 instance end-to-end and write results.json.

    PYTHONPATH=experiments/phase_minus_1 python -m harness.cli \
        --instance experiments/phase_minus_1/instances/example_books.spec.yaml \
        --effector fake

The default effector is ``fake`` (deterministic, ZERO model spend) so CI and
local runs cost nothing. The single REAL run uses ``--effector claude`` and
requires ``ANTHROPIC_API_KEY`` in the environment — hold it for an explicit
go-ahead (budget cap is enforced from the run config).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness.craft import CraftLibrary, seed_default_craft
from harness.effector import ClaudeCodeEffector, FakeEffector
from harness.runconfig import default_run_config
from harness.runner import run_instance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Phase -1 instance end-to-end.")
    parser.add_argument("--instance", required=True, help="path to a *.spec.yaml")
    parser.add_argument("--effector", choices=["fake", "claude"], default="fake")
    parser.add_argument("--run-id", default="spine_books")
    parser.add_argument("--position", type=int, default=1)
    parser.add_argument("--workdir", default=".context/phase_minus_1_runs")
    parser.add_argument("--craft-dir", default=".context/phase_minus_1_runs/craft")
    parser.add_argument("--results-out", default=None, help="optional copy of results.json")
    args = parser.parse_args(argv)

    cfg = default_run_config()
    craft_lib = CraftLibrary(args.craft_dir)
    if not craft_lib.ids():
        seed_default_craft(craft_lib)

    artifact_dir = Path(args.workdir) / args.run_id / "eff_artifacts"
    if args.effector == "claude":
        effector = ClaudeCodeEffector(cfg, artifact_dir=artifact_dir)
        print(
            "[cli] REAL run: driving Claude Code CLI — this spends real money "
            f"(cap ${cfg.budget_cap_usd}). Ensure ANTHROPIC_API_KEY is set."
        )
    else:
        effector = FakeEffector(cfg, artifact_dir=artifact_dir)
        print("[cli] FAKE run: deterministic, zero spend.")

    result = run_instance(
        args.instance,
        config=cfg,
        effector=effector,
        workdir=args.workdir,
        craft_lib=craft_lib,
        run_id=args.run_id,
        position=args.position,
    )

    rec = result.record
    print(
        json.dumps(
            {
                "task_id": rec["task_id"],
                "contract": f"{rec['contract_tests_passed']}/{rec['contract_tests_total']}",
                "contract_passed": rec["contract_passed"],
                "dod_passed": rec["dod_passed"],
                "total_cost_usd": rec["total_cost_usd"],
                "effector_cost_usd": rec["effector_cost_usd"],
                "craft_reused": rec["craft_items_reused"],
                "results": str(result.results_path),
                "run_kind": result.results_doc["run_kind"],
                "decision": result.results_doc["decision"]["status"],
            },
            indent=2,
        )
    )

    if args.results_out:
        out = Path(args.results_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result.results_doc, indent=2))
        print(f"[cli] results copied to {out}")

    ok = rec["contract_passed"] and rec["dod_passed"]
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

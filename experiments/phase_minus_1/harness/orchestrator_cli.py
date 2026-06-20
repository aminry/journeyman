"""CLI to run the Phase −1 orchestrator (driver loop) over a position range (T-1.3).

    # fakes (zero spend; CI/build proof):
    PYTHONPATH=experiments/phase_minus_1 python -m harness.orchestrator_cli \
        --positions 1-3 --driver fake --effector fake --retriever deterministic \
        --run-id pilot_fake --out experiments/phase_minus_1/results/_selftest

    # the REAL pilot triplet (held for explicit go-ahead; spends real money):
    PYTHONPATH=experiments/phase_minus_1 python -m harness.orchestrator_cli \
        --positions 1-3 --driver anthropic --effector claude --retriever bge \
        --mode treatment --run-id pilot_A --out experiments/phase_minus_1/results/pilot

The real path drives the Sonnet 4.6 driver (temp 0, Haiku 4.5 fallback) + the Opus 4.8
coding effector via the Anthropic gateway in the environment (ANTHROPIC_BASE_URL /
ANTHROPIC_API_KEY). Budget caps are per-tier (manifest.md). Artifacts are written under
``--out`` as ``run_kind=experiment`` (distinct from the spine's results/_selftest/).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from harness.craft import CraftLibrary
from harness.driver import AnthropicDriver, FakeDriver
from harness.effector import ClaudeCodeEffector, FakeEffector
from harness.embedding import BGEEmbedder, DeterministicHashEmbedder
from harness.gold import GoldMap
from harness.orchestrator import (
    DEFAULT_GOLD,
    DEFAULT_TASKSET,
    OrchestratorResult,
    RunInputs,
    run_sequence,
)
from harness.retrieval import KeywordCraftRetriever, VectorCraftRetriever
from harness.runconfig import orchestrator_run_config


def parse_positions(spec: str) -> list[int]:
    """Parse ``1-3,7`` / ``1,2,3`` / ``2`` into an ordered position list."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def _validated_against(cfg, embedding_pin: str) -> dict:
    return {
        "models": [cfg.driver_model or "unknown"],
        "effector_version": cfg.effector_version,
        "embedding_model": embedding_pin,
    }


def build_inputs(args) -> RunInputs:
    cfg = orchestrator_run_config()
    library = CraftLibrary(args.craft_dir)
    workdir = Path(args.workdir)
    last_validated = "2026-06-20T00:00:00Z"

    # --- retriever -------------------------------------------------------- #
    if args.retriever == "bge":  # pragma: no cover - real-model path
        embedder = BGEEmbedder(
            cfg.embedding_model,
            revision=cfg.embedding_revision,
            query_prefix=cfg.embedding_query_prefix,
            normalize=cfg.embedding_normalize,
        )
        cfg.embedding_revision = embedder.revision
        cfg.sentence_transformers_version = embedder.sentence_transformers_version
        retriever = VectorCraftRetriever(library, embedder, k=cfg.retrieval_k)
    elif args.retriever == "deterministic":
        cfg.embedding_model = "deterministic-hash-512"
        retriever = VectorCraftRetriever(
            library, DeterministicHashEmbedder(dim=512), k=cfg.retrieval_k
        )
    else:
        retriever = KeywordCraftRetriever(library, k=cfg.retrieval_k)

    va = _validated_against(cfg, cfg.embedding_pin_string())

    # --- driver ----------------------------------------------------------- #
    if args.driver == "anthropic":  # pragma: no cover - real-spend path
        driver = AnthropicDriver(
            model=cfg.driver_model,
            fallback_model=cfg.driver_fallback_model,
            temperature=cfg.driver_temperature,
            max_tokens=cfg.driver_max_tokens,
            validated_against=va,
            last_validated=last_validated,
        )
    else:
        driver = FakeDriver(validated_against=va, last_validated=last_validated)

    # --- effector --------------------------------------------------------- #
    artifact_dir = workdir / args.run_id / "eff_artifacts"
    if args.effector == "claude":  # pragma: no cover - real-spend path
        effector = ClaudeCodeEffector(cfg, artifact_dir=artifact_dir)
    else:
        effector = FakeEffector(cfg, artifact_dir=artifact_dir)

    return RunInputs(
        config=cfg,
        driver=driver,
        effector=effector,
        retriever=retriever,
        library=library,
        gold=GoldMap.load(args.gold),
        workdir=workdir,
    )


def write_artifacts(result: OrchestratorResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / f"{result.run_id}.results.json"
    results_path.write_text(json.dumps(result.results_doc, indent=2))
    (out_dir / f"{result.run_id}.summary.md").write_text(_summary_md(result))
    return results_path


def _summary_md(result: OrchestratorResult) -> str:
    lines = [
        f"# Orchestrator run `{result.run_id}` ({result.run_mode})",
        "",
        "## Per-task cost (driver vs effector)",
        "| pos | task | tier | model$ | effector$ | total$ | retries | first_pass | "
        "retrieved | reused |",
        "|--|--|--|--|--|--|--|--|--|--|",
    ]
    for r, a in zip(result.records, result.tasks):
        lines.append(
            f"| {r['position']} | {r['task_id']} | {r['tier']} | {r['model_cost_usd']:.4f} | "
            f"{r['effector_cost_usd']:.4f} | {r['total_cost_usd']:.4f} | {r['effector_retries']} | "
            f"{r['first_pass_contract_success']} | {len(r['craft_items_retrieved'])} | "
            f"{len(r['craft_items_reused'])} |"
        )
    lines += ["", "## Reflections (craft written/updated)"]
    for a in result.tasks:
        written = a.craft_written or "—"
        lines.append(
            f"- **{a.record['task_id']}**: {a.reflect_action} ({written}) — {a.reflect_rationale}"
        )
    lines += [
        "",
        "## Selectivity — did the driver incorporate selectively or dump all retrieved?",
        "| task | retrieved | incorporated | incorp/retrieved | incorp∩gold prec | "
        "incorp∩gold recall |",
        "|--|--|--|--|--|--|",
    ]
    for a in result.tasks:
        d = a.diagnostic
        sel = "—" if not a.retrieved else f"{d.incorporation_precision:.2f}"
        gp = (
            "—"
            if d.incorporation_curated_precision is None
            else f"{d.incorporation_curated_precision:.2f}"
        )
        gr = (
            "—"
            if d.incorporation_curated_recall is None
            else f"{d.incorporation_curated_recall:.2f}"
        )
        lines.append(
            f"| {a.record['task_id']} | {a.retrieved} | {a.reused} | {sel} | {gp} | {gr} |"
        )
    lines += [
        "",
        "## Retrieval-precision diagnostic (G2)",
        f"```json\n{json.dumps(result.diagnostic_summary, indent=2)}\n```",
        "",
        f"Craft library now: {result.library.ids()}",
        "",
        f"Decision: **{result.results_doc['decision']['status']}** — "
        f"{result.results_doc['decision']['rationale']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the Phase −1 orchestrator over positions.")
    p.add_argument("--positions", required=True, help="e.g. 1-3 or 1,2,3")
    p.add_argument("--mode", choices=["treatment", "control"], default="treatment")
    p.add_argument("--driver", choices=["fake", "anthropic"], default="fake")
    p.add_argument("--effector", choices=["fake", "claude"], default="fake")
    p.add_argument("--retriever", choices=["bge", "deterministic", "keyword"], default="bge")
    p.add_argument("--run-id", default="orchestrator_run")
    p.add_argument("--workdir", default=".context/phase_minus_1_orchestrator")
    p.add_argument("--craft-dir", default=".context/phase_minus_1_orchestrator/craft")
    p.add_argument("--out", default="experiments/phase_minus_1/results/pilot")
    p.add_argument("--gold", default=str(DEFAULT_GOLD))
    p.add_argument("--taskset", default=str(DEFAULT_TASKSET))
    args = p.parse_args(argv)

    positions = parse_positions(args.positions)
    inputs = build_inputs(args)
    if args.driver == "anthropic" or args.effector == "claude":  # pragma: no cover
        print(
            f"[orchestrator] REAL run: driver={args.driver} effector={args.effector} — spends "
            f"real money (per-tier caps {inputs.config.tier_budget_caps}). Positions {positions}."
        )
    result = run_sequence(
        positions, run_mode=args.mode, inputs=inputs, run_id=args.run_id, taskset_path=args.taskset
    )
    path = write_artifacts(result, Path(args.out))
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "run_mode": result.run_mode,
                "tasks": len(result.records),
                "craft_library": result.library.ids(),
                "reuse_total": sum(len(r["craft_items_reused"]) for r in result.records),
                "diagnostic": result.diagnostic_summary,
                "results": str(path),
                "decision": result.results_doc["decision"]["status"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

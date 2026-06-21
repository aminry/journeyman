"""Top-level A-then-B experiment driver for the full 30x2 run (T-1.3 Fix #4).

One invocation runs the full treatment Run A (1..N, library accumulates) then the control
Run B (1..N, frozen-empty + run-and-discard reflection) with ONE frozen RunConfig, the
embedder loaded ONCE (so the bge revision/st/torch pins are captured once and identical for
both arms), the same task order, and a byte-identical driver prompt + decoding. Guards:

* **parity** — :func:`assert_prompt_parity` raises if A's and B's driver prompt or decoding
  differ (the A-B delta would otherwise be confounded);
* **control isolation** — A and B use SEPARATE craft dirs; B's craft dir must be empty at
  start, so the control run physically CANNOT read A's accumulated library;
* **one global budget** — a single ``global_budget_cap_usd`` spans both arms;
* **resumable** — each arm has its own durable ``records.jsonl`` (see orchestrator).

This harness emits DATA ONLY. The treatment-minus-control delta + the pre-registered
statistical pass/stop decision are computed in T-1.4 (ADR-0017), never here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from harness.craft import CraftLibrary
from harness.driver import Driver
from harness.gold import GoldMap
from harness.orchestrator import (
    CONTROL,
    DEFAULT_GOLD,
    TREATMENT,
    OrchestratorResult,
    RunInputs,
    run_sequence,
)
from harness.retrieval import VectorCraftRetriever
from harness.runconfig import RunConfig

_PARITY_DECODING_FIELDS = (
    "driver_model",
    "driver_fallback_model",
    "driver_temperature",
    "driver_max_tokens",
)


def assert_prompt_parity(
    driver_a: Driver, driver_b: Driver, cfg_a: RunConfig, cfg_b: RunConfig
) -> None:
    """Raise if Run A and Run B would NOT use a byte-identical driver prompt + decoding.
    The whole A-B delta rests on this (ADR-0020 §6 parity invariant)."""
    if driver_a.system_prompt != driver_b.system_prompt:
        raise AssertionError(
            "driver prompt parity violated: Run A and Run B have different system prompts"
        )
    for f in _PARITY_DECODING_FIELDS:
        if getattr(cfg_a, f) != getattr(cfg_b, f):
            raise AssertionError(f"driver decoding parity violated on {f!r}: A and B differ")


def run_experiment(
    *,
    positions: list[int],
    cfg: RunConfig,
    embedder: Any,
    gold: GoldMap,
    workdir: Path,
    craft_dir_a: Path,
    craft_dir_b: Path,
    out_dir: Path,
    driver_factory: Callable[[], Driver],
    effector_factory: Callable[[str], Any],
    run_id_a: str = "runA",
    run_id_b: str = "runB",
    global_budget_cap_usd: float = 350.0,
    resume: bool = False,
) -> tuple[OrchestratorResult, OrchestratorResult]:
    craft_dir_a, craft_dir_b, out_dir, workdir = map(
        Path, (craft_dir_a, craft_dir_b, out_dir, workdir)
    )
    if craft_dir_a.resolve() == craft_dir_b.resolve():
        raise ValueError(
            "Run A and Run B MUST use separate craft dirs — the control run is frozen-empty "
            "and must not be able to read Run A's accumulated library."
        )
    lib_a, lib_b = CraftLibrary(craft_dir_a), CraftLibrary(craft_dir_b)
    if not resume and lib_b.ids():
        raise ValueError(
            f"control craft dir {craft_dir_b} is not empty — frozen-empty control violated"
        )

    driver_a, driver_b = driver_factory(), driver_factory()
    assert_prompt_parity(driver_a, driver_b, cfg, cfg)

    # Run A (treatment) — library accumulates.
    inputs_a = RunInputs(
        config=cfg,
        driver=driver_a,
        effector=effector_factory("A"),
        retriever=VectorCraftRetriever(lib_a, embedder, k=cfg.retrieval_k),
        library=lib_a,
        gold=gold,
        workdir=workdir,
    )
    res_a = run_sequence(
        positions,
        run_mode=TREATMENT,
        inputs=inputs_a,
        run_id=run_id_a,
        records_path=out_dir / f"{run_id_a}.records.jsonl",
        resume=resume,
        global_budget_cap_usd=global_budget_cap_usd,
    )
    spent_a = res_a.diagnostic_summary.get("total_spend_usd", 0.0)

    # Run B (control) — frozen-empty + run-and-discard reflection; its OWN empty craft dir,
    # its retriever bound to that dir, so it physically cannot read A's library. The global
    # cap spans both arms (B gets the remainder).
    inputs_b = RunInputs(
        config=cfg,
        driver=driver_b,
        effector=effector_factory("B"),
        retriever=VectorCraftRetriever(lib_b, embedder, k=cfg.retrieval_k),
        library=lib_b,
        gold=gold,
        workdir=workdir,
    )
    res_b = run_sequence(
        positions,
        run_mode=CONTROL,
        inputs=inputs_b,
        run_id=run_id_b,
        records_path=out_dir / f"{run_id_b}.records.jsonl",
        resume=resume,
        global_budget_cap_usd=max(0.0, global_budget_cap_usd - spent_a),
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{run_id_a}.results.json").write_text(json.dumps(res_a.results_doc, indent=2))
    (out_dir / f"{run_id_b}.results.json").write_text(json.dumps(res_b.results_doc, indent=2))
    return res_a, res_b


def _real_inputs(args):  # pragma: no cover - real-spend path
    from harness.driver import AnthropicDriver
    from harness.effector import ClaudeCodeEffector
    from harness.embedding import BGEEmbedder
    from harness.runconfig import orchestrator_run_config

    cfg = orchestrator_run_config()
    embedder = BGEEmbedder(
        cfg.embedding_model,
        revision=cfg.embedding_revision,
        query_prefix=cfg.embedding_query_prefix,
        normalize=cfg.embedding_normalize,
    )
    cfg.embedding_revision = embedder.revision
    cfg.sentence_transformers_version = embedder.sentence_transformers_version
    cfg.torch_version = embedder.torch_version
    va = {
        "models": [cfg.driver_model],
        "effector_version": cfg.effector_version,
        "embedding_model": cfg.embedding_pin_string(),
    }

    def driver_factory() -> Driver:
        return AnthropicDriver(
            model=cfg.driver_model,
            fallback_model=cfg.driver_fallback_model,
            temperature=cfg.driver_temperature,
            max_tokens=cfg.driver_max_tokens,
            validated_against=va,
            last_validated="2026-06-20T00:00:00Z",
        )

    def effector_factory(arm: str):
        return ClaudeCodeEffector(cfg, artifact_dir=Path(args.workdir) / f"run{arm}" / "eff")

    return cfg, embedder, driver_factory, effector_factory


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - real-spend path
    p = argparse.ArgumentParser(description="Run the full Phase −1 30x2 (Run A then Run B).")
    p.add_argument("--positions", default="1-30")
    p.add_argument("--workdir", default=".context/phase_minus_1_fullrun")
    p.add_argument("--out", default="experiments/phase_minus_1/results/fullrun")
    p.add_argument("--global-budget-cap-usd", type=float, default=350.0)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--gold", default=str(DEFAULT_GOLD))
    args = p.parse_args(argv)

    from harness.orchestrator_cli import parse_positions

    positions = parse_positions(args.positions)
    cfg, embedder, driver_factory, effector_factory = _real_inputs(args)
    wd = Path(args.workdir)
    res_a, res_b = run_experiment(
        positions=positions,
        cfg=cfg,
        embedder=embedder,
        gold=GoldMap.load(args.gold),
        workdir=wd,
        craft_dir_a=wd / "craft_A",
        craft_dir_b=wd / "craft_B",
        out_dir=Path(args.out),
        driver_factory=driver_factory,
        effector_factory=effector_factory,
        global_budget_cap_usd=args.global_budget_cap_usd,
        resume=args.resume,
    )
    print(
        json.dumps(
            {
                "runA_tasks": len(res_a.records),
                "runB_tasks": len(res_b.records),
                "runA_spend": res_a.diagnostic_summary.get("total_spend_usd"),
                "runB_spend": res_b.diagnostic_summary.get("total_spend_usd"),
                "runA_craft": res_a.library.ids(),
                "runB_craft": res_b.library.ids(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

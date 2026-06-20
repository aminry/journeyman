# ADR-0023: Phase −1 orchestrator implementation — embedding pin + build decisions

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator (Amin), Claude Code (Opus 4.8)
- **Tags:** experiments, phase-minus-1, orchestration, memory, retrieval, evals
- **Extends:** ADR-0020 (locked design). This ADR records the implementation decisions
  T-1.3 had to pin that ADR-0020 left open — it does not change ADR-0020's locked design.

## Context

ADR-0020 locked the Phase −1 driver-loop design and resolved five forks, but explicitly
left some items "TBD" for the build: the exact **local embedding model + revision**
(`pins.embedding_model`), the **retrieval-precision diagnostic method** (gate G2), and a
set of mechanical implementation choices the experiment's validity depends on (how reuse
is *verified*, how fresh-context is *enforced*, how Run A/B parity is *asserted*). T-1.3
implemented the orchestrator + vector retrieval and proved it against fakes (zero spend)
before any real spend; these decisions were taken with the operator at the T-1.3 start
gate and are recorded here so the run is reproducible and the gold key is pre-registered.

## Decision

**1. Embedding model pin (ADR-0020 §5 "TBD").** We will use **`BAAI/bge-small-en-v1.5`**,
local, deterministic, zero per-call cost. Recorded in `pins.embedding` (model id, HF
revision SHA resolved + frozen at first download, sentence-transformers version,
`normalize=true`, `similarity=cosine`, `k=5`, query prefix) and, compactly as
`<model>@<revision>`, in each craft item's `validated_against.embedding_model` (the
schema allows only a string there). The **bge query-instruction prefix**
(`"Represent this sentence for searching relevant passages:"`) is applied to the
**query only** (instance feature tags + spec digest), never to craft documents. The
sentence-transformers dependency is **lazy-imported** (pilot-only); CI and the fakes
path use a zero-dependency `DeterministicHashEmbedder`, and `build_retriever` degrades to
the keyword/tag fallback when sentence-transformers is absent. If the G1 pilot's
retrieval precision is weak, **tune query construction first, not the model** (operator
decision).

**2. Driver pin (confirming ADR-0020 §3).** Driver = `claude-sonnet-4-6` (primary) +
`claude-haiku-4-5` (fallback), `temperature = 0`, recorded in `pins.driver` and held
**byte-identical across Run A and Run B**. The Haiku fallback is symmetric across A/B and
the model that actually produced a craft item is recorded in its `validated_against.models`
(so a fired fallback is auditable). Opus 4.8 escalation stays a hard, evidence-triggered
**G1-only** gate; we do **not** start on Opus.

**3. Verified-incorporated reuse (ADR-0020 §5).** The composed TaskSpec carries a
`<!-- craft:<id> -->` marker for each incorporated item; `reuse = retrieved ∧
marker-present`. A driver that *claims* incorporation without the guidance appearing in
the TaskSpec does not count — reuse is not a gameable self-report.

**4. Fresh-context enforcement (ADR-0020 §2).** The driver is **stateless**: `compose`
and `reflect` build a fresh `messages=[system, user]` from the call's inputs only; the
driver instance holds only run-level constants (asserted by a test on `vars(driver)`).
The only state crossing tasks is the on-disk craft library (treatment); the kernel
(`orchestrator.py`), not the model, moves data and writes stores.

**5. Run A/B parity (ADR-0020 §6).** "Parity" is **structural**, not equal dollars: both
runs use the same driver, the same frozen `DRIVER_SYSTEM_PROMPT`, the same decoding, and
both execute compose **and** reflect (Run B reflects-and-discards). Run B differs only by
a frozen-empty library (no retrieval) and discarded reflection writes. Run A's compose
legitimately costs more (it has craft to read); that is craft's real cost, reported via
the effector-cost slope alongside the total (G4).

**6. Retrieval-precision diagnostic = curated gold map (primary) + auto cross-check
(G2).** `experiments/phase_minus_1/retrieval_gold.yaml` is the **pre-registered**,
retriever-independent key (universals relevant to every instance + list items + one rule
recipe per rule actually present in the frozen corpus), keyed to the ADR-0020 craft
taxonomy and resolved to concrete ids at runtime. The **auto feature-tag map** (craft
tag ∩ instance feature tags) is reported alongside as a free objective cross-check, with
divergences flagged — it is deliberately blind to universally-relevant craft no
distinguishing tag names (the exact false negative G2 targets). Precision/recall are
computed over `{relevant} ∩ {present-in-library-at-that-position}` (the library is
emergent — unwritten craft is not a "miss"); **per-position recall** is the decisive
metric. The gold map is **DRAFT pending operator/advisor sign-off** before the run is
frozen (ADR-0014 independence) — no post-hoc edits after seeing retrieval results.

**7. Reflection guardrails (ADR-0020 §4).** Reflect-on-signal (retry, first-pass fail, or
uncovered feature); a **project-stripping lint** rejects any craft body that leaks an
instance identifier (forced to SKIP) so only generic craft is persisted; one canonical
item per feature tag (dedupe → UPDATE, not proliferate); per-craft impact metrics +
harmful-craft quarantine (G3). The 13-item taxonomy's template bodies are proven generic
against all 30 specs by test.

**8. Real-spend + artifacts.** The pilot is authorized for the triplet (positions 1–3,
Run A only) via the operator's local Anthropic gateway (`ANTHROPIC_BASE_URL` /
`ANTHROPIC_API_KEY` in the environment); per-tier caps E$3/M$5/H$8. A/B artifacts live in
`experiments/phase_minus_1/results/pilot/` as `run_kind=experiment` (distinct from the
spine's `results/_selftest/`). The full 30×2 run stays gated behind the pilot review.

**9. Retrieval depth `k` = full library size, not a small constant (operator decision,
gold-map review).** `retrieval_k = 13` (the full craft taxonomy), not 5. At `k=5` every
medium (8 relevant) and hard (up to 11 relevant) instance is capped once the library
fills — it would cap the reuse counter at 5 and G2 recall at ~0.45, biting only positions
~15–30 (the cold-start pilot can't reveal it). With `k = full library`, retrieval never
drops relevant craft, so **G2's decisive signal becomes the driver's INCORPORATION
judgment vs the gold** (`incorporation_curated_precision` / `_recall`), not a retrieval-cap
artifact — the right thing at this scale. `verify_incorporated` confirms a marker is
present, not selectivity; **selectivity** is read from `incorporation_precision`
(incorporated ÷ retrieved: 1.0 = the driver dumped all retrieved craft) and its quality
from incorporation-vs-gold. Per-call cost of the larger `k` is zero (local embedder).
Revisit only if a driver invents craft ids beyond the taxonomy (library > k). The pin +
the resolved bge revision, sentence-transformers version, and **torch version** are
recorded in `pins.embedding`.

**10. Run A continuation rule (stated before the pilot).** On a pilot **PASS**, Run A
**continues from the pilot's library state** — same `run_id`, same on-disk craft dir,
positions 4–30, with **no re-run** of positions 1–3 (the craft library persists on disk;
T-1.4 merges the position records into the single Run A). On a **G1 FAIL** (evidence to
bump the driver to Opus 4.8), Run A is **restarted as a new `run_id`** with re-pinned
decoding, and the pilot is **marked superseded** — retained on disk for audit but
excluded from the T-1.4 analysis (`is_real_experiment_decision` already ignores a
3-task run; the supersession is recorded in the run's decision rationale).

## Addendum (2026-06-20) — G1 pilot remediation: constrain the driver to the taxonomy

The first real pilot (`pilot_A`, positions 1–3; retained as G1 evidence, excluded from
T-1.4) passed the machinery + craft-quality checks but exposed one HIGH issue: the Sonnet
driver wrote craft under **its own free-form ids** (e.g. `crud-easy-uuid-string-first-pass`)
instead of the canonical taxonomy. Consequences: the curated G2 gold map (keyed to
taxonomy ids) couldn't grade it (recall/precision null/0), and the dedupe guardrail
(keyed to taxonomy ids) never fired (3 WRITEs, 0 UPDATEs → projected ~20–30 items over 30
tasks vs the designed ~13). Operator decision: **Option A — constrain the driver to the 13
canonical ids** (restores the locked ADR-0020 §4 design; free-form ids were also mildly
anti-generic). Implemented as:

**11. Canonical-id constraint + non-dropping remap backstop.** The driver's reflect tool
constrains `craft_id`/`target_id` to an enum of the 13 canonical ids, and the canonical
catalog (id + `feature_keys` + `when_to_use`) is injected into the compose/reflect context
so the driver selects from it. A backstop (`nearest_canonical_id`) **remaps** any
non-canonical id to the nearest canonical item (by feature tag, else token overlap) — it
**never reject-and-drops** a reflection (dropping would lose a real lesson and bias
coverage down). Dedupe is now **presence-based**: a (canonicalized) id already in the
library becomes an **UPDATE** (version bump), absent becomes a **WRITE** — one canonical
item per feature, evolved over time. Proven deterministically on the fakes (two
same-feature tasks → one UPDATE, not two WRITEs); the merged item must stay
canonical/generic/project-stripped/actionable, and G3 impact tracks its reuse.

**12. Run-health: %-craft-canonical, fail-loud.** The orchestrator computes, per task, the
fraction of library craft ids in the taxonomy and **raises** if it is below 100%
(`assert_craft_canonical`) — so a future drift can never silently blind G2 mid-run again
(the exact failure the pilot caught). Surfaced in the run summary + aggregate.

These are driver-scaffolding + harness-guard changes, not an effector change; craft
*quality* in the pilot was good, so the Opus-escalation gate (ADR-0020 §3) was **not**
triggered. `torch_version` is now pinned alongside the bge revision + sentence-transformers
version. A taxonomy-constrained re-pilot (`pilot_A2`) confirms G2 is non-null and all craft
ids are canonical before the full 30×2 run is authorized.

## Addendum (2026-06-20) — re-pilot fixes: boot-PATH + RE-ASK + reflect-input (ADR-0020 §1 Step E)

`pilot_A2` confirmed Option A (G2 non-null, 100% canonical, real-run UPDATE/dedupe) but
surfaced two more pre-full-run issues:

**13. Boot env must expose Python console scripts (harness/env bug, not an effector miss).**
All 3 pilot boot failures were the same: the effector wrote a correct bare `exec uvicorn
app:app …` `run.sh`, but the `uvicorn` console script (from a `pip --user` install) was not
on the booted service's PATH → `exec: uvicorn: not found`, before the app loaded (notes
booted because it used `python3 -m uvicorn`). This would corrupt *both* arms at random, so
`runner._boot` now prepends the Python scripts dirs (venv/base bin + user-base bin) to the
boot PATH, as a normal venv would. Verified end-to-end with zero spend.

**14. RE-ASK-on-leak instead of SKIP-drop (reflection-quality, ADR-0020 §4).** A reflection
whose draft leaks an instance identifier is now RE-ASKed once (rewrite the same lesson
generically) before SKIP, so a real lesson is recovered rather than dropped (the pilot's
lint SKIP-drop biased coverage down). SKIP only if the re-ask still leaks. Token cost is
summed across both calls.

**15. Reflect-input = gate + a short service-log excerpt (ADR-0020 §1 Step E).** Reflection
(Step E) previously saw only the gate's failing case-ids, so the driver *mis-attributed*
the boot failures (it blamed `/healthz` when the real cause was `uvicorn: not found`).
Reflection quality is the experiment's linchpin, so Step E's input now includes a short
excerpt of the effector's **own** boot/service log. This is the effector's output, **not**
the held-out contract suite (no teaching-to-the-test leak), and the project-strip lint +
RE-ASK genericness guards still apply to whatever craft the driver then writes. An extended
re-pilot (positions 1–6) validates the fixed boot env on real, diverse medium/hard services
before the full 30×2 is authorized.

## Consequences

- **Positive:** the embedding pin is fully reproducible and zero-cost; reuse is verified
  not self-reported; fresh-context and A/B parity are enforced + tested; G2/G3 are
  implemented and the gold key is pre-registered and independent; the whole loop is
  proven on fakes with zero spend (CI green) before any real money.
- **Negative / costs:** a heavyweight optional dependency (sentence-transformers/torch)
  for the real path; the curated gold map is hand-authored (mitigated: mechanical from
  the frozen corpus + sign-off gate); the deterministic CI embedder is not the real
  model, so CI proves machinery, not retrieval quality (that is the pilot's job).
- **Risks & mitigations:** *retrieval too weak* → G2 per-position recall + "tune query
  first"; *harmful craft* → G3 quarantine; *grading the retriever against its own key* →
  independent curated map + sign-off; *reuse over-claim* → marker verification.
- **Follow-ups required:** operator/advisor sign-off on `retrieval_gold.yaml` before the
  pilot; record the resolved bge revision + sentence-transformers version into the pins
  at first model load; the G1 pilot review (craft quality / reuse / precision) before the
  full 30×2 run.

## Alternatives considered

- **`sentence-transformers/all-MiniLM-L6-v2`** — viable and slightly lighter, but bge has
  higher retrieval quality (MTEB) and was the operator's pin; the query-prefix cost is
  handled query-side.
- **Hosted embedding API** — rejected (ADR-0020 §5): adds per-call cost noise + a network
  confound; local is deterministic and free.
- **Auto feature-tag map as the *primary* G2 key** — rejected: it is defined by the same
  tags the retriever uses, so it is blind to universally-relevant craft and would mask the
  decisive false negative. Kept only as a cross-check.
- **Driver rewrites the whole TaskSpec** — rejected: risks dropping spec detail and
  muddying held-out integrity; the base TaskSpec stays deterministic (`build_taskspec`)
  and the driver only *adds* generic craft.
- **Equal-dollar A/B parity** — rejected as a misreading: A's craft-reading cost is real;
  parity is structural (same steps/prompt/decoding), and the effector-cost slope is
  reported alongside the total so a rising driver cost can't mask a falling effector signal.

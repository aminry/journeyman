# Phase −1 — Full-run decision (T−1.4)

**Dataset:** `results/fullrun/runA.results.json` (treatment, 30/30) + `results/fullrun/runB.results.json`
(control, 30/30). Paired, identical specs/order/pins; `run_kind=experiment`. Canonical craft ids,
no dupes, reconstructed == authoritative.
**Analysis scope (pre-registered):** post-warmup positions 6–30 (n=25) for slopes; all 30 paired
for the per-instance tests. Decided by the pre-registered tests in `protocol.md` §"Statistical Test"
and §"Pass Criteria", ADR-0017 (mandatory control + pre-specified test), ADR-0002 (the gate).

---

## Decision: **FAIL** — do not pass the Phase-0 gate on this evidence

The run completed (no Stop-Criteria abort), so this is a `fail` of the four-part **Pass Criteria**,
not a mid-run `stopped`. Pass requires **all** criteria to hold; two fail and one is not met.

### Honest headline

> **Within `spec → CRUD service` × Opus-4.8 effector × this craft-incorporation mechanism,
> competence did not compound.** Cost-per-task did not fall — the treatment arm ran **~16 % more
> expensive** than the no-memory control and trended flat-to-**up**, not down. Quality did not
> improve over control. Craft reuse was **real, well-retrieved, and demonstrably reshaped the
> effector's output**, yet produced **no measurable cost or quality benefit**.
>
> The dramatic "quality collapsed / reuse is net-harmful" signal is **substantially a measurement
> artifact** — a Definition-of-Done gate that ran each service's own tests under an **ambient Python
> interpreter missing the service's `sqlalchemy` dependency** — compounded by tier confounding. It is
> **not** evidence that craft degraded the code. **The trustworthy negative here is the absence of a
> benefit, not the presence of harm.**

This corrects the pre-analysis hypothesis ("quality down, reuse net-harmful, dose-responsive"):
the harm signal did not survive root-cause analysis (see §3). The robust negative is §1.

### Scope of this conclusion (explicit)

This result is scoped to **(spec → CRUD service) × (Opus-4.8 coding effector, claude-code-cli headless)
× (this driver compose/reflect craft-incorporation loop, bge-small vector retrieval over a 10-item
library)**. It is one domain, one model, one incorporation mechanism, n=30 paired. It does **not**
speak to other domains, models, library sizes, or incorporation designs. Per the operating contract,
this document **does not** declare the Journeyman thesis alive or dead and **does not** propose a
domain re-roll — those are the operator's strategic calls. The deliverable is a trustworthy,
fact-backed negative plus the mechanism, so the operator can decide.

---

## Follow-up (T−1.4, post-acceptance): gate fixed, quality re-scored, cost mechanism confirmed

The root cause in §3 was accepted and three measurement-only follow-ups were run. None re-runs the
effector or re-rolls the domain.

**1 — Gate isolation fixed (harness bug).** `run_instance_dod` (`harness/runner.py`) now runs the
instance's own tests under the **repo's project venv** when present (new `_gate_python`), mirroring the
environment the contract suite boots from, instead of a bare ambient `python`. Regression test:
`tests/integration/test_dod_gate_isolation.py` (a repo whose tests need a venv-only dependency passes
DoD under the fix and fails under the ambient interpreter). New tests green; full suite **296 passed,
2 skipped**; ruff + black clean. (Subtlety worth recording: the gate must invoke `.venv/bin/python` by
its **own** path — resolving that symlink to the base interpreter silently defeats the venv, a bug in
the first cut of the fix that re-scoring caught.)

**2 — Re-scored the 10 SQLAlchemy A repos under the fixed gate.** All **10/10 now pass DoD** under the
venv (their code was always fine). Six flip to full-pass (quotes, subscriptions, habits, tickets,
feeds, venues); the other four (shipments, inventory, appointments, invoices) remain non-full-pass for
a **legitimate** reason — hard-tier **contract** misses (business-rule gaps), now cleanly separated
from the gate artifact.

| metric | buggy gate (artifact) | **corrected gate** |
|---|---|---|
| full-pass A vs B | 12/30 vs 21/30 | **18/30 vs 21/30** |
| McNemar (A-wins / B-wins) | 3 / 12, **p=0.035** | **4 / 7, p=0.55 → A≈B** |
| reuse dose-response (full-pass) | reuse<3 62 %, reuse≥3 **0 %** | reuse<3 **88 %**, reuse≥3 **22 %** |

The spurious "significant quality collapse" is gone: corrected A full-pass (18) now equals A
contract-pass (18) — DoD passes wherever the agent's own tests pass, as it should. The residual
dose-response gap (88 % vs 22 %) is **tier confounding** — 7 of the 9 reuse≥3 tasks are hard-tier
contract misses present in **both** arms, not craft harm. (One honestly-reported, **underpowered**
residual: on the hard tier alone A's *contract* pass is 1/10 vs B's 5/10 — numerically worse but
n=6 discordant, p=0.22, not significant; a corrected re-run would be needed to say anything about it.)

**3 — Cost mechanism: the craft-prescribed heavier stack is a real, paired cost penalty.** Effector
cost, positions 21–30, **paired** (A built SQLAlchemy, B built lean FastAPI + sqlite3 from the *same*
specs): **A is +$0.742/task more expensive, on 9/10 pairs.** The A−B effector gap **more than doubles**
where craft imposed the ORM (**+$0.74** in the SQLAlchemy block 21–30 vs **+$0.31** in the lean block
6–20) — so ≈ $0.43/task is attributable to the heavier stack itself, atop a ≈ $0.31 baseline treatment
overhead. This ties the cost negative to a single mechanism: **craft prescribed unnecessary complexity**
(full SQLAlchemy ORM where the lean stack passed the identical contracts).

**Bottom line (unchanged verdict, sharpened framing): FAIL = no compounding.** Cost flat-to-up and
~16 % dearer (now mechanistically explained); quality **A ≈ B**, no improvement; **no genuine quality
regression** (the "collapse" was the gate bug, now fixed and re-scored); plus a **real, craft-induced
cost penalty** from an over-heavy prescribed stack. The negative is the absence of benefit (and a small
self-inflicted cost), **not** harmful-to-correctness craft. §1–§5 below are the original analysis; the
corrected quality numbers above supersede the buggy-gate figures in §2 and §4.

---

## 1. Cost-per-task — **FAIL** (Pass Criterion 1)

Pre-registered test: autocorrelation-aware slope of cost on position, post-warmup, with a CI; pass
needs the **slope CI to exclude zero in the improving (negative) direction** *and* the
**treatment-minus-control delta to favor treatment**. Slopes below are OLS on position 6–30 with
**Newey-West (Bartlett, lag 3) HAC** standard errors; Mann–Kendall (the pre-registered nonparametric
option) is reported alongside.

| Arm | metric | slope ($/task) | HAC 95% CI | CI excludes 0? | Mann–Kendall p | mean $/task |
|---|---|---|---|---|---|---|
| A (treatment) | total | **+0.0233** | [+0.0003, +0.0463] | yes — **wrong (worsening) direction** | 0.216 | 3.418 |
| A (treatment) | effector | **+0.0223** | [−0.0008, +0.0455] | no (includes 0) | 0.216 | 3.374 |
| B (control) | total | −0.0129 | [−0.0443, +0.0186] | no (flat) | 0.726 | 2.937 |
| B (control) | effector | −0.0126 | [−0.0437, +0.0185] | no (flat) | 0.797 | 2.888 |

**Treatment-minus-control slope delta** (the ADR-0017 attribution quantity):
- total: **+0.0361 /task** (95% CI [−0.0029, +0.0751]) — A's slope is *more positive* than B's.
- effector: **+0.0349 /task** (95% CI [−0.0038, +0.0737]).

**Level:** post-warmup, treatment is **+$0.481/task** more expensive on total and **+$0.485/task** on
effector cost; model/driver cost is a rounding error (**−$0.0046/task**, A slightly *lower*).

**Reading:** Neither arm shows the required negative slope. The treatment arm's point estimate is
**upward**, it is ~16 % more expensive than control in level, and the slope delta favors **control**.
The cost overhead is **not** in the driver/compose step (reflection runs in both arms for cost parity,
so model cost is ~equal by design and tiny) — it is in **effector** spend, consistent with craft
pushing the heavier multi-module SQLAlchemy stack it prescribes (§3). Criterion 1 fails decisively.

> Power note: at n=25 with this residual noise the HAC CI half-width on the slope is ≈ ±$0.023/task
> (~30 % of the back-to-front cost spread). The run is thin, but it is not a case of "a real decline
> we couldn't resolve" — the point estimate is the wrong sign.

## 2. Quality — **NOT MET** (Pass Criterion 2)

Paired per-instance tests (McNemar exact two-sided sign test). `effector_retries = 0` for all 60
tasks, so `first_pass == contract_passed`.

| Outcome | A pass | B pass | A-wins / B-wins (discordant) | exact p |
|---|---|---|---|---|
| **full-pass** (DoD ∧ contract) | 12/30 | 21/30 | 3 / 12 | **0.035** |
| contract-pass | 18/30 | 21/30 | 4 / 7 | 0.55 |
| first-pass | 18/30 | 21/30 | 4 / 7 | 0.55 |

- On **functional correctness** (the contract suite), treatment is **not better** than control and
  slightly worse (18 vs 21), not significant (p=0.55). There is **no upward first-pass trend** within A.
- The only significant gap is **full-pass** (p=0.035, 3 A-wins vs 12 B-wins) — and that gap is
  **entirely the DoD column**: all 12 B-wins are tasks where A's `contract_passed` but `dod_passed`
  was false. §3 shows those DoD failures are a gate artifact, not a code regression. **Corrected:
  after the gate fix, full-pass is A=18/30 vs B=21/30, McNemar p=0.55 (A≈B) — see Follow-up.**

Quality therefore **holds at best and does not improve** — Criterion 2 (which requires non-decreasing
quality *and* retries-down-or-first-pass-up) is not met. It is **not** a genuine "quality down".

## 3. Root cause of the DoD failures — **DoD-gate environment-isolation bug (treatment artifact)**

The deciding diagnosis. The fork the protocol-owner asked to resolve: *did craft over-constrain/bloat
the effector into genuinely worse code (real harm / no headroom), or is this a gate interaction that
fires when craft is present (treatment artifact)?* **It is the second.**

**The recorded failures do not reproduce from the persisted effector output.** Re-running each arm's
own test suite in the repo's own venv:

| instance (A failed DoD, B fully passed) | A contract | A recorded DoD | A own tests re-run (repo venv) | mechanism |
|---|---|---|---|---|
| quotes (pos 22) | 17/17 ✓ | `tests-unit: false` | **19 passed** | gate artifact |
| subscriptions (pos 23) | 32/32 ✓ | `tests-unit: false` | **29 passed** | gate artifact |
| habits (pos 25) | 18/18 ✓ | `tests-unit: false` | **28 passed (unit 13)** | gate artifact |

**The mechanism.** `run_instance_dod` (`harness/runner.py:142–158`) runs the instance's own tests with
**bare `python -m pytest tests`** — the *ambient* interpreter on PATH, **not** the repo's `.venv`. At
run time that interpreter had `fastapi` but **not `sqlalchemy`** installed. The contract suite is
unaffected because it boots the service via `bash run.sh` (the repo venv, which *has* `sqlalchemy`),
which is why **contract passes 17/17 while DoD fails on the same commit**. The failure is a `pytest`
**collection error** (`conftest.py: from sqlalchemy import … → ModuleNotFoundError`) → non-zero exit →
`tests-unit: false`. Reproduced directly: the same gate command under an ambient interpreter without
`sqlalchemy` fails to collect; under the repo venv it passes.

**The DoD failures track stack choice, not position — a perfect split:**

| group | n | used SQLAlchemy | DoD pass |
|---|---|---|---|
| A repos, fastapi-only | 20 | no | **20 / 20** |
| A repos, SQLAlchemy ORM | 10 | yes | **0 / 10** |
| B repos (all) | 30 | no | 29 / 30* |

\*The single B DoD failure (invoices, pos 30) is a contract boot failure (0/1), an unrelated cause.

**Craft caused the stack switch (so the artifact is treatment-correlated).** The reused craft
`fastapi-sqlite-scaffold` *explicitly prescribes the SQLAlchemy ORM stack* — its body specifies
`models.py # SQLAlchemy ORM models`, a `requirements.txt` of `fastapi / uvicorn / sqlalchemy /
pydantic`, and the exact multi-module `app/` layout A's back-half repos adopt. A's early repos used a
lean single-file `app.py` and incorporated the scaffold only loosely; by the back third the effector
followed the craft's canonical SQLAlchemy layout faithfully — and walked straight into the broken gate.
The craft body even **warns about this precise antipattern**: *"the process was launched with the
system Python rather than the project virtualenv … create and activate a venv."* The harness gate does
exactly what the craft warns against.

**Conclusion:** the "quality collapse" is **craft → SQLAlchemy stack → a gate that tests under the
wrong interpreter**. The effector's code in those 10 tasks is **functionally correct** (contract suites
pass; the repos' own tests pass under their venv). Under a correctly-isolated gate (one that uses the
repo venv, as the craft itself instructs), those tasks would have passed DoD. This is a **treatment
artifact**, not genuine craft harm — but note it is *triggered by* a real, craft-induced change to the
effector's output, so a corrected gate is required before any quality claim (positive or negative) can
be trusted.

## 4. Reuse & retrieval — real and influential, but **not load-bearing for a pass** (Criterion 3)

- **Reuse is real and rises:** A reuses 1 → 7 craft items across the run; the library grows to 10
  canonical items; `reuse_is_real = true`.
- **It is not a retrieval miss (G2):** Run A retrieval diagnostic — curated recall **1.00**;
  incorporation∩gold **recall 0.83**, **precision 0.99**. The driver finds and selectively
  incorporates the right craft.
- **It demonstrably changed the output (G3 mechanism):** the scaffold craft moved the effector onto
  the SQLAlchemy multi-module layout (§3) — craft materially altered effector instructions, as
  Criterion 3 asks. But Criterion 3 also requires the **cost drop to trace to reuse**, and there is no
  cost drop or quality gain to trace. So the "reuse is real" sub-condition holds while the
  benefit-attribution sub-condition fails.

**On the reuse dose-response (the pre-analysis "decisive within-arm signal").** It is real in the data
but **confounded**, so it is *not* clean evidence of harm (and after the §3 gate fix it attenuates to
88 % vs 22 %, the residual being tier confounding — see Follow-up):

| reuse bucket (Run A, post-warmup) | n | full-pass |
|---|---|---|
| reuse < 3 | 16 | 10 (62 %) |
| reuse ≥ 3 | 9 | 0 (0 %) |

Breakdown of the 9 reuse≥3 failures shows two confounds, not a causal craft-harm channel:
- **3** (accounts, playlists, coupons) — **hard-tier contract misses** (DoD passed; genuine
  business-rule gaps), reuse≥3 only because hard tasks retrieve more recipes;
- **4** (shipments, inventory, appointments, invoices) — **hard-tier**, contract miss **and** the
  SQLAlchemy gate artifact;
- **2** (tickets, venues) — **gate artifact only** (contract passed, DoD artifact).

So reuse≥3 co-occurs with **(i) harder tasks** and **(ii) the SQLAlchemy stack that tripped the gate**.
The negative dose-response is explained by tier difficulty + the §3 artifact — **not** by craft
causally degrading outputs. Reported honestly as a confound, not a finding of harm.

## 5. Security — **MET** (Criterion 4)

Zero `security_events`, zero `human_interventions` across all 60 tasks; `security_controls_held = true`
in both arms. No high-severity event, policy bypass, or unapproved high-impact action.

---

## Criteria summary

| # | Pre-registered Pass Criterion | Verdict | Basis |
|---|---|---|---|
| 1 | Cost slope negative (CI excludes 0) **and** delta favors treatment | **FAIL** | A slope +0.023/task; treatment +$0.48/task vs control; delta favors control |
| 2 | Quality non-decreasing; retries↓ or first-pass↑ | **NOT MET** | contract A≤B (p=0.55), no first-pass uptrend; "full-pass down" is artifact (§3) |
| 3 | Reuse real **and** cost drop traces to it | **NOT MET** | reuse real & influential & well-retrieved, but no cost/quality benefit to attribute |
| 4 | Security controls hold | **MET** | no security events, interventions, or bypasses |

**Pass needs all four → FAIL.** The decisive, robust negative is Criterion 1 (no cost compounding);
Criteria 2–3 confirm no quality or reuse *benefit*. The eye-catching harm signals are artifact/confound.

---

## What this does and does not establish (residual risks & limitations)

- **Robust:** in this domain/model/mechanism, craft reuse delivered **no cost reduction and no quality
  improvement** over a no-memory control, and added cost. This is the trustworthy negative.
- **Corrected:** the "quality collapse / net-harmful reuse" reading is **not** supported — it is a DoD
  gate testing under the wrong interpreter (§3) plus tier confounding (§4).
- **A confound that the corrected gate must settle:** craft *did* change effector behavior (heavier
  stack). Whether that change is net-neutral, mildly costly, or beneficial **cannot be read off this
  run** until the gate isolation bug is fixed and the back third is re-measured. Today the only
  defensible statement is "no benefit observed," not "harm observed."
- **Reconstruction:** the dataset was reconstructed from durable traces after a checkpoint rewound the
  live ledger; Run B ran as 5 parallel control shards + 5 serial (valid — control tasks are
  independent; pins/order identical to A). The per-instance repos, traces, DoD spans, and craft library
  used for §3–§4 are the persisted live artifacts, not re-synthesized.
- **External validity:** single domain, single model, n=30, one incorporation design (ADR-0017 names
  this as the standing residual). Nothing here generalizes beyond the stated scope.
- **Thinness:** n=25 post-warmup is autocorrelated and underpowered for small effects; the slope CIs
  are wide. The conclusion rests on the *sign and level* of cost (clear) plus the *absence* of any
  benefit channel, not on a tight effect-size estimate.

## For the operator (the strategic call is yours)

The mechanism, not just the verdict: **the most reuse-heavy craft moved the effector onto a heavier,
craft-prescribed stack; that stack was functionally correct but tripped a harness gate that tests under
the ambient interpreter instead of the project venv.** The gate-isolation bug (`harness/runner.py`:
run the gate under the repo venv) **is now fixed** (`_gate_python` + regression test) and positions
21–30 **re-scored** — corrected quality is **A ≈ B** (full-pass 18/30 vs 21/30, p=0.55), confirming no
genuine quality regression (see Follow-up). The cost result (Criterion 1) was always independent of
that bug and stands — and the follow-up ties it to one cause: **craft prescribed an over-heavy stack
that cost ~+$0.74/task (paired) and bought no correctness.** Net: **no compounding on cost or quality
in this domain.**

---

### Appendix — reproduce the key checks

```bash
# Stats (slopes, McNemar, dose-response) — prints the tables in §1, §2, §4:
python3 - < /dev/stdin   # (the T-1.4 analysis script; numpy+scipy)

# Root-cause reproduction (§3): contract passes via venv, DoD fails via ambient python
cd .context/phase_minus_1_fullrun/runA/quotes/repo
.venv/bin/python -m pytest tests -q          # -> 19 passed   (repo venv has sqlalchemy)
python3 -m pytest tests -q                    # -> collection error: ModuleNotFoundError: sqlalchemy

# Stack-vs-DoD cross-tab (§3): 10/10 SQLAlchemy A-repos fail DoD, 20/20 fastapi-only pass.
```

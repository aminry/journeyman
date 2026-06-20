# ADR-0013: Portable craft is model/effector-version-scoped

- **Status:** Accepted
- **Date:** 2026-06-20
- **Deciders:** Human operator, Claude Code (Opus 4.8)
- **Tags:** architecture, memory, evals, coding-effector

## Context

Plane B's value is portable orchestration craft — prompts, playbooks, TaskSpec
patterns, decomposition recipes, and catalogued effector failure modes (ADR-0005,
SPEC §8/§11A). But prompts are **brittle across model versions** (large accuracy
swings from non-semantic changes; real-world migrations costing hundreds of
engineering hours), and a playbook that works *around* a current effector
weakness becomes counterproductive when the effector improves or is swapped
(ADR-0005 makes the effector swappable). The spec re-measures model *capability
scores* on updates (§16) but never re-validated the *craft library* against a new
model/effector. Craft was implicitly treated as model-independent; it is not —
"craft" can become "anti-craft" after an upgrade.

## Decision

Treat every craft artifact as **scoped to the model / effector / embedding
versions it was validated against**:

- Skill manifests gain a `validated_against` block (model id(s), effector
  version, embedding model) and a `last_validated` timestamp.
  `memory/skill-manifest.schema.json` makes the manifest an executable contract.
- A material **model, effector, or embedding change is a regression-guard
  trigger for the craft library**: affected skills re-run their evals; those that
  regress are **quarantined** (not retrieved) pending repair or re-validation,
  rather than silently used.
- Retrieval never returns craft whose `validated_against` no longer matches the
  active model/effector without a passing re-validation.

## Consequences

- **Positive:** craft cannot silently become anti-craft after an upgrade; the
  swappable-effector claim becomes real (swap → re-validate, not blind reuse);
  the retrieval surface stays trustworthy.
- **Negative / costs:** model/effector upgrades now carry a craft-revalidation
  cost; quarantine may temporarily shrink available craft.
- **Risks & mitigations:** revalidation cost discourages upgrades → batch it and
  prioritize high-`uses` skills; undetected staleness → `validated_against` and
  `last_validated` are required fields, checked by the gate.

## Alternatives considered

- **Treat craft as model-independent** — rejected: contradicted by
  prompt-brittleness evidence.
- **Re-measure only capability scores** — rejected: scores gate routing, not the
  craft content that encodes model-specific workarounds.

# dream/  (SEED — conservative, PROTECTED via ADR-0008)

The off-duty consolidation job. Hand-written and conservative; not self-built.

Build here (SPEC §7):
- Replay episodes → consolidate into generic facts; cluster failures into avoid-patterns.
- **Distillation boundary** — the Plane A↔B gate: generic & project-stripped → agent memory; project-specific → stays in the project brain.
- **Skill-library maintenance** — dedupe, repair flaky, deprecate unused, contract checks.
- Memory maintenance (dedupe, resolve conflicts, prune, re-embed) and deliberate **forgetting**.
- Eval-gated, versioned (git-snapshot) commits — revertible.

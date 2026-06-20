# governance/  (SEED)

Build here (SPEC §6, ADR-0007/0008):
- **Budget ledger** + **hard cost ceiling** + **cost-per-task viability gate** (halt if cost/task isn't falling while quality holds).
- **Milestone gating + revenue faucet**; **circuit breaker** on floor/ceiling breach.
- **Human approval queue** — routed by *task class* (irreversible/paid/publish/novel), not self-reported confidence.
- **Credential & capability scoping** — least privilege per task, revocable.
- **Regression guard + rotating eval harness** — held-out, growing, adversarial, with human spot-checks. Every self-modification passes before commit; failures roll back.

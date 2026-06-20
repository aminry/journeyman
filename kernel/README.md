# kernel/  (SEED — PROTECTED)

The substrate. **Protected**: the system may *propose* changes here but a human must approve them (ADR-0008).

Build here:
- **Agent runtime** — the single-agent work loop (SPEC §12). One model decision per step; the kernel (not the model) moves money, runs code, writes durable stores, and enforces the Definition-of-Done gate.
- **Model router** — registry of endpoints with measured capability scores + cost; `select()`/`call()`; fallback/escalation; logs every routing decision (feeds the Phase-1 routing learner).
- **Tool registry** — uniform `use_tool(name, args)`; declares required capabilities for credential scoping.
- **Execution sandbox** — container/microVM, no ambient credentials.
- **Event bus + trace log** — spans for every tool/model/store call, cost attached (SPEC §14).

Meta-tools live here (SPEC §5): `select_model, use_tool, register_tool, drive_coding_effector, write_skill, run_tests, query_memory, write_memory, propose_to_shared, request_human_approval, spawn_subtask, emit_event, scaffold_project, update_code_graph, check_definition_of_done`.

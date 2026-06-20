# tools/  (SEED)

Primitive tools (shell, file I/O, web fetch, code exec) and registered skill-tools, behind the kernel's `use_tool` interface.

- **Coding-effector adapter** (ADR-0005, SPEC §11A): drives Claude Code via a **spec-in / verified-out** contract. Input: TaskSpec + acceptance tests. Output accepted only when the Definition-of-Done gate passes. Boundary instrumented (cost, transcript, retries, git diff) as an `effector_session` span. Swappable behind a stable `drive_coding_effector(spec)` interface.
- Every tool declares required capabilities so credentials stay least-privilege.

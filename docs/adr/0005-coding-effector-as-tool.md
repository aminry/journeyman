# ADR-0005: Delegate coding to an effector driven as a tool

- **Status:** Accepted
- **Date:** {{YYYY-MM-DD}}
- **Deciders:** {{WHO_DECIDED}}
- **Tags:** architecture, coding, tools

## Context

Rebuilding an agentic coding harness (file editing, repo navigation, sandboxed execution, test running) inside the kernel is wasted effort; a strong harness (Claude Code) already exists. The platform's distinctive value is the layer above a coder. But "an engineer agent driving a coder agent" risks re-introducing multi-agent coordination failure.

## Decision

Coding is delegated to a **coding effector (Claude Code), driven as a tool, not a second agent**, via a **spec-in / verified-artifact-out** contract: the agent sends a TaskSpec + acceptance tests; the effector works in the target repo; its output is accepted **only when the Definition-of-Done gate passes** (its "done" is untrusted until verified). The boundary is instrumented (cost, transcript, retries, git diff) as an `effector_session` span. The effector is swappable behind a stable interface. Trivial edits follow the capability ladder (done directly/cheaply); full sessions are reserved for substantial work.

## Consequences

- **Positive:** no harness rebuild; "single agent" preserved; platform value concentrated above the coder; what compounds becomes portable orchestration craft.
- **Negative / costs:** an external black box in the trace spine; a token tax if misused (thin pass-through).
- **Risks & mitigations:** seam coordination failures and black-box spend — mitigated by the verified contract and mandatory boundary instrumentation; thin pass-through — mitigated by the capability ladder and the "what is the driver adding?" test.

## Alternatives considered

- **Build coding into the kernel** — rejected: large effort duplicating a strong existing tool.
- **Treat the effector as a peer agent in conversation** — rejected: re-creates the coordination failures of ADR-0003.

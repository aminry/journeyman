# Untrusted Content Pipeline

All web pages, files, issue bodies, PR descriptions, retrieved documents, tool
outputs, user-uploaded content, external API responses, and coding-effector
transcripts are untrusted unless explicitly produced by the kernel policy layer.

## Pipeline

1. **Ingest with source label.** Record source type, URL/path/tool, timestamp,
   task id, and trust level.
2. **Normalize.** Decode common encodings, remove hidden control characters
   where possible, preserve a raw reference only in restricted storage.
3. **Scan.** Check for direct injection, indirect injection, encoded override
   attempts, hidden HTML/Markdown, data-exfiltration markup, forged tool
   observations, and secret-like values.
4. **Quarantine.** Store raw content outside model-visible context. The model
   sees only labeled excerpts or summaries.
5. **Summarize if needed.** A low-privilege reader may summarize content. That
   reader has no write, deploy, credential, or external-side-effect tools.
6. **Separate instructions from data.** Prompts must label untrusted content as
   data to analyze, never instructions to follow.
7. **Action screen.** Before any tool call influenced by untrusted content, a
   policy check compares the proposed action to the original operator task. If
   the action is not necessary for the original task, deny or request approval.
8. **Trace.** Log source labels, scan result, summary reference, and action
   screening result.

## Never Allowed

- Untrusted content cannot define system, developer, tool, memory, approval, or
  security policy instructions.
- Untrusted content cannot request credentials, deployment, payment, publishing,
  deletion, external messages, or policy changes.
- Untrusted content cannot be written to durable memory without passing
  `security/memory-admission-policy.md`.
- A tool call cannot be authorized solely because untrusted content asked for it.

## Red-Team Coverage

The prompt-injection suite must include:

- direct override attempts;
- indirect instructions in code comments and docs;
- base64/hex/Unicode-obfuscated instructions;
- Markdown and HTML exfiltration payloads;
- forged "Thought:", "Observation:", or tool-result text;
- delayed/persistent instructions intended for future sessions;
- RAG poisoning cases that rank highly in retrieval.

## Failure Handling

Fail closed when:

- source label is missing;
- scan fails or times out;
- content classification is ambiguous and the proposed action is high impact;
- action screening cannot compare against the original task;
- audit logging fails.

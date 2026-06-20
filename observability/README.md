# observability/  (SEED schema; dashboards Phase 1)

The trace spine (SPEC §14). Structured append-only events with trace IDs per task; spans for every tool/model/store call and the `effector_session` boundary; decision provenance (what was retrieved and why). Cost on every span, rolled up to the **cost-per-task curve** — the master metric.

Seed: event schema + writer + a way to replay a trace. Phase 1: dashboards over a columnar store (DuckDB/ClickHouse).

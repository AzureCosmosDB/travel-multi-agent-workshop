# Architecture Decision Records (ADR)

This log records every architectural decision for the Agent Analytics and Optimization initiative. Each ADR captures the context, the options considered, the **evidence** behind the decision, the decision itself, and its consequences.

## Process

- New decision → copy `adr-template.md` to `adr-NNNN-short-title.md` (next number), fill it in, set status **Proposed**.
- When agreed → set status **Accepted** with the date.
- If a later decision changes an earlier one → add a new ADR and set the old one's status to **Superseded by ADR-NNNN** (do not delete history).
- Every feasibility claim in an ADR must cite evidence: a file/line, a command run and its observed output, an authoritative doc URL, or a live test result. Untested claims must be labelled as open items, not asserted.

## Index

| ADR | Title | Status | Date |
|-----|-------|--------|------|
| [0001](adr-0001-optimization-loop-surface-architecture.md) | Optimization-loop surface architecture: reverse-ETL to Azure Cosmos DB + web-app apply-loop | Accepted | 2026-07-07 |
| [0002](adr-0002-open-analytics-schema-and-instrumentation.md) | Adopt the Open Analytics Schema, fix/extend instrumentation, and define the Fabric mirror set | Proposed | 2026-07-07 |
| [0003](adr-0003-source-pluggable-ingestion-otel-alignment.md) | Source-pluggable ingestion; OTel GenAI semconv as interop standard; Open Analytics Schema as first-party normalization layer | Proposed | 2026-07-07 |
| [0004](adr-0004-data-generation-redesign.md) | Data-generation redesign: cheap, reproducible, real-enough analytics data (fixture-first + optional live) | Proposed | 2026-07-07 |
| [0005](adr-0005-dependency-modernization.md) | Modernize the workshop dependency stack (langchain/langgraph/openai to latest majors) | Accepted | 2026-07-07 |
| [0006](adr-0006-unify-agent-memory-toolkit-v2.md) | Adopt `agent_memory_toolkit_v2` as the unified baseline; land v2 + modernization + analytics in one PR to `main` | Accepted | 2026-07-07 |

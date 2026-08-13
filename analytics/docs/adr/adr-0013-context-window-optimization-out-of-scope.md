# ADR-0013: Context-window optimization is out of scope — observability owns the visibility, existing levers own the action

- **Status:** Accepted
- **Date:** 2026-08-13
- **Deciders:** Mark Brown
- **Related:** [vision](../vision/agent-analytics-and-optimization-vision.md), [charter](../vision/charter.md), [ADR-0010](adr-0010-agent-centric-data-driven-analysis-engine.md) (lens-vs-policy engine), [ADR-0008](adr-0008-optimization-apply-loop-model-selection.md)

## Context

A stakeholder asked whether the Agent Analytics & Optimization plane **detects or recommends
context-window optimizations for agents** — i.e., a card that analyzes each agent's prompt /
context size, flags context bloat or near-limit conditions, and recommends context-window
actions (truncation, sliding window, tighter recall `top_k`, earlier summarization).

It does not, and this ADR records the deliberate decision **not** to build one here, so the
boundary and its rationale aren't re-litigated each time the question comes up.

The forces:

- The plane's differentiator is the **closed govern → apply → measure loop** with Cosmos as
  the operational system of record and Fabric as the analytical/optimization SoR — *not*
  trace-level visibility.
- The **action levers that shrink context already exist** as first-class, governed policies.
- Per-call context/token size is exactly the kind of trace-grain telemetry that **observability
  and eval frameworks already own**, and LangSmith is already wired into this codebase.

## Decision drivers

- Keep the plane focused on **apply-able, measured** optimizations, not on re-surfacing
  telemetry that observability tooling already provides.
- Honor the engine's organizing principle from ADR-0010: *"a lens points; the policies act."*
  A context-window detector would be a **redundant lens** — it would point at the same agents
  the existing policies already act on.
- Avoid scope creep and the maintenance cost of a card whose marginal value is low.

## Options considered

### Option A — Add a dedicated context-window / input-token-budget recommendation card
Detect agents/turns whose input context is large or near the model limit and recommend a
context-window action. — **Verdict: Rejected.** It is a diagnostic **lens**, not a new
apply-able policy: every remedy it would suggest (prune stale memories, summarize sooner,
lower recall `top_k`, tier the model) is already a shipped lever. Its *visibility* half
duplicates what LangSmith already surfaces per call, and its *loop-closing* half (the measured
effect of trimming context) is already captured by memory-retention's avoided-input-token
telemetry. Net new value ≈ 0; net new surface area > 0.

### Option B — Do not build it; rely on existing policies + observability
Context **reduction** is delivered by memory-retention (fewer stale memories in recall) and the
runtime summarizer, plus recall `top_k` and capability-tiered model selection. Context
**visibility** (per-call token/context size) is delegated to the already-integrated LangSmith
tracing and any OTel-based observability. — **Verdict: Chosen.**

### Option C — Add a guardrail only for hard context-limit failure modes
If small-window models or real truncation/over-limit errors appear, add a **guardrail** that
extends existing levers (e.g., cap recall `top_k`, force earlier summarization) rather than a
standalone detector. — **Verdict: Deferred** (see *Open items / revisit trigger*). Not built
today because the failure mode is not observed and it would be an extension of existing
policies, not a new class of optimization.

## Evidence

- **The recommendation catalog is exactly five cards, none of which analyze prompt/context
  size.** `build_recommendations()` returns `model-selection`, `memory-retention`,
  `tool-call-dedup`, `cost-per-outcome`, and `agent-path-cost`
  (`02_completed/python/src/app/services/optimization_recommendations.py`, `build_recommendations` ~L211;
  the two diagnostics at `build_cost_per_outcome_diagnostic` ~L1016 and
  `build_agent_path_diagnostic` ~L1058). *(verified)*
- **No context-window detector exists in code.** A repository grep for
  `context.?window | token.?budget | truncat | max_tokens | prompt.?size` across
  `02_completed/python` returns only generic per-turn `input_tokens` accounting — no
  context-window, truncation, or prompt-size logic. *(verified — command run 2026-08-13)*
- **Context reduction is already delivered and measured.** memory-retention records the input
  tokens each pruned-memory drop avoids as a `recall_pruned_avoided` ApiEvent
  (`optimization_recommendations.py` ~L615, `"avoided_input_tokens"`), aggregated into the
  card's measured saving in `_memory_recall_savings` (~L644). The runtime summarizer
  additionally bounds conversation history (~every 10 turns). *(verified)*
- **Observability is already integrated.** Every MCP tool is `@traceable`
  (`02_completed/mcp_server/mcp_http_server.py:6` `from langsmith import traceable`, applied
  throughout), with optional `LANGCHAIN_*` tracing. Per-call token counts, latency, and full
  traces are LangSmith's native surface; developers can monitor/alert on them there today.
  *(verified in code; per-call token visibility is standard LangSmith product behavior —
  <https://docs.smith.langchain.com/>)*
- **Design principle.** "It has **no Apply button** … A lens points; the policies act."
  (`01_exercises/workshop/Module-08.md`, Activity 5.) A context-window card would be a lens
  aimed at agents the policies already cover. *(verified)*

## Decision

We will **not** build a context-window optimization detector or recommendation card in the
Agent Analytics & Optimization plane.

- **Context visibility** (per-call context/token size, near-limit conditions) is delegated to
  the already-integrated **observability/eval tooling (LangSmith)** and any OTel-based stack.
- **Context reduction** is delivered by the **existing governed levers**: memory-retention and
  the runtime summarizer, complemented by recall `top_k` and capability-tiered model selection.

A dedicated card would be a redundant diagnostic lens: it adds no new apply-able action beyond
the existing policies and duplicates visibility observability already provides.

## Consequences

- **Positive:** Keeps the plane focused on its differentiator — the closed, governed
  apply/measure loop — instead of re-implementing trace dashboards. Less surface to build,
  test, mirror across `01_exercises`/`02_completed`, and maintain. No confusing "insight-only"
  card whose only remedies are policies the portal already exposes.
- **Negative / costs:** There is no single in-portal card that says "agent X's context is
  bloated"; a developer reads that from LangSmith/traces, then reaches for the existing
  policies. The context/observability story is split across two surfaces (portal for
  apply/measure; LangSmith for per-call inspection).
- **Risks:** If the app later runs on small context-window models or begins hitting real
  truncation/over-limit errors, the absence of an in-loop guardrail could bite — mitigated by
  the revisit trigger below.

## Open items to verify

- **Revisit trigger for Option C:** only if we observe hard context-limit failures (truncation,
  provider over-limit errors, or a move to small-window models). At that point, prefer a
  **guardrail** that extends existing levers (cap recall `top_k`, summarize earlier) over a
  standalone detector, and validate it against real truncation telemetry before building.

## References

- [Agent Analytics & Optimization vision](../vision/agent-analytics-and-optimization-vision.md); [charter](../vision/charter.md)
- [ADR-0010 — agent-centric, data-driven analysis engine](adr-0010-agent-centric-data-driven-analysis-engine.md) ("a lens points; the policies act")
- [ADR-0008 — optimization apply-loop: model selection](adr-0008-optimization-apply-loop-model-selection.md)
- memory-retention lever & in-query exclusion: [AzureCosmosDB/AgentMemoryToolkit#36](https://github.com/AzureCosmosDB/AgentMemoryToolkit/issues/36)
- LangSmith tracing/observability: <https://docs.smith.langchain.com/>

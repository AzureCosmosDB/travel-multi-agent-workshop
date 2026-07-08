# ADR-0007: Analytics instrumentation on v2 — re-wire Cosmos `Debug` capture now, add OpenTelemetry later

- **Status:** Accepted
- **Date:** 2026-07-08
- **Deciders:** @markjbrown (mjbrown)
- **Related:** ADR-0002 (Open Analytics Schema), ADR-0003 (source-pluggable ingestion / OTel alignment), ADR-0006 (adopt v2 as unified baseline)

## Context

ADR-0006 made `agent_memory_toolkit_v2` (supervisor + sub-agents-as-tools, `azure-cosmos-agent-memory` SDK) the unified baseline. Rebuilding the analytics pillars on v2 (ADR-0006 Phase 3) requires an analytics signal for **tokens / agent-selection / cost / hand-offs**. Investigation of v2 established what signal exists.

## Decision drivers

- Restore the token / agent / cost analytics pillars on v2 with the smallest, lowest-risk change.
- Reuse the analytics stack already built (Open Analytics Schema, Fabric mirror, Power BI, SQL endpoint, enricher — all read Cosmos documents).
- Keep the door open to OpenTelemetry as an additional, standards-aligned source (ADR-0003), without blocking analytics on it.

## Options considered

### Option A — Re-wire the (orphaned) Cosmos `Debug` capture into v2's completion path
v2 already ships `store_debug_log` and `store_debug_log_from_response`, but they are **never called** — the completion path (`chat_event_generator`) writes no `Debug` logs. Wire capture into the existing `astream_events` loop and persist via `store_debug_log`. **Verdict:** chosen — minimal change, Cosmos-native, matches the entire existing analytics stack.

### Option B — Instrument OpenTelemetry spans + a span sink now
Emit GenAI-semconv spans and export to Azure Monitor / App Insights (new resource + cost) or a custom Cosmos exporter, then rework Power BI/SQL to read spans. **Verdict:** deferred — high effort, new telemetry surface (KQL) diverging from the Cosmos→Fabric→Power BI stack, and blocks analytics on a from-scratch build. Kept as a **later, additive** source per ADR-0003's source-pluggable design.

## Evidence

- **v2 emits neither signal by default:** OTel is packages + a **commented-out** `configure_azure_monitor()` (`travel_agents_api.py:83`) with zero span code (no `get_tracer`/`set_attribute`/`start_as_current_span` anywhere). `store_debug_log_from_response` / `_post_response_background` are orphaned (never called). Confirmed live: a full 12-persona generator run produced **Debug: 0, ApiEvents: 0**.
- **v2's sub-agents are tools, not nodes:** `find_places` and `create_or_update_itinerary` are invoked via `on_tool_start`, not `on_chain_start`. So delegations/hand-offs must be derived from **tool calls**, not chain nodes (first re-wire attempt produced `agent_path=supervisor, handoff_count=0` even when `find_places` ran; deriving from tools fixed it).
- **The memory pillar already has rich Cosmos-native data** via the SDK (487 memories with `type`/supersession/`source_fact_ids`, 39 summaries, 47 counters after one run) — no instrumentation needed there.

## Decision

Implement Option A now; defer Option B. Specifically:
- Capture token usage (native `usage_metadata` + fallback `response_metadata.token_usage`), model/finish/fingerprint, tool calls, and sub-agent delegations from v2's `astream_events` stream inside `chat_event_generator`, and persist one `Debug` log per turn via `store_debug_log`.
- Extend `store_debug_log` with optional `agent_path` + `handoff_count` (additive propertyBag entries) — under the supervisor model these mean the supervisor→sub-agent **delegation chain** and its length.
- Thread the completion's `debug_log_id` into the generator so the returned message's `debugLogId` matches the stored log (keeps `completiondetails/{debugLogId}` working).

## Consequences

- **Positive:** token/agent/cost/hand-off pillars restored on v2 with a localized change; Cosmos-native, so the existing Fabric mirror + Power BI + SQL + enricher work unchanged; hand-off analytics is arguably *more* interesting under the supervisor model (delegation depth per user request).
- **Negative / costs:** the `Debug` schema is bespoke (not OTel semconv); "agent_path" semantics differ from the classic multi-agent graph and must be documented for the analytics/Power BI layer.
- **Risks:** token fields depend on `usage_metadata` populating under `astream_events` — mitigated by the dual native/nested extraction and verified live (total 23025; input 22211; output 814; cached 15488).

## Open items to verify

- Regenerate the `v2_analytics` baseline with instrumentation active so `Debug` logs exist for the full persona set (the earlier run predated the re-wire).
- Confirm the enricher / Power BI read the v2 `Debug` propertyBag (agent_path/handoff_count) without change.
- Trip-planning pillar: `Trips` were intermittently 0 (itinerary agent called `update_trip` on a missing `tripId` instead of `create_new_trip`) — track and fix separately.

## References

- Implementation: `02_completed/python/src/app/travel_agents_api.py` (`_extract_msg_usage`, `_persist_turn_debug_log`, `chat_event_generator`), `services/azure_cosmos_db.py` (`store_debug_log` agent_path/handoff_count).
- ADR-0003 (source-pluggable ingestion / OTel), ADR-0006 (unify v2).

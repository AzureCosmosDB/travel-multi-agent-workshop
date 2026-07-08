# ADR-0002: Adopt the Open Analytics Schema, fix/extend instrumentation, and define the Fabric mirror set

- **Status:** Proposed
- **Date:** 2026-07-07
- **Deciders:** Mark Brown (@markjbrown), with agent analysis
- **Related:** `../vision/…vision.md`, `../charter.md`, ADR-0001

## Context

The workshop covers all six analytics pillars (Levels 1–3 + one L4 slice). All pillars must ride one pipeline: **operational state in Cosmos → Fabric Mirroring → an open analytical model → gold tables per pillar → surfaces**. This ADR fixes that model and the instrumentation that feeds it.

A **live audit of the deployed Azure Cosmos DB** (`cosmos-kfpokdh52vbec` / `TravelAssistant`, inspected via Entra ID on 2026-07-07) corrected key assumptions: the operational telemetry the app *appears* to capture is largely **empty or opaque**, so this cannot be a "just mirror what exists" decision.

## Decision drivers

- One framework-agnostic analytical model across all six pillars (the vision's Open Analytics Schema).
- Only mirror data that is **real, analytically useful, and cost-justified**.
- Ground every "we have this data" claim in observed rows, not code presence.
- Keep Azure Cosmos DB as the operational system of record (ADR-0001).

## Options considered

### Option A — Mirror existing containers as-is and model in Fabric
**Rejected.** The live audit shows the telemetry containers are unusable as-is (see Evidence): `Debug` analytical fields empty, `ApiEvents`/`Summaries` empty, `Checkpoints` opaque msgpack.

### Option B — Adopt the Open Analytics Schema as the canonical model; fix/extend instrumentation to emit its primitives into purpose-built Cosmos containers; mirror only the useful subset *(chosen)*
Map primitives to existing containers where data is real; add/repair emission where it is missing; exclude opaque/empty containers from mirroring.

### Option C — Rely on external telemetry (LangSmith / OpenTelemetry) as the analytics source
**Rejected as the primary path.** Not mirrored into Fabric, external dependency; conflicts with the vision's "operational-state-first" and Cosmos-as-SoR. May *enrich* later (the vision allows OTel/OpenInference enrichment). **See ADR-0003**, which resolves the follow-up ("does this make the job harder / would other frameworks adopt LangSmith or OTel?"): the interop target is **OpenTelemetry GenAI semconv** (not LangSmith), the Open Analytics Schema is aligned to it, and ingestion is made source-pluggable — so OTel/OpenInference can be added later as adapter sources without re-modeling.

## Evidence (live data, 2026-07-07)

Container counts and shapes (Entra-ID query of the deployed account):

| Container | Count | State |
|---|---|---|
| `Memories` | 265 | **Real** — full memory schema, `embedding[1024]` |
| `Sessions` | 86 | **Real** — `activeAgent`, `createdAt`/`lastActivityAt`, `status`, `messageCount` |
| `Messages` | 690 | **Real** — `role`, `content`, `toolCalls`, `embedding[1024]`, `ts` |
| `Trips` | 35 | **Real** — nested `days[]` with `placeId`s |
| `Users` | 16 | **Real** |
| `Places` | 2937 | **Real** — `embedding[1536]` |
| `Debug` | 334 | **Fields empty** — see below |
| `ApiEvents` | 0 | **Empty** |
| `Summaries` | 0 | **Empty** |
| `Checkpoints` | 19,472 | **Opaque** base64 msgpack (`type:"msgpack"`) |

`Debug` (client-side aggregate of all 334 docs): `total_tokens=0` for 334/334; `agent_selected="Unknown"` 334/334; `previous_agent="Unknown"` 334/334; `transfer_success=false` 334/334; only `model_name="gpt-4.1-mini-2025-04-14"` populated. Root causes (code-verified):
- Tokens: read from `response_metadata.token_usage` (`travel_agents_api.py:687-690`); model runs `streaming=True` (`azure_open_ai.py:41`) → `response_metadata.token_usage` is empty, so the extractor records `total_tokens=0`. **✅ Confirmed by live test (2026-07-07, langchain-openai 1.3.3):** with `streaming=True`, `response_metadata['token_usage'] = {}`. **Correction:** adding `stream_usage=True` does **not** repopulate that field (still `{}`); however `msg.usage_metadata` **is** populated in all variants (incl. plain `streaming=True`). The real fix is a **reader change** — read `msg.usage_metadata` (`input_tokens`/`output_tokens`/`total_tokens`; cached via `input_token_details.cache_read`) — not a model-config change. (Non-streaming also carries `latency_checkpoint` in `response_metadata` — a candidate latency source for Pillar 1.)
- Agent/transition: `agent_selected`/`previous_agent`/`transfer_success` only set on detecting a `transfer_to_` tool call in the passed messages (`travel_agents_api.py:703-708`); that path isn't firing in practice.
- Shape: stored as an EAV `propertyBag` array of `{key,value,timeStamp}` — needs pivoting for analytics.

## Decision

1. **Adopt the vision's Open Analytics Schema (10 primitives) as the canonical analytical model** for this solution.
2. **Map primitives to real data where it exists:** `UserSession`/`WorkflowExecution` ← `Sessions` (+ derived outcome); `AgentStep` ← `Messages`; `MemoryEvent` target ← `Memories` + new retrieval events; Trips/Users/Places remain domain data.
3. **Fix and extend instrumentation to emit the missing primitives into Cosmos** (each its own follow-up, some their own ADRs):
   - **`TokenUsage`** — capture real per-call usage. **On the app's pinned `langchain-openai==0.3.3` this requires BOTH** (verified end-to-end 2026-07-07, PR #70): (a) set `model_kwargs={"stream_options": {"include_usage": True}}` on the model in `azure_open_ai.py` (under plain `streaming=True`, 0.3.3 leaves `usage_metadata=None`), and (b) read `msg.usage_metadata` instead of the empty `response_metadata.token_usage`. Required for Pillar 3. **Name fields to OTel GenAI semconv** (per ADR-0003): `gen_ai.usage.input_tokens` / `output_tokens`, cached via `gen_ai.usage.cache_read.input_tokens`.
   - **`AgentRun` / `AgentStep` / `AgentTransition`** — capture agent selected, previous agent, routing/handoff, and **per-turn latency** reliably (not only on transfer); Pillars 1/2.
   - **`ToolInvocation`** — per tool call (name, args summary, latency, success).
   - **`MemoryEvent`** — memory-retrieval events (which memories recalled, for which session/turn/query, similarity/salience) + outcome linkage; Pillar 4 depth.
   - **`EvaluationResult`** — persist evaluator outputs to a Cosmos container; Pillar 5.
   - **`Checkpoint`** — store *metadata only* (ids/timestamps/parent), not the msgpack blob, if needed at all.
   - **`WorkflowExecution`** — session-level outcome/completion labeling; Pillar 6.
   - Prefer **flat, analytics-friendly fields** over the EAV `propertyBag`, and **name fields to OTel GenAI semconv (`gen_ai.*`) where a counterpart exists** (per ADR-0003) so future OTel/OpenInference sources map 1:1.
4. **Fabric mirror set:** mirror `Memories`, `Sessions`, `Messages`, `Trips`, `Users`, `Places`, **plus the new/fixed telemetry containers** (working names: `AgentEvents`, `MemoryEvents`, `EvaluationResults`). **Do NOT mirror** `Checkpoints` (opaque, 19k+), `ApiEvents` (empty/unused), or `Summaries` (empty) unless a concrete need appears.
5. **Regenerate data after the instrumentation fixes** so Pillars 1/2/3 have real signals (couples to the data-generation redesign — separate ADR).

## Consequences

- **Positive:** one coherent model across all pillars; only real/useful data flows to Fabric; corrects a false "data already exists" assumption before it cost us; leverages existing real data (memory/sessions/messages) immediately.
- **Negative / costs:** real instrumentation work (token capture, transition/latency capture, new event emission) + a data regeneration pass; more Cosmos containers and more mirrored throughput.
- **Risks:** mirroring more containers increases RU/cost (to measure); instrumentation changes touch the hot path (`travel_agents_api.py`) and must not regress latency; outcome labeling (Pillars 5/6) needs a credible signal on synthetic data.

## Open items to verify

- ~~**Confirm the streaming→no-usage hypothesis by live test**~~ **✅ Done (2026-07-07); IMPLEMENTED + tested end-to-end (PR #70).** Root cause confirmed. **Version-accurate correction:** the initial probe used `langchain-openai 1.3.3` (where plain `streaming=True` populates `usage_metadata`), but the app pins **`0.3.3`**, where `streaming=True` leaves both `response_metadata.token_usage` **and** `usage_metadata` empty. The working fix (verified live: `total_tokens` 2618/3178/3412 vs 0 before) is **two parts**: (1) `model_kwargs={"stream_options": {"include_usage": True}}` on the model, and (2) read `msg.usage_metadata`. Evidence: `analytics/docs/verification/2026-07-07-token-capture.md`.
- **Measure the RU/cost impact** of mirroring the additional containers.
- **Finalize the new container set + partition keys** (align with existing `[tenant_id, user_id, session_id]` hierarchy where possible).
- **Confirm** whether the `01_exercises/evaluation` harness can/should write `EvaluationResult` to Cosmos.

## References

- `../vision/agent-analytics-and-optimization-vision.md` (Open Analytics Schema)
- `../charter.md` (Data readiness — verified live findings)
- Live audit: session artifact `inspect_cosmos.py` + aggregates (2026-07-07)
- Code: `02_completed/python/src/app/services/azure_cosmos_db.py`, `02_completed/python/src/app/travel_agents_api.py:649-735`, `02_completed/python/src/app/services/azure_open_ai.py:35-43`

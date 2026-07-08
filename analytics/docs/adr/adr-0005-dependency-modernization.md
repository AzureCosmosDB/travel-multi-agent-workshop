# ADR-0005: Modernize the workshop dependency stack (langchain / langgraph / openai to latest majors)

- **Status:** Accepted
- **Date:** 2026-07-07
- **Deciders:** Mark Brown (@markjbrown), with agent analysis
- **Related:** `../verification/2026-07-07-langgraph-1x-checkpointer-derisk.md`, ADR-0002 (instrumentation), ADR-0004 (data-gen). Builds on the four merged fixes (PRs #69–#72).

## Context

The app pins **major-versions-behind** libraries across the core stack (measured 2026-07-07):

| Package | Pinned | Latest | Gap |
|---|---|---|---|
| langgraph | 0.2.69 | 1.2.8 | major |
| langchain | 0.3.26 | 1.3.11 | major |
| langchain-core | 0.3.66 | 1.4.8 | major |
| langchain-openai | 0.3.3 | 1.3.3 | major |
| openai | 1.60.0 | 2.44.0 | major |
| langchain-mcp-adapters | 0.1.7 | 0.3.0 | minor |
| langgraph-checkpoint-cosmosdb | 0.2.4 | 0.2.7 | patch |

The repo URL will be **shared publicly at an event with live demos** and used for **new workshop modules**, so it must not ship on outdated libraries. We also don't want to build the analytics pillars twice (before and after an upgrade). Therefore: modernize **before** the remaining analytics build, on top of the four merged fixes.

## Decision drivers

- Ship the public workshop on current libraries; avoid learners taking a dependency on stale APIs.
- Do the upgrade **once**, on a known-good base (all four fixes), with full regression.
- De-risk the scariest unknowns **first** (checkpointer) before committing to a plan — done.

## Evidence (spikes run 2026-07-07 — mostly positive)

1. **Cosmos checkpointer is compatible.** `langgraph-checkpoint-cosmosdb 0.2.7` runs on **langgraph 1.2.8** (+ `langgraph-checkpoint 4.1.1`): a live functional round-trip (save / `get_state` / history / repeat-write) succeeded. This was the single biggest risk and it is **cleared**. Evidence: `../verification/2026-07-07-langgraph-1x-checkpointer-derisk.md`.
2. **The langgraph API surface the app uses still imports on 1.2.8** (verified in a throwaway venv): `from langgraph.graph import StateGraph, START, MessagesState`; `from langgraph.prebuilt import create_react_agent`; `from langgraph.types import Command, interrupt`; `from langgraph.checkpoint.memory import MemorySaver`; `from langgraph.graph.message import add_messages`. All OK.
3. **pip resolves the new stack** (`langgraph 1.2.8 + langchain-core 1.4.8 + langgraph-checkpoint-cosmosdb 0.2.7`) with **no conflict**.
4. **Forward-compatibility of our fixes:** the token fix reads `usage_metadata` (the modern field newer libs populate by default) — it survives the upgrade (the `stream_options` flag becomes redundant, not broken). Summarizer/routing/transition fixes are pure logic / stable graph contracts.

**Implication:** the upgrade is materially more tractable than the raw version gap suggests — structural APIs and the checkpointer hold; the work concentrates in a few specific breaking changes plus regression.

## Decision

**Adopt the upgrade to the latest majors**, in a **phased, verify-each-step** manner, on a branch built from `analytics` (which contains all four fixes). Regenerate the analytics baseline only **after** the upgrade (ADR-0004).

### Migration surface (to handle + verify)
- **`create_react_agent` signature/behavior** — likely param rename (`state_modifier` → `prompt`) and prompt-format changes across versions. The app calls it 6×; verify and adjust.
- **`langchain-mcp-adapters` 0.1.7 → 0.3.0** — the `MultiServerMCPClient`/session/`load_mcp_tools` API changed; re-validate the persistent-session pattern in `travel_agents.py`.
- **`openai` 1 → 2** and **`langchain-openai` 0.3 → 1.x** — mostly compatible; re-verify `AzureChatOpenAI`/`AzureOpenAIEmbeddings` construction, the token-usage behavior (our `stream_options`/`usage_metadata` path), and the native `AzureOpenAI` client used by the MCP server + seed script.
- **`langchain-core` message imports** (`HumanMessage`/`AIMessage`/`ToolMessage`/`SystemMessage`) — expected stable; confirm.
- **Checkpoint container provisioning** — the Entra-ID saver path uses an *existing* container; ensure infra creates it.

### Phased plan
1. **✅ De-risk checkpointer** (done).
2. **Branch off `analytics`**; bump `requirements.txt` (both trees) to the target set; create a fresh venv.
3. **Fix imports/signatures** until the app boots (MCP server + API start, agents initialize, graph builds).
4. **Migrate `langchain-mcp-adapters`** usage; confirm tools load and agents can call them.
5. **Re-verify token/latency/telemetry** behavior on the new libs (our fixes still produce non-zero tokens, hand-offs, summaries).
6. **Full regression:** run the app end-to-end (a scripted multi-agent conversation), the `01_exercises/evaluation` harness, and a frontend build; fix fallout.
7. **Propagate to `01_exercises`** (source + manuals) — including the deferred routing-map manual propagation (bundle here since the graph code is being touched anyway).
8. **Regenerate the baseline** (ADR-0004) on the upgraded app; run the acceptance scenarios.

## Consequences

- **Positive:** public-ready on current libraries; one upgrade, not two; our instrumentation fixes carry forward; unblocks new modules.
- **Negative / costs:** a focused migration + full regression across both trees, manuals, and the eval harness; some behavioral re-validation.
- **Risks:** `create_react_agent`/mcp-adapters behavioral changes are the most likely to need real fixes; openai v2 edge cases; the frontend is largely independent but should be built.

## Open items to verify (during implementation)
- Exact `create_react_agent` signature/prompt API on the target `langgraph.prebuilt`.
- `langchain-mcp-adapters` 0.3.0 client/session API vs the current persistent-session pattern.
- `openai` 2.x / `langchain-openai` 1.x construction + token-usage behavior (does `usage_metadata` populate without `stream_options`? if so, simplify the token fix).
- Whether `MessagesState` remains the right state type or a `TypedDict + add_messages` is now idiomatic.
- Old checkpoints (≈19k, saver 0.2.4) are **not** required to be readable (we regenerate) — do not spend effort migrating them.

## References
- Checkpointer de-risk: `../verification/2026-07-07-langgraph-1x-checkpointer-derisk.md`.
- API usage sites: `02_completed/python/src/app/travel_agents.py` (imports lines 18–25; `create_react_agent` 246–276), `services/azure_open_ai.py`, `services/azure_cosmos_db.py`.

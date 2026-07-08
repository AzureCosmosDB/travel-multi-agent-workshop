# ADR-0006: Adopt `agent_memory_toolkit_v2` as the unified baseline and land it, modernization, and analytics in one PR to `main`

- **Status:** Accepted
- **Date:** 2026-07-07
- **Deciders:** @markjbrown (mjbrown), with explicit go-ahead from the repo maintainer (aayush3011)
- **Related:** ADR-0003 (source-pluggable ingestion, OTel alignment), ADR-0005 (dependency modernization), charter, vision

## Context

While mid-way through the analytics initiative (built on the *classic* architecture: orchestrator + 5 specialists with `transfer_to_*` handoffs and a hand-rolled memory subsystem), we learned of an upstream branch, `agent_memory_toolkit_v2`, that is a **next-generation rewrite** of the whole workshop. The maintainer has told us we may incorporate v2 into our work and submit a single PR back to `main` that unifies v2 + our dependency modernization + our analytics — we do **not** have to wait for the maintainer to merge v2 first.

Key facts established (evidence below):
- `main` and v2 are **architecturally opposed**. `main` has *reverted* the memory-toolkit build updates (upstream PRs #63/#58 revert) and deleted `cosmosdb-gsi.bicep`, `seed_gsi_trips.py`, and `agent_memory.py` — i.e. `main` is currently the **classic** architecture. v2 embraces the toolkit.
- v2 is a core-team integration branch (aayush3011, TheovanKraay, jcocchi), **not** yet PR'd to `main`, last touched **2026-06-05**, and 11 commits behind / 11 ahead of `main`.

## Decision drivers

- Maintainer wants the workshop to move to the v2 architecture; we are authorized to be the vehicle.
- Avoid throwaway work: build the analytics pillars **once**, on the future architecture, not twice.
- The public workshop/live demos must ship on current libraries and the intended architecture.
- Preserve our durable design assets (Open Analytics Schema, ADRs, data-gen/enricher, acceptance scenarios) which ADR-0003 already made **architecture-agnostic**.

## Options considered

### Option A — Continue analytics on classic `main`, port to v2 later
Build the six pillars on the classic architecture now, re-instrument on v2 after it lands. **Verdict:** rejected — duplicated instrumentation work; classic-specific analytics (`agent_path`/`handoff_count`/`transfer_to_*` routing) is throwaway under the supervisor model.

### Option B — Adopt v2 now as the unified baseline; layer modernization + analytics; one PR to `main`
Make v2 the base, bring our modernized dependency set and analytics onto it, and submit a single unifying PR. **Verdict:** chosen — matches maintainer intent, builds analytics once on the target architecture, and our design docs port cleanly.

### Branch topology sub-decision
- **Chosen:** branch `mjbrown/unify-v2` **from `upstream/agent_memory_toolkit_v2`** (preserves v2 history/attribution), then **selectively carry forward** the few `main`-only additions we want (e.g. `.github/copilot-instructions.md`), rather than a blind `git merge main` (which would reintroduce the classic files v2 deleted → massive conflicts). The eventual PR `mjbrown/unify-v2 → main` will show the full, intended classic→v2 transformation.

## Evidence

- **Architecture delta** (`git diff --stat <merge-base> upstream/agent_memory_toolkit_v2`, 95 files, +47357/−36968): prompts change from `orchestrator`/`hotel`/`dining`/`activity`/`itinerary_generator` to `supervisor`/`find_places`/`itinerary_agent`; new `services/agent_memory.py` (86-line singleton over `azure.cosmos.agent_memory.aio.AsyncCosmosMemoryClient`); `travel_agents.py` 796→581 lines.
- **`main` reverted the toolkit** (`git log <merge-base>..upstream/main`): commits `efcefe4`/`6daf916` "Revert Akataria/build updates"; `git diff --stat` shows `main` deletes `cosmosdb-gsi.bicep` (−347), `seed_gsi_trips.py` (−400), `agent_memory.py` (−77) and keeps classic prompts.
- **v2 memory kit** = PyPI `azure-cosmos-agent-memory>=0.1.0b2` + `prompty>=2.0.0a9` (v2 `02_completed/requirements.txt`), replacing the hand-rolled extract/resolve/store/recall/summarize subsystem.
- **v2 checkpointer** = `langchain-azure-cosmosdb==1.0.0` (commit `c0ea3db`), replacing `langgraph-checkpoint-cosmosdb`.
- **v2 observability** = full OpenTelemetry + `azure-monitor-opentelemetry*` stack, **and** it *retains* the Cosmos `Debug`/`store_debug_log`/`total_tokens` seam our analytics reads (`travel_agents_api.py:853,919,930`). This aligns with ADR-0003 (OTel GenAI semconv).
- **v2 "rewritten `create_react_agent`"** = `_create_agent()` wrapper (branch `travel_agents.py:97-101`) that stays on `langgraph.prebuilt.create_react_agent` but is version-portable (`state_modifier`↔`prompt`). This differs from our ADR-0005 choice to migrate to `langchain.agents.create_agent`.
- **v2 perf** = one-shot `find_places` (single forced tool call replacing the ReAct 2-call loop), parallel tool calls, ContextVar preference-vector injection (avoids 1536 floats in chat history).
- **Package delta:** v2 pins are slightly *older* than our modernized set (v2: langgraph 1.2.4, langchain-core 1.4.0, openai 2.40, mcp-adapters 0.2.2; ours: 1.2.8 / 1.4.8 / 2.44 / 0.3.0). Our modernization is not wasted — it can raise v2's floor.

## Decision

Adopt `agent_memory_toolkit_v2` as the unified baseline. Create `mjbrown/unify-v2` from it; carry forward select `main`-only additions; layer our dependency modernization and analytics on top; validate; and submit **one** PR to `main` that unifies all three efforts. Execute in phases:

- **Phase 0 — Unified base:** branch from v2; carry forward `main`-only additions (`.github/copilot-instructions.md`, encoding fixes if absent); bring the whole `analytics/` design folder onto the branch; get v2 building/running.
- **Phase 1 — Reconcile dependencies:** merge our modernized pins with v2's requirements (keep `azure-cosmos-agent-memory`, `langchain-azure-cosmosdb`, OTel); re-validate boot + all paths. Revisit `create_agent` vs v2's wrapper (default: keep v2's wrapper to minimize divergence).
- **Phase 2 — Re-scope our fixes:** keep only what still applies on v2 (token capture, UTF-8/emoji, mojibake); drop classic-only fixes (`agent_path`/`handoff_count`/`transfer_to_*`, routing-map, summarizer-trigger, memory-over-extraction seam) that v2 supersedes.
- **Phase 3 — Rebuild analytics on v2:** re-anchor the six pillars on v2 seams; choose ingestion source per ADR-0003 (OTel spans and/or `Debug` logs); redefine "handoffs" as supervisor→tool spans; regenerate data-gen/enricher against v2's API; refresh ADRs 0001–0005 for v2 context.
- **Phase 4 — Docs + validation:** reconcile v2's rewritten Modules 01–06 with analytics additions; full regression (eval harness, frontend build, data-gen).
- **Phase 5 — Unified PR → `main`.**

## Consequences

- **Positive:** analytics built once on the target architecture; workshop ships next-gen (supervisor + memory SDK + OTel + GSI) on current libraries; our design docs and modernization feed forward; single clean PR unifies three streams.
- **Negative / costs:** large integration effort; v2 is ~1 month stale and must be reconciled with current `main`; instrumentation must be reworked for the supervisor/tool model.
- **Risks:** `azure-cosmos-agent-memory` (0.1.0b2) and `langchain-azure-cosmosdb` (1.0.0) are new/beta; v2 architecture may move the analytics seams; package reconciliation may surface runtime breaks (mitigated by the modernization validation already done in ADR-0005).

## Open items to verify

- v2 boots and exercises all paths on the reconciled (modernized) dependency set — **verify by full data-gen run** (Phase 1).
- Whether v2's API contract (`/tenant/{t}/user/{u}/sessions/{s}/completion`) is unchanged enough for the existing data_generator personas — **verify** (Phase 3).
- Whether OTel spans or `Debug` logs (or both) are the better analytics source on v2 — **prototype both** (Phase 3), decide, and record.
- `create_agent` vs v2's `_create_agent` wrapper — **decide in Phase 1** with the user.

## References

- Branch: `upstream/agent_memory_toolkit_v2`; integration branch: `mjbrown/unify-v2`.
- Memory SDK: https://pypi.org/project/azure-cosmos-agent-memory/
- ADR-0003 (source-pluggable ingestion / OTel), ADR-0005 (dependency modernization).

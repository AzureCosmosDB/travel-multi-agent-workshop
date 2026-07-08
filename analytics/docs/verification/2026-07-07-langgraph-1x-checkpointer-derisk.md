# De-risk — `langgraph-checkpoint-cosmosdb` on langgraph 1.x

**Date:** 2026-07-07  •  **Status:** ✅ Verified (gating risk cleared)
**Why:** The Cosmos checkpointer (`langgraph-checkpoint-cosmosdb`, latest **0.2.7**) is a niche third-party package. If it didn't work on **langgraph 1.x**, the whole langgraph major upgrade (0.2 → 1.x) would be blocked. This spike answers that fast, before writing the upgrade ADR.

## Method
Throwaway venv with the target stack; live Cosmos via Entra ID (`az login`). No app code involved.
Installed: **langgraph 1.2.8, langgraph-checkpoint 4.1.1, langgraph-checkpoint-cosmosdb 0.2.7, langchain-core 1.4.8** (pip resolved with **no conflict**).

1. **Import + interface:** `from langgraph_checkpoint_cosmosdb import CosmosDBSaver` — OK. It is a valid `BaseCheckpointSaver` subclass with **no unimplemented abstract methods**; implements `put/aput/put_writes/aput_writes/get_tuple/aget_tuple/list/alist`; `put()` signature matches the 1.x checkpoint API (`config, checkpoint, metadata, new_versions`). It imports the expected symbols from `langgraph.checkpoint.base` (which still exist in `langgraph-checkpoint 4.1.1`).
2. **Functional round-trip:** built a minimal langgraph **1.2.8** `StateGraph` (single `inc` node), compiled with `CosmosDBSaver(database_name="TravelAssistant", container_name="CheckpointsUpgradeSpike")` (throwaway container, PK `/partition_key`), and exercised the full checkpoint path against live Cosmos.

## Result (verbatim)
```
run1 result: {'count': 1}
get_state values: {'count': 1} | next: ()      # get_tuple + deserialize OK
state history entries: 3                        # list OK
run2 result: {'count': 11}                      # second write to same thread OK
FUNCTIONAL CHECKPOINT ROUND-TRIP: OK
```

## Verdict
✅ **`CosmosDBSaver 0.2.7` is functionally compatible with langgraph 1.2.8.** Save, read-back (`get_state`/`get_tuple`), history (`list`), and repeated writes all work. **The langgraph major upgrade is not blocked by the Cosmos checkpointer.**

## Caveats / still to validate in the full upgrade
- This tested the checkpointer in isolation with a trivial graph. The **app-code migration is still substantial** — other 1.x breaking changes remain (e.g. `create_react_agent` location/behavior, `Command`/`interrupt`, `MessagesState`, tool binding, `langchain-mcp-adapters` 0.1→0.3, `openai` 1→2, `langchain-openai` 0.3→1.x). Those are the ADR's scope; the checkpointer is simply no longer a blocker.
- **Old checkpoints** (≈19k written by saver 0.2.4) were not tested for cross-version readability. Not required, since we **regenerate** after the upgrade — but note it if any migration of existing threads is ever desired.
- Connection: saver reads `COSMOSDB_ENDPOINT` and uses `DefaultAzureCredential` when `COSMOSDB_KEY` is unset (matches the app's Entra-ID path). The Entra path uses an **existing** container (does not create it) — provisioning must ensure the checkpoints container exists.

## Reproduce
Throwaway venv (not committed): install `langgraph==1.2.8 langgraph-checkpoint-cosmosdb==0.2.7 azure-cosmos azure-identity`; set `COSMOSDB_ENDPOINT`; run the minimal graph above against a `/partition_key`-partitioned container.

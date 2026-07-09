# Cosmos DB throughput analysis — why dedicated, not shared

**Context:** Fabric mirroring requires a **provisioned** (not serverless) Cosmos account, so the
workshop account needs throughput. This analysis grounds the choice of **dedicated per-container
autoscale** over shared database throughput, using real data from the deployed `TravelAssistantV2`
account (2026-07-09).

## Inventory — 15 containers

| Container | Storage | Docs | Profile |
|---|---:|---:|---|
| **Checkpoints** | **5,298 MB** | **330,813** | LangGraph state — storage giant **and** write-hot (a checkpoint per super-step) |
| **Places** | **996 MB** | 61,655 | vector embeddings — RU-expensive reads |
| Memories | 99 MB | 6,288 | vector |
| Messages | 15 MB | 6,520 | write per turn |
| memories_turns | 11 MB | 6,644 | write per turn |
| memories_summaries | 15 MB | 495 | |
| Debug | 10 MB | 3,579 | write per turn |
| Trips | 3 MB | small | |
| OptimizationTurns | 1.4 MB | 880 | write per turn (heavy under the real-time demo) |
| Sessions / Users / ApiEvents / counter / OptimizationPolicies / OptimizationInsights | <3 MB each | small | cold |

**Checkpoints + Places ≈ 97% of both storage and documents.** The other 13 containers are ~3%.
Asymmetry between the largest and a typical small container: **~3,600× storage, ~375× docs.**

## Why shared database throughput is a trip wire here

Cosmos **shared** throughput distributes the database's RU/s **evenly across physical partitions**.

1. Checkpoints (5.3 GB, growing ~350 docs/session) and Places (1 GB) drive **physical-partition
   splits** as data grows.
2. Every split **dilutes** the shared pool: max RU/s per partition = `dbRUs / partitionCount`.
3. The small **write-hot** containers (Debug / OptimizationTurns / Messages under demo load) and the
   **RU-expensive vector reads** (Places / Memories) then get a thinner and thinner *even* slice —
   mismatched to their real demand.
4. Result: **silent 429 throttling that only appears at scale in production** — a solution that works
   in dev degrades as data accumulates. This is the classic shared-throughput asymmetry cliff.

The even RU distribution only fits **symmetric** workloads; this one is the opposite.

## Decision — dedicated autoscale per container

`infra/shared/cosmosdb.bicep` gives **each container its own autoscale throughput** (params):

- `checkpointsMaxRU` = **4000** (storage + write hotspot)
- `placesMaxRU` = **2000** (vector search)
- `containerMaxRU` = **1000** (all others; autoscale floors at 10% = 100 RU/s)

This **isolates** each container's RU (no dilution, no starvation), scales each independently, and each
pays only its floor when idle. It is the Cosmos-recommended pattern for asymmetric workloads and is
what a customer adopting this as a pattern should do.

> Trade-off: a higher idle baseline than a single shared pool (≈1.7k RU/s floor across 15 containers),
> accepted deliberately for scale-safety over minimal dev cost.

## Related finding — Checkpoints bloat (recommended follow-up)

Checkpoints holds **330,813 docs / 5.3 GB (~350 checkpoints per session)** — the LangGraph
`CosmosDBSaver` is not pruning. This is the dominant storage driver and a write hotspot. **Recommend a
TTL on the Checkpoints container** (e.g., retain a few days) to bound storage and cost; it also shrinks
the biggest asymmetry source. Not applied yet (separate decision).

## Notes

- Applied to `01_exercises` (15 containers) and `02_completed` (12 containers — 02 lacks the 3
  optimization containers; full parity is a tracked follow-up).
- Serverless is not an option because mirroring requires a provisioned account.

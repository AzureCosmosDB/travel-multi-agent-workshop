# ADR-0001: Optimization-loop surface architecture — reverse-ETL to Azure Cosmos DB + web-app apply-loop

- **Status:** Accepted
- **Date:** 2026-07-07
- **Deciders:** Mark Brown (@markjbrown), with agent analysis
- **Related:** `../vision/agent-analytics-and-optimization-vision.md`, `../charter.md`

## Context

The workshop scope (see charter) covers **all six analytics pillars** through **Levels 1–3**, with a single bounded **Level 4** slice, and **Pillar 4 — Memory Intelligence** as the flagship. Unlike Level 1 (Visibility), Levels 2–3 require a *closed loop*: the platform must generate optimization recommendations, present them for human approval, and **write approved changes back into the operational store** (adjust memory salience, retention/TTL, retire stale/conflicting memories, tune retrieval weighting, adjust routing/model policies).

> **Scope note (2026-07-07):** this ADR was first written when scope was Pillar 4 only. Scope has since broadened to all six pillars; the decision below is unaffected and generalizes — the reverse-ETL + web-app apply-loop is the surface for *any* pillar's optimization actions. Write-back is concentrated in memory (Pillar 4) and routing/model policies (Pillars 2/3); Pillars 1/5/6 are more visibility-oriented.

The vision fixes a hard constraint: **Azure Cosmos DB is the operational system of record**; Fabric is the analytical/optimization layer. The already-deployed travel app runs on an **Azure** Cosmos DB account (not Cosmos-in-Fabric).

A candidate was raised: use **Fabric Translytical Task Flows** with **User Data Functions (UDFs)**, invoked from **buttons in Power BI**, to drive write-back actions — which would keep the loop inside Power BI and avoid a separate web app. The open question was whether a Fabric UDF can write to an **external Azure Cosmos DB account** (`*.documents.azure.com`) rather than **Cosmos DB in Fabric**, which is what published samples show.

## Decision drivers

- Level 2/3 requires **writing to the operational store**; Power BI on its own is read-only.
- The operational store must remain **Azure Cosmos DB** (vision alignment; app already deployed there).
- Our Azure Cosmos account uses **`disableLocalAuth: true`** — any write path must use Entra ID, not keys.
- Prefer supported, documented mechanisms over undocumented/hand-rolled ones (charter: data-grounded, tested).
- Reuse existing write primitives where possible.

## Options considered

### Option A — Power BI only (Level 1 visibility)
Read-only reports over gold tables. **Verdict: insufficient.** Cannot host recommend/approve/apply; does not meet Level 2/3.

### Option B — Translytical Task Flows + UDF write-back from Power BI buttons
Power BI button → Fabric UDF → Cosmos patch. **Verdict: rejected for our operational store.** The supported UDF Cosmos connection targets **Cosmos DB *in Fabric***, not our external Azure Cosmos account (evidence below). Adopting it would require making Cosmos-in-Fabric the operational store, which **conflicts with the vision** (Azure Cosmos DB = SoR) and with the already-deployed app. May be revisited for apps that *are* built on Cosmos-in-Fabric.

### Option C — Reverse-ETL gold layer into Azure Cosmos DB + web-app apply-loop *(chosen)*
Fabric mirrors operational data in, Spark computes gold analytics **and** memory-optimization recommendations, and a **reverse-ETL** step writes recommendations (and any serving-gold data) **back into Azure Cosmos DB**. The existing Angular app gains a **review/approve/apply UX**; "apply" calls the app API, which reuses the already-implemented Cosmos patch primitives. **Verdict: chosen.** Keeps Azure Cosmos as SoR, uses the samples-recommended operational bridge, and leverages existing code.

## Evidence

**1. The supported UDF↔Cosmos connection is Fabric-native only.**
- Authoritative doc: *"User data functions with Cosmos DB Database **in Fabric**"*, Microsoft Learn / `MicrosoftDocs/fabric-docs` (`docs/database/cosmos-db/how-to-user-data-functions.md`, `ms.date: 02/20/2026`). All steps obtain the endpoint from **Fabric portal → Cosmos DB database → Settings → Connection ("Endpoint for Cosmos DB NoSQL database")**; the binding is `@udf.connection(argName=..., audienceType="CosmosDB", cosmos_endpoint="{my-cosmos-artifact-uri}")` against the **Fabric artifact**.
- Sample `AzureCosmosDB/cosmos-fabric-samples/translytical-taskflows-nosql-schema` README: *"a translytical task flow using **Cosmos DB in Microsoft Fabric** as the operational data store."* Its `triage_writeback_udf.py` uses the generic `azure.cosmos` SDK, but the managed connection points at the Fabric artifact.
- Corroborating web research (mid-2026): no documented/native support for the UDF managed connection to target an external Azure Cosmos DB account; external access would be an unsupported hand-rolled pattern.
- Our account sets `disableLocalAuth: true` (`02_completed/infra/shared/cosmosdb.bicep`), so key-based hand-rolled access is also closed off.

**2. Azure Cosmos DB is the required operational bridge (authoritative sample statement).**
- `AzureCosmosDB/cosmos-fabric-samples/reverse-etl` README: *"deployed applications in Azure cannot connect directly to Fabric Lakehouse SQL endpoints using managed identity, so **Cosmos DB serves as the operational bridge** between Fabric's analytical processing and your applications."*

**3. A working reverse-ETL + web-app reference exists to adapt.**
- Same repo, `reverse-etl` (Customer 360): Fabric Spark notebook → LLM/embedding enrichment → **reverse-ETL into Azure Cosmos DB for NoSQL** → **FastAPI web app** with Cosmos `VectorDistance()` search. Contains `infra/`, `webapp/`, `fabric/`, `azure.yaml`.

**4. The write-back primitives already exist in our codebase (verified).**
- `02_completed/python/src/app/services/azure_cosmos_db.py`: `boost_memory_salience` (`:667`, salience tuning via read-modify-upsert), `supersede_memory` (`:635`, patch), `update_memory_last_used` (`:610`, patch), TTL-based decay for episodic memories (`store_memory`, `:583-587`). Note: `boost_memory_salience` is currently **defined but never called** (no `@mcp.tool`, no invocation) — a ready primitive with no loop wired to it yet.

## Decision

Build the Level 2/3 optimization loop as: **Fabric (mirror → Spark gold + recommendation generation) → reverse-ETL of recommendations/serving data into Azure Cosmos DB → an interactive review/approve/apply web UX in the existing Angular app**, where "apply" calls the app API and reuses the existing Cosmos patch primitives. **Power BI is retained (optionally) only for Level-1 visibility.** Translytical/UDF write-back to the operational store is **not** adopted, because the supported UDF connection targets Cosmos-in-Fabric, which conflicts with keeping Azure Cosmos DB as the system of record.

## Consequences

- **Positive:** Vision-aligned (Azure Cosmos = SoR); uses the samples-recommended bridge; reuses existing write primitives; gives an interactive, teachable web surface for the workshop; keeps Power BI available for visibility.
- **Negative / costs:** We own a reverse-ETL job (Fabric → Azure Cosmos) and new app UI + API surface; more moving parts than a pure-Power-BI report.
- **Risks:** Reverse-ETL freshness/latency and idempotency; ensuring the apply path is safe, reversible, and auditable (a vision requirement); the memory-effectiveness signals needed for credible recommendations are **not yet instrumented** (see open items).

## Open items to verify

- **(Optional) Live-test** whether a Fabric UDF can reach an external Azure Cosmos account with Entra ID, to convert "no documented support" into an observed result. Not required for this decision.
- **Instrumentation gap:** design and validate a `MemoryEvent` retrieval-event stream and an outcome-linkage signal (recalled memories ↔ turn outcome). Without it, Level 2/3 recommendations cannot be grounded. To be its own ADR.
- **Reverse-ETL mechanics:** confirm the concrete write path (Spark → Azure Cosmos with Entra ID / MI, `disableLocalAuth: true`) by adapting and running the `reverse-etl` sample against our account.

## References

- Vision: `../vision/agent-analytics-and-optimization-vision.md`
- Charter: `../charter.md`
- `MicrosoftDocs/fabric-docs` — `docs/database/cosmos-db/how-to-user-data-functions.md`
- `AzureCosmosDB/cosmos-fabric-samples` — `translytical-taskflows-nosql-schema/`, `reverse-etl/`, `user-data-functions/`

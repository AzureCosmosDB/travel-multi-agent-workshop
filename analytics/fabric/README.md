# Fabric automation runbook — Cosmos mirroring, reverse-ETL, real-time analytics

This is the reproducible automation + findings for putting the Travel Assistant
optimization analytics on **Microsoft Fabric** with **near-real-time Cosmos DB
mirroring**, a reverse-ETL notebook, and a real-time Power BI story.

Everything here was driven via **REST + `az`** with a normal `az login` token —
**no MCP or extra tooling needed**. Fabric ARM support is limited, so mirroring,
notebooks, RBAC, and networking are automated through the **Fabric REST API** and
the **Azure Cosmos ARM API**. Most of Phase 1 is now scripted end-to-end in
[`provision_fabric.py`](./provision_fabric.py); see below.

## Fabric capacity region — flexible by design

`azd up` prompts for a separate `FABRIC_CAPACITY_LOCATION` (default `westcentralus`) so you can
place the Fabric capacity **wherever it best suits you**, independently of the app's own region.
Fabric capacity availability varies by Azure region and can be governed per-tenant, so the region
you deploy the app into isn't necessarily where you want — or are allowed — to run Fabric. Pick any
region that has Fabric capacity available to you.

> **Example:** on the tenant this was built against, the app runs in **West US** while the Fabric
> capacity lives in **West Central US** — hence the separate prompt.
>
> **Heads-up:** if you choose a region where Fabric capacity isn't actually available to your
> tenant, the ARM `Microsoft.Fabric/capacities` resource can still report **Succeeded/Active** yet
> never appear in the Fabric control plane (`/v1/capacities`), so it can't be used. If that happens,
> redeploy the capacity in a region you know has Fabric (it typically appears within ~30s).

- **Capacity (current):** `fabf2tx5x7js4bwi` — **F2**, **West Central US**, Fabric id
  `a04c5461-c9d4-4eb8-b67e-bb76fc302f2d`, admin `mjbrown@microsoft.com`. Deployed by
  `infra/shared/fabriccapacity.bicep` (gated by `deployAnalytics`).
- **Workspace (current):** `Multi-Agent Travel Workshop` = `e743e261-e1a7-4a64-a6e0-7e4182fce243`,
  assigned to the F2 capacity, workspace identity SP `8f33e8f7-d216-43e3-8d9f-0426c4d1df4e`
  (app `84c6d9a1-9916-44de-aa42-732d91f50911`). **Created + wired by `provision_fabric.py --phase 1`.**
- **Cosmos (current, westus):** `cosmos-f2tx5x7js4bwi` (rg `rg-mjb-fabcon-travel`), DB `TravelAssistant`.
  Provisioned autoscale + Continuous backup (both required for mirroring). Cosmos **Data Contributor**
  assigned to the workspace identity SP `8f33e8f7-…` (by Phase 1).
- **Legacy (retire):** old F64 workspace `37733bf9-…` + `cosmos-kfpokdh52vbec`/`TravelAssistantV2`
  mirror `TravelAssistantV2Analytics` (`debe9a19-…`) — stale after the westus redeploy.
- **Connection:** WorkspaceIdentity connection is **still blocked** (`DMTS_UntrustedEndpointForWorkspaceIdentity`,
  re-confirmed 2026-07); create the connection via the **portal Mirrored-DB flow with Organizational
  account (OAuth2)** — the deploying user has Cosmos Data Contributor on the new account. This is the
  one manual step; pass the resulting connection id to `provision_fabric.py --phase 2 --connection-id <id>`.

> **Automating this last step is parked, not shipped.** Creating the connection
> programmatically works today on MSIT but is **demo-only** (the embedded token is
> short-lived and can't refresh) and MSIT-endpoint-specific. The working spike is preserved at
> [`experimental/create_oauth_connection.py`](./experimental/create_oauth_connection.py)
> and tracked in [`../docs/parking-lot.md`](../docs/parking-lot.md); we'll wire it in when
> the Fabric gateway team ships audience/refresh support. Until then, **ship with the
> manual connection step above.**

## provision_fabric.py — Phases 1 & 2 (automated, validated end-to-end)

`python analytics/fabric/provision_fabric.py --phase 1` (reads config from `azd env` or CLI flags):
creates the workspace, assigns it to the F2 capacity, provisions the workspace identity, waits for
the identity SP to propagate to AAD, and grants Cosmos **`readMetadata` + `readAnalytics`** (a custom
`FabricMirroringRole`) to the connection identity. `--phase 2 --connection-id <id>` then creates the
mirror (OptimizationTurns / Trips / OptimizationPolicies / Configuration / Messages /
OptimizationInsights), waits for it to initialize, starts it, and uploads the **Module 09 notebook**
(`ConversionFunnelReverseETL`, learner TODOs by default) with its parameters pre-filled from the
deployment. Idempotent.

> **Learner vs solution notebook:** the default upload is the **learner** notebook (TODOs). For
> `02_completed` / the demo, add **`--solution`** to upload the completed `*_solution` notebook — both
> land as `ConversionFunnelReverseETL`. No Direct Lake semantic model is created; the report is
> DirectQuery over the mirror SQL endpoint.

### One gotcha that cost real debugging time (now fixed in code)

1. **`readAnalytics`, not Data Contributor.** The mirror reads Cosmos **as the connection identity**
   — for an OAuth2 connection that's the **deploying user**, not the workspace identity. Fabric's
   analytical snapshot read requires `Microsoft.DocumentDB/databaseAccounts/readAnalytics`, which the
   **built-in Cosmos Data Contributor role does NOT include**. Missing it surfaces as a *misleading*
   `Http request ... status code 0, either account doesn't exist or it has been deleted` error (looks
   like a network/region problem — it isn't). Fix: grant a custom role with `readMetadata` +
   `readAnalytics` to the **user** (see the Cosmos mirroring limitations doc). This is **not** a
   regional issue — mirroring works cross-region.


## What is automated (and proven)

| Step | How | State |
|---|---|---|
| Workspace identity | `POST /v1/workspaces/{id}/provisionIdentity` | ✅ SP `32087df7-ff95-490f-994f-e2a385f419ab` |
| Cosmos RBAC | custom `FabricMirroringRole` (`readMetadata`+`readAnalytics`) assigned to the **OAuth2 connection identity (the user)** + the workspace identity | ✅ |
| Network trust | none needed for public accounts | ✅ |
| Mirror | `POST /v1/workspaces/{id}/mirroredDatabases` (source CosmosDb → connection + database, `mountedTables`) + `/startMirroring` | ✅ `TravelAssistantV2Analytics` (`debe9a19-…`) replicating |
| Reverse-ETL notebook | `POST /v1/workspaces/{id}/notebooks` + `updateDefinition` + `jobs/instances?jobType=RunNotebook` | ⏳ uploaded; read method being finalized (see below) |
| Traffic simulator | `analytics/traffic_simulator.py` | ✅ proven: 83 turns → mirror in ~60s |

### RBAC (az)

```powershell
# custom role: readMetadata + readAnalytics (account scope)
az cosmosdb sql role definition create -a cosmos-kfpokdh52vbec -g rg-mjb-fabcon-travel --body @role.json
# assign custom + built-in Data Contributor (00..002) to the workspace identity SP
az cosmosdb sql role assignment create -a cosmos-kfpokdh52vbec -g rg-mjb-fabcon-travel \
  --role-definition-id <customRoleId> --principal-id <workspaceIdentitySpObjectId> --scope <accountId>
az cosmosdb sql role assignment create ... --role-definition-id 00000000-0000-0000-0000-000000000002 ...
```

### Mirror (Fabric REST) — `mirroring.json` payload

```json
{ "properties": {
  "source": { "type": "CosmosDb", "typeProperties": { "connection": "<connectionId>", "database": "TravelAssistantV2" } },
  "target": { "type": "MountedRelationalDatabase", "typeProperties": { "defaultSchema": "dbo", "format": "Delta" } },
  "mountedTables": [ { "source": { "typeProperties": { "schemaName": "TravelAssistantV2", "tableName": "OptimizationTurns" } } },
                     { "source": { "typeProperties": { "schemaName": "TravelAssistantV2", "tableName": "Trips" } } },
                     { "source": { "typeProperties": { "schemaName": "TravelAssistantV2", "tableName": "OptimizationPolicies" } } } ] } }
```
Create: `POST /v1/workspaces/{id}/mirroredDatabases` with `definition.parts=[{path:"mirroring.json", payload:<b64>, payloadType:"InlineBase64"}]`, then `POST …/{mirrorId}/startMirroring`.

## The connection object — the crux (partially solved; escalation for the Fabric team)

Fully automating the **Cosmos connection** is the known hard part. Findings:

- The **CosmosDB** Fabric connector supports credential types **Key, OAuth2, WorkspaceIdentity**
  (`GET /v1/connections/supportedConnectionTypes`). Creation method `CosmosDB.Contents`, required param `host`.
- **Key** is unavailable here — the account has `disableLocalAuth: true` (no keys).
- **OAuth2** cannot be created programmatically (documented in `AzureCosmosDB/fabric-cosmos-mirror`;
  the portal uses an internal first-party gateway flow). We fall back to a **pre-existing OAuth2
  connection** (`cosmos travel assistant  mjbrown`, id `7ec42257-…`).
- **WorkspaceIdentity** *should* be the automatable, keyless path (and matches the RBAC setup), but
  `POST /v1/connections` with `credentialType: WorkspaceIdentity` returns
  **`DMTS_UntrustedEndpointForWorkspaceIdentity`** for the Cosmos `documents.azure.com` host —
  **even after** provisioning the workspace identity, assigning the two Cosmos RBAC roles, and
  enabling the Fabric network-ACL bypass. This is a **Fabric-side endpoint-trust gap**, not a Cosmos
  config issue. **This is the escalation item** — it likely matures alongside Service Principal
  connection support. Once either lands, connection creation is one API call and
  the whole flow is hands-free.

## Reverse-ETL notebook — WORKING (read via JDBC SQL endpoint)

`analytics/fabric/ConversionFunnelReverseETL.ipynb` (Module 09) reads the mirrored tables, computes
the **conversion funnel** + abandonment causes, and writes flat rows to Cosmos `OptimizationInsights`
via the **Cosmos Spark connector** with Fabric AAD (the workspace identity) — **no `%pip`, so it is
safe in scheduled jobs**. It ships as a **learner** notebook (two TODOs) with a `*_solution` variant;
`provision_fabric.py` uploads it during Phase 2 (add `--solution` for the completed one).

**Read method (solved):** the Fabric Spark Delta reader (runtime 1.3) **cannot** read the mirrored
tables' **deletion vectors** — `spark.read.format("delta").load(path)` *and* a Lakehouse-shortcut
`spark.read.table(...)` both fail with *"Cannot work with a non-pinned table snapshot"*. The working
fix is to read through the **SQL analytics endpoint over JDBC** (`spark.read.format("jdbc")` with the
mirror SQL endpoint + `mssparkutils.credentials.getToken("pbi")` as `accessToken`), which resolves
deletion vectors at the SQL layer.

**Power BI** reads the mirror via **DirectQuery over the SQL analytics endpoint** — the Business Impact
page reads the reverse-ETL'd `OptimizationInsights` rows. No Direct Lake semantic model is created.

## Real-time demo (works today, no notebook needed)

The mirror is **continuous / near-real-time**, so this shows the "analytics on a transactional
Cosmos workload" story live:

1. Point a Power BI report at the **mirror SQL endpoint** (Direct Lake or DirectQuery):
   - SQL endpoint: `TravelAssistantV2Analytics` (id `421ed091-5396-40b6-bc2b-df2f8291198c`)
   - connection string: `…-….msit-datawarehouse.fabric.microsoft.com`, database `TravelAssistantV2Analytics`.
   - **Direct Lake** is ideal — it reads OneLake directly, so visuals update as the mirror updates,
     with no dataset refresh.
2. Start the traffic simulator:
   ```powershell
   python analytics/traffic_simulator.py --tenant DemoLive --rate 120 --forever
   ```
3. Watch: simulator → Cosmos (transactional) → mirror (~seconds) → Power BI visuals move. **Verified:**
   83 simulated turns appeared in the mirror within ~60s.

## Remaining (Power BI is a Desktop-oriented task)

- **Semantic model** over the mirror (Direct Lake) — **DONE, scripted + validated.**
  `TravelAssistantV2AnalyticsModel` (`6d5e8b30-999a-49f0-927c-6382c80df913`) created via
  `POST /v1/workspaces/{id}/semanticModels` with a TMDL definition (tables `OptimizationTurns` +
  `Trips` in **Direct Lake** mode over the mirror SQL endpoint, plus measures: Total Turns, Total
  Tokens, Trivial %, Est Cost USD, Confirmed Trips, Cost per Outcome). Validated live via
  `POST /v1.0/myorg/groups/{id}/datasets/{ds}/executeQueries` (DAX) → **88 turns, 48.9% trivial,
  $0.49 est cost, 8 confirmed trips, $0.061 cost/outcome** (including simulated turns) — i.e. it reads
  the mirror in near-real-time with no dataset refresh.
- **Report visuals + `.pbit` template + attendee-usability test** — best finalized in **Power BI Desktop**:
  connect to the **`TravelAssistantV2AnalyticsModel`** semantic model (live connection → real-time),
  build the visuals, and save the `.pbit`. `analytics/TravelAssistantReport.pbit` is the v1 template to adapt.

## IDs (dev)

- Workspace `37733bf9-e6c2-4472-b4fb-22cb547079f7` · capacity `38356b39-72d6-4c6c-85af-c1267e985370`
- Mirror `debe9a19-56de-4363-9ea9-88dc29baa003` · SQL endpoint `421ed091-5396-40b6-bc2b-df2f8291198c`
- Notebook `aa597a7e-82ac-4a3d-ba36-29dcd96c2e24`
- Workspace identity SP `32087df7-ff95-490f-994f-e2a385f419ab` (app `43f02795-2596-41d6-b6e2-060588f33593`)
- OAuth2 connection `7ec42257-ca1c-4a4c-a173-c58b1bc7ab6c`

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
> never appear in the Fabric control plane (`/v1/capacities`), so it can't be used. The provisioner
> now stops with this diagnosis. Set `FABRIC_CAPACITY_LOCATION` to a Fabric-supported region for the
> tenant, reprovision the capacity, and retry.

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

## provision_fabric.py — Phases 1–3 (automated, validated end-to-end)

`python analytics/fabric/provision_fabric.py --phase 1` (reads config from `azd env` or CLI flags):
creates the workspace, assigns it to the F2 capacity, provisions the workspace identity, waits for
the identity SP to propagate to AAD, and grants Cosmos **`readMetadata` + `readAnalytics`** (a custom
`FabricMirroringRole`) to the connection identity. `--phase 2 --connection-id <id>` then creates the
mirror (`OptimizationTurns`, `NodeExecutions`, `Trips`, `OptimizationPolicies`,
`OptimizationGovernance`, `Configuration`, `Messages`, `ApiEvents`, `OptimizationInsights`,
and `memories`), waits for it to initialize, starts it, and uploads the **Module 09 notebook**
(`ConversionFunnelReverseETL`, learner TODOs by default) with its parameters pre-filled from the
deployment. Idempotent. Use a tenant-unique workspace name in shared environments; if a hidden
workspace already reserves the name, the provisioner returns an actionable collision error.

The participant wrapper supports the same explicit resume path:

```powershell
.\analytics\fabric\Provision-Fabric.ps1 -Phase 2 -ConnectionId <id>
```

Phase 2 also deploys the **`optimization-apply-loop`** User Data Function, injects the current Cosmos
endpoint/database, installs `azure-cosmos`, and grants the deploying user Cosmos data-plane write.
Phase 3 deploys the source-controlled
**`TravelAssistantAnalyticsReport.SemanticModel`** (TMDL) and
**`TravelAssistantAnalyticsReport.Report`** (PBIR), hydrating the mirror endpoint/database,
workspace/model IDs, and Apply/Revert UDF bindings. It then binds DirectQuery SSO and runs a
dataset query. Deployment is not considered successful until that query validates.

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
| Reverse-ETL notebook | `POST /v1/workspaces/{id}/notebooks` + `updateDefinition` + `jobs/instances?jobType=RunNotebook` | ✅ uploaded; reads mirror through JDBC and persists stage checkpoints |
| Apply/Revert UDF | `POST /v1/workspaces/{id}/userDataFunctions` + hydrated `function_app.py` + `azure-cosmos` | ✅ deployed as `optimization-apply-loop` |
| Power BI report | PBIR/TMDL source deployment + placeholder hydration + SSO binding + DAX validation | ✅ deployed as `TravelAssistantAnalyticsReport` |
| Traffic simulator | `analytics/scripts/traffic_simulator.py` | ✅ proven: 83 turns → mirror in ~60s |

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

Each reverse-ETL section persists a `notebook_run_status` row in `OptimizationInsights`. Its
`last_completed_stage` advances through `core_reverse_etl`, `agent_path`, `turn_metrics`,
`agent_scorecard`, `memory_intelligence`, and `complete`. Use that row to localize generic Spark job
failures; only `complete` means every notebook-backed analytics surface was populated.

**Read method (solved):** the Fabric Spark Delta reader (runtime 1.3) **cannot** read the mirrored
tables' **deletion vectors** — `spark.read.format("delta").load(path)` *and* a Lakehouse-shortcut
`spark.read.table(...)` both fail with *"Cannot work with a non-pinned table snapshot"*. The working
fix is to read through the **SQL analytics endpoint over JDBC** (`spark.read.format("jdbc")` with the
mirror SQL endpoint + `mssparkutils.credentials.getToken("pbi")` as `accessToken`), which resolves
deletion vectors at the SQL layer.

**Power BI** reads the mirror via **DirectQuery over the SQL analytics endpoint** — the Business Impact
page reads the reverse-ETL'd `OptimizationInsights` rows. No Direct Lake semantic model is created.

## Two analytics surfaces, one snapshot

The workshop intentionally ships two complementary surfaces:

- The **web analytics portal** reads the Travel API and can switch between
  **Live (recompute)** and **Reverse-ETL (notebook)** sources. Its gear menu also exposes
  completed-demo maintenance actions when the API advertises those capabilities.
- **`TravelAssistantAnalyticsReport`** reads the Fabric mirror through DirectQuery and the
  mirrored `OptimizationInsights` snapshot. Its data-driven Recommendations table automatically
  shows new `recommendation_card` rows. A selected policy recommendation can call
  `apply_optimization` / `revert_optimization` through the Fabric UDF.

Power BI data-function buttons are standalone report elements; native Table/Matrix cells cannot
embed a UDF button per row. Selection supplies the `scenario` parameter through DAX.

The report intentionally does **not** expose the web gear menu's broad demo-maintenance actions:

- generate traffic with `Run-TrafficSimulator.ps1` (or the hosted completed-demo gear action);
- recompute authoritative insights by rerunning the Fabric notebook;
- keep reset/freshen-time operations in the web demo tooling, not in an analytical report.

## Real-time demo

The mirror is **continuous / near-real-time**, so this shows the "analytics on a transactional
Cosmos workload" story live:

1. Provision the included report; Phase 3 points it at the mirror automatically.
2. Start the policy-aware traffic simulator:
     ```powershell
     .\analytics\scripts\Run-TrafficSimulator.ps1 -Tenant analytics -Rate 120 -Forever -Assume auto
     ```
3. Apply or revert `model-selection` in Power BI or the web portal. The simulator detects the
     policy and changes between premium-only and tiered traffic.
4. Watch: simulator → Cosmos (transactional) → mirror (~seconds) → DirectQuery visuals move. **Verified:**
     83 simulated turns appeared in the mirror within ~60s.

## IDs (dev)

- Workspace `37733bf9-e6c2-4472-b4fb-22cb547079f7` · capacity `38356b39-72d6-4c6c-85af-c1267e985370`
- Mirror `debe9a19-56de-4363-9ea9-88dc29baa003` · SQL endpoint `421ed091-5396-40b6-bc2b-df2f8291198c`
- Notebook `aa597a7e-82ac-4a3d-ba36-29dcd96c2e24`
- Workspace identity SP `32087df7-ff95-490f-994f-e2a385f419ab` (app `43f02795-2596-41d6-b6e2-060588f33593`)
- OAuth2 connection `7ec42257-ca1c-4a4c-a173-c58b1bc7ab6c`

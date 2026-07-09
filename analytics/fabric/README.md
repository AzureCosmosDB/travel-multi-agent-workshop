# Fabric automation runbook — Cosmos mirroring, reverse-ETL, real-time analytics

This is the reproducible automation + findings for putting the Travel Assistant
optimization analytics on **Microsoft Fabric** with **near-real-time Cosmos DB
mirroring**, a reverse-ETL notebook, and a real-time Power BI story.

Everything here was driven via **REST + `az`** with a normal `az login` token —
**no MCP or extra tooling needed**. Fabric ARM support is limited, so mirroring,
notebooks, RBAC, and networking are automated through the **Fabric REST API** and
the **Azure Cosmos ARM API**.

- **Workspace:** Cosmos FabCon (`37733bf9-e6c2-4472-b4fb-22cb547079f7`), F64 capacity.
- **Cosmos:** `cosmos-kfpokdh52vbec` (rg `rg-mjb-fabcon-travel`), DB `TravelAssistantV2`.
  Already **provisioned throughput + Continuous backup** (both required for mirroring).

## What is automated (and proven)

| Step | How | State |
|---|---|---|
| Workspace identity | `POST /v1/workspaces/{id}/provisionIdentity` | ✅ SP `32087df7-ff95-490f-994f-e2a385f419ab` |
| Cosmos RBAC | custom `FabricMirroringRole` (`readMetadata`+`readAnalytics`) + built-in Data Contributor, assigned to the workspace identity | ✅ |
| Network trust | `EnableFabricNetworkAclBypass` capability + `networkAclBypass=AzureServices` + bypass resource id for the workspace | ✅ |
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

### Network trust (az) — required even without VNet

```powershell
az cosmosdb update -n cosmos-kfpokdh52vbec -g rg-mjb-fabcon-travel \
  --capabilities EnableNoSQLVectorSearch EnableFabricNetworkAclBypass \
  --network-acl-bypass AzureServices \
  --network-acl-bypass-resource-ids "/tenants/<tid>/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/Fabric/providers/Microsoft.Fabric/workspaces/<workspaceId>"
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
  config issue. **This is the escalation item** — it likely matures alongside the Service Principal
  connection support expected ~Aug/Sept. Once either lands, connection creation is one API call and
  the whole flow is hands-free.

## Reverse-ETL notebook — read-method note

`analytics/fabric/TravelAssistantOptimizationInsights.ipynb` computes per-tenant KPIs + per-tier cost
and writes them to Cosmos `OptimizationInsights` via the **Cosmos Spark connector** with Fabric AAD
(the workspace identity's Data Contributor role) — **no `%pip`, so it is safe in scheduled jobs**.

Open issue: reading the **mirrored** Delta tables. Mirrored tables use **deletion vectors**, so a
direct `spark.read.format("delta").load(onelake_path)` fails with *"Cannot work with a non-pinned
table snapshot"*. `spark.read.synapsesql(...)` on the mirror SQL endpoint is the next attempt.
**Reliable fix:** create a **Lakehouse shortcut** to the mirror tables and read via
`spark.read.table(...)` (a catalog reference pins the snapshot), or read via JDBC to the SQL endpoint.

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

- **Semantic model** over the mirror (Direct Lake) — scriptable via `POST /v1/workspaces/{id}/semanticModels`
  with a TMDL definition; not yet created for the V2 mirror.
- **Report visuals + `.pbit` template + attendee-usability test** — best finalized in **Power BI Desktop**
  against the mirror SQL endpoint / semantic model. `analytics/TravelAssistantReport.pbit` is the
  parameter-driven v1 template to adapt.

## IDs (dev)

- Workspace `37733bf9-e6c2-4472-b4fb-22cb547079f7` · capacity `38356b39-72d6-4c6c-85af-c1267e985370`
- Mirror `debe9a19-56de-4363-9ea9-88dc29baa003` · SQL endpoint `421ed091-5396-40b6-bc2b-df2f8291198c`
- Notebook `aa597a7e-82ac-4a3d-ba36-29dcd96c2e24`
- Workspace identity SP `32087df7-ff95-490f-994f-e2a385f419ab` (app `43f02795-2596-41d6-b6e2-060588f33593`)
- OAuth2 connection `7ec42257-ca1c-4a4c-a173-c58b1bc7ab6c`

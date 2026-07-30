# Translytical Apply/Revert — Power BI → Fabric UDF → Cosmos (spike runbook)

Click **Apply**/**Revert** on an optimization *in the Power BI report* → a Fabric
**User Data Function** flips the `OptimizationPolicies` doc in Azure Cosmos DB →
the running agent honors it on its next turn. This closes the operational⇄analytical
loop inside one surface — the definitive Fabric + Cosmos **translytical** story.

```
Power BI report (Apply/Revert button)
        │  translytical task flow (passes scenario)
        ▼
Fabric User Data Function  ── azure-cosmos ──►  Azure Cosmos DB: OptimizationPolicies
 (apply_optimization /                              (status active/reverted)
  revert_optimization)                                   │
                                                         ▼
                                    Travel agent reads the policy per turn → behavior changes
```

Based on the official sample: <https://github.com/AzureCosmosDB/cosmos-fabric-samples>
(`user-data-functions/` + `translytical-taskflows/`).

---

## Your deployment (fill these in)

| Value | Where |
|---|---|
| `COSMOS_URI` | `https://cosmos-iyaisgv7zrpyi.documents.azure.com:443/` (your `COSMOSDB_ENDPOINT`) |
| `DB_NAME` | `TravelAssistant` |
| Cosmos account name | `cosmos-iyaisgv7zrpyi` |
| Scenario to demo | `model-selection` |

---

## Step 1 — Create & publish the UDF

1. Fabric → **Data Engineering** → **+ New item** → **User data functions**. Name it e.g. `optimization-apply-loop`.
2. **New function** → paste all of [`optimization_policy_functions.py`](./optimization_policy_functions.py).
3. **Library Management** → **+ Add from PyPI** → `azure-cosmos` (latest) → wait for it to install.
4. Edit the two constants at the top: `COSMOS_URI` and `DB_NAME` (see the table above).
5. **Publish**.

## Step 2 — Grant the UDF's identity Cosmos **data-plane** RBAC

`@udf.connection(audienceType="CosmosDB")` gets an Entra token, but the identity
still needs the **Cosmos DB Built-in Data Contributor** *data-plane* role on the
account (control-plane "Contributor" does **not** grant data access).

First figure out **which principal** Fabric presents. Two candidates — grant both to be safe:
- **You** (interactive Test / your Power BI sign-in): your Entra user object id.
- The **Fabric workspace identity** (unattended/service): the workspace's managed identity (Workspace settings → Managed identity), or the Fabric **capacity** identity.

```powershell
# variables
$acct = "cosmos-iyaisgv7zrpyi"
$rg   = az resource list --name $acct --resource-type "Microsoft.DocumentDB/databaseAccounts" --query "[0].resourceGroup" -o tsv
$sub  = az account show --query id -o tsv
$scope = "/subscriptions/$sub/resourceGroups/$rg/providers/Microsoft.DocumentDB/databaseAccounts/$acct"

# your own object id (interactive path)
$me = az ad signed-in-user show --query id -o tsv

# Cosmos DB Built-in Data Contributor == role definition id 00000000-0000-0000-0000-000000000002
az cosmosdb sql role assignment create `
  --account-name $acct --resource-group $rg `
  --role-definition-id "00000000-0000-0000-0000-000000000002" `
  --principal-id $me `
  --scope $scope
```

Repeat `--principal-id` with the **workspace/capacity managed identity** object id for the Power BI-service path. (Find it in Workspace settings → Managed identity, or via `az resource show` on the Fabric capacity.)

> Note: `--scope` at the account level covers all DBs/containers; you can narrow to the DB/container if you prefer.

## Step 3 — Test the writeback (portal)

1. In the UDF editor, hover the function → **Test**.
2. `apply_optimization` with `scenario = model-selection` → run. Expect
   `{"scenario":"model-selection","status":"active","version":N,...}`.
3. `get_optimization_status` with `scenario = model-selection` → confirm `status=active`.
4. `revert_optimization` → confirm `status=reverted`.

Verify from the app side (any of):
```powershell
# the console/API now reflects the flipped status
curl "http://localhost:8000/optimizations/marvel" | ConvertFrom-Json | Select -Expand recommendations |
  Where scenario -eq 'model-selection' | Select scenario,status
```
Or check Cosmos Data Explorer: `OptimizationPolicies` doc `id=model-selection`.

## Step 4 — Test via REST (automation proof)

Published UDFs expose an Entra-secured REST endpoint (copy it from the function's
… menu → **Copy URL**, or the function properties). Invoke with a bearer token:

```powershell
$fnUrl = "<PASTE THE PUBLISHED FUNCTION URL>"   # .../apply_optimization/invoke (exact shape from the portal)
$token = az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv
Invoke-RestMethod -Method Post -Uri $fnUrl -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" -Body (@{ scenario = "model-selection"; by = "rest-test" } | ConvertTo-Json)
```

> The exact resource/audience for the token and the URL shape are shown in the
> portal; we'll confirm them together when you paste the published URL. If the
> Fabric-API audience is rejected, the portal's "Copy URL" page lists the correct one.

## Step 5 — Wire the Power BI buttons (translytical task flow)

1. Power BI Desktop with **translytical task flow** preview features enabled
   (Options → Preview features), connected to the report.
2. Add a **Button** → Action **Data function** → pick your workspace → the
   `apply_optimization` function → map the parameter `scenario` to the selected
   optimization (a slicer field or a fixed value `model-selection`); set `by="powerbi"`.
3. Duplicate for **Revert** → `revert_optimization`.
4. Optionally add the `get_optimization_status` result (or the `optimization_result`
   saving from `OptimizationInsights`) as a card so the report shows the effect.

Full walkthrough: the `translytical-taskflows/` sample README.

---

## Fallback — self-authenticated client (if the managed connection can't reach an *external* Azure Cosmos account)

The sample targets a **Fabric-native** Cosmos item. If `@udf.connection` can't
reach our external Azure Cosmos account, drop the decorator and build the client
in-function. Two credential options:

**(a) Cosmos key** (simplest to prove connectivity; store as a UDF parameter/secret, not in source):
```python
from azure.cosmos import CosmosClient
@udf.function()
def apply_optimization(scenario: str, cosmosKey: str, by: str = "powerbi"):
    client = CosmosClient(COSMOS_URI, credential=cosmosKey)
    container = client.get_database_client(DB_NAME).get_container_client(POLICIES_CONTAINER)
    return _set_status(container, scenario, "active", by)
```

**(b) Managed identity** (keyless; needs the same data-plane RBAC as Step 2 on the UDF/workspace identity):
```python
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient
@udf.function()
def apply_optimization(scenario: str, by: str = "powerbi"):
    client = CosmosClient(COSMOS_URI, credential=DefaultAzureCredential())
    container = client.get_database_client(DB_NAME).get_container_client(POLICIES_CONTAINER)
    return _set_status(container, scenario, "active", by)
```
Add `azure-identity` in Library Management for option (b).

---

## Verify end-to-end (the money shot)

1. Start the app + a policy-aware simulator: `Run-TrafficSimulator.ps1 -Tenant DemoLive -Forever`
   (baseline single-model until applied).
2. In Power BI, click **Apply** on model-selection → the UDF flips the policy.
3. Within ~15s the simulator prints `model policy changed -> TIERED`, cost/turn drops,
   and the `optimization_result` saving climbs — visible in the report. Click **Revert** to undo.

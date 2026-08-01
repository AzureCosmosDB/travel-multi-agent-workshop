# Translytical Apply/Revert — Power BI → Fabric UDF → Cosmos

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

## Deployed automatically

`Provision-Fabric.ps1` (the Module 09 Fabric provisioning) deploys this UDF in Phase 2:
it injects your Cosmos endpoint + database, installs `azure-cosmos`, publishes the
functions, and grants the deploying user Cosmos data-plane write. That's everything the
loop needs: the **Optimization Console** already applies/reverts policies through the app's
`/optimizations` API. Wiring the Power BI buttons (Step 5) is an **optional, tenant-gated
extra**. The steps below are for reference, or if you want to author/customize the function
by hand.

## Values

| Value | Source |
|---|---|
| `COSMOS_URI` | your `COSMOSDB_ENDPOINT` (`https://<account>.documents.azure.com:443/`) |
| `DB_NAME` | your `COSMOS_DB_DATABASE_NAME` (default `TravelAssistant`) |
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

## Step 4 — Invoke via REST (automation / verification)

Published UDFs expose an Entra-secured REST endpoint. Get the base URL from the
function's **…** menu → **Copy URL** (or the generated OpenAPI `servers.url`); each
function is `{base}/{function_name}/invoke`. Authenticate with a bearer token for
the `https://api.fabric.microsoft.com` audience:

```powershell
$base  = "<FUNCTIONS BASE URL from Copy URL / OpenAPI servers.url>"
$token = az account get-access-token --resource "https://api.fabric.microsoft.com" --query accessToken -o tsv
$h     = @{ Authorization = "Bearer $token" }

# read (non-mutating)
(Invoke-RestMethod -Method Post -Uri "$base/get_optimization_status/invoke" -Headers $h `
  -ContentType "application/json" -Body '{"scenario":"model-selection"}').output

# apply, then revert
(Invoke-RestMethod -Method Post -Uri "$base/apply_optimization/invoke" -Headers $h `
  -ContentType "application/json" -Body '{"scenario":"model-selection","by":"rest"}').output
(Invoke-RestMethod -Method Post -Uri "$base/revert_optimization/invoke" -Headers $h `
  -ContentType "application/json" -Body '{"scenario":"model-selection","by":"rest"}').output
```

The function return is under the `output` field of the response (alongside
`functionName`, `invocationId`, `status`, `errors`).

## Step 5 — Wire the Power BI buttons (translytical task flow) — *optional*

> **Optional enhancement — not required for the loop.** The primary, always-available way to
> apply/revert an optimization is the **Optimization Console** (its Apply/Revert buttons call
> the app's `/optimizations/{scenario}/apply|revert` API). The Power BI button below just
> triggers that same policy flip from *inside the report* — a nicety, not a dependency.
>
> **Correction (2026-08-01, per owner):** the real blocker below was later identified as a **transient product bug** in the translytical data-function button (fix expected ≈ mid-Aug 2026), **not** a tenant setting. Treat the "missing dropdowns" as that bug; re-verify once the fix ships. The original note is kept for reference.
>
> **Prerequisite — a Fabric tenant admin must enable a preview feature.** Translytical task
> flows are in preview. An admin enables **Admin portal → Tenant settings → "Users can create
> and consume translytical task flows"** (label varies by rollout — search *translytical* /
> *task flow* / *data function*), optionally scoped to a security group you're in. Allow
> ~15 min to propagate. **If it's off, the button's Workspace / Function set / Function
> dropdowns simply never appear — with no error.** That missing-dropdowns symptom is the
> tenant setting, not a report or UDF problem.

The functions **return a string** — required for data-function buttons.

> **Add the buttons in the Power BI *Service* (edit in the browser), not Desktop.** In the
> current rollout the data-function button config UI (Workspace / Function set / Data
> function dropdowns) appears reliably only in the Service, and the button fires only
> there. Publish the report first, then add the buttons in the browser.

1. Publish the report, open it in the **Power BI Service** → **Edit**.
2. Add a constant measure for the scenario: `Apply Scenario = "model-selection"`.
3. Add a **Button** → **Format → Action** (On) → Type **Data function**, then fill all
   three dropdowns: **Workspace** → **Function set** `optimization-apply-loop` →
   **Data function** `apply_optimization`. The parameters appear only after the
   Data function is chosen.
4. There is **no static-value option**: click the **`fx`** next to `scenario` and pick
   the `Apply Scenario` measure (or bind to a slicer). Leave `by` unmapped (defaults to
   `powerbi`).
5. Duplicate for **Revert** → Data function `revert_optimization`.
6. Optionally add the `optimization_result` saving from `OptimizationInsights` as a card
   so the report shows the effect.

> Buttons don't fire in Power BI Desktop (they only validate/restyle) — **publish to the
> Power BI Service** to click Apply/Revert for real.

Full walkthrough: the `translytical-taskflows/` sample README.

---

## Alternative auth — self-authenticated client

The functions above use Fabric's managed `@udf.connection`, which reaches the
Azure Cosmos account directly. If you prefer to manage the client yourself, drop
the decorator and build it in-function. Two credential options:

**(a) Cosmos key** (store as a UDF parameter/secret, not in source):
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
2. Apply **model-selection** — from the **Optimization Console** (reliable), or the Power BI
   **Apply** button if translytical task flows are enabled → the policy flips in Cosmos.
3. Within ~15s the simulator prints `model policy changed -> TIERED`, cost/turn drops,
   and the `optimization_result` saving climbs — visible in the report. Click **Revert** to undo.

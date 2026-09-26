# Travel Multi-Agent — Run and Demo Guide

This guide is the short operational path for the completed travel assistant and its Cosmos-to-
Fabric optimization loop. The detailed presenter talk track is in
[`analytics/docs/demo-script.md`](../analytics/docs/demo-script.md).

## What to highlight

1. LangGraph coordinates travel specialists and tools.
2. Persisted profile preferences are authoritative; inferred conversational memory adds absent or
   scoped context.
3. Cosmos DB is the live operational system of record.
4. Fabric Mirroring and the SQL analytics endpoint feed analytical work without scanning the live
   request path.
5. Reverse ETL writes small, governed insights back to Cosmos.
6. Apply/Revert is scoped and reversible; observed traffic must be remeasured before claiming a
   result.

## Configure and deploy

From `02_completed`:

```powershell
azd auth login
azd up
```

`azd up` provisions the Azure resources, deploys the completed application when hosted deployment
is enabled, writes local environment files, and may seed an empty environment or idempotently
ensure initial seed records.

It does **not**:

- invoke controlled reset;
- generate the controlled traffic burst;
- recompute the controlled snapshot; or
- silently restore an existing environment to presentation state.

Controlled reset is a deliberate operator action from the web analytics portal.

Provision the Fabric workspace, mirror, completed notebook, User Data Function, semantic model,
and report separately:

```powershell
cd ..\analytics\fabric
.\Provision-Fabric.ps1 -Solution
```

The provisioner prompts for the Fabric workspace and the connection identifier required by the
Fabric portal. Do not store environment-specific workspace, mirror, SQL endpoint, report, or User
Data Function identifiers in repository documentation.

## Run locally

Use three terminals from `02_completed`:

```powershell
# MCP server
.\.venv-travel\Scripts\Activate.ps1; cd mcp_server; $env:PYTHONPATH="..\python"; python mcp_http_server.py

# Travel API
.\.venv-travel\Scripts\Activate.ps1; cd python; uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000

# Frontend
cd frontend; npm install; npm start
```

Run the analytics portal as a separate static process when developing locally:

```powershell
python -m http.server 8060 --directory ..\analytics\dashboard
```

## Browser setup

Prepare these browser instances or clearly separated windows before presenting:

| Browser instance | Tab | Required location |
|---|---|---|
| Travel app | Explore | Seeded user signed in |
| Travel app | Profile and Memories | Persisted preferences and inferred memories visible |
| Travel app | Trips | Planned Barcelona trip visible |
| Azure portal | Cosmos Data Explorer | `TravelAssistant` database |
| Fabric | Mirrored database | Replication status and mirrored tables |
| Fabric | SQL analytics endpoint | `OptimizationTurns` and `OptimizationInsights` |
| Fabric | Notebook | Completed `ConversionFunnelReverseETL` notebook at the top |
| Fabric | User Data Function | `optimization-apply-loop`; apply, revert, internal status-write functions |
| Fabric | Power BI | Portfolio Overview; Optimizations ready |
| Hosted app | Web analytics portal | Overview and all analytical tabs reachable |

## Presentation modes

### Portal Live mode

Use this mode only when you intend to execute the controlled transition:

1. Verify identity and deployed inventory.
2. Take and verify a durable backup.
3. Run controlled Reset.
4. Validate the direct Cosmos baseline.
5. Recompute the baseline snapshot.
6. Wait for mirror convergence and verify the SQL endpoint.
7. Refresh Power BI.
8. Apply the Analytics model-selection recommendation.
9. Generate the approved Analytics controlled burst.
10. Validate source rows, recompute, wait for the mirror, and refresh Power BI.

Run these steps serially. Do not use **Freshen Turn Times**.

### Prepared Fabric / Power BI mode

Prepare and validate the complete snapshot off-stage. During the presentation, do not reset,
apply/revert, generate traffic, freshen timestamps, or run the full notebook unless that exact
action was separately rehearsed.

## Controlled state contract

After Reset and before controlled traffic:

- Marvel: 200 all-premium turns; **Not Applied · Before**.
- Analytics: 200 all-premium turns; **Not Applied · Before**.
- Both cohorts: 20 populated minute buckets; funnel `192 → 184 → 92 → 56`; conversion `29.2%`;
  largest cause `city_friction`.
- Normal user trips outside fixture ownership remain available.

After Apply but before new traffic:

- Analytics: **Policy Active · Awaiting Traffic · Before**.

After the controlled Analytics burst and explicit Recompute:

- Marvel remains **Not Applied · Before**.
- Analytics has 400 turns total: 270 premium, 110 mini, and 20 nano; **Applied · After**.

The Analytics result is **Measured**. Recommendation-card and volume values are **Projected** or
**Estimated**. Revert changes future routing and preserves captured After data.

Missing, incomplete, duplicate, conflicting, malformed-token, unknown-deployment, or
wrong-model-mix rows are failures, not successful demo states.

## Five-demo presenter flow

### Demo 1 — Frontend application

Start on Explore. Show Profile and Memories, then Trips and the planned Barcelona trip. Ask the
assistant to add a concrete hotel, restaurant or meal, or activity to the existing planning trip.
Breakfast can be an example, but it is not the sole capability.

Verify:

- one authoritative planning trip was resolved;
- a concrete candidate was discovered;
- only the requested itinerary field changed;
- trip ID, dates, planning status, and unrelated fields were preserved; and
- the trip count stayed unchanged with no duplicate.

If zero or multiple planning trips are plausible, the assistant should clarify rather than create
or mutate a trip.

### Demo 2 — Cosmos, mirroring, and SQL endpoint

Show the `TravelAssistant` operational records in Cosmos, the mirrored database replication state,
and the SQL analytics endpoint tables. Use `OptimizationTurns` to explain observed behavior and
`OptimizationInsights` to explain reverse-ETL results.

### Demo 3 — Fabric notebook

Show the completed notebook in this order:

1. read the mirror;
2. classify abandonment cause;
3. calculate measured model-selection saving;
4. reverse-ETL analytical rows;
5. review the LLM analyst and deterministic guardrails.

In Prepared mode, use already completed output.

### Demo 4 — User Data Function

Open `optimization-apply-loop` and show:

1. `apply_optimization`;
2. the internal status-write function and exact Cosmos upsert; and
3. `revert_optimization`.

The User Data Function owns only the scoped policy state write. Reset, synthetic traffic,
recompute, and timestamp maintenance remain outside it.

### Demo 5 — Power BI and web analytics portal

In Power BI, show Portfolio Overview and Optimizations, then the tenant comparison. In the web
analytics portal, walk Overview, Optimizations, Model Selection, Memory, Agents, Business, and
Governance.

Keep the source distinction explicit:

- **Portal Live** reads and recomputes current operational data.
- **Prepared Fabric / Power BI** displays a validated mirrored and reverse-ETL snapshot.

A missing measured row should display **Not measured yet** or blank. `$0.00` is reserved for a
real completed measurement whose result is zero.

## Failure and rollback

If any mutation, validation, mirror, or report check fails:

1. stop the sequence;
2. do not continue to recompute or refresh downstream presentation surfaces;
3. restore only manifest-owned rows and policy state from the durable backup;
4. restore deployment definitions and Container Apps traffic if changed; and
5. verify direct Cosmos state, mirror state, and report state before resuming.

Elapsed time is not evidence of convergence.

## Tear down

When the disposable environment is no longer needed, remove its Azure resources with the normal
`azd down --purge` workflow and remove the associated Fabric workspace separately.

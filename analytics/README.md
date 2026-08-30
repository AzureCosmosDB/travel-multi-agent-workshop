# Travel Assistant — Analytics

The analytics track turns the app's own Cosmos data into **agent-optimization** and **memory-intelligence** insight, and lands it back where the app can act on it. The full loop is:

```
Cosmos DB  →  Fabric mirrored database  →  reverse-ETL notebook (Spark)
     →  OptimizationInsights (back in Cosmos)  →  Analytics Portal + Power BI report
```

Everything here is **auto-deployed** — `azd up` seeds the data and `Provision-Fabric.ps1` stands up the mirror, notebook, translytical UDF, and the Power BI report already pointed at your mirror. You normally don't build anything by hand.

## Where to look

| I want to… | Go to |
|---|---|
| View results / take optimization actions (the web portal) | [`dashboard/README.md`](dashboard/README.md) — the **Analytics Portal**, served at `/analytics/` |
| Stand up Fabric (mirror + notebook + UDF + report) | [`fabric/README.md`](fabric/README.md) — the automation runbook (`Provision-Fabric.ps1`) |
| Understand / maintain the Power BI report | [`powerbi/PowerBI_Optimization_Build_Guide.md`](powerbi/PowerBI_Optimization_Build_Guide.md) |
| See how insight rows are computed (reference twin of the notebook) | [`fabric/compute_insights.py`](fabric/compute_insights.py) |

The PBIR report and TMDL semantic model under `powerbi/` are hydrated and deployed into your Fabric
workspace automatically; attendees open the report in the browser, not Power BI Desktop.

## Data

A pre-baked **golden dataset** (conversations, memories, trips, and the `OptimizationTurns` signal for the `analytics` + `marvel` tenants) ships under `python/data/` and is loaded into Cosmos **offline, with no LLM calls** by `seed_data.py`, which `azd up` runs in its post-provision hook. A fresh `azd up` therefore gives you a fully-populated app and a working local **Analytics Portal** immediately.

Fabric analytics still require you to **configure Cosmos mirroring** (Module 09 / `Provision-Fabric.ps1`) so the seeded rows replicate into Fabric.

To produce your own data instead of using the golden set:

- `scripts/traffic_simulator.py` + `scripts/Run-TrafficSimulator.ps1` — drive turns for a real-time analytics demo (watch the portal update as traffic flows). Policy-aware: applying the model-selection policy re-tiers the same workload, so it doubles as the model-selection before/after.
- `scripts/funnel_seed.py`, `scripts/marvel_seed.py` — targeted seeders for specific analytics scenarios (the conversion funnel on `analytics`, and the `marvel` login users).

## File reference

| File / dir | Purpose |
|---|---|
| `dashboard/` | The **web Analytics Portal** (single-page app served at `/analytics/`) — live/reverse-ETL viewing plus completed-demo maintenance tools |
| `fabric/` | Fabric automation: `Provision-Fabric.ps1`, `provision_fabric.py`, the reverse-ETL notebook (`ConversionFunnelReverseETL.ipynb`), `compute_insights.py`, the translytical UDF, and the Cosmos→Fabric mirroring RBAC step (done automatically by provisioning) |
| `scripts/` | Seeders + demo tools: `funnel_seed.py`, `marvel_seed.py` (scenario seeders), `traffic_simulator.py` / `Run-TrafficSimulator.ps1` (policy-aware live traffic), `optimization_mining.py` (mines optimization opportunities from the traffic) |
| `powerbi/` | The deployed Power BI surface: `TravelAssistantAnalyticsReport.Report` (PBIR), `TravelAssistantAnalyticsReport.SemanticModel` (TMDL), build guide, theme, and `legacy/` templates |
| `docs/` | Maintainer notes, ADRs, vision, and charter for the analytics redesign |
| `evaluation/` | v2 routing evaluation harness (local regression gate for the supervisor + sub-agents-as-tools architecture) |
| `spikes/` | ADR-0012 validation spikes — throwaway design proofs |
| `media/` | Screenshots |

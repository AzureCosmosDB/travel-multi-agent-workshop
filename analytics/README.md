# Travel Assistant — Analytics

The analytics track turns the app's own Cosmos data into **agent-optimization** and **memory-intelligence** insight, and lands it back where the app can act on it. The full loop is:

```
Cosmos DB  →  Fabric mirrored database  →  reverse-ETL notebook (Spark)
     →  OptimizationInsights (back in Cosmos)  →  Power BI report + Optimization Console
```

Everything here is **auto-deployed** — `azd up` seeds the data and `Provision-Fabric.ps1` stands up the mirror, notebook, translytical UDF, and the Power BI report already pointed at your mirror. You normally don't build anything by hand.

## Where to look

| I want to… | Go to |
|---|---|
| Stand up Fabric (mirror + notebook + UDF + report) | [`fabric/README.md`](fabric/README.md) — the automation runbook (`Provision-Fabric.ps1`) |
| Understand / rebuild the Power BI report | [`PowerBI_Optimization_Build_Guide.md`](PowerBI_Optimization_Build_Guide.md) |
| Build just the Memory Intelligence page | [`MemoryIntelligence_Page_Spec.md`](MemoryIntelligence_Page_Spec.md) |
| See how insight rows are computed (reference twin of the notebook) | [`fabric/compute_insights.py`](fabric/compute_insights.py) |

The report (`TravelAssistantAnalyticsReport.pbix`) is imported into your Fabric workspace automatically; attendees open it in the browser, not Power BI Desktop.

## Data

A pre-baked **golden dataset** (conversations, memories, trips, and the `OptimizationTurns` signal for the `analytics` + `marvel` tenants) ships under `python/data/` and is loaded into Cosmos **offline, with no LLM calls** by `seed_data.py`, which `azd up` runs in its post-provision hook. A fresh `azd up` therefore gives you a fully-populated app and a working local **Optimization Console** immediately.

Fabric analytics still require you to **configure Cosmos mirroring** (Module 09 / `Provision-Fabric.ps1`) so the seeded rows replicate into Fabric.

To produce your own data instead of using the golden set:

- `data_generator.py` / `data_enricher.py` — LLM-driven persona conversations that generate memories, trips, and preference-conflict supersessions. Full from-scratch generation is expensive (~3 hrs / ~10M tokens), which is why the committed golden dataset exists.
- `traffic_simulator.py` + `Run-TrafficSimulator.ps1` — drive live turns for a real-time analytics demo (watch the report/Console update as traffic flows).
- `funnel_seed.py`, `marvel_seed.py`, `trivial_seed.py`, `ab_demo_seed.py` — targeted seeders for specific analytics scenarios (conversion funnel, the `marvel` tenant, trivial-turn cost, A/B demo).

## File reference

| File / dir | Purpose |
|---|---|
| `fabric/` | Fabric automation: `Provision-Fabric.ps1`, `provision_fabric.py`, the reverse-ETL notebook (`ConversionFunnelReverseETL.ipynb`), `compute_insights.py`, and the translytical UDF |
| `TravelAssistantAnalyticsReport.pbix` | The committed Power BI report (DirectQuery over the mirror; auto-imported by provisioning) |
| `PowerBI_Optimization_Build_Guide.md` | Step-by-step guide to rebuild/customize the report (optimization pages + Memory Intelligence page) |
| `MemoryIntelligence_Page_Spec.md` | Build spec for the Memory Intelligence report page |
| `data_generator.py` / `data_enricher.py` | LLM data generation + preference-conflict enrichment (optional; golden dataset is preferred) |
| `traffic_simulator.py` / `Run-TrafficSimulator.ps1` | Live traffic driver for the real-time demo |
| `optimization_mining.py` | Mines optimization scenarios/opportunities from the traffic |
| `funnel_seed.py`, `marvel_seed.py`, `trivial_seed.py`, `ab_demo_seed.py`, `demo_live_turns.py` | Scenario seeders / demo helpers |
| `rbac-mirror.ps1` / `rbac-mirror.sh` | Grant Cosmos RBAC for Fabric mirroring (provisioning also does this automatically) |
| `docs/` | Maintainer notes, ADRs, and charter for the analytics redesign |
| `evaluation/` | LLM-as-judge evaluation harness |
| `media/` | Screenshots |

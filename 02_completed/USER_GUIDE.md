# Travel Multi-Agent — Run & Demo Guide

How to **configure, run, and demo** the complete solution — a multi-agent travel
assistant on **Azure Cosmos DB** (operational) with a **Microsoft Fabric** analytics +
optimization loop (analytical), joined by mirroring, reverse-ETL, and a translytical
write-back.

> Want the deep API/architecture reference or to build these pieces step by step? See the
> `README.md` and the workshop modules in `01_exercises/workshop/`. This guide is the
> short path to running and demoing.

---

## What to highlight (the key concepts)

Keep the audience focused on these — everything below is in service of showing them:

1. **Multi-agent orchestration** — an orchestrator routes to hotel / activity / dining / itinerary specialists that hand off to each other.
2. **Persistent memory** — the assistant learns preferences across conversations (no "remember that…" needed).
3. **Semantic search** — describe what you want in plain language; Cosmos DB vector search finds places by meaning.
4. **Two planes** — **Cosmos = operational** (the live agent), **Fabric = analytical** (the brain), joined by **mirroring** + **reverse-ETL**.
5. **The optimization apply-loop** — instrument → **detect** (Console) → **analyze/measure** (Fabric) → **apply** a policy → **re-measure** the real saving.
6. **Translytical write-back** — click **Apply** in a Power BI report; a Fabric **User Data Function** flips a policy in Cosmos and the agent honors it on its next turn.

---

## 1. Configure & deploy

From `02_completed/`:

```powershell
azd auth login   # same work account/tenant as your az login
azd up
```

`azd up` provisions Cosmos DB, Azure OpenAI (`gpt-5.1` / `gpt-5-mini` / `gpt-5-nano` +
embeddings), the **Fabric F2 capacity**, and — because `deployHostedApp` defaults to
**true** — the hosted frontend/API/MCP. The post-provision hook writes the `.env` files,
creates the **`.venv-travel`** virtualenv, and **seeds Cosmos** (including the
`funnel_demo` analytics tenant). It prints **`FRONTEND_URI`** when done.

Two flags matter (set with `azd env set <NAME> <value>` before `azd up`):

| Flag | Default | Keep for the demo? |
|---|---|---|
| `DEPLOY_ANALYTICS` | `true` | **Yes** — analytics containers + the Fabric capacity (Acts 2–7). |
| `DEPLOY_HOSTED_APP` | `true` | Yes for a hosted URL; set `false` to run locally only. |

**Stand up the Fabric analytics** (the workspace/mirror/notebook/UDF that `azd` doesn't
create). Run it with **`-Solution`** (the completed notebook — no TODOs):

```powershell
cd ..\analytics\fabric
.\Provision-Fabric.ps1 -Solution
```

It reads your `azd` environment, prompts for a workspace name and — for one portal step —
a Cosmos connection id (**New → Mirrored Azure Cosmos DB**, sign in with your
**Organizational account**, copy the connection id). It then creates the mirror, uploads
the completed `ConversionFunnelReverseETL` notebook, deploys the `optimization-apply-loop`
**UDF**, and grants your account Cosmos write access. Details: `analytics/fabric/README.md`.

---

## 2. Run

**Hosted:** open the `FRONTEND_URI` from `azd up`.

**Local** — from `02_completed/`, in separate terminals:

```powershell
# MCP tool server
.\.venv-travel\Scripts\Activate.ps1; cd mcp_server; $env:PYTHONPATH="..\python"; python mcp_http_server.py
# Travel API  (wait for "Agents initialized successfully")
.\.venv-travel\Scripts\Activate.ps1; cd python; uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
# Frontend
cd frontend; npm install; npm start
# Optimization Console (static app — no venv)
python -m http.server 8050 --directory console
```

Frontend `:4200` · API docs `:8000/docs` · Optimization Console `:8050`. Sign in as any of
the seeded demo users (`tony`, `steve`, `bruce`, `peter`, all under tenant **`marvel`**).

---

## 3. Demo script

The arc: **talk to the agent → see the signal → see the analytics → generate traffic →
measure in Fabric → apply an optimization → re-measure the payoff.**

### Act 1 — Talk to the assistant *(multi-agent · memory · semantic search)*
In the frontend, plan a trip: *"Plan a 3-day trip to Amsterdam for two."* Then ask for
hotels, dining, and an itinerary. Call out:
- the **orchestrator handing off** to specialists (watch the response build across agents);
- **semantic search** — *"find a quiet boutique hotel near cultural sites"* returns by meaning, not filters;
- **memory** — say *"I'm vegetarian and need wheelchair access,"* start a new chat, and see it personalize without you repeating yourself (Profile page shows learned memories).

Every turn is captured operationally in Cosmos under tenant `marvel`.

### Act 2 — See the signal *(Optimization Console)*
Open **http://localhost:8050**, set **Tenant = `marvel`**, **Refresh**. Walk the panels:
turns & spend, trivial-turn waste, the **single-model** pattern, and the **recommendation
cards** (e.g. *Capability-tiered model selection*). *Thousands of turns become a handful of
decisions.*

### Act 3 — See the analytics baseline *(Power BI)*
Open **`analytics/TravelAssistantAnalyticsReport.pbit`**. When prompted, enter **your**
mirror's **SQL analytics endpoint** and database (`TravelAssistantAnalytics`) — they're
parameters — and sign in with your **Organizational account**. Show **cost by tier** and
**turns over time** on the single-model baseline.

### Act 4 — Generate live traffic *(the simulator)*
Make the dashboards move. From `analytics/`:

```powershell
.\Run-TrafficSimulator.ps1 -Tenant DemoLive -Rate 120 -Minutes 10
```

Turns stream into Cosmos → the mirror carries them → Power BI (filtered to `DemoLive`)
updates live. No optimization applied yet, so it runs the **single-model baseline**.

### Act 5 — Measure in Fabric *(the reverse-ETL loop)*
Open the **`ConversionFunnelReverseETL`** notebook in your Fabric workspace (`TENANT =
"funnel_demo"`) and run the cells. It computes the **conversion funnel** and the **measured
saving** over the mirror and **reverse-ETLs** them to Cosmos `OptimizationInsights`. Back in
Power BI, the **Business Impact** and **Measured Saving** pages **light up** — you never
touched the report. *Cosmos → Fabric → reverse-ETL → Cosmos → mirror → Power BI.*

### Act 6 — Apply an optimization *(two ways)*
- **From the Console/API:** apply **model-selection** — a one-click, reversible policy flip.
- **From the report (translytical):** click **Apply** on the Power BI *Applied Optimizations*
  page. It calls the Fabric **UDF**, which flips the policy in Cosmos; the agent honors
  capability-tiered model selection on its **next turn**. *The analytical report just steered
  the operational system.* Click **Revert** to undo.

### Act 7 — Re-measure the payoff
Re-run the simulator — now **policy-aware**, it serves the **tiered** mix:

```powershell
.\Run-TrafficSimulator.ps1 -Tenant DemoLive -Rate 120 -Minutes 10
```

Re-run the notebook and watch the **Measured Saving** page: cost per turn drops and the
saving % climbs — a **measured** before/after, not an estimate. Revert to show it return to
baseline.

---

## Tenants used (cheat sheet)

| Tenant | Comes from | Used in |
|---|---|---|
| `marvel` | live chat from the frontend | Console *detect* (Act 2) |
| `funnel_demo` | seeded by `azd up` | Fabric notebook → Business Impact + Measured Saving (Act 5) |
| `DemoLive` | the traffic simulator | Power BI cost/turns + before/after (Acts 4, 7) |

## Reset & stop the meter

- **Pause the Fabric capacity when idle** (it bills while running): the Console's Fabric
  controls, `POST /optimizations/fabric/capacity/suspend`, or the Azure/Fabric portal.
- **Revert** any applied policy to return to baseline.
- **Tear down:** `azd down` from `02_completed/`.

## Quick troubleshooting

- **Power BI shows the wrong/old server** → **Transform data → Manage Parameters**, set `MirrorSQLEndpoint` / `MirrorDatabase`, **Close & Apply → Refresh**; clear cached creds under **Options → Data source settings**.
- **Notebook read error / no rows** → the mirror's SQL endpoint is syncing: open the mirrored database → **SQL analytics endpoint → Refresh**, confirm the capacity isn't paused, wait ~1–2 min, re-run.
- **Console empty** → the API is running and the **Tenant** matches where you drove traffic (case-sensitive `marvel`).
- **Provisioning auth errors** → `az login` and `azd auth login` must be the **same work account** in the subscription's tenant.

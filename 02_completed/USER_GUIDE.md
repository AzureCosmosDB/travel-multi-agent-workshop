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
`funnel_demo` analytics tenant) and prints **`FRONTEND_URI`** when done. **`azd up` takes roughly 20–25 minutes** (Azure provisioning + data seed + container image builds).

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
a Cosmos connection id (**Manage connections and gateways → New → Azure Cosmos DB v2**, sign in with your
**Organizational account**, copy the connection id). It then creates the mirror, uploads
the completed `ConversionFunnelReverseETL` notebook, deploys the `optimization-apply-loop`
**UDF**, and grants your account Cosmos write access. Details: `analytics/fabric/README.md`.

---

## 2. Run

### Hosted (the deployed apps) — nothing to start

`azd up` already deployed the app — just open the URLs. Get `FRONTEND_URI` anytime with
`azd env get-value FRONTEND_URI` (from `02_completed/`).

| Open | URL | Notes |
|---|---|---|
| **Travel Assistant app** | `<FRONTEND_URI>` | Sign in as a seeded demo user — `tony`, `steve`, `bruce`, or `peter` (all under tenant **`marvel`**). |
| **Optimization Console** | `<FRONTEND_URI>/console/` | Served from the *same* container; auto-targets the deployed API. Set **Tenant = `marvel`**. |
| **API docs (Swagger)** | `<FRONTEND_URI>/api/docs` | The API itself has **internal** ingress — you reach it through the frontend's `/api` proxy, not directly. |
| **Analytics report** | your **Fabric workspace** → `TravelAssistantAnalyticsReport` | Auto-imported and pointed at your mirror (Section 1). |

The **traffic simulator** (Acts 4/7) writes **straight to Cosmos** (`az login` + your deployment's
`COSMOSDB_ENDPOINT`), so it drives the hosted demo from your machine with **no local servers running**.

### Local (for development)

Run the stack yourself — from `02_completed/`, in separate terminals:

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

> Everything below works against your **deployed** apps — "the frontend" means `<FRONTEND_URI>` and
> "the Console" means `<FRONTEND_URI>/console/` — or your local servers from Section 2, whichever
> you're running. The report + notebook always live in your **Fabric workspace**.

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
Open **`TravelAssistantAnalyticsReport`** in your **Fabric workspace** — `Provision-Fabric.ps1 -Solution`
auto-imported it and already pointed it at your mirror. Show
**cost by tier** and **turns over time** on the single-model baseline.

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

### Act 6 — Apply an optimization
- **From the Console/API:** apply **model-selection** — a one-click, reversible policy flip.
- **From the report (translytical write-back):** click **Apply Optimization** on the Power BI
  *Applied Optimizations* page. It calls the Fabric **UDF**, which flips the policy in Cosmos;
  the agent honors capability-tiered model selection on its **next turn**. *The analytical report
  just steered the operational system.* Click **Revert** to undo. *(The Console/API perform the
  identical flip, so you always have a non-Power-BI path.)*

### Act 7 — Re-measure the payoff
Re-run the simulator — now **policy-aware**, it serves the **tiered** mix:

```powershell
.\Run-TrafficSimulator.ps1 -Tenant DemoLive -Rate 120 -Minutes 10
```

Re-run the notebook and watch the **Measured Saving** page: cost per turn drops and the
saving % climbs — a **measured** before/after, not an estimate. Revert to show it return to
baseline.

---

## Reading the dashboards

The auto-deployed **`TravelAssistantAnalyticsReport`** has **seven pages** (open it in your Fabric
workspace — it's already pointed at your mirror). What each one tells you, and how to use it:

### Optimization Overview
![Optimization Overview](../analytics/media/report_optimization_overview.png)
The fleet-level baseline a trace can't give you: **Total Turns**, **Trivial %** (share of turns that
need no reasoning), **Est Cost USD**, and **Cost per Outcome** (cost ÷ confirmed trips — the number
to actually optimize), plus turns by model. The *Trivial % by Turn Minute* line is a live pulse as
traffic flows.

### Cost by Tier
![Cost by Tier](../analytics/media/report_cost_by_tier.png)
Spend and cache-hit rate grouped by the tier that served each turn, with a per-deployment
breakdown. Before you optimize it's all one tier; after model-selection it splits — and you judge
on **cost per outcome**, not per turn.

### Optimization Opportunity
![Optimization Opportunity](../analytics/media/report_optimization_opportunity.png)
Quantifies the model-selection opportunity: the **Trivial %** gauge plus a plain-language
recommendation and impact. The stacked *Total Turns by Turn Minute and Model Tier* shows the tier
mix over time.

### Applied Optimizations
![Applied Optimizations](../analytics/media/report_applied_optimizations.png)
The governance/audit log: every policy the loop proposed, applied, or reverted — with status,
version, who proposed it, and when it last changed. **Click *Apply Optimization*** to activate the
selected policy: the Fabric **User Data Function** flips the policy doc in Cosmos and the agent
honors it on its **next turn**; **Revert** rolls it back. The analytical report writes straight back
to the operational store.

### Measured Savings
![Measured Savings](../analytics/media/report_measured_savings.png)
The **measured** (not estimated) before/after per optimization. Pick a scenario in the slicer:
**model-selection** shows the real counterfactual (baseline vs actual cost, saving $ and %); the
behavior-changing scenarios read **$0** with a *pending* note until you apply them and measure over
an experiment window.

### Business Impact
![Business Impact](../analytics/media/report_business_impact.png)
The conversation **conversion funnel** (engaged → searched → planned → confirmed) with the
**conversion rate** and the **biggest leak**, plus a breakdown of *why* sessions don't convert.
Empty until the reverse-ETL notebook runs — then it lights up.

### Memory Intelligence
![Memory Intelligence](../analytics/media/report_memory_intelligence.png)
The agent's long-term memory health: **Total** vs **Scored** memories, **Avg Salience**, and
**Supersession Rate**, plus salience distribution, memory-type mix, and health. *Unscored* memories
(procedural rules, which carry no salience by design) appear in the type/health views but are
excluded from the salience-strength chart, so they don't masquerade as weak memories.

### How to read the headline metrics

| Metric | What it is | How to read it |
|---|---|---|
| **Cost per Outcome** | Est. cost ÷ confirmed trips | The real efficiency number — a cheap turn that never books isn't efficient. Lower is better, but only while confirmed trips hold steady. |
| **Trivial %** | Share of turns that need no reasoning (greetings, acks, confirmations) | The size of the model-selection prize: those turns pay premium rates for nothing. Higher = bigger opportunity. |
| **Est Cost USD** | List-price estimate of token spend | Directional, not a bill — reasoning-model "reasoning tokens" make projections rough, so trust the *measured* before/after over this. |
| **Conversion Rate %** | Sessions that reach a confirmed trip | The business outcome. The funnel shows *where* the rest drop off; **biggest leak** names the fix (e.g. `city_friction` → SCEN-001). |
| **Avg Salience** | Mean strength of *scored* memories (0–1) | How confident the agent's long-term memory is. Computed over scored memories only — procedural rules are unscored, not weak. |
| **Supersession Rate %** | Share of memories overridden by newer ones | Conflict resolution at work: the agent correcting itself as a user's preferences change. |
| **Saving USD / %** | Measured before/after per optimization | The *measured* payoff (a counterfactual for model-selection). Pending scenarios read $0 until you apply them and measure over an experiment window. |

---

## Tenants used (cheat sheet)

| Tenant | Comes from | Used in |
|---|---|---|
| `marvel` | live chat from the frontend | Console *detect* (Act 2) |
| `funnel_demo` | seeded by `azd up` | Fabric notebook → Business Impact + Measured Saving (Act 5) |
| `DemoLive` | the traffic simulator | Power BI cost/turns + before/after (Acts 4, 7) |

> **Reserved partitions aren't tenants.** In `OptimizationInsights` you'll also see the partition
> keys **`_global_optimizations`** and **`_global_memory`**. These are **not** tenants — a *tenant*
> is a customer with its own users (like `marvel`). They're reserved buckets for **global,
> cross-tenant** rows (the measured-saving and memory-intelligence signals, which aren't scoped to
> any one customer). Readers select by row `type`, so the partition value is just a container, not a
> customer. (Same note lives in the build guide and the reverse-ETL notebook.)

## Tear down / stop costs

**This deployment is provisioned, not serverless.** The three Container Apps, **Cosmos DB**, **Azure
AI Foundry** (OpenAI), and the **Fabric capacity** all bill **continuously** — idle or not. There is
no low-cost "idle" mode, so the only way to actually stop the charges is to **tear it down**.

- **Delete everything (recommended when you're done):** from `02_completed/`, run
  **`azd down --purge`** (add `--force` to skip prompts). This removes the resource group's Azure
  resources — Container Apps, Cosmos, Foundry, and the Fabric capacity — and `--purge` frees
  soft-deleted names (Key Vault / OpenAI) so you can cleanly redeploy later.
- **Delete the Fabric workspace too.** The workspace, mirror, notebook, report, and UDF are **Fabric
  artifacts** created by `Provision-Fabric.ps1` (not by `azd`), so `azd down` leaves them behind. In
  the Fabric portal, open the workspace → **Workspace settings → Remove this workspace**. (They stop
  working once the capacity is gone anyway — this just keeps your tenant tidy.)
- **Only stepping away briefly?** You can **pause the Fabric capacity** (Console Fabric controls ·
  `POST /optimizations/fabric/capacity/suspend` · or the Fabric portal) to stop the Fabric meter and
  freeze analytics refresh. But that's a **small slice** of the total — Container Apps, Cosmos, and
  Foundry keep billing — so it's a minor, temporary saving, **not** a substitute for tearing down.

> **Resetting the *demo* is not a cost action.** To return the agent to baseline behavior after
> applying an optimization, **Revert** the policy (Console/API or the report's *Applied
> Optimizations* page). That flips a policy doc in Cosmos — it has nothing to do with billing, and
> pausing/deleting the Fabric capacity does **not** revert it.

## Quick troubleshooting

- **Power BI shows the wrong/old server** → **Transform data → Manage Parameters**, set `MirrorSQLEndpoint` / `MirrorDatabase`, **Close & Apply → Refresh**; clear cached creds under **Options → Data source settings**.
- **Notebook read error / no rows** → the mirror's SQL endpoint is syncing: open the mirrored database → **SQL analytics endpoint → Refresh**, confirm the capacity isn't paused, wait ~1–2 min, re-run.
- **Console empty** → the API is running and the **Tenant** matches where you drove traffic (case-sensitive `marvel`).
- **Provisioning auth errors** → `az login` and `azd auth login` must be the **same work account** in the subscription's tenant.

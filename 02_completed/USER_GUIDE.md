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
5. **The optimization apply-loop** — instrument → **detect** (Analytics Portal) → **analyze/measure** (Fabric) → **apply** a policy → **re-measure** the real saving.
6. **Closed-loop apply / revert** — click **Apply** on a recommendation card in the **Analytics Portal**; a reversible policy flip lands in Cosmos and the agent honors it on its next turn. *(An optional Power BI **translytical** write-back performs the identical flip via a Fabric User Data Function — see Module 09.)*

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
`analytics` tenant) and prints **`FRONTEND_URI`** when done. **`azd up` takes roughly 20–25 minutes** (Azure provisioning + data seed + container image builds).

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
| **Analytics Portal** | `<FRONTEND_URI>/analytics/` | Served from the *same* container; reaches the deployed API via the `/api` proxy (nothing to configure). Set **Dataset = `marvel`**. |
| **API docs (Swagger)** | `<FRONTEND_URI>/api/docs` | The API itself has **internal** ingress — you reach it through the frontend's `/api` proxy, not directly. |
| **Analytics report** | your **Fabric workspace** → `TravelAssistantAnalyticsReport` | Auto-imported and pointed at your mirror (Section 1). |

The **traffic simulator** (Acts 4/7) writes **straight to Cosmos** (`az login` + your deployment's
`COSMOSDB_ENDPOINT`), so it drives the hosted demo from your machine with **no local servers running**.

### Demo tools (the ⚙ menu) — drive the whole loop from the portal, no setup

The Portal's **⚙** menu (top-right, next to **Refresh**) lets a reviewer run the entire
optimization loop with **no CLI, no Fabric, no local servers** — everything computes in-process
against Cosmos:

| Action | What it does |
|---|---|
| **Generate traffic** | Writes a burst of synthetic turns. **Policy-aware:** a single premium model until you apply model-selection, then capability-tiered (nano/mini/premium) — this is how you *see the optimization take effect*. |
| **Recompute insights** | Rebuilds the `OptimizationInsights` snapshot in-process, so **Business**, **Memory**, and **Governance** light up on **Source → Reverse-ETL (notebook)** without running the Fabric notebook. |
| **Freshen turn times** | Re-stamps captured turns into the last 2 hours so **Turns-by-minute** reads current. Timestamps only — costs/KPIs unchanged. |
| **Reset to baseline** | Clears governance + the insights snapshot **and** normalizes every turn back to the single-premium baseline (the clean "before-optimization" state). Tokens, the funnel, and app data are untouched. |

**Reviewer quick loop (≈1 min, Dataset → `analytics`):**
1. **⚙ → Reset to baseline** — Model Selection shows one model; the model-selection card reads *proposed*.
2. **Optimizations** tab → **Apply** the *model-selection* card.
3. **⚙ → Generate traffic** — the model-usage donut splits into nano / mini / premium.
4. **⚙ → Recompute insights** — Business / Memory / Governance populate; **Governance** shows the measured saving.
5. **Revert** on the card to show it return to baseline.

*(The Acts below show the same loop via the CLI simulator + Fabric notebook — the "real" path. The ⚙ tools are the zero-setup equivalent for exploring the deployed site.)*

### Local (for development)

Run the stack yourself — from `02_completed/`, in separate terminals:

```powershell
# MCP tool server
.\.venv-travel\Scripts\Activate.ps1; cd mcp_server; $env:PYTHONPATH="..\python"; python mcp_http_server.py
# Travel API  (wait for "Agents initialized successfully")
.\.venv-travel\Scripts\Activate.ps1; cd python; uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
# Frontend
cd frontend; npm install; npm start
# Analytics Portal (static app — no venv)
python -m http.server 8060 --directory ..\analytics\dashboard
```

Frontend `:4200` · API docs `:8000/docs` · Analytics Portal `:8060`. Sign in as any of
the seeded demo users (`tony`, `steve`, `bruce`, `peter`, all under tenant **`marvel`**).

---

## 3. Demo script

The arc: **talk to the agent → see the signal → see the analytics → generate traffic →
measure in Fabric → apply an optimization → re-measure the payoff.**

> Everything below works against your **deployed** apps — "the frontend" means `<FRONTEND_URI>` and
> "the Portal" means `<FRONTEND_URI>/analytics/` — or your local servers from Section 2, whichever
> you're running. The report + notebook always live in your **Fabric workspace**.

### Act 1 — Talk to the assistant *(multi-agent · memory · semantic search)*
In the frontend, plan a trip: *"Plan a 3-day trip to Amsterdam for two."* Then ask for
hotels, dining, and an itinerary. Call out:
- the **orchestrator handing off** to specialists (watch the response build across agents);
- **semantic search** — *"find a quiet boutique hotel near cultural sites"* returns by meaning, not filters;
- **memory** — say *"I'm vegetarian and need wheelchair access,"* start a new chat, and see it personalize without you repeating yourself (Profile page shows learned memories).

Every turn is captured operationally in Cosmos under tenant `marvel`.

### Act 2 — See the signal *(Analytics Portal)*
Open the **Analytics Portal** (`<FRONTEND_URI>/analytics/` when deployed, or locally
`python -m http.server 8060 --directory ..\analytics\dashboard` → <http://localhost:8060>), set
**Dataset = `marvel`** and **Source → Live (recompute)**, **Refresh**. Walk the tabs (Overview →
Optimizations): turns & spend, trivial-turn waste, the **single-model** pattern, and the **recommendation
cards** (e.g. *Capability-tiered model selection*). *Thousands of turns become a handful of
decisions.*

### Act 3 — See the analytics baseline *(Analytics Portal)*
In the Portal, open the **Model Selection** tab (Dataset → `analytics`). Show **cost by
complexity tier** and the **turns-by-model** breakdown on the single-model baseline — one
premium model still serving every turn. *(An optional Power BI report over the same mirror
shows the same baseline — see Module 09 — but the Portal is the recommended surface.)*

### Act 4 — Generate live traffic *(the simulator)*
Make the numbers move. From `analytics/scripts/`:

```powershell
.\Run-TrafficSimulator.ps1 -Tenant analytics -Rate 120 -Minutes 10
```

Turns stream into Cosmos; in the Portal (Dataset → `analytics`, **Source → Live (recompute)**,
**Refresh**) the **Overview** and **Model Selection** tabs update live. No optimization applied
yet, so it runs the **single-model baseline**.

*Zero-setup alternative: **⚙ → Generate traffic** in the Portal — same policy-aware burst, no CLI or `az login`.*

### Act 5 — Measure in Fabric *(the reverse-ETL loop)*
Open the **`ConversionFunnelReverseETL`** notebook in your Fabric workspace (`TENANT =
"analytics"`) and run the cells. It computes the **conversion funnel** and the **measured
saving** over the mirror and **reverse-ETLs** them to Cosmos `OptimizationInsights`. Back in
the Portal, switch **Source → Reverse-ETL (notebook)** and **Refresh**: the **Business** and
**Governance** tabs **light up** from the snapshot — you never touched a report. *Cosmos →
Fabric → reverse-ETL → Cosmos → Travel API → Portal.*

*Zero-setup alternative: **⚙ → Recompute insights** — the same snapshot, computed in-process with no Fabric run.*

### Act 6 — Apply an optimization
- **From the Portal (recommended):** on the **Optimizations** tab, click **Apply** on the
  **model-selection** card — a one-click, reversible policy flip. The agent honors
  capability-tiered model selection on its **next turn**; click **Revert** to undo.
- **From Power BI (optional translytical write-back):** if your Fabric tenant has translytical
  task flows enabled, an **Apply Optimization** button in the report calls the Fabric **UDF**,
  which performs the *identical* policy flip. *The analytical report just steered the operational
  system.* The Portal and API perform the same flip, so this path is optional (see Module 09).

### Act 7 — Re-measure the payoff
Re-run the simulator — now **policy-aware**, it serves the **tiered** mix:

```powershell
.\Run-TrafficSimulator.ps1 -Tenant analytics -Rate 120 -Minutes 10
```

Re-run the notebook, then in the Portal's **Governance** tab (**Source → Reverse-ETL
(notebook)**) watch the **measured-saving** table: cost per turn drops and the saving %
climbs — a **measured** before/after, not an estimate. Revert to show it return to baseline.

---

## Reading the portal

The **web Analytics Portal** (`<FRONTEND_URI>/analytics/`, or locally
`python -m http.server 8060 --directory ..\analytics\dashboard`) is the recommended surface for
reading and acting on the optimization loop. It reads the Travel API's `/optimizations/*`
endpoints live; the **Source** toggle picks **Live (recompute)** (straight from raw turns) or
**Reverse-ETL (notebook)** (the `OptimizationInsights` snapshot the Module 09 notebook writes).
Seven tabs, front to back:

### 1. Overview — the portfolio picture
![Overview tab](../analytics/media/portal/portal-01-overview.png)

Top-line **Portfolio KPIs** (turns, estimated cost, trivial-turn share, models used, cache hit,
confirmed trips, and **Cost per Outcome** = cost ÷ confirmed trips — the number to actually
optimize), an **Optimization band** (open optimizations, estimated vs measured saving, active
policies), and a **turn breakdown** (turns-by-model donut + a turns-per-minute timeline). The
"before" at a glance — one premium model serving everything, with a big slice of trivial turns.

### 2. Optimizations — the action hub
![Optimizations tab](../analytics/media/portal/portal-02-optimizations.png)

The analyst-ranked **Discovered optimizations** table (agent · dimension · fix seam→target ·
projected saving · **Apply mode** · autonomy · clears-SLO · **State**), plus a scenario card per
optimization. **Apply mode** tells you *who acts* — **Automatic** (a config policy the app flips,
carrying **Apply / Revert**) vs **Manual** (a prompt/code edit with a **Review change** diff and
**Approve → Deploy → Roll back / Dismiss** governance). This is where you apply model-selection.

### 3. Model Selection — quantify and project the tiering saving
![Model Selection tab](../analytics/media/portal/portal-03-model-selection.png)

The model-distribution donut, a trivial-turn gauge, **cost by complexity tier**, baseline-vs-actual
bars, and a **turns-per-day projection slider** → monthly/annual saving. The measured cards and
bars are *facts*; the slider + line are a *projection* — drag it to your daily volume and only
**Projected Monthly Saving** moves.

### 4. Memory — the prune opportunity
![Memory tab](../analytics/media/portal/portal-04-memory.png)

Memory KPIs (total, scored, average salience, **supersession %**), memories-by-type and
memory-health donuts, and a salience histogram. A high stale share is the evidence behind the
"prune stale memories" card on the Optimizations tab. *Unscored* procedural rules appear in the
type/health views but are excluded from the salience-strength chart, so they don't look like weak
memories.

### 5. Agents — per-agent × dimension health
![Agents tab](../analytics/media/portal/portal-05-agents.png)

The **scorecard matrix** (each agent scored OK / Watch / Opportunity on cost efficiency, model
selection, workflow efficiency), **cost by agent**, and an **agent-path cost concentration** table —
find the agent/path flagged **Opportunity**; that's where tiering and tool-call fixes pay off most.

### 6. Business — from cost to conversion
![Business tab](../analytics/media/portal/portal-06-business.png)

**Conversion rate** and **biggest leak** KPIs, the **conversion funnel** (engaged → searched →
planned → confirmed), and **why sessions don't convert**. Everything else cuts cost; this answers
*are we converting?* Empty until the reverse-ETL notebook runs (Act 5) — then it lights up.

### 7. Governance — prove it's safe, measured, reversible
![Governance tab](../analytics/media/portal/portal-07-governance.png)

Applied **policies**, the **SLO gate**, a **measured-saving** table, baseline-vs-actual bars, and
the **decision audit trail**. A policy only counts if it **clears the SLO**, and the saving shown is
**measured** (before/after), not projected — every governed action is audited and reversible.

> **Optional: the Power BI report.** A `TravelAssistantAnalyticsReport` is auto-imported to your
> Fabric workspace over the same mirror. It's kept as an **optional, secondary** surface (its
> translytical write-back is still WIP), so the Portal above is the recommended one for this
> workshop. If you do open it, use **Transform data → Manage Parameters** to point
> `MirrorSQLEndpoint` / `MirrorDatabase` at your mirror.

### How to read the headline metrics

| Metric | What it is | How to read it |
|---|---|---|
| **Cost per Outcome** | Est. cost ÷ confirmed trips | The real efficiency number — a cheap turn that never books isn't efficient. Lower is better, but only while confirmed trips hold steady. |
| **Trivial %** | Share of turns that need no reasoning (greetings, acks, confirmations) | The size of the model-selection prize: those turns pay premium rates for nothing. Higher = bigger opportunity. |
| **Est Cost USD** | List-price estimate of token spend | Directional, not a bill — reasoning-model "reasoning tokens" make projections rough, so trust the *measured* before/after over this. |
| **Conversion Rate %** | Sessions that reach a confirmed trip | The business outcome. The funnel shows *where* the rest drop off; **biggest leak** names the fix (e.g. `city_friction` identifies the destination-clarification leak). |
| **Avg Salience** | Mean strength of *scored* memories (0–1) | How confident the agent's long-term memory is. Computed over scored memories only — procedural rules are unscored, not weak. |
| **Supersession Rate %** | Share of memories overridden by newer ones | Conflict resolution at work: the agent correcting itself as a user's preferences change. |
| **Saving USD / %** | Measured before/after per optimization | The *measured* payoff (a counterfactual for model-selection; telemetry for memory-retention once applied). Tool-call-dedup is a governed-path row at $0 here — its estimate is on Discovered Opportunities. |

---

## Tenants used (cheat sheet)

| Tenant | Comes from | Used in |
|---|---|---|
| `marvel` | live chat from the frontend | Portal *detect* (Act 2) |
| `analytics` | seeded by `azd up`, plus the traffic simulator | Fabric notebook → Portal **Business** + **Governance** tabs (Act 5); Portal Overview/Model-Selection before/after (Acts 4, 7) |

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
- **Only stepping away briefly?** You can **pause the Fabric capacity** (`POST
  /optimizations/fabric/capacity/suspend` · or the Fabric portal) to stop the Fabric meter and
  freeze analytics refresh. But that's a **small slice** of the total — Container Apps, Cosmos, and
  Foundry keep billing — so it's a minor, temporary saving, **not** a substitute for tearing down.

> **Resetting the *demo* is not a cost action.** To return the agent to baseline behavior after
> applying an optimization, **Revert** the policy (the Portal's **Optimizations** tab, the API, or
> the optional Power BI translytical button). That flips a policy doc in Cosmos — it has nothing to
> do with billing, and pausing/deleting the Fabric capacity does **not** revert it.

## Quick troubleshooting

- **Power BI (optional report) shows the wrong/old server** → **Transform data → Manage Parameters**, set `MirrorSQLEndpoint` / `MirrorDatabase`, **Close & Apply → Refresh**; clear cached creds under **Options → Data source settings**.
- **Notebook read error / no rows** → the mirror's SQL endpoint is syncing: open the mirrored database → **SQL analytics endpoint → Refresh**, confirm the capacity isn't paused, wait ~1–2 min, re-run.
- **Portal empty** → confirm the API is running and the **Dataset** matches where you drove traffic (case-sensitive `marvel`), with **Source → Live (recompute)**.
- **Provisioning auth errors** → `az login` and `azd auth login` must be the **same work account** in the subscription's tenant.


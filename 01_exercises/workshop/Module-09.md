# Module 09 - Fabric Analytics & Reverse-ETL

**[< Agent Optimization](./Module-08.md)** - **[Lessons Learned & The Future >](./Module-10.md)**

## Introduction

In Modules 07–08 you instrumented the agent, surfaced recommendations, and applied a reversible optimization — all on **Azure Cosmos DB**, the app's **operational** store. Cosmos is the right home for the live agent: single-digit-millisecond reads/writes on the request path, global distribution, schema-flexible documents.

But the *heavy* analytics — a **conversion funnel** across every session, trends over time, cross-tenant rollups — is a different workload. You should **not** run large aggregations on the transactional path: it doesn't scale, it burns request-unit budget, and a runaway analytical query shouldn't be able to slow the agent that's serving customers.

The answer is **two planes, one zero-ETL bridge**:

```
Cosmos (operational) ──mirror──▶ Fabric (analytical) ──reverse-ETL──▶ Cosmos (OptimizationInsights) ──▶ app acts / Power BI
```

- **Microsoft Fabric Mirroring** streams your Cosmos containers into Fabric's OneLake **with no pipeline to build** and near-real-time freshness — and analytics read the *mirror*, never the transactional account.
- **Reverse-ETL** writes the *computed* result back into Cosmos, small and flat, so the operational app (and, at higher maturity, the agent itself) can act on it in real time.

That closed loop is the substrate for the vision's **Level 4 (autonomous)** and **Level 5 (adaptive)** systems: Fabric computes the intelligence; reverse-ETL lands it where the running system can use it.

> **Why this module exists.** This is the pattern that makes agent analytics a *product*, not a demo — and it's why Cosmos + Fabric is such a strong pairing for AI applications: Cosmos for the operational agent, Fabric for the analytical brain, Mirroring + reverse-ETL to connect them.

## Learning Objectives and Activities

By the end you will be able to:

- Explain the **operational vs analytical plane** split and why analytics doesn't belong on the transactional path.
- Describe **Mirroring** (zero-ETL Cosmos → Fabric) and **reverse-ETL** (insights back to Cosmos).
- Compute a **conversion funnel** over the mirror in a Fabric Spark notebook.
- Implement the **reverse-ETL write** that closes the loop.
- **Act on analytics from the report** — flip an optimization policy in Cosmos from a Power BI **translytical** button (a Fabric User Data Function).
- Connect the pattern to **L4/L5 autonomy**.

## Module Exercises

1. [Activity 1: The Two Planes and the Mirror](#activity-1-the-two-planes-and-the-mirror)
2. [Activity 2: Provision the Workspace and Mirror, then Open the Notebook](#activity-2-provision-the-workspace-and-mirror-then-open-the-notebook)
3. [Activity 3: Build the Decision (`cause` classification)](#activity-3-build-the-decision-cause-classification)
4. [Activity 4: Reverse-ETL the Insights Back to Cosmos](#activity-4-reverse-etl-the-insights-back-to-cosmos)
5. [Activity 5: Watch Power BI Light Up](#activity-5-watch-power-bi-light-up)
6. [Activity 6 (bonus): Apply an Optimization from the Report (translytical)](#activity-6-bonus-apply-an-optimization-from-the-report-translytical)

---

## Activity 1: The Two Planes and the Mirror

A **mirrored database** is a zero-ETL, near-real-time copy of your Cosmos analytics containers inside Fabric's OneLake. Analytics read *that* copy — never the transactional account. In the next activity you will create it; for now, understand what it is and why it exists.

> **What `azd up` actually provisioned.** For the analytics path, `azd` created **only the Fabric F2 _capacity_** (compute) and the Cosmos containers. It did **not** create the Fabric workspace, the mirrored database, or the notebook — you stand those up in **Activity 2**.

Once created, the mirror will carry these Cosmos containers as tables: `OptimizationTurns`, `Trips`, `OptimizationPolicies`, `Configuration`, `Messages`, and the reverse-ETL target `OptimizationInsights`. This module reads `OptimizationTurns`, `Trips`, and `Messages`, uses `Configuration` for pricing, and writes results back to `OptimizationInsights`.

Two things to internalize:

- **The analytical plane reads the mirror, not Cosmos.** The Spark notebook queries the mirror's **SQL analytics endpoint** — the transactional account isn't touched by analytics.
- **Reverse-ETL is a deliberate, small write back.** You compute a lot in Fabric, then write a **handful of flat rows** back to Cosmos so the app can act cheaply.

## Activity 2: Provision the Workspace and Mirror, then Open the Notebook

You will create the Fabric workspace, the Cosmos mirror, and upload this module's notebook using a single PowerShell script. It reads your deployment settings from your `azd` environment automatically, so you only supply a workspace name and — for one unavoidable portal step — a connection id.

> **Prerequisites:** you have run `azd up` for this workshop, and you are signed in with `az login` (and `azd auth login`) as a user with permission to create Fabric workspaces. Microsoft Fabric must be enabled for your tenant.

### Step 1 — Run the provisioning script (Phase 1)

Open a **new PowerShell terminal** at the repository root and run:

```powershell
cd analytics\fabric
.\Provision-Fabric.ps1
```

The script auto-detects the workshop folder you deployed (e.g. `02_completed` or `01_exercises`) and its virtual environment. When prompted, accept the default workspace name (**`Multi-Agent Travel Workshop`**) or enter your own. It then runs **Phase 1**: it creates the workspace, assigns it to your F2 capacity, provisions the workspace identity, and grants the required Cosmos RBAC — then pauses.

> Uploading the **completed** notebook (for the `02_completed` demo) instead of the learner version? Run `.\Provision-Fabric.ps1 -Solution`.

### Step 2 — Create the Cosmos connection in the Fabric portal (manual, one time)

Creating the Cosmos **connection** is the one step Fabric does not let us automate today, so the script pauses and walks you through it. You are **only creating a connection object** here — the script creates the mirrored database itself, using the connection id you provide. In [https://app.fabric.microsoft.com](https://app.fabric.microsoft.com):

1. Click **Settings** (gear, top-right) → **Manage connections and gateways**. *(This is a **tenant-level** setting, not your workspace settings.)*
2. On the **Connections** tab, click **+ New**.
3. Set **Connection type** to **Azure Cosmos DB for NoSQL**, and use the Cosmos **endpoint** the script printed as the account URL.
4. Set the **Authentication method** to **OAuth 2.0** (Organizational account), sign in, then click **Create**.
5. Open the new connection → **Settings** and **copy its Connection ID** (a GUID). *Do not start the "New mirrored database" wizard — the script creates the mirror for you.*

> **Paste tip:** in the VS Code terminal, paste with **Ctrl+Shift+V** (`Ctrl+V` shows a literal `^V`). Alternatively, press Enter to exit and re-run non-interactively: `.\Provision-Fabric.ps1 -ConnectionId <id>`.

### Step 3 — Paste the connection id (Phase 2)

Back in the PowerShell terminal, **paste the connection id** at the prompt and press Enter. The script runs **Phase 2**: it creates the mirrored database, starts replication, and uploads the **`ConversionFunnelReverseETL`** notebook with its parameters pre-filled from your deployment (Cosmos endpoint/database + the mirror's SQL endpoint). It saves `FABRIC_WORKSPACE_ID` and `FABRIC_MIRROR_ID` to your `azd` environment.

### Step 4 — Verify in the Fabric portal

Refresh your workspace. Confirm you see both:

- a **mirrored database** whose tables show a *Replicating* / *Running* status,
- the **`ConversionFunnelReverseETL`** notebook, and
- the **`optimization-apply-loop`** User Data Function — the translytical Apply/Revert you use in Activity 6 (the provisioning deployed it with the `azure-cosmos` library and your Cosmos endpoint already configured).

Your `azd up` deployment already **seeded a demo tenant, `funnel_demo`**, into your Cosmos `OptimizationTurns` / `Messages` / `Trips` containers (~120 sessions with a realistic mix of converted and abandoned outcomes). The mirror replicates it within a minute — so there is **nothing extra for you to run**; the notebook has data waiting.

### Step 5 — Open the notebook and read the mirror

Open the **`ConversionFunnelReverseETL`** notebook, confirm the pre-filled parameters look right, and set `TENANT = "funnel_demo"`.

> **Run only the Parameters cell, then Section 1 (Read the mirror) and Section 2 (Build the funnel) — then stop.** Sections **3** and **5** contain the `TODO` exercises you complete later in **Activity 3** and **Activity 4**; don't run them yet.

The read cell (Section 1) pulls the mirrored tables via the SQL endpoint; the funnel cell (Section 2, provided) aggregates turns into per-session stages — **engaged → searched → planned → confirmed** — and attaches a friction signal from the assistant `Messages`:

- `searched` — the session delegated to a place search (`handoff_count > 0` / `agent_path` hit `find_places`).
- `planned` — a turn reached the itinerary step.
- `confirmed` — the session (or its user) has a booked `Trip`.
- `city_reask` / `no_results` — friction flags mined from the assistant messages.

> **Troubleshooting — `Error occurred while attempting to read a deletion vector`.** If the read cell throws this, it's a Fabric **SQL analytics endpoint metadata-sync lag**, not a data problem. Open your **mirrored database → SQL analytics endpoint** in the portal and click **Refresh** (metadata sync), confirm the F2 capacity isn't paused, wait ~1–2 minutes, then re-run the cell. If it persists, **Stop** and then **Start** replication on the mirrored database to force a clean re-snapshot, and re-run.

*This is the analysis you would never run on Cosmos directly — it groups and joins across every session.*

## Activity 3: Build the Decision (`cause` classification)

In the notebook you opened in Activity 2, scroll to the section headed **`## 3. TODO 1 — classify the abandonment cause`**. The code cell just below it contains a `# ---- TODO 1 ----` placeholder — this is the analytics decision (the notebook analog of `classify_turn_tier`). **Replace that placeholder** with the classification below. For every **non-converting** session it adds a `cause` column that explains *why* it leaked, in this order:

| Condition | `cause` |
|---|---|
| `planned == 1` | `cart_abandon` — got a plan, never booked |
| `searched` and `city_reask` | `city_friction` — the agent kept re-asking the city (→ SCEN-001) |
| `searched` and `no_results` | `no_results` — the search dead-ended |
| `searched` | `search_stall` |
| otherwise | `no_engagement` — never searched |

```python
sess = sess.withColumn(
    "cause",
    F.when(F.col("confirmed") == 1, F.lit("converted"))
     .when(F.col("planned") == 1, F.lit("cart_abandon"))
     .when((F.col("searched") == 1) & (F.col("city_reask") == 1), F.lit("city_friction"))
     .when((F.col("searched") == 1) & (F.col("no_results") == 1), F.lit("no_results"))
     .when(F.col("searched") == 1, F.lit("search_stall"))
     .otherwise(F.lit("no_engagement")))
```

The next cell (provided) shapes the results into **flat** `OptimizationInsights` rows — `funnel_stage`, `abandonment_cause`, and a `conversion_kpi` row that even names the **biggest addressable leak**. Flat rows mean the report needs *no* session math. The **Section 4b** cell (also provided) then computes the **measured saving** — a counterfactual over the mirrored `OptimizationTurns` + `Configuration` pricing — into an `optimization_result` row (`result_df`).

## Activity 4: Reverse-ETL the Insights Back to Cosmos

First run the provided **Section 4b** cell (measured saving) so `result_df` exists. Then scroll to the section headed **`## 5. TODO 2 — reverse-ETL the insights back to Cosmos`**. Its code cell contains a `# ---- TODO 2 ----` placeholder — this is the pattern this module teaches. **Replace that placeholder** with the write below. It sends the four DataFrames (`funnel_df`, `cause_df`, `kpi_df`, `result_df`) back to the Cosmos **`OptimizationInsights`** container using the Spark Cosmos connector (the `cosmos_write` options are already defined in the cell above; Fabric authenticates to Cosmos with your Entra token):

```python
for df in (funnel_df, cause_df, kpi_df, result_df):
    df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
```

That's reverse-ETL: Fabric-computed intelligence, landed back in the operational store. The insight now lives where the app can read it — and where the **mirror** will carry it *back* to Fabric for Power BI.

> **The L4/L5 connection.** At Level 2 you *read* this insight. At **Level 4/5**, the system reads it and **acts** — e.g. the agent sees "biggest leak = city_friction" and auto-stages the SCEN-001 prompt fix. Reverse-ETL is the mechanism that makes self-optimizing agents possible: without a path back to the operational store, analytical intelligence just sits in a dashboard.

## Activity 5: Watch Power BI Light Up

Open the provided **`analytics/TravelAssistantAnalyticsReport.pbit`** in Power BI Desktop (the same report you connected in Module 07) and go to its **Business Impact** page. Before you ran the notebook it was empty; after your reverse-ETL write (and a mirror refresh), it **lights up** — the conversion funnel, the conversion-rate KPI, the biggest-leak callout, and the "why sessions don't convert" bar. The **Measured Saving** page lights up too, from the scenario-keyed `optimization_result` row (`model-selection`). **You didn't touch the report** — the insight flowed Cosmos → Fabric → reverse-ETL → Cosmos → mirror → Power BI.

> **Connecting the report (same as Module 07):** when prompted, enter **your own** mirror's **SQL analytics endpoint** and **database name** (`TravelAssistantAnalytics`) — these are parameters, so they point the report at *your* mirror. At the credentials prompt use the **Microsoft account / Organizational account** tab and **Sign in** (not Windows); click **OK/Continue** on the "multiple data sources" privacy prompt. If it shows stale data or the wrong server, fix it via **Home → Transform data → Manage Parameters**, and clear any cached endpoint under **File → Options and settings → Data source settings**.

*Stuck? Compare against `analytics/fabric/ConversionFunnelReverseETL_solution.ipynb`.*

## Activity 6 (bonus): Apply an Optimization from the Report (translytical)

So far the report *reads* analytics. A **translytical task flow** lets it *act*: a button in Power BI calls a Fabric **User Data Function**, which writes back to Cosmos — the same operational store the agent reads per turn. The provisioning already deployed the `optimization-apply-loop` UDF (Activity 2, Step 4), so there is nothing to author; you just bind two buttons.

> **Optional, and gated by a Fabric tenant admin.** Translytical task flows are a **preview feature** — an admin must enable *Admin portal → Tenant settings → "Users can create and consume translytical task flows"* (search *translytical* / *task flow* / *data function*). **If it's off, the button's Workspace / Function set / Function dropdowns never appear — with no error.** If you can't enable it, skip this activity: you can apply/revert the identical `model-selection` policy without Power BI via the app's optimization API (`POST /optimizations/model-selection/apply` · `/revert`), which the Optimization Console in the completed solution wraps with one-click buttons.

> **Do this in the Power BI *Service* (edit in the browser), not Desktop.** In the current rollout the data-function button config UI appears reliably only in the Service, and the button only fires there anyway. So publish the finished report first, then add the buttons in the browser.

1. In the Power BI **Service**, open the published report → **Edit**.
2. On the report's **Applied Optimizations** page, add an **Apply** button: **Insert → Button**, then **Format → Action → Type = Data function** and fill all three dropdowns — your **workspace** → **function set** `optimization-apply-loop` → **data function** `apply_optimization`. There is no static-value option: create a measure `Apply Scenario = "model-selection"` and bind the `scenario` parameter to it via the **`fx`** button (leave `by` unmapped). (Full steps: `analytics/PowerBI_Optimization_Build_Guide.md`, Page 4.)
3. Duplicate it for **Revert** → the **`revert_optimization`** function.
4. Click **Apply**. The UDF flips the `OptimizationPolicies` doc in Cosmos to `status=active`; the running agent honors capability-tiered model selection on its **next turn**. Click **Revert** to roll back — a safe, reversible policy flip, never a code change.

That's the whole thesis in one gesture: **Power BI → Fabric UDF → Cosmos → the agent**. The analytical plane doesn't just observe the operational plane — it *steers* it.

> **How it authenticates:** the UDF uses Fabric's managed Cosmos connection; the deploying user was granted **Cosmos DB Built-in Data Contributor** by the provisioning, so the writeback just works. Details: `analytics/fabric/udf/README.md`.


## Test Your Work

- [ ] The read cell prints non-zero counts for `turns`, `trips`, `messages` from the **mirror**.
- [ ] Your `cause` classification runs and the cause breakdown looks sane (biggest bucket ≈ `city_friction` on `funnel_demo`).
- [ ] Your reverse-ETL write completes: `OptimizationInsights` has `funnel_stage` / `abandonment_cause` / `conversion_kpi` rows for the tenant, plus a scenario-keyed `optimization_result` row for `model-selection` (under `tenantId="_optimizations"`).
- [ ] The Power BI **Business Impact** page populates without any report edits.
- [ ] (bonus) Clicking **Apply** in the report flips the `model-selection` policy to `active` in Cosmos (confirm on the Applied Optimizations page or in Cosmos Data Explorer), and **Revert** rolls it back.
- [ ] You can explain, in your own words, why analytics runs in Fabric (not on Cosmos) and why reverse-ETL is what enables an agent to optimize *itself*.

**[< Agent Optimization](./Module-08.md)** - **[Lessons Learned & The Future >](./Module-10.md)**

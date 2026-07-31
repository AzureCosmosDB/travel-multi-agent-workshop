# Power BI Report Build Guide — Agent Optimization Analytics

> **You usually don't need this guide.** The finished report (`analytics/TravelAssistantAnalyticsReport.pbix`) is **auto-deployed to your Fabric workspace** by `Provision-Fabric.ps1` (Phase 3), already pointed at your mirror — attendees never open Power BI Desktop. This guide is for **maintainers** who want to **rebuild or customize** that report.

Build the **Agent Optimization** report in Power BI Desktop against your **Fabric mirrored database** of the Travel Assistant analytics. It produces the committed **`.pbix`** the provisioning imports (the script overrides its `MirrorSQLEndpoint` / `MirrorDatabase` parameters per deployment).

Use **DirectQuery over the mirrored database SQL endpoint**. Build the report from DAX measures over the raw mirrored tables — a re-pointable, parameterized `.pbix`, with no separate semantic model to create.

---

## Prerequisites

- **Power BI Desktop** installed (latest version).
- A **Fabric mirrored database** of your Cosmos analytics is running and replicating (see `analytics/fabric/README.md`). It mirrors at least `OptimizationTurns`, `Trips`, `Configuration`, and `OptimizationInsights`.
- Your mirror's **SQL analytics endpoint** and **database name**.

To find the SQL analytics endpoint:
1. Open your **Mirrored database** in the Fabric portal.
2. Click the **SQL analytics endpoint** dropdown (top-left, next to the mirror name).
3. Copy the connection string (e.g., `xxxxx.datawarehouse.fabric.microsoft.com`).
4. Note the **database name** — it is the mirror artifact name (e.g., `TravelAssistantAnalytics`), and the **schema** is your Cosmos database name (e.g., `TravelAssistant`).

---

## Step 1: Connect to the Mirror (DirectQuery)

1. Open **Power BI Desktop**.
2. **Get Data** → **SQL Server database**.
3. **Server:** your mirror SQL analytics endpoint URL.
4. **Database:** the mirror name (e.g., `TravelAssistantAnalytics`).
5. **Data Connectivity mode:** **DirectQuery**.
6. **OK**, then in the credentials dialog select the **Microsoft account** tab on the left (a.k.a. organizational account) → **Sign in** → **Connect**.
   > Do not use the Windows tab. If you see **`Microsoft SQL: Integrated Security not supported.`**, clear permissions via **File → Options and settings → Data source settings → Clear Permissions**, then reconnect with **Microsoft account**.
   >
   > Alternative: **Get Data → Microsoft Fabric → OneLake data hub**, then pick your **SQL analytics endpoint**.
7. In the Navigator, expand the schema (your Cosmos DB name, e.g., `TravelAssistant`) and select:

| Table | Used for |
|-------|----------|
| `OptimizationTurns` | every KPI, cost-by-tier, model usage, trivial % |
| `Trips` | confirmed outcomes, cost per outcome |
| `OptimizationPolicies` | applied-optimizations audit (Page 4) |
| `Configuration` | model pricing (`type = "model_pricing"`) used by `Est Cost USD` |
| `OptimizationInsights` | reverse-ETL output (funnel, causes, KPIs) — powers the **Business Impact** page |

8. Click **Load** (not Transform Data).

### Step 1b: Parameterize the connection (REQUIRED — makes the `.pbit` re-pointable)

Step 1 hard-codes your SQL endpoint into every query. If you export the `.pbit` like that, **every attendee who opens it silently queries *your* mirror** (this template previously shipped with that exact bug). Convert the source to parameters so each attendee points it at their own mirror:

1. **Home → Transform data** to open Power Query.
2. **Manage Parameters → New Parameter**, twice:
   - `MirrorSQLEndpoint` — Type **Text**, **Required**.
   - `MirrorDatabase` — Type **Text**, **Required**.
3. For **every** table, open the **Advanced Editor** and change the source line to use the parameters:

   ```
   Source = Sql.Database(MirrorSQLEndpoint, MirrorDatabase),
   ```

   (replacing the literal `Sql.Database("<your-endpoint>", "<your-db>")`).
4. **Close & Apply.**

> **Caution — verify before every export.** Power BI Desktop silently re-bakes the literal server back into the M query when you re-save, **and** caches pending edits (with their literal servers) in an `UnappliedChanges` part inside the `.pbit`. Before exporting (**File → Export → Power BI template**): (1) **Home → Close & Apply** so there are **no** unapplied changes, (2) re-open each table's **Advanced Editor** and confirm it reads `Sql.Database(MirrorSQLEndpoint, MirrorDatabase)`, and (3) as a final check, unzip the `.pbit` and grep **every** part — not just `DataModelSchema`, also `UnappliedChanges` — for `datawarehouse.fabric.microsoft.com`; there must be **zero** matches.

---

## Step 2: Parameterize the Connection (makes the .pbit portable)

1. **Home** → **Transform data** (Power Query Editor).
2. **Home** → **Manage Parameters** → **New Parameter**:
   - **Name:** `MirrorSQLEndpoint` · **Type:** Text · **Current Value:** your SQL endpoint URL.
3. **New Parameter** again:
   - **Name:** `MirrorDatabase` · **Type:** Text · **Current Value:** your mirror name (e.g., `TravelAssistantAnalytics`).
4. For each table, right-click → **Advanced Editor**, and replace the hard-coded server/database in the `Sql.Database(...)` step with the parameters:
   ```m
   Source = Sql.Database(MirrorSQLEndpoint, MirrorDatabase)
   ```
5. **Close & Apply**.

> When someone opens the `.pbit`, Power BI prompts for `MirrorSQLEndpoint` + `MirrorDatabase`.

---

## Step 3: Create the Measures (the analytics)

Add these measures to the **`TravelAssistant OptimizationTurns`** table (right-click → **New measure**). Use the schema-prefixed table names shown below.

**Pricing comes from the mirrored `Configuration` table** — no CSV to load. `Configuration` is one of the mirrored tables (alongside `OptimizationTurns`, `Trips`, `OptimizationPolicies`), so it's already in the model as **`TravelAssistant Configuration`**. Its `type = "model_pricing"` rows carry `model`, `input_price`, and `output_price` — the same numbers the app and the notebook use. `Est Cost USD` looks prices up from it, so changing a price is done once (at deploy time, from `python/data/model_pricing.json`) and flows everywhere. Models are discovered from the data; any model without a pricing row falls back to the default in the measure.

```DAX
Total Turns   = COUNTROWS('TravelAssistant OptimizationTurns')
Total Tokens  = SUM('TravelAssistant OptimizationTurns'[total_tokens])

Trivial Turns = CALCULATE(COUNTROWS('TravelAssistant OptimizationTurns'), 'TravelAssistant OptimizationTurns'[model_tier] = "trivial")
Trivial %     = DIVIDE([Trivial Turns], [Total Turns]) * 100

Est Cost USD =
SUMX(
    'TravelAssistant OptimizationTurns',
    VAR d    = 'TravelAssistant OptimizationTurns'[model_deployment]
    VAR pin  = COALESCE(LOOKUPVALUE('TravelAssistant Configuration'[input_price],  'TravelAssistant Configuration'[type], "model_pricing", 'TravelAssistant Configuration'[model], d), 1.25)
    VAR pout = COALESCE(LOOKUPVALUE('TravelAssistant Configuration'[output_price], 'TravelAssistant Configuration'[type], "model_pricing", 'TravelAssistant Configuration'[model], d), 10.0)
    RETURN ('TravelAssistant OptimizationTurns'[input_tokens] * pin + 'TravelAssistant OptimizationTurns'[output_tokens] * pout) / 1000000
)

Confirmed Trips  = CALCULATE(COUNTROWS('TravelAssistant Trips'), 'TravelAssistant Trips'[status] = "confirmed" || 'TravelAssistant Trips'[status] = "completed")
Cost per Outcome = DIVIDE([Est Cost USD], [Confirmed Trips])

Cached Tokens = SUM('TravelAssistant OptimizationTurns'[cached_tokens])
Cache Hit %   = DIVIDE([Cached Tokens], SUM('TravelAssistant OptimizationTurns'[input_tokens])) * 100

Active Policies      = CALCULATE(COUNTROWS('TravelAssistant OptimizationPolicies'), 'TravelAssistant OptimizationPolicies'[status] = "active")
Latest Policy Change = DATE(1970,1,1) + MAX('TravelAssistant OptimizationPolicies'[updated_epoch]) / 86400.0
```

> **Token pricing** is a list-price estimate stored in the mirrored `Configuration` table; to change it, edit `python/data/model_pricing.json` and re-run the deploy — no DAX edits.
> Set **`Latest Policy Change`** Format = **Date time**.

### Calculated columns

Create these with **New column** (right-click the table → **New column**) — *not* New measure. Set each one's **Data type / Format = Date/time**.

```DAX
-- Table: 'TravelAssistant OptimizationTurns'
TurnTime   = DATE(1970,1,1) + 'TravelAssistant OptimizationTurns'[turn_epoch] / 86400.0
TurnMinute = DATE(1970,1,1) + ROUNDDOWN('TravelAssistant OptimizationTurns'[turn_epoch] / 60, 0) / 1440

-- Table: 'TravelAssistant OptimizationPolicies'
PolicyUpdated = DATE(1970,1,1) + 'TravelAssistant OptimizationPolicies'[updated_epoch] / 86400.0
```

Use `TurnMinute` on time axes (set **X-axis Type = Continuous**, plain field) and `TurnTime` for detail.

---

## Step 4: Set Up the Theme

Use a dark dashboard theme. Set the canvas background to a dark color if desired.

---

## Step 5: Tenant filter & the before/after demo

Turns are keyed by `tenantId`, and the seed includes more than one tenant. Add a **tenant slicer** and a default filter so pages read cleanly:

- **Report-level filter (do this first):** in the Filters pane → **Filters on all pages**, drag `'TravelAssistant OptimizationTurns'[tenantId]` and set it to **`analytics_demo`**. That drops seeding/test tenants (e.g. `marvel`) so the KPIs reflect the intended demo dataset.
- **Tenant slicer:** add a **Slicer** visual on `tenantId` so you can switch tenants live.

**Before/after A/B (recommended for a session):** the repo ships a paired dataset in two tenants — **`before_demo`** (every turn on the single premium model, `model_tier = "default"`) and **`after_demo`** (the *identical* workload, tiered to nano/mini/gpt-5.1). Because only the model routing differs, flipping the tenant slicer between them is a true apples-to-apples before/after — `[Est Cost USD]` drops and `[Trivial %]` goes from 0 to the real share. Build it with:

```powershell
python analytics/ab_demo_seed.py            # writes before_demo + after_demo (240 paired turns)
```

> These land in `OptimizationTurns`/`Trips`, which already mirror to Fabric — no mirror change, just **Refresh** the report.

---

## Page 1: Optimization Overview

Answers: **What are our agents doing, and what does it cost?**

- **KPI Cards** (top row): `[Total Turns]`, `[Est Cost USD]`, `[Trivial %]`, `[Cost per Outcome]`, `[Confirmed Trips]`.
  > Use a **Card** visual or **Multi-row card**, not the **KPI** visual.
- **Donut / bar — Model usage:** Axis `'TravelAssistant OptimizationTurns'[model_deployment]`, Values `[Total Turns]`.
- **Line — Turns over time:** Axis `TurnMinute` (Step 3), Values `[Total Turns]`. Set the X-axis **Type = Continuous** (Format visual → X axis).
  > Use the plain `TurnMinute` field, not the auto **Date Hierarchy**. Use `TurnTime` for finer detail.
  > - **Filtering the time axis:** for a live demo, use a relative UTC filter such as the last hour. For the shipped `.pbit` with static seed data, use a fixed filter (`is on or after <date>`) or none.

## Page 2: Cost by Tier

Answers: **Where does spend go once tiering is applied?**

- **Clustered bar — Est cost by tier:** Axis `'TravelAssistant OptimizationTurns'[model_tier]`, Values `[Est Cost USD]`.
- **Matrix:** Rows `model_tier`, `model_deployment`; Values `[Total Turns]`, `[Total Tokens]`, `[Est Cost USD]`.
- **Card:** `[Cost per Outcome]` — the north-star.
- **Cache effectiveness (a second cost lever):**
  - **Card / Gauge — `[Cache Hit %]`** (~76% observed).
  - **Clustered bar — cache hit % by tier:** Axis `'TravelAssistant OptimizationTurns'[model_tier]`, Values `[Cache Hit %]`.

## Page 3: The Optimization Opportunity

Answers: **Which turns are wasteful, and what's the recommended fix?**

- **Gauge / KPI — Trivial %** (~20–25% in the sample data; set the gauge target to taste).
- **Stacked column — turns by tier over time:** Axis `TurnMinute` (Step 3), Legend `model_tier`, Values `[Total Turns]`.
- **Text box** describing the SCEN-007 model-selection recommendation. Suggested copy:
  > **The Optimization Opportunity — Model Selection (SCEN-007)**
  > A meaningful share of agent turns are *trivial* — greetings, acknowledgements, and short confirmations that need no reasoning (~a quarter of turns in the sample data; it varies with your traffic). Today every turn runs on the same premium model, so we pay the same for "thanks!" as for "plan my 5-day trip to Tokyo."
  > **Recommendation:** route trivial turns to a cheaper model (`gpt-5-nano`) and reserve the larger model for complex requests. Trivial turns cost ~25× less on `gpt-5-nano` than the default `gpt-5.1` (input $0.05 vs $1.25; output $0.40 vs $10.00 per 1M tokens) — no quality loss on turns that were never reasoning. **Impact:** lower Cost per Outcome while confirmed trips stay flat.

## Page 4: Applied Optimizations (governance / audit)

Answers: **What optimizations have we proposed or applied, and what's their state?**

Use the **`OptimizationPolicies`** table (schema-prefixed: `'TravelAssistant OptimizationPolicies'`).

- **Table (main visual):** columns `scenario_id`, `title`, `status`, `apply_mode`, `version`, `proposed_by`, `PolicyUpdated`. Each row is a policy the optimization loop proposed/applied/reverted (e.g., SCEN-007 *Capability-tiered model selection*, SCEN-001 *Active-trip city context*).
  > Use the `PolicyUpdated` calculated column (Step 3). Set **Data type = Date/time**. Turn the visual's **Totals row Off** (Format → Totals).
- **Cards:** `[Active Policies]`, `[Latest Policy Change]` (Step 3).
- **Conditional formatting** (optional): color the `status` column — `active` green, `staged`/`proposed` amber, `reverted` grey.

### Apply / Revert from the report (translytical task flow)

Turn this page from *read-only* into *actionable*: bind **Apply** / **Revert** buttons to the Fabric **User Data Function** the provisioning deploys (`optimization-apply-loop`), so a click flips the `OptimizationPolicies` doc in Cosmos and the running agent honors it on its next turn. (The UDF functions **return a string** — a requirement for data-function buttons.)

> **Optional, and gated by a tenant admin.** Translytical task flows are a **preview feature**: a Fabric admin must enable *Admin portal → Tenant settings → "Users can create and consume translytical task flows"* (search *translytical* / *task flow* / *data function*). **If it's off, the Workspace / Function set / Function dropdowns below never appear in the Service — with no error message.** If you can't get it enabled, skip this section: the **Optimization Console** (and the app's `POST /optimizations/{scenario}/apply|revert` API) perform the exact same policy flip without Power BI.

> **Add these buttons in the Power BI *Service* (edit in the browser), not Desktop.** In the current rollout, the data-function button config UI (the Workspace / Function set / Data function dropdowns) reliably appears only in the Service — and the button only *fires* there anyway. So: finish the report in Desktop, **Publish**, then open it in the Service and add the buttons. The steps below are the same either way.

1. **Options → Preview features → enable "Translytical task flows"**, then restart Power BI Desktop.
2. Add a constant measure for the scenario (New measure, any table): `Apply Scenario = "model-selection"`.
3. **Insert → Button** (label it *Apply*). Select it → **Format → Action** (toggle **On**) → **Type = Data function**, then fill **all three** dropdowns: **Workspace** → **Function set** = `optimization-apply-loop` → **Data function** = `apply_optimization`. The parameters appear only after the Data function is chosen.
4. There is **no static-value option** — bind each parameter to a measure or slicer. Click the **`fx`** next to **`scenario`** → select the **`Apply Scenario`** measure. Leave **`by`** unmapped (it defaults to `powerbi`). (For a dynamic version, bind `scenario` to `SELECTEDVALUE('…OptimizationPolicies'[scenario], "model-selection")` driven by a slicer.)
5. Duplicate the button for **Revert** → **Data function** = `revert_optimization`, same `Apply Scenario` measure.

> **Testing:** buttons do **not** fire in Power BI Desktop — they only validate (the button restyles when the parameter is accepted). **Publish to the Power BI Service** to actually click Apply/Revert.

See `analytics/fabric/udf/README.md` for the UDF details. This is the translytical payoff: the analytical report *writes back* to the operational store — Power BI → Fabric UDF → Cosmos — closing the loop inside one surface.

---

## Page 5: Measured saving by optimization (reverse-ETL)

Answers: **What did each optimization actually save?** — a measured number, not an estimate, and you can **switch between optimizations**.

This reads the flat `optimization_result` rows the reverse-ETL writes into `'TravelAssistant OptimizationInsights'` — **one row per optimization**, keyed by `scenario` and stored under the reserved `tenantId = "_optimizations"` partition (so the axis is the *optimization*, never the tenant). `model-selection` carries a real **counterfactual** measurement (every captured turn priced under the model it actually ran on vs. the all-premium baseline); the behavior-changing scenarios show `method = "pending"` until their before/after is measured.

Measures (add to `'TravelAssistant OptimizationInsights'`):

```DAX
Saving USD        = CALCULATE(MAX('TravelAssistant OptimizationInsights'[saving_usd]),        'TravelAssistant OptimizationInsights'[type] = "optimization_result")
Saving %          = CALCULATE(MAX('TravelAssistant OptimizationInsights'[saving_pct]),        'TravelAssistant OptimizationInsights'[type] = "optimization_result")
Baseline Cost USD = CALCULATE(MAX('TravelAssistant OptimizationInsights'[baseline_cost_usd]), 'TravelAssistant OptimizationInsights'[type] = "optimization_result")
Actual Cost USD   = CALCULATE(MAX('TravelAssistant OptimizationInsights'[actual_cost_usd]),   'TravelAssistant OptimizationInsights'[type] = "optimization_result")
```

Visuals (each with a visual-level filter `type = "optimization_result"`):
- **Scenario slicer:** add a **Slicer** (or button slicer) on `'…OptimizationInsights'[scenario]`, single-select — this is how you **switch between optimizations**. **Add a visual-level filter `type = "optimization_result"` to the slicer itself** (lock/hide it), otherwise it also lists `scenario` values from `recommendation_card` rows (6 scenarios) and a blank `--` from the row types that have no scenario. With the filter it shows only the measured optimizations. (`title` is a nicer label but may not appear until the mirror syncs it; `scenario` is always present.)
- **Cards:** `[Saving USD]` and `[Saving %]` — the headline "we saved $X (Y%)" for the selected optimization (`method="pending"` scenarios read $0 until measured).
- **Clustered column — baseline vs actual:** leave the **X-axis empty** and put **both** `[Baseline Cost USD]` and `[Actual Cost USD]` on the **Y-axis** — you get two columns whose gap *is* the saving. (Simpler alternative: three **Cards** — `[Baseline Cost USD]`, `[Actual Cost USD]`, `[Saving USD]`.)

> **Filtering note:** because these rows live under `tenantId = "_optimizations"`, keep this page **off** the tenant slicer used on other pages (or add a page-level filter `tenantId = "_optimizations"`).

> **Talking point:** the recommendation cards *estimate* a saving; this page shows the **measured** one, per optimization — so apply → re-measure closes the loop with a real number.

---

## Page 6: Business Impact — the conversion funnel (reverse-ETL)

Answers: **Are we converting sessions into booked trips — and if not, why?**

This page reads **pre-computed** rows from `'TravelAssistant OptimizationInsights'` — the output of the **reverse-ETL notebook** (Module 09). The heavy session-level analysis runs in Fabric; the report just displays flat rows, so there is **no session math in DAX**. The page is **empty until the notebook runs**, then it *lights up* — that's the Cosmos → Fabric → reverse-ETL loop made visible.

> `OptimizationInsights` holds several row `type`s; **every visual on this page needs a visual-level filter on `type`.** These filters are **structural** (they carve the right row-type out of the shared table), so in the Filters pane **lock** each one (padlock) — and ideally **hide** it (eye) — so a report consumer can't change/remove it and mix row types.

Measures (add to `'TravelAssistant OptimizationInsights'`):

```DAX
Funnel Sessions   = CALCULATE(SUM('TravelAssistant OptimizationInsights'[sessions]), 'TravelAssistant OptimizationInsights'[type] = "funnel_stage")
Cause Sessions     = CALCULATE(SUM('TravelAssistant OptimizationInsights'[sessions]), 'TravelAssistant OptimizationInsights'[type] = "abandonment_cause")
Conversion Rate %  = CALCULATE(MAX('TravelAssistant OptimizationInsights'[conversion_rate]), 'TravelAssistant OptimizationInsights'[type] = "conversion_kpi")
Biggest Leak       = CALCULATE(MAX('TravelAssistant OptimizationInsights'[biggest_leak]), 'TravelAssistant OptimizationInsights'[type] = "conversion_kpi")
```

Visuals:
- **Funnel visual — the conversion funnel:** use the **Funnel** visual. Category `'…OptimizationInsights'[stage]`, Values `[Funnel Sessions]`, visual-level filter `type = "funnel_stage"`. **To order it engaged → searched → planned → confirmed:** first set the sort-by column — select the `stage` field → **Column tools → Sort by column → `stage_order`** — then on the visual, **… → Sort axis → `stage` → Sort ascending**. (You won't find `stage_order` in the visual's sort menu directly; it only lists fields in the visual, which is why `stage` must carry the order.)
- **Cards:** `[Conversion Rate %]` (a **Card** or **KPI** visual — it's numeric) and `[Biggest Leak]` (use a plain **Card** visual, *not* KPI — `biggest_leak` is **text** like `city_friction`, and the KPI visual only accepts numeric values).
- **Bar — why sessions don't convert:** use a **Stacked bar chart** (or Clustered — identical with one value). **Y-axis** = `'…OptimizationInsights'[cause]`, **X-axis** = `[Cause Sessions]`, **Legend** empty; visual-level filter `type = "abandonment_cause"`. Sort descending (**… → Sort axis → `[Cause Sessions]` → descending**). (Newer Power BI labels the wells **Y-axis/X-axis** rather than Axis/Values.)

> **Talking point:** the earlier pages cut *cost*; this page shows *conversion* — the business metric. And it doesn't leave you guessing: it names the biggest addressable leak (e.g. the agent re-asking the city) and points at the fix (SCEN-001). That's the reverse-ETL payoff — Fabric-computed intelligence, landed back where the app can act on it.

---

## Step 6: Save and Export

### Save as .pbix (the shipped artifact)
**File** → **Save As** → **`TravelAssistantAnalyticsReport.pbix`** into **`analytics/`** so it ships with the repo. This is the file `Provision-Fabric.ps1` imports; because it's **DirectQuery** it carries no data and stays small. Whatever `MirrorSQLEndpoint` / `MirrorDatabase` values are baked in don't matter — the provisioning **overrides them per deployment**.

> **Committing:** `*.pbix` is git-ignored except this one file (see the `.gitignore` exception). Run `git add analytics/TravelAssistantAnalyticsReport.pbix` and commit.

Need a `.pbit` template later (e.g. for someone to open in Desktop)? Export one on demand with **File → Export → Power BI template**, or headless via `pbi-tools compile -format PBIT` — the repo ships the `.pbix` only.

---

## Real-time notes

- **DirectQuery** queries the mirror SQL endpoint live. Use **Refresh** on a page, or set a page **auto-refresh** interval (Format → Page refresh) for a hands-free live demo while the traffic simulator runs.
- The **Business Impact** page (Page 5) refreshes when the Module 09 reverse-ETL notebook rewrites `OptimizationInsights` and the mirror carries the new rows through.

## Table reference (mirrored columns)

**`OptimizationTurns`** — `tenantId`, `userId`, `sessionId`, `model_tier`, `model_deployment`, `model_name`, `input_tokens`, `output_tokens`, `total_tokens`, `cached_tokens`, `handoff_count`, `timeStamp` *(text, ISO-8601)*, `turn_epoch` *(bigint, epoch seconds of the turn — use this for the `TurnTime`/`TurnMinute` columns)*.

**`Trips`** — `tenantId`, `userId`, `tripId`, `status` (planning/confirmed/completed), `destination`, …

**`OptimizationPolicies`** — `scenario_id`, `title`, `status` (proposed/active/staged/reverted), `apply_mode`, `params`, `proposed_change`, `version`, `proposed_by`, `created_at`, `updated_at`, `created_epoch`, `updated_epoch` *(bigint epoch seconds — use `updated_epoch` for `PolicyUpdated`)*.

**`Configuration`** — a small multi-entity config store keyed by `type`. Pricing rows have `type = "model_pricing"`, `model`, `input_price`, `output_price` (USD per 1M tokens); the `type = "model_selection_defaults"` doc carries the proposed tier/classifier policy. Filter `type = "model_pricing"` when joining for cost.

**`OptimizationInsights`** — reverse-ETL output from the Fabric notebook, keyed by `type`: `funnel_stage` (`stage`, `stage_order`, `sessions`), `abandonment_cause` (`cause`, `sessions`), `conversion_kpi` (`engaged`, `confirmed`, `conversion_rate`, `biggest_leak`), and `optimization_result` (`scenario`, `title`, `method`, `status`, `turns`, `baseline_cost_usd`, `actual_cost_usd`, `saving_usd`, `saving_pct`) — **one row per optimization**, stored under `tenantId = "_optimizations"`. Powers the Business Impact + Measured Saving pages; every visual filters on `type`. (The `recommendation_card` and `turn_metrics` rows in this same container carry nested JSON the *app/console* reads — not for Power BI visuals.)

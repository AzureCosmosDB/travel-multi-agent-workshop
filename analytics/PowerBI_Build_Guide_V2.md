# Power BI Report Build Guide — V2 (Agent Optimization Analytics)

Step-by-step instructions for building the **Agent Optimization** report in Power BI Desktop against
your **Fabric mirrored database** of the Travel Assistant analytics. This is the V2 companion to
`PowerBI_Build_Guide.md` (v1 memory analytics) and produces a portable **`.pbit`** template that any
workshop attendee can open and point at their own mirror.

Unlike v1 (Import mode over Lakehouse gold tables), V2 uses **DirectQuery over the mirrored database's
SQL endpoint**, so the report reflects Cosmos data **near-real-time** (the mirror replicates
continuously) with no dataset refresh. The report is **measure-driven** — you build a handful of DAX
measures over two raw mirrored tables.

> The most real-time option is a **Direct Lake semantic model** over the mirror (reads OneLake
> directly). One is created programmatically in the workshop automation
> (`TravelAssistantV2AnalyticsModel`, see `analytics/fabric/README.md`); you can also **live-connect** a
> report to it. DirectQuery is used here because it makes a **portable, re-pointable `.pbit`** for
> attendees.

---

## Prerequisites

- **Power BI Desktop** installed (latest version).
- A **Fabric mirrored database** of your Cosmos analytics is running and replicating (see
  `analytics/fabric/README.md`). It mirrors at least `OptimizationTurns` and `Trips`.
- Your mirror's **SQL analytics endpoint** and **database name**.

To find the SQL analytics endpoint:
1. Open your **Mirrored database** in the Fabric portal.
2. Click the **SQL analytics endpoint** dropdown (top-left, next to the mirror name).
3. Copy the connection string (e.g., `xxxxx.datawarehouse.fabric.microsoft.com`).
4. Note the **database name** — it is the mirror artifact name (e.g., `TravelAssistantV2Analytics`),
   and the **schema** is your Cosmos database name (e.g., `TravelAssistantV2`).

---

## Step 1: Connect to the Mirror (DirectQuery)

1. Open **Power BI Desktop**.
2. **Get Data** → **SQL Server database**.
3. **Server:** your mirror SQL analytics endpoint URL.
4. **Database:** the mirror name (e.g., `TravelAssistantV2Analytics`).
5. **Data Connectivity mode:** **DirectQuery** (this is what gives near-real-time).
6. **OK**, then authenticate with your **Microsoft (organizational) account**.
7. In the Navigator, expand the schema (your Cosmos DB name, e.g., `TravelAssistantV2`) and select:

| Table | Used for |
|-------|----------|
| `OptimizationTurns` | every KPI, cost-by-tier, model usage, trivial % |
| `Trips` | confirmed outcomes, cost per outcome |
| `OptimizationPolicies` *(optional)* | current policy status |

8. Click **Load** (not Transform Data).

---

## Step 2: Parameterize the Connection (makes the .pbit portable)

So attendees can point the template at *their* mirror without editing Power Query:

1. **Home** → **Transform data** (Power Query Editor).
2. **Home** → **Manage Parameters** → **New Parameter**:
   - **Name:** `MirrorSQLEndpoint` · **Type:** Text · **Current Value:** your SQL endpoint URL.
3. **New Parameter** again:
   - **Name:** `MirrorDatabase` · **Type:** Text · **Current Value:** your mirror name (e.g., `TravelAssistantV2Analytics`).
4. For each table, right-click → **Advanced Editor**, and replace the hard-coded server/database in the
   `Sql.Database(...)` step with the parameters:
   ```m
   Source = Sql.Database(MirrorSQLEndpoint, MirrorDatabase)
   ```
5. **Close & Apply**.

> When someone opens the `.pbit`, Power BI prompts for `MirrorSQLEndpoint` + `MirrorDatabase`, they
> paste their own values, and the report loads their data.

---

## Step 3: Create the Measures (the analytics)

The report is driven by these measures. Add them to the **`OptimizationTurns`** table (right-click →
**New measure**). These are the exact, validated measures from the Direct Lake semantic model.

```DAX
Total Turns   = COUNTROWS('OptimizationTurns')
Total Tokens  = SUM('OptimizationTurns'[total_tokens])

Trivial Turns = CALCULATE(COUNTROWS('OptimizationTurns'), 'OptimizationTurns'[model_tier] = "trivial")
Trivial %     = DIVIDE([Trivial Turns], [Total Turns]) * 100

Est Cost USD =
SUMX(
    'OptimizationTurns',
    VAR d    = 'OptimizationTurns'[model_deployment]
    VAR pin  = SWITCH(TRUE(), d = "gpt-5-nano", 0.05, d = "gpt-4.1-mini", 0.40, d = "gpt-5.1", 1.25, 0.40)
    VAR pout = SWITCH(TRUE(), d = "gpt-5-nano", 0.40, d = "gpt-4.1-mini", 1.60, d = "gpt-5.1", 10.0, 1.60)
    RETURN ('OptimizationTurns'[input_tokens] * pin + 'OptimizationTurns'[output_tokens] * pout) / 1000000
)

Confirmed Trips  = CALCULATE(COUNTROWS('Trips'), 'Trips'[status] = "confirmed" || 'Trips'[status] = "completed")
Cost per Outcome = DIVIDE([Est Cost USD], [Confirmed Trips])
```

> **Token pricing** is a list-price estimate; update the `SWITCH` rates if your tiers/prices differ.
> The trivial rule uses `model_tier` (the recorded tier), not an output-token heuristic.

---

## Step 4: Set Up the Theme

Use a dark dashboard theme (matches the workshop screenshots). Set the canvas background to a dark
color if desired.

---

## Page 1: Optimization Overview

Answers: **What are our agents doing, and what does it cost?**

- **KPI Cards** (top row): `[Total Turns]`, `[Est Cost USD]`, `[Trivial %]`, `[Cost per Outcome]`,
  `[Confirmed Trips]`.
- **Donut / bar — Model usage:** Axis `OptimizationTurns[model_deployment]`, Values `[Total Turns]`.
  (A single model at 100% is the model-selection opportunity.)
- **Line — Turns over time:** Axis `OptimizationTurns[timeStamp]` (by minute/hour), Values
  `[Total Turns]`. *(This is the visual that visibly moves as the traffic simulator runs.)*

## Page 2: Cost by Tier

Answers: **Where does spend go once tiering is applied?**

- **Clustered bar — Est cost by tier:** Axis `OptimizationTurns[model_tier]`, Values `[Est Cost USD]`.
- **Matrix:** Rows `model_tier`, `model_deployment`; Values `[Total Turns]`, `[Total Tokens]`,
  `[Est Cost USD]`.
- **Card:** `[Cost per Outcome]` — the north-star.

## Page 3: The Optimization Opportunity

Answers: **Which turns are wasteful, and what's the recommended fix?**

- **Gauge / KPI — Trivial %** with a target (~48% observed).
- **Stacked column — turns by tier over time:** Axis `timeStamp`, Legend `model_tier`, Values
  `[Total Turns]`.
- **Text box** describing the SCEN-007 model-selection recommendation (route trivial turns to a cheap
  model), so the page tells the story, not just the numbers.

---

## Step 5: Save and Export

### Save as .pbix
**File** → **Save As** → `TravelAssistantV2AnalyticsReport.pbix`

### Export as .pbit Template (for distribution)
1. **File** → **Export** → **Power BI template (.pbit)**.
2. Description: "Travel Multi-Agent — Agent Optimization Analytics — DirectQuery over your Fabric
   mirrored database (near-real-time)."
3. Save as **`TravelAssistantV2AnalyticsReport.pbit`** into **`analytics/`** so it ships with the repo.

The `.pbit`:
- Contains layout, visuals, measures, and the parameterized Power Query — **no data** (small file).
- Prompts for `MirrorSQLEndpoint` + `MirrorDatabase` on open; attendees enter their own values.

---

## Real-time notes

- **DirectQuery** queries the mirror SQL endpoint live, so visuals refresh as new turns replicate
  (continuous mirroring, ~seconds). Use **Refresh** on a page, or set a page **auto-refresh** interval
  (Format → Page refresh) for a hands-free live demo while the traffic simulator runs.
- **Direct Lake** (via a semantic model over the mirror) is even more real-time and needs no query
  round-trip; use it if you build reports live-connected to `TravelAssistantV2AnalyticsModel` rather
  than a portable template.

## Table reference (mirrored columns)

**`OptimizationTurns`** — `tenantId`, `userId`, `sessionId`, `model_tier`, `model_deployment`,
`model_name`, `input_tokens`, `output_tokens`, `total_tokens`, `cached_tokens`, `timeStamp`.

**`Trips`** — `tenantId`, `userId`, `tripId`, `status` (planning/confirmed/completed), `destination`, …

**`OptimizationPolicies`** — `scenario`, `status` (proposed/active/reverted), `params`, `version`, `audit`.

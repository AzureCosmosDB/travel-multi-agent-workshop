# Power BI Report Build Guide — Agent Optimization Analytics

Step-by-step instructions for building the **Agent Optimization** report in Power BI Desktop against
your **Fabric mirrored database** of the Travel Assistant analytics. This is the companion to
`PowerBI_Build_Guide.md` (the memory-analytics report) and produces a portable **`.pbit`** template that any
workshop attendee can open and point at their own mirror.

Unlike the memory-analytics guide (Import mode over Lakehouse gold tables), this report uses **DirectQuery over the mirrored database's
SQL endpoint**, so the report reflects Cosmos data **near-real-time** (the mirror replicates
continuously) with no dataset refresh. The report is **measure-driven** — you build a handful of DAX
measures over two raw mirrored tables.

> The most real-time option is a **Direct Lake semantic model** over the mirror (reads OneLake
> directly). One is created programmatically in the workshop automation
> (`TravelAssistantAnalyticsModel`, see `analytics/fabric/README.md`); you can also **live-connect** a
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
4. Note the **database name** — it is the mirror artifact name (e.g., `TravelAssistantAnalytics`),
   and the **schema** is your Cosmos database name (e.g., `TravelAssistant`).

---

## Step 1: Connect to the Mirror (DirectQuery)

1. Open **Power BI Desktop**.
2. **Get Data** → **SQL Server database**.
3. **Server:** your mirror SQL analytics endpoint URL.
4. **Database:** the mirror name (e.g., `TravelAssistantAnalytics`).
5. **Data Connectivity mode:** **DirectQuery** (this is what gives near-real-time).
6. **OK**, then in the credentials dialog select the **Microsoft account** tab on the left (a.k.a.
   organizational account) → **Sign in** → **Connect**.
   > ⚠️ **Do NOT use the Windows tab.** The Fabric SQL analytics endpoint only accepts Microsoft Entra
   > auth. Windows/Integrated auth fails with **`Microsoft SQL: Integrated Security not supported.`**
   > If you hit that error, you cached a Windows credential for this server — clear it via
   > **File → Options and settings → Data source settings → Clear Permissions**, then reconnect and
   > pick **Microsoft account**.
   >
   > *Simpler alternative:* **Get Data → Microsoft Fabric → OneLake data hub**, pick your
   > **SQL analytics endpoint** there — it uses your signed-in Entra identity automatically, no
   > credential prompt.
7. In the Navigator, expand the schema (your Cosmos DB name, e.g., `TravelAssistant`) and select:

| Table | Used for |
|-------|----------|
| `OptimizationTurns` | every KPI, cost-by-tier, model usage, trivial % |
| `Trips` | confirmed outcomes, cost per outcome |
| `OptimizationPolicies` | applied-optimizations audit (Page 4) |

8. Click **Load** (not Transform Data).

---

## Step 2: Parameterize the Connection (makes the .pbit portable)

So attendees can point the template at *their* mirror without editing Power Query:

1. **Home** → **Transform data** (Power Query Editor).
2. **Home** → **Manage Parameters** → **New Parameter**:
   - **Name:** `MirrorSQLEndpoint` · **Type:** Text · **Current Value:** your SQL endpoint URL.
3. **New Parameter** again:
   - **Name:** `MirrorDatabase` · **Type:** Text · **Current Value:** your mirror name (e.g., `TravelAssistantAnalytics`).
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

The report is driven by these measures. Add them to the **`TravelAssistant OptimizationTurns`** table
(right-click → **New measure**). These are the exact, validated measures from the Direct Lake semantic
model.

> **Why the table name has a prefix:** the mirror exposes your tables under a schema equal to your
> **Cosmos DB name** (e.g., `TravelAssistant`), not `dbo`. Power BI's navigator therefore names each
> model table `<schema> <table>` — e.g., **`TravelAssistant OptimizationTurns`**. Reference that full
> name in DAX (as below).
>
> *Rename-proof alternative:* right after **Load**, rename each model table (right-click table →
> **Rename**) to a clean name — `OptimizationTurns`, `Trips`, `OptimizationPolicies`. Then every measure
> and visual can use the short name (`'OptimizationTurns'`), and a future Cosmos DB (schema) rename
> won't touch your DAX at all. If you do this, use the short names throughout instead of the prefixed
> ones shown below.

```DAX
Total Turns   = COUNTROWS('TravelAssistant OptimizationTurns')
Total Tokens  = SUM('TravelAssistant OptimizationTurns'[total_tokens])

Trivial Turns = CALCULATE(COUNTROWS('TravelAssistant OptimizationTurns'), 'TravelAssistant OptimizationTurns'[model_tier] = "trivial")
Trivial %     = DIVIDE([Trivial Turns], [Total Turns]) * 100

Est Cost USD =
SUMX(
    'TravelAssistant OptimizationTurns',
    VAR d    = 'TravelAssistant OptimizationTurns'[model_deployment]
    VAR pin  = SWITCH(TRUE(), d = "gpt-5-nano", 0.05, d = "gpt-4.1-mini", 0.40, d = "gpt-5.1", 1.25, 0.40)
    VAR pout = SWITCH(TRUE(), d = "gpt-5-nano", 0.40, d = "gpt-4.1-mini", 1.60, d = "gpt-5.1", 10.0, 1.60)
    RETURN ('TravelAssistant OptimizationTurns'[input_tokens] * pin + 'TravelAssistant OptimizationTurns'[output_tokens] * pout) / 1000000
)

Confirmed Trips  = CALCULATE(COUNTROWS('TravelAssistant Trips'), 'TravelAssistant Trips'[status] = "confirmed" || 'TravelAssistant Trips'[status] = "completed")
Cost per Outcome = DIVIDE([Est Cost USD], [Confirmed Trips])

Cached Tokens = SUM('TravelAssistant OptimizationTurns'[cached_tokens])
Cache Hit %   = DIVIDE([Cached Tokens], SUM('TravelAssistant OptimizationTurns'[input_tokens])) * 100
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
  > ⚠️ Use the **Card** visual (or **Multi-row card**) — **not** the **KPI** visual. The KPI visual
  > requires a Target + Trend axis and renders **blank** if you just drop a measure in it, which looks
  > like "no data" even when the model is fully populated.
- **Donut / bar — Model usage:** Axis `'TravelAssistant OptimizationTurns'[model_deployment]`, Values `[Total Turns]`.
  (A single model at 100% is the model-selection opportunity.)
- **Line — Turns over time:** Axis `[TurnMinute]` (see note), Values `[Total Turns]`. Set the X-axis
  **Type = Continuous** (Format visual → X axis). *(This is the visual that visibly moves as the traffic
  simulator runs.)*
  > ⚠️ **`timeStamp` is stored as text**, so it won't bin by time. Add a real datetime column first
  > from the Cosmos epoch column **`_ts`** (bigint, seconds):
  > ```DAX
  > TurnTime = DATE(1970,1,1) + 'TravelAssistant OptimizationTurns'[_ts] / 86400.0
  > ```
  > Set its **Data type = Date/time**, then use `[TurnTime]` on every time axis (this line chart and the
  > Page 3 stacked column). `TurnTime` is UTC.
  > - **Use `86400.0`, not `86400`.** In DirectQuery this folds to T-SQL, and `bigint / bigint` is
  >   *integer* division — it truncates the time-of-day and collapses every turn to **midnight**, so
  >   time filters show nothing. The `.0` forces float division and preserves the time.
  > - **To aggregate over time, bucket to the minute** (per-second granularity makes `[Total Turns]`
  >   ≈ 1 at every point — a flat line). Add a minute-bucket **column** (DAX division is float, so floor
  >   it explicitly):
  >   ```DAX
  >   TurnMinute = DATE(1970,1,1) + ROUNDDOWN('TravelAssistant OptimizationTurns'[_ts] / 60, 0) / 1440
  >   ```
  >   Set **Data type = Date/time**, put `TurnMinute` on the time axis, and make sure the axis field is
  >   the plain field (not the auto **Date Hierarchy**) with **X-axis Type = Continuous**.
  > - **Filtering the time axis:** relative filters ("last N hours") are evaluated in **UTC**, matching
  >   `TurnTime`/`TurnMinute` (also UTC) — ideal for a **live demo**, since the window auto-follows new
  >   data. For the **shipped `.pbit` with static seed data, use a fixed filter** (`is on or after
  >   <date>`) or none — a relative filter shows blank once the data ages past the window.
  >   Either way, **use the time filter to dial the view in on the window you want to show** (e.g., the
  >   last hour of a live run, or a specific demo window) so the chart isn't stretched across idle gaps.

## Page 2: Cost by Tier

Answers: **Where does spend go once tiering is applied?**

- **Clustered bar — Est cost by tier:** Axis `'TravelAssistant OptimizationTurns'[model_tier]`, Values `[Est Cost USD]`.
- **Matrix:** Rows `model_tier`, `model_deployment`; Values `[Total Turns]`, `[Total Tokens]`,
  `[Est Cost USD]`.
- **Card:** `[Cost per Outcome]` — the north-star.
- **Cache effectiveness (a second cost lever):**
  - **Card / Gauge — `[Cache Hit %]`** (~76% observed). Prompt caching already recovers most input-token
    cost; this shows how much.
  - **Clustered bar — cache hit % by tier:** Axis `'TravelAssistant OptimizationTurns'[model_tier]`,
    Values `[Cache Hit %]`. Talking point: caching helps *every* tier, but it doesn't fix paying premium
    rates for trivial turns — that's what model selection (Page 3) addresses. The two levers are
    complementary.

## Page 3: The Optimization Opportunity

Answers: **Which turns are wasteful, and what's the recommended fix?**

- **Gauge / KPI — Trivial %** with a target (~48% observed).
- **Stacked column — turns by tier over time:** Axis `[TurnMinute]` (the minute-bucket column from the
  Page 1 note), Legend `model_tier`, Values `[Total Turns]`.
- **Text box** describing the SCEN-007 model-selection recommendation. Suggested copy:
  > **The Optimization Opportunity — Model Selection (SCEN-007)**
  > About half of all agent turns are *trivial* — greetings, acknowledgements, and short confirmations
  > that need no reasoning. Today every turn runs on the same mid-tier model, so we pay the same for
  > "thanks!" as for "plan my 5-day trip to Tokyo."
  > **Recommendation:** route trivial turns to a cheaper model (`gpt-5-nano`) and reserve the larger
  > model for complex requests. Trivial turns cost ~4–8× less on `gpt-5-nano` than `gpt-4.1-mini`
  > (input $0.05 vs $0.40; output $0.40 vs $1.60 per 1M tokens) — no quality loss on turns that were
  > never reasoning. **Impact:** lower Cost per Outcome while confirmed trips stay flat.

## Page 4: Applied Optimizations (governance / audit)

Answers: **What optimizations have we proposed or applied, and what's their state?**

This closes the loop — the earlier pages show the *opportunity*; this shows the *action taken*. Uses the
**`OptimizationPolicies`** table (schema-prefixed: `'TravelAssistant OptimizationPolicies'`).

- **Table (main visual):** columns `scenario_id`, `title`, `status`, `apply_mode`, `version`,
  `proposed_by`, `PolicyUpdated`. Each row is a policy the optimization loop proposed/applied/reverted
  (e.g., SCEN-007 *Capability-tiered model selection*, SCEN-001 *Active-trip city context*).
  > Use the **`PolicyUpdated` calculated column** for the "updated" column, **not** the raw `updated_at`
  > (which is ISO-8601 **text** and displays ugly). Add it as a **column**:
  > ```DAX
  > PolicyUpdated = DATE(1970,1,1) + 'TravelAssistant OptimizationPolicies'[_ts] / 86400.0
  > ```
  > Set **Data type = Date/time**. Also turn the visual's **Totals row Off** (Format → Totals) — summing
  > versions/dates is meaningless here.
- **Cards:**
  - **Active policies** — a Card on `[Active Policies]`.
  - **Latest change** — a Card on `[Latest Policy Change]` (most recent `updated_at`).
- **Conditional formatting** (optional): color the `status` column — `active` green, `staged`/`proposed`
  amber, `reverted` grey — so state reads at a glance.

Add these two measures (Step 3) for the cards:
```DAX
Active Policies      = CALCULATE(COUNTROWS('TravelAssistant OptimizationPolicies'), 'TravelAssistant OptimizationPolicies'[status] = "active")
Latest Policy Change = DATE(1970,1,1) + MAX('TravelAssistant OptimizationPolicies'[_ts]) / 86400.0
```

> `updated_at` is stored as **text** (ISO-8601), so `MAX(updated_at)` returns an ugly raw string — use
> the `_ts` epoch column (as above) and set the measure's **Format = Date time**. Same reason
> `TurnTime` uses `_ts` instead of `timeStamp`.

> This page tells the workshop's punchline: analytics surfaced the opportunity → the optimization loop
> proposed a policy (SCEN-007) → here's its audit trail. It's optional but ties the narrative together.

---

## Step 5: Save and Export

### Save as .pbix
**File** → **Save As** → `TravelAssistantAnalyticsReport.pbix`

### Export as .pbit Template (for distribution)
1. **File** → **Export** → **Power BI template (.pbit)**.
2. Description: "Travel Multi-Agent — Agent Optimization Analytics — DirectQuery over your Fabric
   mirrored database (near-real-time)."
3. Save as **`TravelAssistantAnalyticsReport.pbit`** into **`analytics/`** so it ships with the repo.

The `.pbit`:
- Contains layout, visuals, measures, and the parameterized Power Query — **no data** (small file).
- Prompts for `MirrorSQLEndpoint` + `MirrorDatabase` on open; attendees enter their own values.

---

## Real-time notes

- **DirectQuery** queries the mirror SQL endpoint live, so visuals refresh as new turns replicate
  (continuous mirroring, ~seconds). Use **Refresh** on a page, or set a page **auto-refresh** interval
  (Format → Page refresh) for a hands-free live demo while the traffic simulator runs.
- **Direct Lake** (via a semantic model over the mirror) is even more real-time and needs no query
  round-trip; use it if you build reports live-connected to `TravelAssistantAnalyticsModel` rather
  than a portable template.

## Table reference (mirrored columns)

**`OptimizationTurns`** — `tenantId`, `userId`, `sessionId`, `model_tier`, `model_deployment`,
`model_name`, `input_tokens`, `output_tokens`, `total_tokens`, `cached_tokens`, `timeStamp` *(text,
ISO-8601 — do not use directly on a time axis)*, `_ts` *(bigint, Cosmos epoch **seconds** — use this for
the `TurnTime` datetime column)*.

**`Trips`** — `tenantId`, `userId`, `tripId`, `status` (planning/confirmed/completed), `destination`, …

**`OptimizationPolicies`** — `scenario_id`, `title`, `status` (proposed/active/staged/reverted),
`apply_mode`, `params`, `proposed_change`, `version`, `proposed_by`, `created_at`, `updated_at`.

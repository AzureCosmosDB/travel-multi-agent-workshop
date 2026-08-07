# Power BI report — reconciliation delta (agent scorecard + governance audit)

Apply this to an **already-built** report to bring it up to the current
[`PowerBI_Optimization_Build_Guide.md`](../PowerBI_Optimization_Build_Guide.md). It covers only
what changed with the **node-grain agent scorecard**, the **governance decision-audit trail**, and
the **memory-retention / tool-call-dedup** measured-saving rows. Nothing on Pages 1–5, 6, 7 changes.

## TL;DR

| Action | Item | Why |
|--------|------|-----|
| **Build** | **Page 6b — Agent Performance** (per-agent × dimension scorecard) | New `agent_scorecard` rows; the ADR-0010 primary surface |
| **Load** | **`OptimizationGovernance`** table | New Page 8 *Decision Audit Trail* visual |
| **Modify** | **Page 8** — add *Decision Audit Trail* visual; verify `[Result Note]` | Mirror the C1–C5 audit; new `telemetry`/`governed` methods |
| **Create** | 3 measures: `[Agent Count]`, `[Top Agent Opportunity USD]`, `[Scorecard Status Color]` | Page 6b |
| **Verify** | scenario slicer shows `memory-retention` + `tool-call-dedup` | Data-driven; no structural change |
| **Nav** | Add the **Page 6b** tab after Page 6 | Reading order 1–8 |

No new tables are needed for Page 6b — `agent_scorecard` rows live in the already-loaded
`OptimizationInsights`. Only `OptimizationGovernance` is a new table load (for Page 8).

---

## 1. Data prerequisites (do first)

Page 6b is **empty until a producer writes `agent_scorecard` rows**. Run **either**:
- the **Module 09 notebook** (Section 5d) over the mirrored `NodeExecutions`, **or**
- the app-plane twin: `python analytics/fabric/compute_insights.py --tenant analytics`

Both use the same `build_scorecard` logic **with your Configuration pricing**, so notebook == console
== report. `NodeExecutions` must be **in the mirror** (already done in this deployment). After the
producer runs, **Refresh** the report.

---

## 2. Load the new table (for Page 8 audit trail)

This report is **DirectQuery over the mirror's SQL analytics endpoint** (SQL Server connector,
parameterized on `MirrorSQLEndpoint` / `MirrorDatabase`) — so add the table to the **existing**
connection; do **not** create a new Cosmos source.

**Recommended — keeps the parameterized, re-pointable source:**
1. **Home → Transform data** (Power Query editor).
2. In the **Queries** pane, right-click an existing mirror table (e.g. `OptimizationPolicies`) →
   **Duplicate**.
3. On the duplicate, open **Home → Advanced Editor** and change the navigated table name from
   `OptimizationPolicies` to `OptimizationGovernance` (the `Item="OptimizationPolicies"` step under
   the `Schema="TravelAssistant"` navigation). Leave the `Sql.Database(MirrorSQLEndpoint, MirrorDatabase)`
   source line untouched — that's what keeps it re-pointable.
4. Rename the query to **`OptimizationGovernance`** → **Close & Apply**.

**Quicker alternative (may hard-code the endpoint):** **Home → Get Data → SQL Server database**,
re-enter the same **Server** (mirror SQL endpoint) + **Database** (`TravelAssistantAnalytics`),
**DirectQuery** → in the Navigator expand the `TravelAssistant` schema → check **`OptimizationGovernance`**
→ **Load**. Fine for a local report, but it won't use the parameters, so the `.pbix` isn't re-pointable
across deployments — prefer the Duplicate method for the committed report.

It arrives as `'TravelAssistant OptimizationGovernance'` and holds `type` (`decision` / `slo_policy` /
`declared_schema`), `kind`, `subject`, `by`, `timeStamp`, `tenantId`, and a JSON-string `payload`.
Set `timeStamp`'s **Data type = Date/time**.

> Runtime-only container — **empty until an operator makes a decision** in the Console or via
> `POST /optimizations/agent/{tenant}/decision`. An empty audit table is expected, not a wiring error.

---

## 3. New measures (Modeling → New measure)

```DAX
Agent Count =
    CALCULATE(DISTINCTCOUNT('TravelAssistant OptimizationInsights'[agent]),
              'TravelAssistant OptimizationInsights'[type] = "agent_scorecard")

Top Agent Opportunity USD =
    CALCULATE(MAX('TravelAssistant OptimizationInsights'[value]),
              'TravelAssistant OptimizationInsights'[type] = "agent_scorecard",
              'TravelAssistant OptimizationInsights'[dim_status] = "opportunity")

Scorecard Status Color =        -- conditional formatting for the matrix
    SWITCH(SELECTEDVALUE('TravelAssistant OptimizationInsights'[dim_status]),
        "opportunity", "#f6c453", "watch", "#f6a2a2", "ok", "#57d9a3", "#93a1bd")
```

Also **verify** your existing `[Result Note]` (Page 8) has the `governed` + `telemetry` branches —
update it if it predates the memory-retention / tool-call-dedup work:

```DAX
Result Note =
    VAR _m =
        CALCULATE(MAX('TravelAssistant OptimizationInsights'[method]),
                  'TravelAssistant OptimizationInsights'[type] = "optimization_result")
    RETURN SWITCH(_m,
        "governed",  "Governed-path fix (human-reviewed prompt/code PR) - no in-app policy to apply, so no measured before/after here; see the turn-grain estimate on Discovered Opportunities.",
        "telemetry", "Measured from recall telemetry - input tokens avoided by dropping pruned memories from recall; reads $0 until the memory-retention policy is applied and recalls run.",
        "")
```

---

## 4. Build Page 6b — Agent Performance (new page)

New report page, name it **Agent Performance**. Source rows: `agent_scorecard` in
`'TravelAssistant OptimizationInsights'` — one row per **(agent, dimension)** with `agent`,
`dimension`, `dim_status` (`ok`/`watch`/`opportunity`), `agent_status` (agent's worst dimension),
`cost`, `cost_share`, `executions`, `turns`, `tokens_per_turn`, `headline`, `value`, `unit`.

### How the Power BI panes work (read once)

On the right of Power BI Desktop there are three panes: the **Data** pane (far right — your tables and
fields), the **Visualizations** pane (middle — the row of chart‑type icons, and below them the **field
wells** such as *X‑axis*, *Y‑axis*, *Rows*, *Values*), and the **Filters** pane (its own fly‑out). To
build any visual: click an **empty spot on the canvas**, click a **chart‑type icon** in Visualizations,
then **drag fields from the Data pane into the named wells**. Every step below is literally
*"drag FIELD → WELL."* Fields in `[square brackets]` are **measures** (from §3); the rest are columns
on `'TravelAssistant OptimizationInsights'`.

### Page filter (do this once for the whole page)

Open the **Filters** pane → under **Filters on this page** drag **`tenantId`** in → **Filter type =
Basic** → tick **`analytics`**. (Scorecard rows also exist for `marvel` / `funnel_demo`; this keeps the
whole page on one dataset.)

### Visual 1 — Agent leaderboard (cost by agent) · **Stacked bar chart**

1. Click an empty area of the canvas. In **Visualizations**, click the **Stacked bar chart** icon
   (horizontal bars — hover the icons to read their names).
2. Drag **`agent`** → the **Y‑axis** well.
3. Drag **`cost`** → the **X‑axis** well (it displays as **Sum of cost** — leave it). `cost` is
   **USD** (real per‑1M‑token Configuration pricing), so values are small — ~$0.76–$2.29 per agent
   here. Turn on **Format visual → Data labels** and set **X‑axis → Values → Value decimal places = 2,
   Display units = None** so bars read `$2.29` instead of landing between the `2` and `3` gridlines.
4. Leave the **Legend** well **empty**. *(Putting `dimension` here splits each agent into 3 equal
   segments.)*
5. In the **Filters** pane, under **Filters on this visual**: drag **`type`** in → tick
   **`agent_scorecard`**; then drag **`dimension`** in → tick **`cost_efficiency`**. **This second
   filter is required** — each agent has 3 identical‑cost rows (one per dimension), so without it the
   bars triple‑count (`Sum` = 3× real; `cost_share` sums to 300%).
6. Sort: click the visual's **⋯ (More options, top‑right of the visual) → Sort axis → cost → Sort
   descending**.

> Do **not** use the **100% Stacked bar chart** icon — it forces every bar to 100% regardless of value.

### Visual 2 — Agent × dimension health matrix · **Matrix**

1. Empty canvas → **Visualizations** → **Matrix** icon.
2. Drag **`agent`** → the **Rows** well.
3. Drag **`dimension`** → the **Columns** well.
4. Drag **`dim_status`** → the **Values** well. If it shows as **Count of dim_status**, click its
   dropdown in the **Values** well → choose **First**.
5. **Filters on this visual:** drag **`type`** in → tick **`agent_scorecard`**.
6. Turn off subtotals (the scorecard is a fixed agent×dimension grid, so subtotals just add a
   meaningless "Total" row and column): **Format visual → Row subtotals → Off**, and
   **Format visual → Column subtotals → Off**.
7. Color each cell by health — see **"Color the matrix cells"** immediately below.

#### Color the matrix cells (green/amber by health)

Color each cell by health using the `[Scorecard Status Color]` measure (it returns a hex per
`dim_status`, so each agent×dimension cell paints itself). Two entry points — either works:

**A — via the Values well (most reliable):**
1. Select the matrix. In the **Values** well, click the **dropdown** on the `dim_status` field (or the
   `First(headline)` measure you put there) → **Conditional formatting → Background color**.
2. In the dialog: **Format style = `Field value`**.
3. **What field should we base this on? = `[Scorecard Status Color]`**. (Leave summarization **First**.)
4. **OK**.

**B — via the Format pane (newer Desktop):**
1. Select the matrix → **Format your visual** (paint-roller) → expand **Cell elements**.
2. **Settings apply to → Series:** pick the value field (`dim_status` / `First headline`).
3. Turn **Background color → On**, click its **fx**.
4. **Format style = Field value**, **Based on field = `[Scorecard Status Color]`** → **OK**.

> **Gotchas.** The matrix needs a **Values** field for *Cell elements* to appear — put `dim_status`
> (or `First(headline)`) there first. `[Scorecard Status Color]` uses `SELECTEDVALUE([dim_status])`,
> which resolves cleanly because each cell is exactly one (agent, dimension) row. If the field-value
> option is greyed out, confirm the measure returns valid hex strings (`#57d9a3` etc.). Optionally
> repeat for **Font color** with the same measure to match, and set **Values → Totals = Off** so the
> total column isn't mis-colored.

> **Wide columns / horizontal scrollbar?** Each column auto‑sizes to its **header**
> (`workflow_efficiency` is long) while the cell values are short (`ok`/`watch`/`opportunity`), so the
> columns stretch and overflow → scrollbar. Fix any one: **(a)** widen the visual (drag its side handle)
> so all columns fit; **(b) Format visual → Options → Auto‑size column width → Off**, then drag each
> column's right border left; **(c) Format visual → Column headers → Text →** smaller **Font size** and
> **Word wrap → On** so the header stacks instead of stretching the column.

### Visual 3 — Headline cards · **Card**

1. Empty canvas → **Visualizations** → **Card** icon (shows one big number).
2. Drag **`[Agent Count]`** → the **Fields** well.
3. Add a **second Card** the same way → drag **`[Top Agent Opportunity USD]`** → **Fields**. Format it
   as dollars: **Format visual → General → Data format → Apply settings to = `Top Agent Opportunity USD`
   → Format options → Format = Currency → Decimal places = 2**.

### Visual 4 — Detail table · **Table**

1. Empty canvas → **Visualizations** → **Table** icon.
2. Drag these into the **Columns** well, in this order: **`agent`**, **`dimension`**, **`dim_status`**,
   **`headline`**, **`cost_share`**, **`tokens_per_turn`**.
3. **Filters on this visual:** drag **`type`** in → tick **`agent_scorecard`**.
4. Sort by `cost_share`: click the **`cost_share`** column header until its arrow points **down**.
5. Turn off the totals row: **Format visual → Totals → Off**.

### Optional — two caption text boxes (transparency)

Add each as a **Text box** on the page (top ribbon: **Insert → Text box**), then type the caption. They
exist only so a viewer doesn't over-read the numbers — skip them if you don't want them.

**Caption 1 — how per-agent cost is derived.** Suggested text to type:
> *"Per-agent cost is measured exactly on live app traffic; on the demo (seed) dataset, how a turn's
> cost splits across agents is estimated. Either way the per-agent costs always add up to the turn's
> real total — only the split within a turn is estimated on seed data."*

Why it's here: on real traffic the app records exact per-agent tokens; the seeded `analytics` data only
stored a per-**turn** total, so `seed_data.py` reconstructs a plausible per-agent split that still
reconciles to that total (totals are never fabricated — only the intra-turn division is modeled).

**Caption 2 — why only three dimensions show.** Suggested text to type:
> *"Only 3 of 8 health dimensions are scored today: cost efficiency, model selection, workflow
> efficiency. The other five (agent quality, routing effectiveness, tool utilization, memory
> effectiveness, business outcomes) aren't captured yet, so they're left out rather than shown as a
> fake 'n/a'."*

Why it's here: the matrix intentionally has only 3 dimension columns — this tells the reader the other
five are **not-yet-built**, not broken.

---

## 5. Modify Page 8 — add the Decision Audit Trail

Page 8 already has a table (from `OptimizationPolicies`) showing **which optimizations are currently
turned on**. This adds a **second table** showing **who approved / rejected / attested each optimization,
and when** — the human decision log (from `OptimizationGovernance`). Two different questions: *"is it
on?"* vs *"who decided that, and when?"*

> **Prerequisite — the columns don't exist until there's data.** `OptimizationGovernance` is **empty on
> a fresh deployment** (0 rows), and an empty mirrored table exposes **only `_rid`/`_ts`** — so
> `timeStamp`, `kind`, `subject`, `by` **won't appear in the Data pane yet** and you can't build the
> table. Do one of: **(a)** skip this visual for now and add it later; or **(b)** create one decision
> first — approve/reject/attest in the **Optimization Console**, or `POST /optimizations/agent/{tenant}/decision`
> — then **Refresh** (and refresh the SQL‑endpoint schema if needed). The columns appear once ≥1 row exists.

### Add the audit table · **Table**

1. On **Page 8**, click an empty spot on the canvas. In **Visualizations**, click the **Table** icon.
2. From the **`'TravelAssistant OptimizationGovernance'`** table in the Data pane, drag these into the
   **Columns** well, in this order: **`timeStamp`**, **`kind`**, **`subject`**, **`by`**, **`tenantId`**.
   (`kind` is the decision type — approve / reject / attest / confirm-revert. Skip **`payload`** — it's
   a raw JSON string.)
3. **Filters on this visual:** drag **`type`** in → tick **`decision`**. (The same container also holds
   `slo_policy` and `declared_schema` rows; this keeps the table to decisions only.)
4. Sort newest-first: click the **`timeStamp`** column header until its arrow points **down**.
5. Turn off the totals row: **Format visual → Totals → Off**.

### Optional — two summary visuals

- **A count Card:** **Visualizations → Card** → drag **`id`** into the **Fields** well (it shows as
  **Count of id**; if not, click its dropdown → **Count**). Add the same visual filter **`type` =
  `decision`**. Rename it *"Governed decisions logged."*
- **A count-by-kind bar:** **Visualizations → Stacked bar chart** → **`kind`** → **Y-axis**; **`id`** →
  **X-axis** (set it to **Count**). Add the visual filter **`type` = `decision`**.

> **This table is empty until someone makes a decision** in the Console (or the decision API) —
> `OptimizationGovernance` is runtime-only and never seeded. An empty audit table is expected here, not
> a wiring error.

**No other Page 8 changes.** The Apply/Revert buttons and the measured-saving visuals stay as they are.
The **scenario slicer** will automatically list `memory-retention` and `tool-call-dedup` once a producer
has written those `optimization_result` rows — data-driven, nothing to rebuild.

---

## 6. Nav / reading order

Drag the new **Agent Performance** tab to sit **right after Page 6 (Agent Collaboration)**, so the
tab order stays 1 → 2 → 3 → 4 → 5 → 6 → **6b** → 7 → 8.

---

## Verification checklist

- [ ] Producer run (notebook Section 5d **or** `compute_insights.py --tenant analytics`) → **Refresh**.
- [ ] Page 6b matrix shows `supervisor`, `find_places`, `create_or_update_itinerary` with green/amber
      cells; `find_places` reads *"repeats within a turn"* on `workflow_efficiency`.
- [ ] Agent costs are **realistic per-1M Configuration rates** (not ~34× inflated) — confirms the
      pricing fix is in the producer you ran.
- [ ] `OptimizationGovernance` loaded; Page 8 audit table renders (empty until a decision is made).
- [ ] `[Result Note]` shows the governed / telemetry text when those scenarios are selected.

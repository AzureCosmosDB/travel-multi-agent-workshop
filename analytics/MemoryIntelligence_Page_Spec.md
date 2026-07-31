# Memory Intelligence — report page build spec

A small, high-value page for `TravelAssistantAnalyticsReport.pbix` that surfaces the flagship
**memory-intelligence** signals — how much the agent has learned, how confident it is (salience),
and how much of that knowledge is stale or superseded. It's the *"see the problem"* half of the
**`memory-retention`** optimization the app already ships (the Console soft-prunes superseded
memories). Same detect → measure → apply → re-measure loop as `model-selection`, for the
**memory pillar** — the north-star of `analytics/docs/vision/agent-analytics-and-optimization-vision.md`.

> **The analytics are computed in the notebook, not in Power BI.** `ConversionFunnelReverseETL`
> **Section 6 (Memory intelligence)** reads the mirrored `memories` table and reverse-ETLs the
> result to `OptimizationInsights` — exactly like the conversion funnel. So this page reads the
> **same `OptimizationInsights` table already in the report** (filtered to the `memory_*` row
> types); **no new table, no raw DAX over `memories`.**

---

## Prerequisite — run the notebook
Run the notebook's **Section 6** once (it's provided — no TODO). It writes these flat rows to
`OptimizationInsights` under the reserved partition key `_global_memory` — **a bucket for
global (non-tenant) rows, not a real tenant** (a *tenant* is a customer with its own users like
`marvel`; memory is global, keyed by user). The report reads them by `type`:

| `type` | Fields | Feeds |
|---|---|---|
| `memory_kpi` | `total_memories`, `scored_memories`, `avg_salience`, `supersession_rate`, `low_salience_rate` | KPI cards |
| `memory_type` | `label` (fact/episodic/…), `count` | Memories by type |
| `memory_salience` | `label` (High/Medium/Low tier, or **Unscored**), `count` | Salience distribution |
| `memory_health` | `label` (Active/Superseded/Low-value, or **Unscored**), `count` | Memory health |

The mirror carries them back into the report's **`TravelAssistant OptimizationInsights`** table —
the same one the **Business Impact** page reads.

> **Some memories carry no salience — that's by design.** Salience is a retrieval-strength score
> for *extracted preference claims* (facts and episodics). **Procedural** memories are per-user
> "operating rules" the agent always applies, so they aren't scored (`salience` is NULL). Those
> land in an explicit **`Unscored`** bucket in both `memory_salience` and `memory_health` — never
> folded into `Low`/`Low-value`, so the two views stay consistent and unscored rules aren't
> mistaken for weak memories. The salience KPIs (`avg_salience`, `low_salience_rate`,
> `supersession_rate`) are computed over **scored memories only**; `scored_memories` exposes that
> denominator while `total_memories` still counts everything. **In the visuals, filter `Unscored`
> out of the Salience Distribution chart** (it's a not-applicable category there) — procedural
> memories remain visible in *Memories by Type*, which is where they belong.

> **Tier boundaries are config-driven.** The salience tier cutoffs live in the `Configuration`
> container (`type = "memory_config"`, seeded from `python/data/memory_config.json`: `salience_high`
> 0.8, `salience_medium` 0.5) — the same single-source-of-truth pattern as model pricing. Both the
> notebook (Section 6) and `compute_insights.py` read them, and the `memory_salience` **labels
> reflect the configured values** (e.g. `High (>=0.8)`), so changing the thresholds re-buckets the
> chart with no code edits.

## Measures (over the existing OptimizationInsights table)
```DAX
Total Memories =
    CALCULATE(SUM('TravelAssistant OptimizationInsights'[total_memories]),
              'TravelAssistant OptimizationInsights'[type] = "memory_kpi")

Scored Memories =
    CALCULATE(SUM('TravelAssistant OptimizationInsights'[count]),
              'TravelAssistant OptimizationInsights'[type] = "memory_salience",
              'TravelAssistant OptimizationInsights'[label] <> "Unscored")
    -- Derived from the salience buckets (High+Medium+Low) rather than the stored
    -- scored_memories column, so it needs no DirectQuery schema refresh to work.

Avg Memory Salience =
    CALCULATE(MAX('TravelAssistant OptimizationInsights'[avg_salience]),
              'TravelAssistant OptimizationInsights'[type] = "memory_kpi")

Supersession Rate % =
    CALCULATE(MAX('TravelAssistant OptimizationInsights'[supersession_rate]),
              'TravelAssistant OptimizationInsights'[type] = "memory_kpi")

Memory Bucket Count = SUM('TravelAssistant OptimizationInsights'[count])
```

## The page (one page, 4 visuals)
Add a page named **Memory Intelligence**. Each *bucket* visual gets a **visual-level filter on
`type`** so it only sees its own rows.

1. **KPI cards (top row)** — use the **Card** visual (one per measure), **not** the **KPI** visual.
   *(The KPI visual needs a Trend axis + target and renders blank with just a measure; Card shows
   the scalar directly.)* Cards: `Total Memories` · `Scored Memories` · `Avg Memory Salience`
   (3 decimals) · `Supersession Rate %`.
   *What it tells you:* how much the agent knows (and how much of it is salience-scored), how
   confident it is, and how much has been overridden by newer preferences (conflict resolution at
   work). *`Avg Memory Salience` and the rates are over scored memories only.*
2. **Memories by Type** — donut. *Visual filter:* `type is memory_type`. Legend = `label`,
   Values = `Memory Bucket Count`. *The mix of durable facts vs. episodic/turn memories.*
3. **Salience Distribution** — clustered column. *Visual filter:* `type is memory_salience`
   **AND `label is not Unscored`**. X-axis = `label`, Y = `Memory Bucket Count`. *A large **Low**
   tier signals over-extraction — recall pays to wade through memories it never uses. `Unscored`
   (procedural rules) is excluded here since it has no strength score.*
4. **Memory Health** — donut. *Visual filter:* `type is memory_health`. Legend = `label`,
   Values = `Memory Bucket Count`. *Active vs. **Superseded** vs. **Low-value**; Superseded +
   Low-value is the addressable waste the `memory-retention` optimization prunes.*

> **Clean up the axis/legend titles.** Visuals 2–4 all bind the shared `label` column, so each
> would otherwise show a generic **"label"** axis/legend title (the same column is reused across
> row types). **Rename the field per visual** — this renames it *for that visual only*, not the
> model column: select the visual → in the **Build** pane, double-click `label` in the Axis/Legend
> well (or right-click → **Rename for this visual**) → type a meaningful name: **`Memory Type`**
> (Memories by Type), **`Salience Tier`** (Salience Distribution), **`Health Status`** (Memory
> Health). Optionally rename `Memory Bucket Count` → **`Memories`** on the value axes. The renames
> are stored in the report and travel with the `.pbix`.

> **`superseded` lights up later:** the Fabric mirror only creates the `superseded` column once
> conflict resolution has superseded a memory. Until then Memory Health shows Active/Low-value and
> `Supersession Rate %` is 0 — drive a preference-conflict conversation (or the data enricher) to
> make it appear. The salience and type visuals work immediately.

## Save back to the repo
**File → Save As → `analytics/TravelAssistantAnalyticsReport.pbix`** (overwrite), then commit.
The provisioning auto-imports it, so every deployment ships with the Memory Intelligence page.

## The optimization tie-in (the point)
Memories aren't free: every recall retrieves and *pays* (tokens + latency) for what it pulls, so
**stale, never-recalled, low-salience, and superseded** memories are pure cost that can also
dilute answer quality. This page *measures* it; the **Optimization Console → `memory-retention`**
*acts* on it (reversible soft-prune). It's the memory-pillar instance of the same closed loop as
`model-selection` — and it's something an **analytics platform is uniquely able to show**: trace
tools tell you what one run did, but only cross-entity analytics over your app's own memory state
can tell you *"X% of memories are never recalled and Y% are superseded."*

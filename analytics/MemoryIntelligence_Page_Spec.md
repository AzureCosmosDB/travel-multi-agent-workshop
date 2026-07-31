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
`OptimizationInsights` under a reserved `_memory` tenant:

| `type` | Fields | Feeds |
|---|---|---|
| `memory_kpi` | `total_memories`, `avg_salience`, `supersession_rate`, `low_salience_rate` | KPI cards |
| `memory_type` | `label` (fact/episodic/…), `count` | Memories by type |
| `memory_salience` | `label` (High/Medium/Low tier), `count` | Salience distribution |
| `memory_health` | `label` (Active/Superseded/Low-value), `count` | Memory health |

The mirror carries them back into the report's **`TravelAssistant OptimizationInsights`** table —
the same one the **Business Impact** page reads.

## Measures (over the existing OptimizationInsights table)
```DAX
Total Memories =
    CALCULATE(SUM('TravelAssistant OptimizationInsights'[total_memories]),
              'TravelAssistant OptimizationInsights'[type] = "memory_kpi")

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

1. **KPI cards (top row):** `Total Memories` · `Avg Memory Salience` (3 decimals) · `Supersession Rate %`.
   *What it tells you:* how much the agent knows, how confident it is, and how much has been
   overridden by newer preferences (conflict resolution at work).
2. **Memories by Type** — donut. *Visual filter:* `type is memory_type`. Legend = `label`,
   Values = `Memory Bucket Count`. *The mix of durable facts vs. episodic/turn memories.*
3. **Salience Distribution** — clustered column. *Visual filter:* `type is memory_salience`.
   X-axis = `label`, Y = `Memory Bucket Count`. *A large **Low** tier signals over-extraction —
   recall pays to wade through memories it never uses.*
4. **Memory Health** — donut. *Visual filter:* `type is memory_health`. Legend = `label`,
   Values = `Memory Bucket Count`. *Active vs. **Superseded** vs. **Low-value**; Superseded +
   Low-value is the addressable waste the `memory-retention` optimization prunes.*

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

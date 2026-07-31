# Memory Intelligence — report page build spec

A small, high-value addition to `TravelAssistantAnalyticsReport.pbix`: **one page** that
surfaces the **flagship memory-intelligence signals** — how much the agent has learned, how
confident it is (salience), and how much of that knowledge is stale or superseded. It's the
*"see the problem"* half of the **`memory-retention`** optimization the app already ships
(the Optimization Console can soft-prune superseded memories). Same detect → measure → apply →
re-measure loop as `model-selection`, but for the **memory pillar** — the north-star of
`analytics/docs/vision/agent-analytics-and-optimization-vision.md` ("which memories are stale
or ineffective?").

> **Why an analytics platform and not LangSmith:** trace/observability tools answer *per-run*
> questions (what prompt, which tool, how many tokens). They can't tell you *"across my whole
> user base, X% of memories are never recalled and Y% are superseded"* — that's longitudinal,
> cross-entity analytics over the app's own state, which is exactly what Fabric + Power BI over
> mirrored Cosmos is for.

---

## Prerequisite
`Provision-Fabric.ps1` now mirrors the **`memories`** container (added to `MIRROR_TABLES`), so
after (re)provisioning the mirror it appears in the model as **`TravelAssistant memories`**
(DirectQuery, same SQL endpoint as the other tables).

## `memories` schema (top-level, scalar — what the report uses)
| Field | Type | Use |
|---|---|---|
| `salience` | double (0–1) | confidence/value of the memory — the core signal |
| `type` | string (`fact`, `episodic`, `turn`, …) | memory-type breakdown |
| `confidence` | double | extraction confidence (optional) |
| `created_at` / `updated_at` | timestamp | age / recency |
| `superseded` | bool *(present only on superseded memories)* | conflict-resolution / staleness |
| `user_id`, `role`, `tags`, `content` | — | slicing / detail |
| `embedding` | array | **exclude** (large vector — uncheck it when loading) |
| `metadata` | object | nested (category/subject/predicate) — mirrors as JSON; optional/advanced |

> When you add the table, **uncheck `embedding`** (and `content_hash`, `prompt_id`,
> `prompt_version`) to keep the model lean.

---

## Step 1 — Add the `memories` table
In Desktop, use the same DirectQuery source as the existing tables (the mirror SQL endpoint /
`MirrorSQLEndpoint` parameter) and select **`memories`**. It loads as `TravelAssistant memories`.

## Step 2 — Calculated columns
```DAX
Salience Tier =
SWITCH(
    TRUE(),
    'TravelAssistant memories'[salience] >= 0.8, "High (0.8–1.0)",
    'TravelAssistant memories'[salience] >= 0.5, "Medium (0.5–0.8)",
    "Low (<0.5)"
)
```
```DAX
Memory Health =
SWITCH(
    TRUE(),
    -- 'superseded' may not exist until a conflict supersedes a memory; see note below
    COALESCE('TravelAssistant memories'[superseded], FALSE()) = TRUE(), "Superseded",
    'TravelAssistant memories'[salience] < 0.5, "Low-value",
    "Active"
)
```

## Step 3 — Measures
```DAX
Total Memories = COUNTROWS('TravelAssistant memories')
Avg Salience   = AVERAGE('TravelAssistant memories'[salience])
Superseded Memories =
    CALCULATE([Total Memories], 'TravelAssistant memories'[Memory Health] = "Superseded")
Supersession Rate % = DIVIDE([Superseded Memories], [Total Memories]) * 100
Low-Salience % =
    DIVIDE(
        CALCULATE([Total Memories], 'TravelAssistant memories'[salience] < 0.5),
        [Total Memories]
    ) * 100
```

> **If the `superseded` column doesn't exist yet:** the Fabric mirror only creates columns for
> fields present in the data, and `superseded` appears only once conflict resolution supersedes
> a memory. To make it light up, run a **preference-conflict** conversation (or the data
> enricher) so the agent supersedes an earlier memory — exactly the signal the `memory-retention`
> optimization acts on. Until then, drop the two superseded measures/segment; the salience and
> type visuals work immediately.

## Step 4 — The page (keep it to one page, 4 visuals)
Add a page named **Memory Intelligence**:

1. **KPI cards (top row):** `Total Memories` · `Avg Salience` (3 decimals) · `Supersession Rate %`.
   *What it tells you:* how much the agent knows, how confident it is, and how much knowledge
   has been overridden by newer preferences (conflict resolution at work).
2. **Memories by Type** — donut, Legend = `type`, Values = `Total Memories`.
   *What it tells you:* the mix of durable facts vs. episodic/turn memories.
3. **Salience Distribution** — clustered column, X-axis = `Salience Tier`, Y = `Total Memories`.
   *What it tells you:* how much of memory is high-confidence vs. low-value noise. A large
   Low tier signals **over-extraction** — retrieval pays to wade through memories it never uses.
4. **Memory Health** — donut, Legend = `Memory Health`, Values = `Total Memories`.
   *What it tells you:* Active vs. Superseded vs. Low-value. Superseded + Low-value is the
   **addressable waste** the `memory-retention` optimization prunes.

## The optimization tie-in (the point)
Memories aren't free: every recall retrieves and pays (tokens + latency) for the memories it
pulls. **Stale, never-recalled, low-salience, and superseded memories are pure cost with no
benefit** — and they can dilute answer quality. This page *measures* that; the **Optimization
Console → `memory-retention`** *acts* on it (reversible soft-prune of superseded memories).
That's the memory-pillar instance of the same closed loop as `model-selection`.

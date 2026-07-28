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
- Connect the pattern to **L4/L5 autonomy**.

## Module Exercises

1. [Activity 1: The Two Planes and the Mirror](#activity-1-the-two-planes-and-the-mirror)
2. [Activity 2: Open the Notebook and Read the Mirror](#activity-2-open-the-notebook-and-read-the-mirror)
3. [Activity 3: Build the Decision (`cause` classification)](#activity-3-build-the-decision-cause-classification)
4. [Activity 4: Reverse-ETL the Insights Back to Cosmos](#activity-4-reverse-etl-the-insights-back-to-cosmos)
5. [Activity 5: Watch Power BI Light Up](#activity-5-watch-power-bi-light-up)

---

## Activity 1: The Two Planes and the Mirror

Your `azd`/Fabric provisioning already created a **mirrored database** of the Cosmos analytics containers (see `analytics/fabric/README.md`). The mirror carries the tables this module needs — `OptimizationTurns`, `Trips`, `Messages`, and the reverse-ETL target `OptimizationInsights`.

Two things to internalize:

- **The analytical plane reads the mirror, not Cosmos.** The Spark notebook queries the mirror's **SQL analytics endpoint** — the transactional account isn't touched by analytics.
- **Reverse-ETL is a deliberate, small write back.** You compute a lot in Fabric, then write a **handful of flat rows** back to Cosmos so the app can act cheaply.

## Activity 2: Open the Notebook and Read the Mirror

Provisioning already placed the **`ConversionFunnelReverseETL`** notebook in your Fabric workspace, with its parameters pre-filled from your deployment (Cosmos endpoint/database + the mirror's SQL endpoint). Open it, confirm the parameters look right, and set `TENANT = "funnel_demo"`.

Run the first two cells. The read cell pulls the mirrored tables via the SQL endpoint; the funnel cell (provided) aggregates turns into per-session stages — **engaged → searched → planned → confirmed** — and attaches a friction signal from the assistant `Messages`:

- `searched` — the session delegated to a place search (`handoff_count > 0` / `agent_path` hit `find_places`).
- `planned` — a turn reached the itinerary step.
- `confirmed` — the session (or its user) has a booked `Trip`.
- `city_reask` / `no_results` — friction flags mined from the assistant messages.

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

The next cell (provided) shapes the results into **flat** `OptimizationInsights` rows — `funnel_stage`, `abandonment_cause`, and a `conversion_kpi` row that even names the **biggest addressable leak**. Flat rows mean the report needs *no* session math.

## Activity 4: Reverse-ETL the Insights Back to Cosmos

Scroll to the section headed **`## 5. TODO 2 — reverse-ETL the insights back to Cosmos`**. Its code cell contains a `# ---- TODO 2 ----` placeholder — this is the pattern this module teaches. **Replace that placeholder** with the write below. It sends the three DataFrames (`funnel_df`, `cause_df`, `kpi_df`) back to the Cosmos **`OptimizationInsights`** container using the Spark Cosmos connector (the `cosmos_write` options are already defined in the cell above; Fabric authenticates to Cosmos with your Entra token):

```python
for df in (funnel_df, cause_df, kpi_df):
    df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
```

That's reverse-ETL: Fabric-computed intelligence, landed back in the operational store. The insight now lives where the app can read it — and where the **mirror** will carry it *back* to Fabric for Power BI.

> **The L4/L5 connection.** At Level 2 you *read* this insight. At **Level 4/5**, the system reads it and **acts** — e.g. the agent sees "biggest leak = city_friction" and auto-stages the SCEN-001 prompt fix. Reverse-ETL is the mechanism that makes self-optimizing agents possible: without a path back to the operational store, analytical intelligence just sits in a dashboard.

## Activity 5: Watch Power BI Light Up

Open the provided **`analytics/TravelAssistantAnalyticsReport.pbit`** in Power BI Desktop (the same report you connected in Module 07) and go to its **Business Impact** page. Before you ran the notebook it was empty; after your reverse-ETL write (and a mirror refresh), it **lights up** — the conversion funnel, the conversion-rate KPI, the biggest-leak callout, and the "why sessions don't convert" bar. **You didn't touch the report** — the insight flowed Cosmos → Fabric → reverse-ETL → Cosmos → mirror → Power BI.

*Stuck? Compare against `analytics/fabric/ConversionFunnelReverseETL_solution.ipynb`.*

## Test Your Work

- [ ] The read cell prints non-zero counts for `turns`, `trips`, `messages` from the **mirror**.
- [ ] Your `cause` classification runs and the cause breakdown looks sane (biggest bucket ≈ `city_friction` on `funnel_demo`).
- [ ] Your reverse-ETL write completes and `OptimizationInsights` has `funnel_stage` / `abandonment_cause` / `conversion_kpi` rows for the tenant.
- [ ] The Power BI **Business Impact** page populates without any report edits.
- [ ] You can explain, in your own words, why analytics runs in Fabric (not on Cosmos) and why reverse-ETL is what enables an agent to optimize *itself*.

**[< Agent Optimization](./Module-08.md)** - **[Lessons Learned & The Future >](./Module-10.md)**

"""Generator for ConversionFunnelReverseETL.ipynb (learner version).

Kept in-repo so the notebook can be regenerated deterministically. Run:
    python analytics/fabric/_gen_funnel_notebook.py
Produces ConversionFunnelReverseETL.ipynb (TODOs) and *_solution.ipynb (filled).
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def md(text):
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text, tags=None):
    meta = {"tags": tags} if tags else {}
    return {"cell_type": "code", "metadata": meta, "outputs": [], "execution_count": None,
            "source": text.splitlines(keepends=True)}


INTRO = """# Conversion funnel — reverse-ETL from Fabric back to Cosmos

**Cosmos DB** is the *operational* store for the live travel agent — low-latency reads/writes
on the request path. **Mirroring** streams it into **Microsoft Fabric** (the *analytical* plane)
with no ETL pipeline to build. This notebook does the kind of heavy, cross-session analysis you
would **never** run on the transactional path — a **conversion funnel** — and then
**reverse-ETLs** the result back into Cosmos so the app (and, at higher maturity, the agent
itself) can *act* on it.

```
Cosmos (operational) --mirror--> Fabric (Spark analysis) --reverse-ETL--> Cosmos OptimizationInsights --> app acts / Power BI
```

That closed loop is the substrate for **Level 4 (autonomous)** and **Level 5 (adaptive)**
optimization: Fabric computes the intelligence, reverse-ETL lands it where the operational
system can use it in real time.

You implement two pieces:
- **TODO 1** — classify *why* a session didn't convert (the analytics decision).
- **TODO 2** — the **reverse-ETL write** back to Cosmos (the pattern this module teaches)."""

CONFIG_MD = """## 0. Load the Cosmos connector (run this first)

The reverse-ETL write (Section 5) uses the **Azure Cosmos DB Spark connector** (`cosmos.oltp`), which isn't in Fabric's default Spark runtime. Run the cell below **first** — it loads the connector plus the Fabric auth library and **restarts the Spark session** (takes ~1 minute). After it finishes, run the **Parameters** cell, then continue top to bottom."""

CONFIG = '''%%configure -f
{
    "conf": {
        "spark.jars.packages": "com.azure.cosmos.spark:azure-cosmos-spark_3-5_2-12:4.41.0,com.azure.cosmos.spark:fabric-cosmos-spark-auth_3:1.1.0"
    }
}'''

PARAMS = '''# --- Parameters (overridable via RunNotebook parameterValues) ---
# Cosmos (reverse-ETL write target — the OPERATIONAL store)
COSMOS_ENDPOINT = ""            # https://<account>.documents.azure.com:443/
COSMOS_DATABASE = "TravelAssistant"
INSIGHTS_CONTAINER = "OptimizationInsights"
TENANT_ID = ""                 # Entra tenant (for the Fabric->Cosmos AAD write)
# Mirror SQL analytics endpoint (host, no port) + database (mirror artifact name)
SQL_EP = ""
SQL_DB = ""
SOURCE_SCHEMA = COSMOS_DATABASE   # the mirror schema == the Cosmos DB name
TENANT = "funnel_demo"            # which app tenant to analyze'''

READ = '''from pyspark.sql import functions as F
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()

# ---- read mirrored tables via the SQL analytics endpoint (the analytical plane
# reads the MIRROR, never the transactional Cosmos account) ----
_sql_token = mssparkutils.credentials.getToken("pbi")
_jdbc = f"jdbc:sqlserver://{SQL_EP}:1433;database={SQL_DB};encrypt=true;trustServerCertificate=false"

def read_sql(table):
    return (spark.read.format("jdbc")
            .option("url", _jdbc)
            .option("dbtable", f"[{SOURCE_SCHEMA}].[{table}]")
            .option("accessToken", _sql_token)
            .load()
            .where(F.col("tenantId") == TENANT))

turns = read_sql("OptimizationTurns")
trips = read_sql("Trips")
messages = read_sql("Messages")
print("turns:", turns.count(), "trips:", trips.count(), "messages:", messages.count())'''

FUNNEL = '''# ---- funnel stages per session (PROVIDED) ----
# A session is "searched" if any turn delegated (handoff>0 / agent_path hit find_places),
# "planned" if any turn's agent_path reached the itinerary step.
sess = (turns.groupBy("sessionId", "userId").agg(
    F.max(F.when((F.col("handoff_count") > 0) | F.col("agent_path").contains("find_places"), 1)
          .otherwise(0)).alias("searched"),
    F.max(F.when(F.col("agent_path").contains("itinerary"), 1).otherwise(0)).alias("planned"),
    F.sum("total_tokens").alias("tokens")))

# conversion: session-level when a Trip carries a sessionId, else user-level fallback
_conf = trips.filter(F.col("status").isin("confirmed", "completed"))
conv_sess = _conf.select("sessionId").distinct().withColumn("conv_s", F.lit(1))
conv_user = _conf.select("userId").distinct().withColumn("conv_u", F.lit(1))
sess = (sess.join(conv_sess, "sessionId", "left").join(conv_user, "userId", "left")
        .withColumn("confirmed",
                    F.when((F.col("planned") == 1) & (F.col("conv_s").isNotNull() | F.col("conv_u").isNotNull()), 1)
                     .otherwise(0)))

# friction signal from assistant Messages (feeds the cause classification below)
fr = (messages.filter(F.lower(F.col("role")) == "assistant").groupBy("sessionId").agg(
    F.max(F.when(F.lower(F.col("content")).rlike("which city|what city"), 1).otherwise(0)).alias("city_reask"),
    F.max(F.when(F.lower(F.col("content")).rlike("couldn't find|could not find|no matching|no results|nothing found"), 1)
          .otherwise(0)).alias("no_results")))
sess = sess.join(fr, "sessionId", "left").fillna(0, ["city_reask", "no_results"])
sess.groupBy("searched", "planned", "confirmed").count().show()'''

TODO1_STUB = '''# ---- TODO 1: classify WHY each non-converting session leaked (the analytics decision) ----
# Add a "cause" column. Converted sessions -> "converted". For the rest, in this order:
#   planned == 1                        -> "cart_abandon"   (got a plan, never booked)
#   searched == 1 and city_reask == 1   -> "city_friction"  (agent kept re-asking the city -> SCEN-001)
#   searched == 1 and no_results == 1   -> "no_results"     (search dead-ended)
#   searched == 1                       -> "search_stall"
#   otherwise                           -> "no_engagement"  (never searched)
#
# Hint: chain F.when(...).when(...).otherwise(...) on sess.
raise NotImplementedError("Implement the cause classification and set the `cause` column")

# sess = sess.withColumn("cause", ...)'''

TODO1_SOLUTION = '''# ---- TODO 1 (solution): classify WHY each non-converting session leaked ----
sess = sess.withColumn(
    "cause",
    F.when(F.col("confirmed") == 1, F.lit("converted"))
     .when(F.col("planned") == 1, F.lit("cart_abandon"))
     .when((F.col("searched") == 1) & (F.col("city_reask") == 1), F.lit("city_friction"))
     .when((F.col("searched") == 1) & (F.col("no_results") == 1), F.lit("no_results"))
     .when(F.col("searched") == 1, F.lit("search_stall"))
     .otherwise(F.lit("no_engagement")))
sess.groupBy("cause").count().orderBy(F.desc("count")).show()'''

BUILD = '''# ---- build the flat OptimizationInsights rows (PROVIDED) ----
# One value per row so the mirror keeps every field as a column and Power BI reads it
# with trivial DAX. Types: funnel_stage, abandonment_cause, conversion_kpi.
f = sess.agg(
    F.count(F.lit(1)).alias("engaged"),
    F.sum("searched").alias("searched"),
    F.sum("planned").alias("planned"),
    F.sum("confirmed").alias("confirmed")).collect()[0]
engaged, searched, planned, confirmed = (int(f["engaged"]), int(f["searched"]),
                                         int(f["planned"]), int(f["confirmed"]))

stage_rows = [(f"funnel::{TENANT}::{s}", "funnel_stage", TENANT, s, o, v, now) for s, o, v in [
    ("engaged", 1, engaged), ("searched", 2, searched), ("planned", 3, planned), ("confirmed", 4, confirmed)]]
funnel_df = spark.createDataFrame(stage_rows, ["id", "type", "tenantId", "stage", "stage_order", "sessions", "computed_at"])

cause_pd = (sess.filter(F.col("cause") != "converted").groupBy("cause").count().collect())
cause_rows = [(f"cause::{TENANT}::{r['cause']}", "abandonment_cause", TENANT, r["cause"], int(r["count"]), now)
              for r in cause_pd]
cause_df = spark.createDataFrame(cause_rows or [("cause::none", "abandonment_cause", TENANT, "none", 0, now)],
                                 ["id", "type", "tenantId", "cause", "sessions", "computed_at"])

addressable = {r["cause"]: int(r["count"]) for r in cause_pd if r["cause"] != "no_engagement"}
biggest = max(addressable, key=addressable.get) if addressable else "none"
kpi_df = spark.createDataFrame([(
    f"kpi::{TENANT}", "conversion_kpi", TENANT, engaged, confirmed,
    round(100 * confirmed / max(engaged, 1), 1), biggest, now)],
    ["id", "type", "tenantId", "engaged", "confirmed", "conversion_rate", "biggest_leak", "computed_at"])

print("funnel:", engaged, searched, planned, confirmed, "| biggest leak:", biggest)'''

SAVING_MD = """## 4b. Measured saving — counterfactual, keyed by optimization (provided)

A second reverse-ETL insight: the **measured** cost saving, keyed by the **optimization**
(scenario) — not the tenant. We price every captured turn (all tenants) under the model it
actually ran on vs. the single premium baseline (gpt-5.1), so the gap **is** the realized
saving from capability-tiered model selection. This flat `optimization_result` row (stored
under a reserved `_global_optimizations` partition key — a non-tenant bucket) feeds the
report's **Measured Saving** page, where a `scenario` slicer switches between optimizations.
Run this cell, then include `result_df` in the reverse-ETL write below."""

SAVING = '''# ---- 4b. Measured saving: counterfactual, keyed by OPTIMIZATION (PROVIDED) ----
# Price EVERY captured turn (all tenants) under the model it actually ran on vs. the
# all-premium baseline (gpt-5.1). Keyed by scenario (the optimization), NOT by tenant,
# and stored under a reserved "_global_optimizations" partition so the report slices on
# `scenario`. Pricing comes from the mirrored Configuration table (type="model_pricing").
BASELINE_DEPLOYMENT = "gpt-5.1"

_pricing = (spark.read.format("jdbc")
            .option("url", _jdbc)
            .option("dbtable", f"[{SOURCE_SCHEMA}].[Configuration]")
            .option("accessToken", _sql_token)
            .load()
            .where(F.col("type") == "model_pricing")
            .select(F.col("model").alias("dep"),
                    F.col("input_price").cast("double").alias("in_price"),
                    F.col("output_price").cast("double").alias("out_price")))

_base = _pricing.where(F.col("dep") == BASELINE_DEPLOYMENT).collect()
b_in = float(_base[0]["in_price"]) if _base else 1.25
b_out = float(_base[0]["out_price"]) if _base else 10.0

# ALL turns (every tenant) - the optimization measurement is keyed by scenario, not tenant
_all_turns = (spark.read.format("jdbc")
              .option("url", _jdbc)
              .option("dbtable", f"[{SOURCE_SCHEMA}].[OptimizationTurns]")
              .option("accessToken", _sql_token)
              .load())

_priced = (_all_turns.join(_pricing, _all_turns["model_deployment"] == _pricing["dep"], "left")
           .withColumn("in_price", F.coalesce(F.col("in_price"), F.lit(b_in)))
           .withColumn("out_price", F.coalesce(F.col("out_price"), F.lit(b_out))))

_agg = _priced.agg(
    F.sum((F.col("input_tokens") * F.col("in_price") + F.col("output_tokens") * F.col("out_price")) / F.lit(1e6)).alias("actual"),
    F.sum((F.col("input_tokens") * F.lit(b_in) + F.col("output_tokens") * F.lit(b_out)) / F.lit(1e6)).alias("baseline"),
    F.count(F.lit(1)).alias("turns")).collect()[0]

_actual = float(_agg["actual"] or 0.0)
_baseline = float(_agg["baseline"] or 0.0)
_n = int(_agg["turns"] or 0)
_saving = _baseline - _actual
_saving_pct = round(100 * _saving / _baseline, 1) if _baseline else 0.0

result_df = spark.createDataFrame(
    [("result::model-selection", "optimization_result", "_global_optimizations",
      "model-selection", "Capability-tiered model selection", "counterfactual",
      _n, round(_baseline, 4), round(_actual, 4), round(_saving, 4), _saving_pct, now)],
    ["id", "type", "tenantId", "scenario", "title", "method", "turns",
     "baseline_cost_usd", "actual_cost_usd", "saving_usd", "saving_pct", "computed_at"])
print("measured saving (model-selection): $%.4f (%.1f%% vs all-premium baseline) over %d turns" % (_saving, _saving_pct, _n))'''

TODO2_STUB = '''# ---- TODO 2: reverse-ETL — write the insight rows BACK to Cosmos (the pattern) ----
# Write funnel_df, cause_df, kpi_df, result_df to the Cosmos OptimizationInsights container
# using the Spark Cosmos connector (Fabric AAD). Use these options and mode("append") with the
# ItemOverwrite strategy so re-runs are idempotent.
cosmos_write = {
    "spark.cosmos.accountEndpoint": COSMOS_ENDPOINT,
    "spark.cosmos.account.tenantId": TENANT_ID,
    "spark.cosmos.accountDataResolverServiceName": "com.azure.cosmos.spark.fabric.FabricAccountDataResolver",
    "spark.cosmos.auth.type": "AccessToken",
    "spark.cosmos.useGatewayMode": "true",
    "spark.cosmos.database": COSMOS_DATABASE,
    "spark.cosmos.container": INSIGHTS_CONTAINER,
    "spark.cosmos.write.strategy": "ItemOverwrite",
    "spark.cosmos.write.bulk.enabled": "true",
}
raise NotImplementedError("Write funnel_df, cause_df, kpi_df, result_df to Cosmos with format('cosmos.oltp')")

# for df in (funnel_df, cause_df, kpi_df, result_df):
#     df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
# print("Reverse-ETL complete -> the Power BI Business Impact page will light up.")'''

TODO2_SOLUTION = '''# ---- TODO 2 (solution): reverse-ETL write back to Cosmos ----
cosmos_write = {
    "spark.cosmos.accountEndpoint": COSMOS_ENDPOINT,
    "spark.cosmos.account.tenantId": TENANT_ID,
    "spark.cosmos.accountDataResolverServiceName": "com.azure.cosmos.spark.fabric.FabricAccountDataResolver",
    "spark.cosmos.auth.type": "AccessToken",
    "spark.cosmos.useGatewayMode": "true",
    "spark.cosmos.database": COSMOS_DATABASE,
    "spark.cosmos.container": INSIGHTS_CONTAINER,
    "spark.cosmos.write.strategy": "ItemOverwrite",
    "spark.cosmos.write.bulk.enabled": "true",
}
for df in (funnel_df, cause_df, kpi_df, result_df):
    df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
print("Reverse-ETL complete -> the Power BI Business Impact page will light up.")'''

READ_MD = "## 1. Read the mirror\nThe analytical plane reads the **mirrored** tables through the SQL endpoint — the operational Cosmos account is never touched by analytics."
FUNNEL_MD = "## 2. Build the funnel (provided)\nAggregate turns into per-session stages and attach the friction signal."
TODO1_MD = "## 3. TODO 1 — classify the abandonment cause\nThis is the analytics decision you own (the notebook analog of `classify_turn_tier`)."
BUILD_MD = "## 4. Shape the insight rows (provided)\nFlat rows, one value each, so they mirror cleanly and Power BI needs no session-math."
TODO2_MD = "## 5. TODO 2 — reverse-ETL the insights back to Cosmos\nThe pattern that closes the loop: land Fabric-computed intelligence in the operational store."

MEMORY_MD = "## 6. Memory intelligence (provided) — reverse-ETL memory health\nMemories aren't free: every recall retrieves and *pays* (tokens + latency) for what it pulls, so **stale, low-salience, and superseded** memories are cost with no benefit. This provided section reads the mirrored **`memories`** table (the same SQL-endpoint path as above), computes salience / health / supersession, and reverse-ETLs the result to `OptimizationInsights` — the funnel pattern, for the **memory pillar**.\n\n> **Reserved partition key, not a tenant.** `OptimizationInsights` is partitioned by `/tenantId`, and a *tenant* here is a customer with its own users (e.g. `marvel`, `funnel_demo`). Memory is **global** — memories are keyed by user, not tenant — so these rows use a reserved partition key **`_global_memory`** (a bucket for non-tenant rows, distinguished by `type`), never a real tenant. The Power BI **Memory Intelligence** page reads them by `type`."

MEMORY_CODE = '''# ---- memory intelligence: read mirrored `memories`, compute health, reverse-ETL (PROVIDED) ----
# `_global_memory` is a RESERVED partition key, NOT a tenant. OptimizationInsights is
# partitioned by /tenantId; a tenant is a customer with users (marvel, funnel_demo). Memory is
# global (memories are keyed by user_id/thread_id), so its rows use this reserved bucket and are
# distinguished by `type` — they never mix with real per-tenant rows.
MEMORY_PARTITION = "_global_memory"

# memories are keyed by user_id/thread_id (NOT tenant) -> read the whole mirrored table via the
# same SQL-endpoint JDBC path as read_sql, minus the tenant filter.
mem = (spark.read.format("jdbc")
       .option("url", _jdbc)
       .option("dbtable", f"[{SOURCE_SCHEMA}].[memories]")
       .option("accessToken", _sql_token).load())
if "embedding" in mem.columns:
    mem = mem.drop("embedding")       # skip the large vector column

# Salience tier thresholds come from the mirrored Configuration table (type="memory_config") —
# the single source of truth shared with compute_insights.py, so the tiers never drift. Falls
# back to the built-in defaults if the row isn't seeded.
_mc = (spark.read.format("jdbc")
       .option("url", _jdbc)
       .option("dbtable", f"[{SOURCE_SCHEMA}].[Configuration]")
       .option("accessToken", _sql_token).load()
       .where(F.col("type") == "memory_config").collect())
SAL_HIGH = float(_mc[0]["salience_high"]) if _mc else 0.8
SAL_MED = float(_mc[0]["salience_medium"]) if _mc else 0.5
HIGH_L, MED_L, LOW_L = f"High (>={SAL_HIGH})", f"Medium ({SAL_MED}-{SAL_HIGH})", f"Low (<{SAL_MED})"

# 'superseded' exists only once conflict resolution has superseded a memory
_sup = F.col("superseded") if "superseded" in mem.columns else F.lit(False)
mem = (mem
       .withColumn("salience_tier",
                   F.when(F.col("salience") >= SAL_HIGH, HIGH_L)
                    .when(F.col("salience") >= SAL_MED, MED_L)
                    .otherwise(LOW_L))
       .withColumn("memory_health",
                   F.when(_sup == True, "Superseded")
                    .when(F.col("salience") < SAL_MED, "Low-value")
                    .otherwise("Active")))

total = mem.count()
a = mem.agg(F.avg("salience").alias("avg"),
            F.sum(F.when(_sup == True, 1).otherwise(0)).alias("sup"),
            F.sum(F.when(F.col("salience") < SAL_MED, 1).otherwise(0)).alias("low")).collect()[0]
avg_sal = round(float(a["avg"] or 0), 3)
sup_pct = round(100 * int(a["sup"] or 0) / max(total, 1), 1)
low_pct = round(100 * int(a["low"] or 0) / max(total, 1), 1)

mem_kpi_df = spark.createDataFrame(
    [(f"memkpi::{MEMORY_PARTITION}", "memory_kpi", MEMORY_PARTITION, total, avg_sal, sup_pct, low_pct, now)],
    ["id", "type", "tenantId", "total_memories", "avg_salience", "supersession_rate", "low_salience_rate", "computed_at"])

def _mem_buckets(col, rowtype):
    rs = mem.groupBy(col).count().collect()
    data = [(f"{rowtype}::{MEMORY_PARTITION}::{r[col]}", rowtype, MEMORY_PARTITION, str(r[col]), int(r["count"]), now)
            for r in rs]
    return spark.createDataFrame(
        data or [(f"{rowtype}::none", rowtype, MEMORY_PARTITION, "none", 0, now)],
        ["id", "type", "tenantId", "label", "count", "computed_at"])

for df in (mem_kpi_df,
           _mem_buckets("type", "memory_type"),
           _mem_buckets("salience_tier", "memory_salience"),
           _mem_buckets("memory_health", "memory_health")):
    df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
print(f"Memory reverse-ETL complete -> {total} memories, avg salience {avg_sal}, {sup_pct}% superseded, {low_pct}% low-salience")'''


def notebook(solution: bool):
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"},
                     "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark"}},
        "cells": [
            md(INTRO),
            md(CONFIG_MD), code(CONFIG),
            code(PARAMS, tags=["parameters"]),
            md(READ_MD), code(READ),
            md(FUNNEL_MD), code(FUNNEL),
            md(TODO1_MD), code(TODO1_SOLUTION if solution else TODO1_STUB),
            md(BUILD_MD), code(BUILD),
            md(SAVING_MD), code(SAVING),
            md(TODO2_MD), code(TODO2_SOLUTION if solution else TODO2_STUB),
            md(MEMORY_MD), code(MEMORY_CODE),
        ],
    }


def main():
    for solution, name in ((False, "ConversionFunnelReverseETL.ipynb"),
                           (True, "ConversionFunnelReverseETL_solution.ipynb")):
        path = HERE / name
        path.write_text(json.dumps(notebook(solution), indent=1) + "\n", encoding="utf-8")
        print("wrote", path.name)


if __name__ == "__main__":
    main()

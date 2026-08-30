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


INTRO = """# Optimization analytics — reverse-ETL from Fabric back to Cosmos

**Cosmos DB** is the *operational* store for the live travel agent — low-latency reads/writes
on the request path. **Mirroring** streams it into **Microsoft Fabric** (the *analytical* plane)
with no ETL pipeline to build. This notebook runs the kind of heavy, cross-session analysis you
would **never** run on the transactional path, then **reverse-ETLs** each result back into Cosmos
(`OptimizationInsights`) so the app, the **Optimization Console**, and **Power BI** can *act* on it.

```
Cosmos (operational) --mirror--> Fabric (Spark analysis) --reverse-ETL--> Cosmos OptimizationInsights --> app / Console / Power BI act
```

That closed loop is the substrate for **Level 4 (autonomous)** and **Level 5 (adaptive)**
optimization: Fabric computes the intelligence, reverse-ETL lands it where the operational
system can use it in real time.

**What this notebook computes** — each analysis reverse-ETLs flat rows (keyed by `type`) that the
Console and the Power BI report read directly:
- **Conversion funnel + abandonment cause** (Sections 2–3) — where sessions leak and *why* they don't convert.
- **Measured saving** (Section 4b) — keyed by optimization: the **model-selection counterfactual** (each captured turn re-priced under the model it actually ran on vs. the all-premium baseline) **and** the **memory-retention** telemetry saving (input tokens recalls avoided by dropping pruned memories, aggregated from the mirrored `ApiEvents`; `$0` until the policy is applied). The honest dollar figures behind the estimate cards.
- **Agent-path cost concentration** (5b) — which `agent_path`s dominate token cost (where model tiering + tool-dedup pay off first).
- **Turn metrics** (5c) — the Console KPIs: total turns/tokens, estimated cost, trivial-turn share, model distribution, cost-by-tier.
- **Agent scorecard** (5d) — per-agent health across **cost efficiency**, **model selection**, and **workflow efficiency**, rolled up from the mirrored `NodeExecutions` node-grain (feeds the Power BI **Agent Performance** page 6b).
- **Memory intelligence** (6) — salience / health / supersession of the memory subsystem.
- **LLM analyst** (7) — the model *proposes* one recommendation card **per detected opportunity** (**model-selection** + **tool-call-dedup**) and the engine's **guardrails** *dispose*: bound it to a known seam, require citations, and override its dollar figure with the engine-measured saving. Each accepted card is reverse-ETL'd as a `discovered_opportunity` **and** a flat `recommendation_card` row — now including a compact **evidence line** and a **caveat** — so the Console and the Power BI **recommendation gallery** show the same proof, limitation, and `governed_state` badge (and the tool-dedup card **supersedes** its app-plane "awaiting analysis" placeholder).

**You implement two pieces** (everything else is provided):
- **TODO 1** — classify *why* a session didn't convert (the analytics decision you own; the notebook analog of `classify_complexity_tier`).
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
TENANT = "analytics"            # which app tenant to analyze
# Azure OpenAI (the LLM analyst in Section 7 — keyless/AAD, the same account the app uses).
# Leave blank to skip the live call: the analyst then falls back to the deterministic
# proposer (engine parity), so the section still reverse-ETLs a guardrailed card.
AOAI_ENDPOINT = ""              # https://<account>.openai.azure.com/
AOAI_DEPLOYMENT = "gpt-5.1"
AOAI_API_VERSION = "2025-04-01-preview"'''

READ = '''from pyspark.sql import functions as F
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()

# ---- read mirrored tables via the SQL analytics endpoint (the analytical plane
# reads the MIRROR, never the transactional Cosmos account) ----
_sql_token = mssparkutils.credentials.getToken("pbi")
_jdbc = f"jdbc:sqlserver://{SQL_EP}:1433;database={SQL_DB};encrypt=true;trustServerCertificate=false"

def read_sql(table, tenant_scoped=True):
    df = (spark.read.format("jdbc")
          .option("url", _jdbc)
          .option("dbtable", f"[{SOURCE_SCHEMA}].[{table}]")
          .option("accessToken", _sql_token)
          .load())
    return df.where(F.col("tenantId") == TENANT) if tenant_scoped and "tenantId" in df.columns else df

turns = read_sql("OptimizationTurns")
# schema-compat: pre-rename telemetry stored the model tier as `model_tier`; the current
# app/seed write `complexity_tier` (same field). Normalize so downstream (5c) always finds it.
if "complexity_tier" not in turns.columns and "model_tier" in turns.columns:
    turns = turns.withColumnRenamed("model_tier", "complexity_tier")
trips = read_sql("Trips")
messages = read_sql("Messages")
policies = read_sql("OptimizationPolicies", tenant_scoped=False)
governance = read_sql("OptimizationGovernance")
print("turns:", turns.count(), "trips:", trips.count(), "messages:", messages.count(),
      "policies:", policies.count(), "governance:", governance.count())'''

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
#   searched == 1 and city_reask == 1   -> "city_friction"  (agent kept re-asking the city)
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
saving from capability-tiered model selection. We also aggregate the mirrored **ApiEvents**
recall telemetry into the **memory-retention** saving (input tokens recalls avoided by
dropping pruned memories — `$0` until that policy is applied). These flat `optimization_result`
rows (stored under a reserved `_global_optimizations` partition key — a non-tenant bucket) feed
the report's **Measured Saving** page, where a `scenario` slicer switches between optimizations.
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

# memory-retention: MEASURED from recall telemetry over the mirrored ApiEvents. Each
# `recall_pruned_avoided` event's response.avoided_input_tokens = the input tokens a recall
# avoided by dropping a pruned (superseded) memory from its top-k. Priced at the baseline
# input rate. Reads $0 until the memory-retention policy is applied and recalls run - an
# honest telemetry measurement, never an estimate. ApiEvents is high-volume, so we offload
# its aggregation to Fabric here (not the app plane).
import json as _json_mr
_mr_recalls = 0
_mr_avoided = 0
try:
    _apiev_df = (spark.read.format("jdbc").option("url", _jdbc)
                 .option("dbtable", f"[{SOURCE_SCHEMA}].[ApiEvents]")
                 .option("accessToken", _sql_token).load())
    # An EMPTY mirrored container surfaces only system columns (_rid/_ts) - no data schema
    # yet - so guard on the columns existing before filtering (a raw UNRESOLVED_COLUMN error
    # would look like a failure). ApiEvents fills at runtime (the Module 08 memory demo), so
    # $0 here is expected, not an error.
    if all(_c in _apiev_df.columns for _c in ("provider", "operation", "response")):
        _apiev = (_apiev_df
                  .where((F.col("provider") == "memory") & (F.col("operation") == "recall_pruned_avoided"))
                  .select("response").collect())
        _mr_recalls = len(_apiev)
        for _e in _apiev:
            _resp = _e["response"]
            if isinstance(_resp, str):
                try:
                    _resp = _json_mr.loads(_resp)
                except Exception:
                    _resp = {}
            _mr_avoided += int((_resp or {}).get("avoided_input_tokens") or 0)
    else:
        print("memory-retention: ApiEvents has no telemetry rows yet (empty mirror) - reads $0 until the Module 08 memory demo runs (expected, not an error).")
except Exception as _mrx:
    print("memory-retention telemetry skipped:", _mrx)
_mr_saving = round(_mr_avoided * b_in / 1e6, 4)
_MR_NOTE = ("Measured from recall telemetry (ApiEvents) - input tokens avoided by dropping pruned "
            "memories from a recall's top-k. Reads $0 until the memory-retention policy is applied and recalls run.")

# One row per applyable optimization so the report's `scenario` slicer switches between them.
# model-selection carries the real counterfactual; memory-retention the recall-telemetry
# measurement (both computed here in Fabric); tool-call-dedup is a GOVERNED-path fix (a
# prompt/code PR, not an in-app policy) - no measured before/after. compute_insights.py emits
# the identical rows app-plane (idempotent by id), so notebook == console == report.
_GOVERNED_NOTE = "Governed-path fix (human-reviewed prompt/code PR) - no in-app policy to apply, so no measured before/after here; see the turn-grain estimate on Discovered Opportunities."
_result_rows = [
    ("result::model-selection", "optimization_result", "_global_optimizations",
     "model-selection", "Capability-tiered model selection", "counterfactual",
     _n, round(_baseline, 4), round(_actual, 4), round(_saving, 4), _saving_pct, "", now),
    ("result::memory-retention", "optimization_result", "_global_optimizations",
     "memory-retention", "Memory retention (prune superseded)", "telemetry",
     _mr_recalls, 0.0, 0.0, _mr_saving, 0.0, _MR_NOTE, now),
]
for _sc, _title in [("tool-call-dedup", "Redundant tool-call dedup")]:
    _result_rows.append((f"result::{_sc}", "optimization_result", "_global_optimizations",
                         _sc, _title, "governed", 0, 0.0, 0.0, 0.0, 0.0, _GOVERNED_NOTE, now))

result_df = spark.createDataFrame(
    _result_rows,
    ["id", "type", "tenantId", "scenario", "title", "method", "turns",
     "baseline_cost_usd", "actual_cost_usd", "saving_usd", "saving_pct", "note", "computed_at"])
print("measured saving: model-selection $%.4f (%.1f%% vs baseline) over %d turns; memory-retention $%.4f (%d recalls); +1 governed" % (_saving, _saving_pct, _n, _mr_saving, _mr_recalls))'''

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

CHECKPOINT_SETUP = '''# Persist the last completed stage because failed Fabric jobs do not retain cell output.
def _checkpoint(stage):
    status_df = spark.createDataFrame(
        [(f"run-status::{TENANT}", "notebook_run_status", TENANT, stage,
          datetime.now(timezone.utc).isoformat())],
        ["id", "type", "tenantId", "last_completed_stage", "updated_at"],
    )
    status_df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
    print(f"Notebook checkpoint: {stage}")

_checkpoint("core_reverse_etl")'''


def checkpoint(stage):
    return f'_checkpoint("{stage}")'

READ_MD = "## 1. Read the mirror\nThe analytical plane reads the **mirrored** tables through the SQL endpoint — the operational Cosmos account is never touched by analytics."
FUNNEL_MD = "## 2. Build the funnel (provided)\nAggregate turns into per-session stages and attach the friction signal."
TODO1_MD = "## 3. TODO 1 — classify the abandonment cause\nThis is the analytics decision you own (the notebook analog of `classify_complexity_tier`)."
BUILD_MD = "## 4. Shape the insight rows (provided)\nFlat rows, one value each, so they mirror cleanly and Power BI needs no session-math."
TODO2_MD = "## 5. TODO 2 — reverse-ETL the insights back to Cosmos\nThe pattern that closes the loop: land Fabric-computed intelligence in the operational store."

MEMORY_MD = "## 6. Memory intelligence (provided) — reverse-ETL memory health\nMemories aren't free: every recall retrieves and *pays* (tokens + latency) for what it pulls, so **stale, low-salience, and superseded** memories are cost with no benefit. This provided section reads the mirrored **`memories`** table (the same SQL-endpoint path as above), computes salience / health / supersession, and reverse-ETLs the result to `OptimizationInsights` — the funnel pattern, for the **memory pillar**.\n\n> **Reserved partition key, not a tenant.** `OptimizationInsights` is partitioned by `/tenantId`, and a *tenant* here is a customer with its own users (e.g. `marvel`, `analytics`). Memory is **global** — memories are keyed by user, not tenant — so these rows use a reserved partition key **`_global_memory`** (a bucket for non-tenant rows, distinguished by `type`), never a real tenant. The Power BI **Memory Intelligence** page reads them by `type`."

MEMORY_CODE = '''# ---- memory intelligence: read mirrored `memories`, compute health, reverse-ETL (PROVIDED) ----
# `_global_memory` is a RESERVED partition key, NOT a tenant. OptimizationInsights is
# partitioned by /tenantId; a tenant is a customer with users (marvel, analytics). Memory is
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
# Some memory types (e.g. procedural) carry no salience score. NULL salience is its own
# "Unscored" tier in BOTH breakdowns below — never folded into "Low"/"Low-value", so the
# salience and health views stay consistent and unscored memories aren't mistaken for weak ones.
UNSCORED_L = "Unscored"

# supersession is marked by the 'superseded_by' pointer (+ superseded_at / supersede_reason),
# populated only once conflict resolution has replaced a memory
_sup = F.col("superseded_by").isNotNull() if "superseded_by" in mem.columns else F.lit(False)
mem = (mem
       .withColumn("salience_tier",
                   F.when(F.col("salience").isNull(), UNSCORED_L)
                    .when(F.col("salience") >= SAL_HIGH, HIGH_L)
                    .when(F.col("salience") >= SAL_MED, MED_L)
                    .otherwise(LOW_L))
       .withColumn("memory_health",
                   F.when(_sup == True, "Superseded")
                    .when(F.col("salience").isNull(), UNSCORED_L)
                    .when(F.col("salience") < SAL_MED, "Low-value")
                    .otherwise("Active")))

total = mem.count()
# Salience KPIs are computed over SCORED memories only (salience IS NOT NULL). Unscored
# memories (e.g. procedural guidance rules) have no strength score, so folding them into
# these denominators would understate avg salience and skew the health rates. total_memories
# still counts everything; scored_memories exposes the salience denominator explicitly.
a = mem.agg(F.avg("salience").alias("avg"),
            F.sum(F.when(F.col("salience").isNotNull(), 1).otherwise(0)).alias("scored"),
            F.sum(F.when(_sup == True, 1).otherwise(0)).alias("sup"),
            F.sum(F.when(F.col("salience") < SAL_MED, 1).otherwise(0)).alias("low")).collect()[0]
scored = int(a["scored"] or 0)
avg_sal = round(float(a["avg"] or 0), 3)
sup_pct = round(100 * int(a["sup"] or 0) / max(total, 1), 1)
low_pct = round(100 * int(a["low"] or 0) / max(scored, 1), 1)

mem_kpi_df = spark.createDataFrame(
    [(f"memkpi::{MEMORY_PARTITION}", "memory_kpi", MEMORY_PARTITION, total, scored, avg_sal, sup_pct, low_pct, now)],
    ["id", "type", "tenantId", "total_memories", "scored_memories", "avg_salience", "supersession_rate", "low_salience_rate", "computed_at"])

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
print(f"Memory reverse-ETL complete -> {total} memories ({scored} scored), avg salience {avg_sal}, {sup_pct}% superseded, {low_pct}% low-salience (of scored)")'''


AGENTPATH_MD = "## 5b. Agent-path cost concentration (provided)\nWhere do the tokens actually go? A few **agent paths** (typically the itinerary path) dominate token cost — many times a plain supervisor turn. This provided section aggregates the tenant's turns by `agent_path` and reverse-ETLs the **top paths by average tokens** as `agent_path_cost` rows (the twin of `compute_insights.py`). The Power BI **Agent Collaboration / Agent-Path Cost** page reads them — it's where tiering and tool-dedup fixes pay off."

AGENTPATH_CODE = '''# ---- 5b. agent-path cost concentration -> reverse-ETL agent_path_cost (PROVIDED) ----
# Cost concentrated in a few agent_paths. Top 6 by avg tokens (matches compute_insights.py's
# build_agent_path_diagnostic), so the report reads the same shape whichever producer ran.
_ap = (turns.withColumn("agent_path", F.coalesce(F.col("agent_path"), F.lit("unknown")))
       .groupBy("agent_path")
       .agg(F.count(F.lit(1)).alias("turns"), F.sum("total_tokens").alias("total_tokens"))
       .withColumn("avg_tokens", F.round(F.col("total_tokens") / F.col("turns")).cast("long"))
       .orderBy(F.desc("avg_tokens")).limit(6).collect())
agentpath_rows = [(f"path::{TENANT}::{i}", "agent_path_cost", TENANT, r["agent_path"],
                   int(r["turns"]), int(r["total_tokens"] or 0), int(r["avg_tokens"] or 0), now)
                  for i, r in enumerate(_ap)]
agentpath_df = spark.createDataFrame(
    agentpath_rows or [(f"path::{TENANT}::none", "agent_path_cost", TENANT, "none", 0, 0, 0, now)],
    ["id", "type", "tenantId", "agent_path", "turns", "total_tokens", "avg_tokens", "computed_at"])
agentpath_df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
print(f"Agent-path reverse-ETL complete -> {len(agentpath_rows)} paths")'''

SCORECARD_MD = "## 5d. Agent scorecard — agent × dimension health from node-grain (provided)\nThe primary ADR-0010 surface: **how is each individual agent doing?** Reads the mirrored **`NodeExecutions`** (per-agent node-grain), flattens each turn's executions, and scores every agent across the three node-grain dimensions (`cost_efficiency`, `model_selection`, `workflow_efficiency`) — mirroring `src/app/engine/scorecard` (rollup + dimensions), validated to match `build_scorecard` exactly. Reverse-ETL'd as `agent_scorecard` rows (one per agent×dimension) that the Power BI **Agent Performance** page (6b) reads. `compute_insights.py` writes the identical rows app-plane, so notebook == console == report."

SCORECARD_CODE = "# ---- 5d. agent scorecard -> reverse-ETL agent_scorecard (over mirrored NodeExecutions) ----\n# Mirrors engine/scorecard/{rollup,dimensions}.py. Uses the existing Configuration pricing\n# (_pricing, loaded in 4b - per 1M tokens) so notebook cost == Console cost (the console/\n# compute_insights pass the same pricing to build_scorecard). Shares/statuses are price-invariant.\n# Node-grain is small, so flatten the per-turn arrays on the driver and score in Python.\nimport json as _json_ne\n_SC_PRICE = {r['dep']: (float(r['in_price']), float(r['out_price'])) for r in _pricing.collect()}  # Configuration, per 1M\n_SC_LOW_OUT = 250; _SC_PREMIUM = {'gpt-5.1', 'gpt-5'}; _SC_CHEAP = 'gpt-5-mini'\n_SC_ORDER = {'opportunity': 0, 'watch': 1, 'ok': 2, 'n/a': 3}\ndef _sc_tcost(dep, i, o):\n    p = _SC_PRICE.get(dep)\n    return ((i * p[0] + o * p[1]) / 1e6) if p else 0.0\n\n# nodeExecutions arrives as a JSON string over the SQL endpoint; tolerate an already-parsed list too.\n_ne_rows = read_sql('NodeExecutions').select('turnId', 'nodeExecutions').collect()\n_nodes = []\nfor _r in _ne_rows:\n    _ne = _r['nodeExecutions']\n    if isinstance(_ne, str):\n        try:\n            _ne = _json_ne.loads(_ne)\n        except Exception:\n            _ne = []\n    for _nd in (_ne or []):\n        _d = _nd.asDict() if hasattr(_nd, 'asDict') else dict(_nd)\n        _nodes.append({'turn_id': _r['turnId'], 'agent': _d.get('agent', ''),\n                       'model_deployment': _d.get('model_deployment') or _d.get('model_name') or 'Unknown',\n                       'input_tokens': int(_d.get('input_tokens') or 0), 'output_tokens': int(_d.get('output_tokens') or 0)})\n\n_by_agent = {}\nfor _nd in _nodes:\n    _by_agent.setdefault(_nd['agent'], []).append(_nd)\n_sc_total = sum(_sc_tcost(n['model_deployment'], n['input_tokens'], n['output_tokens']) for n in _nodes) or 0.0\n_scorecard_rows = []\nfor _ag, _an in _by_agent.items():\n    _cost = sum(_sc_tcost(n['model_deployment'], n['input_tokens'], n['output_tokens']) for n in _an)\n    _share = (_cost / _sc_total) if _sc_total else 0.0\n    _ce = 'watch' if _share >= 0.5 else 'ok'\n    _execs = len(_an) or 1\n    _cand = [n for n in _an if n['model_deployment'] in _SC_PREMIUM and n['output_tokens'] < _SC_LOW_OUT]\n    _sav = sum(max(0.0, _sc_tcost(n['model_deployment'], n['input_tokens'], n['output_tokens']) - _sc_tcost(_SC_CHEAP, n['input_tokens'], n['output_tokens'])) for n in _cand)\n    _ms = 'opportunity' if (len(_cand) / _execs >= 0.2 and _sav > 0) else 'ok'\n    _per = {}\n    for n in _an:\n        _per[n['turn_id']] = _per.get(n['turn_id'], 0) + 1\n    _turns = len(_per) or 1\n    _rept = sum(1 for c in _per.values() if c > 1)\n    _we = 'opportunity' if (_rept / _turns) >= 0.1 else 'ok'\n    _tokens = sum(n['input_tokens'] + n['output_tokens'] for n in _an)\n    _tpt = round(_tokens / _turns, 1)\n    _astat = min((_ce, _ms, _we), key=lambda s: _SC_ORDER.get(s, 9))\n    _hce = '$%.4f (%.0f%% of turn spend), %.0f tok/turn' % (_cost, _share * 100, _tokens / _turns)\n    _hms = ('%d/%d trivial turns on a premium model -> save $%.4f by routing to %s' % (len(_cand), _execs, _sav, _SC_CHEAP)) if _cand else ('%d exec(s), no premium-on-trivial waste' % _execs)\n    _hwe = ('repeats within a turn in %d/%d turns (%.0f%%)' % (_rept, _turns, _rept / _turns * 100)) if _rept else ('one call per turn across %d turns (no redundant hops)' % _turns)\n    _dims = {'cost_efficiency': (_ce, _hce, round(_cost, 6), '$/window'),\n             'model_selection': (_ms, _hms, round(_sav, 6), '$/window'),\n             'workflow_efficiency': (_we, _hwe, round(_rept / _turns, 4), 'repeat-turn rate')}\n    for _dim, (_dstat, _head, _val, _unit) in _dims.items():\n        _scorecard_rows.append(('scorecard::%s::%s::%s' % (TENANT, _ag, _dim), 'agent_scorecard', TENANT, _ag, _astat,\n                                round(_cost, 6), round(_share, 4), int(_execs), int(_turns), float(_tpt), _dim, _dstat, _head, float(_val), _unit, now))\n\n_sc_cols = ['id', 'type', 'tenantId', 'agent', 'agent_status', 'cost', 'cost_share', 'executions', 'turns', 'tokens_per_turn', 'dimension', 'dim_status', 'headline', 'value', 'unit', 'computed_at']\n_sc_df = spark.createDataFrame(\n    _scorecard_rows or [('scorecard::%s::none' % TENANT, 'agent_scorecard', TENANT, 'none', 'n/a', 0.0, 0.0, 0, 0, 0.0, 'none', 'n/a', '', 0.0, '', now)],\n    _sc_cols)\n_sc_df.write.format('cosmos.oltp').options(**cosmos_write).mode('append').save()\nprint('Agent scorecard reverse-ETL complete -> %d rows (%d agents)' % (len(_scorecard_rows), len(_by_agent)))"

METRICS_MD = "## 5c. Turn metrics (provided)\nThe aggregate KPIs the **Optimization Console** displays — total turns/tokens, estimated cost, trivial-turn share, model distribution, and a cost-by-tier breakdown. Reverse-ETL'ing them (one `turn_metrics` row with a nested `metrics` object) means the Console reads a pre-computed result instead of re-aggregating Cosmos on every request. Same shape as `compute_insights.py`'s `build_turn_metrics`."

METRICS_CODE = '''# ---- 5c. turn metrics -> reverse-ETL turn_metrics (PROVIDED) ----
# The Console KPIs, computed once here. Priced with the same mirrored Configuration pricing
# as Section 4b. Nested `metrics` object -> we build it in the driver and write it with an
# EXPLICIT schema (the Cosmos connector needs typed nesting; heterogeneous inference fails).
from pyspark.sql.types import (StructType, StructField, StringType, LongType,
                               DoubleType, MapType, ArrayType)

_tp = (turns.join(_pricing, turns["model_deployment"] == _pricing["dep"], "left")
       .withColumn("in_price", F.coalesce(F.col("in_price"), F.lit(b_in)))
       .withColumn("out_price", F.coalesce(F.col("out_price"), F.lit(b_out)))
       .withColumn("cost", (F.col("input_tokens") * F.col("in_price")
                            + F.col("output_tokens") * F.col("out_price")) / F.lit(1e6)))
_m = _tp.agg(
    F.count(F.lit(1)).alias("total_turns"),
    F.sum("input_tokens").alias("in"), F.sum("output_tokens").alias("out"),
    F.sum("total_tokens").alias("tok"), F.sum("cost").alias("cost"),
    F.sum(F.when(F.col("output_tokens") < 60, 1).otherwise(0)).alias("trivial")).collect()[0]
_total = int(_m["total_turns"] or 0)
_dist = {str(r["model_name"]): int(r["count"]) for r in turns.groupBy("model_name").count().collect()}
_tier_rows = (_tp.groupBy("complexity_tier", "model_deployment")
              .agg(F.count(F.lit(1)).alias("turns"), F.sum("total_tokens").alias("tokens"),
                   F.sum("cost").alias("cost")).collect())
_by_tier = [{"complexity_tier": r["complexity_tier"] or "default",
             "deployment": r["model_deployment"] or "Unknown",
             "turns": int(r["turns"]), "tokens": int(r["tokens"] or 0),
             "cost": round(float(r["cost"] or 0), 6)}
            for r in sorted(_tier_rows, key=lambda x: -(x["cost"] or 0))]
_est_cost = round(float(_m["cost"] or 0), 4)
_metrics = {
    "tenant_id": TENANT, "total_turns": _total,
    "total_input_tokens": int(_m["in"] or 0), "total_output_tokens": int(_m["out"] or 0),
    "total_tokens": int(_m["tok"] or 0), "estimated_cost_usd": _est_cost,
    "trivial_turns": int(_m["trivial"] or 0),
    "trivial_pct": round(100 * int(_m["trivial"] or 0) / max(_total, 1), 1),
    "distinct_models": len(_dist), "model_distribution": _dist,
    "confirmed_outcomes": int(confirmed),
    "cost_per_outcome_usd": round(_est_cost / confirmed, 4) if confirmed else None,
    "by_tier": _by_tier,
}
_metrics_schema = StructType([
    StructField("id", StringType()), StructField("type", StringType()),
    StructField("tenantId", StringType()),
    StructField("metrics", StructType([
        StructField("tenant_id", StringType()), StructField("total_turns", LongType()),
        StructField("total_input_tokens", LongType()), StructField("total_output_tokens", LongType()),
        StructField("total_tokens", LongType()), StructField("estimated_cost_usd", DoubleType()),
        StructField("trivial_turns", LongType()), StructField("trivial_pct", DoubleType()),
        StructField("distinct_models", LongType()),
        StructField("model_distribution", MapType(StringType(), LongType())),
        StructField("confirmed_outcomes", LongType()), StructField("cost_per_outcome_usd", DoubleType()),
        StructField("by_tier", ArrayType(StructType([
            StructField("complexity_tier", StringType()), StructField("deployment", StringType()),
            StructField("turns", LongType()), StructField("tokens", LongType()),
            StructField("cost", DoubleType())]))),
    ])),
    StructField("computed_at", StringType()),
])
metrics_df = spark.createDataFrame(
    [(f"metrics::{TENANT}", "turn_metrics", TENANT, _metrics, now)], _metrics_schema)
metrics_df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
print(f"Turn-metrics reverse-ETL complete -> {_total} turns, est ${_est_cost}, {len(_by_tier)} tiers")'''

ANALYST_MD = """## 7. LLM analyst — the model *proposes*, the engine *disposes* (provided)

The final, highest-maturity step of the loop (ADR-0010 Layer 2): turn the aggregate
telemetry above into **ranked recommendations** with an **LLM analyst**, safely.

The model **proposes** one optimization card as strict JSON **per detected opportunity**
— here two: the capability-tiered **model-selection** counterfactual (seam `config`) and
the **repeated-node / tool-call-dedup** structural finding (seam `prompt`,
`supervisor.prompty`). Five deterministic **guardrails** then **dispose** each card:
1. **bounded** — the card's seam/target must be on the app's *declared* surface (else reject);
2. **cited** — every card must cite the detector + opportunity id (else reject);
3. **engine computes the saving** — the model's dollar figure is **ignored**; the
   engine-measured saving wins (Section 4b re-pricing for model-selection; the priced
   avoidable duplicate hop for tool-dedup);
4. **apply_mode from the seam** — `config` auto-applies; `prompt`/`code` are staged;
5. **autonomy ceiling from the seam** — `config` L4, `prompt`/`code` L3.

Then we reverse-ETL each accepted card two ways: a `discovered_opportunity` row (the
analyst's native output) **and** a flat `recommendation_card` projection the Power BI
**Discovered Opportunities** page and the Console already read — so the tool-dedup card,
once analyzed, **supersedes** the app-plane "insight (awaiting analysis)" card on the same
`tool-call-dedup` id. The call is **keyless** (Entra token to the app's Azure OpenAI); if
`AOAI_ENDPOINT` is blank or the call fails, the analyst falls back to the deterministic
proposer, so the section always lands guardrailed cards. This mirrors the reusable engine
analyst in `src/app/engine/analyst/llm.py` and `pipeline.analyze` — same prompt, same
parse, same guardrails, one card per detection."""

ANALYST_CODE = '''# ---- 7. LLM analyst: propose -> guardrail -> reverse-ETL (PROVIDED) ----
# Mirrors src/app/engine/analyst/llm.py + guardrails.py (single design, two runtimes).
import json as _json
import requests as _rq

# The declared optimizable surface — kept in lockstep with src/app/engine/seams/catalog.py.
# Guardrail #1 bounds the analyst to exactly these seams/targets.
SURFACE = {"config": ["model-selection"],
           "prompt": ["itinerary_agent.prompty", "supervisor.prompty"],
           "code": ["introduce-model-selector"]}
SEAM_APPLY_MODE = {"config": "auto", "prompt": "staged_change", "code": "staged_change"}
SEAM_CEILING = {"config": "L4", "prompt": "L3", "code": "L3"}
# Which seam/target each opportunity is fixed at — mirrors pipeline.OPPORTUNITY_SEAMS.
OPPORTUNITY_SEAMS = {"opp-modelfit-supervisor": ("config", "model-selection"),
                     "opp-repeated-node": ("prompt", "supervisor.prompty")}

SYSTEM = (
    "You are an optimization analyst for a multi-agent app. Given a detected issue, propose "
    "exactly ONE change as STRICT JSON (no prose, no markdown) with keys:\\n"
    '  seam: one of "config" | "prompt" | "code"\\n'
    "  target: MUST be one of the allowed targets for that seam (given below)\\n"
    "  claimed_saving: number (your best dollar estimate)\\n"
    '  apply_mode: "auto" or "staged_change"\\n'
    '  autonomy_ceiling: "L3" | "L4" | "L5"\\n'
    "  evidence: a list with one object {detector, opportunity_id, traces:[...]}\\n"
    "Cite the detector + opportunity id you were given. Output ONLY the JSON object."
)

# ---- the ENGINE-computed saving for the repeated-node (tool-dedup) opportunity ----
# Turn-grain estimate mirroring engine/projection/tool_dedup.py: a turn whose agent_path
# repeats the same non-supervisor agent back-to-back wastes ~one hop; attribute that
# hop's share of the turn's tokens (total / hop-count), priced under the model it ran on.
_price_map = {r["dep"]: (float(r["in_price"]), float(r["out_price"])) for r in _pricing.collect()}
_td_turns = 0
_td_saving = 0.0
for _r in turns.select("agent_path", "input_tokens", "output_tokens", "model_deployment").collect():
    _parts = [p.strip() for p in str(_r["agent_path"] or "").split(",") if p.strip()]
    if any(_parts[i] == _parts[i + 1] and _parts[i] != "supervisor" for i in range(len(_parts) - 1)):
        _td_turns += 1
        _hops = max(len(_parts), 1)
        _pin, _pout = _price_map.get(_r["model_deployment"], (b_in, b_out))
        _td_saving += ((float(_r["input_tokens"] or 0) * _pin
                        + float(_r["output_tokens"] or 0) * _pout) / _hops) / 1e6
_td_saving = round(_td_saving, 6)

# The detected issues THIS data supports, each with its ENGINE-computed saving (guardrail #3
# makes the engine number authoritative; the analyst may argue but cannot change it). The
# loop below mirrors pipeline.analyze — one card per detection:
#   (1) model-fit counterfactual -> Section 4b re-pricing ($ _saving over _n turns), seam=config
#   (2) repeated-node structural -> the avoidable duplicated hop priced above, seam=prompt (L3)
_detections = [
    {"detector": "counterfactual.model_fit", "kind": "counterfactual", "agent": "supervisor",
     "dimension": "model selection \\u00b7 cost", "opportunity_id": "opp-modelfit-supervisor",
     "scenario": "model-selection", "title": "Capability-tiered model selection (discovered)",
     "evidence": {"turns": _n, "measured_saving_usd": round(_saving, 4)},
     "engine_saving": round(_saving, 6)},
    {"detector": "structural.repeated_node", "kind": "structural", "agent": "find_places",
     "dimension": "workflow efficiency \\u00b7 tool use", "opportunity_id": "opp-repeated-node",
     "scenario": "tool-call-dedup",
     "title": "Redundant tool calls \\u2014 supervisor prompt fix (discovered)",
     "evidence": {"redundant_tool_turns": _td_turns, "estimated_saving_usd": _td_saving},
     "engine_saving": _td_saving},
]


def _analyst_prompt(det):
    return ("Detected issue:\\n"
            f"  detector: {det['detector']}\\n  kind: {det['kind']}\\n  agent: {det['agent']}\\n"
            f"  dimension: {det['dimension']}\\n  opportunity_id: {det['opportunity_id']}\\n"
            f"  evidence: {_json.dumps(det['evidence'])}\\n\\n"
            "Allowed targets by seam:\\n"
            f"  config: {SURFACE['config']}\\n  prompt: {SURFACE['prompt']}\\n  code: {SURFACE['code']}\\n"
            "Sample trace ids you may cite: ['trace-1','trace-2']")


def _aad_token():
    try:
        import notebookutils as _nb
    except Exception:
        import mssparkutils as _nb
    for aud in ("https://cognitiveservices.azure.com", "pbi"):
        try:
            tk = _nb.credentials.getToken(aud)
            if tk:
                return tk
        except Exception:
            pass
    raise RuntimeError("no Entra token for Azure OpenAI")


def _call_llm(system, user):
    url = (f"{AOAI_ENDPOINT.rstrip('/')}/openai/deployments/{AOAI_DEPLOYMENT}"
           f"/chat/completions?api-version={AOAI_API_VERSION}")
    r = _rq.post(url, headers={"Authorization": f"Bearer {_aad_token()}",
                               "Content-Type": "application/json"},
                 json={"messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}, timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_card(text, det):
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    try:
        obj = _json.loads(t[t.find("{"): t.rfind("}") + 1])
    except Exception:
        return None
    return {"agent": det["agent"], "dimension": det["dimension"],
            "seam": str(obj.get("seam", "")), "target": str(obj.get("target", "")),
            "evidence": obj.get("evidence") or [],
            "claimed_saving": float(obj.get("claimed_saving", 0) or 0),
            "apply_mode": str(obj.get("apply_mode", "")),
            "autonomy_ceiling": str(obj.get("autonomy_ceiling", ""))}


def _default_card(det):   # deterministic fallback (engine parity) when the LLM is unavailable
    seam, target = OPPORTUNITY_SEAMS.get(det["opportunity_id"], ("prompt", "supervisor.prompty"))
    return {"agent": det["agent"], "dimension": det["dimension"], "seam": seam,
            "target": target, "claimed_saving": 0.0, "apply_mode": "", "autonomy_ceiling": "",
            "evidence": [{"detector": det["detector"], "opportunity_id": det["opportunity_id"],
                          "traces": ["sample-trace"]}]}


def _guardrail(card, engine_saving):   # the five deterministic rules; returns (normalized|None, why)
    if card["seam"] not in SURFACE:
        return None, f"reject: unknown seam '{card['seam']}'"
    if card["target"] not in SURFACE[card["seam"]]:
        return None, f"reject: target '{card['target']}' off the declared {card['seam']} surface"
    if not card["evidence"]:
        return None, "reject: uncited"
    for e in card["evidence"]:
        if not (e.get("detector") and e.get("opportunity_id") and e.get("traces")):
            return None, "reject: evidence missing detector/opportunity_id/traces"
    return {"agent": card["agent"], "dimension": card["dimension"], "seam": card["seam"],
            "target": card["target"], "saving": engine_saving,
            "apply_mode": SEAM_APPLY_MODE[card["seam"]],
            "autonomy_ceiling": SEAM_CEILING[card["seam"]]}, "accepted (engine-computed saving; LLM $ ignored)"


# propose -> parse -> (fallback) -> guardrail, once PER detected opportunity (pipeline.analyze's loop)
def _propose(det):
    if AOAI_ENDPOINT:
        try:
            return _parse_card(_call_llm(SYSTEM, _analyst_prompt(det)), det) or _default_card(det)
        except Exception as _e:
            print("LLM analyst unavailable, using deterministic fallback:", str(_e)[:160])
            return _default_card(det)
    print("AOAI_ENDPOINT blank -> deterministic fallback proposer for", det["opportunity_id"])
    return _default_card(det)


from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType


# Flat evidence/caveat for the BI cards: the nested `card` object does NOT surface as columns
# over the Fabric mirror, so we project a compact one-line proof + a caveat onto each row.
# Mirrors summarize_card_evidence / card_caveat in
# src/app/services/optimization_recommendations.py so these analyst cards read identically to
# the app-plane cards they supersede (no regression when the notebook runs last).
def _evidence_line(_det):
    _s = _det["scenario"]
    if _s == "model-selection":
        _mm = globals().get("_metrics") or {}
        _md = _mm.get("model_distribution") or {}
        return (f"{_mm.get('total_turns', _n):,} turns \\u00b7 "
                f"{_mm.get('trivial_turns', 0):,} trivial "
                f"({_mm.get('trivial_pct', 0)}%) \\u00b7 {len(_md)} models")
    if _s == "tool-call-dedup":
        return f"{_td_turns:,} redundant tool turns of {_n:,}"
    return ""


def _caveat_line(_det):
    _s = _det["scenario"]
    if _s == "model-selection":
        return ("Counterfactual estimate \\u2014 every captured turn re-priced under the model it "
                "actually ran on vs. the all-premium baseline.")
    if _s == "tool-call-dedup":
        return ("Turn-grain estimate \\u2014 one avoidable duplicated hop per repeated-node turn, "
                "priced under the model it ran on.")
    return ""


_policy_status = {}
if all(_c in policies.columns for _c in ("scenario", "status")):
    _policy_status = {
        _r["scenario"]: _r["status"]
        for _r in policies.select("scenario", "status").collect()
        if _r["scenario"]
    }

_slo = {"slo": 4.0, "min_confidence": 0.7, "min_effect": 0.05, "by": "default"}
if "type" in governance.columns:
    _slo_query = governance.where(F.col("type") == "slo_policy")
    if "timeStamp" in governance.columns:
        _slo_query = _slo_query.orderBy(F.col("timeStamp").desc())
    _slo_docs = _slo_query.limit(1).collect()
    if _slo_docs:
        _slo_doc = _slo_docs[0].asDict()
        for _key in _slo:
            if _slo_doc.get(_key) is not None:
                _slo[_key] = _slo_doc[_key]

_disc_rows, _agent_opp_rows, _rec_rows = [], [], []
_total_spend = sum(float(_n.get("cost") or 0.0) for _n in nodes)
for _rank, _det in enumerate(_detections):
    _norm, _why = _guardrail(_propose(_det), _det["engine_saving"])
    if _norm is None:                          # a bad LLM proposal -> fall back and guardrail that
        print("guardrail rejected the LLM card:", _why)
        _norm, _why = _guardrail(_default_card(_det), _det["engine_saving"])
    print(f"analyst card [{_det['opportunity_id']}]:", _json.dumps(_norm), "->", _why)
    _disc_rows.append(
        (f"disc:{TENANT}:{_det['opportunity_id']}", "discovered_opportunity", TENANT, _rank,
         _det["opportunity_id"], _det["kind"], _norm["agent"], _norm["dimension"],
         _norm["seam"], _norm["target"], float(_norm["saving"]), _norm["apply_mode"],
         _norm["autonomy_ceiling"], _json.dumps(_det["evidence"]), now))
    _scenario_status = (
        _policy_status.get(_det["scenario"], "not_proposed")
        if _norm["apply_mode"] == "auto"
        else "proposed"
    )
    _display_state = (
        "Active" if _scenario_status == "active"
        else "Not applied" if _norm["apply_mode"] == "auto"
        else "Proposed"
    )
    _effect_pct = 100 * float(_norm["saving"]) / _total_spend if _total_spend else 0.0
    _agent_opp_rows.append(
        (f"agentopp::{TENANT}::{_det['opportunity_id']}", "agent_opportunity", TENANT, _rank + 1,
         f"{_norm['seam']} \\u2192 {_norm['target']}", float(_norm["saving"]), round(_effect_pct, 2),
         "Automatic" if _norm["apply_mode"] == "auto" else "Manual",
         _norm["autonomy_ceiling"], "\\u2713" if _effect_pct / 100 >= float(_slo["min_effect"]) else "\\u00d7",
         _display_state, now))
    _card_obj = {"scenario": _det["scenario"], "scenario_id": _det["scenario"], "title": _det["title"],
                 "dimension": _norm["dimension"], "apply_mode": _norm["apply_mode"],
                 "maturity": "discovered by the LLM analyst (engine-guardrailed)",
                 "estimated_saving_usd": float(_norm["saving"]), "status": _scenario_status}
    _rec_rows.append(
        (f"reccard::{TENANT}::{_det['scenario']}", "recommendation_card", TENANT, _det["scenario"],
         _det["scenario"], _rank, f"{_rank + 1} \\u00b7 {_card_obj['title']}", _card_obj["title"],
         _card_obj["dimension"], _card_obj["apply_mode"], _card_obj["status"], _card_obj["maturity"],
         float(_card_obj["estimated_saving_usd"]),
         _evidence_line(_det), _caveat_line(_det), _card_obj, now))

# reverse-ETL: native analyst rows plus report-compatible ranked opportunities, SLO, and recommendations
disc_df = spark.createDataFrame(
    _disc_rows,
    ["id", "type", "tenantId", "rank", "opportunity_id", "kind", "agent", "dimension", "seam",
     "target", "saving", "apply_mode", "autonomy_ceiling", "evidence_json", "computed_at"])

agent_opp_df = spark.createDataFrame(
    _agent_opp_rows,
    ["id", "type", "tenantId", "order", "note", "saving_usd", "saving_pct", "apply_mode",
     "maturity", "method", "status", "computed_at"])

_slo_rows = [
    (f"slometric::{TENANT}::1", "slo_metric", TENANT, 1, "1 \\u00b7 Quality gate (e2e_quality \\u2265)",
     f"{float(_slo['slo']):g}", now),
    (f"slometric::{TENANT}::2", "slo_metric", TENANT, 2, "2 \\u00b7 Min confidence",
     f"{100 * float(_slo['min_confidence']):.1f}%", now),
    (f"slometric::{TENANT}::3", "slo_metric", TENANT, 3, "3 \\u00b7 Min effect",
     f"{100 * float(_slo['min_effect']):.1f}%", now),
    (f"slometric::{TENANT}::4", "slo_metric", TENANT, 4, "4 \\u00b7 Source", str(_slo["by"]), now),
]
slo_df = spark.createDataFrame(
    _slo_rows, ["id", "type", "tenantId", "order", "title", "evidence_line", "computed_at"])

_rec_schema = StructType([
    StructField("id", StringType()), StructField("type", StringType()), StructField("tenantId", StringType()),
    StructField("scenario", StringType()), StructField("scenario_id", StringType()),
    StructField("order", LongType()), StructField("note", StringType()), StructField("title", StringType()),
    StructField("dimension", StringType()), StructField("apply_mode", StringType()),
    StructField("status", StringType()), StructField("maturity", StringType()),
    StructField("estimated_saving_usd", DoubleType()),
    StructField("evidence_line", StringType()), StructField("caveat", StringType()),
    StructField("card", StructType([
        StructField("scenario", StringType()), StructField("scenario_id", StringType()),
        StructField("title", StringType()), StructField("dimension", StringType()),
        StructField("apply_mode", StringType()), StructField("maturity", StringType()),
        StructField("estimated_saving_usd", DoubleType()), StructField("status", StringType())])),
    StructField("computed_at", StringType()),
])
rec_df = spark.createDataFrame(_rec_rows, _rec_schema)

for _df in (disc_df, agent_opp_df, slo_df, rec_df):
    _df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
print(f"Analyst reverse-ETL complete -> {len(_disc_rows)} discovered_opportunity + "
      f"{len(_agent_opp_rows)} agent_opportunity + {len(_slo_rows)} slo_metric + "
      f"{len(_rec_rows)} recommendation_card rows ("
      + ", ".join(f"{d['scenario']} ${d['engine_saving']}" for d in _detections) + ")")'''


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
            code(CHECKPOINT_SETUP),
            md(AGENTPATH_MD), code(AGENTPATH_CODE), code(checkpoint("agent_path")),
            md(METRICS_MD), code(METRICS_CODE), code(checkpoint("turn_metrics")),
            md(SCORECARD_MD), code(SCORECARD_CODE), code(checkpoint("agent_scorecard")),
            md(MEMORY_MD), code(MEMORY_CODE), code(checkpoint("memory_intelligence")),
            md(ANALYST_MD), code(ANALYST_CODE), code(checkpoint("complete")),
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

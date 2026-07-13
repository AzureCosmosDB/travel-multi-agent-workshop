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


def code(text):
    return {"cell_type": "code", "metadata": {}, "outputs": [], "execution_count": None,
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

TODO2_STUB = '''# ---- TODO 2: reverse-ETL — write the insight rows BACK to Cosmos (the pattern) ----
# Write funnel_df, cause_df, kpi_df to the Cosmos OptimizationInsights container using the
# Spark Cosmos connector (Fabric AAD). Use these options and mode("append") with the
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
raise NotImplementedError("Write funnel_df, cause_df, kpi_df to Cosmos with format('cosmos.oltp')")

# for df in (funnel_df, cause_df, kpi_df):
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
for df in (funnel_df, cause_df, kpi_df):
    df.write.format("cosmos.oltp").options(**cosmos_write).mode("append").save()
print("Reverse-ETL complete -> the Power BI Business Impact page will light up.")'''

READ_MD = "## 1. Read the mirror\nThe analytical plane reads the **mirrored** tables through the SQL endpoint — the operational Cosmos account is never touched by analytics."
FUNNEL_MD = "## 2. Build the funnel (provided)\nAggregate turns into per-session stages and attach the friction signal."
TODO1_MD = "## 3. TODO 1 — classify the abandonment cause\nThis is the analytics decision you own (the notebook analog of `classify_turn_tier`)."
BUILD_MD = "## 4. Shape the insight rows (provided)\nFlat rows, one value each, so they mirror cleanly and Power BI needs no session-math."
TODO2_MD = "## 5. TODO 2 — reverse-ETL the insights back to Cosmos\nThe pattern that closes the loop: land Fabric-computed intelligence in the operational store."


def notebook(solution: bool):
    return {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"language_info": {"name": "python"},
                     "kernelspec": {"name": "synapse_pyspark", "display_name": "Synapse PySpark"}},
        "cells": [
            md(INTRO),
            code(PARAMS),
            md(READ_MD), code(READ),
            md(FUNNEL_MD), code(FUNNEL),
            md(TODO1_MD), code(TODO1_SOLUTION if solution else TODO1_STUB),
            md(BUILD_MD), code(BUILD),
            md(TODO2_MD), code(TODO2_SOLUTION if solution else TODO2_STUB),
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

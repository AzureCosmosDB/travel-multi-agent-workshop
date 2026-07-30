"""
Reverse-ETL reference — compute business-impact insights, write them back to Cosmos.

This is the **reference / maintainer** implementation of the reverse-ETL step the
workshop teaches in the Fabric module. The workshop version runs in a **Fabric Spark
notebook** over the mirrored tables; this Python version reuses the *same tested*
app logic (build_*_diagnostic) reading Cosmos directly, so we can populate and verify
``OptimizationInsights`` (and the Power BI page) without a Fabric run.

It flattens the funnel / agent-path / memory diagnostics into small, flat
``OptimizationInsights`` rows (one value per row) so they mirror cleanly to Fabric and
the report reads them with trivial DAX:

  {type:"funnel_stage",      tenantId, stage, stage_order, sessions}
  {type:"abandonment_cause", tenantId, cause, sessions}
  {type:"conversion_kpi",    tenantId, engaged, confirmed, conversion_rate,
                             wasted_pct, tokens_per_outcome, biggest_leak}
  {type:"agent_path_cost",   tenantId, agent_path, turns, total_tokens, avg_tokens}
  {type:"memory_retention",  tenantId, total_memories, superseded_memories, superseded_pct}

Usage (repo root; Cosmos via DefaultAzureCredential):
  python analytics/fabric/compute_insights.py --tenant funnel_demo
  python analytics/fabric/compute_insights.py --tenant analytics_demo
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.disable(logging.INFO)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "02_completed" / "python"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from azure.cosmos import CosmosClient, PartitionKey  # noqa: E402
from azure.identity import DefaultAzureCredential  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

# Resolve the deployed Cosmos endpoint: an already-set COSMOSDB_ENDPOINT (e.g. exported
# by azd) > a .env in the current dir > either workshop tree's python/.env. _APP stays on
# sys.path above because this reference reverse-ETL reuses the app's tested logic.
if not os.environ.get("COSMOSDB_ENDPOINT"):
    for _env_path in [Path.cwd() / ".env", _APP / ".env", _REPO / "01_exercises" / "python" / ".env"]:
        if _env_path.exists():
            load_dotenv(_env_path)
            if os.environ.get("COSMOSDB_ENDPOINT"):
                break

INSIGHTS_CONTAINER = "OptimizationInsights"
_STAGE_ORDER = {"engaged": 1, "searched": 2, "planned": 3, "confirmed": 4}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_insight_rows(tenant_id: str) -> list[dict]:
    """Compute the diagnostics with the tested app logic and flatten to insight rows."""
    from src.app.services import optimization_recommendations as rec

    now = _now()
    rows: list[dict] = []

    cpo = rec.build_cost_per_outcome_diagnostic(tenant_id)["evidence"]
    funnel = cpo["funnel"]
    for stage, sessions in funnel.items():
        rows.append({
            "id": f"funnel::{tenant_id}::{stage}",
            "type": "funnel_stage", "tenantId": tenant_id,
            "stage": stage, "stage_order": _STAGE_ORDER.get(stage, 9),
            "sessions": sessions, "computed_at": now,
        })
    for cause, sessions in cpo["abandonment"].items():
        rows.append({
            "id": f"cause::{tenant_id}::{cause}",
            "type": "abandonment_cause", "tenantId": tenant_id,
            "cause": cause, "sessions": sessions, "computed_at": now,
        })
    engaged = funnel.get("engaged", 0)
    confirmed = funnel.get("confirmed", 0)
    addressable = {k: v for k, v in cpo["abandonment"].items() if k != "no_engagement"}
    biggest = max(addressable, key=addressable.get) if any(addressable.values()) else "none"
    rows.append({
        "id": f"kpi::{tenant_id}",
        "type": "conversion_kpi", "tenantId": tenant_id,
        "engaged": engaged, "confirmed": confirmed,
        "conversion_rate": round(100 * confirmed / max(engaged, 1), 1),
        "wasted_pct": cpo["wasted_pct"],
        "tokens_per_outcome": cpo["tokens_per_outcome"],
        "biggest_leak": biggest, "computed_at": now,
    })

    paths = rec.build_agent_path_diagnostic(tenant_id)["evidence"]["paths"]
    for i, p in enumerate(paths):
        rows.append({
            "id": f"path::{tenant_id}::{i}",
            "type": "agent_path_cost", "tenantId": tenant_id,
            "agent_path": p["agent_path"], "turns": p["turns"],
            "total_tokens": p["total_tokens"], "avg_tokens": p["avg_tokens"],
            "computed_at": now,
        })

    mem = rec.build_memory_retention_recommendation(tenant_id)["evidence"]
    rows.append({
        "id": f"memory::{tenant_id}",
        "type": "memory_retention", "tenantId": tenant_id,
        "total_memories": mem["total_memories"],
        "superseded_memories": mem["superseded_memories"],
        "superseded_pct": mem["superseded_pct"], "computed_at": now,
    })
    return rows


def build_recommendation_rows(tenant_id: str) -> list[dict]:
    """Reverse-ETL the recommendation *cards* + turn metrics the Console reads.

    Closes the loop the workshop teaches: instead of the Optimization Console
    recomputing these aggregations from Cosmos on every request, the analytics
    plane (this script / the Fabric notebook) computes them and writes them back
    to ``OptimizationInsights``, where the app reads them cheaply. The volatile
    policy ``status`` is re-stamped live by the app on read — analysis is
    analytical, but acting (apply/revert) stays operational.
    """
    from src.app.services import optimization_recommendations as rec

    now = _now()
    rows: list[dict] = []
    for order, card in enumerate(rec.build_recommendations(tenant_id)):
        rows.append({
            "id": f"reccard::{tenant_id}::{card.get('scenario')}",
            "type": "recommendation_card", "tenantId": tenant_id,
            "scenario": card.get("scenario"), "scenario_id": card.get("scenario_id"),
            "order": order, "card": card, "computed_at": now,
        })
    rows.append({
        "id": f"metrics::{tenant_id}",
        "type": "turn_metrics", "tenantId": tenant_id,
        "metrics": rec.build_turn_metrics(tenant_id), "computed_at": now,
    })
    return rows


# The applyable optimizations the report can switch between. model-selection is
# measured (counterfactual); the behavior-changing ones are "pending" until a
# before/after measurement is wired up. Scenario-keyed, stored under one reserved
# partition so the report slices on `scenario`, never on tenant.
MEASUREMENT_PARTITION = "_optimizations"
OPTIMIZATION_SCENARIOS = [
    ("model-selection", "Capability-tiered model selection", "counterfactual"),
    ("memory-retention", "Memory retention (prune superseded)", "pending"),
    ("active-trip-city-context", "Active-trip city context", "pending"),
    ("tool-call-dedup", "Redundant tool-call dedup", "pending"),
]


def _policy_status(db, scenario: str) -> str:
    try:
        p = db.get_container_client("OptimizationPolicies").read_item(scenario, scenario)
        return p.get("status", "not_proposed")
    except Exception:  # noqa: BLE001
        return "not_proposed"


def _model_selection_counterfactual(db) -> tuple[int, float, float]:
    """Counterfactual over ALL captured turns (every tenant): price each turn under the
    model it actually ran on vs. the all-premium baseline (gpt-5.1). Returns
    (turns, baseline_cost, actual_cost)."""
    from src.app.services import optimization_recommendations as rec

    pricing = rec.load_pricing()
    baseline = pricing.get("gpt-5.1", {"input": 1.25, "output": 10.00})
    turns = list(db.get_container_client("OptimizationTurns").query_items(
        query="SELECT c.model_deployment, c.model_name, c.input_tokens, c.output_tokens FROM c",
        enable_cross_partition_query=True,
    ))
    actual_cost = baseline_cost = 0.0
    for d in turns:
        i = int(d.get("input_tokens") or 0)
        o = int(d.get("output_tokens") or 0)
        dep = d.get("model_deployment") or d.get("model_name") or "gpt-5.1"
        pin, pout = rec._price_for(pricing, dep)
        actual_cost += (i * pin + o * pout) / 1_000_000
        baseline_cost += (i * baseline["input"] + o * baseline["output"]) / 1_000_000
    return len(turns), baseline_cost, actual_cost


def build_optimization_result_rows(db) -> list[dict]:
    """Measured before/after impact per OPTIMIZATION (scenario), not per tenant.

    Emits one flat ``optimization_result`` row per applyable scenario under a reserved
    ``_optimizations`` partition, so a Power BI slicer on ``scenario`` switches between
    optimizations. model-selection carries a real **counterfactual** measurement (price
    each captured turn under the model it actually ran on vs. the all-premium baseline,
    across all tenants); the behavior-changing scenarios are ``pending`` until a
    before/after measurement is wired up. Keyed by scenario + measured analytically —
    the tenant is never the axis for "which optimization am I looking at".
    """
    now = _now()
    n, baseline_cost, actual_cost = _model_selection_counterfactual(db)
    saving = baseline_cost - actual_cost
    rows: list[dict] = []
    for scenario, title, method in OPTIMIZATION_SCENARIOS:
        row = {
            "id": f"result::{scenario}",
            "type": "optimization_result", "tenantId": MEASUREMENT_PARTITION,
            "scenario": scenario, "title": title, "method": method,
            "status": _policy_status(db, scenario), "computed_at": now,
        }
        if scenario == "model-selection":
            row.update({
                "turns": n,
                "baseline_cost_usd": round(baseline_cost, 4),
                "actual_cost_usd": round(actual_cost, 4),
                "saving_usd": round(saving, 4),
                "saving_pct": round(100 * saving / baseline_cost, 1) if baseline_cost else 0.0,
            })
        else:
            row.update({
                "turns": 0, "baseline_cost_usd": 0.0, "actual_cost_usd": 0.0,
                "saving_usd": 0.0, "saving_pct": 0.0,
                "note": "Measured before/after pending — apply the policy, then measure over the experiment window.",
            })
        rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Reverse-ETL: compute insights -> OptimizationInsights.")
    ap.add_argument("--tenant", required=True)
    args = ap.parse_args()

    endpoint = os.environ["COSMOSDB_ENDPOINT"]
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)
    container = db.create_container_if_not_exists(
        id=INSIGHTS_CONTAINER, partition_key=PartitionKey(path="/tenantId"))

    rows = build_insight_rows(args.tenant)
    for r in rows:
        container.upsert_item(r)
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["type"]] = kinds.get(r["type"], 0) + 1
    print(f"✅ reverse-ETL wrote {len(rows)} insight rows for '{args.tenant}': {kinds}")

    # Also reverse-ETL the recommendation *cards* + turn metrics the Optimization
    # Console reads, so it no longer recomputes aggregations from Cosmos per request.
    rec_rows = build_recommendation_rows(args.tenant)
    for r in rec_rows:
        container.upsert_item(r)
    rec_kinds: dict[str, int] = {}
    for r in rec_rows:
        rec_kinds[r["type"]] = rec_kinds.get(r["type"], 0) + 1
    print(f"✅ reverse-ETL wrote {len(rec_rows)} recommendation rows for '{args.tenant}': {rec_kinds}")

    # Measure before/after impact per OPTIMIZATION (scenario-keyed, all tenants).
    res_rows = build_optimization_result_rows(db)
    for r in res_rows:
        container.upsert_item(r)
    ms = next((r for r in res_rows if r["scenario"] == "model-selection"), {})
    print(f"✅ reverse-ETL wrote {len(res_rows)} optimization_result rows (scenario-keyed): "
          f"model-selection turns={ms.get('turns')} saving=${ms.get('saving_usd')} ({ms.get('saving_pct')}% vs all-premium baseline)")


if __name__ == "__main__":
    main()

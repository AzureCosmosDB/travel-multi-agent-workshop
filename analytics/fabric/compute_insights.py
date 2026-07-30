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

load_dotenv(_APP / ".env")

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


if __name__ == "__main__":
    main()

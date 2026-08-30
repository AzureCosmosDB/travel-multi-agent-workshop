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
  {type:"agent_scorecard",   tenantId, agent, dimension, dim_status, agent_status, cost, cost_share, ...}
  {type:"agent_opportunity", tenantId, order, note, saving_usd, saving_pct, apply_mode, ...}
  {type:"recommendation_card", tenantId, scenario, order, title, status, evidence_line, ...}
  {type:"slo_metric",        tenantId, order, title, evidence_line}
  {type:"memory_retention",  tenantId, total_memories, superseded_memories, superseded_pct}

Usage (repo root; Cosmos via DefaultAzureCredential):
  python analytics/fabric/compute_insights.py --tenant analytics
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


from src.app.services import optimization_insights  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Reverse-ETL: compute insights -> OptimizationInsights.")
    ap.add_argument("--tenant", required=True)
    args = ap.parse_args()

    endpoint = os.environ["COSMOSDB_ENDPOINT"]
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)

    summary = optimization_insights.recompute_insights(args.tenant, db=db)
    print(f"reverse-ETL wrote {summary['rows_written']} OptimizationInsights rows "
          f"for '{args.tenant}': {summary['by_type']}")


if __name__ == "__main__":
    main()

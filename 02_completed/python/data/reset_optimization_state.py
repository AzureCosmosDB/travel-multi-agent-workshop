"""Reset the optimization *state* containers for a clean demo.

Clears the runtime-accumulated optimization state so the analytics portal shows a
consistent, current picture again:

  * ``OptimizationGovernance`` — the human-in-the-loop audit trail (approvals /
    rejections / attestations). Stale ``approved`` decisions from earlier testing make
    cards (e.g. redundant-tool-calls) show as approved; clearing resets the audit trail.
  * ``OptimizationInsights`` — the Fabric reverse-ETL snapshot (turn metrics, funnel,
    scorecard, memory, measured results, and analyst recommendation cards). A stale
    snapshot disagrees with freshly (re)seeded turns; clearing lets the portal's ``auto``
    source fall back to the always-fresh **Live (recompute)** path until the Module-09
    notebook (or ``analytics/fabric/compute_insights.py``) regenerates a new snapshot.

This does NOT touch the raw turn telemetry (``OptimizationTurns`` / ``NodeExecutions`` /
``Debug``) or any app data (Sessions / Messages / Trips / Users / Memories) — reseed those
with ``data/seed_data.py`` + ``analytics/scripts/funnel_seed.py`` and freshen timestamps with the
portal's *Freshen times* button (``POST /optimizations/demo/refresh-times``).

Usage (from the ``python`` dir, with the venv active and ``az login`` done):

    python data/reset_optimization_state.py                 # clear both, all tenants
    python data/reset_optimization_state.py --tenant analytics
    python data/reset_optimization_state.py --containers OptimizationGovernance
"""

from __future__ import annotations

import argparse
import os

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

DEFAULT_TARGETS = ["OptimizationGovernance", "OptimizationInsights"]


def _pk_paths(container) -> list[str]:
    """The container's partition-key field names (e.g. ['tenantId'])."""
    props = container.read()
    pk = props.get("partitionKey", {}) or {}
    return [p.lstrip("/") for p in pk.get("paths", [])]


def _pk_value(doc: dict, paths: list[str]):
    vals = [doc.get(p) for p in paths]
    return vals[0] if len(vals) == 1 else vals


def _clear(container, tenant: str | None) -> int:
    paths = _pk_paths(container)
    if tenant:
        query = "SELECT * FROM c WHERE c.tenantId = @t"
        params = [{"name": "@t", "value": tenant}]
    else:
        query, params = "SELECT * FROM c", None
    docs = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
    deleted = 0
    for d in docs:
        container.delete_item(item=d["id"], partition_key=_pk_value(d, paths))
        deleted += 1
    return deleted


def main() -> None:
    load_dotenv(override=False)
    ap = argparse.ArgumentParser(description="Reset optimization state containers for a clean demo.")
    ap.add_argument("--tenant", default=None, help="scope to one tenant (default: all tenants + global rows)")
    ap.add_argument("--containers", nargs="*", default=DEFAULT_TARGETS,
                    help=f"containers to clear (default: {' '.join(DEFAULT_TARGETS)})")
    args = ap.parse_args()

    endpoint = os.environ.get("COSMOSDB_ENDPOINT")
    if not endpoint:
        raise SystemExit("COSMOSDB_ENDPOINT not set — run from the python/ dir with python/.env present.")
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")

    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)
    scope = f"tenant '{args.tenant}'" if args.tenant else "all tenants"
    print(f"Resetting {', '.join(args.containers)} ({scope}) in {db_name} @ {endpoint}")
    for name in args.containers:
        try:
            n = _clear(db.get_container_client(name), args.tenant)
            print(f"  [cleared] {n} docs from {name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] {name}: {exc}")
    print("Done. The portal's Live (recompute) source is authoritative; regenerate the "
          "reverse-ETL snapshot with the Module-09 notebook when you want it back.")


if __name__ == "__main__":
    main()

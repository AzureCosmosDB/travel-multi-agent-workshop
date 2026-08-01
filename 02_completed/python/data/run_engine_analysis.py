"""
Run the analysis engine — the reverse-ETL producer (ADR-0010 Layer 2/3).

Loads node-grain telemetry, runs the engine (detect -> project -> propose -> guardrail
-> rank), and writes the ranked discovered-opportunity cards to `OptimizationInsights`
(the container the Console / report read).

Two modes:
  --simulate N   run on N simulated turns and print the cards (no services; local proof)
  --from-cosmos  load real node executions from Cosmos and (with --write) upsert insights

Examples:
  python data/run_engine_analysis.py --simulate 1000
  python data/run_engine_analysis.py --from-cosmos --tenant marvel --write
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow `import src.app.engine` when run as a script from python/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.engine import simulation, analyze, policy  # noqa: E402
from src.app.engine.core.schema import NodeExec  # noqa: E402


def declared_surface() -> dict[str, set]:
    """The optimizable surface for the analyst guardrails (seam registry)."""
    return {
        "config": set(policy.DOMAINS.keys()),                 # policy domains
        "prompt": {"supervisor.prompty", "itinerary_agent.prompty"},
        "code": {"introduce-model-selector"},
    }


def _nodes_from_cosmos(tenant_id: str) -> list[NodeExec]:
    from src.app.services import node_executions as ne
    container = ne._get_container()
    if container is None:
        raise SystemExit("Cosmos unavailable — cannot load NodeExecutions")
    out: list[NodeExec] = []
    query = "SELECT * FROM c WHERE c.tenantId = @t"
    for doc in container.query_items(query=query,
                                     parameters=[{"name": "@t", "value": tenant_id}],
                                     enable_cross_partition_query=True):
        for r in doc.get("nodeExecutions", []):
            out.append(NodeExec(
                tenant_id=doc.get("tenantId", ""), user_id=doc.get("userId", ""),
                session_id=doc.get("sessionId", ""), turn_id=doc.get("turnId", ""),
                seq=r.get("seq", 0), agent=r.get("agent", ""),
                model_deployment=r.get("model_deployment", r.get("model_name", "Unknown")),
                input_tokens=r.get("input_tokens", 0), output_tokens=r.get("output_tokens", 0),
                cached_tokens=r.get("cached_tokens", 0), model_name=r.get("model_name", "Unknown"),
            ))
    return out


def _write_insights(tenant_id: str, cards: list[dict]) -> int:
    from src.app.services import azure_cosmos_db as cosmos
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        raise SystemExit("Cosmos unavailable — cannot write OptimizationInsights")
    container = cosmos.database.get_container_client("OptimizationInsights")
    n = 0
    for rank, card in enumerate(cards):
        doc = {"id": f"disc:{tenant_id}:{card['opportunity_id']}",
               "tenantId": tenant_id, "type": "discovered_opportunity",
               "rank": rank, **card}
        container.upsert_item(doc)
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the analysis engine.")
    ap.add_argument("--simulate", type=int, metavar="N", help="run on N simulated turns")
    ap.add_argument("--from-cosmos", action="store_true", help="load real node executions")
    ap.add_argument("--tenant", default="marvel")
    ap.add_argument("--write", action="store_true", help="upsert cards to OptimizationInsights")
    args = ap.parse_args()

    if args.from_cosmos:
        nodes = _nodes_from_cosmos(args.tenant)
        print(f"Loaded {len(nodes)} node executions for tenant '{args.tenant}'")
    else:
        n = args.simulate or 1000
        nodes = simulation.simulate(seed=7, n_turns=n)
        print(f"Simulated {len(nodes)} node executions ({n} turns)")

    cards = analyze(nodes, declared_surface())
    print(f"\nDiscovered {len(cards)} opportunit{'y' if len(cards) == 1 else 'ies'}:\n")
    for c in cards:
        print(json.dumps({k: c[k] for k in
                          ("opportunity_id", "agent", "dimension", "seam", "target",
                           "saving", "apply_mode", "autonomy_ceiling", "kind")}, indent=2))

    if args.write and args.from_cosmos:
        wrote = _write_insights(args.tenant, cards)
        print(f"\nWrote {wrote} discovered-opportunity cards to OptimizationInsights.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

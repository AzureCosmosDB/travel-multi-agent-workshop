"""
Agent Scorecard CLI (ADR-0010 §3 / §6.2, spike B2).

Renders the per-agent x dimension health rollup from node-grain telemetry — the same
`src.app.engine.scorecard` used by the Console / report, printed to the terminal.

Two sources:
  --simulate N                 score N simulated turns (no services; local proof)
  --from-cosmos --tenant T      load real NodeExecutions from Cosmos and score them
      [--session S]             optionally scope to one session

Examples:
  python data/agent_scorecard.py --simulate 1000
  python data/agent_scorecard.py --from-cosmos --tenant e2e-live
  python data/agent_scorecard.py --from-cosmos --tenant marvel --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Allow `import src.app.engine` when run as a script from python/.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.app.engine import scorecard, simulation  # noqa: E402
from src.app.engine.core.schema import NodeExec  # noqa: E402


def _nodes_from_cosmos(tenant_id: str, session_id: str | None) -> list[NodeExec]:
    from src.app.services import node_executions as ne
    container = ne._get_container()
    if container is None:
        raise SystemExit("Cosmos unavailable — cannot load NodeExecutions")
    query = "SELECT * FROM c WHERE c.tenantId = @t"
    params = [{"name": "@t", "value": tenant_id}]
    if session_id:
        query += " AND c.sessionId = @s"
        params.append({"name": "@s", "value": session_id})
    out: list[NodeExec] = []
    for doc in container.query_items(query=query, parameters=params, enable_cross_partition_query=True):
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Render the agent scorecard from node-grain telemetry.")
    ap.add_argument("--simulate", type=int, metavar="N", help="score N simulated turns")
    ap.add_argument("--from-cosmos", action="store_true", help="load real node executions from Cosmos")
    ap.add_argument("--tenant", default="marvel")
    ap.add_argument("--session", default=None, help="scope to one session (with --from-cosmos)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the text report")
    args = ap.parse_args()

    if args.from_cosmos:
        nodes = _nodes_from_cosmos(args.tenant, args.session)
        scope = f"tenant '{args.tenant}'" + (f", session '{args.session}'" if args.session else "")
        print(f"Loaded {len(nodes)} node executions for {scope}\n")
    else:
        n = args.simulate or 1000
        nodes = simulation.simulate(seed=7, n_turns=n)
        print(f"Simulated {len(nodes)} node executions ({n} turns)\n")

    cards = scorecard.build_scorecard(nodes)
    if args.json:
        print(json.dumps([c.to_dict() for c in cards], indent=2))
    else:
        print(scorecard.format_scorecard(cards))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

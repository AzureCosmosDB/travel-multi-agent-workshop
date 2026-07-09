"""
v2 Supervisor-Delegation Routing Evaluation — Travel Assistant (agent_memory_toolkit_v2).

The classic routing eval assumed a graph of specialist *nodes*
(orchestrator -> hotel / dining / activity / itinerary_generator) and asserted
which specialist a request routed to. v2 uses a single **supervisor** ReAct
agent that delegates to sub-agents exposed as **tools**:

    - `find_places`                 -> hotel / activity / dining search (aspects)
    - `create_or_update_itinerary`  -> build/save a day-by-day trip

So on v2, "routing" means *which sub-agent tool the supervisor delegated to*.
This harness drives the real v2 graph, watches `on_tool_start` events for the
sub-agent tools, and compares the delegation against the expected value.

Unlike the classic suite, this runs **fully locally** — no LangSmith account or
`LANGCHAIN_API_KEY` required — matching the analytics initiative's Cosmos-first,
source-pluggable philosophy (ADR-0003). It imports the reference solution from
``02_completed/python`` and needs the MCP server running on :8080.

Usage (from repo root, with the v2 venv active and MCP server running):
    python analytics/evaluation/routing_evaluation_v2.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPLETED_PY = REPO_ROOT / "02_completed" / "python"
sys.path.insert(0, str(COMPLETED_PY))
load_dotenv(str(COMPLETED_PY / ".env"), override=True)
# Local evaluation only — never upload traces.
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from langchain_core.messages import HumanMessage  # noqa: E402

from src.app.travel_agents import setup_agents, build_agent_graph  # noqa: E402
from src.app.services.azure_cosmos_db import initialize_cosmos_client  # noqa: E402

# Sub-agent delegation tools the supervisor can call.
DELEGATE_TOOLS = ("find_places", "create_or_update_itinerary")


async def run_routing(graph, question: str, uid: str) -> dict:
    """Drive one request and record which sub-agent tool(s) the supervisor delegated to."""
    delegates: list[str] = []
    async for event in graph.astream_events(
        {"messages": [HumanMessage(content=question)]},
        config={
            "configurable": {
                "thread_id": f"routeval_{uid}",
                "user_id": f"routeval_user_{uid}",
                "tenant_id": f"routeval_tenant_{uid}",
            }
        },
        version="v2",
    ):
        if event.get("event") == "on_tool_start":
            name = event.get("name")
            if name in DELEGATE_TOOLS and name not in delegates:
                delegates.append(name)

    # The supervisor may call several sub-agents for one request (e.g. find_places
    # to gather options, then create_or_update_itinerary to save the plan). Report
    # the full delegation set; correctness is membership-based (see below).
    actual = delegates[0] if delegates else "supervisor"
    return {"actual_delegate": actual, "all_delegates": delegates}


def correct_delegation(outputs: dict, reference_outputs: dict) -> bool:
    """Correct if the expected sub-agent was delegated to at all.

    Uses membership rather than first-delegate because an itinerary request
    legitimately fans out to find_places first, then create_or_update_itinerary.
    """
    expected = reference_outputs.get("expected_delegate", "")
    if expected == "supervisor":
        return not outputs.get("all_delegates")
    return expected in outputs.get("all_delegates", [])


async def main() -> int:
    print("=" * 64)
    print("v2 SUPERVISOR-DELEGATION ROUTING EVALUATION")
    print("=" * 64)

    initialize_cosmos_client()
    await setup_agents()
    graph = build_agent_graph()

    dataset_path = Path(__file__).parent / "datasets" / "routing_dataset_v2.json"
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    print(f"Loaded {len(dataset)} routing examples\n")

    passed = 0
    for i, example in enumerate(dataset):
        question = example["inputs"]["question"]
        expected = example["outputs"]["expected_delegate"]
        try:
            result = await run_routing(graph, question, f"{i}_{os.urandom(3).hex()}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}] ERROR on {question[:45]!r}: {type(exc).__name__}: {exc}")
            continue
        ok = correct_delegation(result, {"expected_delegate": expected})
        passed += 1 if ok else 0
        print(
            f"[{i}] {'PASS' if ok else 'FAIL'}  expected={expected:<26} "
            f"delegates={result['all_delegates'] or ['(none)']}  q={question[:40]!r}"
        )

    print(f"\n=== v2 routing: {passed}/{len(dataset)} correct delegations ===")
    return 0 if passed == len(dataset) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

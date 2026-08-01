"""
Spike B1 (deterministic half) — node-grain capture proof (ADR-0012 B1).

Claim (ADR-0010): the app *already* receives per-node token usage from the LangGraph
event stream, but aggregates it into a single turn total and discards per-agent
attribution. Grounded in the real code:

  02_completed/python/src/app/travel_agents_api.py  (~lines 1305-1333)
      async for event in workflow.astream_events(...):
          ...
          elif kind == "on_chat_model_end":
              usage = _extract_msg_usage(event["data"]["output"])
              if usage:
                  dbg["input_tokens"]  += usage["input_tokens"]   # <-- SUMMED, per-node lost
                  dbg["output_tokens"] += usage["output_tokens"]
                  dbg["total_tokens"]  += usage["total_tokens"]

This spike replays a representative multi-agent `astream_events` sequence and shows:
  (1) the CURRENT transform yields one turn-level total (today's behavior);
  (2) a NODE-GRAIN transform yields one record per agent execution WITH per-node token
      attribution — the thing turn grain can't give;
  (3) the node-grain records RECONCILE to the same turn total (it's the same data,
      just not discarded) => the change is a pure re-shape, i.e. COST-NEUTRAL.

Pure stdlib, deterministic. `python b1_node_grain_capture.py` (exit 0 = pass).
"""

from __future__ import annotations

from dataclasses import dataclass


# --- Minimal stand-ins for the LangChain AIMessage the stream carries ------------------
class _Msg:
    """Mimics an AIMessage with langchain-core 1.x native usage_metadata."""
    def __init__(self, model_name, input_tokens, output_tokens, cached=0):
        self.usage_metadata = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": {"cache_read": cached},
        }
        self.response_metadata = {"model_name": model_name}


def _extract_msg_usage(msg) -> dict | None:
    """Faithful to travel_agents_api.py::_extract_msg_usage (native usage_metadata path)."""
    if msg is None:
        return None
    usage = getattr(msg, "usage_metadata", None)
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_token_details") or {}
    return {
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
        "cached_tokens": details.get("cache_read", 0) or 0,
        "model_name": (getattr(msg, "response_metadata", {}) or {}).get("model_name", "Unknown"),
    }


def _event(node, msg):
    """Shape of a LangGraph astream_events on_chat_model_end event (node in metadata)."""
    return {"event": "on_chat_model_end",
            "metadata": {"langgraph_node": node},
            "data": {"output": msg}}


# A representative heavy multi-agent turn: supervisor -> find_places -> itinerary.
TURN_EVENTS = [
    _event("supervisor", _Msg("gpt-5.1", 1500, 180, cached=6528)),
    _event("find_places", _Msg("gpt-5.1", 900, 470, cached=0)),
    _event("create_or_update_itinerary", _Msg("gpt-5.1", 1800, 2100, cached=0)),
]


# --- (1) CURRENT behavior: aggregate to one turn total (mirrors the app today) ----------
def current_turn_aggregate(events) -> dict:
    dbg = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    for ev in events:
        if ev["event"] == "on_chat_model_end":
            usage = _extract_msg_usage(ev["data"]["output"])
            if usage:
                dbg["input_tokens"] += usage["input_tokens"]
                dbg["output_tokens"] += usage["output_tokens"]
                dbg["total_tokens"] += usage["total_tokens"]
                dbg["cached_tokens"] += usage["cached_tokens"]
    return dbg


# --- (2) NODE-GRAIN: one record per agent execution, attribution preserved --------------
@dataclass
class NodeRecord:
    agent: str
    model_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_tokens: int


def node_grain_records(events) -> list[NodeRecord]:
    out: list[NodeRecord] = []
    for ev in events:
        if ev["event"] == "on_chat_model_end":
            usage = _extract_msg_usage(ev["data"]["output"])
            if usage:
                out.append(NodeRecord(
                    agent=ev["metadata"]["langgraph_node"],
                    model_name=usage["model_name"],
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    total_tokens=usage["total_tokens"],
                    cached_tokens=usage["cached_tokens"],
                ))
    return out


def run() -> bool:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail):
        results.append((name, cond, detail))

    agg = current_turn_aggregate(TURN_EVENTS)
    nodes = node_grain_records(TURN_EVENTS)

    # (a) node-grain gives one record PER agent with per-node attribution.
    agents = [n.agent for n in nodes]
    check("node-grain: one record per agent execution",
          agents == ["supervisor", "find_places", "create_or_update_itinerary"],
          f"agents={agents}")
    check("node-grain: per-node token attribution present (turn grain lacks this)",
          all(n.output_tokens > 0 for n in nodes)
          and nodes[0].output_tokens != nodes[2].output_tokens,
          "; ".join(f"{n.agent}:{n.input_tokens}/{n.output_tokens}" for n in nodes))

    # (b) RECONCILIATION: node-grain sums == today's turn total (same data, not discarded).
    sums = {
        "input_tokens": sum(n.input_tokens for n in nodes),
        "output_tokens": sum(n.output_tokens for n in nodes),
        "total_tokens": sum(n.total_tokens for n in nodes),
        "cached_tokens": sum(n.cached_tokens for n in nodes),
    }
    check("reconciliation: node-grain sums == current turn aggregate", sums == agg,
          f"node-sum={sums} vs current={agg}")

    # (c) COST-NEUTRAL: derived purely from events the app already receives (no new LLM call).
    check("cost-neutral: pure re-shape of existing on_chat_model_end events",
          len(nodes) == sum(1 for e in TURN_EVENTS if e["event"] == "on_chat_model_end"),
          f"{len(nodes)} node records from {len(TURN_EVENTS)} existing events, 0 new model calls")

    print("=" * 78)
    print("B1 (deterministic half) — node-grain capture proof")
    print("=" * 78)
    all_pass = True
    for name, ok, detail in results:
        all_pass = all_pass and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("-" * 78)
    print("  Per-agent breakdown (what turn grain throws away):")
    for n in nodes:
        print(f"     {n.agent:<28} in={n.input_tokens:<5} out={n.output_tokens:<5} model={n.model_name}")
    print(f"  Turn total (today): {agg}")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - node grain derivable + reconciles + cost-neutral' if all_pass else 'FAILURES'}")
    print("  (Live capture on a real turn deferred until creds available.)")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

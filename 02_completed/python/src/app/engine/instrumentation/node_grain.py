"""
Node-grain capture (ADR-0010, spike B1).

Derive one record per agent execution from the LangGraph `astream_events` stream.
Faithful to the app's real capture site (travel_agents_api.py ~1305-1333), which
today SUMS `on_chat_model_end` usage into a single turn total and discards per-agent
attribution. `node_grain_records` keeps it; `current_turn_aggregate` is the same
rollup for reconciliation.

Pure functions over event dicts — no app dependency — so the streaming path can call
them and this stays unit-testable.
"""

from __future__ import annotations

from typing import Any

from ..core.schema import NodeExec


def extract_msg_usage(msg: Any) -> dict[str, Any] | None:
    """Pull token usage + model from an AIMessage. Mirrors
    travel_agents_api.py::_extract_msg_usage (native usage_metadata path + the
    OpenAI-style nested response_metadata.token_usage fallback)."""
    if msg is None:
        return None
    usage = getattr(msg, "usage_metadata", None)
    if isinstance(usage, dict):
        details = usage.get("input_token_details") or {}
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
        total_t = usage.get("total_tokens", 0) or (input_t + output_t)
        cached_t = details.get("cache_read", 0) or 0
    else:
        meta = getattr(msg, "response_metadata", None) or {}
        token_usage = meta.get("token_usage") or {}
        if not token_usage:
            return None
        input_t = token_usage.get("prompt_tokens", 0) or 0
        output_t = token_usage.get("completion_tokens", 0) or 0
        total_t = token_usage.get("total_tokens", 0) or (input_t + output_t)
        cached_t = (token_usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    meta = getattr(msg, "response_metadata", None) or {}
    return {"input_tokens": input_t, "output_tokens": output_t, "total_tokens": total_t,
            "cached_tokens": cached_t, "model_name": meta.get("model_name", "Unknown")}


def node_from_event(event: dict, *, tenant_id="", user_id="", session_id="", turn_id="") -> NodeExec | None:
    """Build a NodeExec from an `on_chat_model_end` event, or None if it carries no usage."""
    if event.get("event") != "on_chat_model_end":
        return None
    agent = (event.get("metadata") or {}).get("langgraph_node")
    if agent is None:
        return None
    usage = extract_msg_usage((event.get("data") or {}).get("output"))
    if not usage:
        return None
    return NodeExec(
        tenant_id=tenant_id, user_id=user_id, session_id=session_id, turn_id=turn_id,
        seq=0, agent=agent, model_deployment=usage["model_name"],
        input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
        cached_tokens=usage["cached_tokens"], model_name=usage["model_name"],
    )


def node_grain_records(events, **ctx) -> list[NodeExec]:
    """One record per agent execution, seq assigned in stream order."""
    out: list[NodeExec] = []
    for ev in events:
        n = node_from_event(ev, **ctx)
        if n is not None:
            n.seq = len(out)
            out.append(n)
    return out


def current_turn_aggregate(events) -> dict[str, int]:
    """The app's CURRENT rollup (sums usage into one turn total) — for reconciliation."""
    dbg = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    for ev in events:
        if ev.get("event") == "on_chat_model_end":
            usage = extract_msg_usage((ev.get("data") or {}).get("output"))
            if usage:
                for k in dbg:
                    dbg[k] += usage[k]
    return dbg


def reconciles(records: list[NodeExec], aggregate: dict[str, int]) -> bool:
    """True when node-grain sums == the turn aggregate (same data, not discarded)."""
    return {
        "input_tokens": sum(n.input_tokens for n in records),
        "output_tokens": sum(n.output_tokens for n in records),
        "total_tokens": sum(n.total_tokens for n in records),
        "cached_tokens": sum(n.cached_tokens for n in records),
    } == aggregate

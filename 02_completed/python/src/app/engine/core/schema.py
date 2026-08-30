"""Node-grain telemetry schema (ADR-0010) — one record per agent execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


AGENTS = ("supervisor", "find_places", "create_or_update_itinerary")


@dataclass
class NodeExec:
    """One LangGraph node invocation (a sub-agent execution) within a turn."""
    tenant_id: str
    user_id: str
    session_id: str
    turn_id: str
    seq: int
    agent: str
    model_deployment: str
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    tool_calls: int = 0
    recall_used: bool = False
    outcome_link: str | None = None
    model_name: str = "Unknown"
    ts: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["total_tokens"] = self.total_tokens
        return d

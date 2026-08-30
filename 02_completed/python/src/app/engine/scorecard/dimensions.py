"""
Per-agent dimension scorers (ADR-0010 §3 — the agents × dimensions matrix, spike B2).

Each scorer answers one question for one agent from its node-grain executions and
returns a `DimensionScore`. Scorers are registered on the `DIMENSIONS` registry, so
adding a dimension is the same one-line gesture used everywhere in the engine:

    from ..core import Registry
    @DIMENSIONS.register("my_dimension")
    def my_dimension(agent_nodes, all_nodes, pricing): ...

Honesty note (charter): today's node-grain grain captures *agent, model, tokens*.
The three scorers below are fully grounded in that data. The other canonical
dimensions (agent quality, routing effectiveness, tool utilization, memory
effectiveness, business outcomes) need signals node-grain does not yet carry
(LLM-judge scores, agent_path, per-node tool_calls/recall, Trips.status). They are
listed in `PENDING_DIMENSIONS` with the signal each one waits on, so the scorecard
never fabricates a score it cannot measure — and the extension point is obvious.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core import Registry
from ..core.costs import (
    CHEAP_TARGET,
    LOW_COMPLEXITY_OUTPUT,
    PREMIUM_DEPLOYMENTS,
    reprice_saving,
    token_cost,
)
from ..core.schema import NodeExec

DIMENSIONS = Registry("scorecard.dimensions")


@dataclass
class DimensionScore:
    """One agent's health on one dimension. `status` is a triage label, not a grade."""
    dimension: str
    status: str            # "ok" | "watch" | "opportunity" | "n/a"
    headline: str          # one-line, human-readable
    value: float | None = None
    unit: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


# Canonical dimensions that node-grain cannot score yet, and the signal each needs.
PENDING_DIMENSIONS: dict[str, str] = {
    "agent_quality": "LLM-as-judge scores (answer-quality/correctness) per response",
    "routing_effectiveness": "agent_path vs. expected delegation",
    "tool_utilization": "per-node tool-call counts (not captured in node-grain today)",
    "memory_effectiveness": "recall usage + supersession events (MemoryEvent grain)",
    "business_outcomes": "Trips.status linked via the outcome correlation key",
}


@DIMENSIONS.register("cost_efficiency")
def cost_efficiency(agent_nodes: list[NodeExec], all_nodes: list[NodeExec], pricing=None) -> DimensionScore:
    """$ and tokens this agent spends — the agent-path cost concentration signal."""
    cost = sum(token_cost(n.model_deployment, n.input_tokens, n.output_tokens, pricing) for n in agent_nodes)
    total_cost = sum(token_cost(n.model_deployment, n.input_tokens, n.output_tokens, pricing) for n in all_nodes)
    share = (cost / total_cost) if total_cost else 0.0
    turns = len({n.turn_id for n in agent_nodes}) or 1
    tokens = sum(n.total_tokens for n in agent_nodes)
    # A single agent holding the majority of spend is a concentration worth a look.
    status = "watch" if share >= 0.5 else "ok"
    return DimensionScore(
        dimension="cost_efficiency", status=status,
        headline=f"${cost:.4f} ({share*100:.0f}% of turn spend), {tokens/turns:.0f} tok/turn",
        value=round(cost, 6), unit="$/window",
        detail={"cost": round(cost, 6), "cost_share": round(share, 4),
                "tokens": tokens, "tokens_per_turn": round(tokens / turns, 1), "turns": turns},
    )


@DIMENSIONS.register("model_selection")
def model_selection(agent_nodes: list[NodeExec], all_nodes: list[NodeExec], pricing=None) -> DimensionScore:
    """Premium model spent on trivial (low realized-complexity) turns → downgrade saving for model selection."""
    execs = len(agent_nodes) or 1
    candidates = [n for n in agent_nodes
                  if n.model_deployment in PREMIUM_DEPLOYMENTS and n.output_tokens < LOW_COMPLEXITY_OUTPUT]
    saving = sum(max(0.0, reprice_saving(n, CHEAP_TARGET, pricing)) for n in candidates)
    share = len(candidates) / execs
    status = "opportunity" if (share >= 0.2 and saving > 0) else "ok"
    hl = (f"{len(candidates)}/{execs} premium turns with short output (<{LOW_COMPLEXITY_OUTPUT} tok) -> save ${saving:.4f} "
          f"by routing to {CHEAP_TARGET}") if candidates else f"{execs} exec(s), no premium-on-short-output waste"
    return DimensionScore(
        dimension="model_selection", status=status, headline=hl,
        value=round(saving, 6), unit="$/window",
        detail={"downgrade_candidates": len(candidates), "executions": execs,
                "candidate_share": round(share, 4), "target": CHEAP_TARGET,
                "projected_saving": round(saving, 6)},
    )


@DIMENSIONS.register("workflow_efficiency")
def workflow_efficiency(agent_nodes: list[NodeExec], all_nodes: list[NodeExec], pricing=None) -> DimensionScore:
    """Repeated invocation of the same agent within a turn — a redundant-hop signal for redundant tool calls."""
    per_turn: dict[str, int] = {}
    for n in agent_nodes:
        per_turn[n.turn_id] = per_turn.get(n.turn_id, 0) + 1
    turns = len(per_turn) or 1
    repeats = sum(c - 1 for c in per_turn.values() if c > 1)
    repeat_turns = sum(1 for c in per_turn.values() if c > 1)
    repeat_rate = repeat_turns / turns
    status = "opportunity" if repeat_rate >= 0.1 else "ok"
    hl = (f"repeats within a turn in {repeat_turns}/{turns} turns ({repeat_rate*100:.0f}%)"
          if repeats else f"one call per turn across {turns} turns (no redundant hops)")
    return DimensionScore(
        dimension="workflow_efficiency", status=status, headline=hl,
        value=round(repeat_rate, 4), unit="repeat-turn rate",
        detail={"repeat_turns": repeat_turns, "turns": turns, "extra_calls": repeats},
    )

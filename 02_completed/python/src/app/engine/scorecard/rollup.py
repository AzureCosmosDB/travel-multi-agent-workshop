"""
Agent Scorecard rollup (ADR-0010 §3 / §6.2, spike B2).

`build_scorecard` turns a flat list of node-grain executions into one `AgentScorecard`
per agent — each agent scored across every registered dimension (see `dimensions.py`).
This is the "agent health at a glance" surface the Console / report read, and the
per-agent lens the discovered-opportunity cards drill into.

Pure over `NodeExec` — no Cosmos, no LLM — so it unit-tests and runs on simulated or
live data identically. The CLI `data/agent_scorecard.py` renders it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.costs import token_cost
from ..core.schema import NodeExec
from .dimensions import DIMENSIONS, PENDING_DIMENSIONS, DimensionScore

# Worst-first so the render leads with what needs attention.
_STATUS_ORDER = {"opportunity": 0, "watch": 1, "ok": 2, "n/a": 3}


@dataclass
class AgentScorecard:
    agent: str
    executions: int
    turns: int
    cost: float
    cost_share: float
    total_tokens: int
    dimensions: dict[str, DimensionScore] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """The agent's worst dimension status — its triage headline."""
        if not self.dimensions:
            return "n/a"
        return min((d.status for d in self.dimensions.values()), key=lambda s: _STATUS_ORDER.get(s, 9))

    def to_dict(self) -> dict:
        return {
            "agent": self.agent, "status": self.status, "executions": self.executions,
            "turns": self.turns, "cost": round(self.cost, 6), "cost_share": round(self.cost_share, 4),
            "total_tokens": self.total_tokens,
            "dimensions": {k: {"status": v.status, "headline": v.headline, "value": v.value,
                               "unit": v.unit, "detail": v.detail} for k, v in self.dimensions.items()},
            "pending_dimensions": PENDING_DIMENSIONS,
        }


def build_scorecard(nodes: list[NodeExec], *, pricing=None) -> list[AgentScorecard]:
    """One AgentScorecard per agent, each scored across all registered dimensions."""
    by_agent: dict[str, list[NodeExec]] = {}
    for n in nodes:
        by_agent.setdefault(n.agent, []).append(n)

    total_cost = sum(token_cost(n.model_deployment, n.input_tokens, n.output_tokens, pricing) for n in nodes) or 0.0
    cards: list[AgentScorecard] = []
    for agent, agent_nodes in by_agent.items():
        cost = sum(token_cost(n.model_deployment, n.input_tokens, n.output_tokens, pricing) for n in agent_nodes)
        scores = {name: scorer(agent_nodes, nodes, pricing) for name, scorer in DIMENSIONS.items()}
        cards.append(AgentScorecard(
            agent=agent, executions=len(agent_nodes),
            turns=len({n.turn_id for n in agent_nodes}),
            cost=cost, cost_share=(cost / total_cost) if total_cost else 0.0,
            total_tokens=sum(n.total_tokens for n in agent_nodes), dimensions=scores,
        ))
    # Most expensive agent first — where optimization pays off most.
    cards.sort(key=lambda c: -c.cost)
    return cards


_STATUS_GLYPH = {"opportunity": "[!]", "watch": "[~]", "ok": "[ok]", "n/a": "[--]"}


def format_scorecard(cards: list[AgentScorecard]) -> str:
    """Render the scorecard as a readable text report (for the CLI)."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("AGENT SCORECARD  (agent x dimension health from node-grain telemetry)")
    lines.append("=" * 78)
    if not cards:
        lines.append("  (no node-grain executions in scope)")
        return "\n".join(lines)

    total_cost = sum(c.cost for c in cards)
    lines.append(f"  {len(cards)} agent(s), ${total_cost:.4f} total across "
                 f"{sum(c.executions for c in cards)} execution(s)\n")
    for c in cards:
        lines.append(f"  {_STATUS_GLYPH.get(c.status, '')} {c.agent}   "
                     f"${c.cost:.4f} ({c.cost_share*100:.0f}% of spend) | "
                     f"{c.executions} exec / {c.turns} turn | {c.total_tokens} tok")
        for name, d in sorted(c.dimensions.items(), key=lambda kv: _STATUS_ORDER.get(kv[1].status, 9)):
            lines.append(f"        {_STATUS_GLYPH.get(d.status, '')} {name:<22} {d.headline}")
        lines.append("")

    lines.append("-" * 78)
    lines.append("  Not yet scored (needs additional signal - extension points):")
    for dim, signal in PENDING_DIMENSIONS.items():
        lines.append(f"    - {dim:<22} needs {signal}")
    lines.append("=" * 78)
    return "\n".join(lines)

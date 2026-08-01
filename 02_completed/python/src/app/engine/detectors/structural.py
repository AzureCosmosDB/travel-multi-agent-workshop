"""Structural detectors — definitional rules; fire immediately, no thresholds."""

from __future__ import annotations

from .base import DETECTORS, Detection


@DETECTORS.register("structural.repeated_node")
def repeated_node(nodes):
    """A turn that invokes the same non-supervisor agent back-to-back (e.g.
    find_places,find_places) — redundant work. Mirrors the SCEN-005/008 pattern at
    node grain (services/optimization_recommendations.py::_redundant_tool_turns)."""
    by_turn: dict[str, list] = {}
    for n in nodes:
        by_turn.setdefault(n.turn_id, []).append(n)
    hit: list[str] = []
    for tid, turn in by_turn.items():
        seq = [x.agent for x in sorted(turn, key=lambda x: x.seq)]
        if any(seq[i] == seq[i + 1] and seq[i] != "supervisor" for i in range(len(seq) - 1)):
            hit.append(tid)
    if not hit:
        return []
    return [Detection(
        detector="structural.repeated_node", kind="structural",
        dimension="workflow efficiency · tool use", agent="find_places",
        opportunity_id="opp-repeated-node", count=len(hit),
        evidence={"turns": hit[:20], "total": len(hit)},
    )]

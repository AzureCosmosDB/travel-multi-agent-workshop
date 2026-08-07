"""Projection for the redundant-tool-call (repeated-node) optimization.

Mirrors ``detectors.structural.repeated_node`` at *cost* grain: a turn that invokes
the same non-supervisor agent back-to-back (e.g. find_places, find_places) does
redundant work, and the **second** node in each such pair is avoidable spend. The
projection prices those avoidable duplicate nodes as the saving — a deterministic
counterfactual (same class as model-selection), so the analyst's tool-dedup card
carries an engine-computed dollar figure instead of $0.
"""

from __future__ import annotations

from .base import PROJECTIONS, ProjectionResult
from ..core.costs import token_cost, DEFAULT_PRICING


@PROJECTIONS.register("opp-repeated-node")
def project(nodes, pricing=None) -> ProjectionResult:
    """Dedup back-to-back same-(non-supervisor)-agent node pairs within each turn.

    baseline  = every node priced as it ran
    optimized = baseline minus the avoidable duplicate nodes
    saving    = the avoidable duplicates' token cost
    """
    pricing = pricing or DEFAULT_PRICING
    by_turn: dict[str, list] = {}
    for n in nodes:
        by_turn.setdefault(n.turn_id, []).append(n)

    baseline = 0.0
    avoidable = 0.0
    affected = 0
    for turn in by_turn.values():
        seq = sorted(turn, key=lambda x: x.seq)
        for i, n in enumerate(seq):
            baseline += token_cost(n.model_deployment, n.input_tokens, n.output_tokens, pricing)
            if i > 0 and n.agent == seq[i - 1].agent and n.agent != "supervisor":
                avoidable += token_cost(n.model_deployment, n.input_tokens, n.output_tokens, pricing)
                affected += 1

    optimized = baseline - avoidable
    return ProjectionResult(
        round(baseline, 6), round(optimized, 6), round(avoidable, 6),
        round(100 * avoidable / baseline, 2) if baseline else 0.0, affected)

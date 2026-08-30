"""Projection for the model-selection optimization (price-only)."""

from __future__ import annotations

from .base import PROJECTIONS, ProjectionResult
from ..core.costs import (
    token_cost, DEFAULT_PRICING, LOW_COMPLEXITY_OUTPUT,
    PREMIUM_DEPLOYMENTS, CHEAP_TARGET,
)


@PROJECTIONS.register("opp-modelfit-supervisor")
def project(nodes, pricing=None, cheap_target: str = CHEAP_TARGET) -> ProjectionResult:
    """Re-route low-complexity supervisor turns premium -> cheap; recompute total cost."""
    pricing = pricing or DEFAULT_PRICING
    baseline = optimized = 0.0
    affected = 0
    for n in nodes:
        base = token_cost(n.model_deployment, n.input_tokens, n.output_tokens, pricing)
        baseline += base
        if (n.agent == "supervisor" and n.model_deployment in PREMIUM_DEPLOYMENTS
                and n.output_tokens <= LOW_COMPLEXITY_OUTPUT):
            optimized += token_cost(cheap_target, n.input_tokens, n.output_tokens, pricing)
            affected += 1
        else:
            optimized += base
    saving = baseline - optimized
    return ProjectionResult(round(baseline, 6), round(optimized, 6), round(saving, 6),
                            round(100 * saving / baseline, 2) if baseline else 0.0, affected)

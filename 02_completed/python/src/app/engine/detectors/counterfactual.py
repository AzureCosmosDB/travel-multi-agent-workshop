"""Counterfactual detectors — 're-simulate a change; is the saving material?'"""

from __future__ import annotations

from .base import DETECTORS, Detection
from ..core.costs import (
    reprice_saving, LOW_COMPLEXITY_OUTPUT, DEFAULT_PRICING,
    PREMIUM_DEPLOYMENTS, CHEAP_TARGET,
)


@DETECTORS.register("counterfactual.model_fit")
def model_fit(nodes, pricing=None, cheap_target: str = CHEAP_TARGET):
    """Supervisor nodes with LOW realized complexity currently on a premium model.
    Attaches the re-priced saving (materiality) — the projection recovers it exactly."""
    pricing = pricing or DEFAULT_PRICING
    flagged = [n for n in nodes
               if n.agent == "supervisor"
               and n.model_deployment in PREMIUM_DEPLOYMENTS
               and n.output_tokens <= LOW_COMPLEXITY_OUTPUT]
    if not flagged:
        return []
    saving = round(sum(reprice_saving(n, cheap_target, pricing) for n in flagged), 6)
    return [Detection(
        detector="counterfactual.model_fit", kind="counterfactual",
        dimension="model selection · cost", agent="supervisor",
        opportunity_id="opp-modelfit-supervisor", count=len(flagged),
        projected_saving=saving,
        evidence={"low_complexity_premium_nodes": len(flagged), "cheap_target": cheap_target},
    )]

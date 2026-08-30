"""
Shared cost primitives (token pricing + re-pricing).

Pricing is *reference data* (in production it comes from the Configuration container,
mirrored from model-pricing). The table here is an illustrative default keyed by
deployment name; pass a `pricing` dict to override. Units: cost per 1K tokens.
"""

from __future__ import annotations

from .schema import NodeExec


DEFAULT_PRICING = {
    "gpt-5.1":     {"in": 0.042,  "out": 0.336},
    "gpt-5":       {"in": 0.042,  "out": 0.336},
    "gpt-5-mini":  {"in": 0.0084, "out": 0.067},
    "gpt-5-nano":  {"in": 0.0021, "out": 0.017},
}

# Prior/fallback threshold for "low realized complexity" (real detectors derive this
# from the agent's own baseline; kept here as a seed prior).
LOW_COMPLEXITY_OUTPUT = 250

# Which deployments count as "premium" for model-fit, and the cheaper re-route target.
PREMIUM_DEPLOYMENTS = {"gpt-5.1", "gpt-5"}
CHEAP_TARGET = "gpt-5-mini"


def token_cost(deployment: str, input_tokens: int, output_tokens: int, pricing=None) -> float:
    pricing = pricing or DEFAULT_PRICING
    p = pricing.get(deployment)
    if not p:
        return 0.0
    return p["in"] * input_tokens / 1000.0 + p["out"] * output_tokens / 1000.0


def reprice_saving(node: NodeExec, to_deployment: str, pricing=None) -> float:
    """Saving from re-routing a node's model to a cheaper deployment (>=0 when cheaper)."""
    frm = token_cost(node.model_deployment, node.input_tokens, node.output_tokens, pricing)
    to = token_cost(to_deployment, node.input_tokens, node.output_tokens, pricing)
    return frm - to

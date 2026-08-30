"""
Detector base types + registry (ADR-0010 §6, spike B13).

Detectors are the engine's vocabulary. There are three *kinds* — counterfactual,
structural, statistical — and thresholds come from the kind, not from hand-authored
constants.

To ADD A DETECTOR (teaching extension point): create a module in this package and
decorate a function `(nodes) -> Detection | list[Detection] | None`:

    from .base import DETECTORS, Detection

    @DETECTORS.register("structural.my_pattern")
    def my_pattern(nodes): ...

The package __init__ imports detector modules so registration happens on import.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core import Registry

DETECTORS = Registry("detectors")

KINDS = ("counterfactual", "structural", "statistical")


@dataclass
class Detection:
    detector: str                 # registry key
    kind: str                     # one of KINDS
    dimension: str                # the optimization dimension it speaks to
    agent: str                    # the agent it concerns
    opportunity_id: str           # stable id an analyst card / projection references
    count: int = 0                # how many turns/nodes matched
    projected_saving: float = 0.0 # counterfactual detectors attach a materiality figure
    evidence: dict = field(default_factory=dict)


def run_all(nodes, detectors: Registry | None = None) -> list[Detection]:
    """Run every registered detector over the node-grain data."""
    reg = detectors or DETECTORS
    out: list[Detection] = []
    for _key, fn in reg.items():
        res = fn(nodes)
        if not res:
            continue
        out.extend(res if isinstance(res, list) else [res])
    return out

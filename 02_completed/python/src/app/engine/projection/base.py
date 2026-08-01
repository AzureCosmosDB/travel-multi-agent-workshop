"""
Projection base types + registry (ADR-0010 §4.3, spike B8).

Each optimization carries a *projection function*: given the affected telemetry, it
computes baseline vs optimized cost and the saving. Keyed by opportunity id so the
What-If surface and the analyst can look one up.

To ADD A PROJECTION (teaching extension point): create a module here and register
`(nodes, **kw) -> ProjectionResult` under the opportunity id it projects.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import Registry

PROJECTIONS = Registry("projections")


@dataclass
class ProjectionResult:
    baseline: float
    optimized: float
    saving: float
    pct: float
    affected: int


def project(opportunity_id: str, nodes, **kw) -> ProjectionResult | None:
    """Run the registered projection for an opportunity, or None if none registered."""
    if opportunity_id not in PROJECTIONS.keys():
        return None
    return PROJECTIONS.get(opportunity_id)(nodes, **kw)

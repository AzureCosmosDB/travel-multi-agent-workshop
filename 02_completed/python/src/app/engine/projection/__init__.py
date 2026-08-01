"""
Projection functions + What-If (ADR-0010 §4.3).

Public API:
    PROJECTIONS, ProjectionResult, project(opportunity_id, nodes, ...)
    scale_to_monthly, cost_per_outcome, project_business_impact
"""

from .base import PROJECTIONS, ProjectionResult, project  # noqa: F401
from .whatif import scale_to_monthly, cost_per_outcome, project_business_impact  # noqa: F401

from . import model_selection  # noqa: F401,E402  (registers the projection)

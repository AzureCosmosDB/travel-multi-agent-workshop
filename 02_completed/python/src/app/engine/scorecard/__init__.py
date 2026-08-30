"""
Agent Scorecard (ADR-0010 §3 / §6.2, spike B2) — the agent × dimension health surface.

    from src.app.engine import scorecard
    cards = scorecard.build_scorecard(nodes)   # one AgentScorecard per agent
    print(scorecard.format_scorecard(cards))

Add a dimension by registering a scorer in `dimensions.py` — no other wiring needed.
"""

from __future__ import annotations

# Importing the module registers its scorers on the DIMENSIONS registry.
from . import dimensions  # noqa: F401
from .dimensions import DIMENSIONS, PENDING_DIMENSIONS, DimensionScore  # noqa: F401
from .rollup import AgentScorecard, build_scorecard, format_scorecard  # noqa: F401

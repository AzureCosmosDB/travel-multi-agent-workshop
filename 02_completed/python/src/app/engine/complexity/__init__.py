"""
Realized-complexity signal (ADR-0010 §4.1, spike B6).

    from src.app.engine import complexity
    complexity.realized_tier(output_tokens)   # measured: what the turn actually produced
    complexity.keyword_tier(user_text)        # declared: the app's conservative classifier
    complexity.compare_coverage(labeled)      # head-to-head opportunity coverage
"""

from __future__ import annotations

from .realized import (  # noqa: F401
    LabeledTurn,
    compare_coverage,
    keyword_tier,
    realized_tier,
)

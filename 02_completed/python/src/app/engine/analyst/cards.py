"""Recommendation card + decision types (ADR-0010 §9)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RecommendationCard:
    """What the LLM analyst proposes. The engine validates/normalizes it (guardrails)."""
    agent: str
    dimension: str
    seam: str                        # config | prompt | code
    target: str                      # a policy domain / prompt file / code recipe id
    evidence: list[dict]             # each: {detector, opportunity_id, traces:[...]}
    opportunity_id: str
    claimed_saving: float = 0.0      # the LLM's number — engine overrides it
    apply_mode: str = ""             # the LLM's claim — engine overrides from seam
    autonomy_ceiling: str = ""       # the LLM's claim — engine overrides from seam


@dataclass
class Decision:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    normalized: dict | None = None

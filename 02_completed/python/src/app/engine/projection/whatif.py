"""
What-If helpers (ADR-0010 §4.3): usage scaling + cost-per-outcome + the honest
price-only vs behavior-changing split.
"""

from __future__ import annotations


def scale_to_monthly(saving: float, sample_turns: int, turns_per_day: float, days: int = 30) -> float:
    """Project a per-sample saving onto future volume ('at N turns/day ~ $X/month')."""
    if sample_turns <= 0:
        return 0.0
    return round(saving / sample_turns * turns_per_day * days, 4)


def cost_per_outcome(cost: float, outcomes: int) -> float | None:
    return round(cost / outcomes, 6) if outcomes else None


def project_business_impact(kind: str, cost_before: float, cost_after: float, outcomes_before: int) -> dict:
    """price-only: outcomes constant -> cost/outcome projectable.
       behavior-changing: conversion lift is a HYPOTHESIS -> never projected (measure it)."""
    cpo_before = cost_per_outcome(cost_before, outcomes_before)
    if kind == "price-only":
        return {"cpo_before": cpo_before,
                "cpo_after": cost_per_outcome(cost_after, outcomes_before),  # outcomes unchanged
                "projected_conversion_lift": 0.0}
    return {"cpo_before": cpo_before, "cpo_after": None, "projected_conversion_lift": None}

"""
Spike B8 — projection functions + What-If (ADR-0012 B8, guide §4.3).

Proves the generalized projection: for an optimization, compute baseline vs optimized
cost + saving, SCALE it onto future volume ("at N turns/day ~ $X/month"), and report
cost-per-outcome before/after — with the price-only vs behavior-changing split
(price-only conversion held constant and projectable; behavior-changing conversion is a
hypothesis, never projected).

Pure stdlib, deterministic. `python b8_projection_whatif.py` (exit 0 = pass).
"""

from __future__ import annotations

from dataclasses import dataclass


PRICING = {"premium": {"in": 0.042, "out": 0.336}, "cheap": {"in": 0.0084, "out": 0.067}}
LOW_COMPLEXITY_OUTPUT = 250


@dataclass
class Turn:
    agent: str
    deployment: str
    input_tokens: int
    output_tokens: int


def _cost(deployment, tin, tout):
    p = PRICING[deployment]
    return p["in"] * tin / 1000 + p["out"] * tout / 1000


def project_model_selection(turns):
    """Price-only optimization: re-route low-complexity supervisor turns premium->cheap."""
    baseline = optimized = 0.0
    affected = 0
    for t in turns:
        baseline += _cost(t.deployment, t.input_tokens, t.output_tokens)
        if t.agent == "supervisor" and t.deployment == "premium" and t.output_tokens <= LOW_COMPLEXITY_OUTPUT:
            optimized += _cost("cheap", t.input_tokens, t.output_tokens)
            affected += 1
        else:
            optimized += _cost(t.deployment, t.input_tokens, t.output_tokens)
    saving = baseline - optimized
    return {"baseline": round(baseline, 6), "optimized": round(optimized, 6),
            "saving": round(saving, 6), "pct": round(100 * saving / baseline, 2) if baseline else 0,
            "affected": affected}


def scale_to_monthly(saving, sample_turns, turns_per_day, days=30):
    """Project a per-sample saving onto future volume."""
    per_turn = saving / sample_turns
    return round(per_turn * turns_per_day * days, 4)


def cost_per_outcome(cost, outcomes):
    return round(cost / outcomes, 6) if outcomes else None


def project_business_impact(kind, cost_before, cost_after, outcomes_before):
    """price-only: outcomes constant -> cost/outcome projectable.
       behavior-changing: conversion lift is a HYPOTHESIS -> not projected."""
    cpo_before = cost_per_outcome(cost_before, outcomes_before)
    if kind == "price-only":
        cpo_after = cost_per_outcome(cost_after, outcomes_before)  # outcomes unchanged
        return {"cpo_before": cpo_before, "cpo_after": cpo_after, "projected_conversion_lift": 0.0}
    return {"cpo_before": cpo_before, "cpo_after": None, "projected_conversion_lift": None}  # measure, don't project


def run() -> bool:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail):
        results.append((name, cond, detail))

    # Build a small deterministic sample: 100 light supervisor premium turns + 20 heavy.
    turns = [Turn("supervisor", "premium", 1500, 180) for _ in range(100)] + \
            [Turn("find_places", "premium", 900, 460) for _ in range(20)]
    proj = project_model_selection(turns)

    # Ground-truth saving on the 100 light supervisor turns.
    gt = 100 * (_cost("premium", 1500, 180) - _cost("cheap", 1500, 180))
    check("projected saving matches analytic ground truth",
          abs(proj["saving"] - round(gt, 6)) < 1e-6 and proj["affected"] == 100,
          f"saving={proj['saving']} vs gt={round(gt,6)}, affected={proj['affected']}, pct={proj['pct']}%")

    # Usage scaling: 120-turn sample -> project to 5000 turns/day for 30 days.
    monthly = scale_to_monthly(proj["saving"], sample_turns=len(turns), turns_per_day=5000, days=30)
    expected_monthly = round(proj["saving"] / len(turns) * 5000 * 30, 4)
    check("usage-scaling projects saving onto future volume",
          monthly == expected_monthly and monthly > 0,
          f"~${monthly}/month at 5000 turns/day")

    # Business impact — price-only: outcomes constant, cost/outcome drops with cost.
    bi = project_business_impact("price-only", cost_before=proj["baseline"],
                                 cost_after=proj["optimized"], outcomes_before=10)
    check("price-only -> cost/outcome projectable and lower",
          bi["cpo_after"] is not None and bi["cpo_after"] < bi["cpo_before"],
          f"cpo {bi['cpo_before']} -> {bi['cpo_after']}")

    # Business impact — behavior-changing: conversion is a hypothesis, NOT projected.
    bc = project_business_impact("behavior-changing", cost_before=1.0, cost_after=1.0, outcomes_before=10)
    check("behavior-changing -> conversion NOT projected (measured only)",
          bc["projected_conversion_lift"] is None and bc["cpo_after"] is None,
          f"projected_conversion_lift={bc['projected_conversion_lift']}")

    print("=" * 78)
    print("B8 — projection functions + What-If")
    print("=" * 78)
    all_pass = True
    for name, ok, detail in results:
        all_pass = all_pass and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - projection generalizes + scales; honest business-impact split' if all_pass else 'FAILURES'}")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

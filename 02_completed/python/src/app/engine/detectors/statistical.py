"""
Statistical detectors — 'is there a real, non-noisy shift, on enough data?'

Unlike structural rules (definitional, fire immediately) or counterfactual detectors
(re-price a known change), a statistical detector earns the right to fire:

  * **derived threshold** — the bar comes from the agent's OWN baseline (mean/σ), not a
    hand-authored constant;
  * **minimum sample** — silent until there is enough data to have a baseline AND a recent
    window ("suppressed before N");
  * **sequential / stable verdict** — a shift must be *consistent* across the recent window,
    so a single outlier turn cannot trip it (not noisy).

`cost_regression` flags an agent whose recent per-turn output tokens have shifted up
relative to its own earlier baseline (a cost-efficiency regression).
"""

from __future__ import annotations

import math

from .base import DETECTORS, Detection

MIN_SAMPLE = 30          # per window; need baseline + recent, so ≥ 2*MIN_SAMPLE total
Z_THRESHOLD = 3.0        # mean-shift significance (derived, not a token constant)
CONSISTENCY = 0.6        # fraction of the recent window above the baseline median
MIN_EFFECT = 0.20        # practical significance: ≥20% mean increase (guards huge-N drift)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs, mean):
    if len(xs) < 2:
        return 0.0
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1))


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


@DETECTORS.register("statistical.cost_regression")
def cost_regression(nodes):
    """Fire when an agent's recent output-token mean is a statistically significant,
    *consistent* increase over its earlier baseline — on enough data."""
    by_agent: dict[str, list] = {}
    for n in nodes:
        by_agent.setdefault(n.agent, []).append(n)

    out: list[Detection] = []
    for agent, agent_nodes in by_agent.items():
        # Preserve arrival order (turn ordering) so "earlier vs recent" is meaningful.
        series = [n.output_tokens for n in sorted(agent_nodes, key=lambda x: (x.turn_id, x.seq))]
        if len(series) < 2 * MIN_SAMPLE:            # suppressed before N
            continue
        cut = len(series) // 2
        baseline, recent = series[:cut], series[cut:]
        b_mean, r_mean = _mean(baseline), _mean(recent)
        b_std = _std(baseline, b_mean)
        if b_std == 0:
            continue
        se = b_std / math.sqrt(len(recent))         # standard error of the recent mean
        z = (r_mean - b_mean) / se if se else 0.0
        effect = (r_mean - b_mean) / b_mean if b_mean else 0.0
        consistent = sum(1 for x in recent if x > _median(baseline)) / len(recent)
        # significant (z) AND practically material (effect) AND stable (consistency)
        if z >= Z_THRESHOLD and effect >= MIN_EFFECT and consistent >= CONSISTENCY:
            out.append(Detection(
                detector="statistical.cost_regression", kind="statistical",
                dimension="cost efficiency", agent=agent,
                opportunity_id=f"opp-cost-regression-{agent}", count=len(recent),
                evidence={"baseline_mean": round(b_mean, 1), "recent_mean": round(r_mean, 1),
                          "z": round(z, 2), "effect": round(effect, 3),
                          "consistency": round(consistent, 2),
                          "n_baseline": len(baseline), "n_recent": len(recent)},
            ))
    return out

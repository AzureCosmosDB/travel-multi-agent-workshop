"""
Autonomy guard (ADR-0010 §7.1/§8, spike B16).

After an auto-applied CONFIG optimization, observe outcomes, form a verdict against the
predicted saving + prior baseline, and AUTO-REVERT on an adverse/insufficient result —
with an audit trail. Prompt/code seams are human-governed: the guard flags, never
auto-reverts. A dwell gate suppresses a verdict below a minimum sample.
"""

from __future__ import annotations

from dataclasses import dataclass, field


MIN_SAMPLE = 30          # derived elsewhere (power/CI); a fixed seed prior here
MATERIALITY = 0.05       # >=5% improvement to count as "confirmed"


@dataclass
class Policy:
    scenario: str
    seam: str                       # config | prompt | code
    status: str = "active"
    audit: list[dict] = field(default_factory=list)

    def _log(self, action: str, by: str):
        self.audit.append({"action": action, "by": by})


@dataclass
class Observation:
    n: int
    baseline_cost_per_outcome: float
    measured_cost_per_outcome: float
    predicted_cost_per_outcome: float


def verdict(obs: Observation) -> str:
    """observing | confirmed | insufficient | adverse."""
    if obs.n < MIN_SAMPLE:
        return "observing"
    if obs.measured_cost_per_outcome > obs.baseline_cost_per_outcome:
        return "adverse"
    improvement = (obs.baseline_cost_per_outcome - obs.measured_cost_per_outcome) / obs.baseline_cost_per_outcome
    return "confirmed" if improvement >= MATERIALITY else "insufficient"


def guard(policy: Policy, obs: Observation) -> tuple[str, str]:
    """Run measure -> verdict -> act. Returns (verdict, action)."""
    v = verdict(obs)
    if v == "observing":
        return v, "hold (below min sample)"
    if v == "confirmed":
        return v, "keep"
    # adverse / insufficient -> revert, but autonomously ONLY for the config seam.
    if policy.seam == "config":
        policy.status = "reverted"
        policy._log("auto-revert", by="autonomy-guard")
        return v, "auto-reverted (config seam)"
    policy._log("flag-for-human-revert", by="autonomy-guard")
    return v, "flagged for human revert (non-config seam)"

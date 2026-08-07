"""
Spike B16 — the autonomy guard: measure -> verdict -> auto-revert (ADR-0012 B16, guide §7.1).

Proves the L4 safety loop for a CONFIG-seam optimization: after auto-applying a policy,
the engine observes outcomes, forms a verdict against the predicted saving + prior
baseline, and AUTO-REVERTS on an adverse/insufficient result — with an audit trail —
while refusing to auto-revert a prompt/code seam (human-governed).

Also proves the dwell gate: no verdict until a minimum sample is reached (observing).

Pure stdlib, deterministic. `python b16_autonomy_guard.py` (exit 0 = pass).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MIN_SAMPLE = 30          # derived elsewhere; fixed here for the spike
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
    n: int                          # post-apply sample count
    baseline_cost_per_outcome: float
    measured_cost_per_outcome: float
    predicted_cost_per_outcome: float


def verdict(obs: Observation) -> str:
    """confirmed | insufficient | adverse | observing."""
    if obs.n < MIN_SAMPLE:
        return "observing"
    improvement = (obs.baseline_cost_per_outcome - obs.measured_cost_per_outcome) / obs.baseline_cost_per_outcome
    if obs.measured_cost_per_outcome > obs.baseline_cost_per_outcome:
        return "adverse"            # got worse than before
    if improvement < MATERIALITY:
        return "insufficient"       # better, but not enough to keep
    return "confirmed"


def guard(policy: Policy, obs: Observation) -> tuple[str, str]:
    """Run the measure->verdict->act loop. Returns (verdict, action)."""
    v = verdict(obs)
    if v == "observing":
        return v, "hold (below min sample)"
    if v == "confirmed":
        return v, "keep"
    # adverse or insufficient -> revert, but ONLY autonomously for the config seam.
    if policy.seam == "config":
        policy.status = "reverted"
        policy._log("auto-revert", by="autonomy-guard")
        return v, "auto-reverted (config seam)"
    # prompt/code -> human-governed; the guard recommends, never auto-reverts.
    policy._log("flag-for-human-revert", by="autonomy-guard")
    return v, "flagged for human revert (non-config seam)"


def run() -> bool:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail):
        results.append((name, cond, detail))

    # 1. confirmed -> keep
    p1 = Policy("model-selection", "config")
    v, a = guard(p1, Observation(n=200, baseline_cost_per_outcome=1.00,
                                 measured_cost_per_outcome=0.80, predicted_cost_per_outcome=0.82))
    check("confirmed verdict keeps the policy", v == "confirmed" and a == "keep" and p1.status == "active",
          f"verdict={v}, action={a}, status={p1.status}")

    # 2. adverse -> auto-revert (config) with audit
    p2 = Policy("model-selection", "config")
    v, a = guard(p2, Observation(n=200, baseline_cost_per_outcome=1.00,
                                 measured_cost_per_outcome=1.20, predicted_cost_per_outcome=0.82))
    check("adverse -> auto-revert (config) + audit",
          v == "adverse" and p2.status == "reverted"
          and any(e["action"] == "auto-revert" for e in p2.audit),
          f"verdict={v}, status={p2.status}, audit={p2.audit}")

    # 3. insufficient -> auto-revert (config)
    p3 = Policy("memory-retention", "config")
    v, a = guard(p3, Observation(n=200, baseline_cost_per_outcome=1.00,
                                 measured_cost_per_outcome=0.98, predicted_cost_per_outcome=0.90))
    check("insufficient improvement -> reverted", v == "insufficient" and p3.status == "reverted",
          f"verdict={v}, status={p3.status}")

    # 4. dwell gate: below min sample -> observing, no action
    p4 = Policy("model-selection", "config")
    v, a = guard(p4, Observation(n=5, baseline_cost_per_outcome=1.00,
                                 measured_cost_per_outcome=2.00, predicted_cost_per_outcome=0.82))
    check("below min sample -> observing (no premature verdict)",
          v == "observing" and p4.status == "active", f"verdict={v}, status={p4.status}")

    # 5. prompt/code seam adverse -> NOT auto-reverted (human-governed)
    p5 = Policy("prompt-fix", "prompt")
    v, a = guard(p5, Observation(n=200, baseline_cost_per_outcome=1.00,
                                 measured_cost_per_outcome=1.30, predicted_cost_per_outcome=0.90))
    check("non-config adverse -> flagged, NOT auto-reverted",
          v == "adverse" and p5.status == "active" and "flagged" in a
          and any(e["action"] == "flag-for-human-revert" for e in p5.audit),
          f"verdict={v}, status={p5.status}, action={a}")

    print("=" * 78)
    print("B16 — autonomy guard (measure -> verdict -> auto-revert)")
    print("=" * 78)
    all_pass = True
    for name, ok, detail in results:
        all_pass = all_pass and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - safe auto-revert on config; human-gated elsewhere' if all_pass else 'FAILURES'}")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

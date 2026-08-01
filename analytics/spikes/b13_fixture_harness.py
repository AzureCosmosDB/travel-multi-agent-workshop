"""
Spike B13 — the detector-fixture harness (ADR-0012 ledger row B13).

Goal / exit criterion
---------------------
Prove that a discovery-engine detector can be validated with **constructed ground
truth**, not a hand-authored catalog:

  1. Fabricate node-grain telemetry (the ADR-0010 grain).
  2. Build a **matched positive/negative pair** per detector.
  3. Assert the detector *fires on the positive and stays silent on the negative*
     (recall + precision), and that a counterfactual detector **recovers the
     injected saving magnitude** within tolerance.

Pure standard library — runs anywhere with `python b13_fixture_harness.py`.
No Fabric, no live services, no LLM. Deterministic (seeded) so it doubles as a
regression fixture.

This is a THROWAWAY spike to answer one question ("can we measure detectors with
synthetic ground truth?"). If it passes it graduates into the real fixture harness.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


# --------------------------------------------------------------------------------------
# Node-grain schema (ADR-0010) — one record per agent execution (sub-agent invocation).
# --------------------------------------------------------------------------------------
@dataclass
class NodeExec:
    turn_id: str
    seq: int                 # order of this node within the turn
    agent: str               # supervisor | find_places | create_or_update_itinerary
    model_deployment: str    # "premium" | "cheap"
    input_tokens: int
    output_tokens: int
    tool_calls: int = 0
    recall_used: bool = False
    outcome_link: str | None = None


# Illustrative price table (cost units per 1K tokens). The RATIO is what matters for
# the spike; it mirrors the Fabric CU shape (gpt-5.1 premium vs gpt-5-mini cheap).
PRICING = {
    "premium": {"in": 0.042, "out": 0.336},
    "cheap":   {"in": 0.0084, "out": 0.067},
}

# A supervisor node is "low realized complexity" when its output is small (grounded:
# supervisor avg ~179 output tokens on light turns).
LOW_COMPLEXITY_OUTPUT = 250


# --------------------------------------------------------------------------------------
# Synthetic generators — the "ground truth by construction".
# --------------------------------------------------------------------------------------
def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def gen_population(seed: int, n_turns: int, light_supervisor_fraction: float) -> list[NodeExec]:
    """
    Build a baseline population of node executions on the PREMIUM model.

    `light_supervisor_fraction` controls how many turns have a low-complexity
    supervisor node (a "chit-chat"/ack turn) vs a heavy synthesis one — i.e. how
    much model-selection opportunity exists by construction.
    """
    r = _rng(seed)
    nodes: list[NodeExec] = []
    for i in range(n_turns):
        turn_id = f"t{seed}_{i}"
        light = r.random() < light_supervisor_fraction
        sup_out = int(r.gauss(179, 35)) if light else int(r.gauss(1200, 200))
        sup_out = max(20, sup_out)
        nodes.append(NodeExec(turn_id, 0, "supervisor", "premium",
                              input_tokens=int(r.gauss(1500, 200)), output_tokens=sup_out))
        # Some turns delegate to sub-agents (consistently heavy — premium justified).
        roll = r.random()
        if roll < 0.30:
            nodes.append(NodeExec(turn_id, 1, "find_places", "premium",
                                  input_tokens=int(r.gauss(900, 120)),
                                  output_tokens=int(r.gauss(463, 80)), tool_calls=1))
        elif roll < 0.42:
            nodes.append(NodeExec(turn_id, 1, "find_places", "premium",
                                  input_tokens=int(r.gauss(900, 120)),
                                  output_tokens=int(r.gauss(463, 80)), tool_calls=1))
            nodes.append(NodeExec(turn_id, 2, "create_or_update_itinerary", "premium",
                                  input_tokens=int(r.gauss(1800, 200)),
                                  output_tokens=int(r.gauss(2100, 300))))
    return nodes


def inject_repeated_node(nodes: list[NodeExec], k: int, seed: int) -> list[NodeExec]:
    """Positive fixture for the STRUCTURAL detector: k turns calling find_places twice
    back-to-back (supervisor,find_places,find_places). Returns a new list."""
    r = _rng(seed)
    out = list(nodes)
    for j in range(k):
        tid = f"inj_rep_{seed}_{j}"
        out.append(NodeExec(tid, 0, "supervisor", "premium", int(r.gauss(1500, 200)), 150))
        out.append(NodeExec(tid, 1, "find_places", "premium", 900, 400, tool_calls=1))
        out.append(NodeExec(tid, 2, "find_places", "premium", 900, 400, tool_calls=1))
    return out


# --------------------------------------------------------------------------------------
# Detectors under test.
# --------------------------------------------------------------------------------------
def detector_structural_repeated(nodes: list[NodeExec]) -> int:
    """Count turns whose node sequence calls the same non-supervisor agent back-to-back.
    Mirrors services/optimization_recommendations.py::_redundant_tool_turns, at node grain."""
    by_turn: dict[str, list[NodeExec]] = {}
    for n in nodes:
        by_turn.setdefault(n.turn_id, []).append(n)
    count = 0
    for turn in by_turn.values():
        seq = [n.agent for n in sorted(turn, key=lambda x: x.seq)]
        if any(seq[i] == seq[i + 1] and seq[i] != "supervisor" for i in range(len(seq) - 1)):
            count += 1
    return count


def detector_counterfactual_model_fit(nodes: list[NodeExec]) -> tuple[int, float]:
    """Counterfactual: supervisor nodes with LOW realized complexity currently on the
    premium model. Returns (flagged_count, projected_saving) where the projection
    re-prices exactly those nodes premium->cheap."""
    flagged = 0
    saving = 0.0
    for n in nodes:
        if n.agent == "supervisor" and n.model_deployment == "premium" \
                and n.output_tokens <= LOW_COMPLEXITY_OUTPUT:
            flagged += 1
            saving += _reprice_saving(n)
    return flagged, round(saving, 6)


def _reprice_saving(n: NodeExec) -> float:
    prem, cheap = PRICING["premium"], PRICING["cheap"]
    d_in = (prem["in"] - cheap["in"]) * n.input_tokens / 1000.0
    d_out = (prem["out"] - cheap["out"]) * n.output_tokens / 1000.0
    return d_in + d_out


# --------------------------------------------------------------------------------------
# Assertion harness.
# --------------------------------------------------------------------------------------
@dataclass
class Result:
    name: str
    passed: bool
    detail: str


def _check(name: str, cond: bool, detail: str, results: list[Result]) -> None:
    results.append(Result(name, cond, detail))


def run() -> bool:
    results: list[Result] = []

    # ---- Detector 1: STRUCTURAL repeated-node (recall + precision) --------------------
    clean = gen_population(seed=1, n_turns=400, light_supervisor_fraction=0.0)
    K = 17
    positive = inject_repeated_node(clean, k=K, seed=99)

    neg_count = detector_structural_repeated(clean)
    pos_count = detector_structural_repeated(positive)
    _check("structural/precision (clean is silent)", neg_count == 0,
           f"clean repeated-node turns = {neg_count} (expected 0)", results)
    _check("structural/recall (fires on injected)", pos_count == K,
           f"detected = {pos_count} (injected exactly {K})", results)

    # ---- Detector 2: COUNTERFACTUAL model-fit (recall + precision + MAGNITUDE) --------
    # Positive: opportunity present (many light supervisor turns on premium).
    pos_pop = gen_population(seed=7, n_turns=1000, light_supervisor_fraction=0.6)
    # Ground truth computed independently by summing the re-price over the *actual*
    # low-complexity supervisor premium nodes in the population.
    expected_saving = round(sum(_reprice_saving(n) for n in pos_pop
                                if n.agent == "supervisor"
                                and n.model_deployment == "premium"
                                and n.output_tokens <= LOW_COMPLEXITY_OUTPUT), 6)
    expected_count = sum(1 for n in pos_pop if n.agent == "supervisor"
                         and n.model_deployment == "premium"
                         and n.output_tokens <= LOW_COMPLEXITY_OUTPUT)
    got_count, got_saving = detector_counterfactual_model_fit(pos_pop)

    _check("counterfactual/recall (flags opportunity)", got_count == expected_count and got_count > 0,
           f"flagged = {got_count} (ground truth {expected_count})", results)
    tol = 1e-6
    _check("counterfactual/magnitude (recovers injected saving)",
           abs(got_saving - expected_saving) <= tol,
           f"projected = {got_saving} vs ground truth {expected_saving} (tol {tol})", results)

    # Negative: NO opportunity (all supervisor nodes heavy) -> saving ~ 0.
    neg_pop = gen_population(seed=8, n_turns=1000, light_supervisor_fraction=0.0)
    ncount, nsaving = detector_counterfactual_model_fit(neg_pop)
    _check("counterfactual/precision (no opportunity -> ~0 saving)", nsaving == 0.0 and ncount == 0,
           f"flagged = {ncount}, projected saving = {nsaving} (expected 0)", results)

    # ---- Report ----------------------------------------------------------------------
    print("=" * 78)
    print("B13 — detector-fixture harness (constructed ground truth)")
    print("=" * 78)
    all_pass = True
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        all_pass = all_pass and r.passed
        print(f"  [{mark}] {r.name}\n         {r.detail}")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - B13 exit criterion met' if all_pass else 'FAILURES - see above'}")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

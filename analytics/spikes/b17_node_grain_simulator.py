"""
Spike B17 — node-grain traffic simulator (ADR-0012 B17, guide §11/§12.1).

Proves we can fabricate **agent-structured node executions** with realistic
distributions and NO LLM — fixing the "36% of turns have no agent structure" gap
and giving the fixture-first / $0 attendee path its data.

Asserts: 0% missing agent structure; empirical path mix ~ configured weights;
per-agent token means in expected ranges; reproducible (seeded).

Pure stdlib, deterministic. `python b17_node_grain_simulator.py` (exit 0 = pass).
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class NodeExec:
    turn_id: str
    seq: int
    agent: str
    model_deployment: str
    input_tokens: int
    output_tokens: int


PATHS = {
    "supervisor": 0.55,
    "supervisor,find_places": 0.30,
    "supervisor,find_places,create_or_update_itinerary": 0.15,
}

TOKEN_PROFILE = {   # (mean_out, sd_out)
    "supervisor": (179, 35),
    "find_places": (463, 80),
    "create_or_update_itinerary": (2100, 300),
}


def _pick_path(r: random.Random) -> list[str]:
    x = r.random()
    cum = 0.0
    for path, w in PATHS.items():
        cum += w
        if x <= cum:
            return path.split(",")
    return ["supervisor"]


def simulate(seed: int, n_turns: int) -> list[list[NodeExec]]:
    r = random.Random(seed)
    turns: list[list[NodeExec]] = []
    for i in range(n_turns):
        agents = _pick_path(r)
        turn = []
        for seq, agent in enumerate(agents):
            mo, so = TOKEN_PROFILE[agent]
            turn.append(NodeExec(f"t{seed}_{i}", seq, agent, "premium",
                                 input_tokens=max(50, int(r.gauss(1200, 200))),
                                 output_tokens=max(10, int(r.gauss(mo, so)))))
        turns.append(turn)
    return turns


def _path_str(turn):
    return ",".join(n.agent for n in sorted(turn, key=lambda x: x.seq))


def run() -> bool:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail):
        results.append((name, cond, detail))

    N = 20000
    turns = simulate(seed=42, n_turns=N)

    # 1. 0% missing agent structure (every turn has node-grain agents).
    missing = sum(1 for t in turns if not t)
    check("0% missing agent structure (fixes the ~36% gap)", missing == 0,
          f"missing={missing}/{N}")

    # 2. empirical path mix ~ configured weights (within 2%).
    counts = {p: 0 for p in PATHS}
    for t in turns:
        counts[_path_str(t)] = counts.get(_path_str(t), 0) + 1
    ok_mix = True
    detail = []
    for p, w in PATHS.items():
        emp = counts.get(p, 0) / N
        detail.append(f"{p.count(',')+1}-node={emp:.3f}(~{w})")
        ok_mix = ok_mix and abs(emp - w) < 0.02
    check("path mix matches configured weights (±2%)", ok_mix, "; ".join(detail))

    # 3. per-agent output-token means within ±10% of the profile.
    sums = {a: [0, 0] for a in TOKEN_PROFILE}
    for t in turns:
        for n in t:
            sums[n.agent][0] += n.output_tokens
            sums[n.agent][1] += 1
    ok_tok = True
    tdetail = []
    for a, (mean_out, _) in TOKEN_PROFILE.items():
        emp = sums[a][0] / sums[a][1]
        tdetail.append(f"{a}={emp:.0f}(~{mean_out})")
        ok_tok = ok_tok and abs(emp - mean_out) / mean_out < 0.10
    check("per-agent token means within ±10% of profile", ok_tok, "; ".join(tdetail))

    # 4. reproducible (same seed -> identical output).
    again = simulate(seed=42, n_turns=100)
    first = simulate(seed=42, n_turns=100)
    same = all(a[i].output_tokens == b[i].output_tokens
               for a, b in zip(again, first) for i in range(len(a)))
    check("reproducible (seeded)", same, "identical on re-run" if same else "non-deterministic!")

    print("=" * 78)
    print("B17 — node-grain traffic simulator")
    print("=" * 78)
    all_pass = True
    for name, ok, detail in results:
        all_pass = all_pass and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - agent-structured synthetic telemetry, no LLM, reproducible' if all_pass else 'FAILURES'}")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

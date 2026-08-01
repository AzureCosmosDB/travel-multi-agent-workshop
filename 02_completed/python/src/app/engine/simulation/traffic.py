"""
Agent-structured traffic simulator (ADR-0010 §11/§12.1, spike B17).

Fabricates node-grain executions with realistic distributions and NO LLM — fixes the
"turns with no agent structure" gap and feeds the fixture-first / $0 path. Returns a
flat list[NodeExec] ready for detectors / projection.
"""

from __future__ import annotations

import random

from ..core.schema import NodeExec


DEFAULT_PATHS = {
    "supervisor": 0.55,
    "supervisor,find_places": 0.30,
    "supervisor,find_places,create_or_update_itinerary": 0.15,
}

TOKEN_PROFILE = {  # (mean_out, sd_out)
    "supervisor": (179, 35),
    "find_places": (463, 80),
    "create_or_update_itinerary": (2100, 300),
}


def _pick_path(r: random.Random, paths) -> list[str]:
    x, cum = r.random(), 0.0
    for path, w in paths.items():
        cum += w
        if x <= cum:
            return path.split(",")
    return ["supervisor"]


def simulate(seed: int, n_turns: int, *, paths=None, deployment: str = "gpt-5.1",
             tenant: str = "demo", user: str = "sim", n_sessions: int = 50) -> list[NodeExec]:
    paths = paths or DEFAULT_PATHS
    r = random.Random(seed)
    out: list[NodeExec] = []
    for i in range(n_turns):
        agents = _pick_path(r, paths)
        turn_id, session_id = f"t{seed}_{i}", f"s{i % n_sessions}"
        for seq, agent in enumerate(agents):
            mo, so = TOKEN_PROFILE[agent]
            out.append(NodeExec(
                tenant_id=tenant, user_id=user, session_id=session_id, turn_id=turn_id,
                seq=seq, agent=agent, model_deployment=deployment,
                input_tokens=max(50, int(r.gauss(1200, 200))),
                output_tokens=max(10, int(r.gauss(mo, so))),
                model_name=deployment,
            ))
    return out

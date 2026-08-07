"""
Live B7 (quality half): does a REAL LLM analyst produce guardrail-passing cards?

For each detected opportunity we ask the app's Azure OpenAI model (keyless / Entra) to
PROPOSE a recommendation card as JSON, then run it through the engine's deterministic
guardrails. Measures: acceptance (bounded + cited) and whether the engine overrides the
LLM's self-reported dollar figure (the anti-hallucination guardrail on real output).

Run:  cd 02_completed/python ; ../.venv-travel/Scripts/python.exe data/verify_analyst_live.py
"""

from __future__ import annotations

import os
import sys

_PYDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PYDIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PYDIR, ".env"), override=False)
except Exception:
    pass

from langchain_core.messages import SystemMessage, HumanMessage  # noqa: E402

from src.app.services.azure_open_ai import get_model             # noqa: E402
from src.app.engine import simulation, seams                     # noqa: E402
from src.app.engine.detectors import run_all                     # noqa: E402
from src.app.engine.core.schema import NodeExec                  # noqa: E402
from src.app.engine.projection import project                    # noqa: E402
from src.app.engine.analyst import (                             # noqa: E402
    RecommendationCard, process_card, build_prompt, parse_card, SYSTEM,
)

# The declared optimizable surface, from the seam registry (single source of truth —
# the same surface the pipeline and the notebook analyst bind to).
SURFACE = seams.surface()


def main() -> int:
    # Build data with BOTH a counterfactual (model-fit) and a structural (repeated-node) issue.
    nodes = simulation.simulate(seed=7, n_turns=600)
    for j in range(12):  # inject repeated find_places turns so the structural detector fires
        tid = f"rep_{j}"
        nodes += [
            NodeExec("demo", "sim", f"s{j}", tid, 0, "supervisor", "gpt-5.1", 1500, 150),
            NodeExec("demo", "sim", f"s{j}", tid, 1, "find_places", "gpt-5.1", 900, 400, tool_calls=1),
            NodeExec("demo", "sim", f"s{j}", tid, 2, "find_places", "gpt-5.1", 900, 400, tool_calls=1),
        ]
    detections = run_all(nodes)

    model = get_model()
    results: list[tuple[str, bool, str]] = []

    def ck(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    accepted = overridden_saving = 0
    for det in detections:
        resp = model.invoke([SystemMessage(content=SYSTEM), HumanMessage(content=build_prompt(det, SURFACE))])
        card = parse_card(getattr(resp, "content", "") or "", det)
        if card is None:
            ck(f"[{det.opportunity_id}] LLM produced parseable JSON card", False, "unparseable")
            continue
        pr = project(det.opportunity_id, nodes)
        engine_saving = round(pr.saving, 6) if pr is not None else det.projected_saving
        decision = process_card(card, SURFACE, engine_saving)
        accepted += 1 if decision.accepted else 0
        did_override = any("override saving" in r for r in decision.reasons)
        overridden_saving += 1 if did_override else 0
        ck(f"[{det.opportunity_id}] card accepted (bounded+cited)", decision.accepted,
           f"seam={card.seam} target={card.target} llm_saving={card.claimed_saving} -> engine={engine_saving}")
        ck(f"[{det.opportunity_id}] LLM dollar figure engine-controlled",
           did_override or abs(card.claimed_saving - engine_saving) < 1e-9,
           "; ".join(r for r in decision.reasons if 'saving' in r) or "matched")

    ck("SUMMARY: every detected opportunity yielded an accepted card",
       detections and accepted == len(detections), f"{accepted}/{len(detections)} accepted")

    print("=" * 78)
    print("LIVE B7 (quality) — real LLM analyst through the engine guardrails")
    print("=" * 78)
    ok = True
    for name, passed, detail in results:
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))
    print("-" * 78)
    print(f"  {accepted}/{len(detections)} cards accepted; {overridden_saving} invented savings overridden by the engine")
    print(f"  RESULT: {'ALL PASS - the LLM proposes, the engine safely disposes' if ok else 'SEE ABOVE'}")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

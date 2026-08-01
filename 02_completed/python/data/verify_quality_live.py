"""
Live B9: does the REAL reference-free LLM judge agree with human labels?

Wires the app's Azure OpenAI model (keyless / Entra) into the engine's reference-free
quality judge (`engine.quality.build_llm_judge`) and calibrates it over a small
per-agent labeled set. Passing = the LLM judge's pass/fail agrees with the human labels
within tolerance — the B9 acceptance, on real model output (not the deterministic stub).

Run:  cd 02_completed/python ; ../.venv-travel/Scripts/python.exe data/verify_quality_live.py
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

from src.app.services.azure_open_ai import get_model              # noqa: E402
from src.app.engine.quality import (                              # noqa: E402
    QualityExample, LabeledExample, build_llm_judge, calibrate,
)

# A small, deliberately unambiguous per-agent labeled set (constructed ground truth).
DATASET = [
    LabeledExample(QualityExample("find_places",
        "For Paris I'd suggest Hotel Le Bristol and Hotel Lutetia to stay, and for dinner "
        "Le Comptoir du Relais and Septime — all central and well regarded.",
        "recommend hotels and restaurants in Paris"), True),
    LabeledExample(QualityExample("find_places",
        "There are several nice hotels and a few good restaurants you could look into.",
        "recommend hotels and restaurants in Paris"), False),
    LabeledExample(QualityExample("itinerary",
        "Day 1: check in at Hotel Lutetia, morning at the Louvre, lunch in the Marais, "
        "evening Seine cruise, dinner at Septime. Day 2: Versailles day trip, then dinner "
        "near Saint-Germain before your flight.",
        "make a 2-day Paris itinerary"), True),
    LabeledExample(QualityExample("itinerary",
        "You can see museums and eat at some nice places while you're there.",
        "make a 2-day Paris itinerary"), False),
    LabeledExample(QualityExample("supervisor",
        "Happy to help plan your Paris trip! How many days will you have, and what's your budget?",
        "help me plan a trip to Paris"), True),
    LabeledExample(QualityExample("supervisor", "ok.",
        "help me plan a trip to Paris"), False),
]


def main() -> int:
    model = get_model()

    def invoke(system: str, user: str) -> str:
        msg = model.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        return getattr(msg, "content", "") or ""

    judge = build_llm_judge(invoke)

    print("=" * 78)
    print("LIVE B9 — reference-free LLM quality judge calibration")
    print("=" * 78)
    cal = calibrate(judge, DATASET, tolerance=0.8)
    # Per-example detail for transparency.
    for item in DATASET:
        res = judge(item.example)
        mark = "OK " if res.passed == item.label_pass else "XX "
        print(f"  [{mark}] {item.example.agent:<12} label={'pass' if item.label_pass else 'fail':<4} "
              f"judge={res.score}/{res.scale[1]} -> {'pass' if res.passed else 'fail'}  {res.reasoning[:70]}")
    print("-" * 78)
    print(f"  agreement={cal['agreement']}  precision={cal['precision']}  recall={cal['recall']}  "
          f"confusion={cal['confusion']}")
    ok = cal["within_tolerance"] and cal["precision"] > 0.5
    print(f"  RESULT: {'PASS' if ok else 'FAIL'} — reference-free judge "
          f"{'agrees with labels within tolerance' if ok else 'did NOT clear tolerance'}")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

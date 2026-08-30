"""
The LLM analyst (ADR-0010 §9) — the real proposer that plugs into `pipeline.analyze(analyst=...)`.

The LLM **proposes** exactly one recommendation card as strict JSON; the engine's five
deterministic guardrails then **dispose** — bound the card to the declared seam surface,
require citations, and (critically) override the model's dollar figure with the
engine-computed saving. "The LLM proposes; the engine disposes."

`make_llm_analyst(model, surface)` returns a `Callable[[Detection], RecommendationCard]`
you can hand to `analyze(nodes, surface, analyst=...)`. If the model output can't be
parsed (or the call fails), it falls back to the deterministic `default_analyst`, so the
loop never breaks — a flaky analyst degrades to the offline proposer instead of erroring.

This is the single source of truth for the live proposer: `data/verify_analyst_live.py`
and the Fabric analysis notebook both build their analyst from here, so the prompt and
parser can't drift between the local proof, the reverse-ETL producer, and Fabric.

Kept dependency-light on purpose: the LangChain message/model imports are *lazy* (inside
the returned callable), so importing the engine stays pure-stdlib and offline-safe. Only
constructing a live analyst pulls in the model runtime.
"""

from __future__ import annotations

import json
from typing import Callable

from ..detectors import Detection
from .cards import RecommendationCard

# The analyst's job, stated as strict-JSON contract. Kept verbatim across every caller so
# the guardrail-passing behavior proven in `verify_analyst_live.py` holds everywhere.
SYSTEM = (
    "You are an optimization analyst for a multi-agent app. Given a detected issue, propose "
    "exactly ONE change as STRICT JSON (no prose, no markdown) with keys:\n"
    '  seam: one of "config" | "prompt" | "code"\n'
    "  target: MUST be one of the allowed targets for that seam (given below)\n"
    "  claimed_saving: number (your best dollar estimate)\n"
    '  apply_mode: "auto" or "staged_change"\n'
    '  autonomy_ceiling: "L3" | "L4" | "L5"\n'
    "  evidence: a list with one object {detector, opportunity_id, traces:[...]}\n"
    "Cite the detector + opportunity id you were given. Output ONLY the JSON object."
)


def _citable_traces(det: Detection) -> list[str]:
    """Real trace ids the analyst can cite (guardrail #2), pulled from the detection's
    evidence. Falls back to sample ids so the contract is always satisfiable."""
    for key in ("turns", "traces", "sessions", "examples"):
        vals = det.evidence.get(key)
        if isinstance(vals, list) and vals:
            return [str(v) for v in vals[:3]]
    return ["trace-1", "trace-2"]


def build_prompt(det: Detection, surface: dict[str, set]) -> str:
    """Render the analyst user prompt for one detection, with the allowed targets taken
    from the *passed* seam surface (never hardcoded) so the analyst can only propose
    changes at seams the app actually declares."""
    return (
        f"Detected issue:\n"
        f"  detector: {det.detector}\n  kind: {det.kind}\n  agent: {det.agent}\n"
        f"  dimension: {det.dimension}\n  opportunity_id: {det.opportunity_id}\n"
        f"  evidence: {json.dumps(det.evidence)}\n\n"
        f"Allowed targets by seam:\n"
        f"  config: {sorted(surface.get('config', set()))}\n"
        f"  prompt: {sorted(surface.get('prompt', set()))}\n"
        f"  code: {sorted(surface.get('code', set()))}\n"
        f"Sample trace ids you may cite: {_citable_traces(det)}"
    )


def parse_card(text: str, det: Detection) -> RecommendationCard | None:
    """Parse the model's strict-JSON response into a `RecommendationCard`, tolerating a
    stray markdown fence. Returns None on unparseable output (the caller then falls back)."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    try:
        obj = json.loads(t[t.find("{"): t.rfind("}") + 1])
    except Exception:
        return None
    return RecommendationCard(
        agent=det.agent, dimension=det.dimension,
        seam=str(obj.get("seam", "")), target=str(obj.get("target", "")),
        evidence=obj.get("evidence") or [],
        opportunity_id=det.opportunity_id,
        claimed_saving=float(obj.get("claimed_saving", 0) or 0),
        apply_mode=str(obj.get("apply_mode", "")),
        autonomy_ceiling=str(obj.get("autonomy_ceiling", "")),
    )


def make_llm_analyst(
    model,
    surface: dict[str, set],
    *,
    fallback: Callable[[Detection], RecommendationCard] | None = None,
) -> Callable[[Detection], RecommendationCard]:
    """Build a live LLM analyst bound to `surface`.

    `model` is any LangChain chat model (e.g. `azure_open_ai.get_model()`, keyless/Entra).
    The returned callable proposes a card per detection and falls back to `fallback`
    (default: the engine's deterministic `default_analyst`) whenever the model can't be
    reached or its output won't parse — so `analyze()` always yields a card.
    """
    if fallback is None:
        from ..pipeline import default_analyst  # lazy: avoid pipeline<->analyst import cycle
        fallback = default_analyst

    def _analyst(det: Detection) -> RecommendationCard:
        from langchain_core.messages import SystemMessage, HumanMessage  # lazy: keep engine stdlib-only on import
        try:
            resp = model.invoke([SystemMessage(content=SYSTEM),
                                 HumanMessage(content=build_prompt(det, surface))])
            card = parse_card(getattr(resp, "content", "") or "", det)
        except Exception:
            card = None
        return card if card is not None else fallback(det)

    return _analyst

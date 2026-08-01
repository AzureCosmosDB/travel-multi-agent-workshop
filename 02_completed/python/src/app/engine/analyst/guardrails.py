"""
Analyst guardrails (ADR-0010 §9, spike B7 — the safety half).

The LLM proposes; the engine disposes. These five deterministic guardrails ensure a
bad/hallucinating analyst cannot do harm:

  1. Bounded to known seams   — reject targets outside the declared surface.
  2. Grounded + cited         — reject uncited cards.
  3. Engine computes savings  — the LLM's number is ignored; the engine value wins.
  4. Risk-gated apply_mode     — the seam sets apply_mode (config auto; prompt/code staged).
  5. Autonomy ceiling          — set from the seam/risk model, not the card.

`surface` is the declared optimizable surface: {"config": {...domains}, "prompt":
{...files}, "code": {...recipe ids}} — built from the policy manifest + prompt registry
+ recipe catalog by the caller.
"""

from __future__ import annotations

from .cards import RecommendationCard, Decision


SEAM_APPLY_MODE = {"config": "auto", "prompt": "staged_change", "code": "staged_change"}
SEAM_CEILING = {"config": "L4", "prompt": "L3", "code": "L3"}


def process_card(card: RecommendationCard, surface: dict[str, set], engine_saving: float) -> Decision:
    # 1. bounded to known seams (HARD REJECT)
    if card.seam not in surface:
        return Decision(False, [f"reject: unknown seam '{card.seam}'"])
    if card.target not in surface[card.seam]:
        return Decision(False, [f"reject: target '{card.target}' not in declared {card.seam} surface"])

    # 2. grounded + cited (HARD REJECT)
    if not card.evidence:
        return Decision(False, ["reject: no evidence (uncited)"])
    for e in card.evidence:
        if not (e.get("detector") and e.get("opportunity_id") and e.get("traces")):
            return Decision(False, ["reject: evidence missing detector/opportunity_id/traces"])

    reasons: list[str] = []

    # 3. engine computes the saving (NORMALIZE — the LLM's number is ignored)
    if abs(card.claimed_saving - engine_saving) > 1e-9:
        reasons.append(f"override saving {card.claimed_saving} -> {engine_saving} (engine-computed; LLM ignored)")

    # 4. risk-gated apply_mode (NORMALIZE)
    seam_mode = SEAM_APPLY_MODE[card.seam]
    if card.apply_mode != seam_mode:
        reasons.append(f"override apply_mode {card.apply_mode} -> {seam_mode} (seam-determined)")

    # 5. autonomy ceiling from seam/risk (NORMALIZE)
    seam_ceiling = SEAM_CEILING[card.seam]
    if card.autonomy_ceiling != seam_ceiling:
        reasons.append(f"override autonomy_ceiling {card.autonomy_ceiling} -> {seam_ceiling} (risk model)")

    normalized = {"agent": card.agent, "dimension": card.dimension, "seam": card.seam,
                  "target": card.target, "saving": engine_saving,
                  "apply_mode": seam_mode, "autonomy_ceiling": seam_ceiling}
    return Decision(True, reasons or ["accepted (no corrections)"], normalized)

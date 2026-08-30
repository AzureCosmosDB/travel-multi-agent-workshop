"""
Spike B7 (deterministic half) — the analyst guardrail / rubric harness (ADR-0012 B7).

The LLM-analyst has a *quality* half (does a real model write good cards? — needs an
LLM, deferred) and a *safety* half (does the engine stop a bad/hallucinating model
from doing harm?). This spike proves the **safety half deterministically**, with no
LLM: feed hand-crafted good and bad recommendation cards and assert the engine
enforces the five guardrails from ADR-0010 §9 / guide §9.

Guardrails:
  1. Bounded to known seams  — reject cards whose change targets anything outside the
     declared surface (config knob / prompt file / code recipe).
  2. Grounded + cited        — reject cards with no detector evidence / trace citations.
  3. LLM proposes, engine computes — the saving is (re)computed by the engine's
     projection; a card's self-reported number is IGNORED/overridden (kills
     hallucinated savings).
  4. Risk-gated apply_mode    — the seam sets apply_mode (config->auto, prompt/code->
     staged); the LLM does not choose its own autonomy.
  5. Autonomy ceiling         — set from the seam/risk model, not the card.

Pure stdlib, deterministic. `python b7_analyst_guardrails.py` (exit 0 = pass).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --- The declared optimizable surface (the "seam registry", guide §9.1) ----------------
DECLARED_SURFACE = {
    "config": {"model-selection", "memory-retention", "memory-salience"},   # policy knobs
    "prompt": {"supervisor.prompty", "itinerary_agent.prompty"},            # prompt files
    "code":   {"introduce-model-selector"},                                 # recipe ids
}

# Deterministic projection output (what a detector like B13 produced): opportunity -> saving.
# This stands in for "engine computes the saving"; the analyst must not invent it.
ENGINE_PROJECTION = {
    "opp-modelfit-supervisor": 58.653406,
    "opp-tool-dedup": 4.20,
    "opp-prompt-fix": 12.75,
}

# apply_mode + autonomy ceiling are functions of the seam (never the LLM's choice).
SEAM_APPLY_MODE = {"config": "auto", "prompt": "staged_change", "code": "staged_change"}
SEAM_CEILING = {"config": "L4", "prompt": "L3", "code": "L3"}


@dataclass
class Card:
    agent: str
    dimension: str
    seam: str
    target: str
    evidence: list[dict]           # each: {detector, opportunity_id, traces:[...]}
    opportunity_id: str
    claimed_saving: float          # the LLM's number — must be ignored/overridden
    apply_mode: str                # the LLM's claim — must be overridden from seam
    autonomy_ceiling: str          # the LLM's claim — must be overridden from seam


@dataclass
class Decision:
    accepted: bool
    reasons: list[str] = field(default_factory=list)
    normalized: dict[str, Any] | None = None


def process_card(card: Card) -> Decision:
    reasons: list[str] = []

    # Guardrail 1 — bounded to known seams (HARD REJECT).
    if card.seam not in DECLARED_SURFACE:
        return Decision(False, [f"reject: unknown seam '{card.seam}'"])
    if card.target not in DECLARED_SURFACE[card.seam]:
        return Decision(False, [f"reject: target '{card.target}' not in declared {card.seam} surface"])

    # Guardrail 2 — grounded + cited (HARD REJECT).
    if not card.evidence:
        return Decision(False, ["reject: no evidence (uncited)"])
    for e in card.evidence:
        if not e.get("detector") or not e.get("opportunity_id") or not e.get("traces"):
            return Decision(False, ["reject: evidence missing detector/opportunity_id/traces"])

    # Guardrail 3 — LLM proposes, ENGINE computes the saving (NORMALIZE / override).
    engine_saving = ENGINE_PROJECTION.get(card.opportunity_id)
    if engine_saving is None:
        return Decision(False, [f"reject: opportunity '{card.opportunity_id}' has no engine projection"])
    if abs(card.claimed_saving - engine_saving) > 1e-9:
        reasons.append(f"override saving {card.claimed_saving} -> {engine_saving} (engine-computed; LLM number ignored)")
    final_saving = engine_saving

    # Guardrail 4 — risk-gated apply_mode (NORMALIZE / override).
    seam_mode = SEAM_APPLY_MODE[card.seam]
    if card.apply_mode != seam_mode:
        reasons.append(f"override apply_mode {card.apply_mode} -> {seam_mode} (seam-determined)")

    # Guardrail 5 — autonomy ceiling from seam/risk (NORMALIZE / override).
    seam_ceiling = SEAM_CEILING[card.seam]
    if card.autonomy_ceiling != seam_ceiling:
        reasons.append(f"override autonomy_ceiling {card.autonomy_ceiling} -> {seam_ceiling} (risk model)")

    normalized = {
        "agent": card.agent, "dimension": card.dimension, "seam": card.seam,
        "target": card.target, "saving": final_saving,
        "apply_mode": seam_mode, "autonomy_ceiling": seam_ceiling,
    }
    return Decision(True, reasons or ["accepted (no corrections)"], normalized)


# --- Test cards (good + adversarial) ---------------------------------------------------
def _ev(det, opp):
    return [{"detector": det, "opportunity_id": opp, "traces": ["trace-1", "trace-2"]}]


CARDS = {
    "A_good_config": Card("supervisor", "model selection", "config", "model-selection",
                          _ev("counterfactual", "opp-modelfit-supervisor"),
                          "opp-modelfit-supervisor", 58.653406, "auto", "L4"),
    "B_uncited": Card("supervisor", "model selection", "config", "model-selection",
                      [], "opp-modelfit-supervisor", 58.653406, "auto", "L4"),
    "C_out_of_seam": Card("supervisor", "model selection", "config", "unknown-knob",
                          _ev("counterfactual", "opp-modelfit-supervisor"),
                          "opp-modelfit-supervisor", 58.653406, "auto", "L4"),
    "D_invented_saving": Card("supervisor", "model selection", "config", "model-selection",
                              _ev("counterfactual", "opp-modelfit-supervisor"),
                              "opp-modelfit-supervisor", 9999.0, "auto", "L4"),
    "E_code_claims_auto": Card("supervisor", "model selection", "code", "introduce-model-selector",
                               _ev("counterfactual", "opp-modelfit-supervisor"),
                               "opp-modelfit-supervisor", 58.653406, "auto", "L5"),
    "F_freeform_seam": Card("supervisor", "?", "magic", "do-whatever",
                            _ev("x", "opp-modelfit-supervisor"),
                            "opp-modelfit-supervisor", 1.0, "auto", "L5"),
}


def run() -> bool:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail):
        results.append((name, cond, detail))

    d = {k: process_card(c) for k, c in CARDS.items()}

    # A: valid config card accepted with NO corrections.
    check("A good config accepted, unchanged",
          d["A_good_config"].accepted and d["A_good_config"].reasons == ["accepted (no corrections)"],
          f"{d['A_good_config'].accepted} / {d['A_good_config'].reasons}")

    # B: uncited -> rejected.
    check("B uncited rejected", not d["B_uncited"].accepted, str(d["B_uncited"].reasons))

    # C: out-of-seam target -> rejected.
    check("C out-of-seam rejected", not d["C_out_of_seam"].accepted, str(d["C_out_of_seam"].reasons))

    # D: invented saving accepted BUT overridden to the engine value (hallucination killed).
    dd = d["D_invented_saving"]
    check("D invented saving overridden to engine value",
          dd.accepted and dd.normalized["saving"] == ENGINE_PROJECTION["opp-modelfit-supervisor"]
          and any("override saving" in r for r in dd.reasons),
          f"saving={dd.normalized['saving'] if dd.normalized else None}; reasons={dd.reasons}")

    # E: code seam claiming auto -> accepted BUT apply_mode forced to staged_change, ceiling L3.
    de = d["E_code_claims_auto"]
    check("E code-seam autonomy forced to staged/L3",
          de.accepted and de.normalized["apply_mode"] == "staged_change"
          and de.normalized["autonomy_ceiling"] == "L3",
          f"apply_mode={de.normalized['apply_mode'] if de.normalized else None}, "
          f"ceiling={de.normalized['autonomy_ceiling'] if de.normalized else None}")

    # F: free-form/unknown seam -> rejected.
    check("F free-form seam rejected", not d["F_freeform_seam"].accepted, str(d["F_freeform_seam"].reasons))

    print("=" * 78)
    print("B7 (deterministic half) — analyst guardrail / rubric harness")
    print("=" * 78)
    all_pass = True
    for name, ok, detail in results:
        all_pass = all_pass and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - guardrails enforce safety deterministically' if all_pass else 'FAILURES'}")
    print("  (Quality half — real-LLM card pass-rate — deferred until creds available.)")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

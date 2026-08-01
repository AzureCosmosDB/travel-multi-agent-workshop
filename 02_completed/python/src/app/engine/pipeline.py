"""
The analysis pipeline — the loop, wired (ADR-0010 Layer 2).

    detect (detectors) -> project (engine computes saving) -> propose (analyst) ->
    guardrail (validate/normalize) -> rank (outcome ledger) -> discovered opportunities

The `analyst` argument is where the LLM plugs in (it PROPOSES cards). The default is a
deterministic proposer so the whole loop runs and unit-tests without an LLM; a real
LLM analyst is a drop-in that returns the same `RecommendationCard` shape. Either way
the guardrails and the engine-computed saving are authoritative (LLM proposes / engine
computes).
"""

from __future__ import annotations

from typing import Callable

from .detectors import run_all, Detection
from .projection import project
from .analyst import RecommendationCard, process_card
from .learning import rank_candidates, LedgerEntry

# Which seam/target each opportunity is fixed at (the seam registry mapping).
OPPORTUNITY_SEAMS: dict[str, tuple[str, str]] = {
    "opp-modelfit-supervisor": ("config", "model-selection"),
    "opp-repeated-node": ("prompt", "supervisor.prompty"),
}

# Which catalogued optimization scenario each opportunity rediscovers (acceptance, B14).
# The catalog lives in analytics/docs/optimization-scenarios/. A discovered opportunity
# that maps to a SCEN id is the engine rediscovering a known case end-to-end from data.
OPPORTUNITY_SCENARIOS: dict[str, str] = {
    "opp-modelfit-supervisor": "SCEN-007",   # model selection on trivial turns
    "opp-repeated-node": "SCEN-008",         # tool-utilization / redundant hop
}


def rediscovered_scenarios(cards: list[dict]) -> list[str]:
    """SCEN ids the engine rediscovered from data (for acceptance). Prefixed opportunity
    ids (e.g. cost-regression-<agent>) fall back to their family via a prefix match."""
    out: list[str] = []
    for c in cards:
        oid = c.get("opportunity_id", "")
        scen = OPPORTUNITY_SCENARIOS.get(oid)
        if scen is None and oid.startswith("opp-cost-regression-"):
            scen = "SCEN-005"                # cost concentration / regression family
        if scen and scen not in out:
            out.append(scen)
    return out


def default_analyst(detection: Detection) -> RecommendationCard:
    """Deterministic stand-in for the LLM analyst (proposes a card from a detection)."""
    seam, target = OPPORTUNITY_SEAMS.get(detection.opportunity_id, ("prompt", "supervisor.prompty"))
    traces = list(detection.evidence.get("turns", []))[:3] or ["sample-trace"]
    return RecommendationCard(
        agent=detection.agent, dimension=detection.dimension, seam=seam, target=target,
        evidence=[{"detector": detection.detector, "opportunity_id": detection.opportunity_id, "traces": traces}],
        opportunity_id=detection.opportunity_id, claimed_saving=detection.projected_saving,
    )


def analyze(nodes, surface: dict[str, set], *,
            ledger: list[LedgerEntry] | None = None,
            analyst: Callable[[Detection], RecommendationCard] | None = None) -> list[dict]:
    """Run the full loop over node-grain telemetry -> ranked discovered-opportunity cards."""
    analyst = analyst or default_analyst
    cards: list[dict] = []
    for d in run_all(nodes):
        pr = project(d.opportunity_id, nodes)
        engine_saving = pr.saving if pr is not None else d.projected_saving
        decision = process_card(analyst(d), surface, engine_saving)
        if not decision.accepted:
            continue
        card = dict(decision.normalized)
        card.update(opportunity_id=d.opportunity_id, kind=d.kind, evidence=d.evidence,
                    reasons=decision.reasons)
        cards.append(card)

    if ledger:
        ranked = rank_candidates(ledger, [(c["opportunity_id"], c["saving"]) for c in cards])
        order = {p: i for i, (p, _) in enumerate(ranked)}
        cards.sort(key=lambda c: order.get(c["opportunity_id"], 10_000))
    else:
        cards.sort(key=lambda c: -c["saving"])
    return cards

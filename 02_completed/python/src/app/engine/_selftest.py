"""
Cross-package self-test for the engine (run: `python -m src.app.engine._selftest`).

Exercises every functional area together and asserts they compose. Promotes the
`analytics/spikes/*` proofs into an integration test over the real package. Exit 0 = pass.
"""

from __future__ import annotations

from .instrumentation import node_grain_records, current_turn_aggregate, reconciles
from .detectors import run_all
from .projection import project, scale_to_monthly, cost_per_outcome, project_business_impact
from .policy import DOMAINS, bind_policy
from .analyst import RecommendationCard, process_card
from .autonomy import Policy, Observation, guard
from .learning import LedgerEntry, rank_candidates
from .scorecard import build_scorecard, format_scorecard
from .seams import surface as seam_surface, render_recipe, list_seams
from .pipeline import analyze
from .simulation import simulate


class _Msg:
    def __init__(self, i, o):
        self.usage_metadata = {"input_tokens": i, "output_tokens": o, "total_tokens": i + o,
                               "input_token_details": {"cache_read": 0}}
        self.response_metadata = {"model_name": "gpt-5.1"}


def run() -> bool:
    checks: list[tuple[str, bool, str]] = []

    def ck(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    # --- simulation -> detectors -> projection --------------------------------------
    nodes = simulate(seed=7, n_turns=1000)
    ck("simulation: every node has an agent (0% gap)", all(n.agent for n in nodes) and len(nodes) > 1000,
       f"{len(nodes)} nodes")

    findings = run_all(nodes)
    modelfit = [d for d in findings if d.opportunity_id == "opp-modelfit-supervisor"]
    ck("detectors: model-fit counterfactual fires", len(modelfit) == 1 and modelfit[0].projected_saving > 0,
       f"{[d.detector for d in findings]}")

    # --- structural detector fixture proof (B3): fires on positive, silent on negative ---
    from .detectors.structural import repeated_node
    from .core.schema import NodeExec as _NE

    def _turn(tid, agents):
        return [_NE("t", "u", "s", tid, i, a, "gpt-5.1", 1000, 200) for i, a in enumerate(agents)]

    pos = _turn("tp", ["supervisor", "find_places", "find_places"])  # back-to-back repeat
    neg = _turn("tn", ["supervisor", "find_places", "create_or_update_itinerary"])  # clean
    ck("detectors(structural): repeated_node FIRES on injected positive",
       len(repeated_node(pos)) == 1 and repeated_node(pos)[0].count == 1,
       f"{[d.opportunity_id for d in repeated_node(pos)]}")
    ck("detectors(structural): repeated_node SILENT on clean negative",
       repeated_node(neg) == [], f"{repeated_node(neg)}")

    # --- statistical detector: derived threshold + min-sample + not-noisy (B5) --------
    from .detectors.statistical import cost_regression, MIN_SAMPLE

    def _series(agent, values):
        return [_NE("t", "u", "s", agent, i, agent, "gpt-5.1", 1000, v) for i, v in enumerate(values)]

    def _alt(base, n):  # small ±10 jitter so the baseline has non-zero variance
        return [base - 10 if i % 2 else base + 10 for i in range(n)]

    tiny = _series("A", _alt(200, MIN_SAMPLE))                       # < 2*MIN_SAMPLE
    clean = _series("A", _alt(200, 80))                             # stationary
    outlier = _series("A", _alt(200, 79) + [5000])                  # one spike in recent
    regression = _series("A", _alt(200, 40) + _alt(600, 40))        # persistent level shift
    ck("detectors(statistical): SUPPRESSED before N (min sample)", cost_regression(tiny) == [],
       f"{cost_regression(tiny)}")
    ck("detectors(statistical): silent on a stationary baseline", cost_regression(clean) == [],
       f"{cost_regression(clean)}")
    ck("detectors(statistical): NOT noisy — a single outlier does not fire",
       cost_regression(outlier) == [], f"{cost_regression(outlier)}")
    reg = cost_regression(regression)
    ck("detectors(statistical): FIRES on a consistent, material regression",
       len(reg) == 1 and reg[0].evidence["z"] >= 3.0 and reg[0].evidence["effect"] >= 0.2,
       f"{reg[0].evidence if reg else None}")

    # --- realized-complexity signal beats the keyword tier (B6) ----------------------
    from .complexity import LabeledTurn, compare_coverage
    labeled = [
        # truly trivial turns the keyword classifier MISSES (not greetings, but low-output)
        LabeledTurn("what's the currency in France?", 40, True),
        LabeledTurn("is the Louvre open on Mondays?", 55, True),
        LabeledTurn("how far is Versailles from Paris?", 60, True),
        LabeledTurn("hi", 20, True),                       # keyword catches this one
        # truly substantive turns neither should downgrade
        LabeledTurn("build me a day-by-day itinerary for 5 days", 2200, False),
        LabeledTurn("find hotels and restaurants near the Marais", 700, False),
    ]
    cov = compare_coverage(labeled)
    ck("complexity: measured signal finds MORE opportunity than keyword tier",
       cov["measured_recall"] > cov["keyword_recall"] and cov["extra_opportunities"] >= 2,
       f"keyword={cov['keyword_caught']}/{cov['truly_trivial']} measured={cov['measured_caught']}/{cov['truly_trivial']}")
    ck("complexity: measured signal does not downgrade truly-substantive turns",
       cov["measured_false_downgrades"] == 0, f"false_downgrades={cov['measured_false_downgrades']}")

    pr = project("opp-modelfit-supervisor", nodes)
    ck("projection reconciles with detector saving", abs(pr.saving - modelfit[0].projected_saving) < 1e-6,
       f"proj={pr.saving} det={modelfit[0].projected_saving}")
    ck("what-if: scaling projects onto volume", scale_to_monthly(pr.saving, len(nodes), 5000) > 0,
       f"~${scale_to_monthly(pr.saving, len(nodes), 5000)}/mo")
    bi = project_business_impact("price-only", pr.baseline, pr.optimized, outcomes_before=10)
    ck("what-if: price-only cost/outcome drops", bi["cpo_after"] < bi["cpo_before"],
       f"{bi['cpo_before']}->{bi['cpo_after']}")

    # --- instrumentation reconciliation ---------------------------------------------
    events = [{"event": "on_chat_model_end", "metadata": {"langgraph_node": a},
               "data": {"output": _Msg(i, o)}} for a, i, o in [("supervisor", 1500, 180), ("find_places", 900, 470)]]
    recs = node_grain_records(events)
    ck("instrumentation: node-grain reconciles to turn total", reconciles(recs, current_turn_aggregate(events)) and len(recs) == 2,
       f"{[n.agent for n in recs]}")

    # --- policy binding SDK ----------------------------------------------------------
    schema = DOMAINS.get("model-selection")(available_deployments={"gpt-5.1", "gpt-5-mini", "gpt-5-nano"})
    _, s1 = bind_policy(schema, None)
    ck("policy: fail-closed on no policy", "fail-closed" in s1, s1)
    _, s2 = bind_policy(schema, {"schema_version": 1, "params": {"default_deployment": "gpt-6-ultra"}})
    ck("policy: unknown model rejected -> fail-closed", "fail-closed" in s2, s2)
    p, s3 = bind_policy(schema, {"schema_version": 1, "params": {"enabled": True,
            "default_deployment": "gpt-5-mini", "tiers": {"routine": "gpt-5-mini"}}})
    ck("policy: valid policy accepted", "ok" in s3 and p["default_deployment"] == "gpt-5-mini", s3)

    # --- seam registry (B11) — the declared surface + recipe rendering ---------------
    surface = seam_surface()
    ck("seams: registry lists the app's seams (config/prompt/code)",
       len(list_seams()) >= 4 and "model-selection" in surface["config"]
       and "supervisor.prompty" in surface["prompt"] and "introduce-model-selector" in surface["code"],
       f"{sorted(surface['config'])} | {sorted(surface['prompt'])} | {sorted(surface['code'])}")
    rec = render_recipe("config:model-selection",
                        {"enabled": True, "default_deployment": "gpt-5-mini", "tiers": {"routine": "gpt-5-mini"}})
    ck("seams: config recipe binds params -> a fail-closed policy doc (auto/L4)",
       rec["accepted"] and rec["apply_mode"] == "auto" and rec["autonomy_ceiling"] == "L4"
       and rec["policy_doc"]["params"]["default_deployment"] == "gpt-5-mini", rec["status"])
    bad = render_recipe("config:model-selection", {"default_deployment": "gpt-6-ultra"})
    ck("seams: config recipe fails closed on an invalid deployment",
       not bad["accepted"] and bad["policy_doc"] is None, bad["status"])
    prec = render_recipe("prompt:supervisor", {"guidance": "trim examples"})
    ck("seams: prompt recipe is a staged (human-attested) change",
       prec["apply_mode"] == "staged_change" and "human attestation" in prec["requires"], prec["edit"])

    # --- code-context provider (B12) — read-only retrieval -> drafted diff ------------
    from .codecontext import InMemoryProvider, scaffold_diff
    src = {
        "src/app/travel_agents.py": (
            "def classify_turn_tier(text):\n"
            "    return 'routine'\n\n"
            "def select_deployment_for_turn(messages):\n"
            "    return default, 'default'\n\n"
            "def unrelated_helper(x):\n"
            "    return x\n"
        )
    }
    provider = InMemoryProvider(src)
    ctx = provider.retrieve("introduce-model-selector", hints=["select_deployment_for_turn"])
    got = {s.symbol for s in ctx.snippets}
    ck("codecontext: retrieves the relevant seam symbol (read-only)",
       "select_deployment_for_turn" in got and "unrelated_helper" not in got, f"{sorted(got)}")
    ck("codecontext: provider has no write path",
       not any(hasattr(provider, m) for m in ("write", "save", "apply", "commit")))
    diff = scaffold_diff(ctx, "route trivial turns to a cheaper model")
    ck("codecontext: analyst can draft a grounded diff from retrieved context",
       "select_deployment_for_turn" in diff and "TODO(analyst)" in diff and diff.count("--- a/") >= 1,
       f"{len(diff)} chars")

    # --- reference-free quality judge + per-agent rubrics + calibration (B9) ----------
    from .quality import QualityExample, LabeledExample, deterministic_judge, calibrate, get_rubric
    ck("quality: per-agent rubrics differ (find_places wants named entities)",
       get_rubric("find_places").expects_named_entities and get_rubric("itinerary").expects_structure
       and not get_rubric("supervisor").expects_named_entities)
    dataset = [
        # find_places: names concrete venues => good; vague => bad
        LabeledExample(QualityExample("find_places", "Try Hotel Le Bristol and Le Comptoir du Relais near Saint-Germain.",
                                      "hotels and dining in Paris"), True),
        LabeledExample(QualityExample("find_places", "There are several good hotels and some restaurants you could try.",
                                      "hotels and dining in Paris"), False),
        # itinerary: day-by-day structure => good; unstructured => bad
        LabeledExample(QualityExample("itinerary", "Day 1: check in at Hotel Lutetia, Louvre, then dinner at Septime. Day 2: Versailles day trip.",
                                      "2-day plan"), True),
        LabeledExample(QualityExample("itinerary", "You should visit some museums and eat at nice places while there.",
                                      "2-day plan"), False),
        # supervisor: helpful clarifying answer => good; empty => bad
        LabeledExample(QualityExample("supervisor", "Happy to help plan Paris — how many days and what's your budget?",
                                      "plan my trip"), True),
        LabeledExample(QualityExample("supervisor", "ok.", "plan my trip"), False),
    ]
    cal = calibrate(deterministic_judge, dataset, tolerance=0.8)
    ck("quality: reference-free judge agrees with labels within tolerance",
       cal["within_tolerance"] and cal["agreement"] >= 0.8,
       f"agreement={cal['agreement']} P={cal['precision']} R={cal['recall']} {cal['confusion']}")
    ck("quality: judge does not trivially pass everything (precision > 0.5)",
       cal["precision"] > 0.5, f"precision={cal['precision']}")

    # --- analyst guardrails ----------------------------------------------------------
    ev = [{"detector": "counterfactual.model_fit", "opportunity_id": "opp-modelfit-supervisor", "traces": ["t1"]}]
    good = RecommendationCard("supervisor", "model selection", "config", "model-selection", ev,
                              "opp-modelfit-supervisor", pr.saving, "auto", "L4")
    ck("analyst: valid card accepted unchanged", process_card(good, surface, pr.saving).accepted)
    invented = RecommendationCard("supervisor", "model selection", "config", "model-selection", ev,
                                  "opp-modelfit-supervisor", 9999.0, "auto", "L4")
    d = process_card(invented, surface, pr.saving)
    ck("analyst: invented saving overridden to engine value", d.accepted and d.normalized["saving"] == pr.saving,
       f"{d.normalized['saving'] if d.normalized else None}")
    ck("analyst: unknown seam rejected",
       not process_card(RecommendationCard("x", "y", "magic", "z", ev, "o"), surface, 0).accepted)

    # --- autonomy guard --------------------------------------------------------------
    pol = Policy("model-selection", "config")
    v, _ = guard(pol, Observation(200, 1.0, 1.2, 0.82))
    ck("autonomy: adverse -> auto-revert (config)", v == "adverse" and pol.status == "reverted")
    pol2 = Policy("city-context", "prompt")
    v2, _ = guard(pol2, Observation(200, 1.0, 1.3, 0.9))
    ck("autonomy: non-config adverse NOT auto-reverted", v2 == "adverse" and pol2.status == "active")

    # --- learning --------------------------------------------------------------------
    led = [LedgerEntry("model-selection", 100, 100, "kept"), LedgerEntry("tool-dedup", 100, 20, "reverted")]
    ranked = rank_candidates(led, [("model-selection", 100), ("tool-dedup", 100)])
    ck("learning: reliable pattern ranks first", ranked[0][0] == "model-selection", str(ranked))

    # --- full pipeline (detect -> project -> propose -> guardrail -> rank) -----------
    cards = analyze(nodes, surface)
    msel = [c for c in cards if c["opportunity_id"] == "opp-modelfit-supervisor"]
    ck("pipeline: produces a validated model-selection card",
       len(msel) == 1 and msel[0]["seam"] == "config" and msel[0]["apply_mode"] == "auto",
       f"{[(c['opportunity_id'], c['apply_mode']) for c in cards]}")
    ck("pipeline: card saving == engine projection (not the proposer's claim)",
       msel and abs(msel[0]["saving"] - pr.saving) < 1e-6, f"{msel[0]['saving'] if msel else None}")

    # --- rediscovery acceptance (B14): engine rediscovers a catalogued SCEN from data ---
    from .pipeline import rediscovered_scenarios
    scens = rediscovered_scenarios(cards)
    ck("acceptance(B14): engine rediscovers >=1 catalogued SCEN end-to-end (SCEN-007)",
       len(scens) >= 1 and "SCEN-007" in scens, f"rediscovered={scens}")

    # --- agent scorecard (agent x dimension rollup, B2) ------------------------------
    cards_sc = build_scorecard(nodes)
    sup = next((c for c in cards_sc if c.agent == "supervisor"), None)
    ck("scorecard: one card per agent, supervisor present",
       sup is not None and len(cards_sc) >= 1, f"agents={[c.agent for c in cards_sc]}")
    ck("scorecard: supervisor flags a model-selection opportunity",
       sup is not None and sup.dimensions["model_selection"].status == "opportunity"
       and sup.dimensions["model_selection"].value > 0,
       f"{sup.dimensions['model_selection'].headline if sup else None}")
    ck("scorecard: cost shares sum to ~1 across agents",
       abs(sum(c.cost_share for c in cards_sc) - 1.0) < 1e-6,
       f"sum={sum(c.cost_share for c in cards_sc):.4f}")
    ck("scorecard: renders without error",
       isinstance(format_scorecard(cards_sc), str) and "AGENT SCORECARD" in format_scorecard(cards_sc))

    # --- report ----------------------------------------------------------------------
    print("=" * 78)
    print("engine self-test (integration across all functional areas)")
    print("=" * 78)
    ok = True
    for name, passed, detail in checks:
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - engine wires up and composes end-to-end' if ok else 'FAILURES'}")
    print("=" * 78)
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

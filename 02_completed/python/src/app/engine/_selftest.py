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

    # --- analyst guardrails ----------------------------------------------------------
    surface = {"config": {"model-selection"}, "prompt": {"supervisor.prompty"}, "code": {"introduce-model-selector"}}
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

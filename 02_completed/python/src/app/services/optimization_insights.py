"""
OptimizationInsights writer — in-process reverse-ETL (Fabric-independent).

Computes the business-impact, memory-intelligence, agent-path, agent-scorecard and
measured-saving signals with the app's own tested diagnostics
(``optimization_recommendations`` + ``engine.scorecard``) and flattens them into the flat
``OptimizationInsights`` rows the portal's Business / Memory / Governance views read.

This is the same computation the Module-09 Fabric notebook performs over the mirror — but run
directly against Cosmos, so the snapshot can be (re)built with **no Fabric, mirror, or Spark**.
``analytics/fabric/compute_insights.py`` is the CLI wrapper around this module, and
``POST /optimizations/insights/recompute`` is the in-app trigger.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


INSIGHTS_CONTAINER = "OptimizationInsights"
RECOMPUTABLE_GOVERNANCE_TYPES = frozenset({"controlled_demo4_derived"})

# --- Reserved partition keys (NOT tenants) -------------------------------------------
# OptimizationInsights is partitioned by /tenantId. A real *tenant* is a customer/workspace
# with its own users (e.g. marvel -> tony/steve/bruce/peter; analytics). Some rows are
# GLOBAL / cross-tenant with no single customer -- memory intelligence (memories are keyed
# by user, not tenant) and the scenario-keyed optimization results (measured across all
# tenants). They still need a partition value, so they use reserved keys prefixed `_global_`.
# Readers filter by `type`, so these never mix with real-tenant rows.
MEMORY_PARTITION = "_global_memory"            # global memory-intelligence rows
_STAGE_ORDER = {"engaged": 1, "searched": 2, "planned": 3, "confirmed": 4}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scorecard_nodes_from_dicts(recs: list[dict]):
    """Convert flat NodeExecutions records (node_executions.query_node_executions) into
    engine NodeExec objects for build_scorecard."""
    from src.app.engine.core.schema import NodeExec
    out = []
    for r in recs:
        out.append(NodeExec(
            tenant_id=r.get("tenant_id", ""), user_id=r.get("user_id", ""),
            session_id=r.get("session_id", ""), turn_id=r.get("turn_id", ""),
            seq=r.get("seq", 0), agent=r.get("agent", ""),
            model_deployment=r.get("model_deployment", r.get("model_name", "Unknown")),
            input_tokens=r.get("input_tokens", 0), output_tokens=r.get("output_tokens", 0),
            cached_tokens=r.get("cached_tokens", 0), model_name=r.get("model_name", "Unknown"),
        ))
    return out


def build_insight_rows(tenant_id: str) -> list[dict]:
    """Compute the diagnostics with the tested app logic and flatten to insight rows."""
    from src.app.services import optimization_recommendations as rec

    now = _now()
    rows: list[dict] = []

    cpo = rec.build_cost_per_outcome_diagnostic(tenant_id)["evidence"]
    funnel = cpo["funnel"]
    for stage, sessions in funnel.items():
        rows.append({
            "id": f"funnel::{tenant_id}::{stage}",
            "type": "funnel_stage", "tenantId": tenant_id,
            "stage": stage, "stage_order": _STAGE_ORDER.get(stage, 9),
            "sessions": sessions, "computed_at": now,
        })
    for cause, sessions in cpo["abandonment"].items():
        rows.append({
            "id": f"cause::{tenant_id}::{cause}",
            "type": "abandonment_cause", "tenantId": tenant_id,
            "cause": cause, "sessions": sessions, "computed_at": now,
        })
    engaged = funnel.get("engaged", 0)
    confirmed = funnel.get("confirmed", 0)
    addressable = {k: v for k, v in cpo["abandonment"].items() if k != "no_engagement"}
    biggest = max(addressable, key=addressable.get) if any(addressable.values()) else "none"
    rows.append({
        "id": f"kpi::{tenant_id}",
        "type": "conversion_kpi", "tenantId": tenant_id,
        "engaged": engaged, "confirmed": confirmed,
        "conversion_rate": round(100 * confirmed / max(engaged, 1), 1),
        "wasted_pct": cpo["wasted_pct"],
        "tokens_per_outcome": cpo["tokens_per_outcome"],
        "biggest_leak": biggest, "computed_at": now,
    })

    paths = rec.build_agent_path_diagnostic(tenant_id)["evidence"]["paths"]
    for i, p in enumerate(paths):
        rows.append({
            "id": f"path::{tenant_id}::{i}",
            "type": "agent_path_cost", "tenantId": tenant_id,
            "agent_path": p["agent_path"], "turns": p["turns"],
            "total_tokens": p["total_tokens"], "avg_tokens": p["avg_tokens"],
            "computed_at": now,
        })

    mem = rec.build_memory_retention_recommendation(tenant_id)["evidence"]
    rows.append({
        "id": f"memory::{tenant_id}",
        "type": "memory_retention", "tenantId": tenant_id,
        "total_memories": mem["total_memories"],
        "superseded_memories": mem["superseded_memories"],
        "superseded_pct": mem["superseded_pct"],
        "avoided_recall_tokens": mem.get("avoided_recall_tokens", 0),
        "measured_saving_usd": mem.get("measured_saving_usd", 0.0),
        "computed_at": now,
    })

    # Per-agent x dimension health from node-grain (the agent scorecard the Console shows),
    # flattened one row per (agent, scored dimension) for the Power BI Agent Performance page.
    # Turn totals are measured; the per-agent token/cost SPLIT is the app's live capture
    # (travel_agents_api.py -> NodeExecutions) or, on seeded demo data, a reconstruction
    # (seed_data.py) that reconciles to each turn -- so per-agent COST is exact on live traffic
    # and modeled on seed. The 5 unscored dimensions (see engine PENDING_DIMENSIONS) are omitted
    # here rather than emitted as fabricated n/a rows; the report footnote lists them.
    try:
        from src.app.engine.scorecard import build_scorecard
        from src.app.services import node_executions as ne
        # Use the existing Configuration pricing (per 1M) -> engine per-1K format, so the scorecard
        # cost matches the notebook and the console (all three pass the same pricing).
        _sc_pricing = {m: {"in": p.get("input", 0.0) / 1000.0, "out": p.get("output", 0.0) / 1000.0}
                       for m, p in rec.load_pricing().items()}
        nodes = _scorecard_nodes_from_dicts(ne.query_node_executions(tenant_id))
        for card in build_scorecard(nodes, pricing=_sc_pricing):
            agent_fields = {
                "agent": card.agent, "agent_status": card.status,
                "cost": round(card.cost, 6), "cost_share": round(card.cost_share, 4),
                "executions": card.executions, "turns": card.turns,
                "total_tokens": card.total_tokens,
                "tokens_per_turn": round(card.total_tokens / max(card.turns, 1), 1),
            }
            for dim, sc in card.dimensions.items():
                rows.append({
                    "id": f"scorecard::{tenant_id}::{card.agent}::{dim}",
                    "type": "agent_scorecard", "tenantId": tenant_id, **agent_fields,
                    "dimension": dim, "dim_status": sc.status, "headline": sc.headline,
                    "value": sc.value, "unit": sc.unit, "computed_at": now,
                })
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("compute_insights").debug("agent_scorecard rows skipped: %s", exc)
    return rows


def build_recommendation_rows(tenant_id: str) -> list[dict]:
    """Reverse-ETL the recommendation *cards* + turn metrics the Console reads.

    Closes the loop the workshop teaches: instead of the Optimization Console
    recomputing these aggregations from Cosmos on every request, the analytics
    plane (this script / the Fabric notebook) computes them and writes them back
    to ``OptimizationInsights``, where the app reads them cheaply. The volatile
    policy ``status`` is re-stamped live by the app on read. The manual
    prompt/code opportunity state is also copied from the authoritative live
    opportunity feed for BI, while acting (apply/revert) stays operational.
    """
    from src.app.services import optimization_recommendations as rec

    now = _now()
    rows: list[dict] = []
    from src.app import optimization_agent_api

    opportunities, _, _ = optimization_agent_api._opportunities(tenant_id)
    opportunities_by_id: dict[str, dict] = {}
    for opportunity in opportunities:
        opportunity_id = opportunity.get("opportunity_id")
        if not opportunity_id:
            continue
        if opportunity_id in opportunities_by_id:
            raise ValueError(f"duplicate canonical opportunity_id: {opportunity_id}")
        opportunities_by_id[str(opportunity_id)] = opportunity
    manual_opportunity = next(
        (
            opportunity
            for opportunity in opportunities
            if opportunity.get("opportunity_id") == "opp-repeated-node"
        ),
        None,
    )
    for order, card in enumerate(rec.build_recommendations(tenant_id)):
        card = dict(card)
        scenario = card.get("scenario")
        card_opportunity_id = card.get("opportunity_id")
        matching_opportunity = (
            opportunities_by_id.get(str(card_opportunity_id))
            if card_opportunity_id
            else None
        )
        is_manual = scenario == "tool-call-dedup" and manual_opportunity is not None
        projected_saving = (
            matching_opportunity.get("saving")
            if matching_opportunity is not None
            else card.get("estimated_saving_usd")
        )
        card["estimated_saving_usd"] = round(float(projected_saving or 0.0), 6)
        if matching_opportunity is not None:
            card["opportunity_id"] = matching_opportunity.get("opportunity_id")
        rows.append({
            "id": f"reccard::{tenant_id}::{scenario}",
            "type": "recommendation_card", "tenantId": tenant_id,
            "scenario": scenario, "scenario_id": card.get("scenario_id"),
            "opportunity_id": (
                matching_opportunity.get("opportunity_id")
                if matching_opportunity is not None
                else None
            ),
            "order": order,
            "note": f"{order + 1} · {card.get('title')}",
            # Flat display fields so BI can render the card without reaching into
            # the nested `card` object — nested fields don't surface cleanly over
            # the Fabric mirror / DirectQuery. The report's wrapped narrative
            # measure consumes these fields directly.
            "title": card.get("title"),
            "dimension": card.get("dimension"),
            "apply_mode": "staged_change" if is_manual else card.get("apply_mode") or "policy",
            "status": (
                manual_opportunity.get("governed_state") or "new"
                if is_manual
                else card.get("status") or "insight"
            ),
            "policy_status": card.get("policy_status"),
            "dataset_phase": card.get("dataset_phase"),
            "display_state": card.get("display_state"),
            "state_valid": card.get("state_valid"),
            "state_reason": card.get("state_reason"),
            "maturity": card.get("maturity"),
            "estimated_saving_usd": card["estimated_saving_usd"],
            "saving_kind": card.get("saving_kind") or "Estimated",
            # Flattened evidence summary + caveat so the BI cards can show the same
            # headline numbers / yellow limitation line the Console does (the nested
            # `evidence`/`estimate_caveat` don't surface over the mirror).
            "evidence_line": rec.summarize_card_evidence(card),
            "caveat": rec.card_caveat(card),
            "card": card, "computed_at": now,
        })
    rows.append({
        "id": f"metrics::{tenant_id}",
        "type": "turn_metrics", "tenantId": tenant_id,
        "metrics": rec.build_turn_metrics(tenant_id), "computed_at": now,
    })
    return rows


def build_agent_opportunity_rows(tenant_id: str) -> list[dict]:
    """Flatten the engine-ranked opportunity feed and its effective SLO policy.

    The agent API remains the single source of truth for ranking, projected saving,
    governance state, and SLO gating. These rows only make that same result usable
    by the mirrored DirectQuery semantic model.
    """
    from src.app import optimization_agent_api

    now = _now()
    opportunities, total_spend, slo = optimization_agent_api._opportunities(tenant_id)
    rows: list[dict] = []
    for rank, opportunity in enumerate(opportunities, start=1):
        seam = str(opportunity.get("seam") or "")
        target = str(opportunity.get("target") or "")
        governed_state = str(opportunity.get("governed_state") or "new")
        applied_state = str(opportunity.get("applied_state") or "n/a")
        apply_mode = str(opportunity.get("apply_mode") or "")
        apply_mode_label = {
            "staged_change": "Manual",
            "manual": "Manual",
            "auto": "Automatic",
            "diagnostic": "Diagnostic",
        }.get(apply_mode.lower(), apply_mode.replace("_", " ").title())
        if seam in {"prompt", "code"}:
            display_state = {
                "new": "Proposed",
                "proposed": "Proposed",
                "approved": "Approved",
                "deployed": "Deployed",
                "rolled-back": "Rolled back",
                "dismissed": "Dismissed",
                "staged": "Approved",
                "unstaged": "Dismissed",
                "applied": "Deployed",
                "reverted": "Rolled back",
            }.get(governed_state.lower(), governed_state.replace("_", " ").title())
        else:
            display_state = {
                "active": "Active",
                "not_proposed": "Not applied",
                "n/a": "—",
                "na": "—",
            }.get(applied_state.lower(), applied_state.replace("_", " ").title())
        rows.append({
            "id": f"agentopp::{tenant_id}::{opportunity.get('opportunity_id', rank)}",
            "type": "agent_opportunity",
            "tenantId": tenant_id,
            # Compatibility projection for Fabric mirroring: a mirrored Cosmos table's
            # SQL schema does not evolve when a later document introduces brand-new
            # properties. Populate the existing sparse OptimizationInsights columns
            # below so DirectQuery receives the same truthful values immediately.
            "order": rank,
            "note": f"{seam} \u2192 {target}",
            "saving_usd": round(float(opportunity.get("saving") or 0.0), 6),
            "saving_pct": round(100 * float(opportunity.get("effect") or 0.0), 2),
            "apply_mode": apply_mode_label,
            "maturity": opportunity.get("autonomy_ceiling"),
            "method": "\u2713" if opportunity.get("clears_slo") else "\u00d7",
            "status": display_state,
            "baseline_cost_usd": round(float(total_spend or 0.0), 6),
            "rank": rank,
            "opportunity_id": opportunity.get("opportunity_id"),
            "agent": opportunity.get("agent"),
            "dimension": opportunity.get("dimension"),
            "seam": seam,
            "target": target,
            "fix": f"{seam} \u2192 {target}",
            "saving": round(float(opportunity.get("saving") or 0.0), 6),
            "effect": round(float(opportunity.get("effect") or 0.0), 4),
            "apply_mode_label": apply_mode_label,
            "autonomy_ceiling": opportunity.get("autonomy_ceiling"),
            "clears_slo": bool(opportunity.get("clears_slo")),
            "clears_slo_label": "\u2713" if opportunity.get("clears_slo") else "\u00d7",
            "governed_state": governed_state,
            "applied_state": applied_state,
            "display_state": display_state,
            "total_spend": round(float(total_spend or 0.0), 6),
            "computed_at": now,
        })

    rows.append({
        "id": f"slo::{tenant_id}",
        "type": "slo_policy",
        "tenantId": tenant_id,
        # Same stable-schema projection used above. These columns are interpreted
        # only when type="slo_policy"; their DAX measures remain strongly filtered.
        "baseline_cost_usd": float(slo.get("slo", 0.0)),
        "actual_cost_usd": float(slo.get("min_confidence", 0.0)),
        "saving_usd": float(slo.get("min_effect", 0.0)),
        "method": slo.get("by") or "default",
        "slo": float(slo.get("slo", 0.0)),
        "min_confidence": float(slo.get("min_confidence", 0.0)),
        "min_effect": float(slo.get("min_effect", 0.0)),
        "by": slo.get("by") or "default",
        "computed_at": now,
    })
    for order, (label, value) in enumerate((
        ("1 · Quality gate (e2e_quality ≥)", f"{float(slo.get('slo', 0.0)):g}"),
        ("2 · Min confidence", f"{100 * float(slo.get('min_confidence', 0.0)):.1f}%"),
        ("3 · Min effect", f"{100 * float(slo.get('min_effect', 0.0)):.1f}%"),
        ("4 · Source", str(slo.get("by") or "default")),
    ), start=1):
        rows.append({
            "id": f"slometric::{tenant_id}::{order}",
            "type": "slo_metric",
            "tenantId": tenant_id,
            "order": order,
            "title": label,
            "evidence_line": value,
            "computed_at": now,
        })
    return rows


# The optimizations the report can switch between. model-selection is measured
# (counterfactual) and memory-retention is measured (telemetry); tool-call-dedup is a
# GOVERNED-path fix (a human-reviewed prompt/code PR, not an in-app policy) so it carries
# no measured before/after here — its turn-grain *estimate* lives on the Discovered
# Opportunities page (the notebook analyst's recommendation_card). Scenario-keyed, stored
# under one reserved `_global_optimizations` partition key (NOT a tenant -- see the note by
# MEMORY_PARTITION) so the report slices on `scenario`, never on tenant.
MEASUREMENT_PARTITION = "_global_optimizations"
OPTIMIZATION_SCENARIOS = [
    ("model-selection", "Capability-tiered model selection", "counterfactual"),
    ("memory-retention", "Memory retention (prune superseded)", "telemetry"),
    ("tool-call-dedup", "Redundant tool-call dedup", "governed"),
]


def _policy_status(db, scenario: str, tenant_id: str | None = None) -> str:
    try:
        policy_id = f"{tenant_id}::{scenario}" if tenant_id else scenario
        p = db.get_container_client("OptimizationPolicies").read_item(policy_id, scenario)
        return p.get("status", "not_proposed")
    except Exception:  # noqa: BLE001
        return "not_proposed"


def build_optimization_result_rows(db) -> list[dict]:
    """Measured before/after impact per OPTIMIZATION (scenario), not per tenant.

    Emits one flat ``optimization_result`` row per applyable scenario under a reserved
    ``_global_optimizations`` partition, so a Power BI slicer on ``scenario`` switches between
    optimizations. model-selection carries a real **counterfactual** measurement (price
    each captured turn under the model it actually ran on vs. the all-premium baseline,
    across all tenants); memory-retention carries a real **telemetry** measurement (input
    tokens recalls avoided by dropping pruned memories); tool-call-dedup is a **governed**-path
    row (a prompt/code PR, not an in-app policy) so it has no measured before/after here — its
    turn-grain estimate lives on the Discovered Opportunities page. Keyed by scenario + measured
    analytically — the tenant is never the axis for "which optimization am I looking at".
    """
    from src.app.services.controlled_demo4 import evaluate_controlled_demo4

    now = _now()
    evaluation = evaluate_controlled_demo4(db, "analytics")
    measurement = evaluation.get("measurement")
    rows: list[dict] = []
    for scenario, title, method in OPTIMIZATION_SCENARIOS:
        row = {
            "id": f"result::{scenario}",
            "type": "optimization_result", "tenantId": MEASUREMENT_PARTITION,
            "scenario": scenario, "title": title, "method": method,
            "policy_status": _policy_status(
                db, scenario, "analytics" if scenario == "model-selection" else None
            ),
            "computed_at": now,
        }
        if scenario == "model-selection":
            row.update({
                "method": "Measured",
                "measurement_kind": "Measured",
                "measurement_scope": "Analytics controlled after burst",
                "measurement_tenant": "analytics",
                "measurement_status": evaluation["measurement_status"],
                "dataset_phase": evaluation["dataset_phase"],
                "display_state": evaluation["display_state"],
                "state_valid": evaluation["state_valid"],
                "state_reason": evaluation["state_reason"],
                "turns": 0,
            })
            if evaluation["measurement_status"] == "measured" and measurement is not None:
                row.update(measurement)
                row["turns"] = measurement["observed_count"]
        elif scenario == "memory-retention":
            # Measured from recall telemetry: the input tokens recalls avoided by dropping
            # pruned (superseded) memories from their top-k, priced at the default input rate.
            # Not a before/after re-price — reads $0 until the policy is applied and recalls run.
            from src.app.services import optimization_recommendations as rec
            ms = rec._memory_recall_savings()
            row.update({
                "turns": ms["recalls"],
                "baseline_cost_usd": 0.0, "actual_cost_usd": 0.0,
                "saving_usd": ms["saving_usd"], "saving_pct": 0.0,
                "measurement_kind": "Measured",
                "measurement_status": "measured",
                "measurement_scope": "Global memory recall telemetry",
                "scope_label": "Global",
                "avoided_recall_tokens": ms["avoided_tokens"],
                "note": ("Measured from recall telemetry — input tokens avoided by dropping "
                         "pruned memories from a recall's top-k. Reads $0 until the memory-"
                         "retention policy is applied and recalls run."),
            })
        else:
            row.update({
                "turns": 0,
                "measurement_kind": "Governed",
                "measurement_status": "missing",
                "note": ("Governed-path fix (human-reviewed prompt/code PR) - no in-app policy "
                         "to apply, so no measured before/after here; see the turn-grain estimate "
                         "on the Discovered Opportunities page."),
            })
        rows.append(row)
    return rows


def build_memory_intelligence_rows(db) -> list[dict]:
    """Memory-health signals over the ``memories`` container, flattened to insight rows
    (memory_kpi / memory_type / memory_salience / memory_health) — the reference twin of the
    notebook's Section 6. Global (not tenant-scoped): memories are keyed by user_id/thread_id,
    so these rows live under the reserved ``_global_memory`` partition."""
    now = _now()
    try:
        items = list(db.get_container_client("memories").query_items(
            "SELECT c.salience, c.type, c.superseded_by FROM c", enable_cross_partition_query=True))
    except Exception:
        return []
    total = len(items)
    if total == 0:
        return []

    # Salience tier thresholds come from the Configuration container (type="memory_config") —
    # the single source of truth shared with the notebook, so the tiers never drift. Falls
    # back to the built-in defaults if the row isn't seeded.
    hi, med = 0.8, 0.5
    try:
        cfg = list(db.get_container_client("Configuration").query_items(
            "SELECT * FROM c WHERE c.type='memory_config'", enable_cross_partition_query=True))
        if cfg:
            hi = float(cfg[0].get("salience_high", hi))
            med = float(cfg[0].get("salience_medium", med))
    except Exception:
        pass
    high_l, med_l, low_l = f"High (>={hi})", f"Medium ({med}-{hi})", f"Low (<{med})"
    # Some memory types (e.g. procedural guidance rules) carry no salience score. NULL salience
    # is its own "Unscored" tier in BOTH breakdowns below — never folded into "Low"/"Low-value" —
    # so the salience and health views stay consistent and unscored memories aren't mistaken for
    # weak ones. The salience KPIs (avg/rates) are computed over SCORED memories only.
    unscored_l = "Unscored"

    def _tier(s) -> str:
        if s is None:
            return unscored_l
        return high_l if s >= hi else med_l if s >= med else low_l

    def _health(m: dict) -> str:
        if m.get("superseded_by"):
            return "Superseded"
        s = m.get("salience")
        if s is None:
            return unscored_l
        return "Low-value" if s < med else "Active"

    scored = [m for m in items if m.get("salience") is not None]
    n_scored = len(scored)
    superseded = sum(1 for m in items if m.get("superseded_by"))
    low = sum(1 for m in scored if m["salience"] < med)
    avg_sal = round(sum(m["salience"] for m in scored) / n_scored, 3) if n_scored else 0.0

    rows = [{
        "id": f"memkpi::{MEMORY_PARTITION}", "type": "memory_kpi", "tenantId": MEMORY_PARTITION,
        "total_memories": total, "scored_memories": n_scored, "avg_salience": avg_sal,
        "supersession_rate": round(100 * superseded / max(total, 1), 1),
        "low_salience_rate": round(100 * low / max(n_scored, 1), 1), "computed_at": now,
    }]

    def _buckets(keyfn, rowtype: str) -> list[dict]:
        counts: dict[str, int] = {}
        for m in items:
            k = str(keyfn(m))
            counts[k] = counts.get(k, 0) + 1
        return [{
            "id": f"{rowtype}::{MEMORY_PARTITION}::{k}", "type": rowtype, "tenantId": MEMORY_PARTITION,
            "label": k,
            "title": k.replace("_", " ").title(),
            "count": v,
            "evidence_line": f"{v:,} · {100 * v / total:.1f}%",
            "computed_at": now,
        } for k, v in counts.items()]

    rows += _buckets(lambda m: m.get("type", "unknown"), "memory_type")
    rows += _buckets(lambda m: _tier(m.get("salience")), "memory_salience")
    rows += _buckets(_health, "memory_health")
    return rows



def _delete_partition_rows(container: Any, tenant_id: str) -> int:
    from src.app.services.controlled_demo4 import FIXTURE_VERSION

    rows = list(container.query_items(
        query=(
            "SELECT c.id, c.fixture_version, c.controlled_namespace "
            "FROM c WHERE c.tenantId=@tenant"
        ),
        parameters=[{"name": "@tenant", "value": tenant_id}],
        enable_cross_partition_query=True,
    ))
    namespace_tenant = (
        "shared" if tenant_id.startswith("_global_") else tenant_id
    )
    controlled = [
        row for row in rows
        if row.get("fixture_version") == FIXTURE_VERSION
        and row.get("controlled_namespace")
        == f"{FIXTURE_VERSION}:derived:{namespace_tenant}"
    ]
    for row in controlled:
        container.delete_item(item=row["id"], partition_key=tenant_id)
    return len(controlled)


def _delete_recomputable_governance_rows(container: Any, tenant_id: str) -> int:
    """Delete only explicitly derived governance rows, never human-owned state."""
    from src.app.services.controlled_demo4 import FIXTURE_VERSION

    rows = list(container.query_items(
        query=(
            "SELECT c.id, c.type, c.fixture_version, c.controlled_namespace "
            "FROM c WHERE c.tenantId=@tenant"
        ),
        parameters=[{"name": "@tenant", "value": tenant_id}],
        enable_cross_partition_query=True,
    ))
    derived = [
        row for row in rows
        if row.get("type") in RECOMPUTABLE_GOVERNANCE_TYPES
        and row.get("fixture_version") == FIXTURE_VERSION
        and row.get("controlled_namespace")
        == f"{FIXTURE_VERSION}:derived:{tenant_id}"
    ]
    for row in derived:
        container.delete_item(item=row["id"], partition_key=tenant_id)
    return len(derived)


def _tenant_rows(tenant_id: str) -> list[dict]:
    rows: list[dict] = []
    rows += build_insight_rows(tenant_id)
    rows += build_agent_opportunity_rows(tenant_id)
    rows += build_recommendation_rows(tenant_id)
    return rows


def _controlled_state_row(db: Any, tenant_id: str) -> dict:
    """Project the source-derived controlled state into the report snapshot."""
    from src.app.services.controlled_demo4 import (
        assert_evaluation_schema,
        evaluate_controlled_demo4,
    )

    state = evaluate_controlled_demo4(db, tenant_id)
    assert_evaluation_schema(state)
    return {
        "id": f"state::{tenant_id}",
        "type": "controlled_demo4_state",
        "tenantId": tenant_id,
        "policy_status": state["policy_status"],
        "dataset_phase": state["dataset_phase"],
        "display_state": state["display_state"],
        "state_valid": bool(state["state_valid"]),
        "state_reason": state["state_reason"],
        "measurement_status": state["measurement_status"],
        "fixture_version": state["fixture_version"],
        "burst_version": state["burst_version"],
        "burst_anchor": state["burst_anchor"],
        "burst_window_minutes": state["burst_window_minutes"],
        "baseline_expected_count": int(state["baseline_expected_count"]),
        "baseline_observed_count": int(state["baseline_observed_count"]),
        "burst_expected_count": int(state["burst_expected_count"]),
        "burst_observed_count": int(state["burst_observed_count"]),
        "model_counts_json": json.dumps(state["model_counts"], sort_keys=True),
        "computed_at": _now(),
    }


def recompute_controlled_demo4(db: Any = None) -> dict:
    """Replace controlled tenant rows in Analytics/shared/Marvel order using existing containers."""
    if db is None:
        from src.app.services import azure_cosmos_db as _cosmos
        db = _cosmos.database
    if db is None:
        raise RuntimeError("Cosmos database is not configured")

    insights = db.get_container_client(INSIGHTS_CONTAINER)
    governance = db.get_container_client("OptimizationGovernance")

    from src.app.services.controlled_demo4 import FIXTURE_VERSION

    analytics_rows = _tenant_rows("analytics") + [_controlled_state_row(db, "analytics")]
    shared_rows = build_optimization_result_rows(db) + build_memory_intelligence_rows(db)
    for row in analytics_rows:
        row["fixture_version"] = FIXTURE_VERSION
        row["controlled_namespace"] = f"{FIXTURE_VERSION}:derived:analytics"
    for row in shared_rows:
        row["fixture_version"] = FIXTURE_VERSION
        row["controlled_namespace"] = f"{FIXTURE_VERSION}:derived:shared"
    deleted = {
        "analytics_insights": _delete_partition_rows(insights, "analytics"),
        "analytics_governance": _delete_recomputable_governance_rows(
            governance, "analytics"
        ),
        "shared_optimizations": _delete_partition_rows(insights, MEASUREMENT_PARTITION),
        "shared_memory": _delete_partition_rows(insights, MEMORY_PARTITION),
    }
    for row in analytics_rows:
        insights.upsert_item(row)
    for row in shared_rows:
        insights.upsert_item(row)

    marvel_rows = _tenant_rows("marvel") + [_controlled_state_row(db, "marvel")]
    for row in marvel_rows:
        row["fixture_version"] = FIXTURE_VERSION
        row["controlled_namespace"] = f"{FIXTURE_VERSION}:derived:marvel"
    deleted["marvel_insights"] = _delete_partition_rows(insights, "marvel")
    deleted["marvel_governance"] = _delete_recomputable_governance_rows(
        governance, "marvel"
    )
    for row in marvel_rows:
        insights.upsert_item(row)

    all_rows = analytics_rows + shared_rows + marvel_rows
    by_type: dict[str, int] = {}
    for row in all_rows:
        by_type[row["type"]] = by_type.get(row["type"], 0) + 1
    return {
        "tenants": ["analytics", "marvel"],
        "order": ["analytics", "shared", "marvel"],
        "shared_written_once": True,
        "rows_written": len(all_rows),
        "deleted": deleted,
        "by_type": by_type,
    }


def recompute_insights(tenant_id: str, db: Any = None) -> dict:
    """Compatibility entry point; controlled tenants always use the safe two-tenant order."""
    if tenant_id in {"analytics", "marvel"}:
        return recompute_controlled_demo4(db)
    raise ValueError(f"unsupported controlled recompute tenant: {tenant_id}")

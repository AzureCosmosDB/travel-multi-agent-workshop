"""
Reverse-ETL reference — compute business-impact insights, write them back to Cosmos.

This is the **reference / maintainer** implementation of the reverse-ETL step the
workshop teaches in the Fabric module. The workshop version runs in a **Fabric Spark
notebook** over the mirrored tables; this Python version reuses the *same tested*
app logic (build_*_diagnostic) reading Cosmos directly, so we can populate and verify
``OptimizationInsights`` (and the Power BI page) without a Fabric run.

It flattens the funnel / agent-path / memory diagnostics into small, flat
``OptimizationInsights`` rows (one value per row) so they mirror cleanly to Fabric and
the report reads them with trivial DAX:

  {type:"funnel_stage",      tenantId, stage, stage_order, sessions}
  {type:"abandonment_cause", tenantId, cause, sessions}
  {type:"conversion_kpi",    tenantId, engaged, confirmed, conversion_rate,
                             wasted_pct, tokens_per_outcome, biggest_leak}
  {type:"agent_path_cost",   tenantId, agent_path, turns, total_tokens, avg_tokens}
  {type:"agent_scorecard",   tenantId, agent, dimension, dim_status, agent_status, cost, cost_share, ...}
  {type:"memory_retention",  tenantId, total_memories, superseded_memories, superseded_pct}

Usage (repo root; Cosmos via DefaultAzureCredential):
  python analytics/fabric/compute_insights.py --tenant analytics
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.disable(logging.INFO)

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "02_completed" / "python"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from azure.cosmos import CosmosClient, PartitionKey  # noqa: E402
from azure.identity import DefaultAzureCredential  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

# Resolve the deployed Cosmos endpoint: an already-set COSMOSDB_ENDPOINT (e.g. exported
# by azd) > a .env in the current dir > either workshop tree's python/.env. _APP stays on
# sys.path above because this reference reverse-ETL reuses the app's tested logic.
if not os.environ.get("COSMOSDB_ENDPOINT"):
    for _env_path in [Path.cwd() / ".env", _APP / ".env", _REPO / "01_exercises" / "python" / ".env"]:
        if _env_path.exists():
            load_dotenv(_env_path)
            if os.environ.get("COSMOSDB_ENDPOINT"):
                break

INSIGHTS_CONTAINER = "OptimizationInsights"

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
    policy ``status`` is re-stamped live by the app on read — analysis is
    analytical, but acting (apply/revert) stays operational.
    """
    from src.app.services import optimization_recommendations as rec

    now = _now()
    rows: list[dict] = []
    for order, card in enumerate(rec.build_recommendations(tenant_id)):
        rows.append({
            "id": f"reccard::{tenant_id}::{card.get('scenario')}",
            "type": "recommendation_card", "tenantId": tenant_id,
            "scenario": card.get("scenario"), "scenario_id": card.get("scenario_id"),
            "order": order,
            # Flat display fields so BI can render the card without reaching into
            # the nested `card` object — nested fields don't surface cleanly over
            # the Fabric mirror / DirectQuery. Consumed by the HTML-card measure
            # in PowerBI_Optimization_Build_Guide.md (Page 3).
            "title": card.get("title"),
            "dimension": card.get("dimension"),
            "apply_mode": card.get("apply_mode") or "policy",
            "maturity": card.get("maturity"),
            "estimated_saving_usd": card.get("estimated_saving_usd") or 0,
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


def _policy_status(db, scenario: str) -> str:
    try:
        p = db.get_container_client("OptimizationPolicies").read_item(scenario, scenario)
        return p.get("status", "not_proposed")
    except Exception:  # noqa: BLE001
        return "not_proposed"


def _model_selection_counterfactual(db) -> tuple[int, float, float]:
    """Counterfactual over ALL captured turns (every tenant): price each turn under the
    model it actually ran on vs. the all-premium baseline (gpt-5.1). Returns
    (turns, baseline_cost, actual_cost)."""
    from src.app.services import optimization_recommendations as rec

    pricing = rec.load_pricing()
    baseline = pricing.get("gpt-5.1", {"input": 1.25, "output": 10.00})
    turns = list(db.get_container_client("OptimizationTurns").query_items(
        query="SELECT c.model_deployment, c.model_name, c.input_tokens, c.output_tokens FROM c",
        enable_cross_partition_query=True,
    ))
    actual_cost = baseline_cost = 0.0
    for d in turns:
        i = int(d.get("input_tokens") or 0)
        o = int(d.get("output_tokens") or 0)
        dep = d.get("model_deployment") or d.get("model_name") or "gpt-5.1"
        pin, pout = rec._price_for(pricing, dep)
        actual_cost += (i * pin + o * pout) / 1_000_000
        baseline_cost += (i * baseline["input"] + o * baseline["output"]) / 1_000_000
    return len(turns), baseline_cost, actual_cost


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
    now = _now()
    n, baseline_cost, actual_cost = _model_selection_counterfactual(db)
    saving = baseline_cost - actual_cost
    rows: list[dict] = []
    for scenario, title, method in OPTIMIZATION_SCENARIOS:
        row = {
            "id": f"result::{scenario}",
            "type": "optimization_result", "tenantId": MEASUREMENT_PARTITION,
            "scenario": scenario, "title": title, "method": method,
            "status": _policy_status(db, scenario), "computed_at": now,
        }
        if scenario == "model-selection":
            row.update({
                "turns": n,
                "baseline_cost_usd": round(baseline_cost, 4),
                "actual_cost_usd": round(actual_cost, 4),
                "saving_usd": round(saving, 4),
                "saving_pct": round(100 * saving / baseline_cost, 1) if baseline_cost else 0.0,
            })
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
                "avoided_recall_tokens": ms["avoided_tokens"],
                "note": ("Measured from recall telemetry — input tokens avoided by dropping "
                         "pruned memories from a recall's top-k. Reads $0 until the memory-"
                         "retention policy is applied and recalls run."),
            })
        else:
            row.update({
                "turns": 0, "baseline_cost_usd": 0.0, "actual_cost_usd": 0.0,
                "saving_usd": 0.0, "saving_pct": 0.0,
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
            "label": k, "count": v, "computed_at": now,
        } for k, v in counts.items()]

    rows += _buckets(lambda m: m.get("type", "unknown"), "memory_type")
    rows += _buckets(lambda m: _tier(m.get("salience")), "memory_salience")
    rows += _buckets(_health, "memory_health")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Reverse-ETL: compute insights -> OptimizationInsights.")
    ap.add_argument("--tenant", required=True)
    args = ap.parse_args()

    endpoint = os.environ["COSMOSDB_ENDPOINT"]
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)
    container = db.create_container_if_not_exists(
        id=INSIGHTS_CONTAINER, partition_key=PartitionKey(path="/tenantId"))

    rows = build_insight_rows(args.tenant)
    for r in rows:
        container.upsert_item(r)
    kinds: dict[str, int] = {}
    for r in rows:
        kinds[r["type"]] = kinds.get(r["type"], 0) + 1
    print(f"✅ reverse-ETL wrote {len(rows)} insight rows for '{args.tenant}': {kinds}")

    # Also reverse-ETL the recommendation *cards* + turn metrics the Optimization
    # Console reads, so it no longer recomputes aggregations from Cosmos per request.
    rec_rows = build_recommendation_rows(args.tenant)
    for r in rec_rows:
        container.upsert_item(r)
    rec_kinds: dict[str, int] = {}
    for r in rec_rows:
        rec_kinds[r["type"]] = rec_kinds.get(r["type"], 0) + 1
    print(f"✅ reverse-ETL wrote {len(rec_rows)} recommendation rows for '{args.tenant}': {rec_kinds}")

    # Measure before/after impact per OPTIMIZATION (scenario-keyed, all tenants).
    res_rows = build_optimization_result_rows(db)
    for r in res_rows:
        container.upsert_item(r)
    ms = next((r for r in res_rows if r["scenario"] == "model-selection"), {})
    print(f"✅ reverse-ETL wrote {len(res_rows)} optimization_result rows (scenario-keyed): "
          f"model-selection turns={ms.get('turns')} saving=${ms.get('saving_usd')} ({ms.get('saving_pct')}% vs all-premium baseline)")

    # Memory intelligence rows (memory_kpi / memory_type / memory_salience / memory_health)
    # for the Power BI Memory Intelligence page — twin of the notebook's Section 6.
    mem_rows = build_memory_intelligence_rows(db)
    for r in mem_rows:
        container.upsert_item(r)
    if mem_rows:
        mk = next((r for r in mem_rows if r["type"] == "memory_kpi"), {})
        print(f"✅ reverse-ETL wrote {len(mem_rows)} memory rows (_global_memory): "
              f"total={mk.get('total_memories')} avg_salience={mk.get('avg_salience')} "
              f"superseded={mk.get('supersession_rate')}%")


if __name__ == "__main__":
    main()

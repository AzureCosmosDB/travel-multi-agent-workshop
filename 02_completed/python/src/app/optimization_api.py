"""
Optimization apply-loop REST surface.

The dashboard-facing API for the analytics optimization loop:

    GET  /optimizations/{tenantId}          -> candidate cards (recommend)
    GET  /optimizations/{tenantId}/metrics  -> aggregate KPIs (Console tiles)
    GET  /optimizations/policies            -> all policy docs + status
    GET  /optimizations/{scenario}/policy   -> one policy doc
    POST /optimizations/{scenario}/propose  -> register proposed policy (no effect)
    POST /optimizations/{scenario}/apply    -> activate (one-click apply)
    POST /optimizations/{scenario}/revert   -> roll back (one-click revert)

Apply/revert only flip a small, versioned, reversible policy document that the
running app reads per turn — never a code change — which is what makes these
lower-risk optimizations safe to automate (maturity Level 4/5).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.app.services import optimization_policy
from src.app.services import fabric_capacity
from src.app.services import demo_data
from src.app.services.optimization_recommendations import (
    build_recommendations,
    build_turn_metrics,
    read_recommendations_from_insights,
    read_metrics_from_insights,
    read_optimization_result_from_insights,
    read_conversion_from_insights,
    read_memory_insights,
    read_agent_paths_from_insights,
    build_turns_timeline,
    count_confirmed_trips,
    get_proposed_model_selection_params,
    apply_memory_retention,
    revert_memory_retention,
    PROPOSED_MEMORY_RETENTION_PARAMS,
    MODEL_SELECTION_SCENARIO,
    TOOL_DEDUP_SCENARIO,
    MEMORY_RETENTION_SCENARIO,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/optimizations", tags=["optimizations"])

# Known scenario -> default proposed params provider, so /propose can seed
# without a body. Model selection reads the config-driven defaults at call time.
_SCENARIO_DEFAULT_PROVIDERS: dict[str, Any] = {
    MODEL_SELECTION_SCENARIO: get_proposed_model_selection_params,
    MEMORY_RETENTION_SCENARIO: lambda: dict(PROPOSED_MEMORY_RETENTION_PARAMS),
}

_SCENARIO_META: dict[str, dict[str, str]] = {
    MODEL_SELECTION_SCENARIO: {
        "scenario_id": "model-selection",
        "title": "Capability-tiered model selection",
    },
    MEMORY_RETENTION_SCENARIO: {
        "scenario_id": "memory-retention",
        "title": "Memory retention (prune stale memories)",
    },
    TOOL_DEDUP_SCENARIO: {
        "scenario_id": "tool-call-dedup",
        "title": "Redundant tool calls",
    },
}


class ProposeBody(BaseModel):
    params: Optional[dict[str, Any]] = None
    by: str = "analytics"


class ActionBody(BaseModel):
    by: str = "dashboard"


@router.get("/policies")
def list_policies() -> dict[str, Any]:
    # `capabilities` lets the portal feature-detect optional server actions (e.g. the
    # in-process insights recompute below, present on the completed solution) and hide
    # controls the running API doesn't support — so the shared portal stays clean when
    # served against the workshop scaffold.
    return {"policies": optimization_policy.list_policies(),
            "capabilities": {"recompute_insights": True, "reset_state": True, "generate_traffic": True}}


# --- Fabric capacity control (pause/resume the analytics infra to stop the meter) ---
@router.get("/fabric/capacity")
def fabric_capacity_status() -> dict[str, Any]:
    """Current Fabric capacity state, or {configured:false} if no capacity is wired up."""
    try:
        return fabric_capacity.get_status()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Fabric capacity status failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Fabric capacity query failed: {exc}")


@router.post("/fabric/capacity/suspend")
def fabric_capacity_suspend() -> dict[str, Any]:
    """Pause the Fabric capacity to stop billing."""
    try:
        return fabric_capacity.suspend()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Fabric capacity suspend failed: {exc}")


@router.post("/fabric/capacity/resume")
def fabric_capacity_resume() -> dict[str, Any]:
    """Resume the Fabric capacity (needed to refresh the analytics)."""
    try:
        return fabric_capacity.resume()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Fabric capacity resume failed: {exc}")


# --- Demo convenience: freshen the captured turns' timestamps ---
@router.post("/demo/refresh-times")
def refresh_demo_times(window_minutes: int = 120) -> dict[str, Any]:
    """Re-stamp captured OptimizationTurns into the last ``window_minutes`` so the
    analytics report's time-series charts show a recent, dense trend without a full
    reseed. Timestamps only — the KPIs/costs are time-independent and unchanged."""
    try:
        return demo_data.refresh_turn_times(window_minutes)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Refresh demo times failed: {exc}")


# --- In-process reverse-ETL: (re)build the OptimizationInsights snapshot, no Fabric ---
@router.post("/insights")
def recompute_insights(tenant: str = "analytics") -> dict[str, Any]:
    """Recompute the ``OptimizationInsights`` snapshot for ``tenant`` in-process and upsert
    it to Cosmos — the same reverse-ETL the Module-09 Fabric notebook performs, but computed
    from Cosmos alone (no Fabric, mirror, or Spark). Populates the Business, Memory, and
    Governance views, which read the snapshot. Mirrors analytics/fabric/compute_insights.py."""
    try:
        from src.app.services import optimization_insights
        return optimization_insights.recompute_insights(tenant)
    except Exception as exc:  # noqa: BLE001
        logger.exception("insights recompute failed")
        raise HTTPException(status_code=500, detail=f"Insights recompute failed: {exc}")


# --- Reset the runtime optimization state (governance + insights) for a clean demo ---
@router.post("/reset")
def reset_optimization(tenant: Optional[str] = None) -> dict[str, Any]:
    """Reset the demo to a clean 'before-optimization' state: clear runtime state —
    OptimizationGovernance (stale approvals) + OptimizationInsights (stale snapshot) — AND
    normalize every captured turn back to the single-premium baseline (so the model donut shows
    one model and 'apply model-selection -> tier' reads as a clean before/after). Does NOT touch
    tokens, the funnel signal, or app data. Follow with POST /optimizations/insights to rebuild
    the snapshot."""
    try:
        cleared = demo_data.reset_optimization_state(tenant)
        baseline = demo_data.restore_baseline_turns(tenant)
        return {**cleared, "baseline": baseline}
    except Exception as exc:  # noqa: BLE001
        logger.exception("optimization reset failed")
        raise HTTPException(status_code=500, detail=f"Optimization reset failed: {exc}")


# --- Generate synthetic traffic (policy-aware) to drive the apply -> re-measure loop ---
@router.post("/traffic")
def generate_demo_traffic(tenant: str = "analytics", count: int = 150, minutes: int = 5) -> dict[str, Any]:
    """Write a burst of synthetic turns (policy-aware: baseline single-model until model-selection
    is applied, capability-tiered once active) into the last ``minutes``, dual-writing Debug +
    OptimizationTurns so every live view reflects it. In-process equivalent of
    analytics/scripts/traffic_simulator.py --mode direct."""
    try:
        return demo_data.generate_traffic(tenant, count=count, minutes=minutes)
    except Exception as exc:  # noqa: BLE001
        logger.exception("traffic generation failed")
        raise HTTPException(status_code=500, detail=f"Traffic generation failed: {exc}")


@router.get("/{tenant_id}")
def get_recommendations(tenant_id: str, source: str = "auto") -> dict[str, Any]:
    """Candidate optimization cards mined from the tenant's captured signal.

    ``source`` controls where the aggregations come from:
      - ``auto`` (default): the Fabric-computed cards reverse-ETL'd into
        OptimizationInsights when present, otherwise an in-app compute.
      - ``fabric``: only the reverse-ETL'd cards (may be empty until the loop runs).
      - ``live``: always recompute in-app (the Module-07 "peek" / offline dev path).
    """
    recs = None
    used = "live"
    if source in ("auto", "fabric"):
        recs = read_recommendations_from_insights(tenant_id)
        if recs is not None:
            used = "fabric"
    if recs is None:
        if source == "fabric":
            recs, used = [], "fabric"
        else:
            recs, used = build_recommendations(tenant_id), "live"
    return {"tenant_id": tenant_id, "source": used, "recommendations": recs}


@router.get("/{tenant_id}/metrics")
def get_metrics(tenant_id: str, source: str = "auto") -> dict[str, Any]:
    """Aggregate KPIs for the Optimization Console (turns, cost, tiers, outcomes).

    Prefers the Fabric-computed (reverse-ETL'd) metrics; falls back to an in-app
    compute. Pass ``source=live`` to force the in-app compute.
    """
    if source in ("auto", "fabric"):
        metrics = read_metrics_from_insights(tenant_id)
        if metrics is not None:
            return metrics
        if source == "fabric":
            return {"tenant_id": tenant_id, "source": "fabric",
                    "note": "no reverse-ETL metrics yet; run the analytics loop"}
    return build_turn_metrics(tenant_id)


@router.get("/{tenant_id}/result")
def get_optimization_result(tenant_id: str) -> dict[str, Any]:
    """Measured before/after impact of applied optimizations (counterfactual saving).

    Computed analytically (Fabric / reverse-ETL) and read here — keyed by scenario,
    not by tenant. Empty until the analytics loop has measured this tenant.
    """
    res = read_optimization_result_from_insights(tenant_id)
    if res is None:
        return {"tenant_id": tenant_id, "source": "fabric", "results": [],
                "note": "no measured result yet; run the analytics loop"}
    return res


@router.get("/{tenant_id}/turns_timeline")
def get_turns_timeline(tenant_id: str, bucket_seconds: int = 60) -> dict[str, Any]:
    """Per-bucket turn counts over time (the 'turns over time' line).

    Computed live from the captured turns (the same raw turns Power BI's
    ``OptimizationTurns[Turn Minute]`` line reads), bucketed by ``bucket_seconds``.
    """
    return build_turns_timeline(tenant_id, bucket_seconds)


@router.get("/{tenant_id}/confirmed_trips")
def get_confirmed_trips(tenant_id: str) -> dict[str, Any]:
    """Booked-trip outcomes for a tenant (Option A): count of Trip docs with status
    confirmed/completed, computed live and tenant-scoped. Matches the Power BI
    ``Confirmed Trips`` measure once it is tenant-scoped via TREATAS."""
    return {"tenant_id": tenant_id, "confirmed_trips": count_confirmed_trips(tenant_id), "source": "live"}


@router.get("/{tenant_id}/conversion")
def get_conversion(tenant_id: str) -> dict[str, Any]:
    """Conversion funnel, abandonment causes, and conversion KPI (reverse-ETL) —
    the same rows Power BI's Business Impact page reads. Empty until compute_insights runs."""
    res = read_conversion_from_insights(tenant_id)
    if res is None:
        return {"tenant_id": tenant_id, "source": "fabric", "funnel": [], "causes": [], "kpi": {},
                "note": "no conversion insights yet; run compute_insights / the notebook"}
    return res


@router.get("/{tenant_id}/memory")
def get_memory_insights(tenant_id: str) -> dict[str, Any]:
    """Memory-intelligence buckets + KPI (reverse-ETL) — the same rows Power BI's Memory
    page reads. Memory is global (keyed by user, not tenant); tenant is accepted for
    route symmetry. Empty until compute_insights runs."""
    res = read_memory_insights()
    if res is None:
        return {"tenant_id": tenant_id, "source": "fabric", "by_type": [], "salience": [], "health": [], "kpi": {},
                "note": "no memory insights yet; run compute_insights / the notebook"}
    return res


@router.get("/{tenant_id}/agent_paths")
def get_agent_paths(tenant_id: str) -> dict[str, Any]:
    """Agent-path cost concentration (reverse-ETL) — one row per agent_path with
    turns/total_tokens/avg_tokens/token_share. Empty until compute_insights runs."""
    res = read_agent_paths_from_insights(tenant_id)
    if res is None:
        return {"tenant_id": tenant_id, "source": "fabric", "total_tokens": 0, "paths": [],
                "note": "no agent-path insights yet; run compute_insights / the notebook"}
    return res


@router.get("/{scenario}/policy")
def get_scenario_policy(scenario: str) -> dict[str, Any]:
    doc = optimization_policy.get_policy(scenario)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No policy for scenario '{scenario}'")
    return doc


@router.post("/{scenario}/propose")
def propose(scenario: str, body: Optional[ProposeBody] = None) -> dict[str, Any]:
    body = body or ProposeBody()
    provider = _SCENARIO_DEFAULT_PROVIDERS.get(scenario)
    params = body.params or (provider() if provider else None)
    if params is None:
        raise HTTPException(
            status_code=400,
            detail=f"No default params for scenario '{scenario}'; supply params in the body.",
        )
    meta = _SCENARIO_META.get(scenario, {})
    doc = {
        "scenario": scenario,
        "scenario_id": meta.get("scenario_id"),
        "title": meta.get("title", scenario),
        "params": params,
        "gate": {"metric": "e2e_quality", "threshold": 4.0},
        "proposed_by": body.by,
    }
    saved = optimization_policy.propose_policy(doc)
    if saved is None:
        raise HTTPException(status_code=503, detail="Policy store unavailable")
    return saved


@router.post("/{scenario}/apply")
def apply(scenario: str, body: Optional[ActionBody] = None) -> dict[str, Any]:
    body = body or ActionBody()
    # tool-call-dedup is a MANUAL (human-deployed) prompt optimization: you review the diff
    # and deploy supervisor.prompty yourself, so there is no in-app apply. Governance is
    # recorded via /optimizations/agent/{tenant}/decision (Proposed→Approved→Deployed→Rolled back).
    if scenario == TOOL_DEDUP_SCENARIO:
        raise HTTPException(
            status_code=400,
            detail="This is a Manual (human-deployed) prompt optimization — review the diff and "
                   "deploy supervisor.prompty yourself; record governance via the decision endpoint. "
                   "There is no in-app apply.",
        )
    # Auto-seed a proposal if none exists yet, so apply is genuinely one-click.
    if optimization_policy.get_policy(scenario) is None:
        propose(scenario, ProposeBody(by=body.by))
    saved = optimization_policy.apply_policy(scenario, by=body.by)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"No policy to apply for '{scenario}'")
    # Memory retention applies a side effect: soft-prune superseded memories (reversible).
    if scenario == MEMORY_RETENTION_SCENARIO:
        saved["pruned_memories"] = apply_memory_retention()
    return saved


@router.post("/{scenario}/revert")
def revert(scenario: str, body: Optional[ActionBody] = None) -> dict[str, Any]:
    body = body or ActionBody()
    # tool-call-dedup is a MANUAL prompt optimization: nothing is applied in-app, so nothing
    # to revert here — a deployed prompt is rolled back via the decision endpoint (governance).
    if scenario == TOOL_DEDUP_SCENARIO:
        raise HTTPException(
            status_code=400,
            detail="This is a Manual (human-deployed) prompt optimization; there is no in-app "
                   "applied policy to revert — roll back via the decision endpoint (governance).",
        )
    saved = optimization_policy.revert_policy(scenario, by=body.by)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"No policy to revert for '{scenario}'")
    if scenario == MEMORY_RETENTION_SCENARIO:
        saved["restored_memories"] = revert_memory_retention()
    return saved

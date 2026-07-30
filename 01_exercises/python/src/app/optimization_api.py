"""
Optimization apply-loop REST surface (Module 07).

Mount it from your API with one line (Module 07):
    from src.app.optimization_api import router as optimization_router
    app.include_router(optimization_router)

Endpoints:
    GET  /optimizations/{tenantId}          -> candidate cards (recommend)
    GET  /optimizations/policies            -> all policy docs + status
    GET  /optimizations/{scenario}/policy   -> one policy doc
    POST /optimizations/{scenario}/propose  -> register proposed policy (no effect)
    POST /optimizations/{scenario}/apply    -> activate (one-click apply)
    POST /optimizations/{scenario}/revert   -> roll back (one-click revert)

Apply/revert only flip a small, versioned, reversible policy document that the
running app reads per turn — never a code change.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.app.services import optimization
from src.app.services import fabric_capacity

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/optimizations", tags=["optimizations"])

_SCENARIO_DEFAULT_PROVIDERS: dict[str, Any] = {
    optimization.MODEL_SELECTION_SCENARIO: optimization.get_proposed_model_selection_params,
    optimization.MEMORY_RETENTION_SCENARIO: lambda: dict(optimization.PROPOSED_MEMORY_RETENTION_PARAMS),
}
_SCENARIO_META: dict[str, dict[str, str]] = {
    optimization.MODEL_SELECTION_SCENARIO: {
        "scenario_id": "SCEN-007",
        "title": "Capability-tiered model selection",
    },
    optimization.MEMORY_RETENTION_SCENARIO: {
        "scenario_id": "SCEN-004",
        "title": "Memory retention (prune stale memories)",
    },
}


class ProposeBody(BaseModel):
    params: Optional[dict[str, Any]] = None
    by: str = "analytics"


class ActionBody(BaseModel):
    by: str = "dashboard"


@router.get("/policies")
def list_policies() -> dict[str, Any]:
    return {"policies": optimization.list_policies()}


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


@router.get("/{tenant_id}")
def get_recommendations(tenant_id: str, source: str = "auto") -> dict[str, Any]:
    """Candidate optimization cards.

    ``source``: ``auto`` (default) returns the Fabric-computed cards reverse-ETL'd
    into OptimizationInsights when present, else an in-app compute; ``fabric`` only
    the reverse-ETL'd cards (may be empty); ``live`` always recomputes in-app.
    """
    recs = None
    used = "live"
    if source in ("auto", "fabric"):
        recs = optimization.read_recommendations_from_insights(tenant_id)
        if recs is not None:
            used = "fabric"
    if recs is None:
        if source == "fabric":
            recs, used = [], "fabric"
        else:
            recs, used = optimization.build_recommendations(tenant_id), "live"
    return {"tenant_id": tenant_id, "source": used, "recommendations": recs}


@router.get("/{tenant_id}/metrics")
def get_metrics(tenant_id: str, source: str = "auto") -> dict[str, Any]:
    """Aggregate KPIs for the Optimization Console (turns, cost, tiers, outcomes).

    Prefers the Fabric-computed (reverse-ETL'd) metrics; falls back to in-app.
    Pass ``source=live`` to force the in-app compute.
    """
    if source in ("auto", "fabric"):
        metrics = optimization.read_metrics_from_insights(tenant_id)
        if metrics is not None:
            return metrics
        if source == "fabric":
            return {"tenant_id": tenant_id, "source": "fabric",
                    "note": "no reverse-ETL metrics yet; run the analytics loop"}
    return optimization.build_turn_metrics(tenant_id)


@router.get("/{scenario}/policy")
def get_scenario_policy(scenario: str) -> dict[str, Any]:
    doc = optimization.get_policy(scenario)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No policy for scenario '{scenario}'")
    return doc


@router.post("/{scenario}/propose")
def propose(scenario: str, body: Optional[ProposeBody] = None) -> dict[str, Any]:
    body = body or ProposeBody()
    provider = _SCENARIO_DEFAULT_PROVIDERS.get(scenario)
    params = body.params or (provider() if provider else None)
    if params is None:
        raise HTTPException(status_code=400, detail=f"No default params for scenario '{scenario}'; supply params.")
    meta = _SCENARIO_META.get(scenario, {})
    doc = {
        "scenario": scenario,
        "scenario_id": meta.get("scenario_id"),
        "title": meta.get("title", scenario),
        "params": params,
        "gate": {"metric": "e2e_quality", "threshold": 4.0},
        "proposed_by": body.by,
    }
    saved = optimization.propose_policy(doc)
    if saved is None:
        raise HTTPException(status_code=503, detail="Policy store unavailable")
    return saved


@router.post("/{scenario}/apply")
def apply(scenario: str, body: Optional[ActionBody] = None) -> dict[str, Any]:
    body = body or ActionBody()
    # Human-governed (prompt/code) scenarios cannot be runtime-applied — they must be staged.
    if scenario in (optimization.CITY_CONTEXT_SCENARIO, optimization.TOOL_DEDUP_SCENARIO):
        raise HTTPException(
            status_code=400,
            detail="This is a human-governed prompt change; use POST /optimizations/"
                   f"{scenario}/stage to produce a reviewable proposal (it is not applied at runtime).",
        )
    if optimization.get_policy(scenario) is None:
        propose(scenario, ProposeBody(by=body.by))
    saved = optimization.apply_policy(scenario, by=body.by)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"No policy to apply for '{scenario}'")
    # SCEN-004 applies a side effect: soft-prune superseded memories (reversible).
    if scenario == optimization.MEMORY_RETENTION_SCENARIO:
        saved["pruned_memories"] = optimization.apply_memory_retention()
    return saved


@router.post("/{scenario}/stage")
def stage(scenario: str, body: Optional[ActionBody] = None) -> dict[str, Any]:
    """Stage a human-governed (prompt/code) change for review. Does NOT change runtime."""
    body = body or ActionBody()
    saved = optimization.stage_prompt_change(scenario, by=body.by)
    if saved is None:
        raise HTTPException(
            status_code=400,
            detail=f"Scenario '{scenario}' is not a staged-change (human-governed) scenario.",
        )
    return saved


@router.post("/{scenario}/revert")
def revert(scenario: str, body: Optional[ActionBody] = None) -> dict[str, Any]:
    body = body or ActionBody()
    saved = optimization.revert_policy(scenario, by=body.by)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"No policy to revert for '{scenario}'")
    if scenario == optimization.MEMORY_RETENTION_SCENARIO:
        saved["restored_memories"] = optimization.revert_memory_retention()
    return saved

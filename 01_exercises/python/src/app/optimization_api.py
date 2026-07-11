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

_SCENARIO_DEFAULTS: dict[str, dict[str, Any]] = {
    optimization.MODEL_SELECTION_SCENARIO: optimization.PROPOSED_MODEL_SELECTION_PARAMS,
}
_SCENARIO_META: dict[str, dict[str, str]] = {
    optimization.MODEL_SELECTION_SCENARIO: {
        "scenario_id": "SCEN-007",
        "title": "Capability-tiered model selection",
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
def get_recommendations(tenant_id: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "recommendations": optimization.build_recommendations(tenant_id)}


@router.get("/{tenant_id}/metrics")
def get_metrics(tenant_id: str) -> dict[str, Any]:
    """Aggregate KPIs for the Optimization Console (turns, cost, tiers, outcomes)."""
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
    params = body.params or _SCENARIO_DEFAULTS.get(scenario)
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
    if scenario == optimization.CITY_CONTEXT_SCENARIO:
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
    return saved

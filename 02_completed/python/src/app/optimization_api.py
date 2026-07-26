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
from src.app.services.optimization_recommendations import (
    build_recommendations,
    build_turn_metrics,
    get_proposed_model_selection_params,
    get_city_context_staged_change,
    get_tool_dedup_staged_change,
    apply_memory_retention,
    revert_memory_retention,
    PROPOSED_MEMORY_RETENTION_PARAMS,
    MODEL_SELECTION_SCENARIO,
    CITY_CONTEXT_SCENARIO,
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
        "scenario_id": "SCEN-007",
        "title": "Capability-tiered model selection",
    },
    MEMORY_RETENTION_SCENARIO: {
        "scenario_id": "SCEN-004",
        "title": "Memory retention (prune stale memories)",
    },
    CITY_CONTEXT_SCENARIO: {
        "scenario_id": "SCEN-001",
        "title": "Active-trip city context",
    },
    TOOL_DEDUP_SCENARIO: {
        "scenario_id": "SCEN-008",
        "title": "Redundant tool calls",
    },
}

# Scenarios whose "apply" is a STAGED human-governed change (prompt/code), not a
# runtime toggle -> scenario -> provider of the proposed change (file + text).
_STAGED_CHANGE_PROVIDERS: dict[str, Any] = {
    CITY_CONTEXT_SCENARIO: get_city_context_staged_change,
    TOOL_DEDUP_SCENARIO: get_tool_dedup_staged_change,
}


class ProposeBody(BaseModel):
    params: Optional[dict[str, Any]] = None
    by: str = "analytics"


class ActionBody(BaseModel):
    by: str = "dashboard"


@router.get("/policies")
def list_policies() -> dict[str, Any]:
    return {"policies": optimization_policy.list_policies()}


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
    """Candidate optimization cards mined from the tenant's captured signal."""
    return {"tenant_id": tenant_id, "recommendations": build_recommendations(tenant_id)}


@router.get("/{tenant_id}/metrics")
def get_metrics(tenant_id: str) -> dict[str, Any]:
    """Aggregate KPIs for the Optimization Console (turns, cost, tiers, outcomes)."""
    return build_turn_metrics(tenant_id)


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
    # Human-governed (prompt/code) scenarios cannot be runtime-applied — they must be staged.
    if scenario in _STAGED_CHANGE_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail="This is a human-governed prompt change; use POST /optimizations/"
                   f"{scenario}/stage to produce a reviewable proposal (it is not applied at runtime).",
        )
    # Auto-seed a proposal if none exists yet, so apply is genuinely one-click.
    if optimization_policy.get_policy(scenario) is None:
        propose(scenario, ProposeBody(by=body.by))
    saved = optimization_policy.apply_policy(scenario, by=body.by)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"No policy to apply for '{scenario}'")
    # SCEN-004 applies a side effect: soft-prune superseded memories (reversible).
    if scenario == MEMORY_RETENTION_SCENARIO:
        saved["pruned_memories"] = apply_memory_retention()
    return saved


@router.post("/{scenario}/revert")
def revert(scenario: str, body: Optional[ActionBody] = None) -> dict[str, Any]:
    body = body or ActionBody()
    saved = optimization_policy.revert_policy(scenario, by=body.by)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"No policy to revert for '{scenario}'")
    if scenario == MEMORY_RETENTION_SCENARIO:
        saved["restored_memories"] = revert_memory_retention()
    return saved


@router.post("/{scenario}/stage")
def stage(scenario: str, body: Optional[ActionBody] = None) -> dict[str, Any]:
    """'Apply' for a human-governed change: record a STAGED proposal (never active).

    Staging a prompt/code optimization produces a reviewable diff for a human to
    merge via PR — it deliberately does NOT change runtime behavior (maturity L3).
    """
    body = body or ActionBody()
    provider = _STAGED_CHANGE_PROVIDERS.get(scenario)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Scenario '{scenario}' is not a staged change.")
    meta = _SCENARIO_META.get(scenario, {})
    doc = {
        "scenario": scenario,
        "scenario_id": meta.get("scenario_id"),
        "title": meta.get("title", scenario),
        "apply_mode": "staged_change",
        "proposed_change": provider(),
        "proposed_by": body.by,
    }
    saved = optimization_policy.stage_policy(doc)
    if saved is None:
        raise HTTPException(status_code=503, detail="Policy store unavailable")
    return saved

"""
Optimization apply-loop REST surface.

The dashboard-facing API for the analytics optimization loop:

    GET  /optimizations/{tenantId}          -> candidate cards (recommend)
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
from src.app.services.optimization_recommendations import (
    build_recommendations,
    PROPOSED_MODEL_SELECTION_PARAMS,
    MODEL_SELECTION_SCENARIO,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/optimizations", tags=["optimizations"])

# Known scenario -> default proposed params, so /propose can seed without a body.
_SCENARIO_DEFAULTS: dict[str, dict[str, Any]] = {
    MODEL_SELECTION_SCENARIO: PROPOSED_MODEL_SELECTION_PARAMS,
}

_SCENARIO_META: dict[str, dict[str, str]] = {
    MODEL_SELECTION_SCENARIO: {
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
    return {"policies": optimization_policy.list_policies()}


@router.get("/{tenant_id}")
def get_recommendations(tenant_id: str) -> dict[str, Any]:
    """Candidate optimization cards mined from the tenant's captured signal."""
    return {"tenant_id": tenant_id, "recommendations": build_recommendations(tenant_id)}


@router.get("/{scenario}/policy")
def get_scenario_policy(scenario: str) -> dict[str, Any]:
    doc = optimization_policy.get_policy(scenario)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"No policy for scenario '{scenario}'")
    return doc


@router.post("/{scenario}/propose")
def propose(scenario: str, body: Optional[ProposeBody] = None) -> dict[str, Any]:
    body = body or ProposeBody()
    params = body.params or _SCENARIO_DEFAULTS.get(scenario)
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
    # Auto-seed a proposal if none exists yet, so apply is genuinely one-click.
    if optimization_policy.get_policy(scenario) is None:
        propose(scenario, ProposeBody(by=body.by))
    saved = optimization_policy.apply_policy(scenario, by=body.by)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"No policy to apply for '{scenario}'")
    return saved


@router.post("/{scenario}/revert")
def revert(scenario: str, body: Optional[ActionBody] = None) -> dict[str, Any]:
    body = body or ActionBody()
    saved = optimization_policy.revert_policy(scenario, by=body.by)
    if saved is None:
        raise HTTPException(status_code=404, detail=f"No policy to revert for '{scenario}'")
    return saved

"""
Agent-centric optimization REST surface (ADR-0010) — the Console's API.

Separate from the (turn-centric) `optimization_api.py` so each stays small and focused.
This one speaks the *agents × dimensions* model of ADR-0010 and backs the evolved Console:

  GET  /optimizations/agent/{tenant}/scorecard      -> agent × dimension health (engine.scorecard)
  GET  /optimizations/agent/{tenant}/opportunities  -> discovered opportunities (engine.analyze), SLO-gated
  GET  /optimizations/agent/{tenant}/opportunity/{opportunity_id}/diff  -> staged diff to review (C2)
  GET  /optimizations/agent/{tenant}/decisions      -> the governance audit trail
  POST /optimizations/agent/{tenant}/decision       -> approve/reject/attest/confirm-revert (C1, C4)
  GET  /optimizations/agent/{tenant}/slo            -> the SLO/confidence/min-effect policy (C3)
  POST /optimizations/agent/{tenant}/slo            -> set it (C3)
  GET  /optimizations/agent/{tenant}/schema         -> learner-declared domain schemas (C5)
  POST /optimizations/agent/{tenant}/schema         -> declare one (C5)

The engine (`src.app.engine`) is pure-stdlib; this module wires it to Cosmos telemetry and
the governance audit store. It never invents savings — the engine computes them.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.app.engine import analyze, seams
from src.app.engine.core.costs import token_cost
from src.app.engine.core.schema import NodeExec
from src.app.engine.policy import Field, PolicySchema, bind_policy, discovery_manifest
from src.app.engine.scorecard import build_scorecard
from src.app.services import node_executions as ne
from src.app.services import optimization_governance as gov
from src.app.services import optimization_policy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/optimizations/agent", tags=["optimization-agent"])

_APP_DIR = os.path.dirname(os.path.abspath(__file__))          # .../src/app
_CODE_ALLOWLIST = ["travel_agents.py", "services/optimization.py"]  # read-only code-seam surface

_DECISION_KINDS = {"approve", "reject", "attest", "confirm-revert",
                   "staged", "unstaged", "applied", "reverted",  # legacy (pre-vocabulary)
                   "approved", "deployed", "rolled-back", "dismissed"}  # human-attested lifecycle
_TYPE_MAP = {"int": int, "float": float, "bool": bool, "str": str}


def _load_nodes(tenant_id: str, session_id: Optional[str] = None) -> list[NodeExec]:
    recs = ne.query_node_executions(tenant_id, session_id)
    out: list[NodeExec] = []
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


def _total_cost(nodes: list[NodeExec]) -> float:
    return sum(token_cost(n.model_deployment, n.input_tokens, n.output_tokens) for n in nodes)


def _config_pricing() -> dict[str, dict[str, float]]:
    """Existing Configuration pricing (per 1M tokens) mapped to the engine's per-1K
    ``{deployment: {"in", "out"}}`` format, so the Console scorecard cost matches the
    Power BI report (compute_insights) and the notebook — all pass the same pricing to
    ``build_scorecard`` instead of the engine's illustrative ``DEFAULT_PRICING``."""
    from src.app.services import optimization_recommendations as rec
    return {m: {"in": p.get("input", 0.0) / 1000.0, "out": p.get("output", 0.0) / 1000.0}
            for m, p in rec.load_pricing().items()}


def _opportunities(tenant_id: str) -> tuple[list[dict], float, dict]:
    """Discovered opportunities for a tenant + total spend + the SLO policy (engine-computed)."""
    nodes = _load_nodes(tenant_id)
    cards = analyze(nodes, seams.surface())
    total = _total_cost(nodes) or 0.0
    slo = gov.get_slo_policy(tenant_id)
    min_effect = float(slo.get("min_effect", gov.DEFAULT_SLO["min_effect"]))
    enriched: list[dict] = []
    for c in cards:
        c = dict(c)
        effect = (c["saving"] / total) if total else 0.0
        c["effect"] = round(effect, 4)
        c["clears_slo"] = effect >= min_effect          # the engine consumes the SLO policy
        state = gov.latest_state(tenant_id, c["opportunity_id"])
        c["governed_state"] = state["kind"] if state else "new"
        # Applied-state comes from the OptimizationPolicies source of truth — the same
        # store the app reads at request time and the Power BI report reflects — so the
        # Console and the report can never disagree on whether an optimization is live.
        # `governed_state` above is the human-decision audit (C1/C4), a SEPARATE axis
        # from whether the policy is actually applied. Only config-seam opportunities
        # map to a policy scenario (its `target` is the scenario slug); prompt/code
        # seams have no runtime policy, so their applied-state is "n/a".
        scenario = c["target"] if c.get("seam") == "config" else None
        if scenario:
            applied = optimization_policy.get_active_policy(scenario)
            c["applied_state"] = "active" if applied else (
                (optimization_policy.get_policy(scenario) or {}).get("status", "not_proposed"))
        else:
            c["applied_state"] = "n/a"
        enriched.append(c)
    return enriched, total, slo


# --- read surfaces ----------------------------------------------------------------

@router.get("/{tenant_id}/scorecard")
def scorecard(tenant_id: str, session: Optional[str] = None) -> dict[str, Any]:
    """Agent × dimension health rolled up from node-grain telemetry."""
    nodes = _load_nodes(tenant_id, session)
    cards = build_scorecard(nodes, pricing=_config_pricing())
    return {"tenant_id": tenant_id, "node_count": len(nodes),
            "agents": [c.to_dict() for c in cards]}


@router.get("/{tenant_id}/opportunities")
def opportunities(tenant_id: str) -> dict[str, Any]:
    """Discovered optimization opportunities (SLO-gated, with governance state)."""
    cards, total, slo = _opportunities(tenant_id)
    return {"tenant_id": tenant_id, "total_spend": round(total, 6), "slo": slo,
            "opportunities": cards}


_PROMPT_SUGGESTIONS = {
    "opp-repeated-node": (
        "## Tool-use efficiency (engine-suggested guardrail — review & attest before applying)\n"
        "Do not call the same tool twice in a row within a single turn. If a tool has already "
        "returned a result during this turn, use that result and continue — do not re-invoke the "
        "same tool with identical arguments. Prefer one decisive tool call per step over repeated "
        "back-to-back calls."
    ),
}


def _prompt_suggestion(opportunity_id: str, dimension: str) -> str:
    """A concrete, deterministic prompt edit for a detected pattern. Clearly labeled as a
    suggestion — a human reviews the diff and attests the deploy (never auto-applied)."""
    return _PROMPT_SUGGESTIONS.get(
        opportunity_id,
        ("## Engine-suggested edit (review & attest before applying)\n"
         f"Revise this prompt to address: {dimension} ({opportunity_id})."),
    )


@router.get("/{tenant_id}/opportunity/{opportunity_id}/diff")
def staged_diff(tenant_id: str, opportunity_id: str) -> dict[str, Any]:
    """C2: the reviewable, staged change for one opportunity (never auto-applied for prompt/code)."""
    cards, _total, _slo = _opportunities(tenant_id)
    card = next((c for c in cards if c["opportunity_id"] == opportunity_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"No opportunity '{opportunity_id}'")
    kind, target = card["seam"], card["target"]
    seam = seams.find_seam(kind, target)
    if seam is None:
        raise HTTPException(status_code=404, detail=f"No seam for {kind}:{target}")

    if kind == "code":
        from src.app.engine.codecontext import FileBackedProvider, scaffold_diff
        provider = FileBackedProvider(root=_APP_DIR, allowlist=_CODE_ALLOWLIST)
        ctx = provider.retrieve(
            target,
            hints=["_select_supervisor_model", "get_chat_model_for_turn"],
        )
        diff = scaffold_diff(ctx, f"{card['dimension']} — {opportunity_id}")
        return {"opportunity_id": opportunity_id, "seam": kind, "target": target,
                "apply_mode": seam.apply_mode, "diff": diff, "requires": "human review of staged diff"}

    if kind == "prompt":
        rec = seams.render_recipe(seam.id, {"guidance": f"address {card['dimension']} ({opportunity_id})"})
        before = ""
        try:
            with open(os.path.join(_APP_DIR, "prompts", target), "r", encoding="utf-8") as fh:
                before = fh.read()
        except OSError:
            before = ""
        suggestion = _prompt_suggestion(opportunity_id, card["dimension"])
        after = (before.rstrip() + "\n\n" + suggestion + "\n") if before else suggestion + "\n"
        return {"opportunity_id": opportunity_id, "seam": kind, "target": target,
                "apply_mode": seam.apply_mode, "diff": rec["edit"], "requires": rec["requires"],
                "before": before, "after": after, "suggestion": suggestion}

    # config: render the fail-closed policy document the apply would write
    rec = seams.render_recipe(seam.id, {"enabled": True, "default_deployment": "gpt-5-mini",
                                        "complexity_tiers": {"routine": "gpt-5-mini"}})
    return {"opportunity_id": opportunity_id, "seam": kind, "target": target,
            "apply_mode": seam.apply_mode, "policy_doc": rec.get("policy_doc"),
            "status": rec.get("status")}


@router.get("/{tenant_id}/decisions")
def decisions(tenant_id: str, subject: Optional[str] = None) -> dict[str, Any]:
    """C1/C4: the governance audit trail (optionally for one opportunity)."""
    return {"tenant_id": tenant_id, "decisions": gov.decisions_for(tenant_id, subject)}


# --- governed actions -------------------------------------------------------------

class DecisionBody(BaseModel):
    opportunity_id: str
    action: str                       # approve | reject | attest | confirm-revert
    by: str = "console"
    note: Optional[str] = None


@router.post("/{tenant_id}/decision")
def decide(tenant_id: str, body: DecisionBody) -> dict[str, Any]:
    """C4 approve/reject a card; C1 attest a deploy / confirm a revert. Audited."""
    if body.action not in _DECISION_KINDS:
        raise HTTPException(status_code=400,
                            detail=f"action must be one of {sorted(_DECISION_KINDS)}")
    rec = gov.record_decision(tenant_id, body.action, body.opportunity_id, body.by,
                              {"note": body.note})
    if rec is None:
        raise HTTPException(status_code=503, detail="Governance store unavailable")
    return {"recorded": True, "kind": body.action, "subject": body.opportunity_id,
            "by": body.by, "timeStamp": rec.get("timeStamp")}


class SloBody(BaseModel):
    slo: float = gov.DEFAULT_SLO["slo"]
    min_confidence: float = gov.DEFAULT_SLO["min_confidence"]
    min_effect: float = gov.DEFAULT_SLO["min_effect"]
    by: str = "console"


@router.get("/{tenant_id}/slo")
def get_slo(tenant_id: str) -> dict[str, Any]:
    return gov.get_slo_policy(tenant_id)


@router.post("/{tenant_id}/slo")
def set_slo(tenant_id: str, body: SloBody) -> dict[str, Any]:
    """C3: set the SLO / confidence / min-effect policy the engine consumes."""
    saved = gov.set_slo_policy(tenant_id, body.slo, body.min_confidence, body.min_effect, body.by)
    if saved is None:
        raise HTTPException(status_code=503, detail="Governance store unavailable")
    return saved


class SchemaFieldBody(BaseModel):
    name: str
    type: str = "str"                 # int | float | bool | str
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    enum_ref: Optional[str] = None
    is_map_of_enum: bool = False


class SchemaBody(BaseModel):
    domain: str
    fields: list[SchemaFieldBody]
    value_domains: dict[str, list[Any]] = {}
    sample_params: dict[str, Any] = {}
    by: str = "learner"


@router.get("/{tenant_id}/schema")
def get_schemas(tenant_id: str) -> dict[str, Any]:
    return {"tenant_id": tenant_id, "schemas": gov.declared_schemas(tenant_id)}


@router.post("/{tenant_id}/schema")
def declare_schema(tenant_id: str, body: SchemaBody) -> dict[str, Any]:
    """C5: a learner declares one domain params schema; the engine binds + validates it."""
    try:
        fields = {
            f.name: Field(type=_TYPE_MAP.get(f.type, str), default=f.default, min=f.min,
                          max=f.max, enum_ref=f.enum_ref, is_map_of_enum=f.is_map_of_enum)
            for f in body.fields
        }
        schema = PolicySchema(domain=body.domain, version=1, fields=fields,
                              value_domains={k: set(v) for k, v in body.value_domains.items()})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid schema declaration: {exc}")

    # Bind the learner's sample params through the SDK — proves the engine "behaves".
    bound, status = bind_policy(schema, {"schema_version": 1, "params": body.sample_params}) \
        if body.sample_params else (schema.defaults, "ok (defaults)")
    manifest = discovery_manifest([schema])
    saved = gov.declare_schema(tenant_id, body.domain, manifest, body.by)
    if saved is None:
        raise HTTPException(status_code=503, detail="Governance store unavailable")
    return {"domain": body.domain, "manifest": manifest, "binding_status": status,
            "bound_params": bound, "accepted": status.startswith("ok")}

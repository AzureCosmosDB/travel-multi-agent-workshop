"""
Optimization layer (Module 07 — Analytics & Optimization).

A self-contained, additive "apply-loop" engine for capability-tiered model
selection (SCEN-007). It bolts onto the app you built in Modules 01-06 with a
few small hooks (see Module 07) — it does NOT require changes to the earlier
modules.

The loop it enables:  instrument -> detect -> recommend -> apply -> verify

What ships here (provided):
  - a Cosmos-backed, reversible **policy store** (OptimizationPolicies)
  - a per-deployment **model factory** (get_chat_model)
  - per-turn **tier selection** (select_deployment_for_turn / get_supervisor_for_turn)
  - per-turn **capture** (record_optimization_turn -> OptimizationTurns)
  - **recommendation** cards mined from the captured turns

What YOU implement in Module 07:
  - classify_turn_tier(...)  <-- the one function marked TODO below

Infra note: the OptimizationPolicies and OptimizationTurns containers, and the
gpt-5-nano / gpt-5.1 model deployments, are provisioned by Bicep (`azd up`).
This module assumes they already exist — it never creates them at runtime.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from langchain_openai import AzureChatOpenAI

from src.app.services import azure_cosmos_db as cosmos
from src.app.services.azure_open_ai import (
    model,
    token_provider,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_SELECTION_SCENARIO = "model-selection"
POLICIES_CONTAINER = "OptimizationPolicies"
TURNS_CONTAINER = "OptimizationTurns"

# API version known to support the gpt-5 / o-series reasoning deployments.
_REASONING_API_VERSION = "2025-04-01-preview"

# Estimated USD per 1M tokens (input, output). Single source of truth is
# python/data/model_pricing.json (also written to .env as MODEL_PRICING_JSON by the
# azd post-provision hook, and passed to the reverse-ETL notebook). Resolution order:
#   1. MODEL_PRICING_JSON env var (what .env / azd provides at runtime)
#   2. python/data/model_pricing.json (committed default)
#   3. the built-in dict below (last-resort fallback so the app never breaks)
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.1": {"input": 1.25, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
}


def _normalize_pricing(data: dict[str, Any]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for model_name, v in (data or {}).items():
        if isinstance(v, dict) and "input" in v and "output" in v:
            out[model_name] = {"input": float(v["input"]), "output": float(v["output"])}
        elif isinstance(v, (list, tuple)) and len(v) >= 2:
            out[model_name] = {"input": float(v[0]), "output": float(v[1])}
    return out


def load_pricing() -> dict[str, dict[str, float]]:
    """Model pricing from env (MODEL_PRICING_JSON) → committed file → built-in default."""
    raw = os.getenv("MODEL_PRICING_JSON")
    if raw:
        try:
            parsed = _normalize_pricing(json.loads(raw))
            if parsed:
                return parsed
        except (ValueError, TypeError):
            logger.warning("Invalid MODEL_PRICING_JSON; falling back to the pricing file/default")
    try:
        path = Path(__file__).resolve().parents[3] / "data" / "model_pricing.json"
        if path.exists():
            parsed = _normalize_pricing(json.loads(path.read_text(encoding="utf-8")))
            if parsed:
                return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read model_pricing.json (%s); using built-in default pricing", exc)
    return dict(_DEFAULT_PRICING)


ESTIMATED_PRICING: dict[str, dict[str, float]] = load_pricing()

# The policy the recommendation proposes. `enabled: True` means: once *applied*
# (status active), it routes turns. Until applied it is inert.
PROPOSED_MODEL_SELECTION_PARAMS: dict[str, Any] = {
    "enabled": True,
    "default_deployment": AZURE_OPENAI_DEPLOYMENT,
    "tiers": {
        "trivial": "gpt-5-nano",
        "routine": AZURE_OPENAI_DEPLOYMENT,
        "complex": "gpt-5.1",
    },
    "classifier": {"trivial_max_words": 6},
}

_DEFAULT_TRIVIAL_PATTERNS = [
    r"^(hi|hello|hey|yo|greetings|good (morning|afternoon|evening))\b",
    r"^(thanks|thank you|thx|ty|cheers|much appreciated|appreciate it|appreciated)\b",
    r"^(ok|okay|k|kk|sure|yes|yep|yeah|yup|no|nope|nah|alright|right|fine)\b",
    r"^(great|cool|awesome|perfect|nice|good|wonderful|excellent|fantastic|lovely|brilliant)\b",
    r"^(got it|sounds good|sounds great|looks good|that works|works for me|makes sense|will do|no worries|no problem)\b",
    r"^(bye|goodbye|see you|see ya|later|take care)\b",
]
_DEFAULT_COMPLEX_PATTERNS = [
    r"itinerary",
    r"plan (my|the|a|our) (trip|day|days|vacation|holiday)",
    r"build (me )?(an? )?itinerary",
    r"day[- ]by[- ]day",
    r"full (trip )?plan",
]
_DEFAULT_TRIVIAL_MAX_WORDS = 6


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _database():
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    return cosmos.database


# ---------------------------------------------------------------------------
# Model factory (per-deployment, cached, reasoning-aware)
# ---------------------------------------------------------------------------

_chat_model_cache: dict[str, AzureChatOpenAI] = {}


def _is_reasoning_deployment(deployment_name: str) -> bool:
    name = (deployment_name or "").lower()
    return name.startswith("gpt-5") or name.startswith("o1") or name.startswith("o3") or name.startswith("o4")


def get_chat_model(deployment_name: Optional[str] = None) -> AzureChatOpenAI:
    """Return a cached AzureChatOpenAI bound to a specific Azure deployment.

    Falls back to the app's default shared `model` when no deployment is given
    or it matches the default. Reasoning models (gpt-5*/o-series) omit
    `temperature` and use a newer API version.
    """
    if not deployment_name or deployment_name == AZURE_OPENAI_DEPLOYMENT:
        return model
    cached = _chat_model_cache.get(deployment_name)
    if cached is not None:
        return cached

    kwargs: dict = dict(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=deployment_name,
        azure_ad_token_provider=token_provider,
        streaming=True,
        max_retries=1,
    )
    if _is_reasoning_deployment(deployment_name):
        kwargs["api_version"] = _REASONING_API_VERSION
    else:
        kwargs["api_version"] = AZURE_OPENAI_API_VERSION
        kwargs["temperature"] = 0.7

    tiered = AzureChatOpenAI(**kwargs)
    _chat_model_cache[deployment_name] = tiered
    logger.info(f"✅ Tiered chat model ready: deployment={deployment_name} "
                f"reasoning={_is_reasoning_deployment(deployment_name)}")
    return tiered


# ---------------------------------------------------------------------------
# Policy store (reversible; provisioned by Bicep)
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 15
_policy_cache: dict[str, tuple[float, Optional[dict[str, Any]]]] = {}
_policy_lock = threading.Lock()


def _policies_container():
    db = _database()
    return db.get_container_client(POLICIES_CONTAINER) if db is not None else None


def _invalidate(scenario: str) -> None:
    with _policy_lock:
        _policy_cache.pop(scenario, None)


def get_active_policy(scenario: str) -> Optional[dict[str, Any]]:
    """Return the active policy doc for a scenario, or None. Cached (short TTL)."""
    now = time.monotonic()
    with _policy_lock:
        cached = _policy_cache.get(scenario)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    container = _policies_container()
    policy: Optional[dict[str, Any]] = None
    if container is not None:
        try:
            doc = container.read_item(item=scenario, partition_key=scenario)
            if doc.get("status") == "active":
                policy = doc
        except Exception:  # noqa: BLE001 -- 404 == no policy yet
            policy = None

    with _policy_lock:
        _policy_cache[scenario] = (now, policy)
    return policy


def get_policy(scenario: str) -> Optional[dict[str, Any]]:
    container = _policies_container()
    if container is None:
        return None
    try:
        return container.read_item(item=scenario, partition_key=scenario)
    except Exception:  # noqa: BLE001
        return None


def list_policies() -> list[dict[str, Any]]:
    container = _policies_container()
    if container is None:
        return []
    try:
        return list(container.read_all_items())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error listing optimization policies: {exc}")
        return []


def upsert_policy(doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    container = _policies_container()
    if container is None:
        return None
    scenario = doc["scenario"]
    doc["id"] = scenario
    now = datetime.now(timezone.utc)
    doc.setdefault("created_at", now.isoformat())
    doc["updated_at"] = now.isoformat()
    doc.setdefault("created_epoch", int(now.timestamp()))
    doc["updated_epoch"] = int(now.timestamp())
    saved = container.upsert_item(doc)
    _invalidate(scenario)
    return saved


def propose_policy(doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    doc = dict(doc)
    doc["status"] = "proposed"
    doc.setdefault("version", 1)
    doc["audit"] = list(doc.get("audit", [])) + [
        {"ts": _now_iso(), "action": "proposed", "by": doc.get("proposed_by", "analytics")}
    ]
    return upsert_policy(doc)


def _transition(scenario: str, status: str, by: str) -> Optional[dict[str, Any]]:
    doc = get_policy(scenario)
    if doc is None:
        return None
    doc["status"] = status
    doc["version"] = int(doc.get("version", 1)) + 1
    doc["audit"] = list(doc.get("audit", [])) + [{"ts": _now_iso(), "action": status, "by": by}]
    return upsert_policy(doc)


def apply_policy(scenario: str, by: str = "dashboard") -> Optional[dict[str, Any]]:
    """Activate a scenario's policy (one-click apply). Reversible via revert_policy."""
    return _transition(scenario, "active", by)


def revert_policy(scenario: str, by: str = "dashboard") -> Optional[dict[str, Any]]:
    """Roll a scenario's policy back to inactive (one-click revert)."""
    return _transition(scenario, "reverted", by)


# ---------------------------------------------------------------------------
# The decision layer  (YOUR JOB in Module 07)
# ---------------------------------------------------------------------------

def classify_turn_tier(text: str, classifier: dict[str, Any] | None = None) -> str:
    """Classify a turn as 'trivial', 'complex', or 'routine' from the user text.

    - 'complex'  : explicit planning / itinerary requests -> capable model
    - 'trivial'  : short greetings / acknowledgements       -> cheap model
    - 'routine'  : everything else (incl. place queries)    -> default model

    TODO (Module 07, Activity 5): implement this. Be CONSERVATIVE — only clearly
    trivial greetings become 'trivial', and only explicit planning asks become
    'complex', so a real place query never loses quality on the cheap model.

    Helpers you can use (defined above):
      - classifier.get("trivial_max_words", _DEFAULT_TRIVIAL_MAX_WORDS)
      - classifier.get("trivial_patterns", _DEFAULT_TRIVIAL_PATTERNS)
      - classifier.get("complex_patterns", _DEFAULT_COMPLEX_PATTERNS)
    Suggested order: check complex patterns first, then trivial (short AND
    greeting-like), else 'routine'.
    """
    classifier = classifier or {}
    # TODO: replace this with your implementation.
    return "routine"


def _latest_user_text(messages: Any) -> str:
    """Return the most recent human/user message text from a messages list."""
    for m in reversed(list(messages or [])):
        if isinstance(m, dict):
            role, content = m.get("role"), m.get("content")
        else:
            role, content = getattr(m, "type", None), getattr(m, "content", None)
        if role in ("human", "user") and isinstance(content, str):
            return content
    return ""


def select_deployment_for_turn(messages: Any) -> tuple[str, str]:
    """Return (deployment_name, tier) for this turn from the active policy.

    With no active/enabled policy this returns the default deployment and tier
    'default', so the app behaves exactly as before.
    """
    default = AZURE_OPENAI_DEPLOYMENT
    try:
        policy = get_active_policy(MODEL_SELECTION_SCENARIO)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not read model-selection policy; using default model: {exc}")
        policy = None
    if not policy:
        return default, "default"
    params = policy.get("params", {}) or {}
    if not params.get("enabled", False):
        return default, "default"
    tiers = params.get("tiers", {}) or {}
    tier = classify_turn_tier(_latest_user_text(messages), params.get("classifier"))
    deployment = tiers.get(tier) or params.get("default_deployment") or default
    return deployment, tier


# ---------------------------------------------------------------------------
# Per-tier supervisor selection
# ---------------------------------------------------------------------------
# You register your supervisor builder once at startup (Module 07). It must
# accept a chat model and return a compiled graph, e.g.:
#     optimization.register_supervisor_factory(lambda m: create_supervisor(m))

_supervisor_factory: Optional[Callable[[Any], Any]] = None
_supervisor_by_deployment: dict[str, Any] = {}


def register_supervisor_factory(factory: Callable[[Any], Any]) -> None:
    """Register a `(chat_model) -> compiled_graph` builder for tiered supervisors."""
    global _supervisor_factory
    _supervisor_factory = factory
    _supervisor_by_deployment.clear()


def get_supervisor_for_turn(messages: Any, default_graph: Any = None) -> tuple[Any, str, str]:
    """Return (supervisor_graph, deployment, tier) for this turn.

    If no policy is active (tier 'default') or no factory is registered, returns
    `default_graph` unchanged so behavior is identical to the un-optimized app.
    """
    deployment, tier = select_deployment_for_turn(messages)
    if tier == "default" or _supervisor_factory is None:
        return default_graph, AZURE_OPENAI_DEPLOYMENT, "default"

    graph = _supervisor_by_deployment.get(deployment)
    if graph is None:
        try:
            graph = _supervisor_factory(get_chat_model(deployment))
            _supervisor_by_deployment[deployment] = graph
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to build supervisor for '{deployment}'; using default: {exc}")
            return default_graph, AZURE_OPENAI_DEPLOYMENT, "default"
    return graph, deployment, tier


# ---------------------------------------------------------------------------
# Per-turn capture (the "instrument" step) -> OptimizationTurns
# ---------------------------------------------------------------------------

def _turns_container():
    db = _database()
    return db.get_container_client(TURNS_CONTAINER) if db is not None else None


def record_optimization_turn(
    tenant_id: str,
    user_id: str,
    session_id: str,
    tier: str,
    deployment: str,
    usage: Optional[dict[str, Any]] = None,
    model_name: str = "Unknown",
    handoff_count: int = 0,
) -> None:
    """Record one turn's tier + token usage for the detect/verify steps.

    `usage` is the per-turn token dict your completion handler already builds,
    e.g. {"input_tokens", "output_tokens", "total_tokens", "cached_tokens"}.
    `handoff_count` is how many specialist handoffs the turn took (0 == the
    orchestrator answered directly) — with output_tokens it defines a *trivial*
    turn (handoff_count == 0 AND output_tokens < 60), the model-selection signal.
    `turn_epoch` (epoch seconds of the turn) is recorded so time-series analytics
    key off the real turn time, not Cosmos `_ts`.
    """
    container = _turns_container()
    if container is None:
        return
    usage = usage or {}
    now = datetime.now(timezone.utc)
    doc = {
        "id": str(uuid.uuid4()),
        "type": "optimization_turn",
        "tenantId": tenant_id,
        "userId": user_id,
        "sessionId": session_id,
        "model_tier": tier,
        "model_deployment": deployment,
        "model_name": model_name,
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "cached_tokens": int(usage.get("cached_tokens") or 0),
        "handoff_count": int(handoff_count or 0),
        "timeStamp": now.isoformat(),
        "turn_epoch": int(now.timestamp()),
    }
    try:
        container.upsert_item(doc)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Failed to record optimization turn: {exc}")


# ---------------------------------------------------------------------------
# Recommendations (the "recommend" step)
# ---------------------------------------------------------------------------

def _query_turns(tenant_id: str) -> list[dict]:
    container = _turns_container()
    if container is None:
        return []
    try:
        return list(container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error querying optimization turns: {exc}")
        return []


def build_model_selection_recommendation(tenant_id: str) -> dict[str, Any]:
    """Build the SCEN-007 candidate card from captured OptimizationTurns."""
    turns = _query_turns(tenant_id)
    total = len(turns)
    trivial = trivial_in = trivial_out = 0
    models: dict[str, int] = {}
    for d in turns:
        models[d.get("model_name", "Unknown")] = models.get(d.get("model_name", "Unknown"), 0) + 1
        out = int(d.get("output_tokens") or 0)
        if out < 60:  # short answer ~ trivial turn
            trivial += 1
            trivial_in += int(d.get("input_tokens") or 0)
            trivial_out += out

    mini = ESTIMATED_PRICING["gpt-4.1-mini"]
    nano = ESTIMATED_PRICING["gpt-5-nano"]
    cost_now = (trivial_in * mini["input"] + trivial_out * mini["output"]) / 1_000_000
    cost_proposed = (trivial_in * nano["input"] + trivial_out * nano["output"]) / 1_000_000

    active = get_active_policy(MODEL_SELECTION_SCENARIO)
    status = "active" if active else (get_policy(MODEL_SELECTION_SCENARIO) or {}).get("status", "not_proposed")

    return {
        "scenario": MODEL_SELECTION_SCENARIO,
        "scenario_id": "SCEN-007",
        "title": "Capability-tiered model selection",
        "status": status,
        "evidence": {
            "total_turns": total,
            "trivial_turns": trivial,
            "trivial_pct": round(100 * trivial / max(total, 1), 1),
            "model_distribution": models,
        },
        "estimated_saving_usd": round(cost_now - cost_proposed, 4),
        "estimate_caveat": (
            "ESTIMATE only. gpt-5-nano is a reasoning model that emits billed "
            "reasoning tokens, so trivial turns may not actually be cheaper. The "
            "measured before/after (verify) is authoritative."
        ),
        "proposed_params": PROPOSED_MODEL_SELECTION_PARAMS,
    }


def build_recommendations(tenant_id: str) -> list[dict[str, Any]]:
    return [
        build_model_selection_recommendation(tenant_id),
        build_city_context_recommendation(tenant_id),
    ]


# ---------------------------------------------------------------------------
# Scenario B (SCEN-001) — active-trip city context: a HUMAN-GOVERNED (L3) prompt
# optimization. Unlike model selection, its "apply" does NOT toggle runtime — it
# STAGES a proposed prompt change for human review (a prompt/code change is
# higher-risk, so it caps at maturity L3 and goes through a PR).
# ---------------------------------------------------------------------------

CITY_CONTEXT_SCENARIO = "active-trip-city-context"

_CITY_ASK_RE = re.compile(
    r"which city|what city|city (is|are) (it|this|that|you|the hotel)"
    r"|in which city|which city .* located|what city .* in",
    re.I,
)

# The prompt change this scenario recommends (added to supervisor.prompty).
PROPOSED_CITY_CONTEXT_CHANGE = (
    "When the user refers to a hotel/place by name and an active trip exists, use the "
    "active trip's destination city as the search city instead of asking the user which "
    "city it is in. Only ask for a city when no active trip or destination is known."
)


def _query_assistant_texts(tenant_id: str) -> list[str]:
    db = _database()
    if db is None:
        return []
    try:
        rows = db.get_container_client("Messages").query_items(
            query="SELECT d.role, d.content FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        )
        return [r.get("content", "") for r in rows
                if str(r.get("role", "")).lower() == "assistant" and isinstance(r.get("content"), str)]
    except Exception:  # noqa: BLE001
        return []


def _trip_count(tenant_id: str) -> int:
    db = _database()
    if db is None:
        return 0
    try:
        rows = list(db.get_container_client("Trips").query_items(
            query="SELECT VALUE COUNT(1) FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
        return int(rows[0]) if rows else 0
    except Exception:  # noqa: BLE001
        return 0


def build_city_context_recommendation(tenant_id: str) -> dict[str, Any]:
    """Detect the 'agent re-asks for a city it already knows' pattern (SCEN-001)."""
    reasks = sum(1 for t in _query_assistant_texts(tenant_id) if _CITY_ASK_RE.search(t))
    trips = _trip_count(tenant_id)

    doc = get_policy(CITY_CONTEXT_SCENARIO) or {}
    status = doc.get("status", "not_proposed")

    return {
        "scenario": CITY_CONTEXT_SCENARIO,
        "scenario_id": "SCEN-001",
        "title": "Active-trip city context",
        "dimension": "agent quality · prompt",
        "maturity": "L3 (human-governed)",
        "apply_mode": "staged_change",  # NOT a runtime toggle
        "risk": "higher-risk (prompt change → human review / PR)",
        "status": status,
        "evidence": {
            "city_reasks": reasks,
            "trips": trips,
        },
        "rationale": (
            "The supervisor re-asks which city a hotel is in even when an active trip already "
            "fixes the destination — a prompt gap, not a policy knob."
        ),
        "proposed_change": {
            "file": "python/src/app/prompts/supervisor.prompty",
            "add": PROPOSED_CITY_CONTEXT_CHANGE,
        },
        "note": (
            "Because this is a prompt change (higher-risk), it cannot be applied at runtime. "
            "Staging it produces a reviewable proposal for a human to merge via PR (maturity L3)."
        ),
    }


def stage_prompt_change(scenario: str, by: str = "dashboard") -> Optional[dict[str, Any]]:
    """'Apply' for a human-governed change: record it as STAGED (never active).

    Returns the staged proposal (the diff/text) for a human to review and merge.
    This deliberately does NOT change runtime behavior.
    """
    if scenario != CITY_CONTEXT_SCENARIO:
        return None
    doc = {
        "scenario": scenario,
        "scenario_id": "SCEN-001",
        "title": "Active-trip city context",
        "status": "staged",              # never 'active' -> no runtime effect
        "apply_mode": "staged_change",
        "proposed_change": {
            "file": "python/src/app/prompts/supervisor.prompty",
            "add": PROPOSED_CITY_CONTEXT_CHANGE,
        },
        "audit": list((get_policy(scenario) or {}).get("audit", [])) + [
            {"ts": _now_iso(), "action": "staged", "by": by}
        ],
    }
    saved = upsert_policy(doc)
    return saved


# ---------------------------------------------------------------------------
# Aggregate metrics (for the Optimization Console)
# ---------------------------------------------------------------------------

def _price_for(deployment: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for a deployment/model name. ESTIMATE."""
    name = (deployment or "").lower()
    for key, p in ESTIMATED_PRICING.items():
        if name.startswith(key):
            return p["input"], p["output"]
    return ESTIMATED_PRICING["gpt-4.1-mini"]["input"], ESTIMATED_PRICING["gpt-4.1-mini"]["output"]


def _confirmed_outcomes(tenant_id: str) -> int:
    """Count confirmed/completed trips for the tenant (the 'outcome' denominator)."""
    db = _database()
    if db is None:
        return 0
    try:
        rows = list(db.get_container_client("Trips").query_items(
            query="SELECT VALUE COUNT(1) FROM d WHERE d.tenantId=@t AND (d.status='confirmed' OR d.status='completed')",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
        return int(rows[0]) if rows else 0
    except Exception:  # noqa: BLE001 -- Trips may be absent/empty
        return 0


def build_turn_metrics(tenant_id: str) -> dict[str, Any]:
    """Aggregate the captured turns into the KPIs the Console displays."""
    turns = _query_turns(tenant_id)
    total = len(turns)
    total_in = total_out = total_tokens = trivial = 0
    est_cost = 0.0
    models: dict[str, int] = {}
    by_tier: dict[str, dict[str, Any]] = {}

    for d in turns:
        i = int(d.get("input_tokens") or 0)
        o = int(d.get("output_tokens") or 0)
        total_in += i
        total_out += o
        total_tokens += int(d.get("total_tokens") or 0)
        if o < 60:
            trivial += 1
        mname = d.get("model_name", "Unknown")
        models[mname] = models.get(mname, 0) + 1
        dep = d.get("model_deployment") or mname
        pin, pout = _price_for(dep)
        cost = (i * pin + o * pout) / 1_000_000
        est_cost += cost
        key = f"{d.get('model_tier', 'default')} ({dep})"
        row = by_tier.setdefault(key, {"tier": d.get("model_tier", "default"), "deployment": dep,
                                       "turns": 0, "tokens": 0, "cost": 0.0})
        row["turns"] += 1
        row["tokens"] += int(d.get("total_tokens") or 0)
        row["cost"] += cost

    confirmed = _confirmed_outcomes(tenant_id)
    return {
        "tenant_id": tenant_id,
        "total_turns": total,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(est_cost, 4),
        "trivial_turns": trivial,
        "trivial_pct": round(100 * trivial / max(total, 1), 1),
        "distinct_models": len(models),
        "model_distribution": models,
        "confirmed_outcomes": confirmed,
        "cost_per_outcome_usd": round(est_cost / confirmed, 4) if confirmed else None,
        "by_tier": sorted(by_tier.values(), key=lambda r: -r["cost"]),
    }

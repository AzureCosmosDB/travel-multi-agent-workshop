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

import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
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

# Estimated USD per 1M tokens (input, output). The runtime single source of truth
# is the Cosmos **Configuration** container (type="model_pricing"), populated at
# deploy time by python/data/seed_configuration.py from the models azd actually
# deployed (see analytics/docs/model-pricing.md). Resolution order:
#   1. the Configuration container (what the app, notebook, and report all share)
#   2. the built-in dict below (last-resort fallback so the app never breaks)
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.1": {"input": 1.25, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
}


def load_pricing() -> dict[str, dict[str, float]]:
    """Model pricing from the Configuration container → built-in default."""
    try:
        from src.app.services import configuration_store

        priced = configuration_store.get_model_pricing()
        if priced:
            return priced
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read pricing from Configuration (%s); using default pricing", exc)
    return dict(_DEFAULT_PRICING)


# The policy the recommendation proposes. `enabled: True` means: once *applied*
# (status active), it routes turns. Until applied it is inert. The authoritative
# copy is the Configuration container (type="model_selection_defaults", seeded from
# azd); this code dict is the last-resort fallback.
_CODE_MODEL_SELECTION_PARAMS: dict[str, Any] = {
    "enabled": True,
    "default_deployment": AZURE_OPENAI_DEPLOYMENT,
    "tiers": {
        "trivial": "gpt-5-nano",
        "routine": AZURE_OPENAI_DEPLOYMENT,
        "complex": "gpt-5.1",
    },
    "classifier": {"trivial_max_words": 6},
}

# Backwards-compatible module constant (code default). Prefer
# get_proposed_model_selection_params() to pick up the config-driven values.
PROPOSED_MODEL_SELECTION_PARAMS: dict[str, Any] = dict(_CODE_MODEL_SELECTION_PARAMS)


def get_proposed_model_selection_params() -> dict[str, Any]:
    """Proposed tier/classifier policy from the Configuration container → code default."""
    try:
        from src.app.services import configuration_store

        doc = configuration_store.get_model_selection_defaults()
        if doc and isinstance(doc.get("tiers"), dict):
            return {
                "enabled": bool(doc.get("enabled", True)),
                "default_deployment": doc.get(
                    "default_deployment", _CODE_MODEL_SELECTION_PARAMS["default_deployment"]
                ),
                "tiers": doc["tiers"],
                "classifier": doc.get("classifier", _CODE_MODEL_SELECTION_PARAMS["classifier"]),
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read model_selection_defaults from Configuration (%s)", exc)
    return dict(_CODE_MODEL_SELECTION_PARAMS)

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

    pricing = load_pricing()
    mini = pricing.get(AZURE_OPENAI_DEPLOYMENT, pricing.get("gpt-5.1", _DEFAULT_PRICING["gpt-5.1"]))
    nano = pricing.get("gpt-5-nano", _DEFAULT_PRICING["gpt-5-nano"])
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
        "proposed_params": get_proposed_model_selection_params(),
    }


def build_recommendations(tenant_id: str) -> list[dict[str, Any]]:
    return [
        build_model_selection_recommendation(tenant_id),
        build_memory_retention_recommendation(tenant_id),
        build_city_context_recommendation(tenant_id),
        build_redundant_tool_recommendation(tenant_id),
        build_cost_per_outcome_diagnostic(tenant_id),
        build_agent_path_diagnostic(tenant_id),
    ]


# ---------------------------------------------------------------------------
# Read the Fabric-computed (reverse-ETL'd) cards/metrics from OptimizationInsights.
# CLOSES the analytics loop: the Console reads pre-computed results instead of
# recomputing aggregations from Cosmos per request. The in-app build_* functions
# above remain the "peek" (Module 07) / offline fallback, used automatically
# whenever the loop hasn't populated OptimizationInsights yet.
# ---------------------------------------------------------------------------

INSIGHTS_CONTAINER = "OptimizationInsights"


def _insights_container():
    db = _database()
    return db.get_container_client(INSIGHTS_CONTAINER) if db is not None else None


def read_recommendations_from_insights(tenant_id: str) -> list[dict[str, Any]] | None:
    """Fabric-computed recommendation cards, or None if the loop hasn't populated them.

    Re-stamps the volatile policy ``status`` from the live policy store so the
    Console's apply/revert state stays current (analysis analytical, act operational).
    """
    container = _insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t AND d.type='recommendation_card'",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"reverse-ETL recommendations read failed: {exc}")
        return None
    if not rows:
        return None
    cards: list[dict[str, Any]] = []
    for r in sorted(rows, key=lambda x: x.get("order", 99)):
        card = dict(r.get("card") or {})
        if not card:
            continue
        scenario = card.get("scenario")
        active = get_active_policy(scenario)
        card["status"] = "active" if active else (
            (get_policy(scenario) or {}).get("status", card.get("status", "not_proposed"))
        )
        card["source"] = "fabric"
        card["computed_at"] = r.get("computed_at")
        cards.append(card)
    return cards or None


def read_metrics_from_insights(tenant_id: str) -> dict[str, Any] | None:
    """Fabric-computed Console KPIs, or None if the loop hasn't populated them."""
    container = _insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t AND d.type='turn_metrics'",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"reverse-ETL metrics read failed: {exc}")
        return None
    if not rows:
        return None
    metrics = dict(rows[0].get("metrics") or {})
    if not metrics:
        return None
    metrics["source"] = "fabric"
    metrics["computed_at"] = rows[0].get("computed_at")
    return metrics


def read_optimization_result_from_insights(tenant_id: str) -> dict[str, Any] | None:
    """Measured before/after results (counterfactual saving etc.) for a tenant, or None."""
    container = _insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t AND d.type='optimization_result'",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"reverse-ETL result read failed: {exc}")
        return None
    if not rows:
        return None
    results = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    return {"tenant_id": tenant_id, "source": "fabric", "results": results}


# ---------------------------------------------------------------------------
# SCEN-004 — memory retention: a lower-risk AUTONOMOUS (L4/L5) policy. Memory
# accumulates superseded ("stale") entries as preferences change; applying the
# policy soft-prunes them (a reversible mark), so recall stays cheaper/cleaner.
# "Superseded" = a memory whose id appears in another memory's supersedes_ids.
# ---------------------------------------------------------------------------

MEMORY_RETENTION_SCENARIO = "memory-retention"
_MEMORIES_CONTAINER = os.getenv("COSMOS_MEMORIES_CONTAINER", "memories")

PROPOSED_MEMORY_RETENTION_PARAMS: dict[str, Any] = {
    "enabled": True,
    "prune": "superseded",
}


def _memories_container():
    db = _database()
    if db is None:
        return None
    try:
        return db.get_container_client(_MEMORIES_CONTAINER)
    except Exception:  # noqa: BLE001
        return None


def _superseded_memory_rows() -> list[dict]:
    container = _memories_container()
    if container is None:
        return []
    try:
        rows = list(container.query_items(
            query="SELECT c.id, c.user_id, c.thread_id, c.supersedes_ids, c.retention_status FROM c",
            enable_cross_partition_query=True,
        ))
    except Exception:  # noqa: BLE001
        return []
    superseded_ids: set = set()
    for r in rows:
        for sid in (r.get("supersedes_ids") or []):
            superseded_ids.add(sid)
    return [r for r in rows if r.get("id") in superseded_ids]


def build_memory_retention_recommendation(tenant_id: str) -> dict[str, Any]:
    """Detect stale (superseded) memory accumulation (SCEN-004). Memory is keyed by
    (user_id, thread_id), not tenant — a global memory-hygiene signal."""
    container = _memories_container()
    total = 0
    if container is not None:
        try:
            total = list(container.query_items(
                query="SELECT VALUE COUNT(1) FROM c", enable_cross_partition_query=True))[0]
        except Exception:  # noqa: BLE001
            total = 0
    superseded = _superseded_memory_rows()
    n_sup = len(superseded)
    n_pruned = sum(1 for r in superseded if r.get("retention_status") == "pruned")
    status = (get_policy(MEMORY_RETENTION_SCENARIO) or {}).get("status", "not_proposed")
    if get_active_policy(MEMORY_RETENTION_SCENARIO):
        status = "active"
    return {
        "scenario": MEMORY_RETENTION_SCENARIO,
        "scenario_id": "SCEN-004",
        "title": "Memory retention (prune stale memories)",
        "dimension": "memory · cost + quality",
        "maturity": "L4/L5 (lower-risk autonomous policy)",
        "apply_mode": "policy",
        "status": status,
        "evidence": {
            "total_memories": total,
            "superseded_memories": n_sup,
            "superseded_pct": round(100 * n_sup / max(total, 1), 1),
            "pruned_memories": n_pruned,
        },
        "rationale": (
            "Preferences change, so memory accumulates superseded entries. A large stale share "
            "means recall wades through (and pays for) memories that no longer apply."
        ),
        "estimate_caveat": (
            "Applying soft-prunes superseded memories (a reversible mark). Recall excludes pruned "
            "memories where the memory client surfaces the flag; the mark is always reversible."
        ),
        "proposed_params": PROPOSED_MEMORY_RETENTION_PARAMS,
        "actions": {
            "apply": f"POST /optimizations/{MEMORY_RETENTION_SCENARIO}/apply",
            "revert": f"POST /optimizations/{MEMORY_RETENTION_SCENARIO}/revert",
        },
    }


def apply_memory_retention() -> int:
    """Soft-prune superseded memories (patch retention_status='pruned'). Reversible.
    Uses a partial PATCH so the embedding vector is not rewritten."""
    container = _memories_container()
    if container is None:
        return 0
    pruned = 0
    for r in _superseded_memory_rows():
        if r.get("retention_status") == "pruned":
            continue
        try:
            container.patch_item(
                item=r["id"],
                partition_key=[r.get("user_id"), r.get("thread_id")],
                patch_operations=[{"op": "add", "path": "/retention_status", "value": "pruned"}],
            )
            pruned += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not prune memory {r.get('id')}: {exc}")
    logger.info(f"Memory retention applied: pruned {pruned} superseded memories")
    return pruned


def revert_memory_retention() -> int:
    """Un-prune previously pruned memories. Returns count restored."""
    container = _memories_container()
    if container is None:
        return 0
    try:
        rows = list(container.query_items(
            query="SELECT c.id, c.user_id, c.thread_id FROM c WHERE c.retention_status = 'pruned'",
            enable_cross_partition_query=True,
        ))
    except Exception:  # noqa: BLE001
        return 0
    restored = 0
    for r in rows:
        try:
            container.patch_item(
                item=r["id"],
                partition_key=[r.get("user_id"), r.get("thread_id")],
                patch_operations=[{"op": "remove", "path": "/retention_status"}],
            )
            restored += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not un-prune memory {r.get('id')}: {exc}")
    logger.info(f"Memory retention reverted: restored {restored} memories")
    return restored


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
    if scenario == CITY_CONTEXT_SCENARIO:
        scenario_id, title, change = "SCEN-001", "Active-trip city context", {
            "file": "python/src/app/prompts/supervisor.prompty",
            "add": PROPOSED_CITY_CONTEXT_CHANGE,
        }
    elif scenario == TOOL_DEDUP_SCENARIO:
        scenario_id, title, change = "SCEN-008", "Redundant tool calls", {
            "file": "python/src/app/prompts/supervisor.prompty",
            "add": PROPOSED_TOOL_DEDUP_CHANGE,
        }
    else:
        return None
    doc = {
        "scenario": scenario,
        "scenario_id": scenario_id,
        "title": title,
        "status": "staged",              # never 'active' -> no runtime effect
        "apply_mode": "staged_change",
        "proposed_change": change,
        "audit": list((get_policy(scenario) or {}).get("audit", [])) + [
            {"ts": _now_iso(), "action": "staged", "by": by}
        ],
    }
    saved = upsert_policy(doc)
    return saved


# ---------------------------------------------------------------------------
# SCEN-008 (staged) + SCEN-003 / SCEN-005 (diagnostic) — mined from Debug
# telemetry, which now carries agent_path / handoff_count (see
# store_debug_log_from_response).
# ---------------------------------------------------------------------------

TOOL_DEDUP_SCENARIO = "tool-call-dedup"

PROPOSED_TOOL_DEDUP_CHANGE = (
    "When a place/tool lookup for a query already returned results this turn, reuse them "
    "instead of calling the same tool again. Only re-query on a materially different search."
)


def _bag(doc: dict) -> dict:
    p = doc.get("propertyBag")
    return {i["key"]: i["value"] for i in p} if isinstance(p, list) else (p or {})


def _query_debug(tenant_id: str) -> list[dict]:
    db = _database()
    if db is None:
        return []
    try:
        return list(db.get_container_client("Debug").query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception:  # noqa: BLE001
        return []


def _redundant_tool_turns(debug: list[dict]) -> int:
    n = 0
    for d in debug:
        parts = [p.strip() for p in str(_bag(d).get("agent_path") or "").split(",") if p.strip()]
        if any(parts[i] == parts[i + 1] and parts[i] != "supervisor" for i in range(len(parts) - 1)):
            n += 1
    return n


def build_redundant_tool_recommendation(tenant_id: str) -> dict[str, Any]:
    """Detect redundant back-to-back tool/agent calls (SCEN-008) — a staged prompt fix."""
    debug = _query_debug(tenant_id)
    redundant = _redundant_tool_turns(debug)
    status = (get_policy(TOOL_DEDUP_SCENARIO) or {}).get("status", "not_proposed")
    return {
        "scenario": TOOL_DEDUP_SCENARIO,
        "scenario_id": "SCEN-008",
        "title": "Redundant tool calls",
        "dimension": "agent quality · tool use",
        "maturity": "L3 (human-governed)",
        "apply_mode": "staged_change",
        "risk": "higher-risk (prompt/code change → human review / PR)",
        "status": status,
        "evidence": {"redundant_tool_turns": redundant, "total_turns": len(debug)},
        "rationale": (
            "Some turns invoke the same place-search tool/agent twice in a row — redundant "
            "token spend with no added grounding."
        ),
        "proposed_change": {
            "file": "python/src/app/prompts/supervisor.prompty",
            "add": PROPOSED_TOOL_DEDUP_CHANGE,
        },
        "note": (
            "Prompt/code change (higher-risk) — stage for human review (maturity L3), "
            "not applied at runtime."
        ),
    }


def _converting_users(tenant_id: str) -> set:
    db = _database()
    if db is None:
        return set()
    try:
        rows = db.get_container_client("Trips").query_items(
            query="SELECT d.userId, d.status FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        )
        return {r.get("userId") for r in rows
                if str(r.get("status", "")).lower() in ("confirmed", "completed")}
    except Exception:  # noqa: BLE001
        return set()


_NO_RESULTS_RE = re.compile(
    r"couldn'?t find|could not find|no (matching )?(results|places|hotels|options)|nothing (found|matched)",
    re.I,
)

_ABANDON_FIX = {
    "city_friction": "the active-trip city-context prompt fix (SCEN-001) — it lifts conversion, not just cost",
    "cart_abandon": "a proactive 'shall I book it?' confirmation at the itinerary step",
    "no_results": "better place-search grounding (broaden/relax the query before giving up)",
    "search_stall": "clearer next-step prompting after a search returns",
    "no_engagement": "earlier intent clarification so vague sessions reach a search",
}


def _converted_sessions(tenant_id: str) -> set:
    db = _database()
    if db is None:
        return set()
    try:
        rows = db.get_container_client("Trips").query_items(
            query="SELECT d.sessionId, d.status FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        )
        return {r.get("sessionId") for r in rows
                if r.get("sessionId") and str(r.get("status", "")).lower() in ("confirmed", "completed")}
    except Exception:  # noqa: BLE001
        return set()


def _session_friction(tenant_id: str) -> dict[str, dict]:
    db = _database()
    if db is None:
        return {}
    out: dict[str, dict] = {}
    try:
        rows = db.get_container_client("Messages").query_items(
            query="SELECT d.sessionId, d.role, d.content FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        )
    except Exception:  # noqa: BLE001
        return {}
    for r in rows:
        if str(r.get("role", "")).lower() != "assistant" or not isinstance(r.get("content"), str):
            continue
        f = out.setdefault(r.get("sessionId"), {"city_reask": False, "no_results": False})
        if _CITY_ASK_RE.search(r["content"]):
            f["city_reask"] = True
        if _NO_RESULTS_RE.search(r["content"]):
            f["no_results"] = True
    return out


def _conversion_funnel(tenant_id: str) -> dict[str, Any]:
    debug = _query_debug(tenant_id)
    sessions: dict[str, dict] = {}
    for d in debug:
        sid = d.get("sessionId")
        if not sid:
            continue
        b = _bag(d)
        s = sessions.setdefault(sid, {"searched": False, "planned": False, "tokens": 0, "user": d.get("userId")})
        path = str(b.get("agent_path") or "")
        if int(b.get("handoff_count") or 0) > 0 or "find_places" in path:
            s["searched"] = True
        if "itinerary" in path:
            s["planned"] = True
        s["tokens"] += int(b.get("total_tokens") or 0)

    # Conversion is session-level when trips carry a sessionId (e.g. funnel_demo),
    # else falls back to user-level (real trips have no sessionId).
    converted_sessions = _converted_sessions(tenant_id)
    converting_users = _converting_users(tenant_id)
    friction = _session_friction(tenant_id)
    funnel = {"engaged": 0, "searched": 0, "planned": 0, "confirmed": 0}
    abandon = {"cart_abandon": 0, "city_friction": 0, "no_results": 0, "search_stall": 0, "no_engagement": 0}
    wasted = total = 0
    for sid, s in sessions.items():
        total += s["tokens"]
        funnel["engaged"] += 1
        if s["searched"]:
            funnel["searched"] += 1
        if s["planned"]:
            funnel["planned"] += 1
        if s.get("planned") and (sid in converted_sessions or s.get("user") in converting_users):
            funnel["confirmed"] += 1
            continue
        wasted += s["tokens"]
        fr = friction.get(sid, {})
        if s["planned"]:
            abandon["cart_abandon"] += 1
        elif s["searched"]:
            if fr.get("city_reask"):
                abandon["city_friction"] += 1
            elif fr.get("no_results"):
                abandon["no_results"] += 1
            else:
                abandon["search_stall"] += 1
        else:
            abandon["no_engagement"] += 1
    return {
        "sessions": len(sessions), "funnel": funnel, "abandonment": abandon,
        "wasted_tokens": wasted, "total_tokens": total, "confirmed_sessions": funnel["confirmed"],
    }


def build_cost_per_outcome_diagnostic(tenant_id: str) -> dict[str, Any]:
    """Cost per outcome upleveled to a conversion funnel (SCEN-003): not just *how
    much* is wasted, but *where* sessions leak and *why* — pointing at the fix."""
    f = _conversion_funnel(tenant_id)
    total_tokens = f["total_tokens"]
    wasted = f["wasted_tokens"]
    confirmed = f["confirmed_sessions"]
    abandon = f["abandonment"]
    addressable = {k: v for k, v in abandon.items() if k != "no_engagement"}
    biggest = max(addressable, key=addressable.get) if any(addressable.values()) else None
    if biggest and abandon[biggest] > 0:
        note = (f"Biggest addressable leak: {biggest.replace('_', ' ')} "
                f"({abandon[biggest]} sessions). Fix: {_ABANDON_FIX[biggest]}.")
    else:
        note = ("A lens, not a toggle. Once sessions carry a clear abandonment cause, this names "
                "the leak and the lever; otherwise the levers are spend control and richer instrumentation.")
    return {
        "scenario": "cost-per-outcome",
        "scenario_id": "SCEN-003",
        "title": "Cost per outcome & conversion funnel",
        "dimension": "business impact · conversion",
        "maturity": "diagnostic (points at the conversion fix)",
        "apply_mode": "diagnostic",
        "status": "insight",
        "evidence": {
            "total_tokens": total_tokens,
            "wasted_tokens": wasted,
            "wasted_pct": round(100 * wasted / max(total_tokens, 1), 1),
            "confirmed_sessions": confirmed,
            "tokens_per_outcome": round(total_tokens / max(confirmed, 1)),
            "funnel": f["funnel"],
            "abandonment": abandon,
        },
        "rationale": (
            "'Cheaper per turn' is not the goal; 'cheaper per confirmed outcome' is. The funnel "
            "shows where sessions drop and why — turning a cost signal into a conversion lever."
        ),
        "note": note,
    }


def build_agent_path_diagnostic(tenant_id: str) -> dict[str, Any]:
    """Where the tokens go: cost concentrated in a few agent_paths (SCEN-005)."""
    debug = _query_debug(tenant_id)
    agg: dict[str, list[int]] = {}
    for d in debug:
        path = str(_bag(d).get("agent_path") or "unknown")
        tok = int(_bag(d).get("total_tokens") or 0)
        a = agg.setdefault(path, [0, 0])
        a[0] += 1
        a[1] += tok
    rows = sorted(
        ({"agent_path": p, "turns": c, "total_tokens": t, "avg_tokens": round(t / max(c, 1))}
         for p, (c, t) in agg.items()),
        key=lambda r: -r["avg_tokens"],
    )
    return {
        "scenario": "agent-path-cost",
        "scenario_id": "SCEN-005",
        "title": "Agent-path cost concentration",
        "dimension": "cost efficiency · routing",
        "maturity": "diagnostic (informs tiering + tool fixes)",
        "apply_mode": "diagnostic",
        "status": "insight",
        "evidence": {"paths": rows[:6]},
        "rationale": (
            "A few agent paths (typically the itinerary path) dominate token cost — often "
            "many times a plain supervisor turn. That's where tiering and tool fixes pay off."
        ),
        "note": (
            "A lens: act via model tiering (SCEN-007) on the expensive paths and by removing "
            "redundant tool calls (SCEN-008)."
        ),
    }


# ---------------------------------------------------------------------------
# Aggregate metrics (for the Optimization Console)
# ---------------------------------------------------------------------------

def _price_for(deployment: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for a deployment/model name. ESTIMATE."""
    name = (deployment or "").lower()
    pricing = load_pricing()
    for key, p in pricing.items():
        if name.startswith(key):
            return p["input"], p["output"]
    default = pricing.get("gpt-5.1", _DEFAULT_PRICING["gpt-5.1"])
    return default["input"], default["output"]


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

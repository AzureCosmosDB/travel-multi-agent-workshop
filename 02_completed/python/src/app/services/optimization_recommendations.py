"""
Optimization recommendations (the *recommend* stage of the analytics loop).

Turns signal the app already captures (Debug turn logs) into candidate
"optimization cards" a dashboard can show and a user can apply with one click.
Today this produces the SCEN-007 (capability-tiered model selection) card.

IMPORTANT — pricing is ESTIMATED. The per-token prices below are public
list-price estimates (verify on the Azure pricing calculator before quoting).
They are used only for a rough *projected* saving; the authoritative number is
the measured before/after in the verify step (optimization_mining.py), because
reasoning models (gpt-5-nano / gpt-5.1) emit billed reasoning tokens that a
naive projection cannot know in advance.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from src.app.services import azure_cosmos_db as cosmos
from src.app.services import optimization_policy

logger = logging.getLogger(__name__)

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


MODEL_SELECTION_SCENARIO = "model-selection"

# The policy this card proposes (safe default: disabled until applied). The
# authoritative copy is the Configuration container (type="model_selection_defaults",
# seeded from azd); this code dict is the last-resort fallback.
_CODE_MODEL_SELECTION_PARAMS: dict[str, Any] = {
    "enabled": True,
    "default_deployment": "gpt-5.1",
    "tiers": {
        "trivial": "gpt-5-nano",
        "routine": "gpt-5-mini",
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


def _bag(doc: dict) -> dict:
    p = doc.get("propertyBag")
    return {i["key"]: i["value"] for i in p} if isinstance(p, list) else (p or {})


def _query_debug(tenant_id: str) -> list[dict]:
    if cosmos.debug_logs_container is None:
        cosmos.initialize_cosmos_client()
    if cosmos.debug_logs_container is None:
        return []
    return list(
        cosmos.debug_logs_container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        )
    )


def build_model_selection_recommendation(tenant_id: str) -> dict[str, Any]:
    """Build the SCEN-007 candidate card from Debug turn logs for a tenant."""
    dbg = _query_debug(tenant_id)
    total = len(dbg)

    trivial = 0
    trivial_in = trivial_out = 0
    models: dict[str, int] = {}
    for d in dbg:
        b = _bag(d)
        models[b.get("model_name", "Unknown")] = models.get(b.get("model_name", "Unknown"), 0) + 1
        out = int(b.get("output_tokens") or 0)
        if str(b.get("handoff_count")) == "0" and out < 60:
            trivial += 1
            trivial_in += int(b.get("input_tokens") or 0)
            trivial_out += out

    # Estimated saving IF trivial turns moved from the default (gpt-5.1) -> nano,
    # using the tokens actually observed on those turns. Optimistic: ignores nano
    # reasoning tokens, which is why the verify step (measured before/after) is
    # the real proof.
    pricing = load_pricing()
    baseline = pricing.get("gpt-5.1", _DEFAULT_PRICING["gpt-5.1"])
    nano = pricing.get("gpt-5-nano", _DEFAULT_PRICING["gpt-5-nano"])
    cost_now = (trivial_in * baseline["input"] + trivial_out * baseline["output"]) / 1_000_000
    cost_proposed = (trivial_in * nano["input"] + trivial_out * nano["output"]) / 1_000_000
    est_saving = round(cost_now - cost_proposed, 4)

    active = optimization_policy.get_active_policy(MODEL_SELECTION_SCENARIO)
    status = "active" if active else (
        (optimization_policy.get_policy(MODEL_SELECTION_SCENARIO) or {}).get("status", "not_proposed")
    )

    return {
        "scenario": MODEL_SELECTION_SCENARIO,
        "scenario_id": "SCEN-007",
        "title": "Capability-tiered model selection",
        "dimension": "model selection · cost efficiency",
        "maturity": "L4/L5 (lower-risk autonomous policy)",
        "status": status,
        "evidence": {
            "total_turns": total,
            "trivial_turns": trivial,
            "trivial_pct": round(100 * trivial / max(total, 1), 1),
            "model_distribution": models,
        },
        "estimated_saving_usd": est_saving,
        "estimate_caveat": (
            "ESTIMATE only. gpt-5-nano is a reasoning model that emits billed "
            "reasoning tokens, so trivial turns may not actually be cheaper. The "
            "measured before/after (verify step) is authoritative."
        ),
        "price_assumptions_usd_per_1m": pricing,
        "proposed_params": get_proposed_model_selection_params(),
        "actions": {
            "propose": f"POST /optimizations/{MODEL_SELECTION_SCENARIO}/propose",
            "apply": f"POST /optimizations/{MODEL_SELECTION_SCENARIO}/apply",
            "revert": f"POST /optimizations/{MODEL_SELECTION_SCENARIO}/revert",
        },
    }


def build_recommendations(tenant_id: str) -> list[dict[str, Any]]:
    """Return all candidate optimization cards for a tenant."""
    return [
        build_model_selection_recommendation(tenant_id),
        build_memory_retention_recommendation(tenant_id),
        build_city_context_recommendation(tenant_id),
        build_redundant_tool_recommendation(tenant_id),
        build_cost_per_outcome_diagnostic(tenant_id),
        build_agent_path_diagnostic(tenant_id),
    ]


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
    "prune": "superseded",  # soft-prune memories superseded by a newer one
}


def _memories_container():
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return None
    try:
        return cosmos.database.get_container_client(_MEMORIES_CONTAINER)
    except Exception:  # noqa: BLE001
        return None


def _superseded_memory_rows() -> list[dict]:
    """Memories that another memory supersedes (id ∈ some supersedes_ids)."""
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
    """Detect stale (superseded) memory accumulation (SCEN-004). Note: memory is
    keyed by (user_id, thread_id), not tenant, so this is a global memory-hygiene
    signal — the tenant_id argument is accepted for a uniform card interface."""
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

    active = optimization_policy.get_active_policy(MEMORY_RETENTION_SCENARIO)
    status = "active" if active else (
        (optimization_policy.get_policy(MEMORY_RETENTION_SCENARIO) or {}).get("status", "not_proposed")
    )
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

    Uses a partial PATCH (not a full upsert) so the large embedding vector is not
    rewritten. Returns the number of memories newly pruned.
    """
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
            logger.warning("Could not prune memory %s: %s", r.get("id"), exc)
    logger.info("Memory retention applied: pruned %d superseded memories", pruned)
    return pruned


def revert_memory_retention() -> int:
    """Un-prune: remove retention_status from previously pruned memories. Returns count."""
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
            logger.warning("Could not un-prune memory %s: %s", r.get("id"), exc)
    logger.info("Memory retention reverted: restored %d memories", restored)
    return restored


# ---------------------------------------------------------------------------
# SCEN-001 — active-trip city context: a HUMAN-GOVERNED (L3) prompt optimization.
# Unlike model selection, its "apply" does NOT toggle runtime — it STAGES a
# proposed prompt change for human review (a prompt change is higher-risk, so it
# caps at maturity L3 and goes through a PR).
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


def get_city_context_staged_change() -> dict[str, Any]:
    """The proposed prompt change (file + text) staged for human review."""
    return {
        "file": "python/src/app/prompts/supervisor.prompty",
        "add": PROPOSED_CITY_CONTEXT_CHANGE,
    }


def _query_assistant_texts(tenant_id: str) -> list[str]:
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return []
    try:
        rows = cosmos.database.get_container_client("Messages").query_items(
            query="SELECT d.role, d.content FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        )
        return [r.get("content", "") for r in rows
                if str(r.get("role", "")).lower() == "assistant" and isinstance(r.get("content"), str)]
    except Exception:  # noqa: BLE001
        return []


def _trip_count(tenant_id: str) -> int:
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return 0
    try:
        rows = list(cosmos.database.get_container_client("Trips").query_items(
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

    doc = optimization_policy.get_policy(CITY_CONTEXT_SCENARIO) or {}
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
        "proposed_change": get_city_context_staged_change(),
        "note": (
            "Because this is a prompt change (higher-risk), it cannot be applied at runtime. "
            "Staging it produces a reviewable proposal for a human to merge via PR (maturity L3)."
        ),
    }


# ---------------------------------------------------------------------------
# SCEN-008 — redundant tool calls: a HUMAN-GOVERNED (L3) prompt/code fix (staged).
# ---------------------------------------------------------------------------

TOOL_DEDUP_SCENARIO = "tool-call-dedup"

PROPOSED_TOOL_DEDUP_CHANGE = (
    "When a place/tool lookup for a query already returned results this turn, reuse them "
    "instead of calling the same tool again. Only re-query on a materially different search."
)


def get_tool_dedup_staged_change() -> dict[str, Any]:
    return {
        "file": "python/src/app/prompts/supervisor.prompty",
        "add": PROPOSED_TOOL_DEDUP_CHANGE,
    }


def _redundant_tool_turns(debug: list[dict]) -> int:
    """Turns whose agent_path calls the same (non-supervisor) tool back-to-back."""
    n = 0
    for d in debug:
        parts = [p.strip() for p in str(_bag(d).get("agent_path") or "").split(",") if p.strip()]
        if any(parts[i] == parts[i + 1] and parts[i] != "supervisor" for i in range(len(parts) - 1)):
            n += 1
    return n


def build_redundant_tool_recommendation(tenant_id: str) -> dict[str, Any]:
    """Detect redundant back-to-back tool calls (e.g. find_places,find_places) — SCEN-008."""
    debug = _query_debug(tenant_id)
    redundant = _redundant_tool_turns(debug)
    doc = optimization_policy.get_policy(TOOL_DEDUP_SCENARIO) or {}
    status = doc.get("status", "not_proposed")
    return {
        "scenario": TOOL_DEDUP_SCENARIO,
        "scenario_id": "SCEN-008",
        "title": "Redundant tool calls",
        "dimension": "agent quality · tool use",
        "maturity": "L3 (human-governed)",
        "apply_mode": "staged_change",
        "risk": "higher-risk (prompt/code change → human review / PR)",
        "status": status,
        "evidence": {
            "redundant_tool_turns": redundant,
            "total_turns": len(debug),
        },
        "rationale": (
            "Some turns invoke the same place-search tool twice in a row (e.g. "
            "find_places,find_places) — redundant token spend with no added grounding."
        ),
        "proposed_change": get_tool_dedup_staged_change(),
        "note": (
            "Prompt/code change (higher-risk) — stage for human review (maturity L3), "
            "not applied at runtime."
        ),
    }


# ---------------------------------------------------------------------------
# SCEN-003 / SCEN-005 — DIAGNOSTIC panels. These are lenses, not toggles: they
# tell you WHERE spend concentrates so you can pick the right apply-able fix.
# They carry apply_mode="diagnostic" (no apply/stage) and status="insight".
# ---------------------------------------------------------------------------

def _converting_users(tenant_id: str) -> set:
    """User ids with at least one confirmed/completed trip (an 'outcome')."""
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return set()
    try:
        rows = cosmos.database.get_container_client("Trips").query_items(
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


def _converted_sessions(tenant_id: str) -> set:
    """Session ids with a confirmed/completed trip (session-level conversion)."""
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return set()
    try:
        rows = cosmos.database.get_container_client("Trips").query_items(
            query="SELECT d.sessionId, d.status FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        )
        return {r.get("sessionId") for r in rows
                if r.get("sessionId") and str(r.get("status", "")).lower() in ("confirmed", "completed")}
    except Exception:  # noqa: BLE001
        return set()


def _session_friction(tenant_id: str) -> dict[str, dict]:
    """Per session: whether the agent re-asked the city or dead-ended a search."""
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return {}
    out: dict[str, dict] = {}
    try:
        rows = cosmos.database.get_container_client("Messages").query_items(
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


# Maps the dominant abandonment cause to the concrete lever that addresses it.
_ABANDON_FIX = {
    "city_friction": "the active-trip city-context prompt fix (SCEN-001) — it lifts conversion, not just cost",
    "cart_abandon": "a proactive 'shall I book it?' confirmation at the itinerary step",
    "no_results": "better place-search grounding (broaden/relax the query before giving up)",
    "search_stall": "clearer next-step prompting after a search returns",
    "no_engagement": "earlier intent clarification so vague sessions reach a search",
}


def _conversion_funnel(tenant_id: str) -> dict[str, Any]:
    """Session-level funnel (Engaged->Searched->Planned->Confirmed) + why sessions leak."""
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
        "sessions": len(sessions),
        "funnel": funnel,
        "abandonment": abandon,
        "wasted_tokens": wasted,
        "total_tokens": total,
        "confirmed_sessions": funnel["confirmed"],
    }


def build_cost_per_outcome_diagnostic(tenant_id: str) -> dict[str, Any]:
    """Cost per outcome upleveled to a conversion funnel (SCEN-003): not just *how
    much* is wasted, but *where* sessions leak and *why* — pointing at the fix."""
    f = _conversion_funnel(tenant_id)
    total_tokens = f["total_tokens"]
    wasted = f["wasted_tokens"]
    confirmed = f["confirmed_sessions"]
    abandon = f["abandonment"]
    # The biggest addressable leak (ignore no_engagement — usually not worth chasing).
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
        path = _bag(d).get("agent_path") or "unknown"
        tok = int(_bag(d).get("total_tokens") or 0)
        a = agg.setdefault(str(path), [0, 0])
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
        "evidence": {
            "paths": rows[:6],
        },
        "rationale": (
            "A few agent paths (typically the itinerary path) dominate token cost — often "
            "many times a plain supervisor turn. That's where tiering and tool fixes pay off."
        ),
        "note": (
            "A lens: act via model tiering (SCEN-007) on the expensive paths and by removing "
            "redundant tool calls (SCEN-008)."
        ),
    }

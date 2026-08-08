"""
Optimization recommendations (the *recommend* stage of the analytics loop).

Turns signal the app already captures (Debug turn logs) into candidate
"optimization cards" a dashboard can show and a user can apply with one click.
Today this produces the model selection candidate card.

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
    "complexity_tiers": {
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
    """Proposed complexity_tier/classifier policy from the Configuration container → code default."""
    try:
        from src.app.services import configuration_store

        doc = configuration_store.get_model_selection_defaults()
        if doc and isinstance(doc.get("complexity_tiers"), dict):
            return {
                "enabled": bool(doc.get("enabled", True)),
                "default_deployment": doc.get(
                    "default_deployment", _CODE_MODEL_SELECTION_PARAMS["default_deployment"]
                ),
                "complexity_tiers": doc["complexity_tiers"],
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
    """Build the model selection candidate card from Debug turn logs for a tenant."""
    dbg = _query_debug(tenant_id)
    total = len(dbg)

    # IMPORTANT — this card measures the model-selection *opportunity*, which is NOT
    # the same as the "Trivial-turn share" KPI. The classifier's `complexity_tier ==
    # "trivial"` turns are already routed to nano (trivial-tier -> nano policy), so
    # there is no saving left to harvest from them. The real downgrade opportunity is
    # turns that ran on a PREMIUM model yet produced short output (a cheaper tier
    # likely sufficed). That is the same signal the per-agent scorecard's
    # model_selection dimension flags (premium deployment + output < LOW_COMPLEXITY_
    # OUTPUT), computed here at turn grain. We call these "downgrade candidates" — the
    # word "trivial" is reserved for the classifier tier so the report has ONE
    # definition of "trivial" (the 22.8% KPI), not three.
    PREMIUM = {"gpt-5.1", "gpt-5"}
    SHORT_OUTPUT_MAX = 250  # mirrors engine LOW_COMPLEXITY_OUTPUT (scorecard downgrade threshold)
    candidates = 0
    cand_in = cand_out = 0
    models: dict[str, int] = {}
    for d in dbg:
        b = _bag(d)
        models[b.get("model_name", "Unknown")] = models.get(b.get("model_name", "Unknown"), 0) + 1
        out = int(b.get("output_tokens") or 0)
        if b.get("model_deployment") in PREMIUM and out < SHORT_OUTPUT_MAX:
            candidates += 1
            cand_in += int(b.get("input_tokens") or 0)
            cand_out += out

    # Estimated saving IF those premium-but-short turns moved from the default
    # (gpt-5.1) -> nano, using the tokens actually observed on those turns. Optimistic:
    # ignores nano reasoning tokens, which is why the verify step (measured
    # before/after) is the real proof.
    pricing = load_pricing()
    baseline = pricing.get("gpt-5.1", _DEFAULT_PRICING["gpt-5.1"])
    nano = pricing.get("gpt-5-nano", _DEFAULT_PRICING["gpt-5-nano"])
    cost_now = (cand_in * baseline["input"] + cand_out * baseline["output"]) / 1_000_000
    cost_proposed = (cand_in * nano["input"] + cand_out * nano["output"]) / 1_000_000
    est_saving = round(cost_now - cost_proposed, 4)

    active = optimization_policy.get_active_policy(MODEL_SELECTION_SCENARIO)
    status = "active" if active else (
        (optimization_policy.get_policy(MODEL_SELECTION_SCENARIO) or {}).get("status", "not_proposed")
    )

    return {
        "scenario": MODEL_SELECTION_SCENARIO,
        "scenario_id": "model-selection",
        "title": "Capability-tiered model selection",
        "dimension": "model selection · cost efficiency",
        "maturity": "L4/L5 (lower-risk autonomous policy)",
        "status": status,
        "evidence": {
            "total_turns": total,
            "downgrade_candidates": candidates,
            "downgrade_pct": round(100 * candidates / max(total, 1), 1),
            "model_distribution": models,
        },
        "estimated_saving_usd": est_saving,
        "estimate_caveat": (
            "ESTIMATE only. gpt-5-nano is a reasoning model that emits billed "
            "reasoning tokens, so these premium-but-short turns may not actually be "
            "cheaper. The "
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


def _card_has_signal(card: dict[str, Any]) -> bool:
    """A card is worth showing only when its underlying data has signal. Keeps the
    console clean on a fresh/low-traffic tenant instead of rendering empty cards."""
    ev = card.get("evidence", {}) or {}
    scen = card.get("scenario")
    if scen == MODEL_SELECTION_SCENARIO:
        return int(ev.get("total_turns") or 0) > 0
    if scen == MEMORY_RETENTION_SCENARIO:
        return int(ev.get("total_memories") or 0) > 0
    if scen == TOOL_DEDUP_SCENARIO:
        # Only surface when there is an actual redundant tool call to review — not
        # merely because the dataset has traffic.
        return int(ev.get("redundant_tool_turns") or 0) > 0
    if scen == "cost-per-outcome":
        return int(ev.get("total_tokens") or 0) > 0
    if scen == "agent-path-cost":
        # Cost *concentration* needs at least two distinct paths to compare; a dataset
        # where every turn is a bare "supervisor" turn (no tools) has nothing to show.
        return len(ev.get("paths") or []) >= 2
    return True


def build_recommendations(tenant_id: str) -> list[dict[str, Any]]:
    """Return candidate optimization cards for a tenant (only those with signal)."""
    cards = [
        build_model_selection_recommendation(tenant_id),
        build_memory_retention_recommendation(tenant_id),
        build_redundant_tool_recommendation(tenant_id),
        build_cost_per_outcome_diagnostic(tenant_id),
        build_agent_path_diagnostic(tenant_id),
    ]
    # An empty dataset (no captured turns) should open completely empty. The other
    # cards self-gate on their own signal; the memory card is *global* (not tied to a
    # dataset), so we additionally gate its display on this dataset having any activity
    # — otherwise a brand-new dataset would show a lone memory card.
    ms_turns = int((cards[0].get("evidence") or {}).get("total_turns") or 0)
    dbg_turns = int((cards[2].get("evidence") or {}).get("total_turns") or 0)
    has_activity = ms_turns > 0 or dbg_turns > 0
    out: list[dict[str, Any]] = []
    for c in cards:
        if c.get("scenario") == MEMORY_RETENTION_SCENARIO and not has_activity:
            continue
        if _card_has_signal(c):
            out.append(c)
    return out


def summarize_card_evidence(card: dict[str, Any]) -> str:
    """A compact, one-line evidence summary for a recommendation card.

    The rich per-scenario ``evidence`` dict lives nested inside the card object,
    which does NOT surface as columns over the Fabric mirror (DirectQuery only
    sees flat top-level fields). The reverse-ETL flattens this string onto each
    ``recommendation_card`` row so Power BI can render the same headline numbers
    the Console shows — without reaching into the nested object.
    """
    ev = card.get("evidence") or {}
    scen = card.get("scenario")

    def _i(key: str) -> int:
        try:
            return int(ev.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    if scen == MODEL_SELECTION_SCENARIO:
        models = ev.get("model_distribution") or {}
        return (f"{_i('total_turns'):,} turns \u00b7 {_i('downgrade_candidates'):,} downgrade "
                f"candidates ({ev.get('downgrade_pct', 0)}%) \u00b7 {len(models)} models")
    if scen == MEMORY_RETENTION_SCENARIO:
        line = (f"{_i('total_memories'):,} memories \u00b7 {_i('superseded_memories'):,} "
                f"superseded ({ev.get('superseded_pct', 0)}%)")
        saved = ev.get("measured_saving_usd") or 0
        if saved:
            line += (f" \u00b7 measured saving ${saved:,.2f} over "
                     f"{_i('measured_recalls'):,} recalls")
        return line
    if scen == TOOL_DEDUP_SCENARIO:
        return f"{_i('redundant_tool_turns'):,} redundant tool turns of {_i('total_turns'):,}"
    if scen == "cost-per-outcome":
        return (f"{_i('total_tokens'):,} tokens \u00b7 {ev.get('wasted_pct', 0)}% wasted \u00b7 "
                f"{_i('confirmed_sessions'):,} outcomes \u00b7 {_i('tokens_per_outcome'):,}/outcome")
    if scen == "agent-path-cost":
        paths = ev.get("paths") or []
        if not paths:
            return ""
        top = paths[0]
        return (f"{len(paths)} paths \u00b7 costliest {int(top.get('avg_tokens') or 0):,} "
                f"avg tok/turn")
    return ""


def card_caveat(card: dict[str, Any]) -> str:
    """The card's caveat / limitation text — the Console's yellow ⚠️ line.

    Model-selection and memory carry ``estimate_caveat``; the diagnostics carry a
    ``note``. Flattened onto the card row by the reverse-ETL for the BI cards.
    """
    return str(card.get("estimate_caveat") or card.get("note") or "")


# ---------------------------------------------------------------------------
# Read the Fabric-computed (reverse-ETL'd) cards/metrics from OptimizationInsights.
# This CLOSES the analytics loop: the Console reads pre-computed results instead
# of recomputing aggregations from Cosmos on every request. The in-app build_*
# functions above remain the low-dependency "peek" (Module 07) / --local fallback,
# used automatically whenever the loop hasn't populated OptimizationInsights yet.
# ---------------------------------------------------------------------------

INSIGHTS_CONTAINER = "OptimizationInsights"
_insights_container = None


def _get_insights_container():
    global _insights_container
    if _insights_container is not None:
        return _insights_container
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return None
    try:
        _insights_container = cosmos.database.get_container_client(INSIGHTS_CONTAINER)
    except Exception as exc:  # noqa: BLE001
        logger.warning("OptimizationInsights container unavailable: %s", exc)
        return None
    return _insights_container


def read_recommendations_from_insights(tenant_id: str) -> list[dict[str, Any]] | None:
    """Fabric-computed recommendation cards, or None if the loop hasn't populated them.

    The volatile policy ``status`` is re-stamped from the live policy store so the
    Console's apply/revert state is always current even though the evidence was
    computed analytically (analysis analytical, act operational).
    """
    container = _get_insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t AND d.type='recommendation_card'",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("reverse-ETL recommendations read failed: %s", exc)
        return None
    if not rows:
        return None
    cards: list[dict[str, Any]] = []
    for r in sorted(rows, key=lambda x: x.get("order", 99)):
        card = dict(r.get("card") or {})
        if not card:
            continue
        scenario = card.get("scenario")
        active = optimization_policy.get_active_policy(scenario)
        card["status"] = "active" if active else (
            (optimization_policy.get_policy(scenario) or {}).get("status", card.get("status", "not_proposed"))
        )
        card["source"] = "fabric"
        card["computed_at"] = r.get("computed_at")
        cards.append(card)
    return cards or None


def read_metrics_from_insights(tenant_id: str) -> dict[str, Any] | None:
    """Fabric-computed Console KPIs, or None if the loop hasn't populated them."""
    container = _get_insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t AND d.type='turn_metrics'",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("reverse-ETL metrics read failed: %s", exc)
        return None
    if not rows:
        return None
    metrics = dict(rows[0].get("metrics") or {})
    if not metrics:
        return None
    metrics["source"] = "fabric"
    metrics["computed_at"] = rows[0].get("computed_at")
    return metrics


def read_conversion_from_insights(tenant_id: str) -> dict[str, Any] | None:
    """Fabric-computed conversion funnel + abandonment causes + KPI (the same rows
    Power BI's Business Impact page reads), or None if the loop hasn't populated them."""
    container = _get_insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query=("SELECT * FROM d WHERE d.tenantId=@t AND "
                   "d.type IN ('funnel_stage','abandonment_cause','conversion_kpi')"),
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("reverse-ETL conversion read failed: %s", exc)
        return None
    if not rows:
        return None
    funnel = sorted(
        [{"stage": r.get("stage"), "stage_order": r.get("stage_order"), "sessions": r.get("sessions")}
         for r in rows if r.get("type") == "funnel_stage"],
        key=lambda x: x.get("stage_order") or 0)
    causes = sorted(
        [{"cause": r.get("cause"), "sessions": r.get("sessions")}
         for r in rows if r.get("type") == "abandonment_cause"],
        key=lambda x: -(x.get("sessions") or 0))
    kpi_rows = [r for r in rows if r.get("type") == "conversion_kpi"]
    kpi = ({k: kpi_rows[0].get(k) for k in
            ("engaged", "confirmed", "conversion_rate", "wasted_pct", "tokens_per_outcome", "biggest_leak")}
           if kpi_rows else {})
    return {"tenant_id": tenant_id, "source": "fabric", "funnel": funnel, "causes": causes, "kpi": kpi}


def read_memory_insights() -> dict[str, Any] | None:
    """Fabric-computed memory-intelligence buckets + KPI (the same rows Power BI's
    Memory page reads), or None. Memory rows are global (``_global_memory`` partition)."""
    container = _get_insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query=("SELECT * FROM d WHERE d.type IN "
                   "('memory_type','memory_salience','memory_health','memory_kpi')"),
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("reverse-ETL memory read failed: %s", exc)
        return None
    if not rows:
        return None

    def buckets(t: str) -> list[dict[str, Any]]:
        return [{"label": r.get("label"), "count": r.get("count")} for r in rows if r.get("type") == t]

    kpi_rows = [r for r in rows if r.get("type") == "memory_kpi"]
    kpi = ({k: kpi_rows[0].get(k) for k in
            ("total_memories", "scored_memories", "avg_salience", "supersession_rate", "superseded_pct")}
           if kpi_rows else {})
    return {"source": "fabric", "by_type": buckets("memory_type"),
            "salience": buckets("memory_salience"), "health": buckets("memory_health"), "kpi": kpi}


def read_agent_paths_from_insights(tenant_id: str) -> dict[str, Any] | None:
    """Fabric-computed agent-path cost concentration (the rows Power BI's Agent
    Collaboration page reads): one row per agent_path with turns/total_tokens/avg_tokens."""
    container = _get_insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t AND d.type='agent_path_cost'",
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("reverse-ETL agent_path read failed: %s", exc)
        return None
    if not rows:
        return None
    paths = sorted(
        [{"agent_path": r.get("agent_path"), "turns": r.get("turns"),
          "total_tokens": r.get("total_tokens"), "avg_tokens": r.get("avg_tokens")} for r in rows],
        key=lambda x: -(x.get("total_tokens") or 0))
    grand = sum((p.get("total_tokens") or 0) for p in paths) or 1
    for p in paths:
        p["token_share"] = round((p.get("total_tokens") or 0) / grand, 4)
    return {"tenant_id": tenant_id, "source": "fabric", "total_tokens": grand, "paths": paths}


def read_optimization_result_from_insights(tenant_id: str) -> dict[str, Any] | None:
    """Measured before/after results per optimization (scenario-keyed), or None.

    Results are keyed by scenario under a reserved partition — not by tenant — so the
    tenant argument is accepted for route compatibility but isn't used as a filter."""
    container = _get_insights_container()
    if container is None:
        return None
    try:
        rows = list(container.query_items(
            query="SELECT * FROM d WHERE d.type='optimization_result'",
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("reverse-ETL result read failed: %s", exc)
        return None
    if not rows:
        return None
    results = sorted(
        [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows],
        key=lambda r: r.get("scenario", ""))
    return {"source": "fabric", "results": results}


# ---------------------------------------------------------------------------
# Memory retention: a lower-risk AUTONOMOUS (L4/L5) policy. Memory
# accumulates superseded ("stale") entries as preferences change; applying the
# policy soft-prunes them (a reversible mark), so recall stays cheaper/cleaner.
# "Superseded" = a memory whose own `superseded_by` pointer is set (it was
# replaced by a newer memory). This is the SINGLE canonical definition, shared
# with the memory_health "Superseded" bucket, the Supersession Rate KPI, and
# Power BI's [Supersession Rate %] measure — so every "superseded"/"supersession"
# number agrees across the dashboard, the reverse-ETL, and Power BI.
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
    """Memories that have been superseded — i.e. their own `superseded_by` pointer is set.

    This is the SAME canonical definition used by the memory_health "Superseded" bucket,
    the Supersession Rate KPI, and Power BI's [Supersession Rate %] measure, so the
    memory-retention card's count/percent (and what `apply_memory_retention` prunes) agree
    with them exactly — one definition of "superseded", not two.
    """
    container = _memories_container()
    if container is None:
        return []
    try:
        rows = list(container.query_items(
            query="SELECT c.id, c.user_id, c.thread_id, c.superseded_by, c.retention_status FROM c",
            enable_cross_partition_query=True,
        ))
    except Exception:  # noqa: BLE001
        return []
    return [r for r in rows if r.get("superseded_by")]


# --- recall-time memory-retention measurement (the hook the recall tool calls) ----
# Keeps the `recall_memories` MCP tool thin: the tool hands its recall hits to
# `prune_and_measure_recall`, which drops pruned memories AND records the input tokens
# each drop avoids. Housing this in the optimization service (not the tool) makes it the
# single home for the logic — adopting it in another app is one hook call from the recall.
try:
    import tiktoken
    _MEM_ENCODER = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001 - tokenizer optional; fall back to a char estimate
    _MEM_ENCODER = None


def _count_tokens(text: str) -> int:
    """Token count for a memory's content (tiktoken when available, else ~chars/4)."""
    if not text:
        return 0
    if _MEM_ENCODER is not None:
        try:
            return len(_MEM_ENCODER.encode(text))
        except Exception:  # noqa: BLE001
            pass
    return max(1, len(text) // 4)


def prune_and_measure_recall(records: list[dict[str, Any]], user_id: str,
                             thread_id: str | None = None, query: str = "",
                             top_k: int = 10) -> list[dict[str, Any]]:
    """Recall hook: drop pruned memories and record the input tokens each drop avoids.

    The ``recall_memories`` MCP tool calls this with its recall hits (as dicts). A pruned
    memory that ranked into the top-k is dropped with no backfill, so its tokens are input
    cost the model no longer pays — recorded as one best-effort ``recall_pruned_avoided``
    ApiEvent (global ``_global_memory`` key). Returns the kept memories in original order.
    """
    kept: list[dict[str, Any]] = []
    excluded = avoided = 0
    for d in records:
        if d.get("retention_status") == "pruned":
            excluded += 1
            avoided += _count_tokens(str(d.get("content") or ""))
        else:
            kept.append(d)
    if excluded:
        try:
            cosmos.record_api_event(
                session_id=thread_id or "unknown", tenant_id="_global_memory",
                provider="memory", operation="recall_pruned_avoided",
                request={"user_id": user_id, "thread_id": thread_id, "query": query, "top_k": top_k},
                response={"returned": len(kept), "excluded_pruned": excluded,
                          "avoided_input_tokens": avoided},
                keywords=["memory-retention", "avoided-tokens"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("recall-savings telemetry skipped: %s", exc)
    return kept


def _memory_recall_savings() -> dict[str, Any]:
    """Measured memory-retention impact aggregated from recall telemetry (ApiEvents).

    Each ``recall_pruned_avoided`` event records the input tokens a recall avoided by
    dropping a pruned (superseded) memory that had ranked into its top-k. Summed and
    priced at the default deployment's input rate, that is the *measured* saving of the
    memory-retention optimization — ``$0`` until the policy is applied and recalls run
    (never a fabricated estimate). Global: memory is user/thread-keyed, not tenant."""
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return {"recalls": 0, "avoided_tokens": 0, "saving_usd": 0.0}
    try:
        rows = list(cosmos.database.get_container_client("ApiEvents").query_items(
            query=("SELECT c.response FROM c WHERE c.provider='memory' "
                   "AND c.operation='recall_pruned_avoided'"),
            enable_cross_partition_query=True,
        ))
    except Exception as exc:  # noqa: BLE001
        logger.warning("recall-savings aggregation failed: %s", exc)
        return {"recalls": 0, "avoided_tokens": 0, "saving_usd": 0.0}
    avoided = sum(int((r.get("response") or {}).get("avoided_input_tokens") or 0) for r in rows)
    input_price = load_pricing().get("gpt-5.1", _DEFAULT_PRICING["gpt-5.1"])["input"]
    return {"recalls": len(rows), "avoided_tokens": avoided,
            "saving_usd": round(avoided * input_price / 1_000_000, 4)}


def build_memory_retention_recommendation(tenant_id: str) -> dict[str, Any]:
    """Detect stale (superseded) memory accumulation. Note: memory is
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
    savings = _memory_recall_savings()

    active = optimization_policy.get_active_policy(MEMORY_RETENTION_SCENARIO)
    status = "active" if active else (
        (optimization_policy.get_policy(MEMORY_RETENTION_SCENARIO) or {}).get("status", "not_proposed")
    )
    return {
        "scenario": MEMORY_RETENTION_SCENARIO,
        "scenario_id": "memory-retention",
        "title": "Memory retention (prune stale memories)",
        "dimension": "memory · global — spans all users (not tenant-scoped) · cost + quality",
        "maturity": "L4/L5 (lower-risk autonomous policy)",
        "apply_mode": "policy",
        "status": status,
        # MEASURED (not estimated): the input tokens recalls actually avoided by dropping
        # pruned memories, priced at the default input rate. $0 until the policy is applied
        # and recalls run — deliberately never a fabricated pre-apply estimate.
        "estimated_saving_usd": savings["saving_usd"],
        "evidence": {
            "total_memories": total,
            "superseded_memories": n_sup,
            "superseded_pct": round(100 * n_sup / max(total, 1), 1),
            "pruned_memories": n_pruned,
            "avoided_recall_tokens": savings["avoided_tokens"],
            "measured_recalls": savings["recalls"],
            "measured_saving_usd": savings["saving_usd"],
        },
        "rationale": (
            "Preferences change, so memory accumulates superseded entries. A large stale share "
            "means recall wades through (and pays for) memories that no longer apply."
        ),
        "estimate_caveat": (
            "Global signal — memory is keyed by user, not tenant, so this card reads the "
            "same for every tenant. Applying soft-prunes superseded memories (a reversible mark). Recall excludes pruned "
            "memories where the memory client surfaces the flag; the mark is always reversible. "
            "The saving is MEASURED from recall telemetry (input tokens avoided when a pruned "
            "memory is dropped from a recall's top-k), not estimated — so it reads $0 until the "
            "policy is applied and recalls run."
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
# Redundant tool calls: a HUMAN-GOVERNED (L3) prompt/code fix (staged).
# ---------------------------------------------------------------------------

TOOL_DEDUP_SCENARIO = "tool-call-dedup"


def _redundant_tool_turns(debug: list[dict]) -> int:
    """Turns whose agent_path calls the same (non-supervisor) tool back-to-back."""
    n = 0
    for d in debug:
        parts = [p.strip() for p in str(_bag(d).get("agent_path") or "").split(",") if p.strip()]
        if any(parts[i] == parts[i + 1] and parts[i] != "supervisor" for i in range(len(parts) - 1)):
            n += 1
    return n


def build_redundant_tool_recommendation(tenant_id: str) -> dict[str, Any]:
    """Surface the repeated-node structural pattern as a MANUAL (human-deployed) optimization.

    Detecting the pattern is operational (telemetry). The engine proposes a conservative,
    rule-based tool-use guardrail for ``supervisor.prompty`` (see the ``/opportunity/.../diff``
    endpoint) — reviewable as a GitHub-style diff. It is never auto-applied: a human reviews
    the diff, edits and deploys the prompt file, and re-measures (apply_mode ``staged_change``
    / autonomy ceiling L3 — "Manual").
    """
    debug = _query_debug(tenant_id)
    return {
        "scenario": TOOL_DEDUP_SCENARIO,
        "scenario_id": "tool-call-dedup",
        "title": "Redundant tool calls",
        "dimension": "agent quality · tool use",
        "maturity": "manual (review & deploy)",
        "apply_mode": "staged_change",
        "autonomy_ceiling": "L3",
        "seam": "prompt",
        "target": "supervisor.prompty",
        "opportunity_id": "opp-repeated-node",
        "evidence": {
            "redundant_tool_turns": _redundant_tool_turns(debug),
            "total_turns": len(debug),
        },
        "rationale": (
            "Some turns show the same agent/tool repeated back-to-back in agent_path — a "
            "generic structural telemetry pattern that often means redundant token spend."
        ),
        "note": (
            "Manual optimization — the engine proposes a conservative, rule-based tool-use "
            "guardrail for supervisor.prompty. Review the diff, then edit and deploy the prompt "
            "file yourself (the app never edits it) and re-measure."
        ),
    }


# ---------------------------------------------------------------------------
# Cost per outcome / agent-path cost concentration diagnostics. These are lenses, not toggles: they
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

_DESTINATION_CLARIFICATION_RE = re.compile(
    r"which city|what city|city (is|are) (it|this|that|you|the hotel)"
    r"|in which city|which city .* located|what city .* in",
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


def count_confirmed_trips(tenant_id: str) -> int:
    """Count of booked-trip outcomes for a tenant = Trip docs with status
    confirmed/completed (Option A). Tenant-scoped and independent of ``sessionId``
    (analytics trips carry a null sessionId), matching the Power BI ``Confirmed Trips``
    measure once that measure is tenant-scoped via TREATAS.
    """
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        return 0
    try:
        rows = list(cosmos.database.get_container_client("Trips").query_items(
            query=("SELECT VALUE COUNT(1) FROM d WHERE d.tenantId=@t "
                   "AND (d.status='confirmed' OR d.status='completed')"),
            parameters=[{"name": "@t", "value": tenant_id}],
            enable_cross_partition_query=True,
        ))
        return int(rows[0]) if rows else 0
    except Exception:  # noqa: BLE001
        return 0


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
        if _DESTINATION_CLARIFICATION_RE.search(r["content"]):
            f["city_reask"] = True
        if _NO_RESULTS_RE.search(r["content"]):
            f["no_results"] = True
    return out


# Maps the dominant abandonment cause to the concrete lever that addresses it.
_ABANDON_FIX = {
    "city_friction": "sessions that stalled clarifying the destination — the biggest addressable conversion leak",
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

    # Conversion is session-level when trips carry a sessionId (e.g. analytics),
    # else falls back to user-level (real trips have no sessionId).
    converted_sessions = _converted_sessions(tenant_id)
    converting_users = _converting_users(tenant_id)
    friction = _session_friction(tenant_id)
    funnel = {"engaged": 0, "searched": 0, "planned": 0, "confirmed": 0}
    abandon = {"cart_abandon": 0, "city_friction": 0, "no_results": 0, "search_stall": 0, "no_engagement": 0}
    wasted = total = 0
    for sid, s in sessions.items():
        total += s["tokens"]
        converted = sid in converted_sessions or s.get("user") in converting_users
        if converted:
            # A booked trip means the session necessarily searched and planned, even if
            # the agent_path telemetry for those earlier stages wasn't captured. Credit
            # the whole journey so a real confirmation always advances the funnel.
            s["searched"] = True
            s["planned"] = True
        funnel["engaged"] += 1
        if s["searched"]:
            funnel["searched"] += 1
        if s["planned"]:
            funnel["planned"] += 1
        if converted:
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
    """Cost per outcome upleveled to a conversion funnel: not just *how
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
        "scenario_id": "cost-per-outcome",
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
    """Where the tokens go: cost concentrated in a few agent_paths."""
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
        "scenario_id": "agent-path-cost",
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
            "A lens: act via model tiering on the expensive paths and by removing "
            "redundant tool calls."
        ),
    }


# ---------------------------------------------------------------------------
# Aggregate KPIs for the Optimization Console (GET /optimizations/{tenant}/metrics).
# ---------------------------------------------------------------------------

def _price_for(pricing: dict[str, dict[str, float]], deployment: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for a deployment/model name. ESTIMATE."""
    name = (deployment or "").lower()
    for key, p in pricing.items():
        if name.startswith(key.lower()):
            return float(p.get("input", 0.0)), float(p.get("output", 0.0))
    default = pricing.get("gpt-5.1", _DEFAULT_PRICING["gpt-5.1"])
    return float(default["input"]), float(default["output"])


def _canonical_model(name: str) -> str:
    """Collapse a versioned model name (e.g. ``gpt-5.1-2025-11-13``) to its deployment label
    (``gpt-5.1``) so the same model isn't split across two donut slices — some turns carry the
    deployment (``model_deployment``), others only the dated ``model_name``."""
    n = name or "Unknown"
    parts = n.rsplit("-", 3)  # a trailing -YYYY-MM-DD, if present
    if len(parts) == 4 and all(p.isdigit() for p in parts[1:]):
        return parts[0]
    return n


def build_turn_metrics(tenant_id: str) -> dict[str, Any]:
    """Aggregate the captured turns into the KPIs the Console displays."""
    dbg = _query_debug(tenant_id)
    pricing = load_pricing()
    total = len(dbg)
    total_in = total_out = total_tokens = total_cached = trivial = 0
    est_cost = 0.0
    models: dict[str, int] = {}
    by_tier: dict[str, dict[str, Any]] = {}

    for d in dbg:
        b = _bag(d)
        i = int(b.get("input_tokens") or 0)
        o = int(b.get("output_tokens") or 0)
        total_in += i
        total_out += o
        total_tokens += int(b.get("total_tokens") or 0)
        total_cached += int(b.get("cached_tokens") or 0)
        # Tier: Debug stores it under `model_tier` (complexity_tier is null there);
        # the mirrored OptimizationTurns renames it to complexity_tier. Coalesce so the
        # dashboard's Trivial % and cost-by-tier match Power BI's complexity_tier split.
        tier = b.get("complexity_tier") or b.get("model_tier") or "default"
        if tier == "trivial":
            trivial += 1
        dep = _canonical_model(b.get("model_deployment") or b.get("model_name", "Unknown"))
        models[dep] = models.get(dep, 0) + 1
        pin, pout = _price_for(pricing, dep)
        cost = (i * pin + o * pout) / 1_000_000
        est_cost += cost
        key = f"{tier} ({dep})"
        row = by_tier.setdefault(key, {"complexity_tier": tier, "deployment": dep,
                                       "turns": 0, "tokens": 0, "cost": 0.0})
        row["turns"] += 1
        row["tokens"] += int(b.get("total_tokens") or 0)
        row["cost"] += cost

    confirmed = count_confirmed_trips(tenant_id)
    return {
        "tenant_id": tenant_id,
        "total_turns": total,
        "total_input_tokens": total_in,
        "total_output_tokens": total_out,
        "total_tokens": total_tokens,
        "total_cached_tokens": total_cached,
        "cache_hit_pct": round(100 * total_cached / max(total_in, 1), 1),
        "estimated_cost_usd": round(est_cost, 4),
        "trivial_turns": trivial,
        "trivial_pct": round(100 * trivial / max(total, 1), 1),
        "distinct_models": len(models),
        "model_distribution": models,
        "confirmed_outcomes": confirmed,
        "cost_per_outcome_usd": round(est_cost / confirmed, 4) if confirmed else None,
        "by_tier": sorted(by_tier.values(), key=lambda r: -r["cost"]),
    }


def build_turns_timeline(tenant_id: str, bucket_seconds: int = 60) -> dict[str, Any]:
    """Per-bucket turn counts over time (for the "turns over time" chart).

    Buckets the captured turns by their ``timeStamp`` (falling back to ``_ts``) into
    ``bucket_seconds`` windows. Computed live from the Debug docs — the same raw turns
    Power BI's ``OptimizationTurns[Turn Minute]`` line reads.
    """
    from datetime import datetime, timezone

    dbg = _query_debug(tenant_id)
    bucket_seconds = max(1, int(bucket_seconds or 60))
    counts: dict[int, int] = {}
    for d in dbg:
        epoch = None
        ts = d.get("timeStamp")
        if isinstance(ts, str):
            try:
                epoch = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except Exception:  # noqa: BLE001
                epoch = None
        if epoch is None:
            epoch = d.get("_ts")
        if epoch is None:
            continue
        bkt = int(int(epoch) // bucket_seconds) * bucket_seconds
        counts[bkt] = counts.get(bkt, 0) + 1
    buckets = [
        {"t": datetime.fromtimestamp(b, tz=timezone.utc).isoformat(), "epoch": b, "turns": counts[b]}
        for b in sorted(counts)
    ]
    return {"tenant_id": tenant_id, "bucket_seconds": bucket_seconds,
            "total_turns": sum(counts.values()), "buckets": buckets}

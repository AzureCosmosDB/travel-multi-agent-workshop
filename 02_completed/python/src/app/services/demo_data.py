"""Demo-data helpers.

``refresh_turn_times`` re-stamps every captured ``OptimizationTurns`` document's
``turn_epoch`` / ``timeStamp`` uniformly across the last N minutes (ending now),
so the analytics report's time-series charts (turns/cost over time) show a recent,
dense trend instead of the fixed dates baked into the seed data. It changes
timestamps ONLY — never turn content — and every KPI/cost the app computes is
time-independent, so those are unaffected. This is a demo/ops convenience so a
presenter can freshen the report without a full reseed.
"""

from __future__ import annotations

import concurrent.futures
import logging
import random
import time
import uuid
from typing import Any

from azure.cosmos.exceptions import CosmosHttpResponseError

from src.app.services import azure_cosmos_db as cosmos

logger = logging.getLogger(__name__)

OPTIMIZATION_TURNS_CONTAINER = "OptimizationTurns"
DEBUG_CONTAINER = "Debug"


def _iso(epoch: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _restamp_container(container, start: int, now: int, set_turn_epoch: bool) -> int:
    """Spread every doc's ``timeStamp`` (and ``turn_epoch`` when set_turn_epoch) uniformly
    across [start, now]. Retries on 429 (TooManyRequests). Returns the count re-stamped."""
    docs = list(container.query_items("SELECT * FROM c", enable_cross_partition_query=True))

    def _restamp(doc: dict) -> None:
        e = random.randint(start, now)
        if set_turn_epoch:
            doc["turn_epoch"] = e
        doc["timeStamp"] = _iso(e)
        # Modest concurrency can still outrun the container's provisioned RU/s, so back
        # off and retry on 429 rather than failing the whole refresh.
        for attempt in range(8):
            try:
                container.upsert_item(doc)
                return
            except CosmosHttpResponseError as exc:
                if getattr(exc, "status_code", None) == 429 and attempt < 7:
                    time.sleep(min(0.1 * (2 ** attempt), 2.0))
                    continue
                raise

    if docs:
        # Keep concurrency low so we don't spike RU and trigger sustained throttling.
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(_restamp, docs))
    return len(docs)


def refresh_turn_times(window_minutes: int = 120) -> dict[str, Any]:
    """Spread every captured turn's timestamp uniformly across the last ``window_minutes``
    (ending now) so the analytics time-series charts read current. Re-stamps BOTH the
    ``OptimizationTurns`` analytical signal AND the raw ``Debug`` telemetry — the live
    turns-by-minute chart (``build_turns_timeline``) and the KPI tiles bucket by
    ``Debug.timeStamp``, while the reverse-ETL / Power BI path reads ``OptimizationTurns``.
    Timestamps only — every KPI/cost the app computes is time-independent and unchanged.
    A demo/ops convenience so a presenter can freshen the report without a full reseed."""
    window_minutes = max(1, int(window_minutes))
    if getattr(cosmos, "database", None) is None:
        raise RuntimeError("Cosmos database is not configured")

    now = int(time.time())
    start = now - window_minutes * 60
    n_turns = _restamp_container(
        cosmos.database.get_container_client(OPTIMIZATION_TURNS_CONTAINER), start, now, set_turn_epoch=True)
    try:
        n_debug = _restamp_container(
            cosmos.database.get_container_client(DEBUG_CONTAINER), start, now, set_turn_epoch=False)
    except CosmosHttpResponseError as exc:
        logger.warning("refresh_turn_times: Debug re-stamp skipped: %s", exc)
        n_debug = 0

    logger.info("refresh_turn_times: re-stamped %d OptimizationTurns + %d Debug into the last %d min",
                n_turns, n_debug, window_minutes)
    return {"updated": n_turns + n_debug, "optimization_turns": n_turns, "debug": n_debug,
            "window_minutes": window_minutes, "from": _iso(start), "to": _iso(now)}


# --- Optimization-state reset (clear runtime-accumulated governance + insights) -------
DEFAULT_RESET_TARGETS = ["OptimizationGovernance", "OptimizationInsights"]


def _pk_paths(container) -> list[str]:
    """The container's partition-key field names (e.g. ['tenantId'])."""
    props = container.read()
    pk = props.get("partitionKey", {}) or {}
    return [p.lstrip("/") for p in pk.get("paths", [])]


def _pk_value(doc: dict, paths: list[str]):
    vals = [doc.get(p) for p in paths]
    return vals[0] if len(vals) == 1 else vals


def _clear_container(container, tenant: str | None) -> int:
    paths = _pk_paths(container)
    if tenant:
        query = "SELECT * FROM c WHERE c.tenantId = @t"
        params: Any = [{"name": "@t", "value": tenant}]
    else:
        query, params = "SELECT * FROM c", None
    docs = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
    deleted = 0
    for d in docs:
        container.delete_item(item=d["id"], partition_key=_pk_value(d, paths))
        deleted += 1
    return deleted


def reset_optimization_state(tenant: str | None = None, containers: list[str] | None = None,
                             db: Any = None) -> dict[str, Any]:
    """Clear the runtime-accumulated optimization STATE containers (default:
    ``OptimizationGovernance`` + ``OptimizationInsights``) for a clean demo — removing stale
    approvals and a stale reverse-ETL snapshot so the portal shows a consistent picture again.
    Does NOT touch raw turn telemetry (OptimizationTurns / NodeExecutions / Debug) or any app
    data. Returns a per-container deleted-count summary."""
    if db is None:
        db = getattr(cosmos, "database", None)
    if db is None:
        raise RuntimeError("Cosmos database is not configured")
    targets = containers or DEFAULT_RESET_TARGETS
    cleared: dict[str, Any] = {}
    for name in targets:
        try:
            cleared[name] = _clear_container(db.get_container_client(name), tenant)
        except CosmosHttpResponseError as exc:
            cleared[name] = f"error: {exc}"
    logger.info("reset_optimization_state: cleared %s (tenant=%s)", cleared, tenant)
    return {"tenant": tenant, "cleared": cleared}


# --- Baseline restore + policy-aware synthetic traffic (demo drivers) -----------------
PREMIUM_DEPLOYMENT = "gpt-5.1"
PREMIUM_MODEL = "gpt-5.1-2025-11-13"
POLICIES_CONTAINER = "OptimizationPolicies"
MODEL_SELECTION_SCENARIO = "model-selection"

# Capability-tiered mix — kept in sync with analytics/scripts/traffic_simulator.py.
_COMPLEXITY_PROFILES = [
    {"tier": "trivial", "weight": 0.10, "deployment": "gpt-5-nano", "model": "gpt-5-nano-2025-08-07",
     "in": (2800, 3600), "out": (20, 55), "handoffs": 0, "agent": "supervisor"},
    {"tier": "routine", "weight": 0.55, "deployment": "gpt-5-mini", "model": "gpt-5-mini-2025-08-07",
     "in": (6000, 16000), "out": (200, 450), "handoffs": 1, "agent": "find_places"},
    {"tier": "complex", "weight": 0.35, "deployment": "gpt-5.1", "model": "gpt-5.1-2025-11-13",
     "in": (28000, 33000), "out": (1400, 1900), "handoffs": 2, "agent": "itinerary_generator"},
]


def _upsert_with_backoff(container, doc: dict) -> None:
    for attempt in range(8):
        try:
            container.upsert_item(doc)
            return
        except CosmosHttpResponseError as exc:
            if getattr(exc, "status_code", None) == 429 and attempt < 7:
                time.sleep(min(0.1 * (2 ** attempt), 2.0))
                continue
            raise


def _pick_profile() -> dict:
    r = random.random()
    cum = 0.0
    for p in _COMPLEXITY_PROFILES:
        cum += p["weight"]
        if r <= cum:
            return p
    return _COMPLEXITY_PROFILES[-1]


def _model_selection_active(db) -> bool:
    """True iff the model-selection policy is active AND enabled (baseline otherwise)."""
    try:
        pol = db.get_container_client(POLICIES_CONTAINER)
        doc = pol.read_item(item=MODEL_SELECTION_SCENARIO, partition_key=MODEL_SELECTION_SCENARIO)
    except Exception:  # noqa: BLE001  (404 == no policy yet -> baseline)
        return False
    return doc.get("status") == "active" and bool((doc.get("params") or {}).get("enabled", False))


def _bag_set(bag: list, key: str, value: Any, ts: str) -> None:
    for it in bag:
        if it.get("key") == key:
            it["value"] = value
            return
    bag.append({"key": key, "value": value, "timeStamp": ts})


def restore_baseline_turns(tenant: str | None = None, db: Any = None) -> dict[str, Any]:
    """Normalize captured turns back to the single-premium 'before-optimization' baseline —
    set every OptimizationTurns + Debug turn to gpt-5.1 / complexity_tier=default — WITHOUT
    touching tokens, agent_path or the funnel signal. Only non-baseline turns are rewritten,
    so 'apply model-selection -> tier' reads as a clean before/after."""
    if db is None:
        db = getattr(cosmos, "database", None)
    if db is None:
        raise RuntimeError("Cosmos database is not configured")
    now_iso = _iso(int(time.time()))

    ot = db.get_container_client(OPTIMIZATION_TURNS_CONTAINER)
    q = "SELECT * FROM c WHERE c.model_deployment != @m OR c.complexity_tier != 'default'"
    params: Any = [{"name": "@m", "value": PREMIUM_DEPLOYMENT}]
    if tenant:
        q += " AND c.tenantId = @t"
        params.append({"name": "@t", "value": tenant})
    ot_docs = list(ot.query_items(query=q, parameters=params, enable_cross_partition_query=True))
    for d in ot_docs:
        d["complexity_tier"] = "default"
        d["model_deployment"] = PREMIUM_DEPLOYMENT
        d["model_name"] = PREMIUM_MODEL
        _upsert_with_backoff(ot, d)

    dbg = db.get_container_client(DEBUG_CONTAINER)
    dq = "SELECT * FROM c"
    dparams = None
    if tenant:
        dq += " WHERE c.tenantId = @t"
        dparams = [{"name": "@t", "value": tenant}]
    n_debug = 0
    for d in list(dbg.query_items(query=dq, parameters=dparams, enable_cross_partition_query=True)):
        bag = d.get("propertyBag")
        if not isinstance(bag, list):
            continue
        cur = {i.get("key"): i.get("value") for i in bag}
        dep = str(cur.get("model_deployment") or cur.get("model_name") or "")
        tier = cur.get("complexity_tier") or cur.get("model_tier") or "default"
        if dep.startswith(PREMIUM_DEPLOYMENT) and tier == "default":
            continue  # already baseline
        _bag_set(bag, "model_deployment", PREMIUM_DEPLOYMENT, now_iso)
        _bag_set(bag, "model_name", PREMIUM_MODEL, now_iso)
        _bag_set(bag, "complexity_tier", "default", now_iso)
        _bag_set(bag, "model_tier", "default", now_iso)
        _upsert_with_backoff(dbg, d)
        n_debug += 1

    logger.info("restore_baseline_turns: normalized %d OptimizationTurns + %d Debug", len(ot_docs), n_debug)
    return {"optimization_turns": len(ot_docs), "debug": n_debug}


def generate_traffic(tenant: str = "analytics", count: int = 150, minutes: int = 5,
                     db: Any = None) -> dict[str, Any]:
    """Write a burst of ``count`` synthetic turns spread over the last ``minutes``, policy-aware:
    baseline single premium model until the model-selection policy is applied, capability-tiered
    once active. Dual-writes Debug + OptimizationTurns so every live view (model donut, KPI tiles,
    turns-by-minute) reflects it. The in-process equivalent of traffic_simulator.py --mode direct."""
    if db is None:
        db = getattr(cosmos, "database", None)
    if db is None:
        raise RuntimeError("Cosmos database is not configured")
    count = max(1, min(int(count), 2000))
    minutes = max(1, int(minutes))
    applied = _model_selection_active(db)
    ot = db.get_container_client(OPTIMIZATION_TURNS_CONTAINER)
    dbg = db.get_container_client(DEBUG_CONTAINER)
    now = int(time.time())
    start = now - minutes * 60
    by_model: dict[str, int] = {}
    lock = __import__("threading").Lock()

    def _one(_i: int) -> None:
        p = _pick_profile()
        e = random.randint(start, now)
        ts = _iso(e)
        it = random.randint(*p["in"])
        otok = random.randint(*p["out"])
        cached = int(it * random.uniform(0.6, 0.9))
        if applied:
            tier, dep, model, handoffs = p["tier"], p["deployment"], p["model"], p["handoffs"]
        else:
            tier, dep, model, handoffs = "default", PREMIUM_DEPLOYMENT, PREMIUM_MODEL, p["handoffs"]
        with lock:
            by_model[dep] = by_model.get(dep, 0) + 1
        uid = f"sim_{tenant}"
        sid = f"sim-{uuid.uuid4()}"
        agent = p["agent"]
        turn = {
            "id": f"sim-{uuid.uuid4()}", "type": "optimization_turn",
            "tenantId": tenant, "userId": uid, "sessionId": sid,
            "complexity_tier": tier, "model_deployment": dep, "model_name": model,
            "input_tokens": it, "output_tokens": otok, "total_tokens": it + otok,
            "cached_tokens": cached, "handoff_count": handoffs,
            "agent_path": agent, "timeStamp": ts, "turn_epoch": e,
        }
        did = f"sim-debug-{uuid.uuid4()}"
        bag = [
            {"key": "agent_selected", "value": agent, "timeStamp": ts},
            {"key": "model_deployment", "value": dep, "timeStamp": ts},
            {"key": "model_name", "value": model, "timeStamp": ts},
            {"key": "complexity_tier", "value": tier, "timeStamp": ts},
            {"key": "input_tokens", "value": it, "timeStamp": ts},
            {"key": "output_tokens", "value": otok, "timeStamp": ts},
            {"key": "total_tokens", "value": it + otok, "timeStamp": ts},
            {"key": "cached_tokens", "value": cached, "timeStamp": ts},
            {"key": "handoff_count", "value": handoffs, "timeStamp": ts},
            {"key": "agent_path", "value": agent, "timeStamp": ts},
            {"key": "tool_calls", "value": "[]", "timeStamp": ts},
        ]
        debug = {
            "id": did, "debugLogId": did, "messageId": f"{did}::msg", "type": "debug_log",
            "sessionId": sid, "tenantId": tenant, "userId": uid,
            "timeStamp": ts, "propertyBag": bag,
        }
        _upsert_with_backoff(ot, turn)
        _upsert_with_backoff(dbg, debug)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_one, range(count)))

    mode = "tiered" if applied else "baseline"
    logger.info("generate_traffic: wrote %d %s turns for %s", count, mode, tenant)
    return {"tenant": tenant, "generated": count, "mode": mode, "by_model": by_model, "minutes": minutes}

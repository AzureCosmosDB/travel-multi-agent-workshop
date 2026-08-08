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
from typing import Any

from azure.cosmos.exceptions import CosmosHttpResponseError

from src.app.services import azure_cosmos_db as cosmos

logger = logging.getLogger(__name__)

OPTIMIZATION_TURNS_CONTAINER = "OptimizationTurns"


def _iso(epoch: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def refresh_turn_times(window_minutes: int = 120) -> dict[str, Any]:
    """Spread every OptimizationTurns doc's timestamp uniformly across the last
    ``window_minutes`` (ending now). Returns a summary dict."""
    window_minutes = max(1, int(window_minutes))
    if getattr(cosmos, "database", None) is None:
        raise RuntimeError("Cosmos database is not configured")
    container = cosmos.database.get_container_client(OPTIMIZATION_TURNS_CONTAINER)

    now = int(time.time())
    start = now - window_minutes * 60
    docs = list(container.query_items("SELECT * FROM c", enable_cross_partition_query=True))

    def _restamp(doc: dict) -> None:
        e = random.randint(start, now)
        doc["turn_epoch"] = e
        doc["timeStamp"] = _iso(e)
        # Modest concurrency can still outrun the container's provisioned RU/s, so back
        # off and retry on 429 (TooManyRequests) rather than failing the whole refresh.
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

    logger.info("refresh_turn_times: re-stamped %d turns into the last %d min", len(docs), window_minutes)
    return {"updated": len(docs), "window_minutes": window_minutes, "from": _iso(start), "to": _iso(now)}


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

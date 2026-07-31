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
        container.upsert_item(doc)

    if docs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(_restamp, docs))

    logger.info("refresh_turn_times: re-stamped %d turns into the last %d min", len(docs), window_minutes)
    return {"updated": len(docs), "window_minutes": window_minutes, "from": _iso(start), "to": _iso(now)}

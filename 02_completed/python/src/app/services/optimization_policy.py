"""
Optimization policy store (the *apply* substrate for the analytics loop).

This is the write-back target for lower-risk, autonomous optimizations
(SCEN-007 model selection, SCEN-004 memory retention, SCEN-002 retrieval
weighting). A policy is a small, versioned, reversible document the running
app reads at request time. Applying/reverting an optimization is just a status
flip + audit entry here -- never a code edit -- which is what makes these
optimizations safe to automate (maturity Level 4/5).

Design:
- One active policy per ``scenario`` (partition key ``/scenario``, id == scenario).
- ``status``: ``proposed`` -> ``active`` -> ``reverted``. Only ``active`` +
  ``params.enabled`` changes runtime behavior; anything else is a no-op, so the
  default state is always safe.
- Self-provisioning: the container is created on first use so the prototype
  runs without a Bicep redeploy.
- Small in-process cache with a short TTL so the hot request path doesn't hit
  Cosmos on every turn, while apply/revert still take effect within seconds.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from azure.cosmos import PartitionKey, ThroughputProperties

from src.app.services import azure_cosmos_db as cosmos

logger = logging.getLogger(__name__)

CONTAINER_NAME = "OptimizationPolicies"
_CACHE_TTL_SECONDS = 15

_policies_container = None
_cache: dict[str, tuple[float, Optional[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_container():
    """Return the (lazily self-provisioned) OptimizationPolicies container."""
    global _policies_container
    if _policies_container is not None:
        return _policies_container

    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        logger.warning("⚠️ Cosmos database unavailable; optimization policies disabled")
        return None

    try:
        _policies_container = cosmos.database.create_container_if_not_exists(
            id=CONTAINER_NAME,
            partition_key=PartitionKey(path="/scenario"),
            # Autoscale to match the Bicep-provisioned container. Without this,
            # Cosmos defaults a new dedicated container to manual 400 RU/s, which
            # then conflicts with the Bicep autoscale offer ("Updating offer to
            # autoscale throughput is not allowed") if the app self-provisions it
            # before infra deploy.
            offer_throughput=ThroughputProperties(auto_scale_max_throughput=1000),
        )
        logger.info("✅ OptimizationPolicies container ready")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"❌ Could not initialize OptimizationPolicies container: {exc}")
        _policies_container = None
    return _policies_container


def _invalidate(scenario: str) -> None:
    with _cache_lock:
        _cache.pop(scenario, None)


def get_active_policy(scenario: str) -> Optional[dict[str, Any]]:
    """Return the active policy doc for a scenario, or None. Cached (short TTL)."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(scenario)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    container = _get_container()
    policy: Optional[dict[str, Any]] = None
    if container is not None:
        try:
            doc = container.read_item(item=scenario, partition_key=scenario)
            if doc.get("status") == "active":
                policy = doc
        except Exception:  # noqa: BLE001 -- 404 == no policy yet, which is fine
            policy = None

    with _cache_lock:
        _cache[scenario] = (now, policy)
    return policy


def get_policy(scenario: str) -> Optional[dict[str, Any]]:
    """Return the policy doc for a scenario regardless of status (or None)."""
    container = _get_container()
    if container is None:
        return None
    try:
        return container.read_item(item=scenario, partition_key=scenario)
    except Exception:  # noqa: BLE001
        return None


def list_policies() -> list[dict[str, Any]]:
    container = _get_container()
    if container is None:
        return []
    try:
        return list(container.read_all_items())
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error listing optimization policies: {exc}")
        return []


def upsert_policy(doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Create or replace a policy document. ``scenario`` is the id/partition key."""
    container = _get_container()
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
    """Register a policy in the ``proposed`` state (does not affect runtime)."""
    doc = dict(doc)
    doc["status"] = "proposed"
    doc.setdefault("version", 1)
    doc.setdefault("audit", [])
    doc["audit"] = list(doc["audit"]) + [
        {"ts": _now_iso(), "action": "proposed", "by": doc.get("proposed_by", "analytics")}
    ]
    return upsert_policy(doc)


def _transition(scenario: str, status: str, by: str) -> Optional[dict[str, Any]]:
    doc = get_policy(scenario)
    if doc is None:
        return None
    doc["status"] = status
    doc["version"] = int(doc.get("version", 1)) + 1
    doc["audit"] = list(doc.get("audit", [])) + [
        {"ts": _now_iso(), "action": status, "by": by}
    ]
    return upsert_policy(doc)


def apply_policy(scenario: str, by: str = "dashboard") -> Optional[dict[str, Any]]:
    """Activate a scenario's policy (one-click apply). Reversible via revert_policy."""
    return _transition(scenario, "active", by)


def revert_policy(scenario: str, by: str = "dashboard") -> Optional[dict[str, Any]]:
    """Roll a scenario's policy back to inactive (one-click revert)."""
    return _transition(scenario, "reverted", by)


def stage_policy(doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Register a HUMAN-GOVERNED change as ``staged`` (never ``active`` → no runtime
    effect). This is the "apply" for a higher-risk prompt/code change: it records a
    reviewable proposal for a human to merge via PR (maturity L3), not a toggle."""
    doc = dict(doc)
    doc["status"] = "staged"
    doc.setdefault("version", 1)
    doc.setdefault("audit", [])
    doc["audit"] = list(doc["audit"]) + [
        {"ts": _now_iso(), "action": "staged", "by": doc.get("proposed_by", "dashboard")}
    ]
    return upsert_policy(doc)

"""
Configuration store (a single, multi-entity Cosmos container for runtime config).

The ``Configuration`` container is the *runtime* single source of truth for
small configuration values the app, the Fabric reverse-ETL notebook, and the
Power BI report all need to agree on. It holds different entity *types* keyed by
the ``/type`` partition key, e.g.:

    - ``model_pricing``            one flat row per model deployment
                                   ``{type, model, input_price, output_price}``
    - ``model_selection_defaults`` the default tier/classifier policy the
                                   recommendation card proposes

Why a container (not a file / .env): the pricing rows are mirrored into Fabric
so the Power BI report reads the exact same numbers as the app — no CSV, no
duplicated ``.env`` value, no hardcoded DAX ``SWITCH``. The rows are written by
``python/data/seed_configuration.py`` (run by the ``azd`` post-provision hook),
which discovers the models that were actually deployed and upserts one priced
row per model (see ``analytics/docs/model-pricing.md``).

Design (mirrors optimization_policy.py):
    - Flat docs so Cosmos → Fabric mirroring keeps every field as a column.
    - Self-provisioning: created on first use so the prototype runs without a
      Bicep redeploy.
    - Small in-process cache (short TTL) so the hot path doesn't hit Cosmos on
      every turn.
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

CONTAINER_NAME = "Configuration"

TYPE_MODEL_PRICING = "model_pricing"
TYPE_MODEL_SELECTION_DEFAULTS = "model_selection_defaults"
TYPE_MEMORY_CONFIG = "memory_config"

_CACHE_TTL_SECONDS = 60

_container = None
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_cache_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_container():
    """Return the (lazily self-provisioned) Configuration container, or None."""
    global _container
    if _container is not None:
        return _container

    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        logger.warning("⚠️ Cosmos database unavailable; Configuration store disabled")
        return None

    try:
        _container = cosmos.database.create_container_if_not_exists(
            id=CONTAINER_NAME,
            partition_key=PartitionKey(path="/type"),
            # Match the Bicep-provisioned autoscale offer (see optimization_policy).
            offer_throughput=ThroughputProperties(auto_scale_max_throughput=1000),
        )
        logger.info("✅ Configuration container ready")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"❌ Could not initialize Configuration container: {exc}")
        _container = None
    return _container


def invalidate(config_type: Optional[str] = None) -> None:
    with _cache_lock:
        if config_type is None:
            _cache.clear()
        else:
            _cache.pop(config_type, None)


def get_docs(config_type: str) -> list[dict[str, Any]]:
    """All docs of a given ``type`` (partition-scoped query). Cached (short TTL)."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(config_type)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    container = get_container()
    if container is None:
        return []
    try:
        docs = list(
            container.query_items(
                query="SELECT * FROM c WHERE c.type = @t",
                parameters=[{"name": "@t", "value": config_type}],
                partition_key=config_type,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read Configuration type=%s (%s)", config_type, exc)
        return []

    with _cache_lock:
        _cache[config_type] = (now, docs)
    return docs


def get_model_pricing() -> dict[str, dict[str, float]]:
    """Model pricing from the Configuration container as ``{model: {input, output}}``.

    Returns an empty dict if the container has no pricing rows (callers fall back
    to their built-in default so the app never breaks).
    """
    out: dict[str, dict[str, float]] = {}
    for row in get_docs(TYPE_MODEL_PRICING):
        model = row.get("model")
        if not model:
            continue
        try:
            out[model] = {
                "input": float(row["input_price"]),
                "output": float(row["output_price"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out


def get_model_selection_defaults() -> Optional[dict[str, Any]]:
    """The single ``model_selection_defaults`` doc, or None if not seeded."""
    docs = get_docs(TYPE_MODEL_SELECTION_DEFAULTS)
    return docs[0] if docs else None


def get_memory_config() -> dict[str, float]:
    """Memory salience thresholds from the Configuration container, with built-in
    fallback defaults so callers never break if the row isn't seeded."""
    docs = get_docs(TYPE_MEMORY_CONFIG)
    row = docs[0] if docs else {}

    def _f(key: str, default: float) -> float:
        try:
            return float(row.get(key, default))
        except (TypeError, ValueError):
            return default

    return {"salience_high": _f("salience_high", 0.8),
            "salience_medium": _f("salience_medium", 0.5)}


def upsert(doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Upsert a config doc. Requires ``type``; derives ``id`` when absent.

    Upsert (not replace) is deliberate: a model swapped in later gets added while
    older models' rows remain, so before/after analysis works until data ages out.
    """
    container = get_container()
    if container is None:
        return None
    if "type" not in doc:
        raise ValueError("Configuration doc requires a 'type' field")
    doc.setdefault("id", doc["type"])
    doc.setdefault("updated_at", _now_iso())
    doc.setdefault("updated_epoch", int(time.time()))
    saved = container.upsert_item(doc)
    invalidate(doc["type"])
    return saved

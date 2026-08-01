"""
Node-execution telemetry store (ADR-0010 Layer 1, spike/engine B1).

The streaming path already receives a per-node `on_chat_model_end` event; historically
it summed usage into one turn total and discarded per-agent attribution. This store
persists the node grain instead — one document per turn holding the list of agent
executions — so the analysis engine can attribute cost/quality to an individual agent.

Self-provisioning (like optimization_policy) so the prototype runs without a Bicep
redeploy. Hierarchical partition key [tenantId, userId, sessionId], consistent with the
session-scoped containers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from azure.cosmos import PartitionKey

from src.app.services import azure_cosmos_db as cosmos

logger = logging.getLogger(__name__)

CONTAINER_NAME = "NodeExecutions"
_container = None


def _get_container():
    global _container
    if _container is not None:
        return _container
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        logger.warning("⚠️ Cosmos database unavailable; node-execution telemetry disabled")
        return None
    try:
        _container = cosmos.database.create_container_if_not_exists(
            id=CONTAINER_NAME,
            partition_key=PartitionKey(
                path=["/tenantId", "/userId", "/sessionId"], kind="MultiHash"
            ),
        )
        logger.info("✅ NodeExecutions container ready")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"❌ Could not initialize NodeExecutions container: {exc}")
        _container = None
    return _container


def store_node_executions(
    tenant_id: str,
    user_id: str,
    session_id: str,
    turn_id: str,
    debug_log_id: Optional[str],
    records: list[dict[str, Any]],
) -> int:
    """Persist one document per turn holding the node-grain executions. Returns count."""
    if not records:
        return 0
    container = _get_container()
    if container is None:
        return 0
    now = datetime.now(timezone.utc)
    doc = {
        "id": debug_log_id or f"{session_id}:{turn_id}",
        "tenantId": tenant_id,
        "userId": user_id,
        "sessionId": session_id,
        "turnId": turn_id,
        "debugLogId": debug_log_id,
        "nodeExecutions": records,
        "nodeCount": len(records),
        "timeStamp": now.isoformat(),
        "turn_epoch": int(now.timestamp()),
    }
    try:
        container.upsert_item(doc)
        return len(records)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to store node executions: {exc}")
        return 0

"""
Optimization governance store (the human-in-the-loop audit trail).

Backs the agent-centric Console's governed actions (ADR-0010 §7/§8, ledger C1–C5):

  * card approvals / rejections            (C4)
  * deploy attestations + revert confirms  (C1)
  * SLO / confidence / min-effect policy   (C3)
  * learner-declared domain param schemas  (C5)

Every write is an append-only, timestamped, attributed record — so who decided what, and
when, is auditable. Self-provisioning (like optimization_policy) so the prototype runs
without a Bicep redeploy. Partition key ``/tenantId``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from azure.cosmos import PartitionKey, ThroughputProperties

from src.app.services import azure_cosmos_db as cosmos

logger = logging.getLogger(__name__)

CONTAINER_NAME = "OptimizationGovernance"
_container = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_container():
    global _container
    if _container is not None:
        return _container
    if cosmos.database is None:
        cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        logger.warning("⚠️ Cosmos database unavailable; governance store disabled")
        return None
    try:
        _container = cosmos.database.create_container_if_not_exists(
            id=CONTAINER_NAME,
            partition_key=PartitionKey(path="/tenantId"),
            offer_throughput=ThroughputProperties(auto_scale_max_throughput=1000),
        )
        logger.info("✅ OptimizationGovernance container ready")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"❌ Could not initialize OptimizationGovernance container: {exc}")
        _container = None
    return _container


# --- audit records (append-only) --------------------------------------------------

def record_decision(tenant_id: str, kind: str, subject: str, by: str,
                    payload: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Append one audited governance record. `kind` is e.g. approve/reject/attest/confirm-revert."""
    container = _get_container()
    if container is None:
        return None
    doc = {
        "id": f"{kind}:{subject}:{uuid.uuid4().hex[:8]}",
        "tenantId": tenant_id, "type": "decision", "kind": kind, "subject": subject,
        "by": by, "payload": payload or {}, "timeStamp": _now_iso(),
    }
    try:
        return container.upsert_item(doc)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to record governance decision: {exc}")
        return None


def decisions_for(tenant_id: str, subject: Optional[str] = None) -> list[dict[str, Any]]:
    """Audit trail for a tenant (optionally one opportunity/subject), newest first."""
    container = _get_container()
    if container is None:
        return []
    query = "SELECT * FROM c WHERE c.tenantId = @t AND c.type = 'decision'"
    params: list[dict[str, Any]] = [{"name": "@t", "value": tenant_id}]
    if subject:
        query += " AND c.subject = @s"
        params.append({"name": "@s", "value": subject})
    try:
        rows = list(container.query_items(query=query, parameters=params,
                                          enable_cross_partition_query=True))
        return sorted(rows, key=lambda d: d.get("timeStamp", ""), reverse=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read governance decisions: {exc}")
        return []


def latest_state(tenant_id: str, subject: str) -> Optional[dict[str, Any]]:
    """The most recent decision kind for a subject (its current governed state)."""
    rows = decisions_for(tenant_id, subject)
    return rows[0] if rows else None


# --- singleton documents (SLO policy, declared schemas) ---------------------------

def _upsert_singleton(tenant_id: str, doc_id: str, doc: dict[str, Any]) -> Optional[dict[str, Any]]:
    container = _get_container()
    if container is None:
        return None
    body = {"id": doc_id, "tenantId": tenant_id, **doc, "timeStamp": _now_iso()}
    try:
        return container.upsert_item(body)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to upsert governance singleton {doc_id}: {exc}")
        return None


def _read_singleton(tenant_id: str, doc_id: str) -> Optional[dict[str, Any]]:
    container = _get_container()
    if container is None:
        return None
    try:
        return container.read_item(item=doc_id, partition_key=tenant_id)
    except Exception:  # noqa: BLE001
        return None


DEFAULT_SLO = {"slo": 4.0, "min_confidence": 0.7, "min_effect": 0.05}


def set_slo_policy(tenant_id: str, slo: float, min_confidence: float,
                   min_effect: float, by: str) -> Optional[dict[str, Any]]:
    """C3: set the SLO / confidence / min-effect policy the engine consumes."""
    return _upsert_singleton(tenant_id, f"slo:{tenant_id}", {
        "type": "slo_policy", "slo": slo, "min_confidence": min_confidence,
        "min_effect": min_effect, "by": by,
    })


def get_slo_policy(tenant_id: str) -> dict[str, Any]:
    doc = _read_singleton(tenant_id, f"slo:{tenant_id}")
    if not doc:
        return {"tenantId": tenant_id, "type": "slo_policy", **DEFAULT_SLO, "by": "default"}
    return doc


def declare_schema(tenant_id: str, domain: str, manifest: dict[str, Any], by: str) -> Optional[dict[str, Any]]:
    """C5: persist a learner-declared domain params schema (manifest form)."""
    return _upsert_singleton(tenant_id, f"schema:{tenant_id}:{domain}", {
        "type": "declared_schema", "domain": domain, "manifest": manifest, "by": by,
    })


def declared_schemas(tenant_id: str) -> list[dict[str, Any]]:
    container = _get_container()
    if container is None:
        return []
    query = "SELECT * FROM c WHERE c.tenantId = @t AND c.type = 'declared_schema'"
    try:
        return list(container.query_items(query=query,
                    parameters=[{"name": "@t", "value": tenant_id}],
                    enable_cross_partition_query=True))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to read declared schemas: {exc}")
        return []

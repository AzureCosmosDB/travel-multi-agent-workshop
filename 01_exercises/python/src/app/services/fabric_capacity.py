"""Fabric capacity + mirroring control for the Optimization Console.

A Fabric F-capacity bills while it is *Active* whether or not it is doing work, so
the Optimization Console exposes a Pause / Resume control right where attendees view
their optimization results. Attendees resume the capacity to refresh the analytics,
then pause it when they are done to stop the meter — a first-class cost optimization,
demonstrated on the very infrastructure that powers the analytics.

Capacity pause/resume are ARM control-plane operations on ``Microsoft.Fabric/capacities``:

    POST .../suspend?api-version=2023-11-01
    POST .../resume?api-version=2023-11-01

**Mirroring is NOT auto-managed by capacity pause/resume.** When the capacity is
suspended, Cosmos mirroring stops replicating; resuming the capacity does *not*
restart it. So this module stops mirroring when pausing and restarts it (once the
capacity is Active again) when resuming, via the Fabric REST API:

    POST /v1/workspaces/{ws}/mirroredDatabases/{id}/stopMirroring
    POST /v1/workspaces/{ws}/mirroredDatabases/{id}/startMirroring
    GET  /v1/workspaces/{ws}/mirroredDatabases/{id}/getMirroringStatus
    POST /v1/workspaces/{ws}/mirroredDatabases/{id}/getTablesMirroringStatus

After a resume the mirror re-snapshots and then replicates, so there is a lag before
the analytics are current again. ``get_status`` therefore also reports whether the
mirror is **caught up** (database Running and every table past the initial snapshot,
i.e. ``Replicating``) plus the latest per-table sync time, so the console can tell the
user when it is safe to trust — and then pause — the analytics.

Auth uses :class:`DefaultAzureCredential`. In the local workshop flow the API runs as
the developer's ``az login`` identity (the capacity admin), so no extra RBAC is needed.
In a hosted deployment the API's managed identity needs a role granting
``Microsoft.Fabric/capacities/suspend/action`` + ``/resume/action`` on the capacity,
plus Fabric workspace access for the mirroring calls.

Env vars:
  FABRIC_CAPACITY_NAME, AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP (or RG_NAME)
    -> capacity pause/resume. If unset, every function returns {"configured": False}.
  FABRIC_WORKSPACE_ID, FABRIC_MIRROR_ID (written by provision_fabric.py)
    -> mirroring restart + caught-up reporting. If unset, mirroring is left untouched.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ARM = "https://management.azure.com"
_ARM_SCOPE = "https://management.azure.com/.default"
_API_VERSION = "2023-11-01"

_FABRIC_API = "https://api.fabric.microsoft.com/v1"
_FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

# Table mirroring states that mean the initial snapshot is done and the table is live.
_CAUGHT_UP_STATES = {"Replicating"}

# Seconds to wait for the capacity to become Active before restarting mirroring on resume.
_RESUME_WAIT_SECONDS = 90

_credential = None


def _cred():
    global _credential
    if _credential is None:
        from azure.identity import DefaultAzureCredential

        _credential = DefaultAzureCredential()
    return _credential


def _token(scope: str) -> str:
    return _cred().get_token(scope).token


# --------------------------------------------------------------------------- config
def _config() -> dict[str, str] | None:
    name = os.getenv("FABRIC_CAPACITY_NAME", "").strip()
    sub = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    rg = (os.getenv("AZURE_RESOURCE_GROUP") or os.getenv("RG_NAME") or "").strip()
    if not (name and sub and rg):
        return None
    return {"name": name, "sub": sub, "rg": rg}


def _mirror_config() -> dict[str, str] | None:
    ws = os.getenv("FABRIC_WORKSPACE_ID", "").strip()
    mirror = os.getenv("FABRIC_MIRROR_ID", "").strip()
    if not (ws and mirror):
        return None
    return {"workspace": ws, "mirror": mirror}


def _resource_url(cfg: dict[str, str]) -> str:
    return (
        f"{_ARM}/subscriptions/{cfg['sub']}/resourceGroups/{cfg['rg']}"
        f"/providers/Microsoft.Fabric/capacities/{cfg['name']}"
    )


def _mirror_url(mc: dict[str, str], action: str) -> str:
    return f"{_FABRIC_API}/workspaces/{mc['workspace']}/mirroredDatabases/{mc['mirror']}/{action}"


# --------------------------------------------------------------------------- mirroring
def get_mirroring_status() -> str | None:
    """Return the mirror's database-level status ('Running'/'Stopped'/...), or None."""
    mc = _mirror_config()
    if mc is None:
        return None
    headers = {"Authorization": f"Bearer {_token(_FABRIC_SCOPE)}", "Content-Type": "application/json"}
    r = requests.post(_mirror_url(mc, "getMirroringStatus"), headers=headers, json={}, timeout=30)
    if r.status_code == 404:
        return "NotFound"
    r.raise_for_status()
    return (r.json() or {}).get("status")


def get_tables_mirroring_status() -> list[dict[str, Any]]:
    """Per-table replication status + metrics (rows, last sync time)."""
    mc = _mirror_config()
    if mc is None:
        return []
    headers = {"Authorization": f"Bearer {_token(_FABRIC_SCOPE)}", "Content-Type": "application/json"}
    tables: list[dict[str, Any]] = []
    url = _mirror_url(mc, "getTablesMirroringStatus")
    body: dict[str, Any] = {}
    for _ in range(20):  # follow continuation tokens defensively
        r = requests.post(url, headers=headers, json=body, timeout=30)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        payload = r.json() or {}
        for t in payload.get("data", payload.get("value", [])):
            metrics = t.get("metrics") or {}
            tables.append(
                {
                    "table": t.get("sourceTableName") or t.get("tableName"),
                    "schema": t.get("sourceSchemaName"),
                    "status": t.get("status"),
                    "processedRows": metrics.get("processedRows"),
                    "lastSync": metrics.get("lastSyncDateTime"),
                }
            )
        token = payload.get("continuationToken")
        if not token:
            break
        body = {"continuationToken": token}
    return tables


def mirroring_summary() -> dict[str, Any] | None:
    """Roll up database + table status into a 'caught up' verdict for the UI."""
    if _mirror_config() is None:
        return None
    db_status = get_mirroring_status()
    tables = get_tables_mirroring_status()
    running = db_status == "Running"
    have_tables = len(tables) > 0
    all_replicating = have_tables and all(
        (t.get("status") in _CAUGHT_UP_STATES) for t in tables
    )
    last_syncs = [t.get("lastSync") for t in tables if t.get("lastSync")]
    return {
        "status": db_status,
        "caughtUp": bool(running and all_replicating),
        "tableCount": len(tables),
        "lastSync": max(last_syncs) if last_syncs else None,
        "tables": tables,
    }


def start_mirroring() -> dict[str, Any]:
    mc = _mirror_config()
    if mc is None:
        return {"mirroring": "not_configured"}
    headers = {"Authorization": f"Bearer {_token(_FABRIC_SCOPE)}", "Content-Type": "application/json"}
    r = requests.post(_mirror_url(mc, "startMirroring"), headers=headers, timeout=60)
    if r.status_code not in (200, 202, 204):
        logger.warning("startMirroring returned %s: %s", r.status_code, r.text[:300])
        return {"mirroring": "start_failed", "status_code": r.status_code}
    logger.info("mirroring start requested (%s)", r.status_code)
    return {"mirroring": "started"}


def stop_mirroring() -> dict[str, Any]:
    mc = _mirror_config()
    if mc is None:
        return {"mirroring": "not_configured"}
    headers = {"Authorization": f"Bearer {_token(_FABRIC_SCOPE)}", "Content-Type": "application/json"}
    r = requests.post(_mirror_url(mc, "stopMirroring"), headers=headers, timeout=60)
    if r.status_code not in (200, 202, 204):
        logger.warning("stopMirroring returned %s: %s", r.status_code, r.text[:300])
        return {"mirroring": "stop_failed", "status_code": r.status_code}
    logger.info("mirroring stop requested (%s)", r.status_code)
    return {"mirroring": "stopped"}


# --------------------------------------------------------------------------- capacity
def _capacity_state(cfg: dict[str, str]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {_token(_ARM_SCOPE)}"}
    r = requests.get(f"{_resource_url(cfg)}?api-version={_API_VERSION}", headers=headers, timeout=30)
    if r.status_code == 404:
        return {"found": False}
    r.raise_for_status()
    body = r.json()
    props = body.get("properties", {})
    return {
        "found": True,
        "state": props.get("state"),
        "provisioningState": props.get("provisioningState"),
        "sku": (body.get("sku") or {}).get("name"),
        "location": body.get("location"),
    }


def get_status() -> dict[str, Any]:
    """Return the capacity's current state + mirroring/caught-up summary."""
    cfg = _config()
    if cfg is None:
        return {"configured": False}
    result: dict[str, Any] = {"configured": True, "name": cfg["name"], **_capacity_state(cfg)}
    if result.get("found") and result.get("state") == "Active" and _mirror_config() is not None:
        try:
            result["mirroring"] = mirroring_summary()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mirroring summary failed: %s", exc)
            result["mirroring"] = {"status": "Unknown", "caughtUp": False}
    return result


def _capacity_action(cfg: dict[str, str], action: str) -> int:
    headers = {"Authorization": f"Bearer {_token(_ARM_SCOPE)}", "Content-Type": "application/json"}
    r = requests.post(
        f"{_resource_url(cfg)}/{action}?api-version={_API_VERSION}", headers=headers, timeout=60
    )
    if r.status_code not in (200, 202):
        r.raise_for_status()
    logger.info("Fabric capacity %s '%s' requested (%s)", action, cfg["name"], r.status_code)
    return r.status_code


def suspend() -> dict[str, Any]:
    """Stop mirroring (if any) then pause the capacity to stop the meter."""
    cfg = _config()
    if cfg is None:
        return {"configured": False}
    result: dict[str, Any] = {"configured": True, "name": cfg["name"], "action": "suspend"}
    if _mirror_config() is not None:
        result.update(stop_mirroring())
    _capacity_action(cfg, "suspend")
    result["accepted"] = True
    return result


def resume() -> dict[str, Any]:
    """Resume the capacity, wait for it to become Active, then restart mirroring."""
    cfg = _config()
    if cfg is None:
        return {"configured": False}
    result: dict[str, Any] = {"configured": True, "name": cfg["name"], "action": "resume"}
    _capacity_action(cfg, "resume")
    result["accepted"] = True
    if _mirror_config() is None:
        return result
    # Mirroring can only be (re)started once the capacity is Active again.
    deadline = time.time() + _RESUME_WAIT_SECONDS
    while time.time() < deadline:
        if _capacity_state(cfg).get("state") == "Active":
            result.update(start_mirroring())
            return result
        time.sleep(10)
    result["mirroring"] = "capacity_not_active_yet"
    return result

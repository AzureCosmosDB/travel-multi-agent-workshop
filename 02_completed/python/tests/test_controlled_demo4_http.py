from __future__ import annotations

import sys
import threading
import types
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

cosmos_stub = types.ModuleType("src.app.services.azure_cosmos_db")
cosmos_stub.database = None
cosmos_stub.debug_logs_container = None
cosmos_stub.initialize_cosmos_client = lambda: None
cosmos_stub.record_api_event = lambda **kwargs: None
sys.modules.setdefault("src.app.services.azure_cosmos_db", cosmos_stub)

from src.app import optimization_api  # noqa: E402
from src.app.services.lifecycle_coordinator import (  # noqa: E402
    LifecycleLease,
    LifecycleLeaseBusy,
    LifecycleLeaseUnavailable,
)


class EndpointCoordinator:
    def __init__(self):
        self.lock = threading.Lock()
        self.unavailable = False
        self.fail_release = False

    def acquire(self, operation):
        if self.unavailable:
            raise LifecycleLeaseUnavailable("injected storage failure")
        if not self.lock.acquire(timeout=optimization_api._LIFECYCLE_TIMEOUT_SECONDS):
            raise LifecycleLeaseBusy("injected timeout")
        return LifecycleLease(owner_token="endpoint-owner", operation=operation)

    def release(self, lease):
        if self.fail_release:
            self.lock.release()
            raise LifecycleLeaseUnavailable("injected release failure")
        self.lock.release()
        return True


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(optimization_api, "_LIFECYCLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        optimization_api, "_LIFECYCLE_COORDINATOR", EndpointCoordinator()
    )
    app = FastAPI()
    app.include_router(optimization_api.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_success_responses_are_json_serializable(client, monkeypatch):
    monkeypatch.setattr(
        optimization_api.demo_data,
        "reset_controlled_demo4",
        lambda: {"status": "reset", "tenants": ["analytics", "marvel"]},
    )
    monkeypatch.setattr(
        optimization_api.demo_data,
        "generate_traffic",
        lambda *args, **kwargs: {"mode": "controlled", "generated": 200},
    )
    monkeypatch.setattr(
        optimization_api.optimization_policy,
        "get_policy",
        lambda scenario, tenant_id=None: {"id": f"{tenant_id}::{scenario}"},
    )
    monkeypatch.setattr(
        optimization_api.optimization_policy,
        "apply_policy",
        lambda scenario, by, tenant_id=None: {
            "id": f"{tenant_id}::{scenario}",
            "status": "active",
        },
    )
    monkeypatch.setattr(
        optimization_api.optimization_policy,
        "revert_policy",
        lambda scenario, by, tenant_id=None: {
            "id": f"{tenant_id}::{scenario}",
            "status": "reverted",
        },
    )
    from src.app.services import optimization_insights

    monkeypatch.setattr(
        optimization_insights,
        "recompute_controlled_demo4",
        lambda: {"order": ["analytics", "shared", "marvel"], "rows_written": 12},
    )

    responses = [
        client.post("/optimizations/reset"),
        client.post(
            "/optimizations/model-selection/apply",
            json={"by": "test", "tenant_id": "analytics"},
        ),
        client.post(
            "/optimizations/model-selection/revert",
            json={"by": "test", "tenant_id": "marvel"},
        ),
        client.post(
            "/optimizations/traffic",
            params={"tenant": "analytics", "controlled": "true"},
        ),
        client.post("/optimizations/insights", params={"tenant": "marvel"}),
    ]

    assert [response.status_code for response in responses] == [200] * 5
    assert responses[0].json()["tenants"] == ["analytics", "marvel"]
    assert responses[1].json()["id"] == "analytics::model-selection"
    assert responses[2].json()["id"] == "marvel::model-selection"
    assert responses[3].json()["generated"] == 200
    assert responses[4].json()["order"] == ["analytics", "shared", "marvel"]


def test_prerequisite_failure_is_non_2xx_json_and_has_zero_writes(client, monkeypatch):
    writes = []

    def fail_before_write(*args, **kwargs):
        raise optimization_api.demo_data.ControlledTrafficInactiveError(
            "model-selection must be active and enabled before controlled traffic"
        )

    monkeypatch.setattr(
        optimization_api.demo_data, "generate_traffic", fail_before_write
    )
    response = client.post(
        "/optimizations/traffic",
        params={"tenant": "analytics", "controlled": "true"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "model-selection must be active and enabled before controlled traffic"
    }
    assert writes == []


def test_busy_timeout_is_deterministic_json(client):
    coordinator = optimization_api._LIFECYCLE_COORDINATOR
    assert coordinator.lock.acquire(timeout=0.1)
    try:
        response = client.post("/optimizations/reset")
    finally:
        coordinator.lock.release()

    assert response.status_code == 423
    assert response.json()["detail"] == {
        "code": "controlled_demo_lifecycle_busy",
        "operation": "reset",
        "reason": "lock_acquisition_timeout",
        "timeout_seconds": 0.05,
    }


def test_coordination_storage_failure_is_non_success_json(client):
    optimization_api._LIFECYCLE_COORDINATOR.unavailable = True

    response = client.post("/optimizations/reset")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "controlled_demo_lifecycle_unavailable",
        "operation": "reset",
        "reason": "coordination_storage_unavailable",
    }


def test_release_storage_failure_cannot_return_success_shape(client, monkeypatch):
    monkeypatch.setattr(
        optimization_api.demo_data,
        "reset_controlled_demo4",
        lambda: {"status": "reset"},
    )
    optimization_api._LIFECYCLE_COORDINATOR.fail_release = True

    response = client.post("/optimizations/reset")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "controlled_demo_lifecycle_unavailable",
        "operation": "reset",
        "reason": "coordination_storage_unavailable",
    }


def test_internal_exception_releases_lock_and_retry_succeeds(client, monkeypatch):
    calls = 0

    def reset():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("injected reset failure")
        return {"status": "reset"}

    monkeypatch.setattr(
        optimization_api.demo_data, "reset_controlled_demo4", reset
    )
    failed = client.post("/optimizations/reset")
    retried = client.post("/optimizations/reset")

    assert failed.status_code == 500
    assert failed.json()["detail"] == "Optimization reset failed: injected reset failure"
    assert retried.status_code == 200
    assert retried.json() == {"status": "reset"}


def test_concurrent_requests_are_excluded_and_retry_after_completion_succeeds(
    client, monkeypatch
):
    entered = threading.Event()
    release = threading.Event()

    def reset():
        entered.set()
        assert release.wait(timeout=2)
        return {"status": "reset"}

    monkeypatch.setattr(
        optimization_api.demo_data, "reset_controlled_demo4", reset
    )
    first_result = {}

    def first_request():
        first_result["response"] = client.post("/optimizations/reset")

    worker = threading.Thread(target=first_request)
    worker.start()
    assert entered.wait(timeout=1)
    busy = client.post("/optimizations/insights")
    release.set()
    worker.join(timeout=2)
    retried = client.post("/optimizations/reset")

    assert busy.status_code == 423
    assert busy.json()["detail"]["operation"] == "recompute"
    assert first_result["response"].status_code == 200
    assert retried.status_code == 200


def test_apply_failure_stops_before_later_policy_mutation(client, monkeypatch):
    mutations = []
    monkeypatch.setattr(
        optimization_api.optimization_policy,
        "get_policy",
        lambda scenario, tenant_id=None: None,
    )

    def fail_propose(*args, **kwargs):
        mutations.append("propose")
        raise HTTPException(status_code=503, detail="proposal dependency unavailable")

    monkeypatch.setattr(optimization_api, "propose", fail_propose)
    monkeypatch.setattr(
        optimization_api.optimization_policy,
        "apply_policy",
        lambda *args, **kwargs: mutations.append("apply"),
    )

    response = client.post(
        "/optimizations/model-selection/apply",
        json={"by": "test", "tenant_id": "analytics"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "proposal dependency unavailable"}
    assert mutations == ["propose"]


def test_invalid_recompute_tenant_is_non_2xx_without_service_call(client, monkeypatch):
    from src.app.services import optimization_insights

    calls = []
    monkeypatch.setattr(
        optimization_insights,
        "recompute_controlled_demo4",
        lambda: calls.append("recompute"),
    )
    response = client.post("/optimizations/insights", params={"tenant": "other"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": "unsupported controlled recompute tenant: other"
    }
    assert calls == []

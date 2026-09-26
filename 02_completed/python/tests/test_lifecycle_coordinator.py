from __future__ import annotations

import copy
import sys
import threading
import types

import pytest

cosmos_stub = types.ModuleType("src.app.services.azure_cosmos_db")
cosmos_stub.database = None
cosmos_stub.initialize_cosmos_client = lambda: None
sys.modules.setdefault("src.app.services.azure_cosmos_db", cosmos_stub)

from src.app.services.lifecycle_coordinator import (
    CosmosLifecycleCoordinator,
    LifecycleLeaseBusy,
    LifecycleLeaseUnavailable,
)


class CosmosError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"Cosmos status {status_code}")
        self.status_code = status_code


class SharedLeaseContainer:
    def __init__(self):
        self.document = None
        self.version = 0
        self.fail = False
        self._lock = threading.Lock()

    def _check(self):
        if self.fail:
            raise RuntimeError("injected storage failure")

    def create_item(self, document):
        with self._lock:
            self._check()
            if self.document is not None:
                raise CosmosError(409)
            self.version += 1
            self.document = copy.deepcopy(document)
            self.document["_etag"] = str(self.version)
            return copy.deepcopy(self.document)

    def read_item(self, item, partition_key):
        with self._lock:
            self._check()
            if self.document is None:
                raise CosmosError(404)
            return copy.deepcopy(self.document)

    def replace_item(self, item, body, etag, match_condition):
        with self._lock:
            self._check()
            if self.document is None:
                raise CosmosError(404)
            if self.document["_etag"] != etag:
                raise CosmosError(412)
            self.version += 1
            self.document = copy.deepcopy(body)
            self.document["_etag"] = str(self.version)
            return copy.deepcopy(self.document)

    def delete_item(self, item, partition_key, etag, match_condition):
        with self._lock:
            self._check()
            if self.document is None:
                raise CosmosError(404)
            if self.document["_etag"] != etag:
                raise CosmosError(412)
            self.document = None


def coordinator(container, token, *, wall_clock=lambda: 100.0):
    return CosmosLifecycleCoordinator(
        container_provider=lambda: container,
        acquisition_timeout_seconds=0.01,
        lease_ttl_seconds=10,
        retry_interval_seconds=0.001,
        wall_clock=wall_clock,
        token_factory=lambda: token,
    )


def test_two_independent_coordinators_compete_and_retry_after_release():
    container = SharedLeaseContainer()
    first = coordinator(container, "owner-a")
    second = coordinator(container, "owner-b")

    lease_a = first.acquire("reset")
    with pytest.raises(LifecycleLeaseBusy):
        second.acquire("traffic")

    assert first.release(lease_a) is True
    lease_b = second.acquire("traffic")
    assert lease_b.owner_token == "owner-b"
    assert second.release(lease_b) is True


def test_expired_lease_is_recovered_with_conditional_replace():
    now = [100.0]
    container = SharedLeaseContainer()
    first = coordinator(container, "owner-a", wall_clock=lambda: now[0])
    second = coordinator(container, "owner-b", wall_clock=lambda: now[0])

    first.acquire("reset")
    now[0] = 111.0
    recovered = second.acquire("recompute")

    assert recovered.owner_token == "owner-b"
    assert container.document["operation"] == "recompute"
    assert second.release(recovered) is True


def test_release_is_owner_only():
    container = SharedLeaseContainer()
    first = coordinator(container, "owner-a")
    second = coordinator(container, "owner-b")

    lease = first.acquire("apply")
    impostor = type(lease)(owner_token="owner-b", operation="apply")

    assert second.release(impostor) is False
    assert container.document["owner_token"] == "owner-a"
    assert first.release(lease) is True


def test_storage_failure_fails_closed():
    container = SharedLeaseContainer()
    container.fail = True

    with pytest.raises(LifecycleLeaseUnavailable):
        coordinator(container, "owner-a").acquire("reset")

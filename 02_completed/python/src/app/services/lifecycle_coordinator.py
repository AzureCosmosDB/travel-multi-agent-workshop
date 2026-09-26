"""Distributed lease for controlled Demo 4 lifecycle mutations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from azure.core import MatchConditions

from src.app.services import configuration_store


LEASE_ID = "__coordination__:controlled-demo4-lifecycle"
LEASE_TYPE = "__coordination__:controlled-demo4-lifecycle"


class LifecycleLeaseBusy(RuntimeError):
    """The shared lifecycle lease could not be acquired before the deadline."""


class LifecycleLeaseUnavailable(RuntimeError):
    """The shared coordination store could not be used safely."""


@dataclass(frozen=True)
class LifecycleLease:
    owner_token: str
    operation: str


def _status_code(exc: BaseException) -> int | None:
    return getattr(exc, "status_code", None)


class CosmosLifecycleCoordinator:
    """Serialize lifecycle work across processes with a conditional Cosmos lease."""

    def __init__(
        self,
        *,
        container_provider: Callable[[], Any] = configuration_store.get_container,
        acquisition_timeout_seconds: float = 2.0,
        lease_ttl_seconds: float = 900.0,
        retry_interval_seconds: float = 0.05,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        token_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._container_provider = container_provider
        self.acquisition_timeout_seconds = max(0.01, acquisition_timeout_seconds)
        self.lease_ttl_seconds = min(max(1.0, lease_ttl_seconds), 3600.0)
        self.retry_interval_seconds = max(0.001, retry_interval_seconds)
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._sleeper = sleeper
        self._token_factory = token_factory

    def _container(self) -> Any:
        try:
            container = self._container_provider()
        except Exception as exc:  # noqa: BLE001
            raise LifecycleLeaseUnavailable(
                "coordination storage initialization failed"
            ) from exc
        if container is None:
            raise LifecycleLeaseUnavailable("coordination storage is unavailable")
        return container

    def _document(self, owner_token: str, operation: str) -> dict[str, Any]:
        now = self._wall_clock()
        return {
            "id": LEASE_ID,
            "type": LEASE_TYPE,
            "owner_token": owner_token,
            "operation": operation,
            "acquired_at_epoch": now,
            "lease_expires_at_epoch": now + self.lease_ttl_seconds,
        }

    def acquire(self, operation: str) -> LifecycleLease:
        container = self._container()
        owner_token = self._token_factory()
        deadline = self._monotonic_clock() + self.acquisition_timeout_seconds

        while True:
            candidate = self._document(owner_token, operation)
            try:
                container.create_item(candidate)
                return LifecycleLease(owner_token=owner_token, operation=operation)
            except Exception as exc:  # noqa: BLE001
                if _status_code(exc) != 409:
                    raise LifecycleLeaseUnavailable(
                        "coordination lease create failed"
                    ) from exc

            try:
                current = container.read_item(item=LEASE_ID, partition_key=LEASE_TYPE)
            except Exception as exc:  # noqa: BLE001
                if _status_code(exc) == 404:
                    continue
                raise LifecycleLeaseUnavailable(
                    "coordination lease read failed"
                ) from exc

            if float(current.get("lease_expires_at_epoch", 0)) <= self._wall_clock():
                try:
                    container.replace_item(
                        item=LEASE_ID,
                        body=candidate,
                        etag=current.get("_etag"),
                        match_condition=MatchConditions.IfNotModified,
                    )
                    return LifecycleLease(owner_token=owner_token, operation=operation)
                except Exception as exc:  # noqa: BLE001
                    if _status_code(exc) not in {404, 409, 412}:
                        raise LifecycleLeaseUnavailable(
                            "stale coordination lease recovery failed"
                        ) from exc

            remaining = deadline - self._monotonic_clock()
            if remaining <= 0:
                raise LifecycleLeaseBusy(
                    f"lifecycle lease acquisition timed out for {operation}"
                )
            self._sleeper(min(self.retry_interval_seconds, remaining))

    def release(self, lease: LifecycleLease) -> bool:
        container = self._container()
        try:
            current = container.read_item(item=LEASE_ID, partition_key=LEASE_TYPE)
        except Exception as exc:  # noqa: BLE001
            if _status_code(exc) == 404:
                return False
            raise LifecycleLeaseUnavailable("coordination lease read failed") from exc

        if current.get("owner_token") != lease.owner_token:
            return False
        try:
            container.delete_item(
                item=LEASE_ID,
                partition_key=LEASE_TYPE,
                etag=current.get("_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            if _status_code(exc) in {404, 412}:
                return False
            raise LifecycleLeaseUnavailable("coordination lease release failed") from exc

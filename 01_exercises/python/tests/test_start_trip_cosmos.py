from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))


def _identity_decorator(function=None, *args, **kwargs):
    if callable(function):
        return function
    return lambda wrapped: wrapped


def _load_cosmos_module():
    fake_modules = {}
    cosmos = types.ModuleType("azure.cosmos")

    class OfflineCosmosClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("offline test")

    cosmos.CosmosClient = OfflineCosmosClient
    cosmos.PartitionKey = object
    cosmos_aio = types.ModuleType("azure.cosmos.aio")
    cosmos_aio.CosmosClient = OfflineCosmosClient
    cosmos_exceptions = types.ModuleType("azure.cosmos.exceptions")
    cosmos_exceptions.CosmosResourceNotFoundError = type(
        "CosmosResourceNotFoundError", (Exception,), {}
    )
    cosmos_exceptions.CosmosResourceExistsError = type(
        "CosmosResourceExistsError", (Exception,), {}
    )
    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    identity.DefaultAzureCredential = object
    identity_aio = types.ModuleType("azure.identity.aio")
    identity_aio.DefaultAzureCredential = object
    fake_modules.update({
        "azure": azure,
        "azure.cosmos": cosmos,
        "azure.cosmos.aio": cosmos_aio,
        "azure.cosmos.exceptions": cosmos_exceptions,
        "azure.identity": identity,
        "azure.identity.aio": identity_aio,
    })

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    saver = types.ModuleType("langchain_azure_cosmosdb")
    saver.CosmosDBSaver = object
    langsmith = types.ModuleType("langsmith")
    langsmith.traceable = _identity_decorator
    open_ai = types.ModuleType("src.app.services.azure_open_ai")
    open_ai.generate_embedding = lambda value: []
    open_ai.extract_keywords = lambda value: []
    fake_modules.update({
        "dotenv": dotenv,
        "langchain_azure_cosmosdb": saver,
        "langsmith": langsmith,
        "src.app.services.azure_open_ai": open_ai,
    })

    sys.modules.pop("src.app.services.azure_cosmos_db", None)
    with patch.dict(sys.modules, fake_modules):
        return importlib.import_module("src.app.services.azure_cosmos_db")


class _TripsContainer:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def query_items(self, **kwargs):
        self.calls.append(kwargs)
        return self.results

    def upsert_item(self, item):
        self.calls.append(item)


class _IdempotentTripsContainer:
    def __init__(self, exists_error):
        self.exists_error = exists_error
        self.items = {}

    def create_item(self, item):
        if item["id"] in self.items:
            raise self.exists_error()
        self.items[item["id"]] = dict(item)

    def read_item(self, item, partition_key):
        return self.items[item]


class _FakeContainer:
    def __init__(self, exists_error, not_found_error):
        self.exists_error = exists_error
        self.not_found_error = not_found_error
        self.items = {}
        self.create_calls = 0
        self.read_calls = 0
        self.delete_calls = []

    def create_item(self, item):
        self.create_calls += 1
        if item["id"] in self.items:
            raise self.exists_error()
        self.items[item["id"]] = dict(item)

    def read_item(self, item, partition_key):
        self.read_calls += 1
        if item not in self.items:
            raise self.not_found_error()
        return self.items[item]

    def upsert_item(self, item):
        self.items[item["id"]] = dict(item)

    def delete_item(self, item, partition_key):
        self.delete_calls.append(item)
        self.items.pop(item, None)


class BoundTripLookupTests(unittest.TestCase):
    def test_idempotent_session_create_reads_back_collision_and_rejects_conflict(self):
        cosmos = _load_cosmos_module()
        container = _FakeContainer(
            cosmos.CosmosResourceExistsError,
            cosmos.CosmosResourceNotFoundError,
        )
        cosmos.sessions_container = container
        arguments = {
            "user_id": "tony",
            "tenant_id": "marvel",
            "activeAgent": "orchestrator",
            "title": None,
            "session_id": "session-deterministic",
            "start_trip_request_id": "request-duplicate-123",
            "start_trip_fingerprint": "fingerprint-one",
        }

        first = cosmos.create_session_record(**arguments)
        replay = cosmos.create_session_record(**arguments)

        self.assertEqual(first, replay)
        self.assertEqual(len(container.items), 1)
        self.assertEqual(container.create_calls, 2)
        self.assertEqual(container.read_calls, 1)

        with self.assertRaises(cosmos.TripRequestConflictError):
            cosmos.create_session_record(
                **{
                    **arguments,
                    "title": "Different title",
                    "start_trip_fingerprint": "fingerprint-two",
                }
            )

        self.assertEqual(
            container.items["session-deterministic"]["title"],
            "New Conversation",
        )

    def test_production_path_replays_collision_readback_and_preserves_records(self):
        cosmos = _load_cosmos_module()
        from src.app.trip_planning import (
            TripRequestConflictError,
            start_trip_with_compensation,
        )

        sessions = _FakeContainer(
            cosmos.CosmosResourceExistsError,
            cosmos.CosmosResourceNotFoundError,
        )
        trips = _FakeContainer(
            cosmos.CosmosResourceExistsError,
            cosmos.CosmosResourceNotFoundError,
        )
        cosmos.sessions_container = sessions
        cosmos.trips_container = trips
        common = dict(
            tenant_id="marvel",
            user_id="tony",
            destination="Rome, Italy",
            start_date="2026-10-10",
            end_date="2026-10-14",
            active_agent="orchestrator",
            request_id="request-production-123",
            create_session=cosmos.create_session_record,
            create_trip=cosmos.create_trip,
            get_session=cosmos.get_session_by_id,
            get_trip=cosmos.get_trip,
            delete_trip=cosmos.delete_trip_record,
            delete_session=cosmos.delete_session_record,
        )

        first = start_trip_with_compensation(title=None, **common)
        replay = start_trip_with_compensation(title="New Conversation", **common)

        self.assertEqual(first, replay)
        self.assertEqual(len(sessions.items), 1)
        self.assertEqual(len(trips.items), 1)
        self.assertGreaterEqual(sessions.read_calls, 1)
        self.assertGreaterEqual(trips.read_calls, 2)

        stored_session = dict(first[0])
        stored_trip = dict(first[1])
        with self.assertRaises(TripRequestConflictError):
            start_trip_with_compensation(
                title=None,
                **{**common, "destination": "Paris, France"},
            )

        self.assertEqual(next(iter(sessions.items.values())), stored_session)
        self.assertEqual(next(iter(trips.items.values())), stored_trip)
        self.assertEqual(sessions.delete_calls, [])
        self.assertEqual(trips.delete_calls, [])

    def test_idempotent_trip_create_keeps_one_record_and_rejects_conflict(self):
        cosmos = _load_cosmos_module()
        container = _IdempotentTripsContainer(cosmos.CosmosResourceExistsError)
        cosmos.trips_container = container
        arguments = {
            "user_id": "tony",
            "tenant_id": "marvel",
            "destination": "Rome, Italy",
            "start_date": "2026-10-10",
            "end_date": "2026-10-14",
            "session_id": "session-deterministic",
            "trip_id": "trip-deterministic",
            "start_trip_request_id": "request-duplicate-123",
            "start_trip_fingerprint": "fingerprint-one",
        }

        self.assertEqual(cosmos.create_trip(**arguments), "trip-deterministic")
        self.assertEqual(cosmos.create_trip(**arguments), "trip-deterministic")
        self.assertEqual(len(container.items), 1)

        with self.assertRaises(cosmos.TripRequestConflictError):
            cosmos.create_trip(
                **{
                    **arguments,
                    "destination": "Paris, France",
                    "start_trip_fingerprint": "fingerprint-two",
                }
            )
        self.assertEqual(container.items["trip-deterministic"]["destination"], "Rome, Italy")

    def test_create_trip_persists_exact_dates_session_and_blank_plan(self):
        cosmos = _load_cosmos_module()
        container = _TripsContainer([])
        cosmos.trips_container = container

        first_id = cosmos.create_trip(
            user_id="tony",
            tenant_id="marvel",
            destination="Rome, Italy",
            start_date="2026-10-10",
            end_date="2026-10-14",
            session_id="session-1",
        )
        second_id = cosmos.create_trip(
            user_id="tony",
            tenant_id="marvel",
            destination="Rome, Italy",
            start_date="2026-10-10",
            end_date="2026-10-14",
            session_id="session-2",
        )

        self.assertNotEqual(first_id, second_id)
        created = container.calls[0]
        self.assertEqual(created["startDate"], "2026-10-10")
        self.assertEqual(created["endDate"], "2026-10-14")
        self.assertEqual(created["sessionId"], "session-1")
        self.assertEqual(created["days"], [])

    def test_lookup_is_scoped_without_status_filter_and_returns_newest(self):
        cosmos = _load_cosmos_module()
        expected = {
            "tripId": "trip-1",
            "tenantId": "marvel",
            "userId": "tony",
            "sessionId": "session-1",
            "status": "completed",
        }
        container = _TripsContainer([expected])
        cosmos.trips_container = container

        self.assertEqual(
            cosmos.get_bound_trip_for_session("marvel", "tony", "session-1"),
            expected,
        )
        call = container.calls[0]
        self.assertNotIn("c.status", call["query"])
        self.assertIn("ORDER BY c.createdAt DESC", call["query"])
        self.assertEqual(
            call["parameters"],
            [
                {"name": "@tenantId", "value": "marvel"},
                {"name": "@userId", "value": "tony"},
                {"name": "@sessionId", "value": "session-1"},
            ],
        )


if __name__ == "__main__":
    unittest.main()

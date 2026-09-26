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
    fake_modules.update(
        {
            "azure": azure,
            "azure.cosmos": cosmos,
            "azure.cosmos.aio": cosmos_aio,
            "azure.cosmos.exceptions": cosmos_exceptions,
            "azure.identity": identity,
            "azure.identity.aio": identity_aio,
        }
    )

    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    saver = types.ModuleType("langchain_azure_cosmosdb")
    saver.CosmosDBSaver = object
    langsmith = types.ModuleType("langsmith")
    langsmith.traceable = _identity_decorator
    open_ai = types.ModuleType("src.app.services.azure_open_ai")
    open_ai.generate_embedding = lambda value: []
    open_ai.extract_keywords = lambda value: []
    fake_modules.update(
        {
            "dotenv": dotenv,
            "langchain_azure_cosmosdb": saver,
            "langsmith": langsmith,
            "src.app.services.azure_open_ai": open_ai,
        }
    )

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


class _FailingTripsContainer:
    def query_items(self, **kwargs):
        raise RuntimeError("transient Cosmos query failure")


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
    def test_production_path_replays_collision_readback_and_preserves_records(self):
        cosmos = _load_cosmos_module()
        from src.app.trip_planning import (
            StartTripConflictError,
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
            get_trip=cosmos.get_trip,
            delete_trip=cosmos.delete_trip_record,
            delete_session=cosmos.delete_session_record,
        )

        first = start_trip_with_compensation(title=None, **common)
        replay = start_trip_with_compensation(title="New Conversation", **common)

        self.assertEqual(first, replay)
        self.assertEqual(len(sessions.items), 1)
        self.assertEqual(len(trips.items), 1)
        self.assertEqual(sessions.create_calls, 2)
        self.assertEqual(trips.create_calls, 2)
        self.assertGreaterEqual(sessions.read_calls, 1)
        self.assertGreaterEqual(trips.read_calls, 2)

        stored_session = dict(first[0])
        stored_trip = dict(first[1])
        with self.assertRaises(StartTripConflictError):
            start_trip_with_compensation(
                title=None,
                **{**common, "destination": "Paris, France"},
            )

        self.assertEqual(next(iter(sessions.items.values())), stored_session)
        self.assertEqual(next(iter(trips.items.values())), stored_trip)
        self.assertEqual(sessions.delete_calls, [])
        self.assertEqual(trips.delete_calls, [])

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
        self.assertEqual(created["destination"], "Rome, Italy")
        self.assertEqual(created["startDate"], "2026-10-10")
        self.assertEqual(created["endDate"], "2026-10-14")
        self.assertEqual(created["sessionId"], "session-1")
        self.assertEqual(created["days"], [])
        self.assertEqual(created["status"], "planning")

    def test_lookup_is_scoped_to_tenant_user_session_without_status_filter(self):
        cosmos = _load_cosmos_module()
        expected = {
            "tripId": "trip-1",
            "tenantId": "marvel",
            "userId": "tony",
            "sessionId": "session-1",
            "status": "confirmed",
        }
        container = _TripsContainer([expected])
        cosmos.trips_container = container

        actual = cosmos.get_bound_trip_for_session("marvel", "tony", "session-1")

        self.assertEqual(actual, expected)
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

    def test_lookup_returns_none_when_session_has_no_bound_trip(self):
        cosmos = _load_cosmos_module()
        cosmos.trips_container = _TripsContainer([])

        self.assertIsNone(
            cosmos.get_bound_trip_for_session("marvel", "pepper", "session-other")
        )

    def test_lookup_returns_newest_bound_trip_even_when_not_planning(self):
        cosmos = _load_cosmos_module()
        newest = {
            "tripId": "trip-newest",
            "status": "completed",
            "createdAt": "2026-09-22T12:00:00Z",
        }
        older = {
            "tripId": "trip-older",
            "status": "planning",
            "createdAt": "2026-09-21T12:00:00Z",
        }
        cosmos.trips_container = _TripsContainer([newest, older])

        self.assertEqual(
            cosmos.get_bound_trip_for_session("marvel", "tony", "session-1"),
            newest,
        )

    def test_lookup_failure_is_propagated_instead_of_reported_as_unbound(self):
        cosmos = _load_cosmos_module()
        cosmos.trips_container = _FailingTripsContainer()

        with self.assertRaisesRegex(
            RuntimeError,
            "transient Cosmos query failure",
        ):
            cosmos.get_bound_trip_for_session("marvel", "tony", "session-1")

    def test_unique_barcelona_reference_resolves_operational_trip(self):
        cosmos = _load_cosmos_module()
        barcelona = {
            "tripId": "trip_tony_barcelona_001",
            "tenantId": "marvel",
            "userId": "tony",
            "sessionId": None,
            "destination": "Barcelona, Spain",
            "createdAt": "2026-01-01T00:00:00Z",
        }
        cosmos.trips_container = _TripsContainer([barcelona])

        matches = cosmos.get_operational_trips_referenced_in_message(
            "marvel",
            "tony",
            "I'd like breakfast for my second day in BARCELONA.",
        )

        self.assertEqual(matches, [barcelona])
        self.assertEqual(
            cosmos.trips_container.calls[0]["parameters"],
            [
                {"name": "@tenantId", "value": "marvel"},
                {"name": "@userId", "value": "tony"},
            ],
        )

        with patch.object(
            cosmos,
            "get_bound_trip_for_session",
            return_value=None,
        ), patch.object(
            cosmos,
            "get_operational_trips_referenced_in_message",
            return_value=[barcelona],
        ):
            self.assertEqual(
                cosmos.resolve_trip_for_request(
                    "marvel",
                    "tony",
                    "session-unbound",
                    "I'd like breakfast for my second day in Barcelona.",
                ),
                barcelona,
            )

    def test_exact_trip_id_reference_resolves_without_partial_id_match(self):
        cosmos = _load_cosmos_module()
        trip = {
            "tripId": "trip_tony_barcelona_001",
            "destination": "Barcelona, Spain",
            "sessionId": None,
        }
        cosmos.trips_container = _TripsContainer([trip])

        exact = cosmos.get_operational_trips_referenced_in_message(
            "marvel",
            "tony",
            "Update trip_tony_barcelona_001 with breakfast.",
        )
        partial = cosmos.get_operational_trips_referenced_in_message(
            "marvel",
            "tony",
            "Update trip_tony_barcelona_001_extra with breakfast.",
        )

        self.assertEqual(exact, [trip])
        self.assertEqual(partial, [])

    def test_controlled_fixture_trip_is_excluded_from_reference_matches(self):
        cosmos = _load_cosmos_module()
        operational = {
            "tripId": "trip_tony_barcelona_001",
            "destination": "Barcelona, Spain",
            "sessionId": None,
        }
        fixture = {
            "tripId": "controlled-demo4-v1-marvel-trip-001",
            "destination": "Barcelona, Spain",
            "sessionId": "controlled-demo4-v1-marvel-session-001",
            "fixture_version": "controlled-demo4-v1",
        }
        cosmos.trips_container = _TripsContainer([fixture, operational])

        self.assertEqual(
            cosmos.get_operational_trips_referenced_in_message(
                "marvel",
                "tony",
                "Please update my Barcelona trip.",
            ),
            [operational],
        )

    def test_session_bound_trip_takes_precedence_without_operational_query(self):
        cosmos = _load_cosmos_module()
        bound = {"tripId": "trip-session", "destination": "Rome, Italy"}

        with patch.object(
            cosmos,
            "get_bound_trip_for_session",
            return_value=bound,
        ), patch.object(
            cosmos,
            "get_operational_trips_referenced_in_message",
        ) as operational_lookup:
            actual = cosmos.resolve_trip_for_request(
                "marvel",
                "tony",
                "session-1",
                "Please update my Barcelona trip.",
            )

        self.assertEqual(actual, bound)
        operational_lookup.assert_not_called()

    def test_destination_match_does_not_accept_partial_token(self):
        cosmos = _load_cosmos_module()
        york = {
            "tripId": "trip-york",
            "destination": "York, United Kingdom",
            "sessionId": None,
        }
        cosmos.trips_container = _TripsContainer([york])

        self.assertEqual(
            cosmos.get_operational_trips_referenced_in_message(
                "marvel",
                "tony",
                "Please update my Yorkshire itinerary.",
            ),
            [],
        )

    def test_ambiguous_duplicate_destination_remains_unbound(self):
        cosmos = _load_cosmos_module()
        matches = [
            {
                "tripId": "trip-barcelona-new",
                "destination": "Barcelona, Spain",
                "createdAt": "2026-02-01T00:00:00Z",
            },
            {
                "tripId": "trip-barcelona-old",
                "destination": "Barcelona, Spain",
                "createdAt": "2026-01-01T00:00:00Z",
            },
        ]

        with patch.object(
            cosmos,
            "get_bound_trip_for_session",
            return_value=None,
        ), patch.object(
            cosmos,
            "get_operational_trips_referenced_in_message",
            return_value=matches,
        ):
            actual = cosmos.resolve_trip_for_request(
                "marvel",
                "tony",
                "session-unbound",
                "Please update my Barcelona trip.",
            )

        self.assertIsNone(actual)


if __name__ == "__main__":
    unittest.main()

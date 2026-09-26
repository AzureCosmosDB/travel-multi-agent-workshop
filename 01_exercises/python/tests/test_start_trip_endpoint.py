from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import APIRouter, HTTPException
from src.app.traveller_context import add_active_trip_context


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))


async def _async_none(*args, **kwargs):
    return None


def _load_api_module():
    open_ai = types.ModuleType("src.app.services.azure_open_ai")
    open_ai.model = object()
    open_ai.generate_embedding = lambda value: []
    open_ai.AZURE_OPENAI_DEPLOYMENT = "test-deployment"

    cosmos = types.ModuleType("src.app.services.azure_cosmos_db")
    for name in (
        "sessions_container",
        "messages_container",
        "trips_container",
        "places_container",
        "debug_logs_container",
    ):
        setattr(cosmos, name, None)
    for name in (
        "create_session_record",
        "delete_session_record",
        "get_session_by_id",
        "append_message",
        "get_session_messages",
        "query_places_hybrid",
        "create_trip",
        "delete_trip_record",
        "get_trip",
        "resolve_trip_for_request",
        "query_places_with_theme",
        "query_places_filtered",
        "patch_active_agent",
        "update_session_activity",
        "create_user",
        "get_all_users",
        "get_user_by_id",
        "update_user_preferences",
        "store_debug_log",
        "get_debug_log",
        "query_debug_logs",
    ):
        setattr(cosmos, name, lambda *args, **kwargs: None)
    cosmos.aget_checkpoint_saver = _async_none
    cosmos.close_async_cosmos_client = _async_none
    cosmos.adelete_checkpoints_for_thread = _async_none

    travel_agents = types.ModuleType("src.app.travel_agents")
    travel_agents.setup_agents = _async_none
    travel_agents.build_agent_graph = lambda: None
    travel_agents.cleanup_persistent_session = _async_none
    travel_agents._current_user_preference_vector = ContextVar(
        "test_user_preference_vector",
        default=None,
    )

    agent_memory = types.ModuleType("src.app.services.agent_memory")
    agent_memory.MemoryNotFoundError = type("MemoryNotFoundError", (Exception,), {})
    agent_memory.delete_memory_by_id = _async_none
    agent_memory.get_memory_client = _async_none
    traveller_context = types.ModuleType("src.app.traveller_context")
    traveller_context.build_traveller_context = lambda *args, **kwargs: {}
    traveller_context.extract_summary_embedding = lambda *args, **kwargs: None
    traveller_context.add_active_trip_context = add_active_trip_context

    @contextmanager
    def use_traveller_context(*args, **kwargs):
        yield

    traveller_context.use_traveller_context = use_traveller_context
    optimization = types.ModuleType("src.app.services.optimization")
    optimization_api = types.ModuleType("src.app.optimization_api")
    optimization_api.router = APIRouter()

    fake_modules = {
        "src.app.services.azure_open_ai": open_ai,
        "src.app.services.azure_cosmos_db": cosmos,
        "src.app.travel_agents": travel_agents,
        "src.app.services.agent_memory": agent_memory,
        "src.app.traveller_context": traveller_context,
        "src.app.services.optimization": optimization,
        "src.app.optimization_api": optimization_api,
    }
    sys.modules.pop("src.app.travel_agents_api", None)
    with patch.dict(sys.modules, fake_modules):
        return importlib.import_module("src.app.travel_agents_api")


class StartTripEndpointTests(unittest.TestCase):
    def test_payload_conflict_maps_to_http_409(self):
        api = _load_api_module()
        request = api.StartTripRequest(
            requestId="request-conflict-123",
            destination="Paris, France",
            startDate="2026-10-10",
            endDate="2026-10-14",
        )

        with patch.object(
            api,
            "start_trip_with_compensation",
            side_effect=api.TripRequestConflictError("payload conflict"),
        ):
            with self.assertRaises(HTTPException) as raised:
                api.start_trip("marvel", "tony", request)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail, "payload conflict")

    def test_user_preferences_use_route_identity(self):
        api = _load_api_module()
        request = api.UpdateUserPreferencesRequest(
            preferences={"dietary": "vegetarian"}
        )
        updated_user = {
            "id": "tony",
            "userId": "tony",
            "tenantId": "marvel",
            "name": "Tony Stark",
            "createdAt": "2025-01-15T10:00:00Z",
            "preferences": {"dietary": "vegetarian"},
        }

        with patch.object(
            api,
            "update_user_preferences",
            return_value=updated_user,
        ) as update:
            result = api.patch_user_preferences("marvel", "tony", request)

        update.assert_called_once_with(
            "tony",
            "marvel",
            {"dietary": "vegetarian"},
        )
        self.assertEqual(result.preferences["dietary"], "vegetarian")

    def test_user_preference_persistence_errors_are_not_reported_as_success(self):
        api = _load_api_module()
        request = api.UpdateUserPreferencesRequest(
            preferences={"dietary": "vegetarian"}
        )

        with patch.object(
            api,
            "update_user_preferences",
            side_effect=RuntimeError("Cosmos unavailable"),
        ):
            with self.assertRaises(HTTPException) as raised:
                api.patch_user_preferences("marvel", "tony", request)

        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("Cosmos unavailable", raised.exception.detail)


class ActiveTripRequestContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_trip_resolution_supplies_projected_prompt_context(self):
        api = _load_api_module()
        resolved_trip = {
            "tripId": "trip-tony-lisbon",
            "destination": "Lisbon, Portugal",
            "startDate": "2026-11-10",
            "endDate": "2026-11-14",
            "status": "planning",
            "itinerary": [{"day": 1}],
        }

        with patch.object(
            api,
            "resolve_trip_for_request",
            return_value=resolved_trip,
        ) as resolve:
            active_trip, context = await api._resolve_active_trip_context(
                "marvel",
                "tony",
                "session-unbound",
                "Add breakfast to my Lisbon trip",
            )

        resolve.assert_called_once_with(
            "marvel",
            "tony",
            "session-unbound",
            "Add breakfast to my Lisbon trip",
        )
        self.assertIs(active_trip, resolved_trip)
        self.assertEqual(context["active_trip"]["tripId"], "trip-tony-lisbon")
        self.assertNotIn("itinerary", context["active_trip"])


if __name__ == "__main__":
    unittest.main()

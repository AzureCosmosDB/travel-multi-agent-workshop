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


class _Message:
    def __init__(self, content=""):
        self.content = content


def _identity_decorator(function=None, *args, **kwargs):
    if callable(function):
        return function
    return lambda wrapped: wrapped


def _tool_decorator(name=None, *args, **kwargs):
    if callable(name):
        return name

    def decorate(function):
        function.name = name or function.__name__
        function.description = kwargs.get("description") or function.__doc__
        function.args_schema = kwargs.get("args_schema")
        return function

    return decorate


def _stubbed_travel_agents_module():
    fake_modules = {}
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    fake_modules["dotenv"] = dotenv

    messages = types.ModuleType("langchain_core.messages")
    messages.AIMessage = _Message
    messages.HumanMessage = _Message
    messages.SystemMessage = _Message
    runnables = types.ModuleType("langchain_core.runnables")
    runnables.RunnableConfig = dict
    tools = types.ModuleType("langchain_core.tools")
    tools.tool = _tool_decorator
    fake_modules.update({
        "langchain_core": types.ModuleType("langchain_core"),
        "langchain_core.messages": messages,
        "langchain_core.runnables": runnables,
        "langchain_core.tools": tools,
    })

    langsmith = types.ModuleType("langsmith")
    langsmith.traceable = _identity_decorator
    fake_modules["langsmith"] = langsmith

    mcp_client = types.ModuleType("langchain_mcp_adapters.client")
    mcp_client.MultiServerMCPClient = object
    mcp_tools = types.ModuleType("langchain_mcp_adapters.tools")
    mcp_tools.load_mcp_tools = lambda *args, **kwargs: []
    fake_modules.update({
        "langchain_mcp_adapters": types.ModuleType("langchain_mcp_adapters"),
        "langchain_mcp_adapters.client": mcp_client,
        "langchain_mcp_adapters.tools": mcp_tools,
    })

    prebuilt = types.ModuleType("langgraph.prebuilt")
    prebuilt.create_react_agent = lambda *args, **kwargs: None
    langgraph_config = types.ModuleType("langgraph.config")
    langgraph_config.get_config = lambda: {}
    checkpoint_memory = types.ModuleType("langgraph.checkpoint.memory")
    checkpoint_memory.MemorySaver = type("MemorySaver", (), {})
    fake_modules.update({
        "langgraph": types.ModuleType("langgraph"),
        "langgraph.config": langgraph_config,
        "langgraph.prebuilt": prebuilt,
        "langgraph.checkpoint": types.ModuleType("langgraph.checkpoint"),
        "langgraph.checkpoint.memory": checkpoint_memory,
    })

    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = type("BaseModel", (), {})
    pydantic.Field = lambda default=None, *args, **kwargs: default
    fake_modules["pydantic"] = pydantic

    optimization = types.ModuleType("src.app.services.optimization")
    optimization.get_chat_model_for_turn = lambda messages, tenant_id=None: object()
    azure_open_ai = types.ModuleType("src.app.services.azure_open_ai")
    azure_open_ai.model = object()
    azure_open_ai.AZURE_OPENAI_DEPLOYMENT = "test"
    azure_open_ai._is_reasoning_deployment = lambda value: False
    fake_modules.update({
        "src.app.services.optimization": optimization,
        "src.app.services.azure_open_ai": azure_open_ai,
    })

    sys.modules.pop("src.app.travel_agents", None)
    with patch.dict(sys.modules, fake_modules):
        return importlib.import_module("src.app.travel_agents")


class _FakeModel:
    def bind_tools(self, tools):
        return ("bound", tools)


class DynamicModelSelectionTests(unittest.TestCase):
    def test_dynamic_model_selector_passes_langgraph_tenant_context(self):
        travel_agents = _stubbed_travel_agents_module()
        calls = []
        travel_agents.get_config = lambda: {
            "metadata": {"tenant_id": "analytics"},
        }
        travel_agents.optimization.get_chat_model_for_turn = (
            lambda messages, tenant_id=None: calls.append((messages, tenant_id)) or _FakeModel()
        )

        messages = [_Message("hello")]
        result = travel_agents._select_supervisor_model_for_state(
            {"messages": messages},
            [],
        )

        self.assertEqual(calls, [(messages, "analytics")])
        self.assertEqual(result, ("bound", []))


class _RecordingTripTool:
    def __init__(self, name):
        self.name = name
        self.description = name
        self.args_schema = None
        self.calls = []

    async def ainvoke(self, kwargs, config=None):
        self.calls.append((kwargs, config))
        return kwargs


class _RecordingItineraryAgent:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, state, config=None):
        self.calls.append((state, config))
        return {"messages": [_Message("updated")]}


class SessionBoundTripTests(unittest.IsolatedAsyncioTestCase):
    async def test_bound_trip_overrides_model_trip_and_prefetches_authoritative_trip(self):
        travel_agents = _stubbed_travel_agents_module()
        agent = _RecordingItineraryAgent()
        lookup = _RecordingTripTool("get_trip_details")
        travel_agents._itinerary_agent = agent
        travel_agents._mcp_itinerary_tools = [lookup]

        result = await travel_agents.create_or_update_itinerary_tool(
            trip_id="hallucinated-trip",
            selected_places=[{"placeId": "activity-1"}],
            config={"configurable": {
                "user_id": "tony",
                "tenant_id": "marvel",
                "thread_id": "session-1",
                "active_trip_id": "trip-authoritative",
            }},
        )

        self.assertEqual(result, "updated")
        prompt = agent.calls[0][0]["messages"][0].content
        self.assertIn("trip-authoritative", prompt)
        self.assertIn("First call get_trip_details", prompt)
        self.assertIn("Preserve the existing startDate and endDate", prompt)
        self.assertEqual(
            lookup.calls[0][0],
            {
                "trip_id": "trip-authoritative",
                "user_id": "tony",
                "tenant_id": "marvel",
            },
        )

    async def test_bound_update_forces_trip_id_and_preserves_dates_by_default(self):
        travel_agents = _stubbed_travel_agents_module()
        mcp_tool = _RecordingTripTool("update_trip")
        wrapped = travel_agents._wrap_trip_tool(mcp_tool)
        token = travel_agents._current_identity.set({
            "user_id": "tony",
            "tenant_id": "marvel",
            "session_id": "session-1",
            "active_trip_id": "trip-authoritative",
            "allow_date_changes": False,
        })
        try:
            await wrapped(
                config={},
                trip_id="hallucinated-trip",
                updates={
                    "days": [{"dayNumber": 1}],
                    "startDate": "2099-01-01",
                    "endDate": "2099-01-02",
                },
            )
        finally:
            travel_agents._current_identity.reset(token)

        kwargs = mcp_tool.calls[0][0]
        self.assertEqual(kwargs["trip_id"], "trip-authoritative")
        self.assertEqual(kwargs["updates"], {"days": [{"dayNumber": 1}]})

    async def test_bound_activity_update_preserves_status_and_unrelated_slots(self):
        travel_agents = _stubbed_travel_agents_module()
        mcp_tool = _RecordingTripTool("update_trip")
        wrapped = travel_agents._wrap_trip_tool(mcp_tool)
        token = travel_agents._current_identity.set({
            "user_id": "tony",
            "tenant_id": "marvel",
            "session_id": "session-1",
            "active_trip_id": "trip-authoritative",
            "allow_date_changes": False,
            "existing_trip": {
                "status": "planning",
                "days": [{
                    "dayNumber": 1,
                    "morning": {"activity": "Museum"},
                    "dinner": {"activity": "Existing Dinner"},
                }],
            },
        })
        try:
            await wrapped(
                config={},
                updates={
                    "status": "completed",
                    "days": [{
                        "dayNumber": 1,
                        "afternoon": {
                            "activity": "Harbor Kayaking",
                            "placeId": "activity-lisbon-kayak",
                        },
                    }],
                },
            )
        finally:
            travel_agents._current_identity.reset(token)

        updates = mcp_tool.calls[0][0]["updates"]
        self.assertNotIn("status", updates)
        self.assertEqual(updates["days"][0]["morning"]["activity"], "Museum")
        self.assertEqual(updates["days"][0]["dinner"]["activity"], "Existing Dinner")
        self.assertEqual(
            updates["days"][0]["afternoon"]["placeId"],
            "activity-lisbon-kayak",
        )

    async def test_unbound_chat_retains_trip_creation_behavior(self):
        travel_agents = _stubbed_travel_agents_module()
        mcp_tool = _RecordingTripTool("create_new_trip")
        wrapped = travel_agents._wrap_trip_tool(mcp_tool)
        token = travel_agents._current_identity.set({
            "user_id": "tony",
            "tenant_id": "marvel",
            "session_id": "session-2",
            "active_trip_id": "",
            "allow_date_changes": False,
        })
        try:
            await wrapped(
                config={},
                destination="Paris, France",
                start_date="2026-11-01",
                end_date="2026-11-03",
            )
        finally:
            travel_agents._current_identity.reset(token)

        self.assertEqual(mcp_tool.calls[0][0]["session_id"], "session-2")

    async def test_explicit_date_change_is_preserved_for_bound_update(self):
        travel_agents = _stubbed_travel_agents_module()
        mcp_tool = _RecordingTripTool("update_trip")
        wrapped = travel_agents._wrap_trip_tool(mcp_tool)
        token = travel_agents._current_identity.set({
            "user_id": "tony",
            "tenant_id": "marvel",
            "session_id": "session-1",
            "active_trip_id": "trip-authoritative",
            "allow_date_changes": True,
        })
        try:
            await wrapped(
                config={},
                updates={
                    "startDate": "2026-12-01",
                    "endDate": "2026-12-04",
                },
            )
        finally:
            travel_agents._current_identity.reset(token)

        self.assertEqual(
            mcp_tool.calls[0][0]["updates"],
            {
                "startDate": "2026-12-01",
                "endDate": "2026-12-04",
            },
        )


if __name__ == "__main__":
    unittest.main()

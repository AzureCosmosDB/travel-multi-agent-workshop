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

from src.app.traveller_context import (  # noqa: E402
    _current_traveller_context,
    add_active_trip_context,
    build_traveller_context,
    render_supervisor_prompt,
    use_traveller_context,
)
from src.app.services.agent_memory import (  # noqa: E402
    MemoryNotFoundError,
    delete_memory_by_id,
)


class _Message:
    def __init__(self, content=""):
        self.content = content


class _FakeTool:
    def __init__(self, name: str):
        self.name = name
        self.description = name
        self.args_schema = None

    async def ainvoke(self, _kwargs, config=None):
        return {"config": config}


class _FakeMCPClient:
    instances = []

    def __init__(self, config):
        self.config = config
        self.get_tools_calls = []
        self.session_calls = []
        self.__class__.instances.append(self)

    async def get_tools(self, *, server_name=None):
        self.get_tools_calls.append(server_name)
        return [
            _FakeTool(name)
            for name in (
                "create_session",
                "get_session_context",
                "append_turn",
                "add_turn",
                "recall_memories",
                "discover_places",
                "discover_itinerary",
                "create_new_trip",
                "update_trip",
                "get_trip_details",
                "get_user_summary",
            )
        ]

    def session(self, server_name):
        self.session_calls.append(server_name)
        raise AssertionError("setup_agents must not open a persistent MCP session")


class _FakeModel:
    def bind_tools(self, tools):
        return ("bound", tools)


class _ToolkitSummary:
    def model_dump(self):
        return {
            "content": "Prefers vegetarian Italian restaurants.",
            "embedding": [0.1, 0.2],
            "internal": "not model context",
        }


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
    fake_modules.update(
        {
            "langchain_core": types.ModuleType("langchain_core"),
            "langchain_core.messages": messages,
            "langchain_core.runnables": runnables,
            "langchain_core.tools": tools,
        }
    )

    langsmith = types.ModuleType("langsmith")
    langsmith.traceable = _identity_decorator
    fake_modules["langsmith"] = langsmith

    mcp_client = types.ModuleType("langchain_mcp_adapters.client")
    mcp_client.MultiServerMCPClient = _FakeMCPClient
    fake_modules.update(
        {
            "langchain_mcp_adapters": types.ModuleType("langchain_mcp_adapters"),
            "langchain_mcp_adapters.client": mcp_client,
        }
    )

    prebuilt = types.ModuleType("langgraph.prebuilt")

    def create_react_agent(agent_model, tools, prompt=None, **kwargs):
        return {
            "model": agent_model,
            "tools": tools,
            "prompt": prompt,
            "kwargs": kwargs,
        }

    prebuilt.create_react_agent = create_react_agent
    langgraph_config = types.ModuleType("langgraph.config")
    langgraph_config.get_config = lambda: {}
    checkpoint_memory = types.ModuleType("langgraph.checkpoint.memory")
    checkpoint_memory.MemorySaver = type("MemorySaver", (), {})
    fake_modules.update(
        {
            "langgraph": types.ModuleType("langgraph"),
            "langgraph.config": langgraph_config,
            "langgraph.prebuilt": prebuilt,
            "langgraph.checkpoint": types.ModuleType("langgraph.checkpoint"),
            "langgraph.checkpoint.memory": checkpoint_memory,
        }
    )

    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = type("BaseModel", (), {})
    pydantic.Field = lambda default=None, *args, **kwargs: default
    fake_modules["pydantic"] = pydantic

    optimization = types.ModuleType("src.app.services.optimization")
    optimization.get_chat_model_for_turn = lambda messages, tenant_id=None: _FakeModel()
    azure_open_ai = types.ModuleType("src.app.services.azure_open_ai")
    azure_open_ai.model = _FakeModel()
    fake_modules.update(
        {
            "src.app.services.optimization": optimization,
            "src.app.services.azure_open_ai": azure_open_ai,
        }
    )

    sys.modules.pop("src.app.travel_agents", None)
    with patch.dict(sys.modules, fake_modules):
        return importlib.import_module("src.app.travel_agents")


class TravellerContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.travel_agents = _stubbed_travel_agents_module()

    def test_route_identity_safe_profile_allowlist_and_sensitive_exclusions(self):
        context = build_traveller_context(
            {
                "id": "cosmos-id",
                "userId": "untrusted-document-id",
                "tenantId": "tenant-secret",
                "name": "Tony Stark",
                "age": 48,
                "gender": "male",
                "phone": "555-0100",
                "email": "tony@example.com",
                "createdAt": "2026-01-01",
                "unknown": "do-not-expose",
                "nickname": {"email": "nested@example.com"},
                "address": {
                    "street": "10880 Malibu Point",
                    "city": "Malibu",
                    "state": "CA",
                    "zip": "90265",
                    "country": "USA",
                    "unit": "Penthouse",
                },
            },
            "route-tony",
            _ToolkitSummary(),
        )

        self.assertEqual(
            context["profile"],
            {
                "userId": "route-tony",
                "name": "Tony Stark",
                "age": 48,
                "gender": "male",
                "address": {
                    "city": "Malibu",
                    "state": "CA",
                    "country": "USA",
                },
            },
        )
        self.assertEqual(
            context["memory_summary"],
            "Prefers vegetarian Italian restaurants.",
        )
        rendered = repr(context)
        for sensitive_value in (
            "cosmos-id",
            "untrusted-document-id",
            "tenant-secret",
            "555-0100",
            "tony@example.com",
            "10880 Malibu Point",
            "90265",
            "Penthouse",
            "do-not-expose",
            "nested@example.com",
            "not model context",
        ):
            self.assertNotIn(sensitive_value, rendered)

    def test_prompt_context_is_transient_and_does_not_mutate_messages(self):
        original_message = _Message("Find dinner")
        state = {"messages": [original_message]}
        original_messages = state["messages"]

        with use_traveller_context(
            build_traveller_context(
                {"name": "Tony"},
                "tony",
                {"content": "Vegetarian and prefers Italian food."},
            )
        ):
            prompt_messages = self.travel_agents._supervisor_prompt(state)

        self.assertIs(state["messages"], original_messages)
        self.assertEqual(state["messages"], [original_message])
        self.assertIs(prompt_messages[1], original_message)
        self.assertIn('"userId": "tony"', prompt_messages[0].content)
        self.assertIn("Vegetarian and prefers Italian food.", prompt_messages[0].content)
        self.assertIsNone(_current_traveller_context.get())

    def test_consecutive_contexts_do_not_leak_profiles(self):
        state = {"messages": [_Message("Hello")]}
        with use_traveller_context(
            build_traveller_context(
                {"name": "Tony"},
                "tony",
                {"content": "Tony likes Italian food."},
            )
        ):
            first_prompt = self.travel_agents._supervisor_prompt(state)[0].content

        with use_traveller_context(
            build_traveller_context(
                {"name": "Pepper"},
                "pepper",
                {"content": "Pepper likes Japanese food."},
            )
        ):
            second_prompt = self.travel_agents._supervisor_prompt(state)[0].content

        self.assertIn("Tony", first_prompt)
        self.assertNotIn("Tony", second_prompt)
        self.assertIn('"userId": "pepper"', second_prompt)
        self.assertIn("Pepper likes Japanese food.", second_prompt)
        self.assertIsNone(_current_traveller_context.get())

    def test_resolved_active_trip_is_projected_and_rendered_as_authoritative(self):
        context = add_active_trip_context(
            build_traveller_context({"name": "Tony"}, "tony", None),
            {
                "id": "fallback-id",
                "tripId": "trip-tony-lisbon",
                "destination": "Lisbon, Portugal",
                "startDate": "2026-11-10",
                "endDate": "2026-11-14",
                "status": "planning",
                "sessionId": None,
                "itinerary": [{"day": 1}],
                "tenantId": "marvel",
            },
        )

        self.assertEqual(
            context["active_trip"],
            {
                "tripId": "trip-tony-lisbon",
                "destination": "Lisbon, Portugal",
                "startDate": "2026-11-10",
                "endDate": "2026-11-14",
                "status": "planning",
            },
        )
        prompt = render_supervisor_prompt("BASE", context)
        self.assertIn("authoritative saved trip referenced by this request", prompt)
        self.assertIn("call `create_or_update_itinerary` directly", prompt)
        self.assertIn("call `find_places`, choose a concrete returned place", prompt)
        self.assertIn("never persist a generic placeholder", prompt)
        self.assertIn("Do not ask the traveller to identify or confirm", prompt)
        self.assertIn("Preserve the saved dates", prompt)
        self.assertIn('"tripId": "trip-tony-lisbon"', prompt)
        self.assertNotIn('"itinerary":', prompt)
        self.assertNotIn('"tenantId":', prompt)

    def test_unresolved_trip_does_not_add_active_trip_instruction(self):
        context = add_active_trip_context(
            build_traveller_context({"name": "Tony"}, "tony", None),
            None,
        )

        prompt = render_supervisor_prompt("BASE", context)

        self.assertNotIn("# Trusted Active Trip", prompt)
        self.assertNotIn("create_or_update_itinerary", prompt)

    def test_supervisor_rule_discovers_unnamed_places_before_trip_update(self):
        prompt_path = PYTHON_ROOT / "src" / "app" / "prompts" / "supervisor.prompty"
        prompt = prompt_path.read_text(encoding="utf-8")

        self.assertIn("including breakfast, lunch, or dinner", prompt)
        self.assertIn("first call `recall_memories`", prompt)
        self.assertIn("choose a concrete suitable place from the returned results", prompt)
        self.assertIn("Do not save a generic description or placeholder", prompt)
        self.assertIn("If the user names the exact place", prompt)


class MCPToolLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_uses_per_call_session_tools_and_cleanup_clears_references(self):
        travel_agents = _stubbed_travel_agents_module()
        _FakeMCPClient.instances.clear()

        await travel_agents.setup_agents()

        client = _FakeMCPClient.instances[-1]
        self.assertEqual(client.get_tools_calls, ["travel_tools"])
        self.assertEqual(client.session_calls, [])
        self.assertIs(travel_agents._mcp_client, client)
        self.assertIsNotNone(travel_agents.supervisor_agent)

        await travel_agents.cleanup_persistent_session()

        self.assertIsNone(travel_agents._mcp_client)
        self.assertIsNone(travel_agents.supervisor_agent)
        self.assertEqual(travel_agents._mcp_session_tools, [])
        self.assertEqual(travel_agents._mcp_find_places_tools, [])
        self.assertEqual(travel_agents._mcp_itinerary_tools, [])
        self.assertIsNone(travel_agents._mcp_recall_memories_tool)

    async def test_dynamic_model_selector_passes_langgraph_tenant_context(self):
        travel_agents = _stubbed_travel_agents_module()
        calls = []
        travel_agents.get_config = lambda: {
            "configurable": {"tenantId": "analytics"},
            "metadata": {"tenant_id": "ignored"},
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
    async def test_bound_trip_overrides_model_trip_and_requires_fetch_merge(self):
        travel_agents = _stubbed_travel_agents_module()
        agent = _RecordingItineraryAgent()
        lookup = _RecordingTripTool("get_trip_details")
        travel_agents._itinerary_agent = agent
        travel_agents._mcp_itinerary_tools = [lookup]

        result = await travel_agents.create_or_update_itinerary_tool(
            trip_id="hallucinated-trip",
            selected_places=[{"placeId": "activity-1"}],
            config={
                "configurable": {
                    "user_id": "tony",
                    "tenant_id": "marvel",
                    "thread_id": "session-1",
                    "active_trip_id": "trip-authoritative",
                }
            },
        )

        self.assertEqual(result, "updated")
        prompt = agent.calls[0][0]["messages"][0].content
        self.assertIn("trip-authoritative", prompt)
        self.assertIn("First call get_trip_details", prompt)
        self.assertIn('"trip_id": "trip-authoritative"', prompt)
        self.assertIn("Preserve the existing startDate and endDate", prompt)
        self.assertEqual(
            lookup.calls[0][0],
            {
                "trip_id": "trip-authoritative",
                "user_id": "tony",
                "tenant_id": "marvel",
            },
        )
        self.assertIn("Authoritative current trip", prompt)

    async def test_bound_update_forces_trip_id_and_preserves_dates_by_default(self):
        travel_agents = _stubbed_travel_agents_module()
        mcp_tool = _RecordingTripTool("update_trip")
        wrapped = travel_agents._wrap_trip_tool(mcp_tool)
        token = travel_agents._current_identity.set(
            {
                "user_id": "tony",
                "tenant_id": "marvel",
                "session_id": "session-1",
                "active_trip_id": "trip-authoritative",
                "allow_date_changes": False,
            }
        )
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
        self.assertEqual(kwargs["user_id"], "tony")
        self.assertEqual(kwargs["tenant_id"], "marvel")
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

    async def test_unbound_chat_retains_existing_trip_creation_behavior(self):
        travel_agents = _stubbed_travel_agents_module()
        mcp_tool = _RecordingTripTool("create_new_trip")
        wrapped = travel_agents._wrap_trip_tool(mcp_tool)
        token = travel_agents._current_identity.set(
            {
                "user_id": "tony",
                "tenant_id": "marvel",
                "session_id": "session-2",
                "active_trip_id": "",
                "allow_date_changes": False,
            }
        )
        try:
            await wrapped(
                config={},
                destination="Paris, France",
                start_date="2026-11-01",
                end_date="2026-11-03",
            )
        finally:
            travel_agents._current_identity.reset(token)

        kwargs = mcp_tool.calls[0][0]
        self.assertEqual(kwargs["destination"], "Paris, France")
        self.assertEqual(kwargs["session_id"], "session-2")

    async def test_explicit_date_change_is_not_stripped_from_bound_update(self):
        travel_agents = _stubbed_travel_agents_module()
        mcp_tool = _RecordingTripTool("update_trip")
        wrapped = travel_agents._wrap_trip_tool(mcp_tool)
        token = travel_agents._current_identity.set(
            {
                "user_id": "tony",
                "tenant_id": "marvel",
                "session_id": "session-1",
                "active_trip_id": "trip-authoritative",
                "allow_date_changes": True,
            }
        )
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


class _FakeMemoryClient:
    def __init__(self, memories):
        self.memories = memories
        self.get_calls = []
        self.delete_calls = []

    async def get_memories(self, **kwargs):
        self.get_calls.append(kwargs)
        return self.memories

    async def delete_cosmos(self, memory_id, **kwargs):
        self.delete_calls.append((memory_id, kwargs))


class MemoryDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_uses_exact_lookup_and_record_type(self):
        client = _FakeMemoryClient(
            [
                {
                    "id": "memory-1",
                    "user_id": "tony",
                    "thread_id": "session-1",
                    "type": "fact",
                }
            ]
        )

        await delete_memory_by_id(
            client,
            memory_id="memory-1",
            user_id="tony",
            thread_id="session-1",
        )

        self.assertEqual(
            client.get_calls,
            [
                {
                    "memory_id": "memory-1",
                    "user_id": "tony",
                    "thread_id": "session-1",
                    "include_superseded": True,
                }
            ],
        )
        self.assertEqual(
            client.delete_calls,
            [
                (
                    "memory-1",
                    {
                        "user_id": "tony",
                        "thread_id": "session-1",
                        "memory_type": "fact",
                    },
                )
            ],
        )

    async def test_missing_record_signals_not_found(self):
        client = _FakeMemoryClient([])

        with self.assertRaises(MemoryNotFoundError):
            await delete_memory_by_id(
                client,
                memory_id="missing",
                user_id="tony",
                thread_id="session-1",
            )

        self.assertEqual(client.delete_calls, [])

    async def test_mismatched_record_is_not_accidentally_deleted(self):
        client = _FakeMemoryClient(
            [
                {
                    "id": "different-memory",
                    "user_id": "tony",
                    "thread_id": "session-1",
                    "type": "fact",
                }
            ]
        )

        with self.assertRaises(MemoryNotFoundError):
            await delete_memory_by_id(
                client,
                memory_id="requested-memory",
                user_id="tony",
                thread_id="session-1",
            )

        self.assertEqual(client.delete_calls, [])


if __name__ == "__main__":
    unittest.main()

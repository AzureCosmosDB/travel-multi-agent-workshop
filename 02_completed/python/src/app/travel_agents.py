from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import sys
import uuid
from contextvars import ContextVar
from typing import Any, Literal

from dotenv import load_dotenv

# Add the project root to Python path to enable imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv(override=False)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langsmith import traceable
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel, Field

from src.app.services.azure_open_ai import (
    model,
    get_chat_model,
    AZURE_OPENAI_DEPLOYMENT,
    _is_reasoning_deployment,
)
from src.app.services import optimization_policy


# Setup logging - reduce clutter by setting specific loggers to WARNING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Reduce noise from verbose libraries
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)

# Prompt directory
PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# Runtime context used to pass large preference vectors into the place-search MCP
# tool without putting up to 1536 floats into chat history or model-visible text.
_current_user_preference_vector: ContextVar[list[float] | None] = ContextVar(
    "current_user_preference_vector", default=None
)

# Runtime context carrying the request's (user_id, tenant_id) so the itinerary
# sub-agent's trip tools are called with the correct identity instead of letting
# the sub-agent LLM guess it (it otherwise hallucinates placeholders like "user",
# persisting trips under the wrong partition key).
_current_identity: ContextVar[dict[str, str] | None] = ContextVar(
    "current_identity", default=None
)


def load_prompt(agent_name: str) -> str:
    """Load prompt from .prompty file."""
    file_path = os.path.join(PROMPT_DIR, f"{agent_name}.prompty")
    logger.info(f"Loading prompt for {agent_name} from {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.error(f"Prompt file not found for {agent_name}")
        return f"You are a {agent_name} agent in a travel planning system."


SUPERVISOR_BASE_PROMPT = load_prompt("supervisor")


def filter_tools_by_prefix(tools: list[Any], prefixes: list[str]) -> list[Any]:
    """Filter tools by name prefix."""
    return [
        mcp_tool
        for mcp_tool in tools
        if any(getattr(mcp_tool, "name", "").startswith(prefix) for prefix in prefixes)
    ]


def _tool_names(tools: list[Any]) -> list[str]:
    return [getattr(mcp_tool, "name", "<unnamed>") for mcp_tool in tools]


def _bind_parallel_tool_calls(base_model: Any) -> Any:
    """Return a model binding that asks OpenAI-compatible models to parallelize tool calls."""
    bind = getattr(base_model, "bind", None)
    if callable(bind):
        try:
            return bind(parallel_tool_calls=True)
        except TypeError as exc:
            logger.warning(
                "Model binding does not accept parallel_tool_calls; continuing without it: %s",
                exc,
            )
    return base_model


def _create_agent(agent_model: Any, tools: list[Any], prompt_text: str, **kwargs: Any) -> Any:
    """Create a ReAct agent across LangGraph versions that renamed the prompt kwarg."""
    signature = inspect.signature(create_react_agent)
    prompt_kwarg = "state_modifier" if "state_modifier" in signature.parameters else "prompt"
    return create_react_agent(agent_model, tools, **{prompt_kwarg: prompt_text}, **kwargs)


def _looks_like_vector(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, (int, float)) for item in value)


def _extract_user_preference_vector(
    explicit_vector: list[float] | None,
    config: RunnableConfig,
) -> list[float] | None:
    """Find a preference embedding supplied either as a tool arg or runtime config."""
    if _looks_like_vector(explicit_vector):
        return explicit_vector

    configurable = config.get("configurable", {}) if config else {}
    metadata = config.get("metadata", {}) if config else {}

    candidates = [
        configurable.get("user_preference_vector"),
        configurable.get("preference_vector"),
        metadata.get("user_preference_vector"),
        metadata.get("preference_vector"),
    ]

    for summary_key in ("user_summary", "userSummary"):
        for source in (configurable, metadata):
            summary = source.get(summary_key)
            if isinstance(summary, dict):
                candidates.extend(
                    [
                        summary.get("embedding"),
                        summary.get("user_preference_vector"),
                        summary.get("preference_vector"),
                    ]
                )

    for candidate in candidates:
        if _looks_like_vector(candidate):
            return candidate
    return None


def _wrap_discover_places_tool(mcp_tool: Any) -> Any:
    """Inject the request-scoped preference vector into discover_* MCP calls."""
    description = getattr(mcp_tool, "description", None) or "Discover places."
    args_schema = getattr(mcp_tool, "args_schema", None)
    tool_name = getattr(mcp_tool, "name", "discover_places")

    async def discover_places_with_preference_context(
        config: RunnableConfig,
        **kwargs: Any,
    ) -> Any:
        vector = _current_user_preference_vector.get()
        if vector is not None and not _looks_like_vector(kwargs.get("user_preference_vector")):
            kwargs["user_preference_vector"] = vector
        return await mcp_tool.ainvoke(kwargs, config=config)

    discover_places_with_preference_context.__name__ = tool_name
    discover_places_with_preference_context.__doc__ = description

    return tool(
        tool_name,
        args_schema=args_schema,
        description=description,
    )(discover_places_with_preference_context)


def _with_preference_vector_injection(tools: list[Any]) -> list[Any]:
    wrapped_tools: list[Any] = []
    for mcp_tool in tools:
        name = getattr(mcp_tool, "name", "")
        if name.startswith("discover_places") or name == "discover_itinerary":
            wrapped_tools.append(_wrap_discover_places_tool(mcp_tool))
        else:
            wrapped_tools.append(mcp_tool)
    return wrapped_tools


# Trip tools whose user_id/tenant_id must come from the request identity, not the
# sub-agent LLM (which otherwise guesses placeholder values).
_IDENTITY_TRIP_TOOLS = ("create_new_trip", "update_trip", "get_trip_details")


def _wrap_trip_tool(mcp_tool: Any) -> Any:
    """Force the request-scoped user_id / tenant_id onto trip MCP calls."""
    description = getattr(mcp_tool, "description", None) or "Trip tool."
    args_schema = getattr(mcp_tool, "args_schema", None)
    tool_name = getattr(mcp_tool, "name", "trip_tool")

    async def trip_tool_with_identity(
        config: RunnableConfig,
        **kwargs: Any,
    ) -> Any:
        identity = _current_identity.get() or {}
        user_id = identity.get("user_id")
        tenant_id = identity.get("tenant_id")
        session_id = identity.get("session_id")
        # Always override with the true identity — never trust an LLM-supplied value.
        if user_id:
            kwargs["user_id"] = user_id
        if tenant_id:
            kwargs["tenant_id"] = tenant_id
        # Stamp the session correlation key on trip creation (ADR-0010 §10.4).
        if session_id and tool_name == "create_new_trip":
            kwargs["session_id"] = session_id
        return await mcp_tool.ainvoke(kwargs, config=config)

    trip_tool_with_identity.__name__ = tool_name
    trip_tool_with_identity.__doc__ = description

    return tool(
        tool_name,
        args_schema=args_schema,
        description=description,
    )(trip_tool_with_identity)


def _with_identity_injection(tools: list[Any]) -> list[Any]:
    wrapped_tools: list[Any] = []
    for mcp_tool in tools:
        if getattr(mcp_tool, "name", "") in _IDENTITY_TRIP_TOOLS:
            wrapped_tools.append(_wrap_trip_tool(mcp_tool))
        else:
            wrapped_tools.append(mcp_tool)
    return wrapped_tools


def _last_message_content(result: Any) -> str:
    """Return compact text from the last message produced by a sub-agent."""
    if isinstance(result, dict) and result.get("messages"):
        content = getattr(result["messages"][-1], "content", None)
        if content is not None:
            return str(content)
    return str(result)


def _subagent_config(config: RunnableConfig, agent_name: str) -> RunnableConfig:
    """Preserve request configuration while tagging internal sub-agent calls."""
    inherited = dict(config or {})
    configurable = dict(inherited.get("configurable", {}) or {})
    metadata = dict(inherited.get("metadata", {}) or {})
    metadata["sub_agent"] = agent_name
    inherited["configurable"] = configurable
    inherited["metadata"] = metadata
    return inherited


class FindPlacesInput(BaseModel):
    city: str = Field(..., description="City to search")
    aspects: list[Literal["hotel", "activity", "dining"]] = Field(
        ...,
        description=(
            "Which categories of places to search; pass all needed aspects at once "
            "for parallel fan-out"
        ),
    )
    constraints: dict[str, Any] | None = Field(
        default=None,
        description="Optional constraints, e.g., {'dietary':'vegan','budget':'moderate'}",
    )
    user_preference_vector: list[float] | None = Field(
        default=None,
        description=(
            "Optional preference embedding for personalized RRF; usually injected by "
            "runtime config rather than model-visible text"
        ),
    )


class ItineraryInput(BaseModel):
    trip_id: str | None = Field(
        default=None,
        description="Existing trip id to update; omit or null to create a new trip",
    )
    destination: str | None = Field(
        default=None,
        description="Destination city or region for the itinerary",
    )
    days: list[dict[str, Any]] | str | None = Field(
        default=None,
        description="Requested day plans, duration, or structured day-by-day content",
    )
    selected_places: dict[str, Any] | list[dict[str, Any]] | str | None = Field(
        default=None,
        description="Selected hotel, activity, and dining options to arrange",
    )
    constraints: dict[str, Any] | None = Field(
        default=None,
        description="Traveller constraints and planning preferences",
    )
    dates: dict[str, Any] | str | None = Field(
        default=None,
        description="Optional trip dates or date range",
    )
    notes: str | None = Field(
        default=None,
        description="Additional update instructions or planning notes",
    )


# Global variables for MCP session management
_mcp_client: MultiServerMCPClient | None = None
_session_context: Any | None = None
_persistent_session: Any | None = None

# MCP tool subsets loaded once during startup
_mcp_session_tools: list[Any] = []
_mcp_find_places_tools: list[Any] = []
_mcp_itinerary_tools: list[Any] = []

# Raw MCP recall_memories tool, wrapped by recall_memories_tool below so the
# supervisor LLM never has to know or pass user_id / tenant_id.
_mcp_recall_memories_tool: Any | None = None

# Global agent variables
_find_places_agent: Any | None = None
_itinerary_agent: Any | None = None
supervisor_agent: Any | None = None

# ============================================================================
# Policy-driven capability-tiered model selection (SCEN-007 apply-loop effector)
# ============================================================================
# When the "model-selection" optimization policy is active + enabled, each turn
# is classified (trivial / routine / complex) from the latest user message and
# routed to the tier's Azure deployment. One supervisor ReAct agent is built and
# cached per deployment (they share the same tools + checkpointer). With no
# active policy the default deployment is used, so behavior is unchanged.
MODEL_SELECTION_SCENARIO = "model-selection"

_supervisor_by_deployment: dict[str, Any] = {}
_supervisor_build_ctx: dict[str, Any] | None = None

_DEFAULT_TRIVIAL_PATTERNS = [
    r"^(hi|hello|hey|yo|greetings|good (morning|afternoon|evening))\b",
    r"^(thanks|thank you|thx|ty|cheers|much appreciated|appreciate it|appreciated)\b",
    r"^(ok|okay|k|kk|sure|yes|yep|yeah|yup|no|nope|nah|alright|right|fine)\b",
    r"^(great|cool|awesome|perfect|nice|good|wonderful|excellent|fantastic|lovely|brilliant)\b",
    r"^(got it|sounds good|sounds great|looks good|that works|works for me|makes sense|will do|no worries|no problem)\b",
    r"^(bye|goodbye|see you|see ya|later|take care)\b",
]
_DEFAULT_COMPLEX_PATTERNS = [
    r"itinerary",
    r"plan (my|the|a|our) (trip|day|days|vacation|holiday)",
    r"build (me )?(an? )?itinerary",
    r"day[- ]by[- ]day",
    r"full (trip )?plan",
]
_DEFAULT_TRIVIAL_MAX_WORDS = 6


def _latest_user_text(messages: Any) -> str:
    """Return the most recent human/user message text from a messages list."""
    for m in reversed(list(messages or [])):
        if isinstance(m, dict):
            role, content = m.get("role"), m.get("content")
        else:
            role, content = getattr(m, "type", None), getattr(m, "content", None)
        if role in ("human", "user") and isinstance(content, str):
            return content
    return ""


def classify_turn_tier(text: str, classifier: dict[str, Any] | None = None) -> str:
    """Heuristically classify a turn as trivial / complex / routine.

    Conservative by design: only short greeting/acknowledgement messages become
    ``trivial`` (cheap tier), explicit itinerary/planning asks become ``complex``
    (capable tier), and everything else stays ``routine`` (default) so place
    queries never lose quality.
    """
    classifier = classifier or {}
    trivial_max = int(classifier.get("trivial_max_words", _DEFAULT_TRIVIAL_MAX_WORDS))
    trivial_patterns = classifier.get("trivial_patterns", _DEFAULT_TRIVIAL_PATTERNS)
    complex_patterns = classifier.get("complex_patterns", _DEFAULT_COMPLEX_PATTERNS)

    t = (text or "").strip().lower()
    if not t:
        return "routine"
    for p in complex_patterns:
        if re.search(p, t):
            return "complex"
    words = re.findall(r"[a-z0-9']+", t)
    if len(words) <= trivial_max and any(re.search(p, t) for p in trivial_patterns):
        return "trivial"
    return "routine"


def select_deployment_for_turn(messages: Any) -> tuple[str, str]:
    """Return (deployment_name, tier) for this turn from the active policy."""
    default = AZURE_OPENAI_DEPLOYMENT
    try:
        policy = optimization_policy.get_active_policy(MODEL_SELECTION_SCENARIO)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not read model-selection policy; using default model: {exc}")
        policy = None
    if not policy:
        return default, "default"
    params = policy.get("params", {}) or {}
    if not params.get("enabled", False):
        return default, "default"
    tiers = params.get("tiers", {}) or {}
    tier = classify_turn_tier(_latest_user_text(messages), params.get("classifier"))
    deployment = tiers.get(tier) or params.get("default_deployment") or default
    return deployment, tier


def _build_supervisor(deployment_name: str) -> Any:
    """Build a supervisor ReAct agent bound to a specific deployment."""
    if _supervisor_build_ctx is None:
        raise RuntimeError("Supervisor build context missing; call setup_agents() first")
    ctx = _supervisor_build_ctx
    agent_model = get_chat_model(deployment_name)
    # Reasoning (gpt-5/o-series) deployments don't reliably accept
    # parallel_tool_calls, so only request it for standard chat models.
    bound = agent_model if _is_reasoning_deployment(deployment_name) else _bind_parallel_tool_calls(agent_model)
    return _create_agent(
        bound,
        tools=ctx["tools"],
        prompt_text=ctx["prompt_text"],
        checkpointer=ctx["checkpointer"],
    )


def get_supervisor_for_turn(messages: Any) -> tuple[Any, str, str]:
    """Return (supervisor_agent, deployment, tier) for this turn (lazily built)."""
    deployment, tier = select_deployment_for_turn(messages)
    agent = _supervisor_by_deployment.get(deployment)
    if agent is None:
        try:
            agent = _build_supervisor(deployment)
            _supervisor_by_deployment[deployment] = agent
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to build supervisor for '{deployment}'; falling back to default: {exc}")
            deployment, tier = AZURE_OPENAI_DEPLOYMENT, "default"
            agent = _supervisor_by_deployment.get(deployment) or supervisor_agent
    return agent, deployment, tier


@tool("find_places", args_schema=FindPlacesInput)
@traceable
async def find_places_tool(
    city: str,
    aspects: list[Literal["hotel", "activity", "dining"]],
    constraints: dict[str, Any] | None = None,
    user_preference_vector: list[float] | None = None,
    config: RunnableConfig = None,
) -> str:
    """Search hotels, activities, or dining in a city. Returns raw structured place data."""
    effective_config = config or {"configurable": {}, "metadata": {}}
    vector = _extract_user_preference_vector(user_preference_vector, effective_config)
    configurable = effective_config.get("configurable", {}) or {}
    user_id = (
        configurable.get("user_id")
        or configurable.get("userId")
        or ""
    )
    tenant_id = (
        configurable.get("tenant_id")
        or configurable.get("tenantId")
        or ""
    )

    token = _current_user_preference_vector.set(vector)
    try:
        return await _oneshot_find_places(
            city=city,
            aspects=list(aspects),
            constraints=constraints,
            user_id=str(user_id),
            tenant_id=str(tenant_id),
            vector=vector,
            config=_subagent_config(effective_config, "find_places"),
        )
    finally:
        _current_user_preference_vector.reset(token)


_FIND_PLACES_SELECTOR_PROMPT = (
    "You translate the supervisor's structured place-search request into ONE tool call. "
    "Rules:\n"
    "- For 2 or 3 aspects, call `discover_itinerary` once with `aspects` set to the requested aspects.\n"
    "- For exactly 1 aspect, call `discover_places` with `filters={\"type\": <aspect>}`.\n"
    "- Aspect names in tool args MUST be: 'hotel', 'activity', 'restaurant'. Map any 'dining' aspect to 'restaurant'.\n"
    "- `geo_scope` = the city.\n"
    "- Derive a short `query` (under 20 words) from the constraints: interests, vibe, dietary, budget, accessibility.\n"
    "- Always pass `user_id` and `tenant_id` exactly as given.\n"
    "- NEVER include `user_preference_vector` in tool args; the runtime injects it.\n"
    "- Output ONLY the tool call. No prose."
)


async def _oneshot_find_places(
    city: str,
    aspects: list[str],
    constraints: dict[str, Any] | None,
    user_id: str,
    tenant_id: str,
    vector: list[float] | None,
    config: RunnableConfig,
) -> str:
    """One-shot find-places node: ONE LLM call selects tool args, Python executes, return raw result.

    Replaces the ReAct sub-agent's 2-LLM-call loop (decide + format) with a single
    forced tool-choice call. The tool output is returned verbatim to the supervisor,
    which synthesizes the final user-facing response.
    """
    selector_tools = [
        wrapped_tool
        for wrapped_tool in _mcp_find_places_tools
        if getattr(wrapped_tool, "name", "").startswith("discover_")
    ]
    if not selector_tools:
        return json.dumps({"error": "no discover_* tools available"})

    constraints_str = json.dumps(constraints or {}, ensure_ascii=False, default=str)
    messages = [
        SystemMessage(content=_FIND_PLACES_SELECTOR_PROMPT),
        HumanMessage(
            content=(
                f"city={city!r}\n"
                f"aspects={aspects!r}\n"
                f"constraints={constraints_str}\n"
                f"user_id={user_id!r}\n"
                f"tenant_id={tenant_id!r}\n"
                f"user_preference_vector={'runtime-injected' if vector else 'absent'}"
            )
        ),
    ]

    bound = model.bind_tools(selector_tools, tool_choice="required")
    ai_msg = await bound.ainvoke(messages, config=config)

    tool_calls = getattr(ai_msg, "tool_calls", None) or []
    if not tool_calls:
        return json.dumps(
            {"error": "selector model emitted no tool call", "city": city, "aspects": aspects},
            ensure_ascii=False,
        )

    tools_by_name = {wrapped_tool.name: wrapped_tool for wrapped_tool in selector_tools}
    results: list[dict[str, Any]] = []
    for call in tool_calls:
        name = call.get("name")
        args = dict(call.get("args") or {})
        args.setdefault("user_id", user_id)
        if tenant_id:
            args.setdefault("tenant_id", tenant_id)
        tool_fn = tools_by_name.get(name)
        if tool_fn is None:
            results.append({"tool": name, "error": "unknown tool"})
            continue
        try:
            raw = await tool_fn.ainvoke(args, config=config)
        except Exception as exc:
            logger.warning("oneshot find_places tool=%s failed: %s", name, exc)
            results.append({"tool": name, "error": str(exc)})
            continue
        loggable_args = {k: v for k, v in args.items() if k != "user_preference_vector"}
        results.append({"tool": name, "args": loggable_args, "result": raw})

    return json.dumps(results, ensure_ascii=False, default=str)


class RecallMemoriesInput(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Topic or question to search the user's stored long-term memories for. "
            "Examples: 'hotel preferences', 'dietary needs', 'recent Paris trip', "
            "'past hiking experiences'. Use short topical phrases, not full sentences."
        ),
    )
    top_k: int = Field(
        default=10,
        description="Maximum number of memory records to return (1-15).",
    )


@tool("recall_memories", args_schema=RecallMemoriesInput)
@traceable
async def recall_memories_tool(
    query: str,
    top_k: int = 10,
    config: RunnableConfig = None,
) -> str:
    """Search the current traveller's stored long-term memories (facts, episodic events,
    procedural notes) by topic. Use this whenever the user asks about their own
    preferences, prior trips, or anything personal, or when you need preference
    context to bias a `find_places` search beyond what `## What we know about this
    traveller` already states.
    """
    effective_config = config or {"configurable": {}, "metadata": {}}
    configurable = effective_config.get("configurable", {}) or {}
    user_id = configurable.get("user_id") or configurable.get("userId") or ""
    if not user_id:
        return json.dumps({"error": "no user_id in runtime config"})

    if _mcp_recall_memories_tool is None:
        return json.dumps({"error": "recall_memories MCP tool not loaded"})

    bounded_top_k = max(1, min(int(top_k or 10), 15))
    try:
        return await _mcp_recall_memories_tool.ainvoke(
            {"user_id": str(user_id), "query": query, "top_k": bounded_top_k},
            config=_subagent_config(effective_config, "recall_memories"),
        )
    except Exception as exc:
        logger.warning("recall_memories tool failed user=%s query=%r: %s", user_id, query, exc)
        return json.dumps({"error": str(exc)})


@tool("create_or_update_itinerary", args_schema=ItineraryInput)
@traceable
async def create_or_update_itinerary_tool(
    trip_id: str | None = None,
    destination: str | None = None,
    days: list[dict[str, Any]] | str | None = None,
    selected_places: dict[str, Any] | list[dict[str, Any]] | str | None = None,
    constraints: dict[str, Any] | None = None,
    dates: dict[str, Any] | str | None = None,
    notes: str | None = None,
    config: RunnableConfig = None,
) -> str:
    """Create a new saved itinerary or update an existing trip plan."""
    if _itinerary_agent is None:
        raise RuntimeError("Travel agents have not been initialized")

    payload = {
        "trip_id": trip_id,
        "destination": destination,
        "days": days,
        "selected_places": selected_places,
        "constraints": constraints,
        "dates": dates,
        "notes": notes,
    }
    compact_payload = {key: value for key, value in payload.items() if value is not None}
    user_msg = (
        "Create or update the itinerary using this structured request. "
        "Persist changes with the trip tools before reporting success.\n"
        f"{json.dumps(compact_payload, ensure_ascii=False, default=str)}"
    )
    state = {"messages": [HumanMessage(content=user_msg)]}
    effective_config = config or {"configurable": {}, "metadata": {}}
    configurable = effective_config.get("configurable", {}) or {}
    identity = {
        "user_id": configurable.get("user_id") or configurable.get("userId") or "",
        "tenant_id": configurable.get("tenant_id") or configurable.get("tenantId") or "",
        "session_id": (configurable.get("session_id") or configurable.get("sessionId")
                       or configurable.get("thread_id") or ""),
    }
    identity_token = _current_identity.set(identity)
    try:
        result = await _itinerary_agent.ainvoke(
            state,
            config=_subagent_config(effective_config, "itinerary"),
        )
    finally:
        _current_identity.reset(identity_token)
    return _last_message_content(result)


async def setup_agents(checkpointer=None):
    """
    Initialize the supervisor and internal sub-agents with their MCP tools.

    This creates one persistent MCP session for the process. The topology is:
    user -> supervisor ReAct agent -> find_places or create_or_update_itinerary tools,
    where each tool invokes an internal ReAct sub-agent.
    """
    global _mcp_client, _session_context, _persistent_session
    global _mcp_session_tools, _mcp_find_places_tools, _mcp_itinerary_tools
    global _mcp_recall_memories_tool
    global _find_places_agent, _itinerary_agent, supervisor_agent

    if supervisor_agent is not None:
        logger.info("✅ Travel agents already initialized")
        return

    logger.info("🚀 Starting Travel Assistant MCP client...")

    # Load authentication configuration
    try:
        simple_token = os.getenv("MCP_AUTH_TOKEN")
        github_client_id = os.getenv("GITHUB_CLIENT_ID")
        github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")

        logger.info("🔐 Client Authentication Configuration:")
        logger.info(f"   Simple Token: {'SET' if simple_token else 'NOT SET'}")
        logger.info(
            f"   GitHub OAuth: {'SET' if github_client_id and github_client_secret else 'NOT SET'}"
        )

        if github_client_id and github_client_secret:
            auth_mode = "github_oauth"
            logger.info("   Mode: GitHub OAuth (Production)")
        elif simple_token:
            auth_mode = "simple_token"
            logger.info("   Mode: Simple Token (Development)")
        else:
            auth_mode = "none"
            logger.info("   Mode: No Authentication")

    except ImportError:
        auth_mode = "none"
        simple_token = None
        logger.info("🔐 Client Authentication: Dependencies unavailable - no auth")

    logger.info("   - Transport: streamable_http")
    logger.info(f"   - Server URL: {os.getenv('MCP_SERVER_BASE_URL', 'http://localhost:8080')}/mcp/")
    logger.info(f"   - Authentication: {auth_mode.upper()}")
    logger.info("   - Status: Ready to connect\n")

    # MCP Client configuration
    client_config: dict[str, Any] = {
        "travel_tools": {
            "transport": "streamable_http",
            "url": os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8080") + "/mcp/",
        }
    }

    # Add authentication if configured
    if auth_mode == "simple_token" and simple_token:
        client_config["travel_tools"]["headers"] = {"Authorization": f"Bearer {simple_token}"}
        logger.info("🔐 Added Bearer token authentication to client")
    elif auth_mode == "github_oauth":
        client_config["travel_tools"]["auth"] = "oauth"
        logger.info("🔐 Enabled OAuth authentication for client")

    _mcp_client = MultiServerMCPClient(client_config)
    logger.info("✅ MCP Client initialized successfully")

    # Create persistent session + load tools with timeouts. On a cold start the API
    # can race ahead of the MCP server being ready; without a timeout the connect/
    # load hangs indefinitely and blocks uvicorn startup (failing the health probe).
    # A timeout makes it fail fast so the caller's retry logic recovers.
    _session_context = _mcp_client.session("travel_tools")
    _persistent_session = await asyncio.wait_for(_session_context.__aenter__(), timeout=30)

    # Load all MCP tools once for this persistent session
    all_tools = await asyncio.wait_for(load_mcp_tools(_persistent_session), timeout=30)

    logger.info("[DEBUG] All tools registered from Travel Assistant MCP server:")
    for mcp_tool in all_tools:
        logger.info(f"  - {mcp_tool.name}")

    _mcp_session_tools = filter_tools_by_prefix(
        all_tools,
        ["create_session", "get_session_context", "append_turn", "add_turn"],
    )
    # filter_tools_by_prefix returns a list; recall_memories_tool invokes this as a
    # single tool (.ainvoke), so take the first match (or None). Without this the
    # agent's recall_memories always fails with "'list' object has no attribute
    # 'ainvoke'" and never reads stored memories to personalize responses.
    _recall_matches = filter_tools_by_prefix(all_tools, ["recall_memories"])
    _mcp_recall_memories_tool = _recall_matches[0] if _recall_matches else None
    _mcp_find_places_tools = _with_preference_vector_injection(
        filter_tools_by_prefix(
            all_tools,
            ["discover_places", "discover_itinerary", "add_turn", "recall_memories", "get_user_summary"],
        )
    )
    _mcp_itinerary_tools = _with_identity_injection(
        filter_tools_by_prefix(
            all_tools,
            [
                "create_new_trip",
                "update_trip",
                "get_trip_details",
                "add_turn",
                "recall_memories",
                "get_user_summary",
            ],
        )
    )

    logger.info("\n📊 Tool Distribution (Supervisor + 2 Sub-Agents):")
    logger.info(f"   Supervisor session tools: {len(_mcp_session_tools)} {_tool_names(_mcp_session_tools)}")
    logger.info(f"   Find Places tools: {len(_mcp_find_places_tools)} {_tool_names(_mcp_find_places_tools)}")
    logger.info(f"   Itinerary tools: {len(_mcp_itinerary_tools)} {_tool_names(_mcp_itinerary_tools)}")

    _find_places_agent = None
    logger.info("   Find Places: one-shot tool-selector node (no ReAct loop)")

    _itinerary_agent = _create_agent(
        model,
        _mcp_itinerary_tools,
        load_prompt("itinerary_agent"),
    )

    supervisor_tools = [
        find_places_tool,
        create_or_update_itinerary_tool,
        recall_memories_tool,
        *_mcp_session_tools,
    ]
    supervisor_checkpointer = checkpointer or MemorySaver()

    # Stash the build context so per-tier supervisors (SCEN-007 model selection)
    # can be built lazily against other deployments, sharing tools + checkpointer.
    global _supervisor_build_ctx, _supervisor_by_deployment
    _supervisor_build_ctx = {
        "tools": supervisor_tools,
        "prompt_text": SUPERVISOR_BASE_PROMPT,
        "checkpointer": supervisor_checkpointer,
    }
    _supervisor_by_deployment = {}

    supervisor_agent = _build_supervisor(AZURE_OPENAI_DEPLOYMENT)
    _supervisor_by_deployment[AZURE_OPENAI_DEPLOYMENT] = supervisor_agent

    logger.info("✅ Supervisor and sub-agents created successfully\n")


async def cleanup_persistent_session():
    """Clean up the persistent MCP session when the application shuts down."""
    global _session_context, _persistent_session, supervisor_agent
    global _find_places_agent, _itinerary_agent

    if _session_context is not None and _persistent_session is not None:
        try:
            await _session_context.__aexit__(None, None, None)
            logger.info("✅ MCP persistent session cleaned up successfully")
        except Exception as e:
            logger.error(f"Error cleaning up MCP session: {e}")

    _session_context = None
    _persistent_session = None
    supervisor_agent = None
    _find_places_agent = None
    _itinerary_agent = None


def build_agent_graph():
    """Return the initialized supervisor graph for existing API callers."""
    if supervisor_agent is None:
        raise RuntimeError("Travel agents have not been initialized; call setup_agents() first")
    logger.info("🏗️  Returning supervisor ReAct graph")
    return supervisor_agent


# ============================================================================
# Interactive Chat Function (for CLI testing)
# ============================================================================

async def interactive_chat():
    """Interactive CLI for testing the travel assistant."""
    thread_id = str(uuid.uuid4())
    thread_config = {
        "configurable": {
            "thread_id": thread_id,
            "userId": "Tony",
            "tenantId": "Marvel",
        }
    }

    print("\n" + "=" * 70)
    print("🌍 Travel Assistant - Interactive Test Mode")
    print("=" * 70)
    print("Type 'exit' to end the conversation")
    print("=" * 70 + "\n")

    graph = build_agent_graph()
    user_input = input("You: ")

    while user_input.lower() != "exit":
        input_message = {"messages": [HumanMessage(content=user_input)]}
        response_found = False

        async for update in graph.astream(input_message, config=thread_config, stream_mode="updates"):
            for node_id, value in update.items():
                if isinstance(value, dict) and value.get("messages"):
                    last_message = value["messages"][-1]
                    if isinstance(last_message, AIMessage):
                        print(f"{node_id}: {last_message.content}\n")
                        response_found = True

        if not response_found:
            logger.debug("No AI response received.")

        user_input = input("You: ")

    print("\n👋 Goodbye!")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    async def main():
        await setup_agents()
        await interactive_chat()

    asyncio.run(main())

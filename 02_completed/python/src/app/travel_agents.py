import logging
import os
import sys
import uuid
import asyncio
import json
import re
from typing import Literal
from datetime import datetime, UTC

# Add the project root to Python path to enable imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(override=False)

from langchain_core.messages import ToolMessage, SystemMessage, AIMessage, HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt
from langsmith import traceable
from langgraph_checkpoint_cosmosdb import CosmosDBSaver

from src.app.services.azure_open_ai import model
from src.app.services.azure_cosmos_db import (
    DATABASE_NAME, checkpoint_container,
    sessions_container, patch_active_agent,
    update_session_container, append_message,
    count_active_messages, get_all_user_memories,
    query_places_filtered, query_places_hybrid
)

# Setup logging - reduce clutter by setting specific loggers to WARNING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Reduce noise from verbose libraries
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)

# Local interactive mode flag
local_interactive_mode = False

# Prompt directory
PROMPT_DIR = os.path.join(os.path.dirname(__file__), 'prompts')


def load_prompt(agent_name: str) -> str:
    """Load prompt from .prompty file"""
    file_path = os.path.join(PROMPT_DIR, f"{agent_name}.prompty")
    logger.info(f"Loading prompt for {agent_name} from {file_path}")
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        logger.error(f"Prompt file not found for {agent_name}")
        return f"You are a {agent_name} agent in a travel planning system."


def filter_tools_by_prefix(tools, prefixes):
    """Filter tools by name prefix"""
    return [tool for tool in tools if any(tool.name.startswith(prefix) for prefix in prefixes)]


def format_conflict_message(conflicts: list) -> str:
    """
    Format conflict information for user confirmation.
    
    Args:
        conflicts: List of conflict dictionaries with preference, conflict, and strategy
        
    Returns:
        Formatted message string asking user to clarify
    """
    if not conflicts:
        return ""
    
    msg = "I noticed something about your preferences that I'd like to clarify:\n\n"
    
    for i, conflict in enumerate(conflicts, 1):
        pref = conflict.get("preference", {})
        existing = conflict.get("conflict", "")
        strategy = conflict.get("strategy", "")
        
        msg += f"{i}. You previously mentioned: \"{existing}\"\n"
        msg += f"   But now you said: \"{pref.get('text', '')}\"\n"
        if strategy:
            msg += f"   ({strategy})\n"
        msg += "\n"
    
    msg += "Have your preferences changed, or is this specific to a particular trip? Let me know so I can update your profile correctly!"
    
    return msg


def _extract_transfer_destination(response: dict) -> str | None:
    """Return the specialist destination from the latest transfer tool result."""
    valid_destinations = {
        "hotel",
        "activity",
        "dining",
        "itinerary_generator",
        "summarizer",
        "orchestrator",
    }

    for message in reversed(response.get("messages", [])):
        if isinstance(message, AIMessage):
            for tool_call in message.additional_kwargs.get("tool_calls", []):
                function_name = tool_call.get("function", {}).get("name", "")
                if function_name.startswith("transfer_to_"):
                    goto = function_name.replace("transfer_to_", "")
                    if goto in valid_destinations:
                        return goto

        if not isinstance(message, ToolMessage):
            continue

        try:
            content = json.loads(message.content)
        except Exception as exc:
            logger.debug(f"Could not parse transfer ToolMessage: {exc}")
            continue

        goto = content.get("goto")
        if goto in valid_destinations:
            return goto

    return None


def _deterministic_specialist_route(message: str) -> str | None:
    """Route obvious domain requests without spending an LLM turn."""
    normalized = message.lower()
    has_preference_statement = re.search(
        r"\b(i|we)\s+(am|are|have|need|prefer|like|love|hate|avoid|require)\b|\bmy\s+(preference|preferences|diet|budget|allergy|allergies|restriction|restrictions|requirement|requirements)\b",
        normalized,
    )
    has_search_intent = re.search(
        r"\b(find|show|recommend|search|suggest|where should|what should|places?|restaurants?|hotels?|activities?|museums?|attractions?)\b",
        normalized,
    )
    if has_preference_statement and not has_search_intent:
        return None

    if re.search(r"\b(restaurant|restaurants|dining|dinner|lunch|breakfast|food|eat|cafe|cafes)\b", normalized):
        return "dining"
    if re.search(r"\b(hotel|hotels|stay|stays|lodging|accommodation|accommodations)\b", normalized):
        return "hotel"
    if re.search(r"\b(activity|activities|attraction|attractions|museum|museums|tour|tours|things to do)\b", normalized):
        return "activity"
    return None


# Global variables for MCP session management
_mcp_client = None
_session_context = None
_persistent_session = None
# Global agent variables
orchestrator_agent = None
itinerary_generator_agent = None
summarizer_agent = None


def _latest_user_text(state: MessagesState) -> str:
    message = _latest_user_message(state)
    return str(message.content) if message else ""


def _latest_user_message(state: MessagesState) -> HumanMessage | None:
    for message in reversed(state["messages"]):
        if isinstance(message, HumanMessage):
            return message
    return None


def _extract_geo_scope(message: str) -> str | None:
    match = re.search(
        r"\b(?:in|near|around|for)\s+([A-Za-z][A-Za-z\s-]+?)(?=[?.!,]|\s+(?:with|for|that|and|or|near|in)\s|$)",
        message,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip().lower().replace(" ", "-")
    return None


PREFERENCE_TAXONOMY = {
    "dietary": {
        "pescatarian": {
            "aliases": ["pescatarian", "only eat fish", "eat fish", "fish"],
            "filters": {"dietary": ["seafood"]},
            "search_terms": ["seafood", "fish", "pescatarian"],
            "rank_terms": ["seafood", "fish"],
            "required_terms": ["seafood", "fish"],
            "avoid_terms": ["pork", "meat", "poultry"],
        },
        "vegan": {
            "aliases": ["vegan", "plant based", "plant-based"],
            "filters": {"dietary": ["vegan"]},
            "search_terms": ["vegan", "plant-based"],
            "rank_terms": ["vegan", "plant-based"],
            "required_terms": ["vegan", "plant-based"],
            "avoid_terms": ["meat", "seafood", "dairy"],
        },
        "vegetarian": {
            "aliases": ["vegetarian"],
            "filters": {"dietary": ["vegetarian"]},
            "search_terms": ["vegetarian"],
            "rank_terms": ["vegetarian"],
            "required_terms": ["vegetarian"],
            "avoid_terms": ["meat", "seafood"],
        },
        "gluten_free": {
            "aliases": ["gluten free", "gluten-free"],
            "filters": {"dietary": ["gluten-free"]},
            "search_terms": ["gluten-free"],
            "rank_terms": ["gluten-free"],
            "required_terms": ["gluten-free"],
            "avoid_terms": ["gluten"],
        },
    },
    "price": {
        "luxury": {
            "aliases": ["luxury", "high-end", "upscale", "fine dining", "michelin", "michelin_star"],
            "filters": {},
            "search_terms": ["luxury", "fine dining", "michelin"],
            "rank_terms": ["luxury", "upscale", "fine dining", "michelin"],
            "required_terms": [],
            "avoid_terms": [],
        },
        "budget": {
            "aliases": ["budget", "cheap", "affordable"],
            "filters": {},
            "search_terms": ["budget", "affordable"],
            "rank_terms": ["budget", "affordable"],
            "required_terms": [],
            "avoid_terms": [],
        },
        "moderate": {
            "aliases": ["moderate", "mid-range", "mid range"],
            "filters": {},
            "search_terms": ["moderate", "mid-range"],
            "rank_terms": ["moderate", "mid-range"],
            "required_terms": [],
            "avoid_terms": [],
        },
    },
    "accessibility": {
        "wheelchair": {
            "aliases": ["wheelchair", "wheelchair-friendly", "accessible", "step-free"],
            "filters": {"accessibility": ["wheelchair-friendly"]},
            "search_terms": ["wheelchair-friendly", "accessible", "step-free"],
            "rank_terms": ["wheelchair-friendly", "accessible", "step-free"],
            "required_terms": ["wheelchair-friendly", "accessible", "step-free"],
            "avoid_terms": [],
        },
    },
}


def _memory_text_for_matching(memory: dict) -> str:
    return " ".join([
        str(memory.get("text") or memory.get("content") or memory.get("value") or ""),
        json.dumps(memory.get("facets") or {}),
    ]).lower().replace("_", " ")


def _merge_filter(filters: dict, key: str, value):
    if key == "priceTier":
        filters[key] = value
        return

    values = value if isinstance(value, list) else [value]
    existing = filters.setdefault(key, [])
    for item in values:
        if item not in existing:
            existing.append(item)


def _preference_profile_from_memories(memories: list[dict]) -> dict:
    profile = {
        "filters": {},
        "search_terms": [],
        "rank_terms": [],
        "required_terms": [],
        "avoid_terms": [],
        "matched_preferences": [],
    }

    for memory in memories:
        memory_text = _memory_text_for_matching(memory)
        for category, preferences in PREFERENCE_TAXONOMY.items():
            for canonical, spec in preferences.items():
                if not any(alias in memory_text for alias in spec["aliases"]):
                    continue

                profile["matched_preferences"].append(f"{category}:{canonical}")
                for filter_key, filter_value in spec["filters"].items():
                    _merge_filter(profile["filters"], filter_key, filter_value)
                for key in ["search_terms", "rank_terms", "required_terms", "avoid_terms"]:
                    for term in spec[key]:
                        if term not in profile[key]:
                            profile[key].append(term)

    return profile


def _place_searchable_text(place: dict) -> str:
    return " ".join([
        str(place.get("name") or ""),
        str(place.get("description") or ""),
        " ".join(str(tag) for tag in place.get("tags") or []),
        " ".join(str(item) for item in place.get("dietary") or []),
        " ".join(str(item) for item in place.get("accessibility") or []),
        str(place.get("priceTier") or ""),
    ]).lower()


def _filter_places_by_required_memory(places: list[dict], profile: dict, minimum_results: int = 3) -> list[dict]:
    required_terms = profile.get("required_terms") or []
    if not required_terms:
        return places

    aligned = [
        place for place in places
        if any(term in _place_searchable_text(place) for term in required_terms)
    ]
    return aligned if len(aligned) >= minimum_results else places


def _rank_places_by_memory(places: list[dict], profile: dict) -> list[dict]:
    rank_terms = profile.get("rank_terms") or []
    avoid_terms = profile.get("avoid_terms") or []
    if not rank_terms and not avoid_terms:
        return places

    def score(place: dict) -> tuple[float, float]:
        searchable_text = _place_searchable_text(place)
        memory_score = sum(2 for keyword in rank_terms if keyword in searchable_text)
        memory_score -= sum(1 for keyword in avoid_terms if keyword in searchable_text)
        rating = float(place.get("rating") or 0)
        return (memory_score, rating)

    return sorted(places, key=score, reverse=True)


def _place_memory_matches(place: dict, profile: dict) -> list[str]:
    searchable_text = _place_searchable_text(place)
    matches = [
        term for term in profile.get("rank_terms", [])
        if term in searchable_text
    ]
    return matches[:3]


def _format_places_response(agent_label: str, place_type: str, geo_scope: str, places: list[dict], memories: list[dict], preference_profile: dict | None = None, memory_error: str | None = None) -> str:
    city = geo_scope.replace("-", " ").title()
    noun = {
        "hotel": "hotels",
        "restaurant": "restaurants",
        "attraction": "activities",
    }.get(place_type, "places")

    if not places:
        return f"I checked your saved preferences first, but I could not find matching {noun} in {city}."

    if memory_error:
        intro = f"I tried to check your saved preferences first, but that lookup failed ({memory_error}). I still found these {noun} in {city}:"
    elif memories:
        intro = f"I checked your saved preferences first and found {len(memories)} relevant preference(s). Based on those, here are good {noun} in {city}:"
    else:
        intro = f"I checked your saved preferences first and did not find anything relevant, so I used general quality signals for {city}:"

    lines = [intro]
    for index, place in enumerate(places[:3], start=1):
        name = place.get("name", "Unnamed place")
        rating = place.get("rating")
        neighborhood = place.get("neighborhood")
        price = place.get("priceTier")
        description = place.get("description", "")
        details = []
        if neighborhood:
            details.append(str(neighborhood))
        if rating:
            details.append(f"rating {rating}")
        if price:
            details.append(str(price))
        memory_matches = _place_memory_matches(place, preference_profile or {})
        if memory_matches:
            details.append(f"matches {', '.join(memory_matches)}")
        suffix = f" ({', '.join(details)})" if details else ""
        lines.append(f"{index}. {name}{suffix} — {description}")

    return "\n".join(lines)


async def _memory_first_recommendations(state: MessagesState, config, agent_label: str, place_type: str) -> dict:
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    user_message = _latest_user_text(state)
    geo_scope = _extract_geo_scope(user_message)
    if not geo_scope:
        response_text = "Which city should I use for these recommendations?"
        latest_user_message = _latest_user_message(state)
        messages = [AIMessage(content=response_text, name=agent_label)]
        if latest_user_message:
            messages.insert(0, latest_user_message)
        return {"messages": messages}

    query = f"{place_type} recommendations in {geo_scope.replace('-', ' ')}"

    memories = []
    memory_error = None
    try:
        memories = await asyncio.wait_for(
            asyncio.to_thread(
                get_all_user_memories,
                user_id=user_id,
                tenant_id=tenant_id,
            ),
            timeout=10,
        )
    except Exception as exc:
        memory_error = repr(exc)
        logger.error(f"{agent_label} memory recall failed: {repr(exc)}")

    # Apply durable memories plus explicit constraints from this turn.
    preference_profile = _preference_profile_from_memories(memories + [{"text": user_message}])
    filters = preference_profile["filters"]
    filters["type"] = place_type
    memory_keywords = preference_profile["search_terms"]
    search_query = " ".join(memory_keywords + [query]) if memory_keywords else query

    places = []
    try:
        places = await asyncio.wait_for(
            asyncio.to_thread(
                query_places_hybrid,
                query=search_query,
                geo_scope_id=geo_scope,
                place_type=place_type,
                dietary=filters.get("dietary"),
                accessibility=filters.get("accessibility"),
                price_tier=None,
                limit=10,
            ),
            timeout=25,
        )
    except Exception as exc:
        logger.error(f"{agent_label} hybrid discovery failed; falling back to filtered search: {repr(exc)}")

    if not places:
        places = query_places_filtered(
            geo_scope_id=geo_scope,
            place_type=place_type,
            dietary=filters.get("dietary"),
            accessibility=filters.get("accessibility"),
            price_tier=None,
        )[:10]

    places = _filter_places_by_required_memory(places, preference_profile)
    places = _rank_places_by_memory(places, preference_profile)

    response_text = _format_places_response(agent_label, place_type, geo_scope, places, memories, preference_profile, memory_error)
    latest_user_message = _latest_user_message(state)
    messages = [AIMessage(content=response_text, name=agent_label)]
    if latest_user_message:
        messages.insert(0, latest_user_message)

    return {
        "messages": messages
    }


async def setup_agents():
    """
    Initialize all agents with their respective MCP tools.
    This creates a persistent MCP session and loads domain-aware tools.
    
    Agent Structure:
    - Orchestrator: Entry point, routes to specialized agents
    - Hotel Agent: Deterministic memory-first accommodation recommendations
    - Activity Agent: Deterministic memory-first attraction recommendations
    - Dining Agent: Deterministic memory-first restaurant recommendations
    - Itinerary Generator: Synthesizes all results into day-by-day plan
    - Summarizer: Compresses conversation history (auto-triggered every 10 turns)
    """
    global orchestrator_agent, itinerary_generator_agent, summarizer_agent
    global _mcp_client, _session_context, _persistent_session
    
    logger.info("🚀 Starting Travel Assistant MCP client...")
    
    # Load authentication configuration
    try:
        simple_token = os.getenv("MCP_AUTH_TOKEN")
        github_client_id = os.getenv("GITHUB_CLIENT_ID")
        github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")
        
        logger.info("🔐 Client Authentication Configuration:")
        logger.info(f"   Simple Token: {'SET' if simple_token else 'NOT SET'}")
        logger.info(f"   GitHub OAuth: {'SET' if github_client_id and github_client_secret else 'NOT SET'}")
        
        # Determine authentication mode
        if github_client_id and github_client_secret:
            auth_mode = "github_oauth"
            logger.info("   Mode: GitHub OAuth (Production)")
        elif simple_token:
            auth_mode = "simple_token" 
            logger.info(f"   Mode: Simple Token (Development)")
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
    client_config = {
        "travel_tools": {
            "transport": "streamable_http",
            "url": os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8080") + "/mcp/",
        }
    }
    
    # Add authentication if configured
    if auth_mode == "simple_token" and simple_token:
        client_config["travel_tools"]["headers"] = {
            "Authorization": f"Bearer {simple_token}"
        }
        logger.info("🔐 Added Bearer token authentication to client")
    elif auth_mode == "github_oauth":
        client_config["travel_tools"]["auth"] = "oauth"
        logger.info("🔐 Enabled OAuth authentication for client")
    
    _mcp_client = MultiServerMCPClient(client_config)
    logger.info("✅ MCP Client initialized successfully")
    
    # Create persistent session
    _session_context = _mcp_client.session("travel_tools")
    _persistent_session = await _session_context.__aenter__()
    
    # Load all MCP tools
    all_tools = await load_mcp_tools(_persistent_session)
    
    logger.info("[DEBUG] All tools registered from Travel Assistant MCP server:")
    for tool in all_tools:
        logger.info(f"  - {tool.name}")
    
    # ========================================================================
    # Tool Distribution for Specialized Agents
    # ========================================================================
    
    # Orchestrator: Session management + memory tools + all transfer tools
    orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "create_session", "get_session_context", "append_turn",
        "recall_memories", "extract_preferences_from_message", "resolve_memory_conflicts", "store_resolved_preferences",
        "transfer_to_"  # All transfer tools
    ])

    itinerary_generator_tools = filter_tools_by_prefix(all_tools, [
        "create_new_trip", "update_trip", "get_trip_details",
        "transfer_to_orchestrator"
    ])

    summarizer_tools = filter_tools_by_prefix(all_tools, [
        "get_summarizable_span", "mark_span_summarized", "get_session_context",
        "get_all_user_summaries",  # Query all summaries for the user
        "transfer_to_orchestrator"
    ])
    
    logger.info(f"\n📊 Tool Distribution:")
    logger.info(f"   Orchestrator: {len(orchestrator_tools)} tools")
    logger.info("   Hotel/Activity/Dining: deterministic memory-first service nodes")
    logger.info(f"   Itinerary Generator: {len(itinerary_generator_tools)} tools")
    logger.info(f"   Summarizer: {len(summarizer_tools)} tools")
    
    # Create agents with their tools
    orchestrator_agent = create_react_agent(
        model, 
        orchestrator_tools, 
        state_modifier=load_prompt("orchestrator")
    )
    
    itinerary_generator_agent = create_react_agent(
        model,
        itinerary_generator_tools,
        state_modifier=load_prompt("itinerary_generator")
    )
    
    summarizer_agent = create_react_agent(
        model,
        summarizer_tools,
        state_modifier=load_prompt("summarizer")
    )
    
    logger.info("✅ All agents created successfully\n")


async def cleanup_persistent_session():
    """Clean up the persistent MCP session when the application shuts down"""
    global _session_context, _persistent_session
    
    if _session_context is not None and _persistent_session is not None:
        try:
            await _session_context.__aexit__(None, None, None)
            logger.info("✅ MCP persistent session cleaned up successfully")
        except Exception as e:
            logger.error(f"Error cleaning up MCP session: {e}")


# ============================================================================
# Helper: Store Message in Database at Every Turn
# ============================================================================

# ============================================================================
# Agent Node Functions
# ============================================================================

@traceable(run_type="llm")
async def call_orchestrator_agent(state: MessagesState, config) -> Command[Literal["orchestrator", "hotel", "activity", "dining", "itinerary_generator", "summarizer", "human"]]:
    """
    Orchestrator agent: Routes requests using transfer_to_ tools.
    Checks for active agent and routes directly if found.
    Stores every message in database.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info(f"🎯 Calling orchestrator agent with Thread: {thread_id}, User: {user_id}, Tenant: {tenant_id}")
    
    # Check for active agent in database
    try:
        logging.info(f"Looking up active agent for thread {thread_id}")
        session_doc = sessions_container.read_item(
            item=thread_id,
            partition_key=[tenant_id, user_id, thread_id]
        )
        activeAgent = session_doc.get('activeAgent', 'unknown')
    except Exception as e:
        logger.debug(f"No active agent found: {e}")
        activeAgent = None
    
    # Initialize session if needed (for local testing)
    if activeAgent is None:
        update_session_container({
            "id": thread_id,
            "sessionId": thread_id,
            "tenantId": tenant_id,
            "userId": user_id,
            "title": "New Conversation",
            "createdAt": datetime.now(UTC).isoformat(),
            "lastActivityAt": datetime.now(UTC).isoformat(),
            "status": "active",
            "messageCount": 0
        })
    
    logger.info(f"Active agent from DB: {activeAgent}")

    deterministic_destination = _deterministic_specialist_route(_latest_user_text(state))
    if deterministic_destination:
        logger.info(f"🎯 Orchestrator deterministically routing to {deterministic_destination}")
        return Command(update={}, goto=deterministic_destination)
    
    # Always call orchestrator to analyze the message and decide routing
    # Don't blindly route to the last active agent - user's request may have changed
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))
    response = await orchestrator_agent.ainvoke(state, config)

    destination = _extract_transfer_destination(response)
    if destination and destination != "orchestrator":
        logger.info(f"🎯 Orchestrator transferring to {destination}")
        return Command(update=response, goto=destination)

    return Command(update=response, goto="human")


@traceable(run_type="chain")
async def call_hotel_agent(state: MessagesState, config) -> Command[Literal["hotel", "itinerary_generator", "orchestrator", "human"]]:
    """
    Hotel Agent: Searches accommodations and stores hotel preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("🏨 ========== HOTEL AGENT CALLED ==========")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "hotel_agent")

    logger.info(f"🏨 Running memory-first hotel recommendations...")
    response = await _memory_first_recommendations(state, config, "Hotel", "hotel")
    
    logger.info(f"🏨 ========== HOTEL AGENT COMPLETED ==========")
    return Command(update=response, goto="human")


@traceable(run_type="chain")
async def call_activity_agent(state: MessagesState, config) -> Command[Literal["activity", "itinerary_generator", "orchestrator", "human"]]:
    """
    Activity Agent: Searches attractions and stores activity preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("🎭 Activity Agent searching attractions...")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "activity_agent")
    
    response = await _memory_first_recommendations(state, config, "Activity", "attraction")
    
    return Command(update=response, goto="human")


@traceable(run_type="chain")
async def call_dining_agent(state: MessagesState, config) -> Command[Literal["dining", "itinerary_generator", "orchestrator", "human"]]:
    """
    Dining Agent: Searches restaurants and stores dining preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("🍽️  Dining Agent searching restaurants...")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "dining_agent")
    
    response = await _memory_first_recommendations(state, config, "Dining", "restaurant")
    
    return Command(update=response, goto="human")


@traceable(run_type="llm")
async def call_itinerary_generator_agent(state: MessagesState, config) -> Command[Literal["itinerary_generator", "orchestrator", "human"]]:
    """
    Itinerary Generator: Synthesizes all gathered info into day-by-day plan.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("📋 Itinerary Generator synthesizing plan...")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "itinerary_generator_agent")
    
    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))
    
    response = await itinerary_generator_agent.ainvoke(state, config)
    
    # Remove system message
    if isinstance(response, dict) and "messages" in response:
        response["messages"] = [
            msg for msg in response["messages"]
            if not isinstance(msg, SystemMessage)
        ]
    
    return Command(update=response, goto="human")


@traceable(run_type="llm")
async def call_summarizer_agent(state: MessagesState, config) -> Command[Literal["summarizer", "orchestrator", "human"]]:
    """
    Summarizer agent: Compresses conversation history.
    Auto-triggered every 10 turns.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("📝 Summarizer compressing conversation...")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "summarizer_agent")
    
    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', thread_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))
    
    response = await summarizer_agent.ainvoke(state, config)
    
    # Remove system message
    if isinstance(response, dict) and "messages" in response:
        response["messages"] = [
            msg for msg in response["messages"]
            if not isinstance(msg, SystemMessage)
        ]
    
    return Command(update=response, goto="human")


@traceable
def human_node(state: MessagesState, config) -> None:
    """
    Human node: Interrupts for user input in interactive mode.
    """
    interrupt(value="Ready for user input.")
    return None


def should_summarize(state: MessagesState, config) -> bool:
    """
    Check if conversation should be summarized based on message count.
    Returns True if there are 10+ messages and no recent summarization.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID") 
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    # Count messages in current state (approximate)
    message_count = len(state.get("messages", []))
    
    # If we have 10+ messages, check if we need summarization
    if message_count >= 10:
        try:
            # Get actual count from DB (non-superseded, non-summary messages only)
            actual_count = count_active_messages(
                session_id=thread_id,
                tenant_id=tenant_id,
                user_id=user_id
            )
            
            # Trigger summarization every 10 messages
            if actual_count >= 10 and actual_count % 10 == 0:
                logger.info(f"🎯 Auto-triggering summarization at {actual_count} messages")
                return True
                        
        except Exception as e:
            logger.error(f"Error checking message count for summarization: {e}")
    
    return False


def get_active_agent(state: MessagesState, config) -> str:
    """
    Extract active agent from ToolMessage or fallback to Cosmos DB.
    This is used by the router to determine which specialized agent to call.
    Also checks if auto-summarization should be triggered.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    # **CHECK FOR AUTO-SUMMARIZATION FIRST**
    if should_summarize(state, config):
        logger.info("🤖 Auto-routing to summarizer (10+ messages)")
        return "summarizer"
    
    activeAgent = None
    
    # Search for last ToolMessage and try to extract `goto`
    for message in reversed(state['messages']):
        if isinstance(message, AIMessage):
            for tool_call in message.additional_kwargs.get("tool_calls", []):
                function_name = tool_call.get("function", {}).get("name", "")
                if function_name.startswith("transfer_to_"):
                    activeAgent = function_name.replace("transfer_to_", "")
                    logger.info(f"🎯 Extracted activeAgent from AI tool call: {activeAgent}")
                    break
            if activeAgent:
                break

        if isinstance(message, ToolMessage):
            try:
                content_json = json.loads(message.content)
                activeAgent = content_json.get("goto")
                if activeAgent:
                    logger.info(f"🎯 Extracted activeAgent from ToolMessage: {activeAgent}")
                    break
            except Exception as e:
                logger.debug(f"Failed to parse ToolMessage content: {e}")
    
    # Fallback: Cosmos DB lookup if needed
    if not activeAgent:
        try:
            session_doc = sessions_container.read_item(
                item=thread_id,
                partition_key=[tenant_id, user_id, thread_id]
            )
            activeAgent = session_doc.get('activeAgent', 'unknown')
            logger.info(f"Active agent from DB: {activeAgent}")
        except Exception as e:
            logger.error(f"Error retrieving active agent from DB: {e}")
            activeAgent = "unknown"
    
    # If activeAgent is unknown or None, default to orchestrator
    if activeAgent in [None, "unknown"]:
        logger.info(f"� activeAgent is '{activeAgent}', defaulting to Orchestrator")
        activeAgent = "orchestrator"
    
    return activeAgent


# ============================================================================
# Build Agent Graph
# ============================================================================

def build_agent_graph():
    """
    Build the multi-agent graph using LangGraph.
    
    Graph structure:
    - User input → Orchestrator (entry point)
    - Orchestrator routes via transfer_to_ tools or deterministic domain routing
    - Specialized agents (Hotel, Activity, Dining) answer the turn and return to user
    - Itinerary Generator → Orchestrator only
    - Summarizer → Orchestrator only (auto-triggered every 10 turns)
    - All agents → Human node (for user interrupts)
    """
    logger.info("🏗️  Building multi-agent graph...")
    
    builder = StateGraph(MessagesState)
    
    # Add all agent nodes
    builder.add_node("orchestrator", call_orchestrator_agent)
    builder.add_node("hotel", call_hotel_agent)
    builder.add_node("activity", call_activity_agent)
    builder.add_node("dining", call_dining_agent)
    builder.add_node("itinerary_generator", call_itinerary_generator_agent)
    builder.add_node("summarizer", call_summarizer_agent)
    builder.add_node("human", human_node)
    
    # Set entry point - always start with orchestrator
    builder.add_edge(START, "orchestrator")
    
    # Orchestrator routing - can route to any specialized agent
    builder.add_conditional_edges(
        "orchestrator",
        get_active_agent,
        {
            "hotel": "hotel",
            "activity": "activity",
            "dining": "dining",
            "itinerary_generator": "itinerary_generator",
            "summarizer": "summarizer",
            "human": "human",  # Wait for user input
            "orchestrator": "orchestrator",  # fallback
        }
    )
    
    # Specialist agents answer the current user turn, then return control to the user.
    # The next user turn starts at the orchestrator again, avoiding loops through
    # stale session activeAgent values after non-routing tools like recall_memories.
    builder.add_edge("hotel", "human")
    builder.add_edge("activity", "human")
    builder.add_edge("dining", "human")
    builder.add_edge("itinerary_generator", "human")
    
    # Summarizer routing - can only return to orchestrator
    builder.add_conditional_edges(
        "summarizer",
        get_active_agent,
        {
            "orchestrator": "orchestrator",
            "summarizer": "summarizer",  # Can stay in summarizer
        }
    )
    
    # Compile with checkpointer
    checkpointer = CosmosDBSaver(
        database_name=DATABASE_NAME,
        container_name=checkpoint_container
    )

    graph = builder.compile(checkpointer=checkpointer)
    
    logger.info("✅ Multi-agent graph built successfully")
    logger.info("📊 Graph structure:")
    logger.info("   Entry: User → Orchestrator")
    logger.info("   Orchestrator → Hotel/Activity/Dining/Itinerary/Summarizer")
    logger.info("   Hotel/Activity/Dining → Itinerary Generator or Orchestrator")
    logger.info("   Itinerary Generator → Orchestrator only")
    logger.info("   Summarizer → Orchestrator only (auto-triggered every 10 messages)")
    logger.info("   Agents: 6 total (Orchestrator, Hotel, Activity, Dining, Itinerary Generator, Summarizer)")
    
    return graph


# ============================================================================
# Interactive Chat Function (for CLI testing)
# ============================================================================

async def interactive_chat():
    """
    Interactive CLI for testing the travel assistant.
    Similar to banking app's interactive mode.
    """
    global local_interactive_mode
    local_interactive_mode = True
    
    thread_id = str(uuid.uuid4())
    # thread_id = "thread-7ab201e9-2bbc-41cc-a220-995558523a4f"
    thread_config = {
        "configurable": {
            "thread_id": thread_id,
            "userId": "Tony",
            "tenantId": "Marvel"
        }
    }
    
    print("\n" + "="*70)
    print("🌍 Travel Assistant - Interactive Test Mode")
    print("="*70)
    print("Type 'exit' to end the conversation")
    print("="*70 + "\n")
    
    # Build graph
    graph = build_agent_graph()
    
    user_input = input("You: ")
    
    while user_input.lower() != "exit":
        input_message = {"messages": [{"role": "user", "content": user_input}]}
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
    # Setup agents and run interactive chat
    async def main():
        await setup_agents()
        await interactive_chat()
    
    asyncio.run(main())

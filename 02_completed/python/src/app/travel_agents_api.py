import os
import sys
import uuid
import asyncio
import json
from pathlib import Path

# Ensure stdout/stderr use UTF-8 so emoji in logs/prints don't crash on Windows,
# where the console defaults to cp1252 and raises UnicodeEncodeError on emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import fastapi
from dotenv import load_dotenv
from datetime import datetime
from fastapi import BackgroundTasks, HTTPException, Body, Response
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from pydantic import BaseModel
from typing import List, Dict, Optional, Any, AsyncIterator
from enum import Enum
from starlette.middleware.cors import CORSMiddleware
from azure.cosmos.exceptions import CosmosHttpResponseError
import traceback

import logging

# Add project root to path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load environment variables with explicit path
current_file = Path(__file__)
python_dir = current_file.parent.parent.parent
env_file = python_dir / '.env'

if env_file.exists():
    load_dotenv(dotenv_path=env_file, override=False)
    print(f"✅ Loaded .env from: {env_file}")
else:
    print(f"⚠️  .env file not found at: {env_file}, trying default locations")
    load_dotenv(override=False)

from src.app.services.azure_open_ai import model, generate_embedding
from src.app.services.azure_cosmos_db import (
    sessions_container, messages_container, trips_container,
    places_container, debug_logs_container,
    aget_checkpoint_saver, close_async_cosmos_client, adelete_checkpoints_for_thread,
    create_session_record, get_session_by_id,
    append_message, get_session_messages, query_places_hybrid,
    get_trip, query_places_with_theme, query_places_filtered,
    patch_active_agent, update_session_activity,
    create_user, get_all_users, get_user_by_id,
    store_debug_log, get_debug_log, query_debug_logs
)
from src.app.travel_agents import (
    setup_agents,
    build_agent_graph,
    cleanup_persistent_session,
    _current_user_preference_vector,
)
from src.app.services.agent_memory import get_memory_client

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Quiet down chatty libraries so the workshop logs stay readable
for noisy in (
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.identity",
    "azure.cosmos",
    "httpx",
    "httpcore",
    "mcp",
    "sse_starlette.sse",
    "openai._base_client",
    "urllib3.connectionpool",
    "langsmith.client",
):
    logging.getLogger(noisy).setLevel(logging.WARNING)

# Load environment variables
load_dotenv(override=False)

# Configure Azure Monitor for telemetry
# configure_azure_monitor()

# Tag categories for Swagger UI organization
SESSION_TAG = "Session Management"
CHAT_TAG = "Chat Completion"
TRIP_TAG = "Trip Management"
MEMORY_TAG = "Memory Management"
PLACES_TAG = "Places Discovery"
DEBUG_TAG = "Debug & Analytics"


# ============================================================================
# Pydantic Models
# ============================================================================

class Session(BaseModel):
    id: str
    sessionId: str
    tenantId: str
    userId: str
    title: str = "New Conversation"
    createdAt: str
    lastActivityAt: str
    activeAgent: str = "unknown"
    messageCount: int = 0


class MessageModel(BaseModel):
    id: str
    type: str = "message"
    sessionId: str
    tenantId: str
    userId: str
    timeStamp: str
    sender: str  # "User" | "Orchestrator" | "Hotel" | "Dining" | "Activity" | "Itinerary" | "Summarizer"
    senderRole: str  # "User" | "Assistant"
    text: str
    debugLogId: str
    tokensUsed: int = 0
    rating: Optional[bool] = None


class TripStatus(str, Enum):
    PLANNING = "planning"
    BOOKED = "booked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Trip(BaseModel):
    id: str
    tripId: str
    userId: str
    tenantId: str
    destination: str  # "Paris, France"
    startDate: str  # "2025-11-15"
    endDate: str  # "2025-11-19"
    tripDuration: Optional[int] = None
    days: List[Dict] = []  # Day-by-day itinerary
    status: str = TripStatus.PLANNING
    createdAt: Optional[str] = None


class Memory(BaseModel):
    id: str
    user_id: str
    thread_id: Optional[str] = None
    role: Optional[str] = None
    type: str
    content: str
    metadata: Dict[str, Any] = {}
    created_at: Optional[str] = None
    tags: List[str] = []
    salience: Optional[float] = None


class PlaceType(str, Enum):
    HOTEL = "hotel"
    RESTAURANT = "restaurant"
    ATTRACTION = "attraction"
    CAFE = "cafe"


class Place(BaseModel):
    id: str
    geoScopeId: str
    name: str
    type: str  # "hotel" | "restaurant" | "attraction"
    description: str
    neighborhood: str = None
    priceTier: str
    rating: float
    tags: List[str]
    accessibility: List[str]
    hours: Optional[Dict[str, str]] = None
    # Type-specific fields
    hotelSpecific: Optional[Dict] = None
    restaurantSpecific: Optional[Dict] = None
    activitySpecific: Optional[Dict] = None


class DebugLog(BaseModel):
    id: str
    messageId: str
    type: str = "debug_log"
    sessionId: str
    tenantId: str
    userId: str
    timeStamp: str
    propertyBag: List[Dict[str, Any]]


class PlaceSearchRequest(BaseModel):
    geoScope: str
    query: str
    userId: str
    tenantId: str = ""
    filters: Optional[Dict[str, Any]] = None


class PlaceFilterRequest(BaseModel):
    city: str
    theme: Optional[str] = None  # NEW: Theme for semantic search
    types: Optional[List[str]] = None
    priceTiers: Optional[List[str]] = None
    dietary: Optional[List[str]] = None
    accessibility: Optional[List[str]] = None


class User(BaseModel):
    id: str
    userId: str
    tenantId: str
    name: str
    gender: Optional[str] = None
    age: Optional[int] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    email: Optional[str] = None
    createdAt: str


class CreateUserRequest(BaseModel):
    userId: str
    tenantId: str
    name: str
    gender: Optional[str] = None
    age: Optional[int] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, Any]] = None
    email: Optional[str] = None


# ============================================================================
# FastAPI App Setup
# ============================================================================

app = fastapi.FastAPI(
    title="Travel Assistant Multi-Agent API",
    description="""
    # Travel Assistant API
    
    A multi-agent AI system for personalized travel planning powered by Azure Cosmos DB and Azure OpenAI.
    
    ## Features
    - **Specialized Agents**: Orchestrator, Hotel, Activity, Dining, Itinerary Generator, Summarizer
    - **Memory System**: Stores and recalls user preferences (dietary, budget, accessibility)
    - **Place Discovery**: Vector search across hotels, restaurants, and attractions
    - **Trip Management**: Create, update, and manage day-by-day itineraries
    - **Conversation Threading**: Multi-turn conversations with context preservation
    
    ## Agent Flow
    1. **Orchestrator** - Routes user requests to specialized agents
    2. **Hotel/Activity/Dining** - Search places and store preferences
    3. **Itinerary Generator** - Synthesizes selections into day-by-day plans
    4. **Summarizer** - Compresses conversation history (auto-triggered)
    
    ## Authentication
    Use `tenantId` and `userId` to scope conversations and data.
    """,
    version="1.0.0",
    openapi_url="/travel-assistant-api.json",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Global flag to track agent initialization
_agents_initialized = False
_init_lock = asyncio.Lock()
_graph = None
_checkpointer = None
_background_tasks: set[asyncio.Task] = set()

# Agent name mapping (for consistent display)
agent_mapping = {
    "orchestrator": "Orchestrator",
    "hotel": "Hotel",
    "activity": "Activity",
    "dining": "Dining",
    "itinerary_generator": "Itinerary",
}


@app.on_event("startup")
async def initialize_agents():
    """Initialize agents with retry logic to handle MCP server startup timing"""
    global _agents_initialized, _graph, _checkpointer

    logger.info("🚀 Starting agent initialization with retry logic...")

    max_retries = 5
    retry_delay = 10  # seconds

    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries}: Initializing agents...")
            _checkpointer = await aget_checkpoint_saver()
            await setup_agents(checkpointer=_checkpointer)
            _graph = build_agent_graph()
            _agents_initialized = True
            logger.info("✅ Agents initialized successfully!")
            return
        except Exception as e:
            logger.error(f"❌ Failed to initialize agents (attempt {attempt + 1}/{max_retries}): {e}")
            logger.error(f"❌ Exception type: {type(e).__name__}")
            logger.error(f"❌ Full traceback:")
            logger.error(traceback.format_exc())
            
            # If it's a TaskGroup exception, try to extract sub-exceptions
            if hasattr(e, '__cause__'):
                logger.error(f"❌ Underlying cause: {e.__cause__}")
            if hasattr(e, '__context__'):
                logger.error(f"❌ Exception context: {e.__context__}")
            
            # ExceptionGroup (Python 3.11+) stores sub-exceptions in .exceptions attribute
            if hasattr(e, 'exceptions'):
                logger.error(f"❌ TaskGroup contained {len(e.exceptions)} sub-exception(s):")
                for idx, sub_exc in enumerate(e.exceptions, 1):
                    logger.error(f"\n   --- Sub-exception #{idx} ---")
                    logger.error(f"   Type: {type(sub_exc).__name__}")
                    logger.error(f"   Message: {sub_exc}")
                    logger.error(f"   Traceback:")
                    sub_tb = ''.join(traceback.format_exception(type(sub_exc), sub_exc, sub_exc.__traceback__))
                    for line in sub_tb.split('\n'):
                        logger.error(f"   {line}")
            
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("❌ All retry attempts failed. Service will start but agents won't be available.")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup resources on shutdown"""
    logger.info("🛑 Shutting down Travel Assistant API...")
    await cleanup_persistent_session()
    await close_async_cosmos_client()
    logger.info("✅ Cleanup complete")


async def ensure_agents_initialized():
    """Ensure agents are initialized before handling requests"""
    global _agents_initialized

    if _agents_initialized:
        return

    async with _init_lock:
        if _agents_initialized:
            return
        logger.info("🔄 Initializing agents on demand...")
        try:
            global _graph, _checkpointer
            _checkpointer = await aget_checkpoint_saver()
            await setup_agents(checkpointer=_checkpointer)
            _graph = build_agent_graph()
            _agents_initialized = True
            logger.info("✅ Agents initialized successfully!")
        except Exception as e:
            logger.error(f"❌ Failed to initialize agents: {e}")
            raise HTTPException(
                status_code=503,
                detail="MCP service unavailable. Please try again in a few moments."
            )


def get_compiled_graph():
    """Dependency injection for the compiled graph"""
    if not _agents_initialized or _graph is None:
        raise HTTPException(
            status_code=503,
            detail="Agents not initialized. Please wait for service startup to complete."
        )
    return _graph


def trim_history(messages: list, keep_pairs: int = 10) -> list:
    pairs = []
    current = []
    for message in messages:
        current.append(message)
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            pairs.append(current)
            current = []
    kept = pairs[-keep_pairs:]
    return [message for pair in kept for message in pair]


def _message_content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _last_ai_text_from_value(value: Any) -> str:
    if isinstance(value, AIMessage):
        return _message_content_to_text(value.content).strip()
    if isinstance(value, dict):
        messages = value.get("messages")
        if isinstance(messages, list):
            for message in reversed(messages):
                text = _last_ai_text_from_value(message)
                if text:
                    return text
        for item in value.values():
            text = _last_ai_text_from_value(item)
            if text:
                return text
    if isinstance(value, list):
        for item in reversed(value):
            text = _last_ai_text_from_value(item)
            if text:
                return text
    return ""


# ---------------------------------------------------------------------------
# Debug-log capture (analytics)
#
# v2 streams graph *events* (astream_events) rather than raw node-keyed chunks,
# so token/agent/tool telemetry is captured here from the event stream and
# persisted to the Cosmos `Debug` container via store_debug_log — restoring the
# token / agent-selection / cost analytics pillars on the supervisor architecture.
# ---------------------------------------------------------------------------

# Graph nodes that represent agents (for agent_path / agent_selected).
_AGENT_NODES = ("supervisor", "find_places", "create_or_update_itinerary", "itinerary_agent")
# Sub-agents the supervisor delegates to (everything except the supervisor itself).
_SUBAGENT_NODES = ("find_places", "create_or_update_itinerary", "itinerary_agent")


def _extract_msg_usage(msg: Any) -> Optional[Dict[str, Any]]:
    """Pull token usage + model metadata from an AIMessage.

    Handles both langchain-core 1.x native ``usage_metadata`` and the
    OpenAI-style nested ``response_metadata.token_usage``. Returns None when the
    message carries no usage (e.g. a streamed delta chunk).
    """
    if msg is None:
        return None

    input_t = output_t = total_t = cached_t = 0
    model_name = finish_reason = system_fingerprint = "Unknown"

    usage = getattr(msg, "usage_metadata", None)
    if isinstance(usage, dict):
        input_t = usage.get("input_tokens", 0) or 0
        output_t = usage.get("output_tokens", 0) or 0
        total_t = usage.get("total_tokens", 0) or 0
        details = usage.get("input_token_details") or {}
        cached_t = details.get("cache_read", 0) or 0

    metadata = getattr(msg, "response_metadata", None)
    if isinstance(metadata, dict):
        model_name = metadata.get("model_name", model_name)
        finish_reason = metadata.get("finish_reason", finish_reason)
        system_fingerprint = metadata.get("system_fingerprint", system_fingerprint)
        token_usage = metadata.get("token_usage") or {}
        if not total_t:
            input_t = token_usage.get("prompt_tokens", input_t) or input_t
            output_t = token_usage.get("completion_tokens", output_t) or output_t
            total_t = token_usage.get("total_tokens", total_t) or total_t
            prompt_details = token_usage.get("prompt_tokens_details") or {}
            cached_t = prompt_details.get("cached_tokens", cached_t) or cached_t

    if not (input_t or output_t or total_t):
        return None

    return {
        "input_tokens": input_t,
        "output_tokens": output_t,
        "total_tokens": total_t,
        "cached_tokens": cached_t,
        "model_name": model_name,
        "finish_reason": finish_reason,
        "system_fingerprint": system_fingerprint,
    }


def _persist_turn_debug_log(
    tenant_id: str,
    user_id: str,
    thread_id: str,
    debug_log_id: str,
    dbg: Dict[str, Any],
) -> None:
    """Store a Debug-container log for one completed turn from captured event signal."""
    nodes = dbg.get("nodes", [])
    tools = dbg.get("tools", [])

    # In v2's supervisor architecture the sub-agents (find_places,
    # create_or_update_itinerary) are invoked as *tools*, not graph nodes, so
    # delegations are derived from tool calls. Any that also surface as chain
    # nodes are included too (belt-and-suspenders across graph shapes).
    tool_names = [t.get("name") for t in tools if isinstance(t, dict)]
    delegations = [name for name in tool_names if name in _SUBAGENT_NODES]
    delegations += [node for node in nodes if node in _SUBAGENT_NODES and node not in delegations]

    agent_selected = delegations[-1] if delegations else "supervisor"
    handoff_count = len(delegations)
    agent_path = ",".join(["supervisor", *delegations]) if delegations else "supervisor"

    try:
        store_debug_log(
            session_id=thread_id,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_selected=agent_selected,
            previous_agent="supervisor" if delegations else "Unknown",
            finish_reason=dbg.get("finish_reason", "Unknown"),
            model_name=dbg.get("model_name", "Unknown"),
            system_fingerprint=dbg.get("system_fingerprint", "Unknown"),
            input_tokens=dbg.get("input_tokens", 0),
            output_tokens=dbg.get("output_tokens", 0),
            total_tokens=dbg.get("total_tokens", 0),
            cached_tokens=dbg.get("cached_tokens", 0),
            transfer_success=bool(delegations),
            tool_calls=tools,
            agent_path=agent_path,
            handoff_count=handoff_count,
            debug_log_id=debug_log_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(f"❌ Failed to store turn debug log for session {thread_id}: {exc}")


def _extract_checkpoint_messages(checkpoint: Any) -> list:
    checkpoint_data = getattr(checkpoint, "checkpoint", checkpoint)
    if not isinstance(checkpoint_data, dict):
        return []

    messages = checkpoint_data.get("messages")
    if isinstance(messages, list):
        return messages

    channel_values = checkpoint_data.get("channel_values")
    if isinstance(channel_values, dict):
        messages = channel_values.get("messages")
        if isinstance(messages, list):
            return messages

    return []


async def _load_checkpoint_history(config: dict) -> list:
    if _checkpointer is None or not hasattr(_checkpointer, "alist"):
        return []

    try:
        checkpoints = [c async for c in _checkpointer.alist(config)]
    except Exception as exc:
        logger.warning("failed to load checkpoint history for trim: %s", exc)
        return []

    if not checkpoints:
        return []
    return _extract_checkpoint_messages(checkpoints[-1])


async def _fetch_user_preference_vector(client: Any, user_id: str) -> list[float] | None:
    """Fetch the user_summary embedding for preference-vector biasing in discover_places.

    Returns None when the user has no summary yet, the summary lacks an embedding,
    or any error occurs -- preference biasing is best-effort, never a request blocker.
    """
    if not user_id:
        return None
    try:
        summary = await client.get_user_summary(user_id)
    except Exception as exc:
        logger.warning("user_summary lookup failed for user=%s: %s", user_id, exc)
        return None
    if summary is None:
        return None
    if isinstance(summary, list):
        if not summary:
            return None
        summary = summary[0]
    embedding = summary.get("embedding") if isinstance(summary, dict) else None
    return embedding if isinstance(embedding, list) else None


def _thread_config(tenant_id: str, user_id: str, thread_id: str, pref_vector: list[float] | None = None) -> dict:
    configurable = {
        "thread_id": thread_id,
        "checkpoint_ns": "",
        "user_id": user_id,
        "userId": user_id,
        "tenant_id": tenant_id,
        "tenantId": tenant_id,
    }
    if pref_vector is not None:
        configurable["user_preference_vector"] = pref_vector
    return {"configurable": configurable}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def _flush_memory_bg(client: Any, user_id: str, thread_id: str):
    try:
        # Canonical toolkit path: flushes locally-buffered turns to Cosmos AND
        # writes per-(user, thread) counts to the `counter` container, then
        # schedules cadence-driven processing (fact extraction, dedup, thread
        # summary, user summary) per FACT_EXTRACTION_EVERY_N / DEDUP_EVERY_N /
        # THREAD_SUMMARY_EVERY_N / USER_SUMMARY_EVERY_N env vars.
        await client.push_to_cosmos()
    except Exception as exc:
        logger.warning(
            "background memory flush failed for user=%s thread=%s: %s",
            user_id,
            thread_id,
            exc,
        )


def _build_message_model(
    session_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    text: str,
    debug_log_id: str = "",
) -> MessageModel:
    return MessageModel(
        id=str(uuid.uuid4()),
        type="message",
        sessionId=session_id,
        tenantId=tenant_id,
        userId=user_id,
        timeStamp=datetime.utcnow().isoformat(),
        sender="User" if role == "user" else "Assistant",
        senderRole="User" if role == "user" else "Assistant",
        text=text,
        debugLogId=debug_log_id,
        tokensUsed=0,
        rating=None,
    )


def _persist_chat_turn_messages(
    session_id: str,
    tenant_id: str,
    user_id: str,
    user_message: str,
    assistant_message: str,
):
    message_count = 0
    append_message(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        role="user",
        content=user_message,
    )
    message_count += 1
    if assistant_message:
        append_message(
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            role="assistant",
            content=assistant_message,
        )
        message_count += 1
    update_session_activity(session_id, tenant_id, user_id, message_count=message_count)


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Health & Status Endpoints
# ============================================================================

@app.get(
    "/health",
    summary="Health Check",
    description="Basic health check endpoint to verify service is running"
)
def health_check():
    return {
        "status": "healthy",
        "service": "Travel Assistant Multi-Agent API",
        "version": "1.0.0"
    }


@app.get(
    "/health/ready",
    tags=["Health"],
    summary="Readiness Probe",
    description="Readiness probe for container orchestration (checks if agents are initialized)"
)
async def readiness_check():
    """Readiness probe for Container Apps"""
    try:
        if not _agents_initialized:
            return {"status": "not_ready", "agents_initialized": False}
        return {"status": "ready", "agents_initialized": _agents_initialized}
    except Exception:
        return {"status": "not_ready", "agents_initialized": False}


@app.get(
    "/status",
    tags=["Health"],
    summary="Service Status",
    description="Get detailed service status including agent initialization state"
)
def get_service_status():
    return {
        "service": "Travel Assistant API",
        "status": "running" if _agents_initialized else "initializing",
        "agents_initialized": _agents_initialized,
        "cosmos_db": "connected" if sessions_container else "disconnected"
    }


# ============================================================================
# Session Management Endpoints
# ============================================================================

@app.post(
    "/tenant/{tenantId}/user/{userId}/sessions",
    tags=[SESSION_TAG],
    summary="Create New Session",
    description="Create a new conversation session for the user",
    response_model=Session,
    status_code=201
)
def create_chat_session(tenantId: str, userId: str, activeAgent: str, title: str = None):
    """
    Create a new conversation session.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        activeAgent: Active agent name
        title: Optional session title (defaults to "New Conversation")
    
    Returns:
        Session object with sessionId and metadata
    """
    try:
        session = create_session_record(userId, tenantId, activeAgent, title)
        return Session(**session)
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")


@app.get(
    "/tenant/{tenantId}/user/{userId}/sessions",
    tags=[SESSION_TAG],
    summary="List User Sessions",
    description="Retrieve all conversation sessions for a specific user",
    response_model=List[Session]
)
def get_user_sessions(tenantId: str, userId: str):
    """
    Get all conversation sessions for a user.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
    
    Returns:
        List of Session objects with metadata
    """
    try:
        if not sessions_container:
            raise HTTPException(status_code=503, detail="Cosmos DB not available")

        query = """
        SELECT * FROM c 
        WHERE c.tenantId = @tenantId 
        AND c.userId = @userId
        ORDER BY c.lastActivityAt DESC
        """
        
        items = list(sessions_container.query_items(
            query=query,
            parameters=[
                {"name": "@tenantId", "value": tenantId},
                {"name": "@userId", "value": userId}
            ],
            enable_cross_partition_query=True
        ))
        
        return [Session(**item) for item in items]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch sessions: {str(e)}")


@app.get(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/messages",
    tags=[SESSION_TAG],
    summary="Get Session Messages",
    description="Retrieve conversation history for a specific session",
    response_model=List[MessageModel]
)
def get_session_messages_endpoint(tenantId: str, userId: str, sessionId: str):
    """
    Get conversation messages for a session.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        sessionId: Session identifier
    
    Returns:
        List of MessageModel objects in chronological order
    """
    try:
        messages = get_session_messages(sessionId, tenantId, userId)
        
        # Convert to MessageModel format
        return [
            MessageModel(
                id=msg.get("messageId", msg.get("id")),
                type="message",
                sessionId=sessionId,
                tenantId=tenantId,
                userId=userId,
                timeStamp=msg.get("ts", ""),
                sender=msg.get("role", "unknown").title(),
                senderRole="User" if msg.get("role") == "user" else "Assistant",
                text=msg.get("content", ""),
                debugLogId="",
                tokensUsed=0,
                rating=None
            )
            for msg in messages
        ]
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch messages: {str(e)}")


@app.post(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/rename",
    tags=[SESSION_TAG],
    summary="Rename Session",
    description="Update the title of a conversation session",
    response_model=Session
)
def rename_session(tenantId: str, userId: str, sessionId: str, newSessionName: str):
    """
    Rename a conversation session.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        sessionId: Session identifier
        newSessionName: New title for the session
    
    Returns:
        Updated Session object
    """
    try:
        session = get_session_by_id(sessionId, tenantId, userId)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session["title"] = newSessionName
        sessions_container.upsert_item(session)
        
        return Session(**session)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error renaming session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rename session: {str(e)}")


@app.delete(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}",
    tags=[SESSION_TAG],
    summary="Delete Session",
    description="Delete a conversation session and all associated data",
    status_code=200
)
def delete_session(tenantId: str, userId: str, sessionId: str, background_tasks: BackgroundTasks):
    """
    Delete a conversation session and all related data (messages, checkpoints).
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        sessionId: Session identifier
    
    Returns:
        Success message
    """
    try:
        # Delete session document
        if sessions_container:
            partition_key = [tenantId, userId, sessionId]
            sessions_container.delete_item(item=sessionId, partition_key=partition_key)
        
        # Delete messages
        if messages_container:
            query = "SELECT c.id FROM c WHERE c.sessionId = @sessionId"
            items = list(messages_container.query_items(
                query=query,
                parameters=[{"name": "@sessionId", "value": sessionId}],
                enable_cross_partition_query=True
            ))
            for item in items:
                try:
                    partition_key = [tenantId, userId, sessionId]
                    messages_container.delete_item(item=item["id"], partition_key=partition_key)
                except Exception as e:
                    logger.warning(f"Failed to delete message {item['id']}: {e}")
        
        # Schedule checkpoint cleanup as background task
        async def delete_checkpoints():
            try:
                await adelete_checkpoints_for_thread(sessionId)
            except Exception as e:
                logger.error(f"Error cleaning up checkpoints: {e}")
        
        background_tasks.add_task(delete_checkpoints)
        
        return {"message": "Session deleted successfully", "sessionId": sessionId}
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")


# ============================================================================
# Chat Completion Endpoint
# ============================================================================

def store_debug_log_from_response(sessionId: str, tenantId: str, userId: str, response_data: List[Dict], debug_log_id: Optional[str] = None) -> str:
    """
    Extract debug information from LangGraph response and store in Cosmos DB.
    
    Args:
        sessionId: Session identifier
        tenantId: Tenant identifier
        userId: User identifier
        response_data: LangGraph response data containing agent messages
        debug_log_id: Optional pre-generated debug log ID
    
    Returns:
        Debug log ID
    """
    # Extract debug details from response
    agent_selected = "Unknown"
    previous_agent = "Unknown"
    finish_reason = "Unknown"
    model_name = "Unknown"
    system_fingerprint = "Unknown"
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cached_tokens = 0
    transfer_success = False
    tool_calls = []
    logprobs = None
    content_filter_results = {}
    
    for entry in response_data:
        for agent, details in entry.items():
            if "messages" in details:
                for msg in details["messages"]:
                    if hasattr(msg, 'response_metadata'):
                        metadata = msg.response_metadata
                        finish_reason = metadata.get("finish_reason", finish_reason)
                        model_name = metadata.get("model_name", model_name)
                        system_fingerprint = metadata.get("system_fingerprint", system_fingerprint)
                        token_usage = metadata.get("token_usage", {})
                        input_tokens = token_usage.get("prompt_tokens", input_tokens)
                        output_tokens = token_usage.get("completion_tokens", output_tokens)
                        total_tokens = token_usage.get("total_tokens", total_tokens)
                        
                        # Get cached tokens from prompt_tokens_details
                        prompt_details = token_usage.get("prompt_tokens_details", {})
                        cached_tokens = prompt_details.get("cached_tokens", cached_tokens)
                        
                        logprobs = metadata.get("logprobs", logprobs)
                        content_filter_results = metadata.get("content_filter_results", content_filter_results)
                        
                        # Check for tool calls made by the supervisor or sub-agents
                        if hasattr(msg, 'additional_kwargs') and "tool_calls" in msg.additional_kwargs:
                            msg_tool_calls = msg.additional_kwargs["tool_calls"]
                            tool_calls.extend(msg_tool_calls)
                            if msg_tool_calls:
                                previous_agent = agent_selected
                                last_tool_call = msg_tool_calls[-1]
                                agent_selected = (
                                    last_tool_call.get("name")
                                    or last_tool_call.get("function", {}).get("name")
                                    or "tool"
                                )
                                transfer_success = True
    
    # Store in Cosmos DB using the new function
    try:
        stored_id = store_debug_log(
            session_id=sessionId,
            tenant_id=tenantId,
            user_id=userId,
            agent_selected=agent_selected,
            previous_agent=previous_agent,
            finish_reason=finish_reason,
            model_name=model_name,
            system_fingerprint=system_fingerprint,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            transfer_success=transfer_success,
            tool_calls=tool_calls,
            logprobs=logprobs,
            content_filter_results=content_filter_results,
            debug_log_id=debug_log_id
        )
        
        logger.info(f"✅ Debug log stored: {stored_id} for session {sessionId} (agent: {agent_selected}, tokens: {total_tokens})")
        return stored_id
    except Exception as e:
        logger.error(f"❌ Failed to store debug log: {e}")
        # Return a placeholder ID if storage fails
        return str(uuid.uuid4())


def extract_relevant_messages(
    debug_log_id: str,
    last_active_agent: str,
    response_data: List[Dict],
    tenantId: str,
    userId: str,
    sessionId: str,
    user_message_text: str = ""
) -> List[tuple]:
    """Extract user and assistant messages from response data. Returns tuples of (MessageModel, original_message)"""
    
    # Find the last agent node that responded
    last_agent_node = None
    last_agent_name = "unknown"
    
    for i in range(len(response_data) - 1, -1, -1):
        if "__interrupt__" in response_data[i]:
            if i > 0:
                last_agent_node = response_data[i - 1]
                last_agent_name = list(last_agent_node.keys())[0]
            break
    
    if last_agent_name == "unknown" and response_data:
        last_agent_node = response_data[-1]
        last_agent_name = list(last_agent_node.keys())[0] if last_agent_node else "unknown"
    
    logger.info(f"Last active agent: {last_agent_name}")
    
    # Agent patching moved to _post_response_background for non-blocking response
    
    if not last_agent_node:
        return []
    
    # Collect messages emitted across every update so we can pick the final reply
    # even when an intermediate update (e.g., a tool call) is the "last" node.
    messages = []
    for update in response_data:
        if not isinstance(update, dict):
            continue
        for value in update.values():
            if isinstance(value, dict) and "messages" in value:
                messages.extend(value["messages"])
    
    # With stream_mode="updates" the HumanMessage isn't in any per-node delta,
    # so synthesize it from the request body so the UI can render the turn.
    user_msg = HumanMessage(content=user_message_text) if user_message_text else None
    
    # Find the last assistant message that has real content (skip tool-only AIMessages).
    last_assistant_msg = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not isinstance(msg, ToolMessage):
            if hasattr(msg, "content") and msg.content and str(msg.content).strip():
                last_assistant_msg = msg
                break
    
    filtered_messages = []
    if user_msg is not None:
        filtered_messages.append(user_msg)
    if last_assistant_msg is not None:
        filtered_messages.append(last_assistant_msg)
    
    if not filtered_messages:
        return []
    
    # Convert to MessageModel and keep original message
    mapped_agent = agent_mapping.get(last_agent_name, last_agent_name.title())
    
    result = []
    for msg in filtered_messages:
        if (hasattr(msg, "content") and msg.content) or str(msg):
            message_model = MessageModel(
                id=str(uuid.uuid4()),
                type="message",
                sessionId=sessionId,
                tenantId=tenantId,
                userId=userId,
                timeStamp=msg.response_metadata.get("timestamp", datetime.utcnow().isoformat()) if hasattr(msg, "response_metadata") else datetime.utcnow().isoformat(),
                sender="User" if isinstance(msg, HumanMessage) else mapped_agent,
                senderRole="User" if isinstance(msg, HumanMessage) else "Assistant",
                text=msg.content if hasattr(msg, "content") else str(msg),
                debugLogId=debug_log_id,
                tokensUsed=msg.response_metadata.get("token_usage", {}).get("total_tokens", 0) if hasattr(msg, "response_metadata") else 0,
                rating=None
            )
            result.append((message_model, msg))
    
    return result


def process_messages_background(message_tuples: List[tuple], userId: str, tenantId: str, sessionId: str):
    """
    Background task to store messages in Cosmos DB.
    
    Args:
        message_tuples: List of tuples containing (MessageModel, original_langchain_message)
        userId: User identifier
        tenantId: Tenant identifier
        sessionId: Session identifier
    """
    try:
        for message_model, original_msg in message_tuples:
            # Extract tool_calls from original AIMessage if it exists
            tool_calls = None
            if isinstance(original_msg, AIMessage):
                if hasattr(original_msg, 'tool_calls') and original_msg.tool_calls:
                    tool_calls = original_msg.tool_calls
                elif hasattr(original_msg, 'additional_kwargs') and "tool_calls" in original_msg.additional_kwargs:
                    tool_calls = original_msg.additional_kwargs["tool_calls"]
            
            append_message(
                session_id=sessionId,
                tenant_id=tenantId,
                user_id=userId,
                role="user" if message_model.senderRole == "User" else "assistant",
                content=message_model.text,
                tool_calls=tool_calls
            )
        
        # Update session activity with actual message count
        update_session_activity(sessionId, tenantId, userId, message_count=len(message_tuples))
        
        logger.info(f"✅ Stored {len(message_tuples)} messages for session {sessionId}")
    except Exception as e:
        logger.error(f"Error storing messages: {e}")


async def _post_response_background(sessionId: str, tenantId: str, userId: str, response_data, messages, debug_log_id: str):
    """
    Background task: store debug log, persist messages, update agent state.
    Runs after HTTP response is already sent to the client.
    Each step is guarded independently so one failure doesn't block the others.
    """
    # Step 1: Store debug log
    try:
        await asyncio.to_thread(
            store_debug_log_from_response,
            sessionId,
            tenantId,
            userId,
            response_data,
            debug_log_id=debug_log_id,
        )
    except Exception as e:
        logger.error(f"❌ Failed to store debug log for session {sessionId}: {e}")
    
    # Step 2: Persist messages (runs even if debug log failed)
    messages_persisted = False
    try:
        await asyncio.to_thread(process_messages_background, messages, userId, tenantId, sessionId)
        messages_persisted = True
    except Exception as e:
        logger.error(f"❌ Failed to persist messages for session {sessionId}: {e}")

    # Step 3: Toolkit auto-summarization is now driven by the MCP add_turn
    # tool (which calls add_local + push_to_cosmos) and consults the
    # FACT_EXTRACTION_EVERY_N / THREAD_SUMMARY_EVERY_N / USER_SUMMARY_EVERY_N
    # / DEDUP_EVERY_N env vars. No hand-rolled cadence needed here.
    
    # Step 4: Patch active agent
    try:
        last_agent_name = "unknown"
        for i in range(len(response_data) - 1, -1, -1):
            if "__interrupt__" in response_data[i]:
                if i > 0:
                    last_agent_name = list(response_data[i - 1].keys())[0]
                break
        if last_agent_name == "unknown" and response_data:
            last_agent_name = list(response_data[-1].keys())[0] if response_data[-1] else "unknown"
        
        await asyncio.to_thread(patch_active_agent, tenantId, userId, sessionId, last_agent_name)
    except Exception as e:
        logger.error(f"❌ Failed to patch active agent for session {sessionId}: {e}")
    
    logger.info(f"✅ Background processing complete for session {sessionId}")


async def chat_event_generator(
    tenant_id: str,
    user_id: str,
    thread_id: str,
    user_message: str,
    debug_log_id: Optional[str] = None,
) -> AsyncIterator[dict]:
    workflow = get_compiled_graph()
    client = await get_memory_client()

    if not debug_log_id:
        debug_log_id = str(uuid.uuid4())
    dbg: Dict[str, Any] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "model_name": "Unknown",
        "finish_reason": "Unknown",
        "system_fingerprint": "Unknown",
        "nodes": [],
        "tools": [],
    }

    base_config = _thread_config(tenant_id, user_id, thread_id)
    checkpoint_history = trim_history(await _load_checkpoint_history(base_config))
    pref_vector = await _fetch_user_preference_vector(client, user_id)
    messages: list[Any] = list(checkpoint_history)
    messages.append(HumanMessage(content=user_message))
    config = _thread_config(tenant_id, user_id, thread_id, pref_vector)

    client.add_local(
        user_id=user_id,
        thread_id=thread_id,
        role="user",
        content=user_message,
        memory_type="turn",
    )

    accumulated: list[str] = []
    last_output_text = ""
    token = _current_user_preference_vector.set(pref_vector)
    try:
        async for event in workflow.astream_events(
            {"messages": messages},
            config=config,
            version="v2",
        ):
            kind = event.get("event")
            if kind == "on_tool_start":
                dbg["tools"].append({"name": event.get("name")})
                yield {
                    "event": "tool_call_start",
                    "tool": event.get("name"),
                    "args": event.get("data", {}).get("input"),
                }
            elif kind == "on_tool_end":
                yield {"event": "tool_call_done", "tool": event.get("name")}
            elif kind == "on_chain_start":
                node_name = event.get("name")
                if node_name in _AGENT_NODES and node_name not in dbg["nodes"]:
                    dbg["nodes"].append(node_name)
                if node_name in ("supervisor", "find_places", "create_or_update_itinerary"):
                    yield {"event": "thinking", "node": node_name}
            elif kind == "on_chat_model_end":
                usage = _extract_msg_usage(event.get("data", {}).get("output"))
                if usage:
                    dbg["input_tokens"] += usage["input_tokens"]
                    dbg["output_tokens"] += usage["output_tokens"]
                    dbg["total_tokens"] += usage["total_tokens"]
                    dbg["cached_tokens"] += usage["cached_tokens"]
                    if usage["model_name"] != "Unknown":
                        dbg["model_name"] = usage["model_name"]
                    if usage["finish_reason"] != "Unknown":
                        dbg["finish_reason"] = usage["finish_reason"]
                    if usage["system_fingerprint"] != "Unknown":
                        dbg["system_fingerprint"] = usage["system_fingerprint"]
            elif kind == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                delta = _message_content_to_text(getattr(chunk, "content", ""))
                if delta:
                    accumulated.append(delta)
                    yield {"event": "token", "delta": delta}
            elif kind == "on_chain_end":
                candidate = _last_ai_text_from_value(event.get("data", {}).get("output"))
                if candidate:
                    last_output_text = candidate
    finally:
        _current_user_preference_vector.reset(token)

    if not accumulated and last_output_text:
        yield {"event": "token", "delta": last_output_text}

    final_text = "".join(accumulated).strip() or last_output_text
    if final_text:
        try:
            client.add_local(
                user_id=user_id,
                thread_id=thread_id,
                role="agent",
                content=final_text,
                memory_type="turn",
            )
        except Exception as exc:
            logger.warning("turn capture (agent) failed: %s", exc)

    try:
        await asyncio.to_thread(
            _persist_chat_turn_messages,
            thread_id,
            tenant_id,
            user_id,
            user_message,
            final_text,
        )
    except Exception as exc:
        logger.warning("chat message persistence failed: %s", exc)

    task = asyncio.create_task(_flush_memory_bg(client, user_id, thread_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    try:
        await asyncio.to_thread(
            _persist_turn_debug_log,
            tenant_id,
            user_id,
            thread_id,
            debug_log_id,
            dbg,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("debug log capture failed: %s", exc)

    yield {"event": "done", "thread_id": thread_id}


async def chat_stream_generator(
    tenant_id: str,
    user_id: str,
    thread_id: str,
    user_message: str,
) -> AsyncIterator[str]:
    async for event in chat_event_generator(tenant_id, user_id, thread_id, user_message):
        yield _sse(event)


@app.post(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/completion",
    tags=[CHAT_TAG],
    summary="Chat Completion",
    description="Send a message and get AI agent response (main chat endpoint)",
    response_model=List[MessageModel]
)
async def get_chat_completion(
    tenantId: str,
    userId: str,
    sessionId: str,
    background_tasks: BackgroundTasks,
    request_body: str = Body(..., media_type="application/json"),
):
    """Send a message and receive a non-streamed supervisor response."""
    await ensure_agents_initialized()

    if not request_body.strip():
        raise HTTPException(status_code=400, detail="Request body cannot be empty")

    try:
        debug_log_id = str(uuid.uuid4())
        assistant_chunks: list[str] = []
        async for event in chat_event_generator(tenantId, userId, sessionId, request_body, debug_log_id=debug_log_id):
            if event.get("event") == "token":
                assistant_chunks.append(event.get("delta", ""))

        response_models = [
            _build_message_model(sessionId, tenantId, userId, "user", request_body, debug_log_id)
        ]
        assistant_text = "".join(assistant_chunks).strip()
        if assistant_text:
            response_models.append(
                _build_message_model(sessionId, tenantId, userId, "assistant", assistant_text, debug_log_id)
            )
        return response_models

    except Exception as e:
        logger.error(f"Error in chat completion: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Chat completion failed: {str(e)}")


@app.post(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/completion/stream",
    tags=[CHAT_TAG],
    summary="Streaming Chat Completion",
    description="Stream supervisor response tokens and tool progress over Server-Sent Events",
)
async def stream_chat_completion(
    tenantId: str,
    userId: str,
    sessionId: str,
    request_body: str = Body(..., media_type="application/json"),
):
    await ensure_agents_initialized()

    if not request_body.strip():
        raise HTTPException(status_code=400, detail="Request body cannot be empty")

    return StreamingResponse(
        chat_stream_generator(tenantId, userId, sessionId, request_body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/summarize-name",
    tags=[CHAT_TAG],
    summary="Auto-Generate Session Title",
    description="Generate a descriptive session title based on conversation content",
    response_model=str
)
async def summarize_session_name(
    tenantId: str,
    userId: str,
    sessionId: str,
    request_body: str = Body(..., media_type="application/json")
):
    """
    Generate a concise session title from conversation text.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        sessionId: Session identifier
        request_body: Conversation text to summarize
    
    Returns:
        Suggested session title (string)
    """
    try:
        # Use Azure OpenAI to generate a short title
        response = await model.ainvoke([
            {"role": "system", "content": "You are a helpful assistant that creates short, descriptive titles (max 6 words) for conversations. Return only the title, nothing else."},
            {"role": "user", "content": f"Create a short title for this conversation:\n\n{request_body}"}
        ])
        
        title = response.content.strip().strip('"')
        return title
        
    except Exception as e:
        logger.error(f"Error generating session title: {e}")
        return "New Conversation"


# ============================================================================
# Trip Management Endpoints
# ============================================================================

@app.get(
    "/tenant/{tenantId}/user/{userId}/trips",
    tags=[TRIP_TAG],
    summary="List User Trips",
    description="Get all trip itineraries for a user",
    response_model=List[Trip]
)
def get_user_trips(tenantId: str, userId: str):
    """
    Get all trips created by a user.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
    
    Returns:
        List of Trip objects
    """
    try:
        if not trips_container:
            raise HTTPException(status_code=503, detail="Cosmos DB not available")
        
        query = """
        SELECT * FROM c 
        WHERE c.tenantId = @tenantId 
        AND c.userId = @userId
        ORDER BY c.startDate DESC
        """
        
        items = list(trips_container.query_items(
            query=query,
            parameters=[
                {"name": "@tenantId", "value": tenantId},
                {"name": "@userId", "value": userId}
            ],
            enable_cross_partition_query=True
        ))
        
        return [Trip(**item) for item in items]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching trips: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch trips: {str(e)}")


@app.get(
    "/tenant/{tenantId}/user/{userId}/trips/{tripId}",
    tags=[TRIP_TAG],
    summary="Get Trip Details",
    description="Retrieve detailed information about a specific trip",
    response_model=Trip
)
def get_trip_details(tenantId: str, userId: str, tripId: str):
    """
    Get detailed trip information.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        tripId: Trip identifier
    
    Returns:
        Trip object with full itinerary
    """
    try:
        trip = get_trip(tripId, userId, tenantId)
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        
        return Trip(**trip)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching trip: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch trip: {str(e)}")


@app.put(
    "/tenant/{tenantId}/user/{userId}/trips/{tripId}",
    tags=[TRIP_TAG],
    summary="Update Trip",
    description="Update trip details (dates, places, status, etc.)",
    response_model=Trip
)
def update_trip_endpoint(tenantId: str, userId: str, tripId: str, updates: Dict[str, Any]):
    """
    Update trip information.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        tripId: Trip identifier
        updates: Dictionary of fields to update
    
    Returns:
        Updated Trip object
    """
    try:
        trip = get_trip(tripId, userId, tenantId)
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found")
        
        # Apply updates
        trip.update(updates)
        
        # Save to Cosmos DB
        if trips_container:
            trips_container.upsert_item(trip)
        
        return Trip(**trip)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating trip: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update trip: {str(e)}")


@app.delete(
    "/tenant/{tenantId}/user/{userId}/trips/{tripId}",
    tags=[TRIP_TAG],
    summary="Delete Trip",
    description="Delete a trip itinerary",
    status_code=200
)
def delete_trip_endpoint(tenantId: str, userId: str, tripId: str):
    """
    Delete a trip.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        tripId: Trip identifier
    
    Returns:
        Success message
    """
    try:
        if not trips_container:
            raise HTTPException(status_code=503, detail="Cosmos DB not available")
        
        partition_key = [tenantId, userId, tripId]
        trips_container.delete_item(item=tripId, partition_key=partition_key)
        
        return {"message": "Trip deleted successfully", "tripId": tripId}
    except CosmosHttpResponseError as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="Trip not found")
        raise
    except Exception as e:
        logger.error(f"Error deleting trip: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete trip: {str(e)}")


# ============================================================================
# Memory Management Endpoints
# ============================================================================

@app.get(
    "/users/{user_id}/memories",
    tags=[MEMORY_TAG],
    summary="Get User Memories",
    description="Retrieve toolkit memories for a user; searches when q is supplied, otherwise lists recent memories",
    response_model=List[Dict[str, Any]]
)
async def get_user_memories(
    user_id: str,
    q: Optional[str] = None,
    thread_id: Optional[str] = None,
    top_k: int = 10,
):
    """Get toolkit-backed memories for a user."""
    try:
        client = await get_memory_client()
        if q and q.strip():
            return await client.search_cosmos(
                search_terms=q,
                user_id=user_id,
                thread_id=thread_id,
                top_k=top_k,
            )

        return await client.get_memories(
            user_id=user_id,
            thread_id=thread_id,
            recent_k=top_k,
        )
    except Exception as e:
        logger.error(f"Error fetching memories: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch memories: {str(e)}")


@app.delete(
    "/users/{user_id}/memories/{memory_id}",
    tags=[MEMORY_TAG],
    summary="Delete Memory",
    description="Delete a toolkit memory for a user and thread",
    status_code=204
)
async def delete_memory(user_id: str, memory_id: str, thread_id: Optional[str] = None):
    """Delete a toolkit-backed memory."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required")

    try:
        client = await get_memory_client()
        await client.delete_cosmos(
            memory_id=memory_id,
            thread_id=thread_id,
            user_id=user_id,
        )
        return Response(status_code=204)
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete memory: {str(e)}")


@app.get(
    "/users/{user_id}/summary",
    tags=[MEMORY_TAG],
    summary="Get User Summary",
    description="Retrieve the latest toolkit-generated cross-thread user summary",
    response_model=Optional[Dict[str, Any]]
)
async def get_user_summary(user_id: str):
    """Get the latest toolkit-backed user summary, or null if absent."""
    try:
        client = await get_memory_client()
        summary = await client.get_user_summary(user_id)
        if summary is None:
            return None
        if isinstance(summary, list):
            return summary[0] if summary else None
        return summary
    except Exception as e:
        logger.error(f"Error fetching user summary: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch user summary: {str(e)}")


# ============================================================================
# Places Discovery Endpoints
# ============================================================================

@app.post(
    "/places/search",
    tags=[PLACES_TAG],
    summary="Search Places",
    description="Hybrid search (full-text + vector) with optional filters (type, price, dietary, accessibility) - useful for theme-based searches",
    response_model=List[Place]
)
def search_places(search_request: PlaceSearchRequest):
    """
    Search for hotels, restaurants, or attractions using hybrid RRF search.
    
    This endpoint uses semantic search with optional filters for type, price tier,
    dietary options, accessibility features, and tags.
    
    Args:
        search_request: PlaceSearchRequest with search parameters and optional filters
    
    Returns:
        List of Place objects matching the search criteria
    """
    try:
        # Extract filters
        filters = search_request.filters or {}
        place_type = filters.get("type")
        price_tier = filters.get("priceTier")
        dietary = filters.get("dietary")
        accessibility = filters.get("accessibility")
        
        # Coerce to lists (query_places_hybrid expects List[str])
        if dietary and not isinstance(dietary, list):
            dietary = [dietary]
        if accessibility and not isinstance(accessibility, list):
            accessibility = [accessibility]
        
        logger.info(f"🔍 search_places called with filters: type={place_type}, priceTier={price_tier}, dietary={dietary}, accessibility={accessibility}")
        
        # Call query_places_hybrid with the correct parameters
        # The function handles embedding generation and keyword extraction internally
        places = query_places_hybrid(
            query=search_request.query,
            geo_scope_id=search_request.geoScope.lower(),
            place_type=place_type,
            price_tier=price_tier,
            dietary=dietary,
            accessibility=accessibility
        )
        
        return [Place(**place) for place in places]
    except Exception as e:
        logger.error(f"Error searching places: {e}")
        raise HTTPException(status_code=500, detail=f"Place search failed: {str(e)}")


@app.post(
    "/tenant/{tenantId}/places/filter",
    tags=[PLACES_TAG],
    summary="Filter Places by City and Criteria",
    description="Filter places with optional theme for semantic search. Routes to vector search if theme provided, otherwise simple filter.",
    response_model=List[Place]
)
def filter_places(tenantId: str, filter_request: PlaceFilterRequest):
    """
    Filter places by various criteria with optional theme-based semantic search.
    
    Two scenarios:
    1. WITH THEME: Uses vector search with theme embedding and keyword extraction
    2. WITHOUT THEME: Uses simple filtered query sorted by rating
    
    Args:
        tenantId: Tenant identifier
        filter_request: PlaceFilterRequest with filter parameters
    
    Returns:
        List of Place objects matching the filter criteria
    """
    try:
        logger.info(f"Filtering places for city: {filter_request.city}, theme: {filter_request.theme}")
        logger.info(f"Filters: types={filter_request.types}, priceTiers={filter_request.priceTiers}, dietary={filter_request.dietary}, accessibility={filter_request.accessibility}")

        # Determine which method to use based on theme
        if filter_request.theme and filter_request.theme.strip():
            logger.info("📊 Using THEME Hybrid SEARCH")
            
            # Convert multi-select filters to appropriate format
            place_type = filter_request.types[0] if filter_request.types and len(filter_request.types) == 1 else None

            places = query_places_with_theme(
                theme=filter_request.theme,
                geo_scope_id=filter_request.city,
                place_type=place_type,
                dietary=filter_request.dietary,
                accessibility=filter_request.accessibility,
                price_tier=filter_request.priceTiers
            )
        else:
            # SCENARIO 3: Explore without theme - use simple filter
            logger.info("📊 Using SIMPLE FILTERED SEARCH")
            
            # Convert multi-select filters to appropriate format
            place_type = filter_request.types[0] if filter_request.types and len(filter_request.types) == 1 else None
            
            places = query_places_filtered(
                geo_scope_id=filter_request.city,
                place_type=place_type,
                dietary=filter_request.dietary,
                accessibility=filter_request.accessibility,
                price_tier=filter_request.priceTiers
            )
        
        logger.info(f"✅ Found {len(places)} places matching filters")
        
        return [Place(**place) for place in places]
    except Exception as e:
        logger.error(f"Error filtering places: {e}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Place filter failed: {str(e)}")


@app.get(
    "/places/{placeId}",
    tags=[PLACES_TAG],
    summary="Get Place Details",
    description="Get detailed information about a specific place",
    response_model=Place
)
def get_place_details(placeId: str):
    """
    Get detailed information about a place.
    
    Args:
        placeId: Place identifier
    
    Returns:
        Place object with full details
    """
    try:
        if not places_container:
            raise HTTPException(status_code=503, detail="Cosmos DB not available")
        
        # Note: In production, you'd need proper partition key handling
        query = "SELECT * FROM c WHERE c.id = @placeId"
        items = list(places_container.query_items(
            query=query,
            parameters=[{"name": "@placeId", "value": placeId}],
            enable_cross_partition_query=True
        ))
        
        if not items:
            raise HTTPException(status_code=404, detail="Place not found")
        
        return Place(**items[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching place: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch place: {str(e)}")


# ============================================================================
# Debug & Analytics Endpoints
# ============================================================================

@app.get(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/completiondetails/{debugLogId}",
    tags=[DEBUG_TAG],
    summary="Get Debug Information",
    description="Retrieve detailed debug information for a chat completion",
    response_model=Dict[str, Any]
)
def get_completion_details(tenantId: str, userId: str, sessionId: str, debugLogId: str):
    """
    Get debug information for a specific AI response.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        sessionId: Session identifier
        debugLogId: Debug log identifier
    
    Returns:
        Debug information including tokens used, model name, latency, etc.
    """
    try:
        # Retrieve debug log from Cosmos DB
        debug_log = get_debug_log(debugLogId, tenantId, userId, sessionId)
        
        if not debug_log:
            raise HTTPException(status_code=404, detail="Debug log not found")
        
        # Extract property bag into a more user-friendly format
        properties = {}
        if "propertyBag" in debug_log:
            for prop in debug_log["propertyBag"]:
                properties[prop["key"]] = prop["value"]
        
        return {
            "id": debugLogId,
            "sessionId": sessionId,
            "messageId": debug_log.get("messageId"),
            "timestamp": debug_log.get("timeStamp"),
            "agentSelected": properties.get("agent_selected", "Unknown"),
            "previousAgent": properties.get("previous_agent", "Unknown"),
            "finishReason": properties.get("finish_reason", "Unknown"),
            "modelName": properties.get("model_name", "Unknown"),
            "systemFingerprint": properties.get("system_fingerprint", "Unknown"),
            "inputTokens": properties.get("input_tokens", 0),
            "outputTokens": properties.get("output_tokens", 0),
            "totalTokens": properties.get("total_tokens", 0),
            "cachedTokens": properties.get("cached_tokens", 0),
            "transferSuccess": properties.get("transfer_success", False),
            "toolCalls": properties.get("tool_calls", "[]"),
            "logprobs": properties.get("logprobs", "{}"),
            "contentFilterResults": properties.get("content_filter_results", "{}")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving debug log: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve debug log: {str(e)}")


@app.get(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/debug-logs",
    tags=[DEBUG_TAG],
    summary="List Session Debug Logs",
    description="Retrieve all debug logs for a session",
    response_model=List[Dict[str, Any]]
)
def get_session_debug_logs(tenantId: str, userId: str, sessionId: str, limit: int = 10):
    """
    Get all debug logs for a session.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        sessionId: Session identifier
        limit: Maximum number of logs to return (default: 10)
    
    Returns:
        List of debug logs with summary information
    """
    try:
        # Retrieve debug logs from Cosmos DB
        debug_logs = query_debug_logs(sessionId, tenantId, userId, limit)
        
        # Transform to user-friendly format
        result = []
        for log in debug_logs:
            properties = {}
            if "propertyBag" in log:
                for prop in log["propertyBag"]:
                    properties[prop["key"]] = prop["value"]
            
            result.append({
                "id": log.get("debugLogId", log.get("id")),
                "sessionId": log.get("sessionId"),
                "messageId": log.get("messageId"),
                "timestamp": log.get("timeStamp"),
                "agentSelected": properties.get("agent_selected", "Unknown"),
                "totalTokens": properties.get("total_tokens", 0),
                "modelName": properties.get("model_name", "Unknown"),
                "transferSuccess": properties.get("transfer_success", False)
            })
        
        return result
    except Exception as e:
        logger.error(f"Error retrieving debug logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve debug logs: {str(e)}")


@app.post(
    "/tenant/{tenantId}/user/{userId}/sessions/{sessionId}/message/{messageId}/rate",
    tags=[DEBUG_TAG],
    summary="Rate Message",
    description="Rate an AI response with thumbs up/down",
    response_model=MessageModel
)
def rate_message(tenantId: str, userId: str, sessionId: str, messageId: str, rating: bool):
    """
    Rate an AI response.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        sessionId: Session identifier
        messageId: Message identifier
        rating: True for thumbs up, False for thumbs down
    
    Returns:
        Updated MessageModel with rating
    """
    # Note: In production, you'd update the message in Cosmos DB
    # For now, return mock response
    return MessageModel(
        id=messageId,
        type="message",
        sessionId=sessionId,
        tenantId=tenantId,
        userId=userId,
        timeStamp=datetime.utcnow().isoformat(),
        sender="Assistant",
        senderRole="Assistant",
        text="This is a rated message",
        debugLogId=str(uuid.uuid4()),
        tokensUsed=0,
        rating=rating
    )


# ============================================================================
# User Management Endpoints
# ============================================================================

@app.post(
    "/tenant/{tenantId}/users",
    tags=["User Management"],
    summary="Create New User",
    description="Create a new user profile",
    response_model=User,
    status_code=201
)
def create_new_user(
    tenantId: str,
    request: CreateUserRequest
):
    """
    Create a new user profile.
    
    Args:
        tenantId: Tenant identifier
        request: User creation request with all user details
    
    Returns:
        Created User object
    """
    try:
        user_id = create_user(
            user_id=request.userId,
            tenant_id=tenantId,
            name=request.name,
            gender=request.gender,
            age=request.age,
            phone=request.phone,
            address=request.address,
            email=request.email
        )
        
        # Retrieve and return the created user
        user_data = get_user_by_id(user_id, tenantId)
        if not user_data:
            raise HTTPException(status_code=500, detail="Failed to retrieve created user")
        
        return User(**user_data)
    
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/tenant/{tenantId}/users",
    tags=["User Management"],
    summary="Get All Users",
    description="Get all users for a tenant",
    response_model=List[User]
)
def get_tenant_users(tenantId: str):
    """
    Get all users for a specific tenant.
    
    Args:
        tenantId: Tenant identifier
    
    Returns:
        List of User objects
    """
    try:
        users = get_all_users(tenantId)
        return [User(**user) for user in users]
    
    except Exception as e:
        logger.error(f"Error retrieving users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get(
    "/tenant/{tenantId}/users/{userId}",
    tags=["User Management"],
    summary="Get User by ID",
    description="Get a specific user by their ID",
    response_model=User
)
def get_user(tenantId: str, userId: str):
    """
    Get a specific user by their ID.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
    
    Returns:
        User object
    """
    try:
        user_data = get_user_by_id(userId, tenantId)
        
        if not user_data:
            raise HTTPException(status_code=404, detail=f"User not found: {userId}")
        
        return User(**user_data)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Cities - Get Distinct Cities
# ============================================================================

@app.get(
    "/cities",
    tags=["Cities"],
    summary="Get All Cities",
    description="Get all distinct cities available in the system"
)
def get_cities_endpoint():
    """
    Get all distinct cities (geoScopeIds) from the places container.
    
    Returns:
        List of city objects with id, name, and displayName
    """
    try:
        from src.app.services.azure_cosmos_db import get_distinct_cities
        
        # Pass empty tenant since it's not needed for cities query
        cities = get_distinct_cities("")
        return cities
    
    except Exception as e:
        logger.error(f"Error retrieving cities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Run Server
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    
    uvicorn.run(
        "travel_agents_api:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )

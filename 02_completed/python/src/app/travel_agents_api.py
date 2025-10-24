import os
import sys
import uuid
import asyncio
from pathlib import Path

import fastapi
from dotenv import load_dotenv
from datetime import datetime
from fastapi import BackgroundTasks, Depends, HTTPException, Body
from langchain_core.messages import HumanMessage, ToolMessage, AIMessage
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from enum import Enum
from starlette.middleware.cors import CORSMiddleware
from azure.cosmos.exceptions import CosmosHttpResponseError

import logging

# logging.basicConfig(
#     level=logging.DEBUG,  # Change to DEBUG for more details
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )

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

# # Verify critical environment variables
# mcp_token = os.getenv("MCP_AUTH_TOKEN")
# mcp_url = os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8080")
# print(f"🔐 MCP_AUTH_TOKEN: {'SET (' + mcp_token[:8] + '...)' if mcp_token else 'NOT SET'}")
# print(f"🌐 MCP_SERVER_BASE_URL: {mcp_url}")

from src.app.services.azure_open_ai import model, generate_embedding
from src.app.services.azure_cosmos_db import (
    sessions_container, messages_container, trips_container,
    memories_container, places_container, debug_logs_container, get_checkpoint_saver,
    create_session_record, get_session_by_id,
    append_message, get_session_messages,
    get_trip, query_memories, query_places,
    patch_active_agent, update_session_activity,
    create_user, get_all_users, get_user_by_id,
    store_debug_log, get_debug_log, query_debug_logs
)
from src.app.travel_agents import setup_agents, build_agent_graph, cleanup_persistent_session

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    scope: Dict[str, str]  # {"type": "city", "id": "rome"}
    dates: Dict[str, str]  # {"start": "2024-06-01", "end": "2024-06-04"}
    travelers: List[str]
    constraints: Dict[str, Any]  # {"budgetTier": 2}
    days: List[Dict] = []  # Day-by-day itinerary
    status: str = TripStatus.PLANNING


class MemoryType(str, Enum):
    DECLARATIVE = "declarative"
    EPISODIC = "episodic"
    PROCEDURAL = "procedural"


class Memory(BaseModel):
    id: str
    memoryId: str
    userId: str
    tenantId: str
    memoryType: str  # "declarative" | "episodic" | "procedural"
    text: str
    facets: Dict[str, Any]  # {"category": "dining", "preference": "vegetarian"}
    salience: float
    justification: str
    extractedAt: str
    lastUsedAt: str
    ttl: Optional[int] = None


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
_graph = None
_checkpointer = None

# Agent name mapping (for consistent display)
agent_mapping = {
    "orchestrator": "Orchestrator",
    "hotel": "Hotel",
    "activity": "Activity",
    "dining": "Dining",
    "itinerary_generator": "Itinerary",
    "summarizer": "Summarizer"
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
            await setup_agents()
            _graph = build_agent_graph()
            _checkpointer = get_checkpoint_saver()
            _agents_initialized = True
            logger.info("✅ Agents initialized successfully!")
            return
        except Exception as e:
            logger.error(f"❌ Failed to initialize agents (attempt {attempt + 1}/{max_retries}): {e}")
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
    logger.info("✅ Cleanup complete")


async def ensure_agents_initialized():
    """Ensure agents are initialized before handling requests"""
    global _agents_initialized

    if not _agents_initialized:
        logger.info("🔄 Initializing agents on demand...")
        try:
            await setup_agents()
            global _graph, _checkpointer
            _graph = build_agent_graph()
            _checkpointer = get_checkpoint_saver()
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
    "/",
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
        def delete_checkpoints():
            try:
                if _checkpointer and hasattr(_checkpointer, 'container'):
                    query = "SELECT c.id, c.partition_key FROM c WHERE CONTAINS(c.partition_key, @sessionId)"
                    partitions = list(_checkpointer.container.query_items(
                        query=query,
                        parameters=[{"name": "@sessionId", "value": sessionId}],
                        enable_cross_partition_query=True
                    ))
                    for partition in partitions:
                        try:
                            _checkpointer.container.delete_item(
                                item=partition["id"],
                                partition_key=partition["partition_key"]
                            )
                        except Exception as e:
                            logger.warning(f"Failed to delete checkpoint: {e}")
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

def store_debug_log_from_response(sessionId: str, tenantId: str, userId: str, response_data: List[Dict]) -> str:
    """
    Extract debug information from LangGraph response and store in Cosmos DB.
    
    Args:
        sessionId: Session identifier
        tenantId: Tenant identifier
        userId: User identifier
        response_data: LangGraph response data containing agent messages
    
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
                        
                        # Check for tool calls (agent transfers)
                        if hasattr(msg, 'additional_kwargs') and "tool_calls" in msg.additional_kwargs:
                            msg_tool_calls = msg.additional_kwargs["tool_calls"]
                            tool_calls.extend(msg_tool_calls)
                            transfer_success = any(
                                call.get("name", "").startswith("transfer_to_") for call in msg_tool_calls
                            )
                            if transfer_success and tool_calls:
                                previous_agent = agent_selected
                                agent_selected = tool_calls[-1].get("name", "").replace("transfer_to_", "")
    
    # Store in Cosmos DB using the new function
    try:
        debug_log_id = store_debug_log(
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
            content_filter_results=content_filter_results
        )
        
        logger.info(f"✅ Debug log stored: {debug_log_id} for session {sessionId} (agent: {agent_selected}, tokens: {total_tokens})")
        return debug_log_id
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
    sessionId: str
) -> List[MessageModel]:
    """Extract user and assistant messages from response data"""
    
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
    
    # Update active agent in session
    patch_active_agent(tenantId, userId, sessionId, last_agent_name)
    
    if not last_agent_node:
        return []
    
    # Extract messages
    messages = []
    for key, value in last_agent_node.items():
        if isinstance(value, dict) and "messages" in value:
            messages.extend(value["messages"])
    
    # Find last user message index
    last_user_index = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_user_index = i
            break
    
    if last_user_index == -1:
        return []
    
    # Get messages after last user message
    messages_after_user = messages[last_user_index:]
    
    # Filter: Only keep the last user message and the LAST assistant message (not all intermediate ones)
    filtered_messages = []
    
    # Add user message
    for msg in messages_after_user:
        if isinstance(msg, HumanMessage):
            filtered_messages.append(msg)
            break
    
    # Find and add only the LAST assistant message (skip intermediates and tool messages)
    last_assistant_msg = None
    for i in range(len(messages_after_user) - 1, -1, -1):
        msg = messages_after_user[i]
        if isinstance(msg, AIMessage) and not isinstance(msg, ToolMessage):
            # Make sure it has actual content
            if hasattr(msg, "content") and msg.content and msg.content.strip():
                last_assistant_msg = msg
                break
    
    if last_assistant_msg:
        filtered_messages.append(last_assistant_msg)
    
    # Convert to MessageModel
    mapped_agent = agent_mapping.get(last_agent_name, last_agent_name.title())
    
    return [
        MessageModel(
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
        for msg in filtered_messages
        if (hasattr(msg, "content") and msg.content) or str(msg)
    ]


def process_messages_background(messages: List[MessageModel], userId: str, tenantId: str, sessionId: str):
    """Background task to store messages in Cosmos DB"""
    try:
        for message in messages:
            append_message(
                session_id=sessionId,
                tenant_id=tenantId,
                user_id=userId,
                role="user" if message.senderRole == "User" else "assistant",
                content=message.text
            )
        
        # Update session activity
        update_session_activity(sessionId, tenantId, userId)
        
        logger.info(f"✅ Stored {len(messages)} messages for session {sessionId}")
    except Exception as e:
        logger.error(f"Error storing messages: {e}")


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
    workflow = Depends(get_compiled_graph)
):
    """
    Send a message and receive AI response from the multi-agent system.
    
    This endpoint:
    1. Resumes conversation from last checkpoint
    2. Routes message through orchestrator to appropriate agent
    3. Stores messages in Cosmos DB
    4. Returns user message + agent response
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        sessionId: Session identifier
        request_body: User message as plain text string
    
    Returns:
        List of MessageModel objects (user message + agent response)
    """
    # Ensure agents are initialized
    await ensure_agents_initialized()
    
    if not request_body.strip():
        raise HTTPException(status_code=400, detail="Request body cannot be empty")
    
    try:
        # Configuration for LangGraph
        config = {
            "configurable": {
                "thread_id": sessionId,
                "checkpoint_ns": "",
                "userId": userId,
                "tenantId": tenantId
            }
        }
        
        # Retrieve last checkpoint
        checkpoints = list(_checkpointer.list(config))
        last_active_agent = "orchestrator"
        
        if not checkpoints:
            # No previous state - start fresh
            new_state = {"messages": [{"role": "user", "content": request_body}]}
            response_data = await workflow.ainvoke(new_state, config, stream_mode="updates")
        else:
            # Resume from last checkpoint
            last_checkpoint = checkpoints[-1]
            last_state = last_checkpoint.checkpoint
            
            if "messages" not in last_state:
                last_state["messages"] = []
            
            last_state["messages"].append({"role": "user", "content": request_body})
            
            # Get active agent from state
            if "channel_versions" in last_state:
                for channel, version in last_state["channel_versions"].items():
                    if channel != "__start__" and version > 0:
                        last_active_agent = channel
                        break
            
            response_data = await workflow.ainvoke(last_state, config, stream_mode="updates")
        
        # Store debug log in Cosmos DB
        debug_log_id = store_debug_log_from_response(sessionId, tenantId, userId, response_data)
        
        # Extract messages
        messages = extract_relevant_messages(
            debug_log_id, last_active_agent, response_data, 
            tenantId, userId, sessionId
        )
        
        # Get active agent from database
        session = get_session_by_id(sessionId, tenantId, userId)
        if session:
            active_agent = session.get("activeAgent", "orchestrator")
            mapped_agent = agent_mapping.get(active_agent, active_agent.title())
            # Update last message sender
            if messages:
                messages[-1].sender = mapped_agent
        
        # Schedule background task to store messages
        background_tasks.add_task(
            process_messages_background, 
            messages, userId, tenantId, sessionId
        )
        
        return messages
        
    except Exception as e:
        logger.error(f"Error in chat completion: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Chat completion failed: {str(e)}")


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
        ORDER BY c.dates.start DESC
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
    "/tenant/{tenantId}/user/{userId}/memories",
    tags=[MEMORY_TAG],
    summary="Get User Memories",
    description="Retrieve user preferences and stored memories",
    response_model=List[Memory]
)
def get_user_memories(
    tenantId: str, 
    userId: str, 
    memoryType: Optional[str] = None,
    minSalience: float = 0.0,
):
    """
    Get stored memories for a user.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        memoryType: Optional filter by type (declarative, episodic, procedural)
        minSalience: Minimum importance score (0.0-1.0)
    
    Returns:
        List of Memory objects
    """
    try:
        memory_types = [memoryType] if memoryType else None
        memories = query_memories(
            user_id=userId,
            tenant_id=tenantId,
            memory_types=memory_types,
            min_salience=minSalience
        )
        
        return [Memory(**mem) for mem in memories]
    except Exception as e:
        logger.error(f"Error fetching memories: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch memories: {str(e)}")


@app.delete(
    "/tenant/{tenantId}/user/{userId}/memories/{memoryId}",
    tags=[MEMORY_TAG],
    summary="Delete Memory",
    description="Delete a specific user memory/preference",
    status_code=200
)
def delete_memory(tenantId: str, userId: str, memoryId: str):
    """
    Delete a stored memory.
    
    Args:
        tenantId: Tenant identifier
        userId: User identifier
        memoryId: Memory identifier
    
    Returns:
        Success message
    """
    try:
        if not memories_container:
            raise HTTPException(status_code=503, detail="Cosmos DB not available")
        
        partition_key = [tenantId, userId]
        memories_container.delete_item(item=memoryId, partition_key=partition_key)
        
        return {"message": "Memory deleted successfully", "memoryId": memoryId}
    except CosmosHttpResponseError as e:
        if e.status_code == 404:
            raise HTTPException(status_code=404, detail="Memory not found")
        raise
    except Exception as e:
        logger.error(f"Error deleting memory: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete memory: {str(e)}")


# ============================================================================
# Places Discovery Endpoints
# ============================================================================

@app.post(
    "/places/search",
    tags=[PLACES_TAG],
    summary="Search Places",
    description="Vector search with optional filters (type, price, dietary, accessibility, tags) - useful for theme-based searches",
    response_model=List[Place]
)
def search_places(search_request: PlaceSearchRequest):
    """
    Search for hotels, restaurants, or attractions using vector similarity.
    
    This endpoint uses semantic search with optional filters for type, price tier,
    dietary options, accessibility features, and tags.
    
    Args:
        search_request: PlaceSearchRequest with search parameters and optional filters
    
    Returns:
        List of Place objects matching the search criteria (top 5 by vector similarity)
    """
    try:
        # Generate embedding for query
        vectors = generate_embedding(search_request.query)
        
        # Extract filters
        place_type = search_request.filters.get("type") if search_request.filters else None
        price_tier = search_request.filters.get("priceTier") if search_request.filters else None
        dietary = search_request.filters.get("dietary") if search_request.filters else None
        accessibility = search_request.filters.get("accessibility") if search_request.filters else None
        tags = search_request.filters.get("tags") if search_request.filters else None
        
        logger.info(f"🔍 search_places called with filters: type={place_type}, priceTier={price_tier}, dietary={dietary}, accessibility={accessibility}, tags={tags}")
        
        # Query places with all filters
        places = query_places(
            vectors=vectors,
            geo_scope_id=search_request.geoScope.lower(),
            place_type=place_type,
            price_tier=price_tier,
            dietary=dietary,
            accessibility=accessibility,
            tags=tags
        )
        
        return [Place(**place) for place in places]
    except Exception as e:
        logger.error(f"Error searching places: {e}")
        raise HTTPException(status_code=500, detail=f"Place search failed: {str(e)}")


@app.post(
    "/tenant/{tenantId}/places/filter",
    tags=[PLACES_TAG],
    summary="Filter Places by City and Criteria",
    description="Filter places by city, type, price tier, etc. Returns places without requiring embeddings.",
    response_model=List[Place]
)
def filter_places(tenantId: str, filter_request: PlaceFilterRequest):
    """
    Filter places by various criteria.
    
    This endpoint returns places from a specific city filtered by type, price tier, 
    dietary options, and accessibility features.
    
    Args:
        tenantId: Tenant identifier
        filter_request: PlaceFilterRequest with filter parameters
    
    Returns:
        List of Place objects matching the filter criteria
    """
    try:
        logger.info(f"Filtering places for city: {filter_request.city}")
        logger.info(f"Filter criteria: types={filter_request.types}, priceTiers={filter_request.priceTiers}")

        # Build query
        query = "SELECT * FROM c WHERE c.geoScopeId = @city"
        parameters = [{"name": "@city", "value": filter_request.city.lower()}]
        
        # Add type filter
        if filter_request.types and len(filter_request.types) > 0:
            placeholders = ", ".join([f"@type{i}" for i in range(len(filter_request.types))])
            query += f" AND c.type IN ({placeholders})"
            for i, place_type in enumerate(filter_request.types):
                parameters.append({"name": f"@type{i}", "value": place_type})
        
        # Add price tier filter
        if filter_request.priceTiers and len(filter_request.priceTiers) > 0:
            placeholders = ", ".join([f"@tier{i}" for i in range(len(filter_request.priceTiers))])
            query += f" AND c.priceTier IN ({placeholders})"
            for i, tier in enumerate(filter_request.priceTiers):
                parameters.append({"name": f"@tier{i}", "value": tier})

        # Add dietary options filter
        if filter_request.dietary and len(filter_request.dietary) > 0:
            # Use ARRAY_CONTAINS for each dietary option (AND logic - place must have ALL selected options)
            dietary_conditions = []
            for i, diet in enumerate(filter_request.dietary):
                dietary_conditions.append(f"ARRAY_CONTAINS(c.dietary, @dietary{i})")
                parameters.append({"name": f"@dietary{i}", "value": diet})
            query += f" AND ({' AND '.join(dietary_conditions)})"

        # Add accessibility features filter
        if filter_request.accessibility and len(filter_request.accessibility) > 0:
            # Use ARRAY_CONTAINS for each accessibility feature (AND logic - place must have ALL selected features)
            accessibility_conditions = []
            for i, feature in enumerate(filter_request.accessibility):
                accessibility_conditions.append(f"ARRAY_CONTAINS(c.accessibility, @accessibility{i})")
                parameters.append({"name": f"@accessibility{i}", "value": feature})
            query += f" AND ({' AND '.join(accessibility_conditions)})"
        
        logger.info(f"Executing query: {query}")
        logger.info(f"Parameters: {parameters}")
        
        # Execute query
        places = list(places_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        logger.info(f"✅ Found {len(places)} places matching filters")
        
        return [Place(**place) for place in places]
    except Exception as e:
        logger.error(f"Error filtering places: {e}")
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

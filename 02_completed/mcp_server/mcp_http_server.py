import sys
import os
import logging
import json
from typing import Any, Dict, List, Optional
from langsmith import traceable
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

try:
    from src.app.services.agent_memory import get_memory_client
except ImportError:  # pragma: no cover - supports alternate workshop package layout
    from app.services.agent_memory import get_memory_client

from src.app.services.azure_open_ai import generate_embedding
from src.app.services.azure_cosmos_db import (
    create_session_record,
    get_session_by_id,
    append_message,
    get_session_messages,
    query_places_hybrid,
    create_trip,
    get_trip,
    record_api_event,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress SSE, OpenAI, urllib3, and LangSmith debug logs
logging.getLogger("sse_starlette.sse").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("langsmith.client").setLevel(logging.WARNING)


# Load environment variables
try:
    load_dotenv('.env', override=False)
    
    # Load authentication configuration
    simple_token = os.getenv("MCP_AUTH_TOKEN")
    github_client_id = os.getenv("GITHUB_CLIENT_ID")
    github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    base_url = os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8080")
    
    print("🔐 Authentication Configuration:")
    print(f"   Simple Token: {'SET' if simple_token else 'NOT SET'}")
    print(f"   GitHub Client ID: {'SET' if github_client_id else 'NOT SET'}")
    print(f"   Base URL: {base_url}")
    
    # Determine authentication mode
    if github_client_id and github_client_secret:
        auth_mode = "github_oauth"
        print("✅ GITHUB OAUTH MODE ENABLED")
    elif simple_token:
        auth_mode = "simple_token"
        print("✅ SIMPLE TOKEN MODE ENABLED (Development)")
        print(f"   Token: {simple_token[:8]}...")
    else:
        auth_mode = "none"
        print("⚠️  NO AUTHENTICATION - All requests accepted")
        
except ImportError as e:
    auth_mode = "none"
    simple_token = None
    print(f"❌ OAuth dependencies not available: {e}")

# Initialize MCP server
print("\n🚀 Initializing Travel Assistant MCP Server...")
port = int(os.getenv("PORT", 8080))
mcp = FastMCP("TravelAssistantTools", host="0.0.0.0", port=port)

print(f"✅ Travel Assistant MCP server initialized")
print(f"🌐 Server will be available at: http://0.0.0.0:{port}")
print(f"📋 Authentication mode: {auth_mode.upper()}\n")


# ============================================================================
# 1. Session Management Tools
# ============================================================================

@mcp.tool()
@traceable
def create_session(
    user_id: str,
    tenant_id: str = "",
    title: str = None,
    activeAgent: str = "orchestrator"
) -> Dict[str, Any]:
    """
    Create a new conversation session with proper initialization.
    
    Args:
        user_id: User identifier
        tenant_id: Tenant identifier (default: empty string)
        title: Optional session title
        
    Returns:
        Dictionary with session details including sessionId
    """
    logger.info(f"🆕 Creating session for user: {user_id}")
    session = create_session_record(user_id, tenant_id, activeAgent, title)
    return {
        "sessionId": session["sessionId"],
        "userId": user_id,
        "title": session["title"],
        "createdAt": session["createdAt"]
    }


@mcp.tool()
@traceable
def get_session_context(
    session_id: str,
    tenant_id: str,
    user_id: str
) -> Dict[str, Any]:
    """
    Retrieve conversation context (recent messages).
    
    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        
    Returns:
        Dictionary with messages and metadata
    """
    logger.info(f"📖 Getting context for session: {session_id}")
    
    messages = get_session_messages(session_id, tenant_id, user_id)
    session_info = get_session_by_id(session_id, tenant_id, user_id)
    
    result = {
        "messages": messages,
        "sessionInfo": session_info,
        "messageCount": len(messages)
    }
    
    return result


@mcp.tool()
@traceable
def append_turn(
    session_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    content: str,
    tool_call: Optional[Dict] = None,
    keywords: Optional[List[str]] = None,
    generate_embedding_flag: bool = True
) -> Dict[str, Any]:
    """
    Atomically store a message and update session metadata.
    
    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        role: Message role (user/assistant/system)
        content: Message content
        tool_call: Optional tool call information
        keywords: Optional list of keywords
        generate_embedding_flag: Whether to generate embedding (default: True)
        
    Returns:
        Dictionary with messageId and metadata
    """
    logger.info(f"💬 Appending {role} message to session: {session_id}")
    
    # Generate embedding if requested
    embedding = None
    if generate_embedding_flag and content:
        try:
            embedding = generate_embedding(content)
        except Exception as e:
            logger.warning(f"Failed to generate embedding: {e}")
    
    message_id = append_message(
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        content=content,
        tool_call=tool_call,
        embedding=embedding,
        keywords=keywords
    )
    
    return {
        "messageId": message_id,
        "sessionId": session_id,
        "role": role,
        "embeddingGenerated": embedding is not None
    }
# ============================================================================
# 2. Memory Tools
# ============================================================================


def _memory_to_dict(memory: Any) -> Dict[str, Any]:
    """Serialize toolkit memory objects and dicts for MCP responses."""
    if hasattr(memory, "model_dump"):
        return memory.model_dump()
    return dict(memory)


@mcp.tool()
@traceable
def add_turn(user_id: str, thread_id: str, role: str, text: str) -> Dict[str, Any]:
    """Persist a single conversational turn to long-term memory.

    Routes through ``add_local`` + ``push_to_cosmos`` so the toolkit's
    auto-trigger fires and consults the configured threshold knobs
    (``FACT_EXTRACTION_EVERY_N``, ``THREAD_SUMMARY_EVERY_N``,
    ``USER_SUMMARY_EVERY_N``, ``DEDUP_EVERY_N``). ``add_cosmos`` would
    skip the trigger entirely and break per-turn extraction.

    role is 'user' or 'assistant'. Returns {"id": <new memory id>}.
    """
    if role not in {"user", "assistant"}:
        raise ValueError("role must be 'user' or 'assistant'")

    client = get_memory_client()
    toolkit_role = "agent" if role == "assistant" else "user"

    client.add_local(
        user_id=user_id,
        role=toolkit_role,
        content=text,
        memory_type="turn",
        thread_id=thread_id,
        metadata={"role": role},
    )
    memory_id = client.local_memory[-1]["id"]
    client.push_to_cosmos()
    client.local_memory.clear()
    return {"id": memory_id}


@mcp.tool()
@traceable
def recall_memories(
    user_id: str,
    query: str,
    thread_id: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Hybrid vector+keyword recall over the user's memories.
    Returns up to top_k records ranked by relevance."""
    client = get_memory_client()

    import inspect

    params = inspect.signature(client.search_cosmos).parameters
    if "query" in params:
        hits = client.search_cosmos(
            query=query,
            user_id=user_id,
            thread_id=thread_id,
            top_k=top_k,
        )
    else:
        hits = client.search_cosmos(
            search_terms=query,
            user_id=user_id,
            thread_id=thread_id,
            top_k=top_k,
            hybrid_search=True,
        )
    return [_memory_to_dict(hit) for hit in hits]


@mcp.tool()
@traceable
def get_user_summary(user_id: str) -> Optional[Dict[str, Any]]:
    """Return the latest rolling user summary for a user, or None if not yet generated."""
    client = get_memory_client()
    summary = client.get_user_summary(user_id)
    if summary is None:
        return None
    if isinstance(summary, list):
        if not summary:
            return None
        summary = summary[0]
    return _memory_to_dict(summary)


# ============================================================================
# 4. Place Discovery Tools
# ============================================================================

@mcp.tool()
@traceable
def discover_places(
        geo_scope: str,
        query: str,
        user_id: str,
        tenant_id: str = "",
        filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Memory-aware place search with hybrid RRF retrieval (for chat assistant).
    
    Args:
        geo_scope: Geographic scope (e.g., "barcelona")
        query: Natural language search query
        user_id: User identifier (for memory alignment)
        tenant_id: Tenant identifier
        filters: Optional filters dict with:
            - type: "hotel" | "restaurant" | "attraction" (optional)
            - dietary: ["vegan", "seafood"] (optional)
            - accessibility: ["wheelchair-friendly"] (optional)
            - priceTier: "budget" | "moderate" | "luxury" (optional)
        
    Returns:
        List of places with match reasons and memory alignment scores
    """
    logger.info(f"🗺️  ========== DISCOVER_PLACES TOOL CALLED ==========")
    logger.info(f"🗺️  Parameters:")
    logger.info(f"     - geo_scope: {geo_scope}")
    logger.info(f"     - query: {query}")
    logger.info(f"     - user_id: {user_id}")
    logger.info(f"     - tenant_id: {tenant_id}")
    logger.info(f"     - filters: {filters}")

    # Parse filters
    filters = filters or {}
    place_type = filters.get("type")
    dietary = filters.get("dietary", [])
    accessibility = filters.get("accessibility", [])
    price_tier = filters.get("priceTier")

    # Convert single values to lists if needed
    if dietary and not isinstance(dietary, list):
        dietary = [dietary]
    if accessibility and not isinstance(accessibility, list):
        accessibility = [accessibility]

    logger.info(f"🔍 Parsed filters: type={place_type}, dietary={dietary}, access={accessibility}, price={price_tier}")

    # Query places using hybrid RRF search
    try:
        places = query_places_hybrid(
            query=query,
            geo_scope_id=geo_scope,
            place_type=place_type,
            dietary=dietary,
            accessibility=accessibility,
            price_tier=price_tier,
            limit=10
        )
        logger.info(f"✅ Hybrid RRF returned {len(places)} results")
    except Exception as e:
        logger.error(f"❌ Error in hybrid search: {e}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        return []

    # Memory alignment scoring using the filters the agent already provided.
    # The calling agent recalls memories BEFORE calling discover_places and
    # encodes them as filters, so we score alignment against those filters
    # instead of re-fetching memories (which would duplicate the embedding +
    # Cosmos query the agent already did).
    for place in places:
        alignment_score = 0.0
        match_reasons = ["Hybrid search match (text + semantic)"]

        # Dietary alignment from filters
        if dietary:
            place_dietary = place.get("dietary", [])
            for d in dietary:
                if d in place_dietary:
                    alignment_score += 0.3
                    match_reasons.append(f"Matches {d} dietary preference")

        # Price tier alignment from filters
        if price_tier:
            place_price = place.get("priceTier")
            if price_tier == place_price:
                alignment_score += 0.2
                match_reasons.append(f"Matches {place_price} price preference")

        # Accessibility alignment from filters
        if accessibility:
            place_access = place.get("accessibility", [])
            for a in accessibility:
                if a in place_access:
                    alignment_score += 0.3
                    match_reasons.append(f"Accessible: {a}")

        place["memoryAlignment"] = min(alignment_score, 1.0)
        place["matchReasons"] = match_reasons

    logger.info(f"✅ Returning {len(places)} places with filter-based alignment")
    return places


# ============================================================================
# 5. Trip Management Tools
# ============================================================================

@mcp.tool()
@traceable
def create_new_trip(
        user_id: str,
        tenant_id: str,
        destination: str,
        start_date: str,
        end_date: str,
        days: Optional[List[Dict[str, Any]]] = None,
        trip_duration: Optional[int] = None
) -> Dict[str, Any]:
    """
    Create a new trip itinerary.
    
    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        destination: Trip destination (e.g. "Barcelona, Spain")
        start_date: Trip start date in ISO format (e.g. "2026-03-10")
        end_date: Trip end date in ISO format (e.g. "2026-03-11")
        days: Optional list of day-by-day itinerary (dayNumber, date, morning, lunch, afternoon, dinner, accommodation)
        trip_duration: Optional total number of days (calculated from days array if not provided)
        
    Returns:
        Dictionary with tripId and details
    """
    logger.info(f"🎒 Creating trip for user: {user_id} with {len(days or [])} days")

    trip_id = create_trip(
        user_id=user_id,
        tenant_id=tenant_id,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        days=days or [],
        trip_duration=trip_duration
    )

    return {
        "tripId": trip_id,
        "destination": destination,
        "startDate": start_date,
        "endDate": end_date,
        "tripDuration": trip_duration or len(days or []),
        "daysCount": len(days or [])
    }


@mcp.tool()
@traceable
def get_trip_details(
        trip_id: str,
        user_id: str,
        tenant_id: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Get trip details by ID.
    
    Args:
        trip_id: Trip identifier
        user_id: User identifier
        tenant_id: Tenant identifier
        
    Returns:
        Trip dictionary or None if not found
    """
    logger.info(f"📋 Getting trip: {trip_id}")
    return get_trip(trip_id, user_id, tenant_id)


@mcp.tool()
@traceable
def update_trip(
        trip_id: str,
        user_id: str,
        tenant_id: str,
        updates: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Update trip details (add days, modify constraints, etc.).
    
    Args:
        trip_id: Trip identifier
        user_id: User identifier
        tenant_id: Tenant identifier
        updates: Dictionary of fields to update
        
    Returns:
        Updated trip dictionary
    """
    logger.info(f"📝 Updating trip: {trip_id}")

    # Get existing trip
    trip = get_trip(trip_id, user_id, tenant_id)
    if not trip:
        raise ValueError(f"Trip {trip_id} not found")

    # Apply updates
    trip.update(updates)

    # Save to Cosmos DB
    from src.app.services.azure_cosmos_db import trips_container
    if trips_container:
        trips_container.upsert_item(trip)

    return trip


# ============================================================================
# 6. Cross-Thread Search Tools
# ============================================================================

@mcp.tool()
@traceable
def search_user_threads(
        user_id: str,
        tenant_id: str,
        query: str,
        mode: str = "hybrid",
        since: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Hybrid search across user's conversation history.
    
    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        query: Search query
        mode: Search mode (hybrid/semantic/fulltext)
        since: Optional ISO date to filter recent conversations
        
    Returns:
        List of matches grouped by thread with scores
    """
    logger.info(f"🔍 Searching user threads for: {query}")

    from src.app.services.azure_cosmos_db import messages_container

    if not messages_container:
        return []

    # Generate query embedding for semantic search
    query_embedding = None
    if mode in ["hybrid", "semantic"]:
        try:
            query_embedding = generate_embedding(query)
        except Exception as e:
            logger.warning(f"Failed to generate query embedding: {e}")

    # Search messages (simplified - full implementation would use vector search)
    query_filter = """
    SELECT TOP 10 c.threadId, c.messageId, c.content, c.ts, c.role
    FROM c 
    WHERE c.userId = @userId 
    AND c.tenantId = @tenantId
    AND CONTAINS(LOWER(c.content), LOWER(@query))
    ORDER BY c.ts DESC
    """
    
    params = [
        {"name": "@userId", "value": user_id},
        {"name": "@tenantId", "value": tenant_id},
        {"name": "@query", "value": query},
    ]
    
    if since:
        query_filter = query_filter.replace(
            "ORDER BY",
            "AND c.ts >= @since ORDER BY"
        )
        params.append({"name": "@since", "value": since})
    
    results = list(messages_container.query_items(
        query=query_filter,
        parameters=params,
        enable_cross_partition_query=True
    ))
    
    # Group by thread
    threads_map = {}
    for msg in results:
        thread_id = msg["threadId"]
        if thread_id not in threads_map:
            threads_map[thread_id] = {
                "threadId": thread_id,
                "matches": [],
                "totalScore": 0.0
            }
        
        threads_map[thread_id]["matches"].append({
            "messageId": msg["messageId"],
            "content": msg["content"],
            "timestamp": msg["ts"],
            "role": msg["role"],
            "score": 0.8  # Placeholder
        })
        threads_map[thread_id]["totalScore"] += 0.8
    
    return list(threads_map.values())


# ============================================================================
# 7. API Event Tools
# ============================================================================

@mcp.tool()
@traceable
def record_api_call(
    session_id: str,
    tenant_id: str,
    provider: str,
    operation: str,
    request: Dict[str, Any],
    response: Dict[str, Any],
    keywords: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Store API event with auto-extracted keywords.
    
    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        provider: API provider name (e.g., "FlightsAPI")
        operation: Operation name (e.g., "search")
        request: Request parameters
        response: Response data
        keywords: Optional list of keywords
        
    Returns:
        Dictionary with eventId and metadata
    """
    logger.info(f"📡 Recording API call: {provider}.{operation}")
    
    event_id = record_api_event(
        session_id=session_id,
        tenant_id=tenant_id,
        provider=provider,
        operation=operation,
        request=request,
        response=response,
        keywords=keywords
    )
    
    return {
        "eventId": event_id,
        "provider": provider,
        "operation": operation
    }


# ============================================================================
# 9. Agent Transfer Tools (for Orchestrator Routing)
# ============================================================================

@mcp.tool()
@traceable
def transfer_to_hotel(
    reason: str
) -> str:
    """
    Transfer conversation to the Hotel Agent.
    
    Use this when:
    - User wants to search for hotels or accommodations
    - User is sharing hotel/lodging preferences (boutique, quiet, central, etc.)
    - User asks about places to stay
    
    Examples:
    - "Find hotels in Paris"
    - "I prefer quiet hotels away from tourist areas"
    - "Where should I stay?"
    
    Args:
        reason: Why you're transferring to this agent
        
    Returns:
        JSON with goto field for routing
    """
    
    logger.info(f"🔄 Transfer to Hotel Agent: {reason}")
    
    return json.dumps({
        "goto": "hotel",
        "reason": reason,
        "message": "Transferring to Hotel Agent to find accommodations for you."
    })


@mcp.tool()
@traceable
def transfer_to_activity(
    reason: str
) -> str:
    """
    Transfer conversation to the Activity Agent.
    
    Use this when:
    - User wants to discover attractions, museums, landmarks
    - User is sharing activity preferences (art, history, nature, etc.)
    - User asks about things to do or see
    
    Examples:
    - "What should I do in Barcelona?"
    - "Find art museums"
    - "I love history and architecture"
    
    Args:
        reason: Why you're transferring to this agent
        
    Returns:
        JSON with goto field for routing
    """
    
    logger.info(f"🔄 Transfer to Activity Agent: {reason}")
    
    return json.dumps({
        "goto": "activity",
        "reason": reason,
        "message": "Transferring to Activity Agent to discover attractions for you."
    })


@mcp.tool()
@traceable
def transfer_to_dining(
    reason: str
) -> str:
    """
    Transfer conversation to the Dining Agent.
    
    Use this when:
    - User wants restaurant or cafe recommendations
    - User is sharing dietary preferences or cuisine interests
    - User asks where to eat
    
    Examples:
    - "Find vegetarian restaurants"
    - "I'm pescatarian and like local bistros"
    - "Where should I have dinner?"
    
    Args:
        reason: Why you're transferring to this agent
        
    Returns:
        JSON with goto field for routing
    """
    
    logger.info(f"🔄 Transfer to Dining Agent: {reason}")
    
    return json.dumps({
        "goto": "dining",
        "reason": reason,
        "message": "Transferring to Dining Agent to find restaurants for you."
    })


@mcp.tool()
@traceable
def transfer_to_itinerary_generator(
    reason: str
) -> str:
    """
    Transfer conversation to the Itinerary Generator agent.
    
    Use this when:
    - User explicitly requests an itinerary or day-by-day plan
    - User says "create itinerary", "plan my days", "generate schedule"
    - User wants a complete trip plan synthesized
    
    Examples:
    - "Create an itinerary for my trip"
    - "Plan my 4 days in Paris"
    - "Generate a schedule with everything we discussed"
    
    Args:
        reason: Why you're transferring to this agent
        
    Returns:
        JSON with goto field for routing
    """
    
    logger.info(f"🔄 Transfer to Itinerary Generator: {reason}")
    
    return json.dumps({
        "goto": "itinerary_generator",
        "reason": reason,
        "message": "Transferring to Itinerary Generator to create your day-by-day plan."
    })


@mcp.tool()
@traceable
def transfer_to_orchestrator(
    reason: str
) -> str:
    """
    Transfer conversation back to the Orchestrator agent.
    
    Use this when:
    - Task is complete and user needs general assistance
    - User has a new question that doesn't fit specialized agents
    - General conversation, greetings, clarifications needed
    
    Examples:
    - After completing a specific task
    - User says "Thanks" or changes topic
    - User asks general questions about the system
    
    Args:
        reason: Why you're transferring to this agent
        
    Returns:
        JSON with goto field for routing
    """
    
    logger.info(f"🔄 Transfer to Orchestrator: {reason}")
    
    return json.dumps({
        "goto": "orchestrator",
        "reason": reason,
        "message": "Transferring back to Orchestrator for general assistance."
    })


# ============================================================================
# Server Startup
# ============================================================================

if __name__ == "__main__":
    print("Starting Travel Assistant MCP server...")

    # Configure server options
    server_options = {
        "transport": "streamable-http"
    }

    print("🔓 Starting server without built-in authentication...")
    print("💡 For OAuth, use a reverse proxy like nginx or API gateway")

    try:
        mcp.run(**server_options)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)

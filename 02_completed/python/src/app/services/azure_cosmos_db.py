import logging
import os
import uuid
from datetime import UTC, datetime
from typing import List, Dict, Optional, Any
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.aio import CosmosClient as AsyncCosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from dotenv import load_dotenv
from langchain_azure_cosmosdb import CosmosDBSaver
from langsmith import traceable

from src.app.services.azure_open_ai import generate_embedding, extract_keywords

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv(override=False)

# Azure Cosmos DB configuration
COSMOS_DB_URL = os.getenv("COSMOSDB_ENDPOINT")
COSMOS_DB_KEY = os.getenv("COSMOSDB_KEY")
DATABASE_NAME = os.getenv("COSMOSDB_DATABASE_NAME", "TravelAssistant")
checkpoint_container = "Checkpoints"

# Global client variables
cosmos_client = None
database = None

# Container clients - for both MCP server and agent use
sessions_container = None
messages_container = None
api_events_container = None
debug_logs_container = None
places_container = None
trips_container = None
users_container = None

# Async client globals for the LangGraph checkpointer.
# langchain-azure-cosmosdb CosmosDBSaver is async-only and requires an
# AsyncContainerProxy, so we keep a parallel AsyncCosmosClient alive for
# the app lifetime.
_async_cosmos_client = None
_async_credential = None
_async_checkpoint_container = None
_checkpoint_saver = None


def initialize_cosmos_client():
    """Initialize the Cosmos DB client and all containers"""
    global cosmos_client, database
    global sessions_container, messages_container
    global api_events_container, debug_logs_container, places_container, trips_container, users_container
    
    if cosmos_client is None:
        try:
            credential = DefaultAzureCredential()
            cosmos_client = CosmosClient(COSMOS_DB_URL, credential=credential)
            logger.info(f"✅ Connected to Cosmos DB successfully using DefaultAzureCredential.")
        except Exception as dac_error:
            logger.error(f"❌ Failed to authenticate using DefaultAzureCredential: {dac_error}")
            logger.warning("⚠️ Continuing without Cosmos DB client - some features may not work")
            return

        # Initialize database and containers
        try:
            database = cosmos_client.get_database_client(DATABASE_NAME)
            logger.info(f"✅ Connected to database: {DATABASE_NAME}")

            # Initialize all containers (using PascalCase names to match Bicep)
            sessions_container = database.get_container_client("Sessions")
            messages_container = database.get_container_client("Messages")
            api_events_container = database.get_container_client("ApiEvents")
            debug_logs_container = database.get_container_client("Debug")
            places_container = database.get_container_client("Places")
            trips_container = database.get_container_client("Trips")
            users_container = database.get_container_client("Users")
            
            logger.info("✅ All Cosmos DB containers initialized")
        except Exception as e:
            logger.error(f"❌ Error initializing Cosmos DB containers: {e}")
            logger.warning("⚠️ Continuing without containers - some features may not work")


# Initialize on import
try:
    initialize_cosmos_client()
except Exception as e:
    logger.warning(f"⚠️ Failed to initialize Cosmos DB client during import: {e}")


def is_cosmos_available():
    """Check if Cosmos DB is available"""
    return all([
        sessions_container, messages_container,
        api_events_container, debug_logs_container, places_container, trips_container, users_container
    ])


def get_cosmos_client():
    """Return the initialized Cosmos client"""
    return cosmos_client


async def aget_checkpoint_saver():
    """Return the async CosmosDBSaver, initializing it on first call.

    Idempotent: subsequent calls return the cached saver. Call
    ``close_async_cosmos_client()`` at shutdown to release the underlying
    async client and credential cleanly. Falls back to MemorySaver if the
    async Cosmos client cannot be created.
    """
    global _async_cosmos_client, _async_credential, _async_checkpoint_container, _checkpoint_saver

    if _checkpoint_saver is not None:
        return _checkpoint_saver

    try:
        if COSMOS_DB_KEY:
            _async_cosmos_client = AsyncCosmosClient(COSMOS_DB_URL, credential=COSMOS_DB_KEY)
        else:
            _async_credential = AsyncDefaultAzureCredential()
            _async_cosmos_client = AsyncCosmosClient(COSMOS_DB_URL, credential=_async_credential)

        db = await _async_cosmos_client.create_database_if_not_exists(DATABASE_NAME)
        _async_checkpoint_container = await db.create_container_if_not_exists(
            id=checkpoint_container,
            partition_key=PartitionKey(path="/partition_key"),
        )
        _checkpoint_saver = CosmosDBSaver(_async_checkpoint_container)
        logger.info(f"✅ CosmosDBSaver initialized on container: {checkpoint_container}")
        return _checkpoint_saver
    except Exception as e:
        logger.warning(f"Failed to create async CosmosDBSaver: {e}")
        logger.warning("Using MemorySaver for checkpoint persistence (data will not persist)")
        from langgraph.checkpoint.memory import MemorySaver
        _checkpoint_saver = MemorySaver()
        return _checkpoint_saver


async def close_async_cosmos_client():
    """Release the async client and credential on app shutdown."""
    global _async_cosmos_client, _async_credential, _async_checkpoint_container, _checkpoint_saver
    if _async_cosmos_client is not None:
        try:
            await _async_cosmos_client.close()
        except Exception as e:
            logger.warning(f"Error closing async Cosmos client: {e}")
        _async_cosmos_client = None
    if _async_credential is not None:
        try:
            await _async_credential.close()
        except Exception as e:
            logger.warning(f"Error closing async credential: {e}")
        _async_credential = None
    _async_checkpoint_container = None
    _checkpoint_saver = None


async def adelete_checkpoints_for_thread(thread_id: str) -> int:
    """Delete every checkpoint document associated with a LangGraph thread.

    ``CosmosDBSaver.adelete_thread()`` raises ``NotImplementedError`` in
    langchain-azure-cosmosdb v1.0.0, so we issue the query + delete loop
    ourselves against the async container. Returns the number of documents
    deleted.
    """
    if _async_checkpoint_container is None:
        logger.warning("Checkpoint container not initialized — skipping checkpoint delete")
        return 0

    deleted = 0
    query = "SELECT c.id, c.partition_key FROM c WHERE CONTAINS(c.partition_key, @sessionId)"
    params = [{"name": "@sessionId", "value": thread_id}]
    async for item in _async_checkpoint_container.query_items(query=query, parameters=params):
        try:
            await _async_checkpoint_container.delete_item(
                item=item["id"],
                partition_key=item["partition_key"],
            )
            deleted += 1
        except Exception as e:
            logger.warning(f"Failed to delete checkpoint {item.get('id')}: {e}")
    return deleted


# ============================================================================
# Agent-Specific Functions (for travel_agents.py)
# ============================================================================

def update_session_container(session_doc: dict):
    """
    Create or update a session document in the sessions container.
    Used for initializing sessions in local testing mode.
    """
    if sessions_container is None:
        logger.warning("Sessions container not initialized")
        return
    
    try:
        sessions_container.upsert_item(session_doc)
        logger.info(f"Session document upserted: {session_doc.get('id')}")
    except Exception as e:
        logger.error(f"Error upserting session document: {e}")
        raise


def patch_active_agent(tenantId: str, userId: str, sessionId: str, activeAgent: str):
    """
    Patch the active agent field in the sessions' container.
    Uses Cosmos DB 'set' operation which creates or replaces the field
    in a single round trip (no read-before-write needed).
    """
    if sessions_container is None:
        logger.warning("Sessions container not initialized")
        return
    
    try:
        pk = [tenantId, userId, sessionId]
        operations = [
            {'op': 'set', 'path': '/activeAgent', 'value': activeAgent}
        ]
        sessions_container.patch_item(
            item=sessionId, 
            partition_key=pk,
            patch_operations=operations
        )
        logger.info(f"✅ Patched active agent to '{activeAgent}' for session: {sessionId}")
    except Exception as e:
        logger.error(f"❌ Error patching active agent for session {sessionId}: {e}")


# ============================================================================
# MCP Tool Functions (for mcp_http_server.py)
# ============================================================================
@traceable
def create_session_record(user_id: str, tenant_id: str, activeAgent: str, title: str = None) -> Dict[str, Any]:
    """Create a new session record"""
    if not sessions_container:
        raise Exception("Cosmos DB not available")
    
    session_id = f"session_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)
    
    session = {
        "id": session_id,
        "sessionId": session_id,
        "tenantId": tenant_id,
        "userId": user_id,
        "title": title or "New Conversation",
        "activeAgent": activeAgent,
        "createdAt": now.isoformat(),
        "lastActivityAt": now.isoformat(),
        "status": "active",
        "messageCount": 0
    }
    
    sessions_container.upsert_item(session)
    logger.info(f"✅ Created session: {session_id}")
    return session


@traceable(run_type="retriever")
def get_session_by_id(session_id: str, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Get session by ID using point read (partition key known)"""
    if not sessions_container:
        raise Exception("Cosmos DB not available")
    
    try:
        return sessions_container.read_item(
            item=session_id,
            partition_key=[tenant_id, user_id, session_id]
        )
    except CosmosResourceNotFoundError:
        logger.debug(f"Session not found: {session_id}")
        return None
    except Exception as e:
        logger.error(f"Error reading session {session_id}: {e}")
        return None


@traceable
def update_session_activity(session_id: str, tenant_id: str, user_id: str, message_count: int = 1):
    """Update session's last activity timestamp using patch (single round trip)"""
    if not sessions_container:
        return
    
    try:
        pk = [tenant_id, user_id, session_id]
        operations = [
            {'op': 'set', 'path': '/lastActivityAt', 'value': datetime.now(UTC).isoformat()},
            {'op': 'incr', 'path': '/messageCount', 'value': message_count}
        ]
        sessions_container.patch_item(
            item=session_id,
            partition_key=pk,
            patch_operations=operations
        )
    except Exception as e:
        logger.error(f"Error updating session activity: {e}")


# ============================================================================
# Message Management Functions
# ============================================================================
@traceable
def append_message(
    session_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    content: str,
    tool_calls: Optional[List[Dict]] = None,
) -> str:
    """
    Append a message to a session.
    Keywords are extracted locally (no LLM call) and stored with the message.
    Message embeddings are not generated or stored; they can be backfilled
    later if needed for semantic search.
    
    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        role: Message role ("user" or "assistant")
        content: Message content text
        tool_calls: Optional list of tool calls made by the assistant
    
    Returns:
        str: The generated message ID
    """
    if not messages_container:
        raise Exception("Cosmos DB not available")
    
    # Keywords extracted via lightweight regex (no LLM call after perf fix)
    keywords = extract_keywords(content)
    
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)
    
    message = {
        "id": message_id,
        "messageId": message_id,
        "sessionId": session_id,
        "tenantId": tenant_id,
        "userId": user_id,
        "role": role,
        "content": content,
        "toolCalls": tool_calls or [],
        "ts": now.isoformat(),
        "keywords": keywords or [],
        "superseded": False
    }
    
    messages_container.upsert_item(message)
    
    logger.info(f"✅ Appended message: {message_id} to session: {session_id}")
    return message_id


@traceable(run_type="retriever")
def get_message_by_id(
    message_id: str,
    session_id: str,
    tenant_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """Get a specific message by its ID"""
    if not messages_container:
        return None
    
    try:
        query = """
        SELECT * FROM c 
        WHERE c.messageId = @messageId
        AND c.sessionId = @sessionId 
        AND c.tenantId = @tenantId 
        AND c.userId = @userId
        """
        
        items = list(messages_container.query_items(
            query=query,
            parameters=[
                {"name": "@messageId", "value": message_id},
                {"name": "@sessionId", "value": session_id},
                {"name": "@tenantId", "value": tenant_id},
                {"name": "@userId", "value": user_id}
            ],
            partition_key=[tenant_id, user_id, session_id]
        ))
        
        return items[0] if items else None
    except Exception as e:
        logger.error(f"Error getting message {message_id}: {e}")
        return None


@traceable(run_type="retriever")
def get_session_messages(
    session_id: str,
    tenant_id: str,
    user_id: str,
    include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """Get messages for a session"""
    if not messages_container:
        return []
    
    superseded_filter = "" if include_superseded else "AND (NOT IS_DEFINED(c.superseded) OR c.superseded = false)"
    
    query = f"""
    SELECT * FROM c 
    WHERE c.sessionId = @sessionId 
    AND c.tenantId = @tenantId 
    AND c.userId = @userId
    {superseded_filter}
    ORDER BY c.ts DESC
    """
    
    items = list(messages_container.query_items(
        query=query,
        parameters=[
            {"name": "@sessionId", "value": session_id},
            {"name": "@tenantId", "value": tenant_id},
            {"name": "@userId", "value": user_id}
        ],
        partition_key=[tenant_id, user_id, session_id]
    ))
    
    return items


@traceable(run_type="retriever")
def count_active_messages(
    session_id: str,
    tenant_id: str,
    user_id: str
) -> int:
    """
    Count non-superseded, non-summary messages for a session.
    Used to determine when auto-summarization should trigger.
    """
    if not messages_container:
        return 0
    
    try:
        query = """
        SELECT VALUE COUNT(1)
        FROM c 
        WHERE c.sessionId = @sessionId 
        AND c.tenantId = @tenantId 
        AND c.userId = @userId
        AND (NOT IS_DEFINED(c.superseded) OR c.superseded = false)
        AND (NOT IS_DEFINED(c.isSummary) OR c.isSummary = false)
        """
        
        params = [
            {"name": "@sessionId", "value": session_id},
            {"name": "@tenantId", "value": tenant_id}, 
            {"name": "@userId", "value": user_id}
        ]
        
        results = list(messages_container.query_items(
            query=query, 
            parameters=params,
            partition_key=[tenant_id, user_id, session_id]
        ))
        
        count = results[0] if results else 0
        logger.info(f"📊 Active message count for session {session_id}: {count}")
        return count
        
    except Exception as e:
        logger.error(f"Error counting active messages: {e}")
        return 0


# ============================================================================
# Place Discovery Functions
# ============================================================================
@traceable(run_type="retriever")
def query_places_hybrid(
    query: str,
    geo_scope_id: str,
    place_type: Optional[str] = None,
    dietary: Optional[List[str]] = None,
    accessibility: Optional[List[str]] = None,
    price_tier: Optional[str] = None,
    limit: int = 5,
    user_preference_vector: list[float] | None = None
) -> List[Dict[str, Any]]:
    """Query places with filters including array-based filters (dietary, accessibility, tags)"""
    logger.info(f"🔍 ========== QUERY_PLACES CALLED ==========")
    logger.info(f"🔍 Parameters:")
    logger.info(f"     - geo_scope_id: {geo_scope_id}")
    logger.info(f"     - place_type: {place_type}")
    logger.info(f"     - dietary: {dietary}")
    logger.info(f"     - accessibility: {accessibility}")
    logger.info(f"     - price_tier: {price_tier}")
    
    if not places_container:
        logger.error(f"❌ places_container is None! Cosmos DB not initialized properly.")
        return []
    
    # Extract keywords from query for tags
    keywords = extract_keywords(query)
    keywords_str = ", ".join([f'"{kw}"' for kw in keywords[:5]])  # Limit to 5 keywords
    
    # Generate embedding from query
    embedding = generate_embedding(query)
    
    # Build WHERE clause dynamically
    geo_scope_id = geo_scope_id.lower().strip()
    where_clauses = ["c.geoScopeId = @geoScopeId"]
    params = [
        {"name": "@geoScopeId", "value": geo_scope_id},
        {"name": "@embedding", "value": embedding},
        {"name": "@limit", "value": limit}
    ]
    
    if place_type:
        where_clauses.append("c.type = @type")
        params.append({"name": "@type", "value": place_type})
    
    if price_tier:
        where_clauses.append("c.priceTier = @priceTier")
        params.append({"name": "@priceTier", "value": price_tier})
    
    where_clause = " AND ".join(where_clauses)
    
    # Build FullTextScore clauses for RRF
    fulltext_clauses = []
    
    # Always include tags with keywords
    if keywords_str:
        fulltext_clauses.append(f"FullTextScore(c.tags, {keywords_str})")
    
    # Add dietary FullTextScore if provided
    if dietary and len(dietary) > 0:
        dietary_str = ", ".join([f'"{d}"' for d in dietary])
        fulltext_clauses.append(f"FullTextScore(c.dietary, {dietary_str})")
    
    # Add accessibility FullTextScore if provided
    if accessibility and len(accessibility) > 0:
        access_str = ", ".join([f'"{a}"' for a in accessibility])
        fulltext_clauses.append(f"FullTextScore(c.accessibility, {access_str})")
    
    # Always include VectorDistance
    fulltext_clauses.append("VectorDistance(c.embedding, @embedding)")
    if user_preference_vector is not None:
        # Places embeddings are 1536-dim; user_preference_vector from toolkit
        # may be 1536-dim. Only include in RRF if dimensions match.
        if len(user_preference_vector) == len(embedding):
            fulltext_clauses.append("VectorDistance(c.embedding, @pref_vector)")
            params.append({"name": "@pref_vector", "value": user_preference_vector})
        else:
            logger.warning(
                "Skipping user_preference_vector in RRF: dim %d != places dim %d",
                len(user_preference_vector), len(embedding),
            )
    
    rrf_clause = ", ".join(fulltext_clauses)
    
    # Build hybrid RRF query
    query_sql = f"""
    SELECT TOP @limit 
        c.id, c.geoScopeId, c.name, c.type, c.description, 
        c.tags, c.dietary, c.accessibility, c.hours, 
        c.neighborhood, c.priceTier, c.rating,
        VectorDistance(c.embedding, @embedding) AS similarityScore
    FROM c
    WHERE {where_clause}
    ORDER BY RANK RRF({rrf_clause})
    """
    
    logger.info(f"📝 Hybrid RRF Query: {query_sql}...")
    
    try:
        items = list(places_container.query_items(
            query=query_sql,
            parameters=params,
            partition_key=geo_scope_id
        ))
        logger.info(f"✅ Returned {len(items)} items")
        return items
    except Exception as ex:
        logger.error(f"❌ Error in hybrid search: {ex}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        return []


@traceable(run_type="retriever")
def query_places_with_theme(
    theme: str,
    geo_scope_id: str,
    place_type: Optional[str] = None,
    dietary: Optional[List[str]] = None,
    accessibility: Optional[List[str]] = None,
    price_tier: Optional[List[str]] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """
    Filtered vector search with theme (Explore page with theme text).
    
    Args:
        theme: Theme text (e.g., "romantic waterfront dining")
        geo_scope_id: City/location (required)
        place_type: Optional type filter
        dietary: Optional dietary filters
        accessibility: Optional accessibility filters
        price_tier: Optional price tier filter
        limit: Maximum results
        
    Returns:
        List of places ranked by vector similarity with filters
    """
    logger.info(f"🎨 ========== THEME VECTOR SEARCH (EXPLORE) ==========")
    logger.info(f"     Theme: {theme}")
    logger.info(f"     City: {geo_scope_id}")
    
    if not places_container:
        return []
    
    # Import here to avoid circular dependency
    from src.app.services.azure_open_ai import generate_embedding, extract_keywords
    
    # Extract keywords from theme for tags filter
    keywords = extract_keywords(theme)
    keywords_str = ", ".join([f'"{kw}"' for kw in keywords[:5]])  # Limit to 5 keywords
    
    # Generate embedding from theme
    embedding = generate_embedding(theme)
    
    # Build WHERE clause dynamically
    geo_scope_id = geo_scope_id.lower().strip()
    where_clauses = ["c.geoScopeId = @geoScopeId"]
    params = [
        {"name": "@geoScopeId", "value": geo_scope_id},
        {"name": "@embedding", "value": embedding},
        {"name": "@limit", "value": limit}
    ]
    
    if place_type:
        where_clauses.append("c.type = @type")
        params.append({"name": "@type", "value": place_type})
    
    if price_tier and len(price_tier) > 0:
        price_tier_conditions = []
        for i, pt in enumerate(price_tier):
            price_tier_conditions.append(f"c.priceTier = @priceTier{i}")
            params.append({"name": f"@priceTier{i}", "value": pt})
        where_clauses.append(f"({' OR '.join(price_tier_conditions)})")

    
    if dietary and len(dietary) > 0:
        dietary_conditions = []
        for i, diet in enumerate(dietary):
            dietary_conditions.append(f"ARRAY_CONTAINS(c.dietary, @dietary{i})")
            params.append({"name": f"@dietary{i}", "value": diet})
        where_clauses.append(f"({' OR '.join(dietary_conditions)})")
    
    if accessibility and len(accessibility) > 0:
        accessibility_conditions = []
        for i, feature in enumerate(accessibility):
            accessibility_conditions.append(f"ARRAY_CONTAINS(c.accessibility, @accessibility{i})")
            params.append({"name": f"@accessibility{i}", "value": feature})
        where_clauses.append(f"({' OR '.join(accessibility_conditions)})")
    
    # Add tags filter from theme keywords
    if keywords:
        tags_conditions = []
        for i, kw in enumerate(keywords[:5]):  # Limit to 5 keywords
            tags_conditions.append(f"ARRAY_CONTAINS(c.tags, @tag{i})")
            params.append({"name": f"@tag{i}", "value": kw})
        where_clauses.append(f"({' OR '.join(tags_conditions)})")
    
    where_clause = " AND ".join(where_clauses)

    # Build FullTextScore clauses for RRF
    fulltext_clauses = []
    
    # Always include tags with keywords
    if keywords_str:
        fulltext_clauses.append(f"FullTextScore(c.tags, {keywords_str})")

    # Always include VectorDistance
    fulltext_clauses.append("VectorDistance(c.embedding, @embedding)")
    
    rrf_clause = ", ".join(fulltext_clauses)    

    
    query_sql = f"""
    SELECT TOP @limit 
        c.id, c.geoScopeId, c.name, c.type, c.description, 
        c.tags, c.dietary, c.accessibility, c.hours, 
        c.neighborhood, c.priceTier, c.rating,
        c.hotelSpecific, c.restaurantSpecific, c.activitySpecific,
        VectorDistance(c.embedding, @embedding) AS similarityScore
    FROM c
    WHERE {where_clause}
    ORDER BY RANK RRF({rrf_clause})
    """
    
    logger.info(f"📝 Theme Vector Query: {query_sql}...")
    
    try:
        items = list(places_container.query_items(
            query=query_sql,
            parameters=params,
            partition_key=geo_scope_id
        ))
        logger.info(f"✅ Returned {len(items)} items")
        return items
    except Exception as ex:
        logger.error(f"❌ Error in theme search: {ex}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        return []


@traceable(run_type="retriever")
def query_places_filtered(
    geo_scope_id: str,
    place_type: Optional[str] = None,
    dietary: Optional[List[str]] = None,
    accessibility: Optional[List[str]] = None,
    price_tier: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Simple filtered search without theme (Explore page filters only).
    
    Args:
        geo_scope_id: City/location (required)
        place_type: Optional type filter
        dietary: Optional dietary filters
        accessibility: Optional accessibility filters
        price_tier: Optional price tier filter
        limit: Maximum results (default: 100 for browse)
        
    Returns:
        List of places filtered and sorted by rating
    """
    logger.info(f"🔍 ========== FILTERED SEARCH (EXPLORE) ==========")
    logger.info(f"     City: {geo_scope_id}")
    
    if not places_container:
        return []
    
    # Build WHERE clause dynamically
    geo_scope_id = geo_scope_id.lower().strip()
    where_clauses = ["c.geoScopeId = @geoScopeId"]
    params = [
        {"name": "@geoScopeId", "value": geo_scope_id}
    ]
    
    if place_type:
        where_clauses.append("c.type = @type")
        params.append({"name": "@type", "value": place_type})
    
    if price_tier and len(price_tier) > 0:
        price_tier_conditions = []
        for i, pt in enumerate(price_tier):
            price_tier_conditions.append(f"c.priceTier = @priceTier{i}")
            params.append({"name": f"@priceTier{i}", "value": pt})
        where_clauses.append(f"({' OR '.join(price_tier_conditions)})")
    
    if dietary and len(dietary) > 0:
        dietary_conditions = []
        for i, diet in enumerate(dietary):
            dietary_conditions.append(f"ARRAY_CONTAINS(c.dietary, @dietary{i})")
            params.append({"name": f"@dietary{i}", "value": diet})
        where_clauses.append(f"({' OR '.join(dietary_conditions)})")
    
    if accessibility and len(accessibility) > 0:
        accessibility_conditions = []
        for i, feature in enumerate(accessibility):
            accessibility_conditions.append(f"ARRAY_CONTAINS(c.accessibility, @accessibility{i})")
            params.append({"name": f"@accessibility{i}", "value": feature})
        where_clauses.append(f"({' OR '.join(accessibility_conditions)})")
    
    where_clause = " AND ".join(where_clauses)
    
    query_sql = f"""
    SELECT 
        c.id, c.geoScopeId, c.name, c.type, c.description, 
        c.tags, c.dietary, c.accessibility, c.hours, 
        c.neighborhood, c.priceTier, c.rating,
        c.hotelSpecific, c.restaurantSpecific, c.activitySpecific
    FROM c
    WHERE {where_clause}
    ORDER BY c.rating DESC
    """
    
    logger.info(f"📝 Filtered Query: {query_sql[:200]}...")
    
    try:
        items = list(places_container.query_items(
            query=query_sql,
            parameters=params,
            partition_key=geo_scope_id
        ))
        logger.info(f"✅ Returned {len(items)} items")
        return items
    except Exception as ex:
        logger.error(f"❌ Error querying places: {ex}")
        logger.error(f"❌ Exception type: {type(ex).__name__}")
        import traceback
        logger.error(f"❌ Full traceback:\n{traceback.format_exc()}")
        raise ex


# ============================================================================
# Trip Management Functions
# ============================================================================
@traceable
def create_trip(
    user_id: str,
    tenant_id: str,
    destination: str,
    start_date: str,
    end_date: str,
    days: Optional[List[Dict[str, Any]]] = None,
    trip_duration: Optional[int] = None
) -> str:
    """Create a new trip"""
    if not trips_container:
        raise Exception("Cosmos DB not available")
    
    # Generate a short destination slug for the trip ID
    dest_slug = destination.lower().split(",")[0].strip().replace(" ", "_")[:15]
    trip_id = f"trip_{user_id}_{dest_slug}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    
    # Calculate trip duration from days array if not provided
    if trip_duration is None and days:
        trip_duration = len(days)
    
    trip = {
        "id": trip_id,
        "tripId": trip_id,
        "userId": user_id,
        "tenantId": tenant_id,
        "destination": destination,
        "startDate": start_date,
        "endDate": end_date,
        "tripDuration": trip_duration,
        "days": days or [],
        "status": "planning",
        "createdAt": datetime.utcnow().isoformat() + "Z"
    }
    
    trips_container.upsert_item(trip)
    logger.info(f"✅ Created trip: {trip_id} with {trip_duration} days")
    return trip_id


@traceable(run_type="retriever")
def get_trip(trip_id: str, user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get a trip by ID using point read"""
    if not trips_container:
        return None
    
    try:
        return trips_container.read_item(
            item=trip_id,
            partition_key=[tenant_id, user_id, trip_id]
        )
    except CosmosResourceNotFoundError:
        logger.debug(f"Trip not found: {trip_id}")
        return None
    except Exception as e:
        logger.error(f"Error reading trip {trip_id}: {e}")
        return None


# ============================================================================
# User Management Functions
# ============================================================================
@traceable
def create_user(
    user_id: str,
    tenant_id: str,
    name: str,
    gender: Optional[str] = None,
    age: Optional[int] = None,
    phone: Optional[str] = None,
    address: Optional[Dict[str, Any]] = None,
    email: Optional[str] = None
) -> str:
    """Create a new user"""
    if not users_container:
        raise Exception("Cosmos DB users container not available")
    
    now = datetime.now(UTC)
    
    user = {
        "id": user_id,
        "userId": user_id,
        "tenantId": tenant_id,
        "name": name,
        "gender": gender,
        "age": age,
        "phone": phone,
        "address": address or {},
        "email": email,
        "createdAt": now.isoformat()
    }
    
    users_container.upsert_item(user)
    logger.info(f"✅ Created user: {user_id} ({name})")
    return user_id


@traceable(run_type="retriever")
def get_all_users(tenant_id: str) -> List[Dict[str, Any]]:
    """Get all users for a tenant"""
    if not users_container:
        return []
    
    try:
        query = """
        SELECT * FROM c 
        WHERE c.tenantId = @tenantId
        ORDER BY c.createdAt DESC
        """
        items = list(users_container.query_items(
            query=query,
            parameters=[
                {"name": "@tenantId", "value": tenant_id}
            ],
            enable_cross_partition_query=True
        ))
        logger.info(f"✅ Retrieved {len(items)} users for tenant: {tenant_id}")
        return items
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return []


@traceable(run_type="retriever")
def get_user_by_id(user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get a user by ID using point read"""
    if not users_container:
        return None
    
    try:
        user = users_container.read_item(
            item=user_id,
            partition_key=user_id
        )
        # Validate tenant isolation
        if user.get("tenantId") != tenant_id:
            logger.warning(f"⚠️  Tenant mismatch for user {user_id}: expected {tenant_id}")
            return None
        logger.info(f"✅ Retrieved user: {user_id}")
        return user
    except CosmosResourceNotFoundError:
        logger.warning(f"⚠️  User not found: {user_id}")
        return None
    except Exception as e:
        logger.error(f"Error reading user {user_id}: {e}")
        return None


# ============================================================================
# API Event Functions
# ============================================================================

def record_api_event(
    session_id: str,
    tenant_id: str,
    provider: str,
    operation: str,
    request: Dict[str, Any],
    response: Dict[str, Any],
    keywords: Optional[List[str]] = None
) -> str:
    """Record an API event"""
    if not api_events_container:
        raise Exception("Cosmos DB not available")
    
    event_id = f"api_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)
    
    event = {
        "id": event_id,
        "eventId": event_id,
        "sessionId": session_id,
        "tenantId": tenant_id,
        "provider": provider,
        "operation": operation,
        "request": request,
        "response": response,
        "ts": now.isoformat(),
        "keywords": keywords or []
    }
    
    api_events_container.upsert_item(event)
    logger.info(f"✅ Recorded API event: {event_id} ({provider}.{operation})")
    return event_id


# ============================================================================
# Debug Logs
# ============================================================================

def store_debug_log(
    session_id: str,
    tenant_id: str,
    user_id: str,
    agent_selected: str = "Unknown",
    previous_agent: str = "Unknown",
    finish_reason: str = "Unknown",
    model_name: str = "Unknown",
    system_fingerprint: str = "Unknown",
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    cached_tokens: int = 0,
    transfer_success: bool = False,
    tool_calls: List[Dict[str, Any]] = None,
    logprobs: Optional[Dict[str, Any]] = None,
    content_filter_results: Optional[Dict[str, Any]] = None,
    debug_log_id: Optional[str] = None,
    agent_path: Optional[str] = None,
    handoff_count: Optional[int] = None
) -> str:
    """
    Store detailed debug log information in Cosmos DB.
    
    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        agent_selected: Name of the agent that handled the request
        previous_agent: Name of the previous agent (for transfers)
        finish_reason: Reason for completion (stop, length, etc.)
        model_name: Name of the LLM model used
        system_fingerprint: System fingerprint from the model
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens generated
        total_tokens: Total tokens used
        cached_tokens: Number of cached tokens
        transfer_success: Whether agent transfer was successful
        tool_calls: List of tool calls made during execution
        logprobs: Log probabilities from the model
        content_filter_results: Content filtering results
    
    Returns:
        Debug log ID
    """
    if not debug_logs_container:
        raise Exception("Debug logs container not available")
    
    if not debug_log_id:
        debug_log_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    timestamp = datetime.now(UTC).isoformat()
    
    property_bag = [
        {"key": "agent_selected", "value": agent_selected, "timeStamp": timestamp},
        {"key": "previous_agent", "value": previous_agent, "timeStamp": timestamp},
        {"key": "finish_reason", "value": finish_reason, "timeStamp": timestamp},
        {"key": "model_name", "value": model_name, "timeStamp": timestamp},
        {"key": "system_fingerprint", "value": system_fingerprint, "timeStamp": timestamp},
        {"key": "input_tokens", "value": input_tokens, "timeStamp": timestamp},
        {"key": "output_tokens", "value": output_tokens, "timeStamp": timestamp},
        {"key": "total_tokens", "value": total_tokens, "timeStamp": timestamp},
        {"key": "cached_tokens", "value": cached_tokens, "timeStamp": timestamp},
        {"key": "transfer_success", "value": transfer_success, "timeStamp": timestamp},
        {"key": "tool_calls", "value": str(tool_calls or []), "timeStamp": timestamp},
        {"key": "logprobs", "value": str(logprobs or {}), "timeStamp": timestamp},
        {"key": "content_filter_results", "value": str(content_filter_results or {}), "timeStamp": timestamp}
    ]

    # Agent hand-off analytics (supervisor -> sub-agent delegations)
    if agent_path is not None:
        property_bag.append({"key": "agent_path", "value": agent_path, "timeStamp": timestamp})
    if handoff_count is not None:
        property_bag.append({"key": "handoff_count", "value": handoff_count, "timeStamp": timestamp})
    
    debug_entry = {
        "id": debug_log_id,
        "debugLogId": debug_log_id,
        "messageId": message_id,
        "type": "debug_log",
        "sessionId": session_id,
        "tenantId": tenant_id,
        "userId": user_id,
        "timeStamp": timestamp,
        "propertyBag": property_bag
    }
    
    debug_logs_container.upsert_item(debug_entry)
    logger.info(f"✅ Stored debug log: {debug_log_id} (agent: {agent_selected}, tokens: {total_tokens})")
    return debug_log_id


def get_debug_log(debug_log_id: str, tenant_id: str, user_id: str, session_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a debug log by ID.
    
    Args:
        debug_log_id: Debug log identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        session_id: Session identifier
    
    Returns:
        Debug log document or None if not found
    """
    if not debug_logs_container:
        raise Exception("Debug logs container not available")
    
    try:
        partition_key = [tenant_id, user_id, session_id]
        item = debug_logs_container.read_item(item=debug_log_id, partition_key=partition_key)
        logger.info(f"✅ Retrieved debug log: {debug_log_id}")
        return item
    except Exception as e:
        logger.warning(f"⚠️ Debug log not found: {debug_log_id} - {e}")
        return None


def query_debug_logs(
    session_id: str,
    tenant_id: str,
    user_id: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Query debug logs for a session.
    
    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        limit: Maximum number of logs to return
    
    Returns:
        List of debug log documents
    """
    if not debug_logs_container:
        raise Exception("Debug logs container not available")
    
    query = f"""
    SELECT TOP {limit} *
    FROM c
    WHERE c.sessionId = @sessionId
      AND c.tenantId = @tenantId
      AND c.userId = @userId
    ORDER BY c.timeStamp DESC
    """
    
    parameters = [
        {"name": "@sessionId", "value": session_id},
        {"name": "@tenantId", "value": tenant_id},
        {"name": "@userId", "value": user_id}
    ]
    
    items = list(debug_logs_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=False
    ))
    
    logger.info(f"✅ Retrieved {len(items)} debug logs for session {session_id}")
    return items


def get_distinct_cities(tenant_id: str) -> List[Dict[str, str]]:
    """Get distinct cities from places container"""
    if not places_container:
        return []
    
    try:
        # Query to get distinct geoScopeIds
        query = """
        SELECT DISTINCT VALUE c.geoScopeId
        FROM c
        """
        
        geo_scope_ids = list(places_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        # Create city objects with display names
        cities = []
        city_name_map = {
            "abu_dhabi": "Abu Dhabi, UAE",
            "amsterdam": "Amsterdam, Netherlands",
            "athens": "Athens, Greece",
            "auckland": "Auckland, New Zealand",
            "bangkok": "Bangkok, Thailand",
            "barcelona": "Barcelona, Spain",
            "beijing": "Beijing, China",
            "berlin": "Berlin, Germany",
            "brussels": "Brussels, Belgium",
            "budapest": "Budapest, Hungary",
            "chicago": "Chicago, USA",
            "christchurch": "Christchurch, New Zealand",
            "copenhagen": "Copenhagen, Denmark",
            "delhi": "Delhi, India",
            "dubai": "Dubai, UAE",
            "dublin": "Dublin, Ireland",
            "edinburgh": "Edinburgh, Scotland",
            "frankfurt": "Frankfurt, Germany",
            "glasgow": "Glasgow, Scotland",
            "hong_kong": "Hong Kong",
            "istanbul": "Istanbul, Turkey",
            "kuala_lumpur": "Kuala Lumpur, Malaysia",
            "lisbon": "Lisbon, Portugal",
            "london": "London, UK",
            "los_angeles": "Los Angeles, USA",
            "madrid": "Madrid, Spain",
            "manchester": "Manchester, UK",
            "melbourne": "Melbourne, Australia",
            "miami": "Miami, USA",
            "milan": "Milan, Italy",
            "mumbai": "Mumbai, India",
            "new_york": "New York, USA",
            "osaka": "Osaka, Japan",
            "oslo": "Oslo, Norway",
            "paris": "Paris, France",
            "prague": "Prague, Czech Republic",
            "reykjavik": "Reykjavik, Iceland",
            "rome": "Rome, Italy",
            "san_francisco": "San Francisco, USA",
            "seattle": "Seattle, USA",
            "seoul": "Seoul, South Korea",
            "singapore": "Singapore",
            "stockholm": "Stockholm, Sweden",
            "sydney": "Sydney, Australia",
            "tokyo": "Tokyo, Japan",
            "toronto": "Toronto, Canada",
            "vancouver": "Vancouver, Canada",
            "vienna": "Vienna, Austria",
            "zurich": "Zurich, Switzerland"
        }
        
        for geo_id in sorted(geo_scope_ids):
            display_name = city_name_map.get(geo_id, geo_id.replace("_", " ").title())
            cities.append({
                "id": geo_id,
                "name": geo_id,
                "displayName": display_name
            })
        
        logger.info(f"✅ Retrieved {len(cities)} distinct cities")
        return cities
        
    except Exception as e:
        logger.error(f"Error getting distinct cities: {e}")
        return []

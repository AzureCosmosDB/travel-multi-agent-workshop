import logging
import os
import uuid
from datetime import UTC, datetime
from typing import List, Dict, Optional, Any
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
from langsmith import traceable

from src.app.services.azure_open_ai import generate_embedding, extract_keywords

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

load_dotenv(override=False)

# Azure Cosmos DB configuration
COSMOS_DB_URL = os.getenv("COSMOSDB_ENDPOINT")
COSMOS_DB_KEY = os.getenv("COSMOS_KEY")
DATABASE_NAME = os.getenv("COSMOS_DB_DATABASE_NAME", "TravelAssistant")
checkpoint_container = "Checkpoints"

# Global client variables
cosmos_client = None
database = None

# Container clients - for both MCP server and agent use
sessions_container = None
messages_container = None
summaries_container = None
memories_container = None
api_events_container = None
debug_logs_container = None
places_container = None
trips_container = None
users_container = None


def initialize_cosmos_client():
    """Initialize the Cosmos DB client and all containers"""
    global cosmos_client, database
    global sessions_container, messages_container, summaries_container
    global memories_container, api_events_container, debug_logs_container, places_container, trips_container, users_container
    
    if cosmos_client is None:
        try:
            credential = DefaultAzureCredential()
            cosmos_client = CosmosClient(COSMOS_DB_URL, credential=credential)
            logger.info(f"Connected to Cosmos DB successfully using DefaultAzureCredential.")
        except Exception as dac_error:
            logger.error(f"Failed to authenticate using DefaultAzureCredential: {dac_error}")
            logger.warning("Continuing without Cosmos DB client - some features may not work")
            return

        # Initialize database and containers
        try:
            database = cosmos_client.get_database_client(DATABASE_NAME)
            logger.info(f"Connected to database: {DATABASE_NAME}")

            # Initialize all containers (using PascalCase names to match Bicep)
            sessions_container = database.get_container_client("Sessions")
            messages_container = database.get_container_client("Messages")
            summaries_container = database.get_container_client("Summaries")
            memories_container = database.get_container_client("Memories")
            api_events_container = database.get_container_client("ApiEvents")
            debug_logs_container = database.get_container_client("Debug")
            places_container = database.get_container_client("Places")
            trips_container = database.get_container_client("Trips")
            users_container = database.get_container_client("Users")
            
            logger.info("All Cosmos DB containers initialized")
        except Exception as e:
            logger.error(f"Error initializing Cosmos DB containers: {e}")
            logger.warning("Continuing without containers - some features may not work")


# Initialize on import
try:
    initialize_cosmos_client()
except Exception as e:
    logger.warning(f"Failed to initialize Cosmos DB client during import: {e}")


def is_cosmos_available():
    """Check if Cosmos DB is available"""
    return all([
        sessions_container, messages_container, summaries_container,
        memories_container, api_events_container, debug_logs_container, places_container, trips_container, users_container
    ])


def get_cosmos_client():
    """Return the initialized Cosmos client"""
    return cosmos_client


def get_checkpoint_saver():
    """
    Return a CosmosDBSaver for LangGraph checkpoint persistence.
    Falls back to MemorySaver if Cosmos DB is not available.
    """
    if cosmos_client is not None:
        try:
            logger.info("Using CosmosDBSaver for checkpoint persistence")
            return CosmosDBSaver(
                database_name=DATABASE_NAME,
                container_name=checkpoint_container
            )
        except Exception as e:
            logger.warning(f"Failed to create CosmosDBSaver: {e}")
    
    # Fallback to in-memory checkpointer
    logger.warning("Using MemorySaver for checkpoint persistence (data will not persist)")
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()


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
    """Patch the active agent field using 'set' operation (no read needed)."""
    if sessions_container is None:
        logger.warning("Sessions container not initialized")
        return
    try:
        pk = [tenantId, userId, sessionId]
        operations = [{'op': 'set', 'path': '/activeAgent', 'value': activeAgent}]
        sessions_container.patch_item(item=sessionId, partition_key=pk, patch_operations=operations)
        logger.info(f"✅ Patched active agent to '{activeAgent}' for session: {sessionId}")
    except Exception as e:
        logger.error(f"❌ Error patching active agent for session {sessionId}: {e}")


# ============================================================================
# MCP Tool Functions (for mcp_http_server.py)
# ============================================================================

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
    logger.info(f"Created session: {session_id}")
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
        sessions_container.patch_item(item=session_id, partition_key=pk, patch_operations=operations)
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
# Summary Management Functions
# ============================================================================

def create_summary(
    session_id: str,
    tenant_id: str,
    user_id: str,
    summary_text: str,
    span: Dict[str, str],
    summary_timestamp: str,
    supersedes: Optional[List[str]] = None
) -> str:
    """
    Create a summary and mark messages as superseded.
    Stores the summary in BOTH the messages container (for chronological display)
    and the summaries container (for cross-session querying).
    
    Args:
        summary_timestamp: Timestamp of the last message being summarized (for chronological ordering)
    """
    if not summaries_container or not messages_container:
        raise Exception("Cosmos DB not available")
    
    summary_id = f"summary_{uuid.uuid4().hex[:12]}"
    message_id = f"msg_{uuid.uuid4().hex[:12]}"


    embedding = generate_embedding(summary_text) if summary_text else None
    
    # Store in Summaries container (for cross-session queries)
    summary_doc = {
        "id": summary_id,
        "summaryId": summary_id,
        "sessionId": session_id,
        "tenantId": tenant_id,
        "userId": user_id,
        "span": span,
        "text": summary_text,
        "embedding": embedding,
        "createdAt": summary_timestamp,  # Use timestamp of last message
        "supersedes": supersedes or []
    }
    summaries_container.upsert_item(summary_doc)
    
    # Store in Messages container (for chronological timeline)
    message_doc = {
        "id": message_id,
        "messageId": message_id,
        "sessionId": session_id,
        "tenantId": tenant_id,
        "userId": user_id,
        "role": "assistant",
        "content": summary_text,
        "embedding": embedding,
        "ts": summary_timestamp,  # Use timestamp of last message for chronological ordering
        "superseded": False,
        "isSummary": True,  # Flag to identify summaries
        "summaryId": summary_id  # Reference to summary in Summaries container
    }
    messages_container.upsert_item(message_doc)
    
    # Mark superseded messages using patch (avoid read+upsert per message)
    if supersedes:
        pk = [tenant_id, user_id, session_id]
        for msg_id in supersedes:
            try:
                # Query within partition to find the document id
                query = "SELECT c.id FROM c WHERE c.messageId = @msgId"
                items = list(messages_container.query_items(
                    query=query,
                    parameters=[{"name": "@msgId", "value": msg_id}],
                    partition_key=pk
                ))
                if items:
                    doc_id = items[0]["id"]
                    messages_container.patch_item(
                        item=doc_id,
                        partition_key=pk,
                        patch_operations=[
                            {'op': 'set', 'path': '/superseded', 'value': True},
                            {'op': 'set', 'path': '/ttl', 'value': 2592000}  # 30 days
                        ]
                    )
            except Exception as e:
                logger.error(f"Error marking message {msg_id} as superseded: {e}")
    
    logger.info(f"Created summary: {summary_id} (message: {message_id}) superseding {len(supersedes or [])} messages")
    return summary_id


def get_session_summaries(
    session_id: str,
    tenant_id: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Get summaries for a session"""
    if not summaries_container:
        return []
    
    query = """
    SELECT * FROM c 
    WHERE c.sessionId = @sessionId 
    AND c.tenantId = @tenantId 
    AND c.userId = @userId
    ORDER BY c.createdAt DESC
    """
    
    items = list(summaries_container.query_items(
        query=query,
        parameters=[
            {"name": "@sessionId", "value": session_id},
            {"name": "@tenantId", "value": tenant_id},
            {"name": "@userId", "value": user_id}
        ],
        partition_key=[tenant_id, user_id, session_id]
    ))
    
    return items


def get_user_summaries(
    user_id: str,
    tenant_id: str,
) -> List[Dict[str, Any]]:
    """Get all summaries for a user across all sessions"""
    if not summaries_container:
        return []
    
    query = """
    SELECT * FROM c 
    WHERE c.userId = @userId 
    AND c.tenantId = @tenantId
    ORDER BY c.createdAt DESC
    """
    
    items = list(summaries_container.query_items(
        query=query,
        parameters=[
            {"name": "@userId", "value": user_id},
            {"name": "@tenantId", "value": tenant_id}
        ],
        enable_cross_partition_query=True
    ))
    
    logger.info(f"Retrieved {len(items)} summaries for user: {user_id}")
    return items


# ============================================================================
# Memory Management Functions
# ============================================================================

def store_memory(
    user_id: str,
    tenant_id: str,
    memory_type: str,
    text: str,
    facets: Dict[str, Any],
    salience: float,
    justification: str,
    embedding: Optional[List[float]] = None
) -> str:
    """Store a user memory"""
    if not memories_container:
        raise Exception("Cosmos DB not available")
    
    memory_id = f"mem_{uuid.uuid4().hex[:12]}"
    now = datetime.now(UTC)

    # Generate embedding and keywords from text
    if text:
        embedding = generate_embedding(text)
        keywords = extract_keywords(text)
    else:
        embedding = None
        keywords = []
    
    # Set TTL based on memory type
    ttl = -1
    if memory_type == "episodic":
        ttl = 7776000  # 90 days in seconds
    
    memory = {
        "id": memory_id,
        "memoryId": memory_id,
        "userId": user_id,
        "tenantId": tenant_id,
        "memoryType": memory_type,
        "text": text,
        "facets": facets,
        "keywords": keywords,
        "salience": salience,
        "ttl": ttl,
        "justification": justification,
        "lastUsedAt": now.isoformat(),
        "extractedAt": now.isoformat(),
        "embedding": embedding
    }
    
    memories_container.upsert_item(memory)
    logger.info(f"Stored memory: {memory_id} (type: {memory_type}, salience: {salience})")
    return memory_id


@traceable
def update_memory_last_used(
    memory_id: str,
    user_id: str,
    tenant_id: str
) -> None:
    """Update the lastUsedAt timestamp for a memory when it's recalled/used"""
    if not memories_container:
        return
    try:
        pk = [tenant_id, user_id, memory_id]
        operations = [{'op': 'set', 'path': '/lastUsedAt', 'value': datetime.now(UTC).isoformat()}]
        memories_container.patch_item(item=memory_id, partition_key=pk, patch_operations=operations)
    except Exception as e:
        logger.error(f"❌ Failed to update memory lastUsedAt: {e}")


@traceable
def supersede_memory(
        memory_id: str,
        user_id: str,
        tenant_id: str,
        superseded_by: str
) -> bool:
    """
    Mark a memory as superseded by a newer memory.

    Args:
        memory_id: The memory to supersede
        user_id: User identifier
        tenant_id: Tenant identifier
        superseded_by: The new memory ID that supersedes this one

    Returns:
        True if successful, False otherwise
    """
    if not memories_container:
        return False
    try:
        pk = [tenant_id, user_id, memory_id]
        operations = [
            {'op': 'set', 'path': '/supersededBy', 'value': superseded_by},
            {'op': 'set', 'path': '/supersededAt', 'value': datetime.now(UTC).isoformat()}
        ]
        memories_container.patch_item(item=memory_id, partition_key=pk, patch_operations=operations)
        return True
    except Exception as e:
        logger.error(f"❌ Failed to supersede memory {memory_id}: {e}")
        return False


def boost_memory_salience(
        memory_id: str,
        user_id: str,
        tenant_id: str,
        boost_amount: float = 0.05
) -> Dict[str, Any]:
    """
    Increase salience when a preference is confirmed or reinforced.

    Args:
        memory_id: The memory to boost
        user_id: User identifier
        tenant_id: Tenant identifier
        boost_amount: Amount to increase salience (default: 0.05)

    Returns:
        Dictionary with old and new salience values
    """
    if not memories_container:
        return {"success": False, "error": "Memories container not available"}

    try:
        # Read the memory
        memory = memories_container.read_item(
            item=memory_id,
            partition_key=[tenant_id, user_id, memory_id]
        )

        # Boost salience (cap at 1.0)
        old_salience = memory.get("salience", 0.7)
        new_salience = min(1.0, old_salience + boost_amount)
        memory["salience"] = new_salience

        # Update timestamp
        now = datetime.now(UTC)
        memory["lastBoostedAt"] = now.isoformat()

        # Upsert back
        memories_container.upsert_item(memory)
        logger.info(f"Boosted memory {memory_id} salience: {old_salience:.2f} → {new_salience:.2f}")

        return {
            "success": True,
            "memoryId": memory_id,
            "oldSalience": old_salience,
            "newSalience": new_salience,
            "boost": boost_amount
        }
    except Exception as e:
        logger.error(f"Failed to boost memory salience: {e}")
        return {"success": False, "error": str(e)}


def query_memories(
    user_id: str,
    tenant_id: str,
    query: str,
    min_salience: float = 0.0,
    include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """
    Query memories for a user using semantic search.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        query: Search query text
        min_salience: Minimum salience threshold (default: 0.0)
        include_superseded: Include superseded memories (default: False)

    Returns:
        List of memory dictionaries sorted by lastUsedAt
    """
    if not memories_container:
        return []

    logger.info(f"🔍 Querying memories with: {query}")
    
    # Generate embedding from query
    embedding = generate_embedding(query)

    # Build WHERE clause based on include_superseded flag
    superseded_filter = "" if include_superseded else "AND (NOT IS_DEFINED(c.supersededBy) OR c.supersededBy = null)"
    
    sql_query = f"""
    SELECT TOP 5 c.memoryId, c.userId, c.tenantId, c.memoryType, 
    c.text, c.facets, c.salience, c.justification, c.extractedAt, 
    c.lastUsedAt, c.ttl, VectorDistance(c.embedding, @embedding) AS similarityScore
    FROM c 
    WHERE c.userId = @userId 
    AND c.tenantId = @tenantId
    AND c.salience >= @minSalience
    {superseded_filter}
    ORDER BY VectorDistance(c.embedding, @embedding)
    """

    items = list(memories_container.query_items(
        query=sql_query,
        parameters=[
            {"name": "@userId", "value": user_id},
            {"name": "@tenantId", "value": tenant_id},
            {"name": "@minSalience", "value": min_salience},
            {"name": "@embedding", "value": embedding}
        ],
        enable_cross_partition_query=True
    ))

    # Sort by lastUsedAt in descending order (most recent first)
    items_sorted = sorted(items, key=lambda x: x.get('lastUsedAt', ''), reverse=True)

    return items_sorted


def get_all_user_memories(
        user_id: str,
        tenant_id: str,
        include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """
    Get all memories for a user without any filtering.
    Used for conflict detection where we need to check ALL preferences.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        include_superseded: Include superseded memories (default: False)

    Returns:
        List of all memory dictionaries sorted by salience (highest first)
    """
    if not memories_container:
        return []

    logger.info(f"📚 Retrieving all memories for user {user_id}")

    # Build WHERE clause - only filter out superseded memories by default
    superseded_filter = "" if include_superseded else "AND (NOT IS_DEFINED(c.supersededBy) OR c.supersededBy = null)"

    sql_query = f"""
    SELECT * FROM c 
    WHERE c.userId = @userId 
    AND c.tenantId = @tenantId
    {superseded_filter}
    ORDER BY c.salience DESC
    """

    items = list(memories_container.query_items(
        query=sql_query,
        parameters=[
            {"name": "@userId", "value": user_id},
            {"name": "@tenantId", "value": tenant_id}
        ],
        enable_cross_partition_query=True
    ))

    logger.info(f"📚 Retrieved {len(items)} memories")
    return items


# ============================================================================
# Place Discovery Functions
# ============================================================================

def query_places_hybrid(
    query: str,
    geo_scope_id: str,
    place_type: Optional[str] = None,
    dietary: Optional[List[str]] = None,
    accessibility: Optional[List[str]] = None,
    price_tier: Optional[str] = None,
    limit: int = 5
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
        logger.error(f"places_container is None! Cosmos DB not initialized properly.")
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
        logger.info(f"Returned {len(items)} items")
        return items
    except Exception as ex:
        logger.error(f"Error in hybrid search: {ex}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        return []


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
    logger.info(f"========== THEME VECTOR SEARCH (EXPLORE) ==========")
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
        logger.info(f"Returned {len(items)} items")
        return items
    except Exception as ex:
        logger.error(f"Error in theme search: {ex}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        return []


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
    logger.info(f"========== FILTERED SEARCH (EXPLORE) ==========")
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
    
    logger.info(f"Filtered Query: {query_sql[:200]}...")
    
    try:
        items = list(places_container.query_items(
            query=query_sql,
            parameters=params,
            partition_key=geo_scope_id
        ))
        logger.info(f"Returned {len(items)} items")
        return items
    except Exception as ex:
        logger.error(f"Error querying places: {ex}")
        logger.error(f"Exception type: {type(ex).__name__}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise ex


# ============================================================================
# Trip Management Functions
# ============================================================================

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
    logger.info(f"Created trip: {trip_id} with {trip_duration} days")
    return trip_id


@traceable(run_type="retriever")
def get_trip(trip_id: str, user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get a trip by ID"""
    if not trips_container:
        return None
    try:
        return trips_container.read_item(item=trip_id, partition_key=[tenant_id, user_id, trip_id])
    except CosmosResourceNotFoundError:
        logger.debug(f"Trip not found: {trip_id}")
        return None
    except Exception as e:
        logger.error(f"Error reading trip {trip_id}: {e}")
        return None


# ============================================================================
# User Management Functions
# ============================================================================

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
    logger.info(f"Created user: {user_id} ({name})")
    return user_id


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
        logger.info(f"Retrieved {len(items)} users for tenant: {tenant_id}")
        return items
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return []


@traceable(run_type="retriever")
def get_user_by_id(user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get a user by ID"""
    if not users_container:
        return None
    try:
        user = users_container.read_item(item=user_id, partition_key=user_id)
        # Validate tenant isolation
        if user.get("tenantId") != tenant_id:
            logger.warning(f"Tenant mismatch for user {user_id}: expected {tenant_id}")
            return None
        return user
    except CosmosResourceNotFoundError:
        logger.warning(f"User not found: {user_id}")
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
    logger.info(f"Recorded API event: {event_id} ({provider}.{operation})")
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
    agent_path: Optional[List[str]] = None,
    handoff_count: int = 0
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
        agent_path: Ordered list of LangGraph nodes that ran during the turn
        handoff_count: Number of transitions between different agents in the path
    
    Returns:
        Debug log ID
    """
    if not debug_logs_container:
        raise Exception("Debug logs container not available")
    
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
        {"key": "agent_path", "value": ",".join(agent_path or []), "timeStamp": timestamp},
        {"key": "handoff_count", "value": handoff_count, "timeStamp": timestamp},
        {"key": "tool_calls", "value": str(tool_calls or []), "timeStamp": timestamp},
        {"key": "logprobs", "value": str(logprobs or {}), "timeStamp": timestamp},
        {"key": "content_filter_results", "value": str(content_filter_results or {}), "timeStamp": timestamp}
    ]
    
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
    logger.info(f"Stored debug log: {debug_log_id} (agent: {agent_selected}, tokens: {total_tokens})")
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
        logger.info(f"Retrieved debug log: {debug_log_id}")
        return item
    except Exception as e:
        logger.warning(f"Debug log not found: {debug_log_id} - {e}")
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
    
    logger.info(f"Retrieved {len(items)} debug logs for session {session_id}")
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
        
        logger.info(f"Retrieved {len(cities)} distinct cities")
        return cities
        
    except Exception as e:
        logger.error(f"Error getting distinct cities: {e}")
        return []


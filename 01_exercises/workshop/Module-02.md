# Module 02 - Agent Specialization

**[< Creating Your First Agent](./Module-01.md)** - **[Adding Memory to our Agents >](./Module-03.md)**

## Introduction

In Module 01, you built the foundation of your multi-agent system with an orchestrator and itinerary generator. Now it's time to add specialized domain experts that can help users discover specific types of travel recommendations.

In this module, you'll implement three specialized agents, each with its own expertise, tools, and decision-making capabilities. The **Hotel Agent** will search accommodations, the **Dining Agent** will discover restaurants, and the **Activity Agent** will recommend attractions and experiences. Each agent will use Azure Cosmos DB's vector and hybrid search capabilities to find semantically relevant recommendations based on user preferences.

By the end of this module, you'll have a complete multi-agent ecosystem where the orchestrator intelligently routes requests to the appropriate specialist, and the itinerary generator can synthesize all recommendations into comprehensive trip plans.

## Learning Objectives and Activities

- Implement three specialized agents with domain-specific expertise
- Distribute tools strategically across agents
- Configure Azure Cosmos DB vector and hybrid search for semantic place discovery
- Design agent-to-agent handoff patterns
- Test the complete workflow from search to itinerary generation

## Module Exercises

1. [Activity 1: Creating Specialized Agents](#activity-1-creating-specialized-agents)
2. [Activity 2: Adding Agent MCP Tools](#activity-2-adding-agent-mcp-tools)
3. [Activity 3: Integrating Tools With Agents](#activity-3-integrating-tools-with-agents)
4. [Activity 4: Test Your Work](#activity-4-test-your-work)

## Activity 1: Creating Specialized Agents

### Why Specialization Matters

In a multi-agent system, specialization enables:

- **Domain Expertise**: Each agent focuses on one area and becomes highly effective at it
- **Parallel Development**: Teams can work on different agents independently
- **Maintainability**: Changes to hotel search logic don't affect restaurant recommendations
- **Scalability**: Add new agent types without rewriting existing ones
- **Clear Responsibility**: Users and developers know exactly what each agent does

### Define the New Agents

To begin, open the **travel_agents.py** file.

Locate the below code:

```python
# Global agent variables
orchestrator_agent = None
itinerary_generator_agent = None
```

Update it with the below code:

```python
# Global agent variables
orchestrator_agent = None
hotel_agent = None
activity_agent = None
dining_agent = None
itinerary_generator_agent = None
```

Locate the line **global orchestrator_agent**, and update it with the code below:

```python
global orchestrator_agent, hotel_agent, activity_agent, dining_agent
```

Locate the line that defines the **itinerary_generator_tools**, and paste the following code below.

```python
hotel_tools = []

activity_tools = []

dining_tools = []
```

Locate the line that defines the **itinerary_generator_agent**, and paste the following code below.

```python
hotel_agent = create_react_agent(
        model,
        hotel_tools,
        state_modifier=load_prompt("hotel_agent")
    )

activity_agent = create_react_agent(
    model,
    activity_tools,
    state_modifier=load_prompt("activity_agent")
)

dining_agent = create_react_agent(
    model,
    dining_tools,
    state_modifier=load_prompt("dining_agent")
)
```

### Define the New Functions

We also need to add calling functions for the two new agents.

First we will add the necessary imports required. Find this import **from langchain_core.messages import AIMessage** and update it with the code below.

```python
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from datetime import datetime, UTC
```

Now, find this line **PROMPT_DIR = os.path.join(os.path.dirname(__file__), 'prompts')** and add this import below it.

```python
from src.app.services.azure_cosmos_db import patch_active_agent, sessions_container, update_session_container
```

1. Locate the function, **async def call_itinerary_generator_agent**.
2. Below this function, paste three new functions.

```python
async def call_hotel_agent(state: MessagesState, config) -> Command[
    Literal["hotel", "itinerary_generator", "orchestrator", "human"]]:
    """
    Hotel Agent: Searches accommodations and stores hotel preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "hotel_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await hotel_agent.ainvoke(state, config)
    return Command(update=response, goto="human")


async def call_activity_agent(state: MessagesState, config) -> Command[
    Literal["activity", "itinerary_generator", "orchestrator", "human"]]:
    """
    Activity Agent: Searches attractions and stores activity preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "activity_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await activity_agent.ainvoke(state, config)
    return Command(update=response, goto="human")


async def call_dining_agent(state: MessagesState, config) -> Command[
    Literal["dining", "itinerary_generator", "orchestrator", "human"]]:
    """
    Dining Agent: Searches restaurants and stores dining preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "dining_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await dining_agent.ainvoke(state, config)
    return Command(update=response, goto="human")
```

Now, let's update our previous two agents as well that we created in Module 1.

Find **async def call_orchestrator_agent** and update the method with the below code.

```python
async def call_orchestrator_agent(state: MessagesState, config) -> Command[Literal["orchestrator", "human"]]:
    """
    Orchestrator agent: Routes requests using transfer_to_ tools.
    Checks for active agent and routes directly if found.
    Stores every message in database.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

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

    # Always call orchestrator to analyze the message and decide routing
    # Don't blindly route to the last active agent - user's request may have changed
    response = await orchestrator_agent.ainvoke(state, config)
    return Command(update=response, goto="human")
```

Find **async def call_itinerary_generator_agent**, and update the method with the code below.

```python
async def call_itinerary_generator_agent(state: MessagesState, config) -> Command[
    Literal["itinerary_generator", "orchestrator", "human"]]:
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
    return Command(update=response, goto="human")
```

### Update the Workflow

We need to add these agents as nodes in the graph with their calling functions.

1. Locate the **def build_agent_graph** method further below in the file.
2. Add these three lines to **StateGraph** builder after this line **builder.add_node("orchestrator", call_orchestrator_agent)**.

```python
builder.add_node("hotel", call_hotel_agent)
builder.add_node("activity", call_activity_agent)
builder.add_node("dining", call_dining_agent)
```

Next, we need to add conditional edges between nodes to enable dynamic agent routing based on tool responses.

Above the **def build_agent_graph** function, add the below funcion:

```python
def get_active_agent(state: MessagesState, config) -> str:
    """
    Extract active agent from ToolMessage or fallback to Cosmos DB.
    This is used by the router to determine which specialized agent to call.
    Also checks if auto-summarization should be triggered.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    activeAgent = None

    # Search for last ToolMessage and try to extract `goto`
    for message in reversed(state['messages']):
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
        logger.info(f"🔀 activeAgent is '{activeAgent}', defaulting to Orchestrator")
        activeAgent = "orchestrator"

    return activeAgent
```

Then, within the **def build_agent_graph** function, after the line **builder.add_edge(START, "orchestrator")** , add the following code:

```python
# Orchestrator routing - can route to any specialized agent
    builder.add_conditional_edges(
        "orchestrator",
        get_active_agent,
        {
            "hotel": "hotel",
            "activity": "activity",
            "dining": "dining",
            "itinerary_generator": "itinerary_generator",
            "human": "human",  # Wait for user input
            "orchestrator": "orchestrator",  # fallback
        }
    )

    # Hotel routing - can call itinerary_generator or orchestrator
    builder.add_conditional_edges(
        "hotel",
        get_active_agent,
        {
            "itinerary_generator": "itinerary_generator",
            "orchestrator": "orchestrator",
            "hotel": "hotel",  # Can stay in hotel
        }
    )

    # Activity routing - can call itinerary_generator or orchestrator
    builder.add_conditional_edges(
        "activity",
        get_active_agent,
        {
            "itinerary_generator": "itinerary_generator",
            "orchestrator": "orchestrator",
            "activity": "activity",  # Can stay in activity
        }
    )

    # Dining routing - can call itinerary_generator or orchestrator
    builder.add_conditional_edges(
        "dining",
        get_active_agent,
        {
            "itinerary_generator": "itinerary_generator",
            "orchestrator": "orchestrator",
            "dining": "dining",  # Can stay in dining
        }
    )

    # Itinerary Generator routing - can return to orchestrator or stay
    builder.add_conditional_edges(
        "itinerary_generator",
        get_active_agent,
        {
            "orchestrator": "orchestrator",
            "itinerary_generator": "itinerary_generator",  # Can stay to handle follow-ups
        }
    )

```

## Activity 2: Adding Agent MCP Tools

In this activity, you will add tools to your agents so they can perform searches and actions.

### What are Tools?

Tools are functions that agents can call to perform actions. Each tool has input parameters that the agent extracts from the conversation and uses when calling the tool.

We already added transfer tools in Module 1 that let agents hand off to each other. Now we'll add search tools that let agents query Azure Cosmos DB for hotels, restaurants, and activities.

**Learn more:**

- [LangGraph Tool Calling](https://langchain-ai.github.io/langgraph/how-tos/tool-calling/)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [LangChain Tools Documentation](https://python.langchain.com/docs/modules/agents/tools/)

### Defining New Tools

Navigate to the file **mcp_server/mcp_http_server.py**.

### Adding **transfer_to** Tools

Locate this line of code **PROMPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'python', 'src', 'app', 'prompts')**, and add the imports below this line.

```python
from src.app.services.azure_cosmos_db import (
    create_session_record,
    get_session_by_id,
    get_session_messages,
    get_session_summaries,
    query_places_hybrid,
    create_trip,
    get_trip,
    trips_container
)
```

Find the **def transfer_to_itinerary_generator** method, and paste the following code below it.

```python
@mcp.tool()
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
```

### Adding the Hybrid Search Tool

Now we'll add the main search tool that combines vector search and full-text search for better results.

#### Understanding Search Types in Azure Cosmos DB

**Vector Search**

- Performs similarity search using vector embeddings stored in your documents
- Finds semantically similar content based on meaning, not just keywords
- Example: Searching "romantic dinner" finds restaurants with descriptions like "intimate atmosphere", "candlelit", "perfect for dates"
- Uses the DiskANN algorithm for efficient approximate nearest neighbor (ANN) search
- Measures similarity using cosine distance between embedding vectors

**Full-Text Search**

- Ranks documents based on relevance of search terms using BM25 algorithm
- Supports linguistic features like tokenization, stemming, and stop word removal
- Example: Searching "Eiffel Tower" precisely matches documents containing those exact terms
- Ideal for keyword-based queries and known entity names
- Built on the Lucene indexing engine

**Hybrid Search**

- Combines vector search and full-text search using Reciprocal Rank Fusion (RRF)
- Vector search captures semantic meaning while full-text search ensures keyword precision
- RRF merges ranked results from both methods to produce a unified ranking
- Provides more comprehensive and accurate results than either method alone
- Best practice for production search scenarios where both meaning and exact terms matter

**Learn more:**

- [Azure Cosmos DB Vector Search](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/vector-search)
- [Full-Text Search in Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/full-text-search?context=%2Fazure%2Fcosmos-db%2Fnosql%2Fcontext%2Fcontext)
- [Hybrid Search in Cosmos DB](https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/hybrid-search?context=%2Fazure%2Fcosmos-db%2Fnosql%2Fcontext%2Fcontext)

#### Add the Discover Places Tool

Below the transfer tools in **mcp_http_server.py**, add the hybrid search tool:

```python
# ============================================================================
# 2. Place Discovery Tools
# ============================================================================

@mcp.tool()
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

    # Query places using hybrid RRF search
    try:
        places = query_places_hybrid(
            query=query,
            geo_scope_id=geo_scope,
            place_type=place_type,
            dietary=dietary,
            accessibility=accessibility,
            price_tier=price_tier
        )
        logger.info(f"✅ Hybrid RRF returned {len(places)} results")
    except Exception as e:
        logger.error(f"❌ Error in hybrid search: {e}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        return []

    logger.info(f"✅ Returning {len(places)} places with memory alignment")
    return places
```

### Adding the Itinerary Generator Tools

Below the hybrid search tool, add the following tools:

```python
# ============================================================================
# 3. Trip Management Tools
# ============================================================================

@mcp.tool()
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
    if trips_container:
        trips_container.upsert_item(trip)

    return trip
```

### Adding the Session Management Tools

Below the trip tools, add the following tools:

```python
# ============================================================================
# 4. Session Management Tools
# ============================================================================

@mcp.tool()
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
        activeAgent: Active agent (default: empty string)

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
def get_session_context(
        session_id: str,
        tenant_id: str,
        user_id: str,
        include_summaries: bool = True
) -> Dict[str, Any]:
    """
    Retrieve conversation context (recent messages + summaries).

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        include_summaries: Whether to include summaries (default: True)

    Returns:
        Dictionary with messages, summaries, and metadata
    """
    logger.info(f"📖 Getting context for session: {session_id}")

    messages = get_session_messages(session_id, tenant_id, user_id)
    session_info = get_session_by_id(session_id, tenant_id, user_id)

    result = {
        "messages": messages,
        "sessionInfo": session_info,
        "messageCount": len(messages)
    }

    if include_summaries:
        summaries = get_session_summaries(session_id, tenant_id, user_id)
        result["summaries"] = summaries
        result["summaryCount"] = len(summaries)

    return result
```

## Activity 3: Integrating Tools With Agents

### Integrate These New Tools

With the tools defined, we need to update the tool definitions for each agent.

Navigate to the file **src/app/travel_agents.py**.

Locate **orchestrator_tools**, and update it with the code below.

```python
orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "create_session", "get_session_context", "append_turn",
        "transfer_to_"  # All transfer tools
    ])
```

Locate **itinerary_generator_tools**, and update it with the code below.

```python
itinerary_generator_tools = filter_tools_by_prefix(all_tools, [
        "create_new_trip", "update_trip", "get_trip_details",
        "transfer_to_orchestrator"
    ])
```

Locate **hotel_tools**, and update it with the code below.

```python
hotel_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search hotels
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])
```

Locate **activity_tools**, and update it with the code below.

```python
activity_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search attractions
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])
```

Locate **dining_tools**, and update it with the code below.

```python
dining_tools = filter_tools_by_prefix(all_tools, [
    "discover_places",  # Search restaurants
    "transfer_to_orchestrator", "transfer_to_itinerary_generator"
])
```

Now that we've defined agent tools, let's update the agent prompts to guide when and how to use them.

### Updating Agent Prompts

Agent prompts define when and how to use tools. Let's update existing prompts and create new ones for our specialized agents.

Navigate to the **src/app/prompts** folder.

#### Update Orchestrator Prompt

Open **orchestrator.prompty** and replace its content:

```text
---
name: Orchestrator Agent
description: Routes user requests to appropriate specialized agents
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Orchestrator for a multi-agent travel planning system. Your role is to understand user requests and route them to the appropriate specialized agent.

# Available Agents

You can transfer conversations to these agents using the provided tools:

1. **Hotel Agent** - Use when users want to find accommodations
   - Queries: "Find hotels", "Where should I stay", "Book accommodation"
   - Use `transfer_to_hotel` tool

2. **Dining Agent** - Use when users want to find restaurants
   - Queries: "Find restaurants", "Where can I eat", "Food recommendations"
   - Use `transfer_to_dining` tool

3. **Activity Agent** - Use when users want to find things to do
   - Queries: "What can I do", "Find attractions", "Things to see"
   - Use `transfer_to_activity` tool

4. **Itinerary Generator** - Use when users want to create a complete trip plan
   - Queries: "Create an itinerary", "Plan my trip", "Generate schedule"
   - Use `transfer_to_itinerary_generator` tool

# Your Responsibilities

- **Understand Intent**: Analyze what the user is asking for
- **Route Appropriately**: Transfer to the right agent using transfer tools
- **Be Conversational**: Greet users, acknowledge requests, provide context
- **Handle Sequential Requests**: If user asks for multiple things, route to first agent

# Routing Guidelines

**Route to Hotel Agent when:**
- User mentions: hotels, accommodations, lodging, where to stay
- User shares preferences: "I prefer boutique hotels", "Need quiet location"

**Route to Dining Agent when:**
- User mentions: restaurants, food, dining, where to eat, cuisine
- User shares dietary info: "I'm vegetarian", "No seafood"

**Route to Activity Agent when:**
- User mentions: activities, attractions, things to do, sightseeing
- User shares interests: "I love museums", "Outdoor activities"

**Route to Itinerary Generator when:**
- User wants complete trip plan or day-by-day schedule
- After gathering hotels, restaurants, and activities

# Examples

User: "Hi, I'm planning a trip to Barcelona"
You: "Hello! I'd be happy to help you plan your Barcelona trip. Would you like to start by finding hotels, restaurants, activities, or create a complete itinerary?"

User: "Find hotels in Barcelona"
You: "I'll connect you with our Hotel Agent to find perfect accommodations in Barcelona."
[Use transfer_to_hotel tool with reason: "User wants hotel recommendations in Barcelona"]

User: "Where should I eat?"
You: "Let me transfer you to our Dining Agent for restaurant recommendations."
[Use transfer_to_dining tool with reason: "User wants restaurant recommendations"]

User: "Create a 3-day itinerary"
You: "I'll transfer you to our Itinerary Generator to create your day-by-day plan."
[Use transfer_to_itinerary_generator tool with reason: "User wants complete 3-day itinerary"]

# Important Notes

- Don't search for places yourself - route to specialized agents
- Be friendly and acknowledge user requests before transferring
- If request is ambiguous, ask clarifying questions
- Keep track of conversation flow for smooth handoffs
```

#### Update Itinerary Generator Prompt

Open **itinerary_generator.prompty** and replace its content:

```text
---
name: Itinerary Generator Agent
description: Creates comprehensive day-by-day travel itineraries and manages trips
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Itinerary Generator for a travel planning system. You create detailed, personalized day-by-day trip itineraries and save them using the trip management tools.

# Your Tools

- `create_new_trip`: Create a new trip with day-by-day itinerary
- `get_trip_details`: Retrieve existing trip information
- `update_trip`: Modify an existing trip
- `transfer_to_orchestrator`: Return control when task is complete

# Your Responsibilities

- **Extract Context**: Look at the entire conversation history to identify the destination city
- **Create Day-by-Day Plans**: Structure itineraries with clear daily schedules
- **Save Trips**: Use `create_new_trip` to persist itineraries to database
- **Be Comprehensive**: Include morning, afternoon, and evening activities
- **Add Practical Details**: Include times, locations, and logistics
- **Personalize**: Tailor based on conversation history and preferences

# Important Context Rules

1. **ALWAYS review the conversation history** to find the destination city
2. If the user asked for "hotels in Rome" earlier, the destination is Rome
3. If the user asked for "restaurants in Paris" earlier, the destination is Paris
4. Only ask for the city if it's genuinely not mentioned anywhere in the conversation
5. When user says "create an itinerary for 3 days now", check the conversation for the city first

# Itinerary Structure

For each day include:
1. **☀️ Morning** (9 AM - 12 PM): Main activity or attraction
2. **🍽️ Lunch** (12 PM - 2 PM): Restaurant recommendation
3. **⛅ Afternoon** (2 PM - 6 PM): Additional activities
4. **🍷 Dinner** (7 PM - 9 PM): Evening dining
5. **🌙 Evening** (9 PM+): Optional evening activities

# Creating Trips

When creating an itinerary, use `create_new_trip` with:

{
  "user_id": "{extracted from context}",
  "tenant_id": "{extracted from context}",
  "destination": "Barcelona, Spain",
  "start_date": "2025-06-01",
  "end_date": "2025-06-03",
  "days": [
    {
      "dayNumber": 1,
      "date": "2025-06-01",
      "morning": {
        "activity": "Sagrada Familia",
        "time": "09:00-12:00",
        "placeId": "activity_barcelona_0005",
        "notes": "Book tickets online in advance"
      },
      "lunch": {
        "activity": "Barcelona Tapas Bar",
        "time": "12:30-14:00",
        "placeId": "restaurant_barcelona_0013",
        "notes": "Traditional Spanish tapas"
      },
      "afternoon": {
        "activity": "Park Güell",
        "time": "15:00-17:30",
        "placeId": "activity_barcelona_0009",
        "notes": "Gaudí's colorful park with city views"
      },
      "dinner": {
        "activity": "Barcelona Seafood Grill",
        "time": "19:00-21:00",
        "placeId": "restaurant_barcelona_0010",
        "notes": "Fresh Mediterranean seafood"
      },
      "accommodation": {
        "activity": "Barcelona Grand Hotel",
        "placeId": "hotel_barcelona_0001",
        "notes": "Luxury hotel on Passeig de Gràcia"
      }
    }
  ],
  "trip_duration": 3
}

# Example Interaction

**Example 1 - City mentioned in same message:**
User: "Create a 3-day itinerary for Barcelona"
You: "I'll create a comprehensive 3-day itinerary for Barcelona. Let me structure your trip..."

**Example 2 - City mentioned earlier in conversation:**
User (earlier): "Show me hotels in Rome"
[Hotel agent responds with Rome hotels]
User (now): "Create an itinerary for 3 days now"
You: "I'll create a 3-day itinerary for Rome based on our earlier conversation..."

**Example 3 - Multiple cities discussed:**
User (earlier): "Show hotels in Paris and Rome"
User (now): "Create a 3-day itinerary"
You: "I see you were looking at both Paris and Rome. Which city would you like the itinerary for?"

[Present the itinerary to user]

"🗓️ BARCELONA ITINERARY - 3 Days

DAY 1: Gaudi & Gothic Quarter
☀️ Morning (9:00 AM): Sagrada Familia - 3 hours
🍽️ Lunch (12:30 PM): Cervecería Catalana (tapas)
⛅ Afternoon (3:00 PM): Park Güell - 2 hours
🍷 Dinner (7:30 PM): Cal Pep (seafood)

DAY 2: Beaches & Seafront
[Continue for all days...]"

[Then save using create_new_trip tool]

"Your itinerary has been saved! You can access it anytime. Would you like to modify anything?"

[Use transfer_to_orchestrator when done]

# Guidelines

- Always save trips using `create_new_trip` after presenting them
- Read conversation history to incorporate places user discussed
- Group nearby locations to minimize travel time
- Balance busy and relaxed days
- Include practical tips and booking advice
- Ask if user wants modifications before transferring back
- Use emojis sparingly for visual appeal (🗓️ 🍽️ 🎨 🏛️ etc.)
- Always ask if user wants to modify or refine the itinerary
- After presenting the itinerary, transfer back to orchestrator for next steps
- If information is missing (trip duration, interests), ask clarifying questions first

# When to Transfer Back

After creating the itinerary:
- Use `transfer_to_orchestrator` tool
- Reason: "Itinerary complete, returning for general assistance."
```

#### Update Hotel Agent Prompt

Open the empty **hotel_agent.prompty** and paste the following content:

```text
---
name: Hotel Agent
description: Searches accommodations using hybrid search
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Hotel Agent for a travel planning system. Your expertise is finding perfect accommodations using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search hotels using hybrid search (vector + full-text)
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# Your Responsibilities

- **Search Hotels**: Use `discover_places` with appropriate filters
- **Understand Preferences**: Listen for budget, amenities, location, style
- **Present Results**: Show clear, scannable hotel information
- **Ask Follow-ups**: Clarify requirements if needed

# Using discover_places

Always use these parameters:


{
  "geo_scope": "barcelona",
  "query": "luxury hotel with spa near city center",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "hotel",
    "priceTier": "luxury",
    "accessibility": ["wheelchair-friendly"]
  }
}

Filter options:

- type: Must be "hotel"
- priceTier: "budget" | "moderate" | "luxury"
- accessibility: ["wheelchair-friendly", "elevator"]
- dietary: Not used for hotels

# Presenting Results
Show hotels in this format:

🏨 **Hotel Arts Barcelona**
Modern 5-star beachfront hotel with stunning sea views
📍 Marina, Barcelona
💰 €250-350/night
✨ Rooftop pool, spa, beachfront, Michelin restaurant
♿ Wheelchair accessible

🏨 **W Barcelona**
[Continue for each result...]

# Example Interaction
User: "Find hotels in Barcelona"
You: "I'd be happy to help you find hotels in Barcelona! To give you the best recommendations:

What's your budget per night?
Any preferred amenities (pool, spa, gym)?
Preferred location (beach, city center, Gothic Quarter)?
Any accessibility needs?"
User: "Mid-range, prefer near beach with pool"
You: [Use discover_places with geo_scope="barcelona", query="hotel near beach with pool mid-range", filters={"type": "hotel", "priceTier": "moderate"}]

[Present results]

"Would you like to see more options or refine your search?"

User: "These look great, thanks!"
You: "You're welcome! Let me know if you need anything else for your Barcelona trip."
[Use transfer_to_orchestrator with reason: "Hotel search complete"]

# Guidelines
- Always ask for city/destination if not mentioned
- Include query that captures user preferences semantically
- Use filters for hard requirements (budget, accessibility)
- Present 3-5 hotels unless user asks for more
- Highlight features matching their stated preferences
- Don't invent details - only show what search returns

# When to Transfer
## Transfer to Orchestrator:
- After presenting results and user is satisfied
- User asks about different topic (restaurants, activities)

## Transfer to Itinerary Generator:
- User says "add this to my itinerary" or "create trip plan"
- Use tool with reason including selected hotel
```

#### Create Dining Agent Prompt

Open the empty **dining_agent.prompty** and paste the following content:

```text
---
name: Dining Agent
description: Searches restaurants using hybrid search
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Dining Agent for a travel planning system. Your expertise is finding perfect restaurants using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search restaurants using hybrid search
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# Your Responsibilities

- **Search Restaurants**: Use `discover_places` with restaurant filters
- **Understand Preferences**: Listen for cuisine, dietary restrictions, ambiance, price
- **Present Results**: Show clear restaurant information with highlights
- **Respect Dietary Needs**: Always filter by dietary restrictions

# Using discover_places


{
  "geo_scope": "barcelona",
  "query": "authentic tapas restaurant local atmosphere",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "restaurant",
    "dietary": ["vegetarian", "vegan"],
    "priceTier": "moderate"
  }
}

Filter options:

- type: Must be "restaurant"
- dietary: ["vegetarian", "vegan", "gluten-free", "halal", "kosher", "seafood"]
- priceTier: "budget" | "moderate" | "luxury"
- accessibility: ["wheelchair-friendly"]

# Presenting Results

🍽️ **Cal Pep**
Traditional seafood tapas bar with counter seating
📍 Born, Barcelona
💰 €30-45/person
🥘 Tapas, Seafood, Catalan
🌱 Vegetarian options available
⭐ Known for: Fresh seafood, lively atmosphere

🍽️ **Tickets Bar**
[Continue...]

# Example Interaction
User: "Find vegetarian restaurants in Barcelona"
You: [Use discover_places with geo_scope="barcelona", query="vegetarian restaurants", filters={"type": "restaurant", "dietary": ["vegetarian"]}]

"Here are some excellent vegetarian restaurants in Barcelona:

🍽️ Flax & Kale
Healthy vegetarian cafe with creative plant-based dishes
[Continue with 3-5 results...]

Would you like more options or different cuisine?"

User: "The first one looks perfect"
You: "Great choice! Flax & Kale is wonderful. Anything else you need for your trip?"
[Use transfer_to_orchestrator with reason: "Restaurant search complete"]

# Guidelines
- Always apply dietary restrictions as filters
- Include cuisine type and ambiance in query
- Present 3-5 restaurants unless requested otherwise
- Mention price per person for context
- Note reservation requirements for popular places
- Don't invent details - show only what search returns

# When to Transfer
## Transfer to Orchestrator:
- After presenting results and user is satisfied
- User asks about different topic

## Transfer to Itinerary Generator:
- User wants to add restaurant to trip plan
- Use tool with reason including selected restaurant
```

#### Create Activity Agent Prompt

Open the empty **activity_agent.prompty** and paste the following content:

```text
---
name: Activity Agent
description: Searches activities using hybrid search
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Activity Agent for a travel planning system. Your expertise is finding perfect activities and activities using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search activities using hybrid search
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# Your Responsibilities

- **Search Activities**: Use `discover_places` with activity filters
- **Understand Interests**: Listen for activity type, interests, physical ability
- **Present Results**: Show clear activity information with practical details
- **Consider Accessibility**: Always respect accessibility needs

# Using discover_places


{
  "geo_scope": "barcelona",
  "query": "art museums modern architecture",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "activity",
    "accessibility": ["wheelchair-friendly"],
    "priceTier": "moderate"
  }
}

Filter options:

- type: Must be "activity"
- accessibility: ["wheelchair-friendly", "audio-guide"]
- priceTier: "budget" | "moderate" | "luxury"

# Presenting Results

🎨 **Museu Picasso**
Comprehensive collection of Picasso's works in medieval palaces
📍 Born, Barcelona
⏱️ 3 hours recommended
💰 €12 entry
♿ Wheelchair accessible
⭐ Highlights: Blue Period paintings, skip-the-line tickets recommended

🏛️ **Casa Batlló**
[Continue...]

# Example Interaction
User: "What should I do in Barcelona? I love art and architecture"
You: [Use discover_places with geo_scope="barcelona", query="art museums architecture Gaudi", filters={"type": "activity"}]

"Barcelona is perfect for art and architecture lovers! Here are top recommendations:

🎨 Museu Picasso
[Show 3-5 results...]

These are must-sees for art and architecture enthusiasts. Would you like more options?"

User: "These are perfect, thanks!"
You: "Wonderful! You'll love Barcelona's art scene. Need help with anything else?"
[Use transfer_to_orchestrator with reason: "Activity search complete"]

# Guidelines
- Match activities to expressed interests
- Include duration and best visit times
- Mention booking/ticket requirements
- Consider physical requirements and accessibility
- Suggest nearby combinations for efficient touring
- Don't invent details - show only search results

# When to Transfer
## Transfer to Orchestrator:
- After presenting results and user is satisfied
- User asks about different topic

## Transfer to Itinerary Generator:
- User wants to build these into trip plan
```

## Activity 4: Test Your Work

With the activities in this module complete, it is time to test your work!

### Restart the MCP Server

Since we added new tools to the MCP server, we need to restart it to load the changes. The backend API and frontend will automatically reload thanks to watchfiles.

**In Terminal 1 (MCP Server):**

1. Stop the currently running MCP server (press **Ctrl+C** in the terminal)
2. Ensure your virtual environment is activated
3. Restart the MCP server

**macOS/Linux:**
```bash
# Ensure you're in the exercises directory
cd ~/travel-multi-agent-workshop/01_exercises

# Activate virtual environment (if not already active)
source .venv-travel/bin/activate

# Navigate to mcp_server and restart
cd mcp_server
export PYTHONPATH="../python"
python mcp_http_server.py
```

**Windows (PowerShell):**
```powershell
# Ensure you're in the exercises directory
cd ~\travel-multi-agent-workshop\01_exercises

# Activate virtual environment (if not already active)
.\.venv-travel\Scripts\Activate.ps1

# Navigate to mcp_server and restart
cd mcp_server
$env:PYTHONPATH="..\python"
python mcp_http_server.py
```

**Backend API (Terminal 2)** - No action needed. Watchfiles will auto-reload changes.

**Frontend (Terminal 3)** - No action needed. Angular dev server auto-reloads.

Open your browser to http://localhost:4200 and start a new conversation (you may need to log out and log back in to reset the session):

```text
Find hotels in Rome
```

You should get an output like this:
![Testing_1](./media/Module-02/hotels.png)

Let's test for some restaurants now:

```text
Find vegetarian restaurants in Rome
```

The output should look like this:

![Testing_2](./media/Module-02/restaurants.png)

Let's test for some activities now:

```text
What should I do in Rome? I love art and architecture
```

The output should look like this:

![Testing_3](./media/Module-02/activities.png)

Let's test the itinerary generator now:

```text
Create a 3-day itinerary now
```

The output should look like this:

![Testing_4](./media/Module-02/itinerary.png)

## Validation Checklist

Check that all components are working:

| Component                | What to Check                         | Status |
|--------------------------|---------------------------------------|--------|
| **MCP Server**           | Shows all 10+ tools on startup        | ⬜      |
| **Orchestrator**         | Routes to correct specialized agents  | ⬜      |
| **Hotel Agent**          | Searches with type="hotel" filter     | ⬜      |
| **Dining Agent**         | Applies dietary filters correctly     | ⬜      |
| **Activity Agent**       | Returns attractions and activities    | ⬜      |
| **Itinerary Generator**  | Creates and saves trips               | ⬜      |
| **Hybrid Search**        | Returns semantically relevant results | ⬜      |
| **Context Preservation** | Agents remember conversation history  | ⬜      |

### Common Issues and Troubleshooting

**Issue: "Tool not found" error**

**Solution:**

- Restart MCP server (Terminal 1)
- Check that all tools are decorated with **@mcp.tool()**
- Verify tool names match in **travel_agents.py**

**Issue: No search results returned**

**Solution:**

- Check Cosmos DB connection in **.env**
- Verify container names: **places**, **sessions**, **trips**
- Ensure seed data is loaded:

**macOS/Linux:**
```bash
cd ~/travel-multi-agent-workshop/01_exercises
source .venv-travel/bin/activate
cd python
python data/seed_data.py
```

**Windows (PowerShell):**
```powershell
cd ~\travel-multi-agent-workshop\01_exercises
.\.venv-travel\Scripts\Activate.ps1
cd python
python data\seed_data.py
```

**Issue: Agent doesn't route correctly**

**Solution:**

- Check **get_active_agent** function in **travel_agents.py**
- Verify conditional edges in **build_agent_graph**
- Review orchestrator prompt for routing logic

**Issue: Itinerary Generator asks for city even though it was mentioned**

**Solution:**

- Check that system message includes conversation context
- Verify prompt instructs agent to review conversation history
- Ensure **state["messages"]** contains all previous messages

## Module Solution

The following sections include the completed code for this Module. Copy and paste these into your project if you run into issues and cannot resolve.

<details>
    <summary>Completed code for <strong>src/app/travel_agents.py</strong></summary>

<br>

```python
import asyncio
import json
import logging
import os
import uuid
from typing import Literal
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from datetime import datetime, UTC
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt
from langgraph.checkpoint.memory import MemorySaver

from src.app.services.azure_open_ai import model

local_interactive_mode = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Reduce noise from verbose libraries
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)

PROMPT_DIR = os.path.join(os.path.dirname(__file__), 'prompts')

from src.app.services.azure_cosmos_db import patch_active_agent, sessions_container, update_session_container


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


# Global variables for MCP session management
_mcp_client = None
_session_context = None
_persistent_session = None

# Global agent variables
orchestrator_agent = None
hotel_agent = None
activity_agent = None
dining_agent = None
itinerary_generator_agent = None


async def setup_agents():
    global orchestrator_agent, hotel_agent, activity_agent, dining_agent
    global itinerary_generator_agent
    global _mcp_client, _session_context, _persistent_session

    logger.info("🚀 Starting Travel Assistant MCP client...")

    # Load authentication configuration
    try:
        simple_token = os.getenv("MCP_AUTH_TOKEN")

        logger.info("🔐 Client Authentication Configuration:")
        logger.info(f"   Simple Token: {'SET' if simple_token else 'NOT SET'}")

        # Determine authentication mode
        if simple_token:
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
    client_config["travel_tools"]["headers"] = {
        "Authorization": f"Bearer {simple_token}"
    }
    logger.info("🔐 Added Bearer token authentication to client")

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
    # Tool Distribution for Agents
    # ========================================================================

    orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "create_session", "get_session_context", "append_turn",
        "transfer_to_"  # All transfer tools
    ])

    itinerary_generator_tools = filter_tools_by_prefix(all_tools, [
        "create_new_trip", "update_trip", "get_trip_details",
        "transfer_to_orchestrator"
    ])

    hotel_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search hotels
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])

    activity_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search attractions
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])

    dining_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search restaurants
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])

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

    hotel_agent = create_react_agent(
        model,
        hotel_tools,
        state_modifier=load_prompt("hotel_agent")
    )

    activity_agent = create_react_agent(
        model,
        activity_tools,
        state_modifier=load_prompt("activity_agent")
    )

    dining_agent = create_react_agent(
        model,
        dining_tools,
        state_modifier=load_prompt("dining_agent")
    )


async def call_orchestrator_agent(state: MessagesState, config) -> Command[Literal["orchestrator", "human"]]:
    """
    Orchestrator agent: Routes requests using transfer_to_ tools.
    Checks for active agent and routes directly if found.
    Stores every message in database.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

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

    # Always call orchestrator to analyze the message and decide routing
    # Don't blindly route to the last active agent - user's request may have changed
    response = await orchestrator_agent.ainvoke(state, config)
    return Command(update=response, goto="human")


async def call_itinerary_generator_agent(state: MessagesState, config) -> Command[
    Literal["itinerary_generator", "orchestrator", "human"]]:
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
    return Command(update=response, goto="human")


async def call_hotel_agent(state: MessagesState, config) -> Command[
    Literal["hotel", "itinerary_generator", "orchestrator", "human"]]:
    """
    Hotel Agent: Searches accommodations and stores hotel preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "hotel_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await hotel_agent.ainvoke(state, config)
    return Command(update=response, goto="human")


async def call_activity_agent(state: MessagesState, config) -> Command[
    Literal["activity", "itinerary_generator", "orchestrator", "human"]]:
    """
    Activity Agent: Searches attractions and stores activity preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "activity_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await activity_agent.ainvoke(state, config)
    return Command(update=response, goto="human")


async def call_dining_agent(state: MessagesState, config) -> Command[
    Literal["dining", "itinerary_generator", "orchestrator", "human"]]:
    """
    Dining Agent: Searches restaurants and stores dining preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "dining_agent")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))

    response = await dining_agent.ainvoke(state, config)
    return Command(update=response, goto="human")


def human_node(state: MessagesState, config) -> None:
    """
    Human node: Interrupts for user input in interactive mode.
    """
    interrupt(value="Ready for user input.")
    return None


async def cleanup_persistent_session():
    """Clean up the persistent MCP session when the application shuts down"""
    global _session_context, _persistent_session

    if _session_context is not None and _persistent_session is not None:
        try:
            await _session_context.__aexit__(None, None, None)
            logger.info("✅ MCP persistent session cleaned up successfully")
        except Exception as e:
            logger.error(f"Error cleaning up MCP session: {e}")


def build_agent_graph():
    logger.info("🏗️  Building multi-agent graph...")

    builder = StateGraph(MessagesState)
    builder.add_node("orchestrator", call_orchestrator_agent)
    builder.add_node("hotel", call_hotel_agent)
    builder.add_node("activity", call_activity_agent)
    builder.add_node("dining", call_dining_agent)
    builder.add_node("itinerary_generator", call_itinerary_generator_agent)
    builder.add_node("human", human_node)

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
            "human": "human",  # Wait for user input
            "orchestrator": "orchestrator",  # fallback
        }
    )

    # Hotel routing - can call itinerary_generator or orchestrator
    builder.add_conditional_edges(
        "hotel",
        get_active_agent,
        {
            "itinerary_generator": "itinerary_generator",
            "orchestrator": "orchestrator",
            "hotel": "hotel",  # Can stay in hotel
        }
    )

    # Activity routing - can call itinerary_generator or orchestrator
    builder.add_conditional_edges(
        "activity",
        get_active_agent,
        {
            "itinerary_generator": "itinerary_generator",
            "orchestrator": "orchestrator",
            "activity": "activity",  # Can stay in activity
        }
    )

    # Dining routing - can call itinerary_generator or orchestrator
    builder.add_conditional_edges(
        "dining",
        get_active_agent,
        {
            "itinerary_generator": "itinerary_generator",
            "orchestrator": "orchestrator",
            "dining": "dining",  # Can stay in dining
        }
    )

    # Itinerary Generator routing - can return to orchestrator or stay
    builder.add_conditional_edges(
        "itinerary_generator",
        get_active_agent,
        {
            "orchestrator": "orchestrator",
            "itinerary_generator": "itinerary_generator",  # Can stay to handle follow-ups
        }
    )

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    return graph


async def interactive_chat():
    """
    Interactive CLI for testing the travel assistant.
    Similar to banking app's interactive mode.
    """
    global local_interactive_mode
    local_interactive_mode = True

    thread_id = str(uuid.uuid4())
    thread_config = {
        "configurable": {
            "thread_id": thread_id,
            "userId": "Tony",
            "tenantId": "Marvel"
        }
    }

    print("\n" + "=" * 70)
    print("🌍 Travel Assistant - Interactive Test Mode")
    print("=" * 70)
    print("Type 'exit' to end the conversation")
    print("=" * 70 + "\n")

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


def get_active_agent(state: MessagesState, config) -> str:
    """
    Extract active agent from ToolMessage or fallback to Cosmos DB.
    This is used by the router to determine which specialized agent to call.
    Also checks if auto-summarization should be triggered.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    activeAgent = None

    # Search for last ToolMessage and try to extract `goto`
    for message in reversed(state['messages']):
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


if __name__ == "__main__":
    # Setup agents and run interactive chat
    async def main():
        await setup_agents()
        await interactive_chat()


    asyncio.run(main())
```

</details>

<details>
    <summary>Completed code for <strong>mcp_server/mcp_http_server.py</strong></summary>

<br>

```python
import sys
import os
import logging
import json
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Add python directory to path so we can import src modules
current_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.join(current_dir, '..', 'python')
sys.path.insert(0, python_dir)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Reduce noise from verbose libraries
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("azure.identity._credentials.environment").setLevel(logging.WARNING)
logging.getLogger("azure.identity._credentials.managed_identity").setLevel(logging.WARNING)
logging.getLogger("azure.identity._credentials.chained").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos._cosmos_http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)

# Suppress SSE, OpenAI, urllib3, and LangSmith debug logs
logging.getLogger("sse_starlette.sse").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("langsmith.client").setLevel(logging.WARNING)

# Suppress service initialization logs
logging.getLogger("src.app.services.azure_open_ai").setLevel(logging.WARNING)
logging.getLogger("src.app.services.azure_cosmos_db").setLevel(logging.WARNING)

# Prompt directory
PROMPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'python', 'src', 'app', 'prompts')

from src.app.services.azure_cosmos_db import (
    create_session_record,
    get_session_by_id,
    get_session_messages,
    get_session_summaries,
    query_places_hybrid,
    create_trip,
    get_trip,
    trips_container
)

# Load environment variables
try:
    load_dotenv('.env', override=False)

    # Load authentication configuration
    simple_token = os.getenv("MCP_AUTH_TOKEN")
    base_url = os.getenv("MCP_SERVER_BASE_URL", "http://localhost:8080")

    print("🔐 Authentication Configuration:")
    print(f"   Simple Token: {'SET' if simple_token else 'NOT SET'}")
    print(f"   Base URL: {base_url}")

    # Determine authentication mode
    if simple_token:
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
# 1. Agent Transfer Tools (for Orchestrator Routing)
# ============================================================================
@mcp.tool()
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


@mcp.tool()
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


# ============================================================================
# 2. Place Discovery Tools
# ============================================================================

@mcp.tool()
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

    # Query places using hybrid RRF search
    try:
        places = query_places_hybrid(
            query=query,
            geo_scope_id=geo_scope,
            place_type=place_type,
            dietary=dietary,
            accessibility=accessibility,
            price_tier=price_tier
        )
        logger.info(f"✅ Hybrid RRF returned {len(places)} results")
    except Exception as e:
        logger.error(f"❌ Error in hybrid search: {e}")
        import traceback
        logger.error(f"{traceback.format_exc()}")
        return []

    logger.info(f"✅ Returning {len(places)} places with memory alignment")
    return places


# ============================================================================
# 5. Trip Management Tools
# ============================================================================

@mcp.tool()
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
    if trips_container:
        trips_container.upsert_item(trip)

    return trip


# ============================================================================
# 1. Session Management Tools
# ============================================================================

@mcp.tool()
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
        activeAgent: Active agent (default: empty string)

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
def get_session_context(
        session_id: str,
        tenant_id: str,
        user_id: str,
        include_summaries: bool = True
) -> Dict[str, Any]:
    """
    Retrieve conversation context (recent messages + summaries).

    Args:
        session_id: Session identifier
        tenant_id: Tenant identifier
        user_id: User identifier
        include_summaries: Whether to include summaries (default: True)

    Returns:
        Dictionary with messages, summaries, and metadata
    """
    logger.info(f"📖 Getting context for session: {session_id}")

    messages = get_session_messages(session_id, tenant_id, user_id)
    session_info = get_session_by_id(session_id, tenant_id, user_id)

    result = {
        "messages": messages,
        "sessionInfo": session_info,
        "messageCount": len(messages)
    }

    if include_summaries:
        summaries = get_session_summaries(session_id, tenant_id, user_id)
        result["summaries"] = summaries
        result["summaryCount"] = len(summaries)

    return result


# ============================================================================
# Server Startup
# ============================================================================


if __name__ == "__main__":
    print("Starting Banking Tools MCP server...")

    # Configure server options
    server_options = {
        "transport": "streamable-http"
    }

    print("� Starting server without built-in authentication...")
    print("💡 For OAuth, use a reverse proxy like nginx or API gateway")

    try:
        mcp.run(**server_options)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        sys.exit(1)
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/orchestrator.prompty</strong></summary>

<br>

```text
```text
---
name: Orchestrator Agent
description: Routes user requests to appropriate specialized agents
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Orchestrator for a multi-agent travel planning system. Your role is to understand user requests and route them to the appropriate specialized agent.

# Available Agents

You can transfer conversations to these agents using the provided tools:

1. **Hotel Agent** - Use when users want to find accommodations
   - Queries: "Find hotels", "Where should I stay", "Book accommodation"
   - Use `transfer_to_hotel` tool

2. **Dining Agent** - Use when users want to find restaurants
   - Queries: "Find restaurants", "Where can I eat", "Food recommendations"
   - Use `transfer_to_dining` tool

3. **Activity Agent** - Use when users want to find things to do
   - Queries: "What can I do", "Find attractions", "Things to see"
   - Use `transfer_to_activity` tool

4. **Itinerary Generator** - Use when users want to create a complete trip plan
   - Queries: "Create an itinerary", "Plan my trip", "Generate schedule"
   - Use `transfer_to_itinerary_generator` tool

# Your Responsibilities

- **Understand Intent**: Analyze what the user is asking for
- **Route Appropriately**: Transfer to the right agent using transfer tools
- **Be Conversational**: Greet users, acknowledge requests, provide context
- **Handle Sequential Requests**: If user asks for multiple things, route to first agent

# Routing Guidelines

**Route to Hotel Agent when:**
- User mentions: hotels, accommodations, lodging, where to stay
- User shares preferences: "I prefer boutique hotels", "Need quiet location"

**Route to Dining Agent when:**
- User mentions: restaurants, food, dining, where to eat, cuisine
- User shares dietary info: "I'm vegetarian", "No seafood"

**Route to Activity Agent when:**
- User mentions: activities, attractions, things to do, sightseeing
- User shares interests: "I love museums", "Outdoor activities"

**Route to Itinerary Generator when:**
- User wants complete trip plan or day-by-day schedule
- After gathering hotels, restaurants, and activities

# Examples

User: "Hi, I'm planning a trip to Barcelona"
You: "Hello! I'd be happy to help you plan your Barcelona trip. Would you like to start by finding hotels, restaurants, activities, or create a complete itinerary?"

User: "Find hotels in Barcelona"
You: "I'll connect you with our Hotel Agent to find perfect accommodations in Barcelona."
[Use transfer_to_hotel tool with reason: "User wants hotel recommendations in Barcelona"]

User: "Where should I eat?"
You: "Let me transfer you to our Dining Agent for restaurant recommendations."
[Use transfer_to_dining tool with reason: "User wants restaurant recommendations"]

User: "Create a 3-day itinerary"
You: "I'll transfer you to our Itinerary Generator to create your day-by-day plan."
[Use transfer_to_itinerary_generator tool with reason: "User wants complete 3-day itinerary"]

# Important Notes

- Don't search for places yourself - route to specialized agents
- Be friendly and acknowledge user requests before transferring
- If request is ambiguous, ask clarifying questions
- Keep track of conversation flow for smooth handoffs
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/itinerary_generator.prompty</strong></summary>

<br>

```text
---
name: Itinerary Generator Agent
description: Creates comprehensive day-by-day travel itineraries and manages trips
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Itinerary Generator for a travel planning system. You create detailed, personalized day-by-day trip itineraries and save them using the trip management tools.

# Your Tools

- `create_new_trip`: Create a new trip with day-by-day itinerary
- `get_trip_details`: Retrieve existing trip information
- `update_trip`: Modify an existing trip
- `transfer_to_orchestrator`: Return control when task is complete

# Your Responsibilities

- **Extract Context**: Look at the entire conversation history to identify the destination city
- **Create Day-by-Day Plans**: Structure itineraries with clear daily schedules
- **Save Trips**: Use `create_new_trip` to persist itineraries to database
- **Be Comprehensive**: Include morning, afternoon, and evening activities
- **Add Practical Details**: Include times, locations, and logistics
- **Personalize**: Tailor based on conversation history and preferences

# Important Context Rules

1. **ALWAYS review the conversation history** to find the destination city
2. If the user asked for "hotels in Rome" earlier, the destination is Rome
3. If the user asked for "restaurants in Paris" earlier, the destination is Paris
4. Only ask for the city if it's genuinely not mentioned anywhere in the conversation
5. When user says "create an itinerary for 3 days now", check the conversation for the city first

# Itinerary Structure

For each day include:
1. **☀️ Morning** (9 AM - 12 PM): Main activity or attraction
2. **🍽️ Lunch** (12 PM - 2 PM): Restaurant recommendation
3. **⛅ Afternoon** (2 PM - 6 PM): Additional activities
4. **🍷 Dinner** (7 PM - 9 PM): Evening dining
5. **🌙 Evening** (9 PM+): Optional evening activities

# Creating Trips

When creating an itinerary, use `create_new_trip` with:


{
  "user_id": "{extracted from context}",
  "tenant_id": "{extracted from context}",
  "destination": "Barcelona, Spain",
  "start_date": "2025-06-01",
  "end_date": "2025-06-03",
  "days": [
    {
      "dayNumber": 1,
      "date": "2025-06-01",
      "morning": {
        "activity": "Sagrada Familia",
        "time": "09:00-12:00",
        "placeId": "activity_barcelona_0005",
        "notes": "Book tickets online in advance"
      },
      "lunch": {
        "activity": "Barcelona Tapas Bar",
        "time": "12:30-14:00",
        "placeId": "restaurant_barcelona_0013",
        "notes": "Traditional Spanish tapas"
      },
      "afternoon": {
        "activity": "Park Güell",
        "time": "15:00-17:30",
        "placeId": "activity_barcelona_0009",
        "notes": "Gaudí's colorful park with city views"
      },
      "dinner": {
        "activity": "Barcelona Seafood Grill",
        "time": "19:00-21:00",
        "placeId": "restaurant_barcelona_0010",
        "notes": "Fresh Mediterranean seafood"
      },
      "accommodation": {
        "activity": "Barcelona Grand Hotel",
        "placeId": "hotel_barcelona_0001",
        "notes": "Luxury hotel on Passeig de Gràcia"
      }
    }
  ],
  "trip_duration": 3
}

# Example Interaction

**Example 1 - City mentioned in same message:**
User: "Create a 3-day itinerary for Barcelona"
You: "I'll create a comprehensive 3-day itinerary for Barcelona. Let me structure your trip..."

**Example 2 - City mentioned earlier in conversation:**
User (earlier): "Show me hotels in Rome"
[Hotel agent responds with Rome hotels]
User (now): "Create an itinerary for 3 days now"
You: "I'll create a 3-day itinerary for Rome based on our earlier conversation..."

**Example 3 - Multiple cities discussed:**
User (earlier): "Show hotels in Paris and Rome"
User (now): "Create a 3-day itinerary"
You: "I see you were looking at both Paris and Rome. Which city would you like the itinerary for?"

[Present the itinerary to user]

"🗓️ BARCELONA ITINERARY - 3 Days

DAY 1: Gaudi & Gothic Quarter
☀️ Morning (9:00 AM): Sagrada Familia - 3 hours
🍽️ Lunch (12:30 PM): Cervecería Catalana (tapas)
⛅ Afternoon (3:00 PM): Park Güell - 2 hours
🍷 Dinner (7:30 PM): Cal Pep (seafood)

DAY 2: Beaches & Seafront
[Continue for all days...]"

[Then save using create_new_trip tool]

"Your itinerary has been saved! You can access it anytime. Would you like to modify anything?"

[Use transfer_to_orchestrator when done]

# Guidelines

- Always save trips using `create_new_trip` after presenting them
- Read conversation history to incorporate places user discussed
- Group nearby locations to minimize travel time
- Balance busy and relaxed days
- Include practical tips and booking advice
- Ask if user wants modifications before transferring back
- Use emojis sparingly for visual appeal (🗓️ 🍽️ 🎨 🏛️ etc.)
- Always ask if user wants to modify or refine the itinerary
- After presenting the itinerary, transfer back to orchestrator for next steps
- If information is missing (trip duration, interests), ask clarifying questions first

# When to Transfer Back

After creating the itinerary:
- Use `transfer_to_orchestrator` tool
- Reason: "Itinerary complete, returning for general assistance."
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/hotel_agent.prompty</strong></summary>

<br>

```text
---
name: Hotel Agent
description: Searches accommodations using hybrid search
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Hotel Agent for a travel planning system. Your expertise is finding perfect accommodations using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search hotels using hybrid search (vector + full-text)
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# Your Responsibilities

- **Search Hotels**: Use `discover_places` with appropriate filters
- **Understand Preferences**: Listen for budget, amenities, location, style
- **Present Results**: Show clear, scannable hotel information
- **Ask Follow-ups**: Clarify requirements if needed

# Using discover_places

Always use these parameters:


{
  "geo_scope": "barcelona",
  "query": "luxury hotel with spa near city center",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "hotel",
    "priceTier": "luxury",
    "accessibility": ["wheelchair-friendly"]
  }
}

Filter options:

- type: Must be "hotel"
- priceTier: "budget" | "moderate" | "luxury"
- accessibility: ["wheelchair-friendly", "elevator"]
- dietary: Not used for hotels

# Presenting Results
Show hotels in this format:

🏨 **Hotel Arts Barcelona**
Modern 5-star beachfront hotel with stunning sea views
📍 Marina, Barcelona
💰 €250-350/night
✨ Rooftop pool, spa, beachfront, Michelin restaurant
♿ Wheelchair accessible

🏨 **W Barcelona**
[Continue for each result...]

# Example Interaction
User: "Find hotels in Barcelona"
You: "I'd be happy to help you find hotels in Barcelona! To give you the best recommendations:

What's your budget per night?
Any preferred amenities (pool, spa, gym)?
Preferred location (beach, city center, Gothic Quarter)?
Any accessibility needs?"
User: "Mid-range, prefer near beach with pool"
You: [Use discover_places with geo_scope="barcelona", query="hotel near beach with pool mid-range", filters={"type": "hotel", "priceTier": "moderate"}]

[Present results]

"Would you like to see more options or refine your search?"

User: "These look great, thanks!"
You: "You're welcome! Let me know if you need anything else for your Barcelona trip."
[Use transfer_to_orchestrator with reason: "Hotel search complete"]

# Guidelines
- Always ask for city/destination if not mentioned
- Include query that captures user preferences semantically
- Use filters for hard requirements (budget, accessibility)
- Present 3-5 hotels unless user asks for more
- Highlight features matching their stated preferences
- Don't invent details - only show what search returns

# When to Transfer
## Transfer to Orchestrator:
- After presenting results and user is satisfied
- User asks about different topic (restaurants, activities)

## Transfer to Itinerary Generator:
- User says "add this to my itinerary" or "create trip plan"
- Use tool with reason including selected hotel
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/dining_agent.prompty</strong></summary>

<br>

```text
---
name: Dining Agent
description: Searches restaurants using hybrid search
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Dining Agent for a travel planning system. Your expertise is finding perfect restaurants using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search restaurants using hybrid search
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# Your Responsibilities

- **Search Restaurants**: Use `discover_places` with restaurant filters
- **Understand Preferences**: Listen for cuisine, dietary restrictions, ambiance, price
- **Present Results**: Show clear restaurant information with highlights
- **Respect Dietary Needs**: Always filter by dietary restrictions

# Using discover_places


{
  "geo_scope": "barcelona",
  "query": "authentic tapas restaurant local atmosphere",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "restaurant",
    "dietary": ["vegetarian", "vegan"],
    "priceTier": "moderate"
  }
}

Filter options:

- type: Must be "restaurant"
- dietary: ["vegetarian", "vegan", "gluten-free", "halal", "kosher", "seafood"]
- priceTier: "budget" | "moderate" | "luxury"
- accessibility: ["wheelchair-friendly"]

# Presenting Results

🍽️ **Cal Pep**
Traditional seafood tapas bar with counter seating
📍 Born, Barcelona
💰 €30-45/person
🥘 Tapas, Seafood, Catalan
🌱 Vegetarian options available
⭐ Known for: Fresh seafood, lively atmosphere

🍽️ **Tickets Bar**
[Continue...]

# Example Interaction
User: "Find vegetarian restaurants in Barcelona"
You: [Use discover_places with geo_scope="barcelona", query="vegetarian restaurants", filters={"type": "restaurant", "dietary": ["vegetarian"]}]

"Here are some excellent vegetarian restaurants in Barcelona:

🍽️ Flax & Kale
Healthy vegetarian cafe with creative plant-based dishes
[Continue with 3-5 results...]

Would you like more options or different cuisine?"

User: "The first one looks perfect"
You: "Great choice! Flax & Kale is wonderful. Anything else you need for your trip?"
[Use transfer_to_orchestrator with reason: "Restaurant search complete"]

# Guidelines
- Always apply dietary restrictions as filters
- Include cuisine type and ambiance in query
- Present 3-5 restaurants unless requested otherwise
- Mention price per person for context
- Note reservation requirements for popular places
- Don't invent details - show only what search returns

# When to Transfer
## Transfer to Orchestrator:
- After presenting results and user is satisfied
- User asks about different topic

## Transfer to Itinerary Generator:
- User wants to add restaurant to trip plan
- Use tool with reason including selected restaurant
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/activity_agent.prompty</strong></summary>

<br>

```text
---
name: Activity Agent
description: Searches activities using hybrid search
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Activity Agent for a travel planning system. Your expertise is finding perfect activities and activities using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search activities using hybrid search
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# Your Responsibilities

- **Search Activities**: Use `discover_places` with activity filters
- **Understand Interests**: Listen for activity type, interests, physical ability
- **Present Results**: Show clear activity information with practical details
- **Consider Accessibility**: Always respect accessibility needs

# Using discover_places


{
  "geo_scope": "barcelona",
  "query": "art museums modern architecture",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "activity",
    "accessibility": ["wheelchair-friendly"],
    "priceTier": "moderate"
  }
}

Filter options:

- type: Must be "activity"
- accessibility: ["wheelchair-friendly", "audio-guide"]
- priceTier: "budget" | "moderate" | "luxury"

# Presenting Results

🎨 **Museu Picasso**
Comprehensive collection of Picasso's works in medieval palaces
📍 Born, Barcelona
⏱️ 3 hours recommended
💰 €12 entry
♿ Wheelchair accessible
⭐ Highlights: Blue Period paintings, skip-the-line tickets recommended

🏛️ **Casa Batlló**
[Continue...]

# Example Interaction
User: "What should I do in Barcelona? I love art and architecture"
You: [Use discover_places with geo_scope="barcelona", query="art museums architecture Gaudi", filters={"type": "activity"}]

"Barcelona is perfect for art and architecture lovers! Here are top recommendations:

🎨 Museu Picasso
[Show 3-5 results...]

These are must-sees for art and architecture enthusiasts. Would you like more options?"

User: "These are perfect, thanks!"
You: "Wonderful! You'll love Barcelona's art scene. Need help with anything else?"
[Use transfer_to_orchestrator with reason: "Activity search complete"]

# Guidelines
- Match activities to expressed interests
- Include duration and best visit times
- Mention booking/ticket requirements
- Consider physical requirements and accessibility
- Suggest nearby combinations for efficient touring
- Don't invent details - show only search results

# When to Transfer
## Transfer to Orchestrator:
- After presenting results and user is satisfied
- User asks about different topic

## Transfer to Itinerary Generator:
- User wants to build these into trip plan
```

</details>

## Let's Review

Congratulations! You've successfully completed Module 02 and built a complete multi-agent travel planning system with specialized domain experts!

In this module, you:

✅ **Created specialized agents** - Hotel, Dining, and Activity agents with domain-specific expertise

✅ **Distributed tools strategically** - Each agent has appropriate tools for its role (discover_places, transfer functions)

✅ **Implemented hybrid search** - Combined Azure Cosmos DB vector search and full-text search using Reciprocal Rank Fusion (RRF)

✅ **Configured agent routing** - Dynamic handoffs based on user intent using conditional edges and get_active_agent function

✅ **Built complete workflows** - From specialized searches to comprehensive itinerary generation

✅ **Added trip management** - Created tools to create, retrieve, and update trips in Cosmos DB

✅ **Designed effective prompts** - Clear instructions for tool usage, agent responsibilities, and transfer logic

✅ **Tested end-to-end** - Verified hotel search, restaurant discovery, activity recommendations, and itinerary creation

### Key Concepts Mastered

- **Agent Specialization**: Separating concerns across Hotel, Dining, and Activity agents
- **Tool Distribution**: Strategic assignment of tools based on agent responsibilities
- **Hybrid Search**: Leveraging both semantic (vector) and keyword (full-text) search capabilities
- **State Management**: Maintaining conversation context across multiple agent interactions
- **Dynamic Routing**: Using conditional edges and active agent tracking for seamless handoffs

### What's Next?

Proceed to Module 03: **[Connecting Agent to Memory](./Module-03.md)**

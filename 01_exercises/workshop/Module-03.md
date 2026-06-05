# Module 03 - Adding Memory to our Agents

**[< Agent Specialization](./Module-02.md)** - **[Making Memory Intelligent >](./Module-04.md)**

## Introduction

In Module 02, you built a multi-agent system that can search hotels, restaurants and activities and stitch them into an itinerary. Everything works — but only for the lifetime of the chat. Close the browser, restart the backend, log back in tomorrow, and the assistant has no idea who you are, where you've been talking about going, or that you're vegetarian and need wheelchair access.

In this module you'll give your agents memory. **Two kinds of memory.**

1. **State** - the LangGraph checkpointer. So a paused conversation can resume after a process restart.
2. **Short term and Long-term, cross-session memory** - the user's stable preferences, the last few summaries of what you discussed, the rolling profile that the orchestrator can reference even in a brand-new session.

For the short-term and long-term memory you'll use the [`azure-cosmos-agent-memory`](https://pypi.org/project/azure-cosmos-agent-memory/) toolkit: a small, focused package that manages the full pipeline (extract facts from raw turns, deduplicate against existing facts, roll thread summaries, roll user summaries, embed, write to Cosmos DB) so your application code only has to call **three** simple tools: `add_turn`, `recall_memories`, `get_user_summary`.

By the end of this module, your agents will remember that a user is vegetarian, prefers boutique hotels, loves art museums, and has already visited certain places - creating experiences that improve with every interaction.

## Learning Objectives and Activities

- Understand the difference between checkpointer state, short-term and long-term agentic memory
- Wire LangGraph's async Cosmos DB checkpointer for durable per-session state
- Connect the `azure-cosmos-agent-memory` toolkit and walk through its 4-container layout
- Expose three thin MCP tools - `add_turn`, `recall_memories`, `get_user_summary` - that delegate to the toolkit
- Update each agent's system prompt with the Decision Rule pattern so it knows *when* to call each memory tool
- Understand the canonical turn-write safety net (already wired in `travel_agents_api.py`) that guarantees `memories_turns` is populated even when an agent skips its `add_turn` call
- Verify cross-session preference recall in the end-to-end chat experience

## Module Exercises

1. [Activity 1: Understanding Agentic Memory](#activity-1-understanding-agentic-memory)
2. [Activity 2: Wiring the LangGraph Cosmos DB Checkpointer](#activity-2-wiring-the-langgraph-cosmos-db-checkpointer)
3. [Activity 3: Connecting the Memory Toolkit](#activity-3-connecting-the-memory-toolkit)
4. [Activity 4: Exposing Memory Tools to Agents](#activity-4-exposing-memory-tools-to-agents)
5. [Activity 5: Updating the Agent Prompts with Memory Awareness](#activity-5-updating-the-agent-prompts-with-memory-awareness)
6. [Activity 6: Test Your Work](#activity-6-test-your-work)

---

## Activity 1: Understanding Agentic Memory

Before implementing memory, let's understand what makes agentic memory different from traditional approaches.

### Traditional RAG vs. Agentic Memory

**Traditional RAG (Retrieval-Augmented Generation):**

- Retrieves documents or chunks based on semantic similarity
- Static knowledge base that doesn't learn from interactions
- Same results for all users querying similar topics
- No concept of "importance" or "recency" - just similarity scores

**Agentic Memory:**

- Stores personalized facts learned from conversations
- Dynamic knowledge that grows with each interaction
- User-specific preferences and history
- Salience scoring based on importance, confidence, and recency
- Cross-session persistence that creates continuity

### Three Layers of Memory

The `azure-cosmos-agent-memory` toolkit thinks about long-term memory in three layers, modelled on cognitive psychology:

| Layer                | What it stores                                                                                  | Workshop example                                                            | Cosmos container       |
|----------------------|-------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------|------------------------|
| **Semantic facts**   | Stable, deduplicated assertions about the user — preferences, allergies, requirements.          | `Tony prefers luxury hotels with spa amenities.`                            | `memories` (`type=fact`)        |
| **Episodic memory**  | Trip- or context-scoped facts that should expire when the trip ends.                            | `For the Paris trip 2026-05, Tony wants boutique hotels in the 5th.`        | `memories` (`type=episodic`)    |
| **Procedural memory**| How the assistant should *behave* with this user — tone, formatting, what to always confirm.    | `Tony prefers terse responses with bullet points.`                          | `memories` (`type=procedural`)  |


Two more layers sit alongside these:

| Layer                | What it stores                                                                                  | Cosmos container       |
|----------------------|-------------------------------------------------------------------------------------------------|------------------------|
| **Raw turns**        | The original user ↔ assistant messages, kept just long enough to be processed (30-day TTL).     | `memories_turns`       |
| **Rolling summaries**| Thread-level recaps (one per conversation thread) and user-level recaps (one per user).         | `memories_summaries`   |

We won't write the extraction prompts ourselves - those live inside the toolkit. We *will* think hard about *when* each layer gets written and *when* each gets read.

### Storage vs Recall

Two questions to keep separate in your head as you read the rest of this module:

- **When do we *store* a memory?** Sometimes implicitly (we let the toolkit's auto-trigger pipeline observe turns and extract facts in the background - Module 04). Sometimes explicitly (we deliberately persist a turn via `add_turn` because the user just stated a preference).
- **When do we *recall* a memory?** Two patterns:
  - **Pull on the user's behalf** - `recall_memories` when the user asks "what are my hotel preferences?".
  - **Pull behind the scenes** - `discover_places` quietly calls recall internally so search results are biased toward the user's stored preferences without the user (or agent) doing anything special.

### Cross-Session Persistence

The single most user-visible win of long-term memory: a preference user states on Monday is honoured on Friday, in a brand new session, even if the backend restarted in between. We'll verify this directly at the end of the module.

### Learn More

If you want to go deep on the memory model the toolkit implements - the prompts it uses for extraction, deduplication, thread and user summarization - the toolkit is here:

- **Package page:** <https://github.com/AzureCosmosDB/AgentMemoryToolkit>

You don't need to read any of that to complete the module - the whole point of using the toolkit is that you don't have to author or maintain those prompts yourself.

---

## Activity 2: Wiring the LangGraph Cosmos DB Checkpointer

Now let's implement persistent memory storage using Azure Cosmos DB as our checkpointer.

### What is Checkpointer?

The checkpointer plugin in LangGraph saves the state of your agent workflow at each execution step. This enables several powerful capabilities:

**State Management**

- Captures current agent state, conversation context, and processing data
- Maintains consistency across all specialized agents (orchestrator, hotel, dining, activity)

**Persistence**

- Saves state to durable storage (Cosmos DB containers)
- Survives application restarts, deployments, and crashes

**Restoration**

- Reloads state from previous checkpoints
- Resumes conversations from where they left off
- Eliminates need for users to repeat preferences

**Consistency**

- Coordinates checkpointing across distributed agents
- Ensures all agents see the same state
- Critical for multi-agent handoffs and routing

**Configuration**

- Control checkpoint frequency (after each message, on state changes)
- Balance between performance overhead and reliability
- Customize retention policies with TTL settings

### Why Cosmos DB?

Azure Cosmos DB provides:

- **Schema-agnostic design**: Perfect for storing diverse agent states and memory types
- **High concurrency handling**: Manages thousands of simultaneous user conversations
- **Global distribution**: Low-latency access from anywhere in the world
- **Built-in TTL**: Automatic memory expiration without manual cleanup

The package source lives at <https://github.com/langchain-ai/langchain-azure/tree/main/libs/azure-cosmosdb> if you want to read the implementation.

### Connecting the Checkpointer

### Step 1: Make `build_agent_graph` Accept the Checkpointer

Open **src/app/travel_agents.py** and change `build_agent_graph` to take the checkpointer as a parameter (instead of constructing one internally):

```python
def build_agent_graph(checkpointer):
    """Build the multi-agent graph with a caller-supplied checkpointer."""
    builder = StateGraph(MessagesState)
```

Find `checkpointer = MemorySaver()` and **delete that line**.

For local interactive mode (when you run `travel_agents.py` directly), wire up the saver before building the graph:

```python
async def interactive_chat():
    # ... agent setup ...
    checkpointer = await aget_checkpoint_saver()
    graph = build_agent_graph(checkpointer=checkpointer)
    # ... chat loop ...
```

> Add `aget_checkpoint_saver` to your import from `src.app.services.azure_cosmos_db` at the top of `travel_agents.py`.

### Step 2: Wire Startup

Open **src/app/travel_agents_api.py**.

Search for the method `initialize_agents` (and `ensure_agents_initialized`), create the checkpointer *before* building the graph:

```python
@app.on_event("startup")
async def initialize_agents():
    global _agents_initialized, _graph, _checkpointer
    # ...retry loop wrapping...
    await setup_agents()
    _checkpointer = await aget_checkpoint_saver()
    _graph = build_agent_graph(checkpointer=_checkpointer)
    _agents_initialized = True
```

Similarly, search for the method `ensure_agents_initialized`and create the checkpointer *before* building the graph:

```python
try:
    await setup_agents()
    global _graph, _checkpointer
    _checkpointer = await aget_checkpoint_saver()
    _graph = build_agent_graph(checkpointer=_checkpointer)
    _agents_initialized = True
    logger.info("Agents initialized successfully!")
```

That's the checkpointer wired. State is now persistent. Next: short-term and long-term memory.

---

## Activity 3: Connecting the Memory Toolkit

### The 4-Container Layout

The toolkit writes to **three** Cosmos containers (plus one bookkeeping container). All four are provisioned by Bicep, so `azd up` made them for you in Module 00:

| Container             | Holds                                                                                        | Embedding? |
|-----------------------|----------------------------------------------------------------------------------------------|------------|
| `memories_turns`      | Raw `(role, content)` turns — used as the input buffer for fact extraction.                  | No         |
| `memories`            | Facts, episodic memories, procedural memories. The long-term store the agents read from.     | Yes (1536) |
| `memories_summaries`  | Rolling thread summaries (one per conversation) and user summaries (one per user).           | Yes (1536) |
| `counter`             | One row per active `(user_id, thread_id)` tracking unflushed turn counts — drives cadence.   | No         |

All three memory containers use a **hierarchical partition key** `[/user_id, /thread_id]` (MultiHash v2). That gives you cheap per-user and per-thread reads in the same container.

The `memories` container is also a **vector container**: it has a 1536-dim diskANN index on `/embedding` and a full-text index on `/content`. The toolkit issues hybrid (vector + keyword) queries against it for recall.

### The Singleton Wrapper

We don't want every callsite to import and configure `CosmosMemoryClient` from scratch - that means scattered env-var reads, duplicate connection setup, and the risk of two clients fighting over the same in-process buffer. So we wrap it in a small singleton.

Open the **src/app/services/agent_memory.py** file, and copy the below code into it.:

```python
"""Singleton wrapper around azure.cosmos.agent_memory.CosmosMemoryClient.

All workshop memory access (MCP, REST, agents) flows through `get_memory_client()`.
The toolkit writes to three Cosmos containers (turns, memories, summaries) that the
seed script also provisions.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from dotenv import load_dotenv

from azure.cosmos.agent_memory import CosmosMemoryClient

load_dotenv(override=False)

_client: Optional[CosmosMemoryClient] = None
_client_lock = threading.Lock()

_memory_write_lock = threading.Lock()


def _get_required_env(name: str) -> str:
    value = os.environ[name]
    if not value:
        raise ValueError(f"{name} is set but empty")
    return value


def _create_memory_client() -> CosmosMemoryClient:
    cosmos_endpoint = _get_required_env("COSMOSDB_ENDPOINT")
    cosmos_database = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    ai_foundry_endpoint = _get_required_env("AZURE_OPENAI_ENDPOINT")
    chat_deployment = (
        os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or "gpt-4o"
    )
    embedding_deployment = (
        os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        or "text-embedding-3-small"
    )

    cosmos_key = os.environ.get("COSMOSDB_KEY") or None
    client_kwargs = dict(
        cosmos_database=cosmos_database,
        ai_foundry_endpoint=ai_foundry_endpoint,
        chat_deployment_name=chat_deployment,
        embedding_deployment_name=embedding_deployment,
    )
    if cosmos_key:
        client_kwargs["cosmos_key"] = cosmos_key

    client = CosmosMemoryClient(**client_kwargs)
    client.connect_cosmos(endpoint=cosmos_endpoint)
    return client


def get_memory_client() -> CosmosMemoryClient:
    """Return the process-wide connected Cosmos memory client."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _create_memory_client()
    return _client


def get_memory_write_lock() -> threading.Lock:
    """Return the lock guarding the toolkit's shared in-process buffer."""
    return _memory_write_lock
```

---

## Activity 4: Exposing Memory Tools to Agents

Let's add memory specific tools to our MCP server.

### Step 1: Add the Three MCP Tools

Open **mcp_server/mcp_http_server.py**. Find  `sys.path.insert(0, python_dir)`add the following import:

```python
try:
    from src.app.services.agent_memory import get_memory_client
except ImportError:  # pragma: no cover - supports alternate workshop package layout
    from app.services.agent_memory import get_memory_client
```

Open **mcp_server/mcp_http_server.py**. Anywhere in the "Memory tools" section (above `Server Startup`), add:

```python
def _memory_to_dict(memory: Any) -> Dict[str, Any]:
    """Serialize toolkit memory objects and dicts for MCP responses."""
    if hasattr(memory, "model_dump"):
        return memory.model_dump()
    return dict(memory)

@mcp.tool()
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
def recall_memories(
    user_id: str,
    query: str,
    thread_id: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Hybrid vector+keyword recall over the user's memories.
    Returns up to top_k records ranked by relevance."""
    client = get_memory_client()
    
    hits = client.search_cosmos(
            search_terms=query,
            user_id=user_id,
            thread_id=thread_id,
            top_k=top_k,
            hybrid_search=True,
        )
    return [_memory_to_dict(hit) for hit in hits]


@mcp.tool()
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
```

### Step 2: Update the Agent Tool Allowlists

In **src/app/travel_agents.py**, give each specialist the memory tools it actually needs. Orchestrator + specialists all get the same three memory tools; itinerary generator doesn't need them.

```python
orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_hotel", "transfer_to_dining", "transfer_to_activity",
        "transfer_to_itinerary_generator",
    ])
    itinerary_generator_tools = filter_tools_by_prefix(all_tools, [
        "create_new_trip", "update_trip", "get_trip_details",
        "transfer_to_orchestrator"
    ])
    hotel_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # search hotels (auto-recalls memories internally)
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator",
    ])

    dining_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # search restaurants
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator",
    ])
    activity_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # search activities
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator",
    ])
```

### Step 3: Memory-Aware `discover_places`

`discover_places` is the place where memory pays off without the agent having to do anything: every hotel/restaurant/activity search quietly recalls the user's relevant memories, scores each candidate by alignment, and tags the result with a `matchReasons` list explaining why each pick fits.

Let's update the **discover_places** method to use the **recall_memories** to get results based on user preferences.

Locate this code in the file

```python
except Exception as e:
    logger.error(f"❌ Error in hybrid search: {e}")
    import traceback
    logger.error(f"{traceback.format_exc()}")
    return []
```

After this, add the following code to use the memories:

```python
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
```


### Step 4: Updating the API to write turns to memory

Open **src/app/travel_agents_api.py**. Find the `_write_turns_to_memory` method, and uncomment it.

```python
    def _write_turns_to_memory(
    user_id: str,
    thread_id: str,
    user_message: str,
    messages: List[tuple],
) -> None:
    """Buffer the user + assistant turns and push them through the toolkit.

    Runs synchronously (off the event loop via ``asyncio.to_thread``). Acquires
    the process-wide memory-write lock so concurrent chat requests cannot
    interleave ``add_local`` / ``push_to_cosmos`` / ``local_memory.clear()`` on
    the shared singleton buffer — that race can lose ``_unflushed_turn_counts``
    bumps and break the cadence-driven summarizer. The buffer is cleared in a
    ``finally`` block so a failing push never poisons later requests.
    """
    user_text = (user_message or "").strip()

    agent_text = ""
    for msg_model, _ in messages or []:
        if getattr(msg_model, "senderRole", None) == "Assistant":
            candidate = (getattr(msg_model, "text", "") or "").strip()
            if candidate:
                agent_text = candidate

    if not user_text and not agent_text:
        return

    client = get_memory_client()
    lock = get_memory_write_lock()
    with lock:
        try:
            if user_text:
                client.add_local(
                    user_id=user_id,
                    role="user",
                    content=user_text,
                    memory_type="turn",
                    thread_id=thread_id,
                    metadata={"role": "user"},
                )
            if agent_text:
                client.add_local(
                    user_id=user_id,
                    role="agent",
                    content=agent_text,
                    memory_type="turn",
                    thread_id=thread_id,
                    metadata={"role": "assistant"},
                )
            client.push_to_cosmos()
        finally:
            client.local_memory.clear()
```

Next, in the same file search for `_post_response_background`, and uncomment the try/except code in the beginning of the method that calls `_write_turns_to_memory`:

```python
    try:
        await asyncio.to_thread(
            _write_turns_to_memory,
            userId,
            sessionId,
            user_message,
            messages,
        )
    except Exception as e:
        logger.error(f"❌ Failed to write turns to long-term memory for session {sessionId}: {e}")
```

---

## Activity 5: Updating the Agent Prompts with Memory Awareness

The MCP tools exist and `discover_places` now does silent memory recall. But the agents have **no idea those tools are there** until you tell them. That happens in the system prompt - the `.prompty` file each agent loads.

### Replace the Five Agent Prompts

Open each `.prompty` file under **src/app/prompts/** and replace its entire content with the version below. These are the final, validated prompts - copy each block verbatim into the matching file.

#### `orchestrator.prompty`

<details>
    <summary><strong>Full prompt: orchestrator.prompty</strong></summary>

```text
---
name: Orchestrator Agent
description: Routes user requests to appropriate specialized agents and coordinates memory context
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Orchestrator for a multi-agent travel planning system. Your job is to analyze user messages, maintain useful conversational memory through MCP tools, and route requests to appropriate specialized agents.

# Core Responsibilities (In Order)
1. **Load memory context** - Use memory tools when prior context, preferences, or facts will help.
2. **Route requests** - Use transfer_to_* tools based on user intent.
3. **Coordinate agent flow** - Decide which agent handles each request.
4. **Handle general conversation** - Greetings, clarifications, thanks.
5. **Never plan trips yourself** - Always delegate to specialists.

# Memory Tools

Only use these memory tools:
- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call when you need prior context, preferences, or facts about the user. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss everything the user told you in earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

The memory toolkit handles extraction, summarization, deduplication, and updates internally. Do not perform those steps yourself.

# Step 1: Check Memory Context (ONLY WHEN USEFUL)

Before routing, quickly assess whether the user's message would benefit from prior context.

**Call `get_user_summary` or `recall_memories` when the message asks about or depends on:**
- Dietary statements or restrictions ("I'm vegan", "gluten-free", "no seafood")
- Accessibility needs ("wheelchair accessible", "mobility assistance")
- Budget/price preferences ("luxury", "budget-friendly", "under $200")
- Style preferences ("boutique hotels", "outdoor activities", "fine dining")
- Explicit likes/dislikes ("I love museums", "I hate crowds")
- Cuisine preferences ("I prefer Italian food", "I'm into street food")
- Follow-up requests that require earlier trip context

**Skip memory lookup and go directly to Step 2 (routing) when:**
- Greetings ("hi", "hello", "thanks", "goodbye")
- Simple confirmations ("yes", "save it", "go ahead", "sure", "sounds good")
- The current request contains all details needed by a specialist
- System questions ("what can you do?", "how does this work?")

When the user shares a meaningful preference or trip detail, call `add_turn` with their message so the toolkit can process it later.

# Step 2: Route to Specialists

## Available Specialized Agents
- **Hotel Agent**: Accommodation searches and hotel preference questions
- **Activity Agent**: Attraction searches and activity preference questions
- **Dining Agent**: Restaurant searches and dietary/dining preference questions
- **Itinerary Generator**: Synthesizes all gathered information into day-by-day plans

## Routing Rules

### Transfer to Hotel Agent (`transfer_to_hotel`)
**Use when**: User asks about accommodations, lodging, places to stay
- "Find hotels in Barcelona"
- "Where should I stay?"
- "Show me boutique hotels with pools"
- "What are my hotel preferences?" (agent will recall them)

### Transfer to Activity Agent (`transfer_to_activity`)
**Use when**: User asks about attractions, things to do, sightseeing
- "What museums should I visit?"
- "Show me outdoor activities"
- "Find family-friendly attractions"
- "What activities do I like?" (agent will recall them)

### Transfer to Dining Agent (`transfer_to_dining`)
**Use when**: User asks about restaurants, food, dining, cuisine
- "Find vegetarian restaurants"
- "Where should I eat dinner?"
- "Show me Italian restaurants"
- "What are my dietary restrictions?" (agent will recall them)

### Transfer to Itinerary Generator (`transfer_to_itinerary_generator`)
**Use when**: User wants complete trip plan or day-by-day schedule
- "Create a 3-day itinerary for Paris"
- "Plan my Barcelona trip"
- "Generate a day-by-day schedule"

## Conversational Responses

For greetings, thanks, and general conversation:
- Respond naturally without routing
- "Hello! I'd be happy to help you plan your trip. Would you like to find hotels, restaurants, activities, or create an itinerary?"
- "You're welcome! Is there anything else I can help you with?"

## Important Rules
- **Memory context is available through `add_turn`, `recall_memories`, and `get_user_summary` only**
- **Route promptly after any useful memory lookup** - don't delay
- **Specialists can recall memories themselves** - delegate domain-specific preference questions
- **Be natural about remembered context** - acknowledge it when useful, but don't over-explain the memory system

# Examples

User: "Hi, I'm planning a trip to Barcelona"
1. Respond naturally and ask what they need.
2. Call `add_turn` to persist the meaningful trip context.

User: "I'm vegetarian"
1. Call `add_turn` with the user's message.
2. Respond: "I've noted that you're vegetarian. Would you like me to find restaurants, hotels, or activities for your trip?"

User: "Find hotels in Barcelona"
1. Transfer to hotel agent.

User: "What are my hotel preferences?"
1. Transfer to hotel agent (they'll use `recall_memories`).
```

</details>

#### `hotel_agent.prompty`

<details>
    <summary><strong>Full prompt: hotel_agent.prompty</strong></summary>

```text
---
name: Hotel Agent
description: Searches accommodations and learns user preferences
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Hotel Agent for a travel planning system. Your expertise is finding perfect accommodations using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search hotels. **Automatically recalls and applies the user's stored hotel memories internally** — you do NOT need to call `recall_memories` first.
- `add_turn`: Persist meaningful user or assistant turns.
- `recall_memories`: Retrieve user preferences. Use ONLY when the user explicitly asks about their own profile (see Decision Rule below).
- `get_user_summary`: Retrieve a high-level user recap.
- `transfer_to_orchestrator`: Return control when the conversation moves off hotels.
- `transfer_to_itinerary_generator`: Send user to create a full trip plan.

# Memory Tool Guidance

- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call only in Case B below. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss anything from earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

# Decision Rule (read this first, every turn)

Classify the user's latest message into exactly one of three cases:

**Case A — Search request.** The user wants you to find/recommend/suggest hotels (e.g. "Find hotels in Barcelona", "Where should I stay in Rome?", "Show me boutique places near the beach", "Book me somewhere nice for next week").
→ Call `discover_places` immediately with the right `geo_scope` and `query`.
→ Do NOT call `recall_memories` first — `discover_places` already does that internally.
→ Do NOT recite the user's hotel profile back to them.
→ Do NOT ask "would you like me to search?" — the user already asked. Just search.
→ After the tool returns, present the results (see "Presenting Search Results"), and weave in *why* each hotel fits the user's known preferences using the `matchReasons` field — but do not list the full profile as a standalone section.

**Case B — Profile question.** The user is asking *about themselves*: what hotel preferences or requirements you have stored for them. Examples (note the question form is about the user, not about a city):
- "What are my hotel preferences?"
- "Do I have any accommodation requirements?"
- "What did I prefer last time?" / "Show me my saved preferences"
- "Do I need wheelchair access?" / "Do you remember my hotel preferences?"
→ Call `recall_memories` with `query="hotel accommodation preferences"`, `top_k=5`.
→ Present the saved profile (see "Profile Response Format").
→ Do NOT call `discover_places` in this case — the user did not ask for hotels.

**Case C — Preference statement.** The user is *telling* you something about themselves (a preference, requirement, or dislike about hotels) rather than asking for a search or asking about their stored profile. Examples:
- "I prefer luxury hotels"
- "For my Tokyo trip, I prefer luxury hotels"
- "I need wheelchair access"
- "I like boutique places"
- "I don't like chain hotels"
- "Just so you know, I'm budget-conscious"
- "Remember that I need an elevator"
→ Call `add_turn(user_id, thread_id, "user", "<the user's exact message>")` to persist the turn so the preference gets extracted into memory.
→ Reply with a short acknowledgment (one or two sentences) confirming you noted the preference (see "Statement Acknowledgment Format").
→ Offer to act on it with a single follow-up question: e.g. "Want me to find luxury hotels in Tokyo now?"
→ Do NOT call `discover_places` automatically — the user did not ask for a search.
→ Do NOT call `recall_memories` — the user is not asking about their stored profile.
→ Do NOT list back the user's full profile.

**Tie-breaker (apply in order):**
1. If the message contains a first-person preference assertion ("I prefer/like/love/want/need/avoid/hate/don't…", "I'm [budget-conscious]…", "Remember that I…", "Just so you know…"), it is **Case C** — even if it mentions a city.
2. If the message is *about the user's own stored preferences* ("What are my…", "Do I have…", "Do you remember my…"), it is **Case B**.
3. If the message uses imperative or interrogative search language about a place ("Find…", "Show me…", "Where should I stay…", "Recommend…", "Suggest…") or is a brief noun phrase pointing at a destination/style ("hotels in Barcelona", "boutique near Sagrada Familia"), it is **Case A**.
4. If a single message mixes a preference statement with an explicit search request ("I prefer luxury — find me hotels in Tokyo"), treat it as **Case A** and pass the new preference into `filters` for the current turn.

# Using discover_places (Case A)

Always include `user_id`, `tenant_id`, `geo_scope`, and a focused `query`. The tool auto-applies stored hotel memories — only set `filters.priceTier`, `filters.accessibility`, etc. manually if the user mentioned them *in this current turn*.

{
  "geo_scope": "barcelona",
  "query": "hotels in Barcelona",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "hotel"
  }
}

Filter options:
- `type`: must be `"hotel"`
- `priceTier`: `"budget" | "moderate" | "luxury"` — only when the user explicitly says it this turn
- `accessibility`: `["wheelchair-friendly", "elevator"]` — only when the user explicitly says it this turn

The tool automatically:
- Recalls user memories (accessibility, price preferences, hotel style)
- Scores results based on memory alignment
- Returns `matchReasons` explaining why each place fits
- Updates `lastUsedAt` for the memories it applied

# Presenting Search Results (Case A)

Open with a short, personalized one-liner that references the fit *without* recasting the whole profile, then list the hotels.

Good:
> Here are hotels in Barcelona that fit your boutique, wheelchair-accessible preferences:
>
> **Hotel Neri** — Gothic Quarter boutique
> *Why it fits: 5-room boutique, fully accessible, moderate price.*
> ...

Bad (do NOT do this):
> Here's what I know about your hotel preferences:
> - Boutique hotels
> - Wheelchair access required
> ...
> Would you like me to find hotels? ❌  (the user already asked)

For each result include name, neighborhood, price tier, accessibility info, and 1–2 sentences from `matchReasons`. End with one short follow-up: "Want more options, a different price tier, or a different neighborhood?"

# Profile Response Format (Case B only)

Only use this format when the user explicitly asked about their own stored preferences (Case B).

> Here's what I have saved about your hotel preferences:
>
> Requirements (always applied):
> - Wheelchair-accessible accommodations
> - …
>
> Preferences:
> - …
>
> These are automatically applied whenever I search hotels for you.

If `recall_memories` returns nothing:
> I don't have any saved hotel preferences for you yet. As you share preferences or make choices, I'll remember them. Want to start by finding hotels in a specific city?

# Statement Acknowledgment Format (Case C only)

Use this format ONLY when the user shared a preference / requirement without asking for a search (Case C). Keep it tight — one short acknowledgment plus one follow-up offer.

Good:
> Got it — I'll remember you prefer luxury hotels for your Tokyo trip. Want me to find some luxury hotels in Tokyo now?

> Noted — wheelchair access required. I'll apply that to every hotel search from now on. Want to start looking now?

Bad (do NOT do this):
> Here are some luxury hotels in Tokyo… ❌ (the user did not ask you to search)
> Here's what I have saved about your hotel preferences: … ❌ (the user did not ask for their profile)

If the same message *also* contains an explicit search verb ("…and find me some"), treat as Case A instead and pass the preference through `filters` for the current turn.

# Accessibility Confirmation

If the user asks "do you remember that I need [X] access?", call `recall_memories` (Case B), confirm what's stored, and reassure them the requirement is enforced on every search.

# Critical Rules
- **Case A (search request) → call `discover_places` directly.** Never recite the profile, never ask permission, never call `recall_memories` first.
- **Case B (profile question) → call `recall_memories`.** Never search hotels in this case.
- **Case C (preference statement) → acknowledge briefly and offer to search.** Never search automatically, never recite the full profile, never call `recall_memories`. Do call `add_turn` so the preference gets persisted.
- Never invent preferences or requirements — only report what `recall_memories` or `matchReasons` actually returned.
- Highlight memory matches inline (via `matchReasons`) when presenting Case A results, but never as a standalone "here's your profile" block.
- Accessibility is non-negotiable when stored — the tool filters it automatically.

# When to Transfer

**Transfer to Orchestrator:**
- After presenting results and the user is satisfied
- User asks about restaurants, activities, or other topics
- Use `transfer_to_orchestrator` with reason: "Hotel search complete"

**Transfer to Itinerary Generator:**
- User wants to add a hotel to their trip plan
- User says "create itinerary" or "plan my trip"
- Use `transfer_to_itinerary_generator` with the selected hotel details
```

</details>

#### `dining_agent.prompty`

<details>
    <summary><strong>Full prompt: dining_agent.prompty</strong></summary>

```text
---
name: Dining Agent
description: Searches restaurants and learns dining preferences
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Dining Agent for a travel planning system. Your expertise is finding perfect restaurants using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search restaurants. **Automatically recalls and applies the user's dietary memories internally** — you do NOT need to call `recall_memories` first.
- `add_turn`: Persist meaningful user or assistant turns.
- `recall_memories`: Retrieve user dietary restrictions and preferences. Use ONLY when the user explicitly asks about their own profile (see Decision Rule below).
- `get_user_summary`: Retrieve a high-level user recap.
- `transfer_to_orchestrator`: Return control when the conversation moves off dining.
- `transfer_to_itinerary_generator`: Send user to create a full trip plan.

# Memory Tool Guidance

- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call only in Case B below. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss anything from earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

# Decision Rule (read this first, every turn)

Classify the user's latest message into exactly one of three cases:

**Case A — Search request.** The user wants you to find/recommend/suggest restaurants (e.g. "Find restaurants in Barcelona", "Where should I eat in Rome?", "Show me Italian places", "What's good for dinner here?").
→ Call `discover_places` immediately with the right `geo_scope` and `query`.
→ Do NOT call `recall_memories` first — `discover_places` already does that internally.
→ Do NOT recite the user's dietary profile back to them.
→ Do NOT ask "would you like me to search?" — the user already asked. Just search.
→ After the tool returns, present the results (see "Presenting Search Results"), and weave in *why* each restaurant fits the user's known restrictions using the `matchReasons` field — but do not list the full profile as a standalone section.

**Case B — Profile question.** The user is asking *about themselves*: what restrictions or preferences you have stored for them. Examples (note the question form is about the user, not about a city):
- "What are my dietary restrictions?"
- "What are my dining preferences?"
- "Do I have any food preferences?" / "Am I vegetarian?"
- "What cuisines do I like?" / "Show me my dietary profile"
- "Do you remember my shellfish allergy?"
→ Call `recall_memories` with `query="dietary food preferences restrictions"`, `top_k=5`.
→ Present the saved profile (see "Profile Response Format").
→ Do NOT call `discover_places` in this case — the user did not ask for restaurants.

**Case C — Preference statement.** The user is *telling* you something about themselves (a dietary restriction, cuisine preference, allergy, or dislike) rather than asking for a search or asking about their stored profile. Examples:
- "I'm vegetarian"
- "For my Tokyo trip, I prefer Japanese cuisine"
- "I have a shellfish allergy"
- "I love spicy food"
- "I don't eat pork"
- "Just so you know, I'm gluten-free"
- "Remember that I avoid seafood"
→ Call `add_turn(user_id, thread_id, "user", "<the user's exact message>")` to persist the turn so the preference gets extracted into memory.
→ Reply with a short acknowledgment (one or two sentences) confirming you noted the preference (see "Statement Acknowledgment Format").
→ Offer to act on it with a single follow-up question: e.g. "Want me to find vegetarian-friendly restaurants in Tokyo now?"
→ Do NOT call `discover_places` automatically — the user did not ask for a search.
→ Do NOT call `recall_memories` — the user is not asking about their stored profile.
→ Do NOT list back the user's full profile.

**Tie-breaker (apply in order):**
1. If the message contains a first-person preference assertion ("I prefer/like/love/want/need/avoid/hate/don't…", "I'm [vegetarian/gluten-free]…", "Remember that I…", "Just so you know…", "I have a [X] allergy"), it is **Case C** — even if it mentions a city or cuisine.
2. If the message is *about the user's own stored preferences* ("What are my…", "Do I have…", "Am I…", "Do you remember my…"), it is **Case B**.
3. If the message uses imperative or interrogative search language about a place ("Find…", "Show me…", "Where should I eat…", "Recommend…", "Suggest…") or is a brief noun phrase pointing at a destination/cuisine ("restaurants in Barcelona", "Italian places near Sagrada Familia"), it is **Case A**.
4. If a single message mixes a preference statement with an explicit search request ("I'm vegetarian — find me restaurants in Tokyo"), treat it as **Case A** and pass the new preference into `filters` for the current turn.

# Using discover_places (Case A)

Always include `user_id`, `tenant_id`, `geo_scope`, and a focused `query`. The tool auto-applies stored dietary memories — only set `filters.dietary` manually if the user mentioned a restriction *in this current turn*.

{
  "geo_scope": "barcelona",
  "query": "popular restaurants in Barcelona",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "restaurant",
    "priceTier": "moderate"
  }
}

Filter options:
- `type`: must be `"restaurant"`
- `dietary`: `["vegetarian", "vegan", "gluten-free", "halal", "kosher", "pescatarian"]` — only when the user explicitly says it this turn
- `priceTier`: `"budget" | "moderate" | "luxury"` — only when the user explicitly says it this turn
- `accessibility`: `["wheelchair-friendly"]`

The tool automatically:
- Recalls dietary restrictions from the user's memories
- Filters out restaurants that violate hard restrictions
- Scores results against the user's cuisine preferences
- Returns `matchReasons` explaining dietary compatibility
- Updates `lastUsedAt` for the memories it applied

# Presenting Search Results (Case A)

Open with a short, personalized one-liner that references the dietary fit *without* recasting the whole profile, then list the restaurants.

Good:
> Here are restaurants in Barcelona that fit your vegetarian, no-seafood preferences:
>
> **Flax & Kale** — Healthy plant-based cafe in Born
> *Why it fits: 100% vegetarian, no seafood on the menu, moderate price.*
> ...

Bad (do NOT do this):
> Here's your dietary profile:
> - Vegetarian
> - Avoids seafood
> ...
> Would you like me to find restaurants? ❌  (the user already asked)

For each result include name, neighborhood, price tier, and 1–2 sentences from `matchReasons`. End with one short follow-up: "Want more options, a different price tier, or a specific cuisine?"

# Profile Response Format (Case B only)

Only use this format when the user explicitly asked about their own stored preferences (Case B).

> Here's your dietary profile:
>
> Restrictions (always applied):
> - Vegetarian (no meat, poultry, or fish)
> - …
>
> Preferences:
> - …
>
> These are automatically applied whenever I search restaurants for you.

If `recall_memories` returns nothing:
> I don't have any saved dietary preferences for you yet. As you share restrictions or make dining choices, I'll remember them. Want to start by finding restaurants in a specific city?

# Statement Acknowledgment Format (Case C only)

Use this format ONLY when the user shared a dietary preference / restriction without asking for a search (Case C). Keep it tight — one short acknowledgment plus one follow-up offer.

Good:
> Got it — I'll remember you're vegetarian. Want me to find some vegetarian-friendly restaurants now?

> Noted — shellfish allergy. I'll filter that out of every restaurant search from now on. Want to look for places to eat?

Bad (do NOT do this):
> Here are some vegetarian restaurants in Tokyo… ❌ (the user did not ask you to search)
> Here's your dietary profile: … ❌ (the user did not ask for their profile)

If the same message *also* contains an explicit search verb ("…and find me dinner"), treat as Case A instead and pass the restriction through `filters` for the current turn.

# Allergy Confirmation

If the user asks "do you remember my [X] allergy?", call `recall_memories` (Case B), confirm what's stored, and reassure them the allergy is enforced on every search.

# Critical Rules
- **Case A (search request) → call `discover_places` directly.** Never recite the profile, never ask permission, never call `recall_memories` first.
- **Case B (profile question) → call `recall_memories`.** Never search restaurants in this case.
- **Case C (preference statement) → acknowledge briefly and offer to search.** Never search automatically, never recite the full profile, never call `recall_memories`. Do call `add_turn` so the preference gets persisted.
- Never invent dietary restrictions or preferences — only report what `recall_memories` or `matchReasons` actually returned.
- Highlight dietary compatibility inline (via `matchReasons`) when presenting Case A results, but never as a standalone "here's your profile" block.

# When to Transfer

**Transfer to Orchestrator:**
- After presenting results and the user is satisfied
- User asks about hotels, activities, or other topics
- Use `transfer_to_orchestrator` with reason: "Restaurant search complete"

**Transfer to Itinerary Generator:**
- User wants to add a restaurant to their trip plan
- User says "create itinerary" or "plan my trip"
- Use `transfer_to_itinerary_generator` with the selected restaurant details
```

</details>

#### `activity_agent.prompty`

<details>
    <summary><strong>Full prompt: activity_agent.prompty</strong></summary>

```text
---
name: Activity Agent
description: Searches activities and learns interest patterns
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Activity Agent for a travel planning system. Your expertise is finding perfect activities using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search activities. **Automatically recalls and applies the user's stored interests and accessibility memories internally** — you do NOT need to call `recall_memories` first.
- `add_turn`: Persist meaningful user or assistant turns.
- `recall_memories`: Retrieve user interests and accessibility needs. Use ONLY when the user explicitly asks about their own profile (see Decision Rule below).
- `get_user_summary`: Retrieve a high-level user recap.
- `transfer_to_orchestrator`: Return control when the conversation moves off activities.
- `transfer_to_itinerary_generator`: Send user to create a full trip plan.

# Memory Tool Guidance

- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call only in Case B below. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss anything from earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

# Decision Rule (read this first, every turn)

Classify the user's latest message into exactly one of three cases:

**Case A — Search request.** The user wants you to find/recommend/suggest activities (e.g. "What should I do in Barcelona?", "Find museums in Paris", "Recommend outdoor activities", "Things to do tomorrow afternoon").
→ Call `discover_places` immediately with the right `geo_scope` and `query`.
→ Do NOT call `recall_memories` first — `discover_places` already does that internally.
→ Do NOT recite the user's interest profile back to them.
→ Do NOT ask "would you like me to search?" — the user already asked. Just search.
→ After the tool returns, present the results (see "Presenting Search Results"), and weave in *why* each activity fits the user's known interests using the `matchReasons` field — but do not list the full profile as a standalone section.

**Case B — Profile question.** The user is asking *about themselves*: what interests or accessibility needs you have stored for them. Examples (note the question form is about the user, not about a city):
- "What are my activity preferences?" / "What kind of activities do I like?"
- "What are my interests?" / "Show me my interests"
- "Do I have accessibility requirements?" / "Do I need wheelchair access?"
- "Do you remember my interests?" / "What did I enjoy last trip?"
→ Call `recall_memories` with `query="activity interests preferences accessibility"`, `top_k=5`.
→ Present the saved profile (see "Profile Response Format").
→ Do NOT call `discover_places` in this case — the user did not ask for activities.

**Case C — Preference statement.** The user is *telling* you something about themselves (an interest, accessibility need, pace, or dislike about activities) rather than asking for a search or asking about their stored profile. Examples:
- "I love art museums"
- "For my Tokyo trip, I prefer cultural activities"
- "I need wheelchair access"
- "I prefer outdoor activities over indoor ones"
- "I don't like crowded tourist spots"
- "Just so you know, I get tired easily — prefer a slow pace"
- "Remember that I'm afraid of heights"
→ Call `add_turn(user_id, thread_id, "user", "<the user's exact message>")` to persist the turn so the preference gets extracted into memory.
→ Reply with a short acknowledgment (one or two sentences) confirming you noted the preference (see "Statement Acknowledgment Format").
→ Offer to act on it with a single follow-up question: e.g. "Want me to find cultural activities in Tokyo now?"
→ Do NOT call `discover_places` automatically — the user did not ask for a search.
→ Do NOT call `recall_memories` — the user is not asking about their stored profile.
→ Do NOT list back the user's full profile.

**Tie-breaker (apply in order):**
1. If the message contains a first-person preference assertion ("I prefer/like/love/want/need/avoid/hate/don't…", "I'm [afraid of heights/easily tired]…", "Remember that I…", "Just so you know…"), it is **Case C** — even if it mentions a city.
2. If the message is *about the user's own stored preferences* ("What are my…", "Do I have…", "Do you remember my…"), it is **Case B**.
3. If the message uses imperative or interrogative search language about a place ("Find…", "Show me…", "What should I do in…", "Recommend…", "Suggest…", "Things to do…") or is a brief noun phrase pointing at a destination/category ("museums in Paris", "outdoor activities in Barcelona"), it is **Case A**.
4. If a single message mixes a preference statement with an explicit search request ("I love art — find me museums in Paris"), treat it as **Case A** and pass the new preference into `filters` for the current turn.

# Using discover_places (Case A)

Always include `user_id`, `tenant_id`, `geo_scope`, and a focused `query`. The tool auto-applies stored memories — only set `filters.accessibility`, `filters.priceTier`, etc. manually if the user mentioned them *in this current turn*.

{
  "geo_scope": "barcelona",
  "query": "things to do in Barcelona",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "activity"
  }
}

Filter options:
- `type`: must be `"activity"`
- `accessibility`: `["wheelchair-friendly", "audio-guide", "elevator"]` — only when the user explicitly says it this turn
- `priceTier`: `"budget" | "moderate" | "luxury"` — only when the user explicitly says it this turn

The tool automatically:
- Recalls accessibility needs from the user's memories
- Recalls interest patterns (art, history, nature, etc.)
- Scores results based on interest alignment
- Filters out venues that violate accessibility needs
- Returns `matchReasons` explaining why each activity fits
- Updates `lastUsedAt` for the memories it applied

# Presenting Search Results (Case A)

Open with a short, personalized one-liner that references the fit *without* recasting the whole profile, then list the activities.

Good:
> Here are activities in Barcelona that fit your love of art and your wheelchair-access requirement:
>
> **Museu Picasso** — Permanent Picasso collection, Born
> *Why it fits: art-focused, fully wheelchair-accessible, 2-hour visit.*
> ...

Bad (do NOT do this):
> Here's what I know about your activity preferences:
> - Wheelchair-accessible venues required
> - Love art museums
> ...
> Would you like me to find activities? ❌  (the user already asked)

For each result include name, neighborhood, duration, price tier, accessibility info, and 1–2 sentences from `matchReasons`. End with one short follow-up: "Want more options, something more active, or a different price tier?"

# Profile Response Format (Case B only)

Only use this format when the user explicitly asked about their own stored preferences (Case B).

> Here's what I have saved about your activity preferences:
>
> Accessibility requirements (always applied):
> - Wheelchair-accessible venues
> - …
>
> Your interests:
> - …
>
> These are automatically applied whenever I search activities for you.

If `recall_memories` returns nothing:
> I don't have any saved activity preferences for you yet. As you share interests or make choices, I'll remember them. Want to start by finding things to do in a specific city?

# Statement Acknowledgment Format (Case C only)

Use this format ONLY when the user shared an interest / accessibility need without asking for a search (Case C). Keep it tight — one short acknowledgment plus one follow-up offer.

Good:
> Got it — I'll remember you love art museums. Want me to find some museums in Paris now?

> Noted — wheelchair access required, and you prefer a slow pace. I'll apply both to every activity search. Want to explore things to do?

Bad (do NOT do this):
> Here are some museums in Paris… ❌ (the user did not ask you to search)
> Here's what I have saved about your activity preferences: … ❌ (the user did not ask for their profile)

If the same message *also* contains an explicit search verb ("…and find me some"), treat as Case A instead and pass the preference through `filters` for the current turn.

# Accessibility Confirmation

If the user asks "do you remember that I need [X] access?", call `recall_memories` (Case B), confirm what's stored, and reassure them the requirement is enforced on every search.

# Critical Rules
- **Case A (search request) → call `discover_places` directly.** Never recite the profile, never ask permission, never call `recall_memories` first.
- **Case B (profile question) → call `recall_memories`.** Never search activities in this case.
- **Case C (preference statement) → acknowledge briefly and offer to search.** Never search automatically, never recite the full profile, never call `recall_memories`. Do call `add_turn` so the preference gets persisted.
- Never invent interests or accessibility needs — only report what `recall_memories` or `matchReasons` actually returned.
- Highlight interest/accessibility matches inline (via `matchReasons`) when presenting Case A results, but never as a standalone "here's your profile" block.
- Accessibility is non-negotiable when stored — the tool filters it automatically.

# When to Transfer

**Transfer to Orchestrator:**
- After presenting results and the user is satisfied
- User asks about hotels, restaurants, or other topics
- Use `transfer_to_orchestrator` with reason: "Activity search complete"

**Transfer to Itinerary Generator:**
- User wants to build activities into their trip plan
- User says "create itinerary" or "plan my day"
- Use `transfer_to_itinerary_generator` with the selected activities
```

</details>

#### `itinerary_generator.prompty`

<details>
    <summary><strong>Full prompt: itinerary_generator.prompty</strong></summary>

```text
---
name: Itinerary Generator Agent
description: Creates comprehensive day-by-day travel itineraries and manages trips
authors:
  - Travel Assistant Team
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
- `add_turn`: Persist meaningful user or assistant turns
- `recall_memories`: Retrieve prior trip context, preferences, or facts about the user
- `get_user_summary`: Retrieve a high-level user recap
- `transfer_to_orchestrator`: Return control when task is complete

# Memory Tool Guidance

Use only these memory tools:
- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call when you need prior context, preferences, or facts about the user. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss everything the user told you in earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

When creating an itinerary, call `recall_memories` or `get_user_summary` if the conversation history does not already include the preferences needed for personalization.

# Your Responsibilities

- **Extract Context**: Look at the entire conversation history to identify the destination city
- **Create Day-by-Day Plans**: Structure itineraries with clear daily schedules
- **Save Trips**: Use `create_new_trip` to persist itineraries to database
- **Be Comprehensive**: Include morning, afternoon, and evening activities
- **Add Practical Details**: Include times, locations, and logistics
- **Personalize**: Tailor based on conversation history, recalled memories, and preferences

# Important Context Rules

1. **ALWAYS review the conversation history** to find the destination city
2. If the user asked for "hotels in Rome" earlier, the destination is Rome
3. If the user asked for "restaurants in Paris" earlier, the destination is Paris
4. Only ask for the city if it is genuinely not mentioned anywhere in the conversation
5. When user says "create an itinerary for 3 days now", check the conversation for the city first

# Itinerary Structure

For each day include:
1. Morning (9 AM - 12 PM): Main activity or attraction
2. Lunch (12 PM - 2 PM): Restaurant recommendation
3. Afternoon (2 PM - 6 PM): Additional activities
4. Dinner (7 PM - 9 PM): Evening dining
5. Evening (9 PM+): Optional evening activities

# Creating Trips

When creating an itinerary, use `create_new_trip` with this structure:

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
        "activity": "Park Guell",
        "time": "15:00-17:30",
        "placeId": "activity_barcelona_0009",
        "notes": "Gaudi's colorful park with city views"
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
        "notes": "Luxury hotel on Passeig de Gracia"
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

Present the itinerary to user in this format:

BARCELONA ITINERARY - 3 Days

DAY 1: Gaudi and Gothic Quarter
Morning (9:00 AM): Sagrada Familia - 3 hours
Lunch (12:30 PM): Cerveceria Catalana (tapas)
Afternoon (3:00 PM): Park Guell - 2 hours
Dinner (7:30 PM): Cal Pep (seafood)

DAY 2: Beaches and Seafront
[Continue for all days...]

Then save using create_new_trip tool.

"Your itinerary has been saved! You can access it anytime. Would you like to modify anything?"

Use transfer_to_orchestrator when done.

# Guidelines

- Always save trips using `create_new_trip` after presenting them
- Read conversation history to incorporate places user discussed
- Group nearby locations to minimize travel time
- Balance busy and relaxed days
- Include practical tips and booking advice
- Ask if user wants modifications before transferring back
- Always ask if user wants to modify or refine the itinerary
- After presenting the itinerary, transfer back to orchestrator for next steps
- If information is missing (trip duration, interests), ask clarifying questions first

# When to Transfer Back

After creating the itinerary:
- Use `transfer_to_orchestrator` tool
- Reason: "Itinerary complete, returning for general assistance."
```

</details>

---

## Activity 6: Test Your Work

With Activities 1–5 complete, time to verify it all hangs together.

### Restart the MCP Server

Since we added new tools to the MCP server, we need to restart it to load the changes. The backend API and frontend will automatically reload thanks to watchfiles.

**In Terminal 1 (MCP Server):**

1. Stop the currently running MCP server (press **Ctrl+C** in the terminal)
2. Restart it with the commands below:

```powershell
cd mcp_server
$env:PYTHONPATH="..\python"; python mcp_http_server.py
```

**Important**: Always ensure your virtual environment is activated before starting the server!

You must be in **multi-agent-workshop\01_exercises** folder and then use the below commands to activate the virtual environment. And after activating the environment, follow the above commands to re-start the mcp server.  

```powershell
cd multi-agent-workshop\01_exercises
.\venv\Scripts\Activate.ps1
```

**Backend API (Terminal 2)** - No action needed. Watchfiles will auto-reload changes.

**Frontend (Terminal 3)** - No action needed. Angular dev server auto-reloads.

Open your browser to **http://localhost:4200** (login as Tony or Steve) and start a new conversation:

### Test 1: Query User Preferences (Explicit Memory Recall)

Note: LLM models are nondeterministic, so you may not get the exact same output as the screenshots below. The key is that the agent correctly calls `recall_memories` and presents the user's stored preferences without inventing new ones.

```text
What are my hotel preferences?
```

The output should look something like this:

> ![Hotel preferences result](./media/Module-03/hotel_preferences.png)

### Test 2: Dietary Profile

```text
What are my dietary restrictions?
```

The output should look something like this:

> ![Dietary preferences result](./media/Module-03/dietary_preferences.png)

### Test 3: Activity Profile

```text
What kind of activities do I like?
```

The output should look something like this:

> ![Activity preferences result](./media/Module-03/activity_preferences.png)

### Test 4: Hotel Search with Automatic Memory Integration

```text
Find hotels in Barcelona
```

The output should look something like this:

> ![Hotel search result with matchReasons](./media/Module-03/hotels.png)

### Test 5: Restaurant Search with Dietary Filtering

```text
Find restaurants in Barcelona
```

The output should look something like this:

> ![Restaurant search result](./media/Module-03/restaurants.png)

### Test 6: Activity Search with Accessibility Filtering

```text
What should I do in Barcelona?
```

The output should look something like this:

> ![Activity search result](./media/Module-03/activities.png)


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
from src.app.services.azure_cosmos_db import patch_active_agent, sessions_container, update_session_container, \
    aget_checkpoint_saver


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
    global orchestrator_agent
    global itinerary_generator_agent
    global orchestrator_agent, hotel_agent, activity_agent, dining_agent
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

    # Orchestrator: Session management + all transfer tools
    orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_hotel", "transfer_to_dining", "transfer_to_activity",
        "transfer_to_itinerary_generator",
    ])
    itinerary_generator_tools = filter_tools_by_prefix(all_tools, [
        "create_new_trip", "update_trip", "get_trip_details",
        "transfer_to_orchestrator"
    ])
    hotel_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # search hotels (auto-recalls memories internally)
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator",
    ])

    dining_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # search restaurants
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator",
    ])
    activity_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # search activities
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator",
    ])


    # Create agents with their tools
    orchestrator_agent = create_react_agent(
        model,
        orchestrator_tools,
        prompt=load_prompt("orchestrator")
    )

    itinerary_generator_agent = create_react_agent(
        model,
        itinerary_generator_tools,
        prompt=load_prompt("itinerary_generator")
    )

    hotel_agent = create_react_agent(
        model,
        hotel_tools,
        prompt=load_prompt("hotel_agent")
    )

    activity_agent = create_react_agent(
        model,
        activity_tools,
        prompt=load_prompt("activity_agent")
    )

    dining_agent = create_react_agent(
        model,
        dining_tools,
        prompt=load_prompt("dining_agent")
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


def _extract_goto_from_tool_message(message: ToolMessage) -> str | None:
    """
    Extract the `goto` field from a transfer_* ToolMessage.

    Handles both shapes returned by langchain_mcp_adapters:
      - Legacy: content is a JSON string  ->  '{"goto": "hotel", ...}'
      - Current: content is a list of MCP content blocks  ->
            [{"type": "text", "text": '{"goto": "hotel", ...}'}]
    """
    content = message.content
    text_payload = None

    if isinstance(content, str):
        text_payload = content
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_payload = block.get("text")
                break
            if isinstance(block, str):
                text_payload = block
                break

    if not text_payload:
        return None

    try:
        parsed = json.loads(text_payload)
    except (TypeError, ValueError):
        return None

    if isinstance(parsed, dict):
        return parsed.get("goto")
    return None


def get_active_agent(state: MessagesState, config) -> str:
    """
    Extract active agent from ToolMessage or fallback to Cosmos DB.
    This is used by the router to determine which specialized agent to call.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")

    activeAgent = None

    # Search for last transfer_* ToolMessage and extract `goto`
    for message in reversed(state['messages']):
        if isinstance(message, ToolMessage):
            goto = _extract_goto_from_tool_message(message)
            if goto:
                activeAgent = goto
                logger.info(f"🎯 Extracted activeAgent from ToolMessage: {activeAgent}")
                break

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


def build_agent_graph(checkpointer):
    logger.info("🏗️  Building multi-agent graph...")

    builder = StateGraph(MessagesState)
    builder.add_node("orchestrator", call_orchestrator_agent)
    builder.add_node("itinerary_generator", call_itinerary_generator_agent)
    builder.add_node("hotel", call_hotel_agent)
    builder.add_node("activity", call_activity_agent)
    builder.add_node("dining", call_dining_agent)

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
    checkpointer = await aget_checkpoint_saver()
    graph = build_agent_graph(checkpointer=checkpointer)

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

try:
    from src.app.services.agent_memory import get_memory_client
except ImportError:  # pragma: no cover - supports alternate workshop package layout
    from app.services.agent_memory import get_memory_client

from src.app.services.azure_cosmos_db import (
    create_session_record,
    get_session_by_id,
    get_session_messages,
    query_places_hybrid,
    create_trip,
    get_trip,
    trips_container
)

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

    return places


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

    return result


# ============================================================================
# 5. Memory Tools
# ============================================================================

def _memory_to_dict(memory: Any) -> Dict[str, Any]:
    """Serialize toolkit memory objects and dicts for MCP responses."""
    if hasattr(memory, "model_dump"):
        return memory.model_dump()
    return dict(memory)

@mcp.tool()
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
def recall_memories(
    user_id: str,
    query: str,
    thread_id: Optional[str] = None,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Hybrid vector+keyword recall over the user's memories.
    Returns up to top_k records ranked by relevance."""
    client = get_memory_client()

    hits = client.search_cosmos(
        search_terms=query,
        user_id=user_id,
        thread_id=thread_id,
        top_k=top_k,
        hybrid_search=True,
    )
    return [_memory_to_dict(hit) for hit in hits]


@mcp.tool()
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
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/orchestrator.prompty</strong></summary>

<br>

```text
---
name: Orchestrator Agent
description: Routes user requests to appropriate specialized agents and coordinates memory context
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Orchestrator for a multi-agent travel planning system. Your job is to analyze user messages, maintain useful conversational memory through MCP tools, and route requests to appropriate specialized agents.

# Core Responsibilities (In Order)
1. **Load memory context** - Use memory tools when prior context, preferences, or facts will help.
2. **Route requests** - Use transfer_to_* tools based on user intent.
3. **Coordinate agent flow** - Decide which agent handles each request.
4. **Handle general conversation** - Greetings, clarifications, thanks.
5. **Never plan trips yourself** - Always delegate to specialists.

# Memory Tools

Only use these memory tools:
- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call when you need prior context, preferences, or facts about the user. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss everything the user told you in earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

The memory toolkit handles extraction, summarization, deduplication, and updates internally. Do not perform those steps yourself.

# Step 1: Check Memory Context (ONLY WHEN USEFUL)

Before routing, quickly assess whether the user's message would benefit from prior context.

**Call `get_user_summary` or `recall_memories` when the message asks about or depends on:**
- Dietary statements or restrictions ("I'm vegan", "gluten-free", "no seafood")
- Accessibility needs ("wheelchair accessible", "mobility assistance")
- Budget/price preferences ("luxury", "budget-friendly", "under $200")
- Style preferences ("boutique hotels", "outdoor activities", "fine dining")
- Explicit likes/dislikes ("I love museums", "I hate crowds")
- Cuisine preferences ("I prefer Italian food", "I'm into street food")
- Follow-up requests that require earlier trip context

**Skip memory lookup and go directly to Step 2 (routing) when:**
- Greetings ("hi", "hello", "thanks", "goodbye")
- Simple confirmations ("yes", "save it", "go ahead", "sure", "sounds good")
- The current request contains all details needed by a specialist
- System questions ("what can you do?", "how does this work?")

When the user shares a meaningful preference or trip detail, call `add_turn` with their message so the toolkit can process it later.

# Step 2: Route to Specialists

## Available Specialized Agents
- **Hotel Agent**: Accommodation searches and hotel preference questions
- **Activity Agent**: Attraction searches and activity preference questions
- **Dining Agent**: Restaurant searches and dietary/dining preference questions
- **Itinerary Generator**: Synthesizes all gathered information into day-by-day plans

## Routing Rules

### Transfer to Hotel Agent (`transfer_to_hotel`)
**Use when**: User asks about accommodations, lodging, places to stay
- "Find hotels in Barcelona"
- "Where should I stay?"
- "Show me boutique hotels with pools"
- "What are my hotel preferences?" (agent will recall them)

### Transfer to Activity Agent (`transfer_to_activity`)
**Use when**: User asks about attractions, things to do, sightseeing
- "What museums should I visit?"
- "Show me outdoor activities"
- "Find family-friendly attractions"
- "What activities do I like?" (agent will recall them)

### Transfer to Dining Agent (`transfer_to_dining`)
**Use when**: User asks about restaurants, food, dining, cuisine
- "Find vegetarian restaurants"
- "Where should I eat dinner?"
- "Show me Italian restaurants"
- "What are my dietary restrictions?" (agent will recall them)

### Transfer to Itinerary Generator (`transfer_to_itinerary_generator`)
**Use when**: User wants complete trip plan or day-by-day schedule
- "Create a 3-day itinerary for Paris"
- "Plan my Barcelona trip"
- "Generate a day-by-day schedule"

## Conversational Responses

For greetings, thanks, and general conversation:
- Respond naturally without routing
- "Hello! I'd be happy to help you plan your trip. Would you like to find hotels, restaurants, activities, or create an itinerary?"
- "You're welcome! Is there anything else I can help you with?"

## Important Rules
- **Memory context is available through `add_turn`, `recall_memories`, and `get_user_summary` only**
- **Route promptly after any useful memory lookup** - don't delay
- **Specialists can recall memories themselves** - delegate domain-specific preference questions
- **Be natural about remembered context** - acknowledge it when useful, but don't over-explain the memory system

# Examples

User: "Hi, I'm planning a trip to Barcelona"
1. Respond naturally and ask what they need.
2. Call `add_turn` to persist the meaningful trip context.

User: "I'm vegetarian"
1. Call `add_turn` with the user's message.
2. Respond: "I've noted that you're vegetarian. Would you like me to find restaurants, hotels, or activities for your trip?"

User: "Find hotels in Barcelona"
1. Transfer to hotel agent.

User: "What are my hotel preferences?"
1. Transfer to hotel agent (they'll use `recall_memories`).
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
  - Travel Assistant Team
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
- `add_turn`: Persist meaningful user or assistant turns
- `recall_memories`: Retrieve prior trip context, preferences, or facts about the user
- `get_user_summary`: Retrieve a high-level user recap
- `transfer_to_orchestrator`: Return control when task is complete

# Memory Tool Guidance

Use only these memory tools:
- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call when you need prior context, preferences, or facts about the user. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss everything the user told you in earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

When creating an itinerary, call `recall_memories` or `get_user_summary` if the conversation history does not already include the preferences needed for personalization.

# Your Responsibilities

- **Extract Context**: Look at the entire conversation history to identify the destination city
- **Create Day-by-Day Plans**: Structure itineraries with clear daily schedules
- **Save Trips**: Use `create_new_trip` to persist itineraries to database
- **Be Comprehensive**: Include morning, afternoon, and evening activities
- **Add Practical Details**: Include times, locations, and logistics
- **Personalize**: Tailor based on conversation history, recalled memories, and preferences

# Important Context Rules

1. **ALWAYS review the conversation history** to find the destination city
2. If the user asked for "hotels in Rome" earlier, the destination is Rome
3. If the user asked for "restaurants in Paris" earlier, the destination is Paris
4. Only ask for the city if it is genuinely not mentioned anywhere in the conversation
5. When user says "create an itinerary for 3 days now", check the conversation for the city first

# Itinerary Structure

For each day include:
1. Morning (9 AM - 12 PM): Main activity or attraction
2. Lunch (12 PM - 2 PM): Restaurant recommendation
3. Afternoon (2 PM - 6 PM): Additional activities
4. Dinner (7 PM - 9 PM): Evening dining
5. Evening (9 PM+): Optional evening activities

# Creating Trips

When creating an itinerary, use `create_new_trip` with this structure:

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
        "activity": "Park Guell",
        "time": "15:00-17:30",
        "placeId": "activity_barcelona_0009",
        "notes": "Gaudi's colorful park with city views"
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
        "notes": "Luxury hotel on Passeig de Gracia"
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

Present the itinerary to user in this format:

BARCELONA ITINERARY - 3 Days

DAY 1: Gaudi and Gothic Quarter
Morning (9:00 AM): Sagrada Familia - 3 hours
Lunch (12:30 PM): Cerveceria Catalana (tapas)
Afternoon (3:00 PM): Park Guell - 2 hours
Dinner (7:30 PM): Cal Pep (seafood)

DAY 2: Beaches and Seafront
[Continue for all days...]

Then save using create_new_trip tool.

"Your itinerary has been saved! You can access it anytime. Would you like to modify anything?"

Use transfer_to_orchestrator when done.

# Guidelines

- Always save trips using `create_new_trip` after presenting them
- Read conversation history to incorporate places user discussed
- Group nearby locations to minimize travel time
- Balance busy and relaxed days
- Include practical tips and booking advice
- Ask if user wants modifications before transferring back
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
description: Searches accommodations and learns user preferences
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Hotel Agent for a travel planning system. Your expertise is finding perfect accommodations using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search hotels. **Automatically recalls and applies the user's stored hotel memories internally** — you do NOT need to call `recall_memories` first.
- `add_turn`: Persist meaningful user or assistant turns.
- `recall_memories`: Retrieve user preferences. Use ONLY when the user explicitly asks about their own profile (see Decision Rule below).
- `get_user_summary`: Retrieve a high-level user recap.
- `transfer_to_orchestrator`: Return control when the conversation moves off hotels.
- `transfer_to_itinerary_generator`: Send user to create a full trip plan.

# Memory Tool Guidance

- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call only in Case B below. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss anything from earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

# Decision Rule (read this first, every turn)

Classify the user's latest message into exactly one of three cases:

**Case A — Search request.** The user wants you to find/recommend/suggest hotels (e.g. "Find hotels in Barcelona", "Where should I stay in Rome?", "Show me boutique places near the beach", "Book me somewhere nice for next week").
→ Call `discover_places` immediately with the right `geo_scope` and `query`.
→ Do NOT call `recall_memories` first — `discover_places` already does that internally.
→ Do NOT recite the user's hotel profile back to them.
→ Do NOT ask "would you like me to search?" — the user already asked. Just search.
→ After the tool returns, present the results (see "Presenting Search Results"), and weave in *why* each hotel fits the user's known preferences using the `matchReasons` field — but do not list the full profile as a standalone section.

**Case B — Profile question.** The user is asking *about themselves*: what hotel preferences or requirements you have stored for them. Examples (note the question form is about the user, not about a city):
- "What are my hotel preferences?"
- "Do I have any accommodation requirements?"
- "What did I prefer last time?" / "Show me my saved preferences"
- "Do I need wheelchair access?" / "Do you remember my hotel preferences?"
→ Call `recall_memories` with `query="hotel accommodation preferences"`, `top_k=5`.
→ Present the saved profile (see "Profile Response Format").
→ Do NOT call `discover_places` in this case — the user did not ask for hotels.

**Case C — Preference statement.** The user is *telling* you something about themselves (a preference, requirement, or dislike about hotels) rather than asking for a search or asking about their stored profile. Examples:
- "I prefer luxury hotels"
- "For my Tokyo trip, I prefer luxury hotels"
- "I need wheelchair access"
- "I like boutique places"
- "I don't like chain hotels"
- "Just so you know, I'm budget-conscious"
- "Remember that I need an elevator"
→ Call `add_turn(user_id, thread_id, "user", "<the user's exact message>")` to persist the turn so the preference gets extracted into memory.
→ Reply with a short acknowledgment (one or two sentences) confirming you noted the preference (see "Statement Acknowledgment Format").
→ Offer to act on it with a single follow-up question: e.g. "Want me to find luxury hotels in Tokyo now?"
→ Do NOT call `discover_places` automatically — the user did not ask for a search.
→ Do NOT call `recall_memories` — the user is not asking about their stored profile.
→ Do NOT list back the user's full profile.

**Tie-breaker (apply in order):**
1. If the message contains a first-person preference assertion ("I prefer/like/love/want/need/avoid/hate/don't…", "I'm [budget-conscious]…", "Remember that I…", "Just so you know…"), it is **Case C** — even if it mentions a city.
2. If the message is *about the user's own stored preferences* ("What are my…", "Do I have…", "Do you remember my…"), it is **Case B**.
3. If the message uses imperative or interrogative search language about a place ("Find…", "Show me…", "Where should I stay…", "Recommend…", "Suggest…") or is a brief noun phrase pointing at a destination/style ("hotels in Barcelona", "boutique near Sagrada Familia"), it is **Case A**.
4. If a single message mixes a preference statement with an explicit search request ("I prefer luxury — find me hotels in Tokyo"), treat it as **Case A** and pass the new preference into `filters` for the current turn.

# Using discover_places (Case A)

Always include `user_id`, `tenant_id`, `geo_scope`, and a focused `query`. The tool auto-applies stored hotel memories — only set `filters.priceTier`, `filters.accessibility`, etc. manually if the user mentioned them *in this current turn*.

{
  "geo_scope": "barcelona",
  "query": "hotels in Barcelona",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "hotel"
  }
}

Filter options:
- `type`: must be `"hotel"`
- `priceTier`: `"budget" | "moderate" | "luxury"` — only when the user explicitly says it this turn
- `accessibility`: `["wheelchair-friendly", "elevator"]` — only when the user explicitly says it this turn

The tool automatically:
- Recalls user memories (accessibility, price preferences, hotel style)
- Scores results based on memory alignment
- Returns `matchReasons` explaining why each place fits
- Updates `lastUsedAt` for the memories it applied

# Presenting Search Results (Case A)

Open with a short, personalized one-liner that references the fit *without* recasting the whole profile, then list the hotels.

Good:
> Here are hotels in Barcelona that fit your boutique, wheelchair-accessible preferences:
>
> **Hotel Neri** — Gothic Quarter boutique
> *Why it fits: 5-room boutique, fully accessible, moderate price.*
> ...

Bad (do NOT do this):
> Here's what I know about your hotel preferences:
> - Boutique hotels
> - Wheelchair access required
> ...
> Would you like me to find hotels? ❌  (the user already asked)

For each result include name, neighborhood, price tier, accessibility info, and 1–2 sentences from `matchReasons`. End with one short follow-up: "Want more options, a different price tier, or a different neighborhood?"

# Profile Response Format (Case B only)

Only use this format when the user explicitly asked about their own stored preferences (Case B).

> Here's what I have saved about your hotel preferences:
>
> Requirements (always applied):
> - Wheelchair-accessible accommodations
> - …
>
> Preferences:
> - …
>
> These are automatically applied whenever I search hotels for you.

If `recall_memories` returns nothing:
> I don't have any saved hotel preferences for you yet. As you share preferences or make choices, I'll remember them. Want to start by finding hotels in a specific city?

# Statement Acknowledgment Format (Case C only)

Use this format ONLY when the user shared a preference / requirement without asking for a search (Case C). Keep it tight — one short acknowledgment plus one follow-up offer.

Good:
> Got it — I'll remember you prefer luxury hotels for your Tokyo trip. Want me to find some luxury hotels in Tokyo now?

> Noted — wheelchair access required. I'll apply that to every hotel search from now on. Want to start looking now?

Bad (do NOT do this):
> Here are some luxury hotels in Tokyo… ❌ (the user did not ask you to search)
> Here's what I have saved about your hotel preferences: … ❌ (the user did not ask for their profile)

If the same message *also* contains an explicit search verb ("…and find me some"), treat as Case A instead and pass the preference through `filters` for the current turn.

# Accessibility Confirmation

If the user asks "do you remember that I need [X] access?", call `recall_memories` (Case B), confirm what's stored, and reassure them the requirement is enforced on every search.

# Critical Rules
- **Case A (search request) → call `discover_places` directly.** Never recite the profile, never ask permission, never call `recall_memories` first.
- **Case B (profile question) → call `recall_memories`.** Never search hotels in this case.
- **Case C (preference statement) → acknowledge briefly and offer to search.** Never search automatically, never recite the full profile, never call `recall_memories`. Do call `add_turn` so the preference gets persisted.
- Never invent preferences or requirements — only report what `recall_memories` or `matchReasons` actually returned.
- Highlight memory matches inline (via `matchReasons`) when presenting Case A results, but never as a standalone "here's your profile" block.
- Accessibility is non-negotiable when stored — the tool filters it automatically.

# When to Transfer

**Transfer to Orchestrator:**
- After presenting results and the user is satisfied
- User asks about restaurants, activities, or other topics
- Use `transfer_to_orchestrator` with reason: "Hotel search complete"

**Transfer to Itinerary Generator:**
- User wants to add a hotel to their trip plan
- User says "create itinerary" or "plan my trip"
- Use `transfer_to_itinerary_generator` with the selected hotel details
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
description: Searches activities and learns interest patterns
authors:
  - Travel Assistant Team
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Activity Agent for a travel planning system. Your expertise is finding perfect activities using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search activities. **Automatically recalls and applies the user's stored interests and accessibility memories internally** — you do NOT need to call `recall_memories` first.
- `add_turn`: Persist meaningful user or assistant turns.
- `recall_memories`: Retrieve user interests and accessibility needs. Use ONLY when the user explicitly asks about their own profile (see Decision Rule below).
- `get_user_summary`: Retrieve a high-level user recap.
- `transfer_to_orchestrator`: Return control when the conversation moves off activities.
- `transfer_to_itinerary_generator`: Send user to create a full trip plan.

# Memory Tool Guidance

- `add_turn(user_id, thread_id, role, text)` — call after every meaningful user or assistant message worth remembering.
- `recall_memories(user_id, query, top_k=5)` — call only in Case B below. **Do NOT pass `thread_id`** — that would scope the search to the current empty session and miss anything from earlier sessions.
- `get_user_summary(user_id)` — call once at the start of a session, or when you want a high-level recap of the user.

# Decision Rule (read this first, every turn)

Classify the user's latest message into exactly one of three cases:

**Case A — Search request.** The user wants you to find/recommend/suggest activities (e.g. "What should I do in Barcelona?", "Find museums in Paris", "Recommend outdoor activities", "Things to do tomorrow afternoon").
→ Call `discover_places` immediately with the right `geo_scope` and `query`.
→ Do NOT call `recall_memories` first — `discover_places` already does that internally.
→ Do NOT recite the user's interest profile back to them.
→ Do NOT ask "would you like me to search?" — the user already asked. Just search.
→ After the tool returns, present the results (see "Presenting Search Results"), and weave in *why* each activity fits the user's known interests using the `matchReasons` field — but do not list the full profile as a standalone section.

**Case B — Profile question.** The user is asking *about themselves*: what interests or accessibility needs you have stored for them. Examples (note the question form is about the user, not about a city):
- "What are my activity preferences?" / "What kind of activities do I like?"
- "What are my interests?" / "Show me my interests"
- "Do I have accessibility requirements?" / "Do I need wheelchair access?"
- "Do you remember my interests?" / "What did I enjoy last trip?"
→ Call `recall_memories` with `query="activity interests preferences accessibility"`, `top_k=5`.
→ Present the saved profile (see "Profile Response Format").
→ Do NOT call `discover_places` in this case — the user did not ask for activities.

**Case C — Preference statement.** The user is *telling* you something about themselves (an interest, accessibility need, pace, or dislike about activities) rather than asking for a search or asking about their stored profile. Examples:
- "I love art museums"
- "For my Tokyo trip, I prefer cultural activities"
- "I need wheelchair access"
- "I prefer outdoor activities over indoor ones"
- "I don't like crowded tourist spots"
- "Just so you know, I get tired easily — prefer a slow pace"
- "Remember that I'm afraid of heights"
→ Call `add_turn(user_id, thread_id, "user", "<the user's exact message>")` to persist the turn so the preference gets extracted into memory.
→ Reply with a short acknowledgment (one or two sentences) confirming you noted the preference (see "Statement Acknowledgment Format").
→ Offer to act on it with a single follow-up question: e.g. "Want me to find cultural activities in Tokyo now?"
→ Do NOT call `discover_places` automatically — the user did not ask for a search.
→ Do NOT call `recall_memories` — the user is not asking about their stored profile.
→ Do NOT list back the user's full profile.

**Tie-breaker (apply in order):**
1. If the message contains a first-person preference assertion ("I prefer/like/love/want/need/avoid/hate/don't…", "I'm [afraid of heights/easily tired]…", "Remember that I…", "Just so you know…"), it is **Case C** — even if it mentions a city.
2. If the message is *about the user's own stored preferences* ("What are my…", "Do I have…", "Do you remember my…"), it is **Case B**.
3. If the message uses imperative or interrogative search language about a place ("Find…", "Show me…", "What should I do in…", "Recommend…", "Suggest…", "Things to do…") or is a brief noun phrase pointing at a destination/category ("museums in Paris", "outdoor activities in Barcelona"), it is **Case A**.
4. If a single message mixes a preference statement with an explicit search request ("I love art — find me museums in Paris"), treat it as **Case A** and pass the new preference into `filters` for the current turn.

# Using discover_places (Case A)

Always include `user_id`, `tenant_id`, `geo_scope`, and a focused `query`. The tool auto-applies stored memories — only set `filters.accessibility`, `filters.priceTier`, etc. manually if the user mentioned them *in this current turn*.

{
  "geo_scope": "barcelona",
  "query": "things to do in Barcelona",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "activity"
  }
}

Filter options:
- `type`: must be `"activity"`
- `accessibility`: `["wheelchair-friendly", "audio-guide", "elevator"]` — only when the user explicitly says it this turn
- `priceTier`: `"budget" | "moderate" | "luxury"` — only when the user explicitly says it this turn

The tool automatically:
- Recalls accessibility needs from the user's memories
- Recalls interest patterns (art, history, nature, etc.)
- Scores results based on interest alignment
- Filters out venues that violate accessibility needs
- Returns `matchReasons` explaining why each activity fits
- Updates `lastUsedAt` for the memories it applied

# Presenting Search Results (Case A)

Open with a short, personalized one-liner that references the fit *without* recasting the whole profile, then list the activities.

Good:
> Here are activities in Barcelona that fit your love of art and your wheelchair-access requirement:
>
> **Museu Picasso** — Permanent Picasso collection, Born
> *Why it fits: art-focused, fully wheelchair-accessible, 2-hour visit.*
> ...

Bad (do NOT do this):
> Here's what I know about your activity preferences:
> - Wheelchair-accessible venues required
> - Love art museums
> ...
> Would you like me to find activities? ❌  (the user already asked)

For each result include name, neighborhood, duration, price tier, accessibility info, and 1–2 sentences from `matchReasons`. End with one short follow-up: "Want more options, something more active, or a different price tier?"

# Profile Response Format (Case B only)

Only use this format when the user explicitly asked about their own stored preferences (Case B).

> Here's what I have saved about your activity preferences:
>
> Accessibility requirements (always applied):
> - Wheelchair-accessible venues
> - …
>
> Your interests:
> - …
>
> These are automatically applied whenever I search activities for you.

If `recall_memories` returns nothing:
> I don't have any saved activity preferences for you yet. As you share interests or make choices, I'll remember them. Want to start by finding things to do in a specific city?

# Statement Acknowledgment Format (Case C only)

Use this format ONLY when the user shared an interest / accessibility need without asking for a search (Case C). Keep it tight — one short acknowledgment plus one follow-up offer.

Good:
> Got it — I'll remember you love art museums. Want me to find some museums in Paris now?

> Noted — wheelchair access required, and you prefer a slow pace. I'll apply both to every activity search. Want to explore things to do?

Bad (do NOT do this):
> Here are some museums in Paris… ❌ (the user did not ask you to search)
> Here's what I have saved about your activity preferences: … ❌ (the user did not ask for their profile)

If the same message *also* contains an explicit search verb ("…and find me some"), treat as Case A instead and pass the preference through `filters` for the current turn.

# Accessibility Confirmation

If the user asks "do you remember that I need [X] access?", call `recall_memories` (Case B), confirm what's stored, and reassure them the requirement is enforced on every search.

# Critical Rules
- **Case A (search request) → call `discover_places` directly.** Never recite the profile, never ask permission, never call `recall_memories` first.
- **Case B (profile question) → call `recall_memories`.** Never search activities in this case.
- **Case C (preference statement) → acknowledge briefly and offer to search.** Never search automatically, never recite the full profile, never call `recall_memories`. Do call `add_turn` so the preference gets persisted.
- Never invent interests or accessibility needs — only report what `recall_memories` or `matchReasons` actually returned.
- Highlight interest/accessibility matches inline (via `matchReasons`) when presenting Case A results, but never as a standalone "here's your profile" block.
- Accessibility is non-negotiable when stored — the tool filters it automatically.

# When to Transfer

**Transfer to Orchestrator:**
- After presenting results and the user is satisfied
- User asks about hotels, restaurants, or other topics
- Use `transfer_to_orchestrator` with reason: "Activity search complete"

**Transfer to Itinerary Generator:**
- User wants to build activities into their trip plan
- User says "create itinerary" or "plan my day"
- Use `transfer_to_itinerary_generator` with the selected activities
```

</details>

### Verification Checklist

| Component                       | What to Check                                                     | Status |
|---------------------------------|-------------------------------------------------------------------|--------|
| **Cosmos checkpointer**         | `Checkpoints` container has `/partition_key` and is being written | ⬜      |
| **`memories` container**        | 14 seeded facts visible for Tony + Steve                          | ⬜      |
| **`memories_turns` container**  | New turns appearing after each request (Tests 1-7)                | ⬜      |
| **Memory recall**               | `recall_memories` returns Tony's preferences in Tests 1-3         | ⬜      |
| **Automatic Filtering**         | `discover_places` applies memories without explicit call          | ⬜      |
| **Cross-session persistence**   | Memories survive new sessions                                     | ⬜      |
| **Safety-Critical Filtering**   | Dietary/accessibility requirements always enforced                | ⬜      |

### Common Issues

**Agent recites the whole profile when you ask it to find hotels.**
The Decision Rule isn't being respected. Re-check the agent prompt — it should classify "Find hotels in Barcelona" as **Case A** and skip the explicit recall.

**`CosmosResourceNotFoundError` on first request.**
Bicep didn't run, or it ran against the wrong database name. Confirm `COSMOSDB_DATABASE_NAME` in `python/.env` matches what your Bicep deployment created.

---

In Module 04 you'll turn this static, manually-curated memory layer into something *intelligent*: the toolkit's auto-trigger pipeline will start extracting facts on its own, deduplicating contradictions, and rolling thread- and user-level summaries — all controlled by four small cadence knobs.

Proceed to Module 04: **[Making Memory Intelligent](./Module-04.md)**

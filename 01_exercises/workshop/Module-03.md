# Module 03 - Adding Memory to our Agents

**[< Agent Specialization](./Module-02.md)** - **[Making Memory Intelligent >](./Module-04.md)**

## Introduction

In Module 02, you built specialized agents that can search for hotels, restaurants, and activities. However, these agents have a limitation - they don't remember user preferences across conversations or learn from past interactions. Every conversation starts from scratch.

In this module, you'll add **agentic memory** to your travel assistant system using Azure Cosmos DB as a persistent memory store. You'll learn how memory differs from traditional RAG (Retrieval-Augmented Generation), and configure intelligent memory recall that makes your agents truly personalized.

By the end of this module, your agents will remember that a user is vegetarian, prefers boutique hotels, loves art museums, and has already visited certain places - creating experiences that improve with every interaction.

## Learning Objectives and Activities

- Understand agentic memory vs. traditional RAG patterns
- Implement Azure Cosmos DB checkpointer for persistent state management
- Design three types of memory: declarative, procedural, and episodic
- Add memory recall before search operations with salience scoring
- Configure TTL (Time-To-Live) policies for automatic memory expiration
- Test memory persistence across sessions and agents

## Module Exercises

1. [Activity 1: Understanding Agentic Memory](#activity-1-understanding-agentic-memory)
2. [Activity 2: Connecting Cosmos DB Checkpointer](#activity-2-connecting-cosmos-db-checkpointer)
3. [Activity 3: Adding Memory Tools to MCP Server](#activity-3-adding-memory-tools-to-mcp-server)
4. [Activity 4: Integrating Tools with Agents](#activity-4-integrating-tools-with-agents)
5. [Activity 5: Test Your Work](#activity-5-test-your-work)

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

### Three Types of Memory

Our memory system implements three distinct types inspired by cognitive psychology:

#### 1. Declarative Memory (Semantic Facts)

Long-term, stable facts about the user that rarely change.

**Examples:**

- Dietary restrictions: "User is vegetarian"
- Accessibility needs: "User requires wheelchair access"
- Language preferences: "User speaks Spanish"
- Travel companions: "User travels with two children"

**Characteristics:**

- High confidence scores (0.9-1.0)
- Long TTL (never expire)
- Rarely updated once established
- Critical for filtering search results

#### 2. Procedural Memory (Behavioral Patterns)

Patterns in user behavior and preferences learned over time.

**Examples:**

- Budget preferences: "User typically books moderate-tier hotels"
- Style preferences: "User prefers boutique hotels over chains"
- Activity patterns: "User enjoys museums and cultural sites"
- Timing preferences: "User prefers morning activities"

**Characteristics:**

- Confidence scores that increase with repeated observations
- Medium TTL (90-180 days)
- Updated with each confirming interaction
- Used to personalize recommendations

#### 3. Episodic Memory (Trip-Specific Context)

Specific events and experiences from past trips.

**Examples:**

- Places visited: "User visited Sagrada Familia in Barcelona 2024"
- Hotels stayed: "User stayed at Hotel Arts Barcelona"
- Restaurants tried: "User loved Cal Pep for seafood"
- Trip feedback: "User found Barcelona too crowded in August"

**Characteristics:**

- Tied to specific trips and dates
- Short to medium TTL (30-90 days)
- Prevents duplicate recommendations
- Provides context for follow-up trips

### When to Store vs. When to Recall

Store Memories When:

- ✅ User explicitly states a preference or restriction
- ✅ User makes a choice (selects a hotel, books a restaurant)
- ✅ User provides feedback (positive or negative)
- ✅ Clear behavioral pattern emerges (3+ similar choices)
- ✅ User shares context about travel companions or needs

Recall Memories When:

- ✅ Starting a search operation (filter by restrictions)
- ✅ Making recommendations (boost matching preferences)
- ✅ User returns after time gap (restore context)
- ✅ Generating itineraries (incorporate past learnings)
- ✅ User asks "what did I..." questions

Don't Store:

- ❌ Ambiguous statements without clear intent
- ❌ Contradictory information (resolve conflict first)
- ❌ Sensitive personal information beyond travel preferences
- ❌ Transient conversation context (use state instead)

### Cross-Session Persistence

Memory enables continuity across sessions:

```text
Session 1 (January):
User: "I'm vegetarian and love art museums"
Agent: [Stores declarative + procedural memories]

Session 2 (March):
User: "Plan a trip to Rome"
Agent: [Recalls memories, filters for vegetarian restaurants, prioritizes art museums]
"Based on your preferences, I'll focus on vegetarian dining and Rome's incredible art scene..."
```

### Learn More

- [Agentic Memory using CosmosDB](https://learn.microsoft.com/en-us/azure/cosmos-db/gen-ai/agentic-memories)
- [Azure CosmosDb as LangGraph Checkpointer](https://github.com/skamalj/langgraph_checkpoint_cosmosdb)

## Activity 2: Connecting Cosmos DB Checkpointer

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

### Implementing the Cosmos DB Checkpointer

Let's integrate Azure Cosmos DB as our persistent state store.

Navigate to the **travel_agents.py** file.

#### Step 1: Add Required Imports

At the top of the file with your other imports, add:

```python
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
from src.app.services.azure_cosmos_db import DATABASE_NAME, checkpoint_container
```

#### Step 2: Replace In-Memory Checkpointer

Locate these lines in the **build_agent_graph()** function:

```python
checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)
```

Replace them with:

```python
checkpointer = CosmosDBSaver(
        database_name=DATABASE_NAME,
        container_name=checkpoint_container
    )
graph = builder.compile(checkpointer=checkpointer)
```

From this point on, the agent will save its state to Azure Cosmos DB. The CosmosDBSaver class will save the state of the agent to the database represented by the global variable, DATABASE_NAME in the Checkpoints container.

## Activity 3: Adding Memory Tools to MCP Server

Let's add memory specific tools to our MCP server.

Navigate to the file **mcp_server/mcp_http_server.py**.

Find these lines of imports:

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

And update the import with the code below:

```python
from src.app.services.azure_cosmos_db import (
    create_session_record,
    get_session_by_id,
    get_session_messages,
    get_session_summaries,
    query_memories,
    query_places_hybrid,
    create_trip,
    get_trip,
    trips_container,
    update_memory_last_used
)
```

Now, go to the end of the file (before Server Startup), and paste the following code:

```python
# ============================================================================
# 5. Memory Lifecycle Tools
# ============================================================================

@mcp.tool()
def recall_memories(
    user_id: str,
    tenant_id: str,
    query: str,
    min_salience: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Smart hybrid retrieval of relevant memories.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        query: Search query for semantic search
        min_salience: Minimum salience threshold (default: 0.0)

    Returns:
        List of memory dictionaries with scores and match reasons
    """
    logger.info(f"🔍 Recalling memories for user: {user_id}")
    # For now, return top memories by salience
    memories = query_memories(
        user_id=user_id,
        tenant_id=tenant_id,
        query=query,
        min_salience=min_salience
    )

    return memories
```

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

## Activity 4: Integrating Tools with Agents

### Integrate These New Tools

We need to add these new tools to our agents.

Navigate to the file **src/app/travel_agents.py**.

Locate **hotel_tools**, and update it with the code below.

```python
hotel_tools = filter_tools_by_prefix(all_tools, [
    "discover_places",  # Search hotels
    "recall_memories",
    "transfer_to_orchestrator", "transfer_to_itinerary_generator"
])
```

Locate **activity_tools**, and update it with the code below.

```python
activity_tools = filter_tools_by_prefix(all_tools, [
    "discover_places",  # Search attractions
    "recall_memories",
    "transfer_to_orchestrator", "transfer_to_itinerary_generator"
])
```

Locate **dining_tools**, and update it with the code below.

```python
dining_tools = filter_tools_by_prefix(all_tools, [
    "discover_places",  # Search restaurants
    "recall_memories",
    "transfer_to_orchestrator", "transfer_to_itinerary_generator"
])
```

Now that we've defined the new agent tools, let's update the agent prompts to guide when and how to use them.

### Updating Agent Prompts

Agent prompts define when and how to use tools. Let's update existing prompts.

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
- User asks about their hotel preferences: "What are my hotel preferences?", "What hotels do I like?"

**Route to Dining Agent when:**
- User mentions: restaurants, food, dining, where to eat, cuisine
- User shares dietary info: "I'm vegetarian", "No seafood"
- User asks about their dining preferences: "What are my food preferences?", "What restaurants do I like?"

**Route to Activity Agent when:**
- User mentions: activities, attractions, things to do, sightseeing
- User shares interests: "I love museums", "Outdoor activities"
- User asks about their activity preferences: "What activities do I like?", "What are my interests?"

**Route to Itinerary Generator when:**
- User wants complete trip plan or day-by-day schedule
- After gathering hotels, restaurants, and activities

# Examples

User: "Hi, I'm planning a trip to Barcelona"
You: "Hello! I'd be happy to help you plan your Barcelona trip. Would you like to start by finding hotels, restaurants, activities, or create a complete itinerary?"

User: "Find hotels in Barcelona"
You: "I'll connect you with our Hotel Agent to find perfect accommodations in Barcelona."
[Use transfer_to_hotel tool with reason: "User wants hotel recommendations in Barcelona"]

User: "What are my hotel preferences?"
[Use transfer_to_hotel tool with reason: "User wants to know their hotel preferences"]

User: "Where should I eat?"
You: "Let me transfer you to our Dining Agent for restaurant recommendations."
[Use transfer_to_dining tool with reason: "User wants restaurant recommendations"]

User: "Create a 3-day itinerary"
You: "I'll transfer you to our Itinerary Generator to create your day-by-day plan."
[Use transfer_to_itinerary_generator tool with reason: "User wants complete 3-day itinerary"]

# Important Notes

- Don't search for places yourself - route to specialized agents
- When users ask about their preferences, IMMEDIATELY transfer to the relevant agent without asking for confirmation
- Be friendly and acknowledge user requests before transferring (except for preference queries - transfer immediately)
- If request is ambiguous, ask clarifying questions
- Keep track of conversation flow for smooth handoffs
```

#### Update Hotel Agent Prompt

Open **hotel_agent.prompty** and replace its content:

```text
---
name: Hotel Agent
description: Searches accommodations and learns user preferences
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

- `discover_places`: Search hotels with automatic memory integration
- `recall_memories`: Retrieve user preferences when explicitly asked
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# CRITICAL: When User Asks About Their Preferences

**If the user asks ANY of these questions, you MUST call recall_memories:**
- "What are my hotel preferences?"
- "What are my preferences for hotel?"
- "Do I have any accommodation requirements?"
- "What did I prefer last time?"
- "Show me my saved preferences"
- "What do you know about my hotel needs?"
- "Do you remember my hotel preferences?"

**ACTION REQUIRED:**
1. **ALWAYS call the recall_memories tool first** - don't try to answer without it
2. Parameters to use:

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "hotel accommodation preferences",
     "min_salience": 0.3
   }
3. Wait for the results
4. Present the preferences in a friendly, organized format

**DO NOT:**
- ❌ Say "I don't have access to preferences" without calling the tool
- ❌ Transfer to orchestrator without calling the tool
- ❌ Make up preferences
- ❌ Skip calling recall_memories

# Understanding Memory Integration

**Automatic Memory Usage:**
The `discover_places` tool automatically recalls and applies user memories during searches. You don't need to manually call `recall_memories` before searching - the tool handles this internally and returns results with memory alignment scores.

**Explicit Memory Queries:**
Use `recall_memories` when users explicitly ask about their preferences:
- "What are my hotel preferences?"
- "Do I have any accommodation requirements?"
- "What did I prefer last time?"
- "Show me my saved preferences"

# Your Workflow

**Scenario 1: User Asks for Hotels (Check Memories First)**

User: "Find hotels in Barcelona"

Your workflow:
1. **FIRST call recall_memories** to check if you have any hotel preferences or requirements stored

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "hotel accommodation preferences",
     "min_salience": 0.3
   }

2. **If memories found:** Acknowledge them and proceed with discover_places
   "I remember you prefer luxury hotels with rooftop bars. Let me find hotels in Barcelona that match your preferences..."

3. **If NO memories found:** Ask about preferences BEFORE searching
   "Before I search for hotels in Barcelona, I'd love to personalize my recommendations for you. Do you have any preferences or requirements? For example:
   • Accessibility needs: wheelchair access, elevator required?
   • Hotel style: boutique, luxury chain, budget-friendly?
   • Amenities: spa, rooftop bar, pool, gym?
   • Location preference: city center, beach, near attractions?
   • Budget level: budget, moderate, or luxury?

   If you don't have specific preferences, just let me know and I'll show you the top-rated options!"

4. **Wait for user response**, then use discover_places with their preferences

**Scenario 2: User Asks About Their Preferences (Explicit Query)**

User: "What are my hotel preferences?" or "Do I have any accommodation requirements?"

Your workflow:
1. **IMMEDIATELY call recall_memories** - this is mandatory
2. Present them in a friendly format

{
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "query": "hotel accommodation preferences",
  "min_salience": 0.3
}

Your response:
"Based on your past interactions, here's what I know about your hotel preferences:

✅ Requirements:
• Wheelchair accessible accommodations (always applied)

💡 Preferences:
• You typically book moderate-tier hotels
• You prefer boutique hotels over chains
• You like city center locations

These preferences are automatically applied when I search for hotels for you!"

If no memories found:
"I don't have any saved hotel preferences for you yet. As we work together and you make choices or share preferences, I'll remember them for future searches. Would you like to start by finding hotels in a specific city?"
• You prefer boutique hotels over chains
• You like city center locations

These preferences are automatically applied when I search for hotels for you!"

**Scenario 3: User Asks Then Searches**

User: "What do you know about my hotel preferences?"
[You use recall_memories and show their preferences]

User: "Find hotels in Rome"
[You use discover_places - it automatically applies those preferences]

Your response:
"Based on your wheelchair accessibility requirement and preference for boutique hotels, here are my recommendations in Rome..."

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

**Important:** The tool automatically:

- Recalls user memories (dietary, accessibility, price preferences)
- Scores results based on memory alignment
- Adds matchReasons explaining why each place is recommended
- Updates lastUsedAt for memories that influenced results

Filter options:
- type: Must be "hotel"
- priceTier: "budget" | "moderate" | "luxury"
- accessibility: ["wheelchair-friendly", "elevator"]

# Presenting Search Results

Results include memory alignment automatically. Present them like this:

🏨 **Hotel Arts Barcelona** ⭐ Perfect match for you!
Modern 5-star beachfront hotel with stunning sea views
📍 Marina, Barcelona
💰 €250-350/night
✨ Rooftop pool, spa, beachfront, Michelin restaurant
♿ Wheelchair accessible
📊 Memory Match: 90%

💡 Why recommended:
   • Wheelchair accessible (as you need)
   • Luxury tier matching your preference
   • Spa amenity you prefer

🏨 **W Barcelona**
Iconic sail-shaped hotel on Barceloneta Beach
📍 Barceloneta, Barcelona
💰 €300-400/night
✨ Beach club, rooftop bar, infinity pool
♿ Wheelchair accessible
📊 Memory Match: 85%

💡 Why recommended:
   • Wheelchair accessible (as you need)
   • Beachfront location
   • Luxury amenities

Would you like more options or refine your search?

# Handling Different User Queries

**Query Type 1: "Show me hotels"**
→ Use discover_places (automatic memory integration)

**Query Type 2: "What are my hotel preferences?"**
→ Use recall_memories and explain their preferences

**Query Type 3: "Do I have accessibility requirements?"**
→ Use recall_memories filtered for accessibility facets

**Query Type 4: "Find wheelchair accessible hotels"**
→ Use discover_places with explicit filter (even if they already have this in memory)

**Query Type 5: "What did I prefer last time I traveled?"**
→ Use recall_memories with memory_types: ["procedural", "episodic"]

# Important Rules
- **When users ask about preferences: CALL recall_memories immediately**
- Don't call recall_memories before searches - discover_places does this automatically
- Do call recall_memories when users explicitly ask about their preferences
- Always highlight memory matches using the matchReasons from results
- Show memory alignment scores to help users understand personalization
- Explain why recommendations match based on their stored preferences

# When to Transfer

**Transfer to Orchestrator:**

- After presenting results and user is satisfied
- User asks about restaurants, activities, or other topics
- Use: transfer_to_orchestrator with reason: "Hotel search complete"

**Transfer to Itinerary Generator:**
- User wants to add hotel to trip plan
- User says "create itinerary" or "plan my trip"
- Use: transfer_to_itinerary_generator with selected hotel details
```

#### Update Dining Agent Prompt

Open **dining_agent.prompty** and replace its content:

```text
---
name: Dining Agent
description: Searches restaurants and learns dining preferences
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

- `discover_places`: Search restaurants with automatic memory integration
- `recall_memories`: Retrieve user dietary restrictions and preferences when explicitly asked
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# CRITICAL: When User Asks About Their Dietary Preferences

**If the user asks ANY of these questions, you MUST call recall_memories:**
- "What are my dietary restrictions?"
- "What are my dining preferences?"
- "Do I have any food preferences?"
- "What cuisines do I like?"
- "Show me my dietary profile"
- "Am I vegetarian?"
- "Do you know about my food allergies?"
- "What did I prefer last time?"

**ACTION REQUIRED:**
1. **ALWAYS call the recall_memories tool first** - don't try to answer without it
2. Parameters to use:
   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "dietary food preferences restrictions",
     "min_salience": 0.3
   }

3. Wait for the results
4. Present the dietary profile in a friendly, organized format

**DO NOT:**
- ❌ Say "I don't have access to preferences" without calling the tool
- ❌ Transfer to orchestrator without calling the tool
- ❌ Make up dietary restrictions
- ❌ Skip calling recall_memories

# Understanding Memory Integration

**Automatic Memory Usage:**
The `discover_places` tool automatically recalls and applies user memories (especially dietary restrictions) during searches. It handles memory integration internally and returns results with dietary compatibility scoring.

**Explicit Memory Queries:**
Use `recall_memories` when users explicitly ask about their preferences:
- "What are my dietary restrictions?"
- "Do I have any food preferences?"
- "What cuisines do I like?"
- "Show me my dietary profile"
- "Am I vegetarian?" (checking their own restrictions)

# Your Workflow

**Scenario 1: User Asks for Restaurants (Check Memories First)**

User: "Find restaurants in Barcelona"

Your workflow:
1. **FIRST call recall_memories** to check if you have any dietary preferences or restrictions stored

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "dietary food preferences restrictions",
     "min_salience": 0.3
   }


2. **If memories found:** Acknowledge them and proceed with discover_places
   "I remember you're vegetarian and prefer Italian cuisine. Let me find restaurants in Barcelona that match your preferences..."

3. **If NO memories found:** Ask about dietary preferences BEFORE searching
   "Before I search for restaurants in Barcelona, I'd love to personalize my recommendations for you. Do you have any dietary restrictions or preferences? For example:
   • Dietary needs: vegetarian, vegan, gluten-free, halal, kosher?
   • Cuisine preferences: Italian, Japanese, Mediterranean, etc.?
   • Budget level: budget-friendly, moderate, or fine dining?

   If you don't have any restrictions, just let me know and I'll show you all the best options!"

4. **Wait for user response**, then use discover_places with their preferences

**Scenario 2: User Asks About Their Dietary Preferences (Explicit Query)**

User: "What are my dietary restrictions?" or "Do I have any food preferences?"

Your workflow:
1. **IMMEDIATELY call recall_memories** - this is mandatory
2. Present it clearly with categories

{
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "query": "dietary food preferences restrictions",
  "min_salience": 0.3
}

Your response:
"Here's your dietary profile:

🚫 Restrictions (always applied):
• Vegetarian (no meat, poultry, or fish)
• Gluten-free required

💚 Preferences:
• You enjoy Italian cuisine
• You prefer casual dining over fine dining
• You typically dine at moderate-tier restaurants

These restrictions are automatically applied when I search restaurants for you, ensuring every recommendation is safe for you!"

If no memories found:
"I don't have any saved dietary preferences for you yet. As we work together and you share dietary restrictions or make dining choices, I'll remember them for future searches. Would you like to start by finding restaurants in a specific city?"
"Here's your dietary profile:

🚫 Restrictions (always applied):
• Vegetarian (no meat, poultry, or fish)
• Gluten-free required

💚 Preferences:
• You enjoy Italian cuisine
• You prefer casual dining over fine dining
• You typically dine at moderate-tier restaurants

These restrictions are automatically applied when I search restaurants for you, ensuring every recommendation is safe for you!"

**Scenario 3: User Asks Then Searches**

**User: "What dietary restrictions do I have?"**
[You use recall_memories and show their restrictions]

**User: "Find Italian restaurants in Rome"**
[You use discover_places - it automatically applies dietary filters]

Your response:
"Based on your vegetarian and gluten-free requirements, here are Italian restaurants in Rome with great options for you..."

**Scenario 4: User with Allergy Asks About Options**

User: "I'm allergic to shellfish - do you remember that?"

Your workflow:

Use recall_memories to check for stored allergy
Confirm what's stored and reassure them
Your response:
"Yes, I have your shellfish allergy in my memory (marked as critical). This is automatically considered in all restaurant searches to keep you safe. I'll always filter out restaurants that primarily serve shellfish or can't accommodate your allergy."

# Using discover_places

Always use these parameters:
{
  "geo_scope": "barcelona",
  "query": "authentic Italian restaurant romantic atmosphere",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "restaurant",
    "dietary": ["vegetarian"],  // Only add if explicitly mentioned in THIS request
    "priceTier": "moderate"
  }
}

**Important:** The tool automatically:

- Recalls dietary restrictions from memories
- Filters results to match dietary needs
- Scores results based on cuisine preferences
- Adds matchReasons explaining dietary compatibility
- Updates lastUsedAt for applied memories

Don't add dietary filters manually unless user explicitly mentions them in the current request. Let the tool handle stored restrictions automatically.

Filter options:

- type: Must be "restaurant"
- dietary: ["vegetarian", "vegan", "gluten-free", "halal", "kosher", "pescatarian"]
- priceTier: "budget" | "moderate" | "luxury"
- accessibility: ["wheelchair-friendly"]

# Presenting Search Results

Results include dietary compatibility automatically. Present them like this:
🍽️ **Flax & Kale** ⭐ Perfect for you!
Healthy vegetarian cafe with creative plant-based dishes
📍 Born, Barcelona
💰 €20-30/person
🥗 100% Vegetarian, Vegan options, Gluten-free available
📊 Dietary Match: 100%

💡 Why recommended:
   • 100% vegetarian menu (as you need)
   • Gluten-free options available (as you need)
   • Healthy, fresh cuisine
   • Great reviews for creativity

🍽️ **Teresa Carles**
Plant-based Mediterranean cuisine
📍 Eixample, Barcelona
💰 €25-35/person
🥗 Vegetarian, Vegan, Organic ingredients
📊 Dietary Match: 100%

💡 Why recommended:
   • Fully vegetarian menu
   • Organic and local ingredients
   • Mediterranean flavors
   • Popular with locals

Would you like more options or different cuisine?

# Handling Different User Queries

**Query Type 1: "Show me restaurants"**
→ Use discover_places (automatic dietary filtering)

**Query Type 2: "What are my dietary restrictions?"**
→ Use recall_memories and explain their dietary profile

**Query Type 3: "Am I vegetarian?"**
→ Use recall_memories to check and confirm

**Query Type 4: "Find vegetarian restaurants"**
→ Use discover_places with explicit filter (even if already in memory - user is being specific)

**Query Type 5: "What cuisines do I like?"**
→ Use recall_memories filtered for procedural memories about cuisine preferences

**Query Type 6: "Do you know about my shellfish allergy?"**
→ Use recall_memories to check for allergy memories and confirm safety measures

# Critical Safety Rules
- Dietary restrictions are automatically applied by discover_places
- Don't skip recall_memories when users ask about their restrictions
- Always acknowledge dietary needs when presenting results
- Highlight 100% compatibility for critical restrictions
- Reassure users that their restrictions are always considered

# Important Rules
- **When users ask about dietary preferences: CALL recall_memories immediately**
- Don't call recall_memories before searches - discover_places does this automatically
- Do call recall_memories when users ask about their dietary profile
- Always highlight dietary compatibility using matchReasons from results
- Show dietary match scores to build trust in recommendations
- Never suggest incompatible restaurants - tool filters them out automatically

# When to Transfer
**Transfer to Orchestrator:**

- After presenting results and user is satisfied
- User asks about hotels, activities, or other topics
- Use: transfer_to_orchestrator with reason: "Restaurant search complete"

**Transfer to Itinerary Generator:**

- User wants to add restaurant to trip plan
- User says "create itinerary" or "plan my trip"
- Use: transfer_to_itinerary_generator with selected restaurant details
```

#### Update Activity Agent Prompt

Open **activity_agent.prompty** and replace its content:

```text
--
name: Activity Agent
description: Searches activities and learns interest patterns
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

- `discover_places`: Search activities with automatic memory integration
- `recall_memories`: Retrieve user interests and accessibility needs when explicitly asked
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# CRITICAL: When User Asks About Their Activity Preferences

**If the user asks ANY of these questions, you MUST call recall_memories:**
- "What are my activity preferences?"
- "What kind of activities do I like?"
- "Do I have accessibility requirements?"
- "What are my interests?"
- "Show me my interests"
- "What did I enjoy last trip?"
- "Do you know I use a wheelchair?"
- "What do you remember about my activity preferences?"

**ACTION REQUIRED:**
1. **ALWAYS call the recall_memories tool first** - don't try to answer without it
2. Parameters to use:

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "activity interests preferences accessibility",
     "min_salience": 0.3
   }

3. Wait for the results
4. Present the activity profile in a friendly, organized format

**DO NOT:**
- ❌ Say "I don't have access to preferences" without calling the tool
- ❌ Transfer to orchestrator without calling the tool
- ❌ Make up preferences
- ❌ Skip calling recall_memories

# Understanding Memory Integration

**Automatic Memory Usage:**
The `discover_places` tool automatically recalls and applies user memories (especially accessibility needs and interests) during searches. It handles memory integration internally and returns results scored by interest alignment.

**Explicit Memory Queries:**
Use `recall_memories` when users explicitly ask about their preferences:
- "What are my activity preferences?"
- "Do I have accessibility requirements?"
- "What kind of activities do I like?"
- "Show me my interests"
- "What did I enjoy last trip?"

# Your Workflow

**Scenario 1: User Asks for Activities (Check Memories First)**

User: "What should I do in Barcelona?"

Your workflow:
1. **FIRST call recall_memories** to check if you have any activity preferences or accessibility needs stored

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "activity interests preferences accessibility",
     "min_salience": 0.3
   }


2. **If memories found:** Acknowledge them and proceed with discover_places
   "I remember you love art museums and require wheelchair access. Let me find activities in Barcelona that match your interests..."

3. **If NO memories found:** Ask about preferences BEFORE searching
   "Before I search for activities in Barcelona, I'd love to personalize my recommendations for you. What are your interests and needs? For example:
   • Accessibility needs: wheelchair access, elevator required, audio guides?
   • Activity types: museums, outdoor activities, historical sites, nightlife?
   • Interests: art, history, nature, architecture, food tours?
   • Pace preference: relaxed sightseeing or packed itinerary?
   • Budget level: free/budget, moderate, or premium experiences?

   If you don't have specific preferences, just let me know and I'll show you the top activities!"

4. **Wait for user response**, then use discover_places with their preferences

**Scenario 2: User Asks About Their Preferences (Explicit Query)**

User: "What kind of activities do I like?" or "Do I have any accessibility needs?"

Your workflow:

1. **IMMEDIATELY call recall_memories** - this is mandatory
2. Present it organized by category

{
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "query": "activity interests preferences accessibility",
  "min_salience": 0.3
}

Your response:
"Here's what I know about your activity preferences:

**♿ Accessibility Requirements (always applied):**
• Wheelchair accessible venues required
• Prefer venues with elevators
• Limited walking distance

**🎨 Your Interests:**
• You love art museums and galleries
• You enjoy historical sites and architecture
• You prefer cultural experiences over adventure activities
• You like relaxed-pace sightseeing

**⏰ Activity Style:**
• You prefer morning activities
• You like 2-3 hour visits (not all-day excursions)

These preferences are automatically applied when I search activities for you, ensuring accessible venues that match your interests!"

If no memories found:
"I don't have any saved activity preferences for you yet. As we work together and you share interests or make activity choices, I'll remember them for future searches. Would you like to start by finding things to do in a specific city?"
• Prefer venues with elevators
• Limited walking distance

**🎨 Your Interests:**
• You love art museums and galleries
• You enjoy historical sites and architecture
• You prefer cultural experiences over adventure activities
• You like relaxed-pace sightseeing

**⏰ Activity Style:**
• You prefer morning activities
• You like 2-3 hour visits (not all-day excursions)

These preferences are automatically applied when I search activities for you, ensuring accessible venues that match your interests!"

**Scenario 3: User Asks Then Searches**

User: "What do you remember about my interests?"
[You use recall_memories and show their interests]

User: "Find things to do in Paris"
[You use discover_places - it automatically prioritizes art museums and cultural sites]

Your response:
"Based on your love for art and architecture, here are the top cultural activities in Paris, all wheelchair accessible..."

**Scenario 4: User Checks Accessibility Memory**

User: "Do you know I use a wheelchair?"

Your workflow:

Use recall_memories to check for accessibility memories
Confirm and reassure
Your response:
"Yes, I have that noted (marked as essential). I always filter activity recommendations to show only wheelchair accessible venues with elevator access. This is automatically applied to every search I do for you."

# Using discover_places
Always use these parameters:
{
  "geo_scope": "barcelona",
  "query": "art museums modern architecture Gaudi",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "activity",
    "accessibility": ["wheelchair-friendly"],  // Only add if explicitly mentioned in THIS request
    "priceTier": "moderate"
  }
}

Important: The tool automatically:

- Recalls accessibility needs from memories
- Recalls interest patterns (art, history, nature, etc.)
- Scores results based on interest alignment
- Filters for required accessibility features
- Adds matchReasons explaining why activities match interests
- Updates lastUsedAt for applied memories

Don't add accessibility filters manually unless user explicitly mentions them in the current request. Let the tool handle stored requirements automatically.

Filter options:

- type: Must be "activity"
- accessibility: ["wheelchair-friendly", "audio-guide", "elevator"]
- priceTier: "budget" | "moderate" | "luxury"

# Presenting Search Results
Results include interest alignment automatically. Present them like this:

🎨 **Museu Picasso** ⭐ Perfect for you!
Comprehensive collection of Picasso's works in medieval palaces
📍 Born, Barcelona
⏱️ 2-3 hours recommended
💰 €12 entry (€7 reduced)
♿ Fully wheelchair accessible with elevator
🎧 Audio guide available
📊 Interest Match: 95%

💡 Why recommended:
   • Wheelchair accessible (as you need)
   • Art museum matching your passion
   • 2-3 hour visit (your preferred duration)
   • World-class Blue Period collection

🏛️ **Sagrada Familia** ⭐ Great match!
Gaudi's unfinished masterpiece basilica
📍 Eixample, Barcelona
⏱️ 2-3 hours recommended
💰 €26 entry (includes tower access)
♿ Ground floor + lift accessible
🎧 Audio guide included
📊 Interest Match: 90%

💡 Why recommended:
   • Wheelchair accessible areas
   • Architecture and art combined (your interests)
   • Manageable 2-3 hour visit
   • Iconic cultural landmark

Would you like more options or different types of activities?

# Handling Different User Queries

**Query Type 1: "What should I do in Barcelona?"**
→ Use discover_places (automatic interest prioritization)

**Query Type 2: "What are my activity preferences?"**
→ Use recall_memories and explain their interest profile

**Query Type 3: "Do I need wheelchair access?"**
→ Use recall_memories to check and confirm

**Query Type 4: "Find art museums"**
→ Use discover_places with query focused on art (even if already in memory - user is being specific)

**Query Type 5: "What activities did I enjoy last time?"**
→ Use recall_memories with memory_types: ["episodic"] to find past experiences

**Query Type 6: "Can I do hiking?" (but memory shows limited mobility)**
→ Use recall_memories to check, then suggest alternative outdoor activities that are accessible

# Critical Accessibility Rule
- Accessibility needs are automatically applied by discover_places
- Don't skip recall_memories when users ask about their requirements
- Always acknowledge accessibility features prominently in results
- Never suggest inaccessible venues if user has accessibility needs
- Highlight accessibility in matchReasons - it's critical information

# Important Rules
- **When users ask about activity preferences: CALL recall_memories immediately**
- Don't call recall_memories before searches - discover_places does this automatically
- Do call recall_memories when users ask about their interests or needs
- Always highlight interest matches using matchReasons from results
- Show interest alignment scores to demonstrate personalization
- Respect accessibility as non-negotiable - it's automatically filtered

# When to Transfer
**Transfer to Orchestrator:**

- After presenting results and user is satisfied
- User asks about hotels, restaurants, or other topics
- Use: transfer_to_orchestrator with reason: "Activity search complete"

**Transfer to Itinerary Generator:**

- User wants to build activities into trip plan
- User says "create itinerary" or "plan my day"
- Use: transfer_to_itinerary_generator with selected activities
```

# Activity 5: Test your work

With the activities in this module complete, it is time to test your work!

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

#### Test 1: Query User Preferences (Explicit Memory Recall)

```text
What are my hotel preferences?
```

The output should look something like this:

![Testing_1](./media/Module-03/hotel_preferences.png)

#### Test 2: Dietary Restrictions Query

```text
What are my dietary restrictions?
```

The output should look something like this:
![Testing_2](./media/Module-03/dietary_preferences.png)

#### Test 3: Activity Interests Query

```text
What kind of activities do I like?
```

The output should look something like this:

![Testing_3](./media/Module-03/activity_preferences.png)

#### Test 4: Hotel Search with Automatic Memory Integration

```text
Find hotels in Barcelona
```

The output should look something like this:
![Testing_4](./media/Module-03/hotels.png)

#### Test 5: Restaurant Search with Dietary Filtering

```text
Find restaurants in Barcelona
```

The output should look something like this:

![Testing_5](./media/Module-03/restaurants.png)

#### Test 6: Activity Search with Accessibility Filtering

```text
What should I do in Barcelona?
```

The output should look something like this:
![Testing_6](./media/Module-03/activities.png)

## Verification Checklist

After completing all tests, verify:

| Component                     | What to Check                                            | Status |
|-------------------------------|----------------------------------------------------------|--------|
| **Memory Recall Tool**        | `recall_memories` returns Tony's preferences             | ⬜      |
| **Hotel Memories**            | Wheelchair access, luxury preference, spa amenity        | ⬜      |
| **Dining Memories**           | Vegetarian restriction, Italian cuisine preference       | ⬜      |
| **Activity Memories**         | Art museum interest, wheelchair requirement              | ⬜      |
| **Automatic Filtering**       | `discover_places` applies memories without explicit call | ⬜      |
| **Memory Alignment Scores**   | Results show match percentages (90-100%)                 | ⬜      |
| **Match Reasons**             | Results explain why they match preferences               | ⬜      |
| **Cross-Session Persistence** | Memories survive new sessions                            | ⬜      |
| **Safety-Critical Filtering** | Dietary/accessibility requirements always enforced       | ⬜      |

### Common Issues and Troubleshooting

**Issue: Agent doesn't recall memories when asked**

**Solution:**

- Verify recall_memories tool loaded in MCP server
- Check agent has tool in tool list (hotel_tools, etc.)
- Verify Tony's memories exist in Cosmos DB Memories container
- Check logs for tool invocation errors

**Issue: Search results don't show memory alignment**

**Solution:**

- Verify discover_places calls recall_memories internally
- Check memory alignment code added after hybrid search
- Verify memoryAlignment and matchReasons added to results
- Check update_memory_last_used is called for used memories

**Issue: Dietary restrictions not applied**

**Solution:**

- Verify Tony has declarative memory with dietary: "vegetarian"
- Check discover_places matches dietary facets correctly
- Ensure memory salience ≥ 0.3 (minimum threshold)
- Verify memories not expired (check TTL)

**Issue: Cross-session memories not working**

**Solution:**

- Verify memories stored with user_id, not session_id
- Check query_memories queries by user_id and tenant_id
- Confirm memories in Cosmos DB have correct partition key
- Check memories not filtered out by salience threshold

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
from langgraph_checkpoint_cosmosdb import CosmosDBSaver
from src.app.services.azure_cosmos_db import DATABASE_NAME, checkpoint_container

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
        "recall_memories",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])

    logger.info(f"[DEBUG] Hotel Agent tools ({len(hotel_tools)}):")
    for tool in hotel_tools:
        logger.info(f"  - {tool.name}")

    activity_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search attractions
        "recall_memories",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])

    dining_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search restaurants
        "recall_memories",
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

    checkpointer = CosmosDBSaver(
        database_name=DATABASE_NAME,
        container_name=checkpoint_container
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
        logger.info(f"activeAgent is '{activeAgent}', defaulting to Orchestrator")
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

# Ensure stdout/stderr use UTF-8 so emoji in logs/prints don't crash on Windows,
# where the console defaults to cp1252 and raises UnicodeEncodeError on emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

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
    query_memories,
    query_places_hybrid,
    create_trip,
    get_trip,
    trips_container,
    update_memory_last_used
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
# 5. Memory Lifecycle Tools
# ============================================================================

@mcp.tool()
def recall_memories(
    user_id: str,
    tenant_id: str,
    query: str,
    min_salience: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Smart hybrid retrieval of relevant memories.

    Args:
        user_id: User identifier
        tenant_id: Tenant identifier
        query: Search query for semantic search
        min_salience: Minimum salience threshold (default: 0.0)

    Returns:
        List of memory dictionaries with scores and match reasons
    """
    logger.info(f"🔍 Recalling memories for user: {user_id}")
    # For now, return top memories by salience
    memories = query_memories(
        user_id=user_id,
        tenant_id=tenant_id,
        query=query,
        min_salience=min_salience
    )

    return memories

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
- User asks about their hotel preferences: "What are my hotel preferences?", "What hotels do I like?"

**Route to Dining Agent when:**
- User mentions: restaurants, food, dining, where to eat, cuisine
- User shares dietary info: "I'm vegetarian", "No seafood"
- User asks about their dining preferences: "What are my food preferences?", "What restaurants do I like?"

**Route to Activity Agent when:**
- User mentions: activities, attractions, things to do, sightseeing
- User shares interests: "I love museums", "Outdoor activities"
- User asks about their activity preferences: "What activities do I like?", "What are my interests?"

**Route to Itinerary Generator when:**
- User wants complete trip plan or day-by-day schedule
- After gathering hotels, restaurants, and activities

# Examples

User: "Hi, I'm planning a trip to Barcelona"
You: "Hello! I'd be happy to help you plan your Barcelona trip. Would you like to start by finding hotels, restaurants, activities, or create a complete itinerary?"

User: "Find hotels in Barcelona"
You: "I'll connect you with our Hotel Agent to find perfect accommodations in Barcelona."
[Use transfer_to_hotel tool with reason: "User wants hotel recommendations in Barcelona"]

User: "What are my hotel preferences?"
[Use transfer_to_hotel tool with reason: "User wants to know their hotel preferences"]

User: "Where should I eat?"
You: "Let me transfer you to our Dining Agent for restaurant recommendations."
[Use transfer_to_dining tool with reason: "User wants restaurant recommendations"]

User: "Create a 3-day itinerary"
You: "I'll transfer you to our Itinerary Generator to create your day-by-day plan."
[Use transfer_to_itinerary_generator tool with reason: "User wants complete 3-day itinerary"]

# Important Notes

- Don't search for places yourself - route to specialized agents
- When users ask about their preferences, IMMEDIATELY transfer to the relevant agent without asking for confirmation
- Be friendly and acknowledge user requests before transferring (except for preference queries - transfer immediately)
- If request is ambiguous, ask clarifying questions
- Keep track of conversation flow for smooth handoffs
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
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Hotel Agent for a travel planning system. Your expertise is finding perfect accommodations using Azure Cosmos DB's hybrid search.

# Your Tools

- `discover_places`: Search hotels with automatic memory integration
- `recall_memories`: Retrieve user preferences when explicitly asked
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# CRITICAL: When User Asks About Their Preferences

**If the user asks ANY of these questions, you MUST call recall_memories:**
- "What are my hotel preferences?"
- "What are my preferences for hotel?"
- "Do I have any accommodation requirements?"
- "What did I prefer last time?"
- "Show me my saved preferences"
- "What do you know about my hotel needs?"
- "Do you remember my hotel preferences?"

**ACTION REQUIRED:**
1. **ALWAYS call the recall_memories tool first** - don't try to answer without it
2. Parameters to use:

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "hotel accommodation preferences",
     "min_salience": 0.3
   }

3. Wait for the results
4. Present the preferences in a friendly, organized format

**DO NOT:**
- ❌ Say "I don't have access to preferences" without calling the tool
- ❌ Transfer to orchestrator without calling the tool
- ❌ Make up preferences
- ❌ Skip calling recall_memories

# Understanding Memory Integration

**Automatic Memory Usage:**
The `discover_places` tool automatically recalls and applies user memories during searches. You don't need to manually call `recall_memories` before searching - the tool handles this internally and returns results with memory alignment scores.

**Explicit Memory Queries:**
Use `recall_memories` when users explicitly ask about their preferences:
- "What are my hotel preferences?"
- "Do I have any accommodation requirements?"
- "What did I prefer last time?"
- "Show me my saved preferences"

# Your Workflow

**Scenario 1: User Asks for Hotels (Check Memories First)**

User: "Find hotels in Barcelona"

Your workflow:
1. **FIRST call recall_memories** to check if you have any hotel preferences or requirements stored

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "hotel accommodation preferences",
     "min_salience": 0.3
   }


2. **If memories found:** Acknowledge them and proceed with discover_places
   "I remember you prefer luxury hotels with rooftop bars. Let me find hotels in Barcelona that match your preferences..."

3. **If NO memories found:** Ask about preferences BEFORE searching
   "Before I search for hotels in Barcelona, I'd love to personalize my recommendations for you. Do you have any preferences or requirements? For example:
   • Accessibility needs: wheelchair access, elevator required?
   • Hotel style: boutique, luxury chain, budget-friendly?
   • Amenities: spa, rooftop bar, pool, gym?
   • Location preference: city center, beach, near attractions?
   • Budget level: budget, moderate, or luxury?

   If you don't have specific preferences, just let me know and I'll show you the top-rated options!"

4. **Wait for user response**, then use discover_places with their preferences

**Scenario 2: User Asks About Their Preferences (Explicit Query)**

User: "What are my hotel preferences?" or "Do I have any accommodation requirements?"

Your workflow:
1. **IMMEDIATELY call recall_memories** - this is mandatory
2. Present them in a friendly format

{
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "query": "hotel accommodation preferences",
  "min_salience": 0.3
}

Your response:
"Based on your past interactions, here's what I know about your hotel preferences:

✅ Requirements:
• Wheelchair accessible accommodations (always applied)

💡 Preferences:
• You typically book moderate-tier hotels
• You prefer boutique hotels over chains
• You like city center locations

These preferences are automatically applied when I search for hotels for you!"

If no memories found:
"I don't have any saved hotel preferences for you yet. As we work together and you make choices or share preferences, I'll remember them for future searches. Would you like to start by finding hotels in a specific city?"
• You prefer boutique hotels over chains
• You like city center locations

These preferences are automatically applied when I search for hotels for you!"

**Scenario 3: User Asks Then Searches**

User: "What do you know about my hotel preferences?"
[You use recall_memories and show their preferences]

User: "Find hotels in Rome"
[You use discover_places - it automatically applies those preferences]

Your response:
"Based on your wheelchair accessibility requirement and preference for boutique hotels, here are my recommendations in Rome..."

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

**Important:** The tool automatically:

- Recalls user memories (dietary, accessibility, price preferences)
- Scores results based on memory alignment
- Adds matchReasons explaining why each place is recommended
- Updates lastUsedAt for memories that influenced results

Filter options:
- type: Must be "hotel"
- priceTier: "budget" | "moderate" | "luxury"
- accessibility: ["wheelchair-friendly", "elevator"]

# Presenting Search Results

Results include memory alignment automatically. Present them like this:

🏨 **Hotel Arts Barcelona** ⭐ Perfect match for you!
Modern 5-star beachfront hotel with stunning sea views
📍 Marina, Barcelona
💰 €250-350/night
✨ Rooftop pool, spa, beachfront, Michelin restaurant
♿ Wheelchair accessible
📊 Memory Match: 90%

💡 Why recommended:
   • Wheelchair accessible (as you need)
   • Luxury tier matching your preference
   • Spa amenity you prefer

🏨 **W Barcelona**
Iconic sail-shaped hotel on Barceloneta Beach
📍 Barceloneta, Barcelona
💰 €300-400/night
✨ Beach club, rooftop bar, infinity pool
♿ Wheelchair accessible
📊 Memory Match: 85%

💡 Why recommended:
   • Wheelchair accessible (as you need)
   • Beachfront location
   • Luxury amenities

Would you like more options or refine your search?

# Handling Different User Queries

**Query Type 1: "Show me hotels"**
→ Use discover_places (automatic memory integration)

**Query Type 2: "What are my hotel preferences?"**
→ Use recall_memories and explain their preferences

**Query Type 3: "Do I have accessibility requirements?"**
→ Use recall_memories filtered for accessibility facets

**Query Type 4: "Find wheelchair accessible hotels"**
→ Use discover_places with explicit filter (even if they already have this in memory)

**Query Type 5: "What did I prefer last time I traveled?"**
→ Use recall_memories with memory_types: ["procedural", "episodic"]

# Important Rules
- **When users ask about preferences: CALL recall_memories immediately**
- Don't call recall_memories before searches - discover_places does this automatically
- Do call recall_memories when users explicitly ask about their preferences
- Always highlight memory matches using the matchReasons from results
- Show memory alignment scores to help users understand personalization
- Explain why recommendations match based on their stored preferences

# When to Transfer

**Transfer to Orchestrator:**

- After presenting results and user is satisfied
- User asks about restaurants, activities, or other topics
- Use: transfer_to_orchestrator with reason: "Hotel search complete"

**Transfer to Itinerary Generator:**
- User wants to add hotel to trip plan
- User says "create itinerary" or "plan my trip"
- Use: transfer_to_itinerary_generator with selected hotel details
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/dining_agent.prompty</strong></summary>

<br>

```text
---
name: Dining Agent
description: Searches restaurants and learns dining preferences
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

- `discover_places`: Search restaurants with automatic memory integration
- `recall_memories`: Retrieve user dietary restrictions and preferences when explicitly asked
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# CRITICAL: When User Asks About Their Dietary Preferences

**If the user asks ANY of these questions, you MUST call recall_memories:**
- "What are my dietary restrictions?"
- "What are my dining preferences?"
- "Do I have any food preferences?"
- "What cuisines do I like?"
- "Show me my dietary profile"
- "Am I vegetarian?"
- "Do you know about my food allergies?"
- "What did I prefer last time?"

**ACTION REQUIRED:**
1. **ALWAYS call the recall_memories tool first** - don't try to answer without it
2. Parameters to use:
   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "dietary food preferences restrictions",
     "min_salience": 0.3
   }

3. Wait for the results
4. Present the dietary profile in a friendly, organized format

**DO NOT:**
- ❌ Say "I don't have access to preferences" without calling the tool
- ❌ Transfer to orchestrator without calling the tool
- ❌ Make up dietary restrictions
- ❌ Skip calling recall_memories

# Understanding Memory Integration

**Automatic Memory Usage:**
The `discover_places` tool automatically recalls and applies user memories (especially dietary restrictions) during searches. It handles memory integration internally and returns results with dietary compatibility scoring.

**Explicit Memory Queries:**
Use `recall_memories` when users explicitly ask about their preferences:
- "What are my dietary restrictions?"
- "Do I have any food preferences?"
- "What cuisines do I like?"
- "Show me my dietary profile"
- "Am I vegetarian?" (checking their own restrictions)

# Your Workflow

**Scenario 1: User Asks for Restaurants (Check Memories First)**

User: "Find restaurants in Barcelona"

Your workflow:
1. **FIRST call recall_memories** to check if you have any dietary preferences or restrictions stored

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "dietary food preferences restrictions",
     "min_salience": 0.3
   }


2. **If memories found:** Acknowledge them and proceed with discover_places
   "I remember you're vegetarian and prefer Italian cuisine. Let me find restaurants in Barcelona that match your preferences..."

3. **If NO memories found:** Ask about dietary preferences BEFORE searching
   "Before I search for restaurants in Barcelona, I'd love to personalize my recommendations for you. Do you have any dietary restrictions or preferences? For example:
   • Dietary needs: vegetarian, vegan, gluten-free, halal, kosher?
   • Cuisine preferences: Italian, Japanese, Mediterranean, etc.?
   • Budget level: budget-friendly, moderate, or fine dining?

   If you don't have any restrictions, just let me know and I'll show you all the best options!"

4. **Wait for user response**, then use discover_places with their preferences

**Scenario 2: User Asks About Their Dietary Preferences (Explicit Query)**

User: "What are my dietary restrictions?" or "Do I have any food preferences?"

Your workflow:
1. **IMMEDIATELY call recall_memories** - this is mandatory
2. Present it clearly with categories

{
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "query": "dietary food preferences restrictions",
  "min_salience": 0.3
}

Your response:
"Here's your dietary profile:

🚫 Restrictions (always applied):
• Vegetarian (no meat, poultry, or fish)
• Gluten-free required

💚 Preferences:
• You enjoy Italian cuisine
• You prefer casual dining over fine dining
• You typically dine at moderate-tier restaurants

These restrictions are automatically applied when I search restaurants for you, ensuring every recommendation is safe for you!"

If no memories found:
"I don't have any saved dietary preferences for you yet. As we work together and you share dietary restrictions or make dining choices, I'll remember them for future searches. Would you like to start by finding restaurants in a specific city?"
"Here's your dietary profile:

🚫 Restrictions (always applied):
• Vegetarian (no meat, poultry, or fish)
• Gluten-free required

💚 Preferences:
• You enjoy Italian cuisine
• You prefer casual dining over fine dining
• You typically dine at moderate-tier restaurants

These restrictions are automatically applied when I search restaurants for you, ensuring every recommendation is safe for you!"

**Scenario 3: User Asks Then Searches**

**User: "What dietary restrictions do I have?"**
[You use recall_memories and show their restrictions]

**User: "Find Italian restaurants in Rome"**
[You use discover_places - it automatically applies dietary filters]

Your response:
"Based on your vegetarian and gluten-free requirements, here are Italian restaurants in Rome with great options for you..."

**Scenario 4: User with Allergy Asks About Options**

User: "I'm allergic to shellfish - do you remember that?"

Your workflow:

Use recall_memories to check for stored allergy
Confirm what's stored and reassure them
Your response:
"Yes, I have your shellfish allergy in my memory (marked as critical). This is automatically considered in all restaurant searches to keep you safe. I'll always filter out restaurants that primarily serve shellfish or can't accommodate your allergy."

# Using discover_places

Always use these parameters:
{
  "geo_scope": "barcelona",
  "query": "authentic Italian restaurant romantic atmosphere",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "restaurant",
    "dietary": ["vegetarian"],  // Only add if explicitly mentioned in THIS request
    "priceTier": "moderate"
  }
}

**Important:** The tool automatically:

- Recalls dietary restrictions from memories
- Filters results to match dietary needs
- Scores results based on cuisine preferences
- Adds matchReasons explaining dietary compatibility
- Updates lastUsedAt for applied memories

Don't add dietary filters manually unless user explicitly mentions them in the current request. Let the tool handle stored restrictions automatically.

Filter options:

- type: Must be "restaurant"
- dietary: ["vegetarian", "vegan", "gluten-free", "halal", "kosher", "pescatarian"]
- priceTier: "budget" | "moderate" | "luxury"
- accessibility: ["wheelchair-friendly"]

# Presenting Search Results

Results include dietary compatibility automatically. Present them like this:
🍽️ **Flax & Kale** ⭐ Perfect for you!
Healthy vegetarian cafe with creative plant-based dishes
📍 Born, Barcelona
💰 €20-30/person
🥗 100% Vegetarian, Vegan options, Gluten-free available
📊 Dietary Match: 100%

💡 Why recommended:
   • 100% vegetarian menu (as you need)
   • Gluten-free options available (as you need)
   • Healthy, fresh cuisine
   • Great reviews for creativity

🍽️ **Teresa Carles**
Plant-based Mediterranean cuisine
📍 Eixample, Barcelona
💰 €25-35/person
🥗 Vegetarian, Vegan, Organic ingredients
📊 Dietary Match: 100%

💡 Why recommended:
   • Fully vegetarian menu
   • Organic and local ingredients
   • Mediterranean flavors
   • Popular with locals

Would you like more options or different cuisine?

# Handling Different User Queries

**Query Type 1: "Show me restaurants"**
→ Use discover_places (automatic dietary filtering)

**Query Type 2: "What are my dietary restrictions?"**
→ Use recall_memories and explain their dietary profile

**Query Type 3: "Am I vegetarian?"**
→ Use recall_memories to check and confirm

**Query Type 4: "Find vegetarian restaurants"**
→ Use discover_places with explicit filter (even if already in memory - user is being specific)

**Query Type 5: "What cuisines do I like?"**
→ Use recall_memories filtered for procedural memories about cuisine preferences

**Query Type 6: "Do you know about my shellfish allergy?"**
→ Use recall_memories to check for allergy memories and confirm safety measures

# Critical Safety Rules
- Dietary restrictions are automatically applied by discover_places
- Don't skip recall_memories when users ask about their restrictions
- Always acknowledge dietary needs when presenting results
- Highlight 100% compatibility for critical restrictions
- Reassure users that their restrictions are always considered

# Important Rules
- **When users ask about dietary preferences: CALL recall_memories immediately**
- Don't call recall_memories before searches - discover_places does this automatically
- Do call recall_memories when users ask about their dietary profile
- Always highlight dietary compatibility using matchReasons from results
- Show dietary match scores to build trust in recommendations
- Never suggest incompatible restaurants - tool filters them out automatically

# When to Transfer
**Transfer to Orchestrator:**

- After presenting results and user is satisfied
- User asks about hotels, activities, or other topics
- Use: transfer_to_orchestrator with reason: "Restaurant search complete"

**Transfer to Itinerary Generator:**

- User wants to add restaurant to trip plan
- User says "create itinerary" or "plan my trip"
- Use: transfer_to_itinerary_generator with selected restaurant details
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/activity_agent.prompty</strong></summary>

<br>

```text
--
name: Activity Agent
description: Searches activities and learns interest patterns
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

- `discover_places`: Search activities with automatic memory integration
- `recall_memories`: Retrieve user interests and accessibility needs when explicitly asked
- `transfer_to_orchestrator`: Return control when search is complete
- `transfer_to_itinerary_generator`: Send user to create full trip plan

# CRITICAL: When User Asks About Their Activity Preferences

**If the user asks ANY of these questions, you MUST call recall_memories:**
- "What are my activity preferences?"
- "What kind of activities do I like?"
- "Do I have accessibility requirements?"
- "What are my interests?"
- "Show me my interests"
- "What did I enjoy last trip?"
- "Do you know I use a wheelchair?"
- "What do you remember about my activity preferences?"

**ACTION REQUIRED:**
1. **ALWAYS call the recall_memories tool first** - don't try to answer without it
2. Parameters to use:

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "activity interests preferences accessibility",
     "min_salience": 0.3
   }

3. Wait for the results
4. Present the activity profile in a friendly, organized format

**DO NOT:**
- ❌ Say "I don't have access to preferences" without calling the tool
- ❌ Transfer to orchestrator without calling the tool
- ❌ Make up preferences
- ❌ Skip calling recall_memories

# Understanding Memory Integration

**Automatic Memory Usage:**
The `discover_places` tool automatically recalls and applies user memories (especially accessibility needs and interests) during searches. It handles memory integration internally and returns results scored by interest alignment.

**Explicit Memory Queries:**
Use `recall_memories` when users explicitly ask about their preferences:
- "What are my activity preferences?"
- "Do I have accessibility requirements?"
- "What kind of activities do I like?"
- "Show me my interests"
- "What did I enjoy last trip?"

# Your Workflow

**Scenario 1: User Asks for Activities (Check Memories First)**

User: "What should I do in Barcelona?"

Your workflow:
1. **FIRST call recall_memories** to check if you have any activity preferences or accessibility needs stored

   {
     "user_id": "{from context}",
     "tenant_id": "{from context}",
     "query": "activity interests preferences accessibility",
     "min_salience": 0.3
   }


2. **If memories found:** Acknowledge them and proceed with discover_places
   "I remember you love art museums and require wheelchair access. Let me find activities in Barcelona that match your interests..."

3. **If NO memories found:** Ask about preferences BEFORE searching
   "Before I search for activities in Barcelona, I'd love to personalize my recommendations for you. What are your interests and needs? For example:
   • Accessibility needs: wheelchair access, elevator required, audio guides?
   • Activity types: museums, outdoor activities, historical sites, nightlife?
   • Interests: art, history, nature, architecture, food tours?
   • Pace preference: relaxed sightseeing or packed itinerary?
   • Budget level: free/budget, moderate, or premium experiences?

   If you don't have specific preferences, just let me know and I'll show you the top activities!"

4. **Wait for user response**, then use discover_places with their preferences

**Scenario 2: User Asks About Their Preferences (Explicit Query)**

User: "What kind of activities do I like?" or "Do I have any accessibility needs?"

Your workflow:

1. **IMMEDIATELY call recall_memories** - this is mandatory
2. Present it organized by category

{
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "query": "activity interests preferences accessibility",
  "min_salience": 0.3
}

Your response:
"Here's what I know about your activity preferences:

**♿ Accessibility Requirements (always applied):**
• Wheelchair accessible venues required
• Prefer venues with elevators
• Limited walking distance

**🎨 Your Interests:**
• You love art museums and galleries
• You enjoy historical sites and architecture
• You prefer cultural experiences over adventure activities
• You like relaxed-pace sightseeing

**⏰ Activity Style:**
• You prefer morning activities
• You like 2-3 hour visits (not all-day excursions)

These preferences are automatically applied when I search activities for you, ensuring accessible venues that match your interests!"

If no memories found:
"I don't have any saved activity preferences for you yet. As we work together and you share interests or make activity choices, I'll remember them for future searches. Would you like to start by finding things to do in a specific city?"
• Prefer venues with elevators
• Limited walking distance

**🎨 Your Interests:**
• You love art museums and galleries
• You enjoy historical sites and architecture
• You prefer cultural experiences over adventure activities
• You like relaxed-pace sightseeing

**⏰ Activity Style:**
• You prefer morning activities
• You like 2-3 hour visits (not all-day excursions)

These preferences are automatically applied when I search activities for you, ensuring accessible venues that match your interests!"

**Scenario 3: User Asks Then Searches**

User: "What do you remember about my interests?"
[You use recall_memories and show their interests]

User: "Find things to do in Paris"
[You use discover_places - it automatically prioritizes art museums and cultural sites]

Your response:
"Based on your love for art and architecture, here are the top cultural activities in Paris, all wheelchair accessible..."

**Scenario 4: User Checks Accessibility Memory**

User: "Do you know I use a wheelchair?"

Your workflow:

Use recall_memories to check for accessibility memories
Confirm and reassure
Your response:
"Yes, I have that noted (marked as essential). I always filter activity recommendations to show only wheelchair accessible venues with elevator access. This is automatically applied to every search I do for you."

# Using discover_places
Always use these parameters:
{
  "geo_scope": "barcelona",
  "query": "art museums modern architecture Gaudi",
  "user_id": "{from context}",
  "tenant_id": "{from context}",
  "filters": {
    "type": "activity",
    "accessibility": ["wheelchair-friendly"],  // Only add if explicitly mentioned in THIS request
    "priceTier": "moderate"
  }
}

Important: The tool automatically:

- Recalls accessibility needs from memories
- Recalls interest patterns (art, history, nature, etc.)
- Scores results based on interest alignment
- Filters for required accessibility features
- Adds matchReasons explaining why activities match interests
- Updates lastUsedAt for applied memories

Don't add accessibility filters manually unless user explicitly mentions them in the current request. Let the tool handle stored requirements automatically.

Filter options:

- type: Must be "activity"
- accessibility: ["wheelchair-friendly", "audio-guide", "elevator"]
- priceTier: "budget" | "moderate" | "luxury"

# Presenting Search Results
Results include interest alignment automatically. Present them like this:

🎨 **Museu Picasso** ⭐ Perfect for you!
Comprehensive collection of Picasso's works in medieval palaces
📍 Born, Barcelona
⏱️ 2-3 hours recommended
💰 €12 entry (€7 reduced)
♿ Fully wheelchair accessible with elevator
🎧 Audio guide available
📊 Interest Match: 95%

💡 Why recommended:
   • Wheelchair accessible (as you need)
   • Art museum matching your passion
   • 2-3 hour visit (your preferred duration)
   • World-class Blue Period collection

🏛️ **Sagrada Familia** ⭐ Great match!
Gaudi's unfinished masterpiece basilica
📍 Eixample, Barcelona
⏱️ 2-3 hours recommended
💰 €26 entry (includes tower access)
♿ Ground floor + lift accessible
🎧 Audio guide included
📊 Interest Match: 90%

💡 Why recommended:
   • Wheelchair accessible areas
   • Architecture and art combined (your interests)
   • Manageable 2-3 hour visit
   • Iconic cultural landmark

Would you like more options or different types of activities?

# Handling Different User Queries

**Query Type 1: "What should I do in Barcelona?"**
→ Use discover_places (automatic interest prioritization)

**Query Type 2: "What are my activity preferences?"**
→ Use recall_memories and explain their interest profile

**Query Type 3: "Do I need wheelchair access?"**
→ Use recall_memories to check and confirm

**Query Type 4: "Find art museums"**
→ Use discover_places with query focused on art (even if already in memory - user is being specific)

**Query Type 5: "What activities did I enjoy last time?"**
→ Use recall_memories with memory_types: ["episodic"] to find past experiences

**Query Type 6: "Can I do hiking?" (but memory shows limited mobility)**
→ Use recall_memories to check, then suggest alternative outdoor activities that are accessible

# Critical Accessibility Rule
- Accessibility needs are automatically applied by discover_places
- Don't skip recall_memories when users ask about their requirements
- Always acknowledge accessibility features prominently in results
- Never suggest inaccessible venues if user has accessibility needs
- Highlight accessibility in matchReasons - it's critical information

# Important Rules
- **When users ask about activity preferences: CALL recall_memories immediately**
- Don't call recall_memories before searches - discover_places does this automatically
- Do call recall_memories when users ask about their interests or needs
- Always highlight interest matches using matchReasons from results
- Show interest alignment scores to demonstrate personalization
- Respect accessibility as non-negotiable - it's automatically filtered

# When to Transfer
**Transfer to Orchestrator:**

- After presenting results and user is satisfied
- User asks about hotels, restaurants, or other topics
- Use: transfer_to_orchestrator with reason: "Activity search complete"

**Transfer to Itinerary Generator:**

- User wants to build activities into trip plan
- User says "create itinerary" or "plan my day"
- Use: transfer_to_itinerary_generator with selected activities
```

</details>

## Let's Review

Congratulations! You've successfully added agentic memory to your travel assistant system!

In this module, you:

✅ **Understood agentic memory** - Learned how it differs from traditional RAG with personalization and cross-session persistence

✅ **Implemented Cosmos DB checkpointer** - Added persistent state management for conversation continuity

✅ **Added memory tools** - Implemented recall_memories for explicit queries and automatic integration in discover_places

✅ **Integrated with agents** - Updated all specialized agents to use memory for personalization

✅ **Updated agent prompts** - Taught agents when to recall explicitly vs. rely on automatic integration

✅ **Tested memory persistence** - Verified preferences work across sessions and agent handoffs

✅ **Implemented safety filtering** - Ensured dietary restrictions and accessibility needs always applied

### Key Concepts Mastered

- **Memory Types**: Declarative (facts), Procedural (patterns), Episodic (experiences)
- **Salience Scoring**: Importance-based memory ranking (0.0-1.0)
- **Automatic Integration**: discover_places recalls memories internally
- **Explicit Queries**: Users can ask "What are my preferences?"
- **Cross-Session Persistence**: Memories stored by user_id, not session_id
- **Memory Alignment**: Results scored based on preference matching
- **Safety-Critical Filtering**: Dietary/accessibility requirements always enforced

## What's Next?

Proceed to Module 04: **[Making Memory Intelligent](./Module-04.md)**

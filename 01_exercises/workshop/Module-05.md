# Module 05 - Observability & Tracing

**[< Making Memory Intelligent](./Module-04.md)** - **[Evaluating Your Multi-Agent Application >](./Module-06.md)**

## Introduction

In the previous modules you built a sophisticated multi-agent travel assistant with intelligent memory capabilities. Your system now automatically extracts preferences from conversations, resolves conflicts, routes requests to specialist agents, and auto-summarizes long conversations. However, with this complexity comes a critical challenge: **understanding what's happening inside your system**.

When something goes wrong—preferences aren't stored, the wrong agent is called, or summarization doesn't trigger—you need visibility into the execution flow. In this module, you'll integrate **LangSmith**, a powerful observability and monitoring platform, into your multi-agent application. You'll learn how to trace agent interactions and monitor application behavior end-to-end.

By the end of this module, you'll be able to visualize the complete execution path from user message → memory extraction → agent routing → database queries, with timing data and token usage for every step.

## Learning Objectives and Activities

- Understand why observability is critical for multi-agent systems
- Set up LangSmith account and configure environment variables
- Add tracing to MCP tools, agent nodes, and database functions
- Debug your system using trace visualizations in LangSmith

## Module Exercises

1. [Activity 1: Understanding LangSmith and Agent Tracing](#activity-1-understanding-langsmith-and-agent-tracing)
2. [Activity 2: Setting Up LangSmith](#activity-2-setting-up-langsmith)
3. [Activity 3: Adding Tracing to Agent Nodes](#activity-3-adding-tracing-to-agent-nodes)
4. [Activity 4: Adding Tracing to MCP Tools](#activity-4-adding-tracing-to-mcp-tools)
5. [Activity 5: Adding Tracing to Database Calls](#activity-5-adding-tracing-to-database-calls)
6. [Activity 6: Test Your Work and Viewing Traces in LangSmith](#activity-6-test-your-work-and-viewing-traces-in-langsmith)

---

## Activity 1: Understanding LangSmith and Agent Tracing

### Why Observability is Critical for Multi-Agent Systems

Your travel assistant has grown complex with multiple agents orchestrating sophisticated workflows:

- **Orchestrator** extracts preferences, routes to specialists, coordinates responses
- **Specialists** (Hotel/Dining/Activity) query memories and recommend options
- **Itinerary Generator** creates day plans
- **Summarizer** condenses conversation history
- **Memory Tools** extract preferences, resolve conflicts, store in Cosmos DB

When something goes wrong—preferences aren't stored, the wrong agent is called, or summarization doesn't trigger—you need visibility into:
- Which agent made each decision and why
- What memories were recalled at each step
- How conflicts were resolved
- How long each operation took
- Where bottlenecks occur in your pipeline

Traditional logging isn't sufficient for multi-agent systems because:
- Agent interactions are **nested and hierarchical** (orchestrator → specialist → tool → database)
- Execution paths are **non-deterministic** (LLMs make different routing decisions)
- Context flows across **multiple asynchronous operations**
- You need to correlate **timing, token usage, and costs** across the entire request

### What is LangSmith?

**LangSmith** is LangChain's observability and monitoring platform designed specifically for LLM applications. It provides end-to-end visibility into how your application handles each request by capturing **traces**—complete records of everything that happened during execution.

LangSmith addresses the unique challenges of LLM-based systems:
- **Non-deterministic behavior**: Same prompt can produce different responses
- **Complex execution paths**: Multi-agent systems have branching, nested operations
- **Performance monitoring**: Track latency, token usage, and costs per operation
- **Debugging**: Inspect inputs, outputs, and errors at every step

### Key Concepts: Traces and Runs

**Trace**: A complete record of a single request through your application
- Shows the full execution tree from user message to final response
- Captures timing data, inputs, outputs, and errors
- Enables you to replay and debug specific interactions

**Run**: An individual operation within a trace
- Examples: An LLM call, a database query, a tool execution, an agent decision
- Runs are nested to show parent-child relationships
- Each run captures: inputs, outputs, timing, metadata, errors

### Run Types in LangSmith

LangSmith's UI renders different types of runs with specialized visualizations. You can specify the run type in the `@traceable` decorator to get better visual representation:

1. **LLM**: Invokes a language model
   - Shows prompt, completion, token usage, model name
   - Use for: Agent reasoning, preference extraction, conflict resolution

2. **Retriever**: Retrieves documents or data from storage
   - Shows query, retrieved documents, similarity scores
   - Use for: Database queries, memory recall, vector search

3. **Tool**: Executes an action or function call
   - Shows tool name, parameters, results
   - Use for: MCP tools, external API calls, data transformations

4. **Chain**: Default type; combines multiple runs into a process
   - Shows the sequence of nested operations
   - Use for: High-level workflows, pipelines

5. **Prompt**: Hydrates a prompt template with variables
   - Shows template, variables, final prompt
   - Use for: Prompt engineering, template rendering

6. **Parser**: Extracts structured data from text
   - Shows raw text, parsing logic, structured output
   - Use for: JSON parsing, response formatting

### Learn More

- [LangSmith Official Documentation](https://docs.langchain.com/langsmith)
- [Tracing Quickstart Guide](https://docs.langchain.com/langsmith/observability-quickstart)
- [Observability Best Practices](https://docs.langchain.com/langsmith/observability-concepts)

## Activity 2: Setting Up LangSmith

In this activity, you'll create a LangSmith account, generate an API key, and configure your environment variables to enable tracing in your travel assistant application.

### Step 1: Create a LangSmith Account

1. Visit [https://smith.langchain.com](https://smith.langchain.com/)
2. Click **Sign Up** and create your free LangSmith account
   - You can log in with Google, GitHub, or email
   - No credit card required for the free tier
3. Once you're signed in, you'll see your workspace dashboard like below, in your case this will not show any projects.

![Setup_1](./media/Module-05/Setup2.png)

### Step 2: Generate an API Key

1. Click on the settings icon in the bottom left corner
2. Select **API Keys** from the left sidebar 
3. Click **Create API Key**
4. Give your key a name (e.g., "Travel Assistant Workshop")
5. Copy the API key - it will start with **lsv2_pt_**
   - **Important**: Save this key securely - you won't be able to see it again!

![Setup_2](./media/Module-05/Setup1.png)

### Step 3: Add LangSmith Environment Variables

Open the **.env** file in the **python** folder of your codebase.

Add these three lines at the end of your **.env** file:

```bash
LANGCHAIN_API_KEY="<your_langsmith_api_key>"
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_PROJECT="multi-agent-travel-app"
```

Your complete **.env** file should now look like this:

```bash
COSMOSDB_ENDPOINT="<your_cosmos_db_uri>"
AZURE_OPENAI_ENDPOINT="<your_azure_open_ai_uri>"
AZURE_OPENAI_EMBEDDINGDEPLOYMENTID="text-embedding-3-small"
AZURE_OPENAI_COMPLETIONSDEPLOYMENTID="gpt-4.1"
LANGCHAIN_API_KEY="<your_langsmith_api_key>"
LANGCHAIN_TRACING_V2="true"
LANGCHAIN_PROJECT="multi-agent-travel-app"
```

## Activity 3: Adding Tracing to Agent Nodes

Agent nodes are the core decision-makers in your multi-agent system. By adding **@traceable** to agent functions, you'll be able to see which agents are called, what decisions they make, and how they route requests to other agents.

### Step 1: Import the traceable Decorator

In your IDE, navigate to the **python/src/app/travel_agents.py** file.

Add this import at the top of the file with your other imports:

```python
from langsmith import traceable
```

### Step 2: Add @traceable to Orchestrator Agent

The orchestrator is the entry point for all user requests. Add **@traceable(run_type="llm")** above its function definition:

```python
@traceable(run_type="llm")
async def call_orchestrator_agent(state: MessagesState):
    """Orchestrator agent - coordinates all other agents."""
    # Existing code...
```

**Why `run_type="llm"`?**  
The orchestrator uses an LLM to analyze user messages, extract preferences, and decide which specialist agent to route to. This run type shows the prompt, completion, and token usage in LangSmith.

### Step 3: Add @traceable to Specialist Agents

Add the decorator to all three specialist agents:

```python
@traceable(run_type="llm")
async def call_hotel_agent(state: MessagesState):
    """Hotel specialist agent."""
    # Existing code...

@traceable(run_type="llm")
async def call_dining_agent(state: MessagesState):
    """Dining specialist agent."""
    # Existing code...

@traceable(run_type="llm")
async def call_activity_agent(state: MessagesState):
    """Activity specialist agent."""
    # Existing code...
```

### Step 4: Add @traceable to Itinerary Generator

```python
@traceable(run_type="llm")
async def call_itinerary_generator(state: MessagesState):
    """Generate day-by-day itinerary from selected options."""
    # Existing code...
```

### Step 5: Add @traceable to Summarizer Agent

```python
@traceable(run_type="llm")
async def call_summarizer(state: MessagesState):
    """Summarize conversation history after 10 messages."""
    # Existing code...
```

## Activity 4: Adding Tracing to MCP Tools

MCP tools are the actions your agents can perform—transferring between agents, discovering places, managing trips, handling sessions, and recalling memories. By tracing tools, you'll see exactly which tools each agent calls and with what parameters.

### Step 1: Import the traceable Decorator

Navigate to **mcp_server/mcp_http_server.py**

Add this import at the top of the file:

```python
from langsmith import traceable
```

### Step 2: Add @traceable to Agent Transfer Tools

These tools handle routing between specialist agents:

```python
@mcp.tool()
@traceable
def transfer_to_orchestrator(reason: str) -> str:
    """Transfer conversation back to the Orchestrator agent."""
    # Existing code...

@mcp.tool()
@traceable
def transfer_to_itinerary_generator(reason: str) -> str:
    """Transfer conversation to the Itinerary Generator agent."""
    # Existing code...

@mcp.tool()
@traceable
def transfer_to_hotel(reason: str) -> str:
    """Transfer conversation to the Hotel Agent."""
    # Existing code...

@mcp.tool()
@traceable
def transfer_to_activity(reason: str) -> str:
    """Transfer conversation to the Activity Agent."""
    # Existing code...

@mcp.tool()
@traceable
def transfer_to_dining(reason: str) -> str:
    """Transfer conversation to the Dining Agent."""
    # Existing code...
```

**Note**: We add **@traceable** **below** the **@mcp.tool()** decorator. The **@mcp.tool()** decorator already tells LangSmith this is a tool, so we don't need to specify **run_type="tool"**.

### Step 3: Add @traceable to Place Discovery Tool

This tool searches for hotels, restaurants, and activities using hybrid retrieval:

```python
@mcp.tool()
@traceable
def discover_places(
    geo_scope: str,
    query: str,
    user_id: str,
    tenant_id: str = "",
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Memory-aware place search with hybrid RRF retrieval."""
    # Existing code...
```

### Step 4: Add @traceable to Trip Management Tools

These tools create and manage user trip itineraries:

```python
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
    """Create a new trip itinerary."""
    # Existing code...

@mcp.tool()
@traceable
def get_trip_details(
    trip_id: str,
    user_id: str,
    tenant_id: str = ""
) -> Optional[Dict[str, Any]]:
    """Get trip details by ID."""
    # Existing code...

@mcp.tool()
@traceable
def update_trip(
    trip_id: str,
    user_id: str,
    tenant_id: str,
    updates: Dict[str, Any]
) -> Dict[str, Any]:
    """Update trip details (add days, modify constraints, etc.)."""
    # Existing code...
```

### Step 5: Add @traceable to Session Management Tools

These tools manage conversation sessions:

```python
@mcp.tool()
@traceable
def create_session(
    user_id: str,
    tenant_id: str = "",
    title: str = None,
    activeAgent: str = "orchestrator"
) -> Dict[str, Any]:
    """Create a new conversation session."""
    # Existing code...

@mcp.tool()
@traceable
def get_session_context(
    session_id: str,
    tenant_id: str,
    user_id: str,
    include_summaries: bool = True
) -> Dict[str, Any]:
    """Retrieve conversation context (recent messages + summaries)."""
    # Existing code...
```

### Step 6: Add @traceable to the Memory Tools 

These tools handle memory recall and user summaries:

```python
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
```

## Activity 5: Adding Tracing to Database Calls

Database operations can be performance bottlenecks. By tracing Cosmos DB queries, you'll see exactly how long each query takes, what data is retrieved, and where to optimize.

### Step 1: Import the traceable Decorator

Navigate to **python/src/app/services/azure_cosmos_db.py**

Add this import at the top of the file:

```python
from langsmith import traceable
```

### Step 2: Add @traceable to Session Management Functions

Use **run_type="retriever"** for functions that retrieve session data from Cosmos DB:

```python
@traceable(run_type="retriever")
def get_session_by_id(session_id: str, tenant_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Get session by ID"""
    # Existing code...

@traceable
def create_session_record(user_id: str, tenant_id: str, activeAgent: str, title: str = None) -> Dict[str, Any]:
    """Create a new session record"""
    # Existing code...

@traceable
def update_session_activity(session_id: str, tenant_id: str, user_id: str):
    """Update session's last activity timestamp"""
    # Existing code...
```

**Why **run_type="retriever"** for queries?**  
Functions that retrieve data from storage should use **run_type="retriever"** so LangSmith renders them like RAG retrieval operations, showing query details and results.

### Step 3: Add @traceable to Message Management Functions

These functions handle conversation messages:

```python
@traceable
def append_message(
    session_id: str,
    tenant_id: str,
    user_id: str,
    role: str,
    content: str,
    tool_calls: Optional[List[Dict]] = None,
) -> str:
    """Append a message to a session."""
    # Existing code...

@traceable(run_type="retriever")
def get_message_by_id(
    message_id: str,
    session_id: str,
    tenant_id: str,
    user_id: str
) -> Optional[Dict[str, Any]]:
    """Get a specific message by its ID"""
    # Existing code...

@traceable(run_type="retriever")
def get_session_messages(
    session_id: str,
    tenant_id: str,
    user_id: str,
    include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """Get messages for a session"""
    # Existing code...

@traceable(run_type="retriever")
def count_active_messages(
    session_id: str,
    tenant_id: str,
    user_id: str
) -> int:
    """Count non-superseded, non-summary messages for a session."""
    # Existing code...
```

### Step 4: Add @traceable to Summary Management Functions

These functions manage conversation summaries:

```python
@traceable
def create_summary(
    session_id: str,
    tenant_id: str,
    user_id: str,
    summary_text: str,
    span: Dict[str, str],
    summary_timestamp: str,
    supersedes: Optional[List[str]] = None
) -> str:
    """Create a summary and mark messages as superseded."""
    # Existing code...

@traceable(run_type="retriever")
def get_session_summaries(
    session_id: str,
    tenant_id: str,
    user_id: str,
) -> List[Dict[str, Any]]:
    """Get summaries for a session"""
    # Existing code...

@traceable(run_type="retriever")
def get_user_summaries(
    user_id: str,
    tenant_id: str,
) -> List[Dict[str, Any]]:
    """Get all summaries for a user across all sessions"""
    # Existing code...
```

### Step 5: Add @traceable to Memory Management Functions

These functions handle user preference storage and retrieval:

```python
@traceable
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
    # Existing code...

@traceable
def update_memory_last_used(
    memory_id: str,
    user_id: str,
    tenant_id: str
) -> None:
    """Update the lastUsedAt timestamp for a memory when it's recalled/used"""
    # Existing code...

@traceable
def supersede_memory(
    memory_id: str,
    user_id: str,
    tenant_id: str,
    superseded_by: str
) -> bool:
    """Mark a memory as superseded by a newer memory."""
    # Existing code...

@traceable
def boost_memory_salience(
    memory_id: str,
    user_id: str,
    tenant_id: str,
    boost_amount: float = 0.05
) -> Dict[str, Any]:
    """Increase salience when a preference is confirmed or reinforced."""
    # Existing code...

@traceable(run_type="retriever")
def query_memories(
    user_id: str,
    tenant_id: str,
    query: str,
    min_salience: float = 0.0,
    include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """Query memories for a user using semantic search."""
    # Existing code...

@traceable(run_type="retriever")
def get_all_user_memories(
    user_id: str,
    tenant_id: str,
    include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """Get all memories for a user without any filtering."""
    # Existing code...
```

### Step 6: Add @traceable to Place Discovery Functions

These functions query the Places container:

```python
@traceable(run_type="retriever")
def query_places_hybrid(
    query: str,
    geo_scope_id: str,
    place_type: Optional[str] = None,
    dietary: Optional[List[str]] = None,
    accessibility: Optional[List[str]] = None,
    price_tier: Optional[str] = None,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Query places with filters including array-based filters"""
    # Existing code...

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
    """Filtered vector search with theme (Explore page with theme text)."""
    # Existing code...

@traceable(run_type="retriever")
def query_places_filtered(
    geo_scope_id: str,
    place_type: Optional[str] = None,
    dietary: Optional[List[str]] = None,
    accessibility: Optional[List[str]] = None,
    price_tier: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Simple filtered search without theme (Explore page filters only)."""
    # Existing code...
```

### Step 7: Add @traceable to Trip and User Management Functions

These functions manage trips and user profiles:

```python
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
    # Existing code...

@traceable(run_type="retriever")
def get_trip(trip_id: str, user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get a trip by ID"""
    # Existing code...

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
    # Existing code...

@traceable(run_type="retriever")
def get_all_users(tenant_id: str) -> List[Dict[str, Any]]:
    """Get all users for a tenant"""
    # Existing code...

@traceable(run_type="retriever")
def get_user_by_id(user_id: str, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Get a user by ID"""
    # Existing code...
```

### What This Achieves

With database calls traced, you can now:

✅ **Measure query performance**: See which Cosmos DB queries are slow  
✅ **Understand data flow**: What memories are recalled before each recommendation?  
✅ **Debug retrieval issues**: Why did query_memories return 0 results?  
✅ **Track summarization pipeline**: Count → Get messages → Create summary → Mark as summarized  
✅ **Optimize indexes**: Identify queries that need performance tuning  
✅ **Monitor memory operations**: See when memories are stored, superseded, or boosted

---

## Activity 6: Test Your Work and Viewing Traces in LangSmith

Now that all your agents, tools, and database functions are instrumented with **@traceable**, it's time to test the system and explore traces in the LangSmith dashboard.

### Step 1: Start Your Application

In your terminal, navigate to the app directory and start the FastAPI server:

Since we've added support for LangSmith, restart all services to load the changes.

**Terminal 1 (MCP Server):**
Stop the currently running MCP server (press **Ctrl+C**), then restart it:

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

**Terminal 2 (Backend API):**
Stop the currently running backend (press **Ctrl+C**), then restart it:

```powershell
cd python
uvicorn src.app.travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

**Important**: Always ensure your virtual environment is activated before starting the server!

You must be in **multi-agent-workshop\01_exercises** folder and then use the below commands to activate the virtual environment. And after activating the environment, follow the above commands to re-start the backend server.  

```powershell
cd multi-agent-workshop\01_exercises
.\venv\Scripts\Activate.ps1
```

**Terminal 3 (Frontend):**
Stop the currently running frontend (press **Ctrl+C**), then restart it:
```powershell
npm start
```

### Step 2: Open LangSmith Dashboard

1. Open your browser and go to [smith.langchain.com](https://smith.langchain.com/)
2. Navigate to your project: **multi-agent-travel-app**
3. You should see the **Traces** tab—this is where all your execution traces will appear

**Note:** If you don't see your project, use the search bar and type "travel" to find it.

### Step 3: Run Test Scenarios

Now we'll run test scenarios to generate traces. Make sure all three services are running (MCP server, backend API, and frontend).

Open your browser to http://localhost:4200 and interact with the travel assistant to generate traces.

#### Test 1

- Start a new conversation in the frontend(you can choose any user)
- Send: **Hi, I'm planning a trip to Seattle**

**What to look for in LangSmith:**

Navigate to your LangSmith dashboard and click on your project **travel-assistant**, and you will see the runs like the image below. Every message you send to the assistant will generate a run.

![Test1](./media/Module-05/Test5.png)

Now click on the **Threads** tab right next to the **Runs**, where you will see the tracing for every session. Click on the session/thread shown there, and you would be able to see tracing for every turn like below.

![Test2](./media/Module-05/Test6.png)

Now, let's copy the sessionId and navigate back to the **Runs** tab. Click on filter, add Thread Id filter like below and press enter. 

![Test3](./media/Module-05/Test3.png)

#### Test 2

- Continue the previous conversation.
- Send: **Find me some hotels.**

You should see a new run/trace. You can see in the trace that the app starts with the orchestrator agent, which extracts preferences from the user message. Clicking on the agent nodes and tool calls, you can check the complete stack trace of the multi agent app.

![Test4](./media/Module-05/Test4.png)

#### Test 3

- You can try sending more messages to the chat assistant, and keep exploring the traces.
- The **Runs** tab show you details about every turn, and the **Threads** tab show the entire session having all the turns.

## Troubleshooting

| Issue                        | Check                 | Solution                                                                          |
|------------------------------|-----------------------|-----------------------------------------------------------------------------------|
| No traces in LangSmith       | Environment variables | Verify `LANGCHAIN_TRACING_V2=true` and API key is correct in `.env`               |
| `@traceable` not found       | Imports               | Add `from langsmith import traceable` at top of file                              |
| Traces missing tool calls    | MCP server            | Ensure `mcp_http_server.py` has `@traceable` on all tool functions                |
| Agent routing not visible    | Agent nodes           | Add `@traceable(run_type="llm")` to all agent functions in `travel_agents.py`     |
| Database queries not showing | Database functions    | Add `@traceable(run_type="retriever")` to query functions in `azure_cosmos_db.py` |
| Incomplete trace tree        | Async functions       | Ensure all async functions use `await` correctly                                  |
| API key errors               | LangSmith account     | Regenerate API key in LangSmith settings and update `.env`                        |


## Key Takeaways

1. **@traceable decorator** automatically captures inputs, outputs, timing, and errors without manual logging
2. **Nested traces** show the complete execution path from orchestrator → specialist → tools → database
3. **Run types** (LLM, Tool, Retriever) help LangSmith render different components appropriately
4. **Memory extraction chain** is now fully visible (extract → resolve → store → database)
5. **Performance bottlenecks** are easy to identify with timing data for each operation
6. **Debugging is faster** when you can see exactly which agent made what decision and why

## LangSmith Use cases

With observability in place, you can:
- Debug complex agent routing issues by visualizing the decision tree
- Optimize slow database queries using timing data
- Understand why preferences are or aren't being stored
- Monitor token usage and OpenAI costs per agent
- Share traces with your team for collaborative troubleshooting
- Track system behavior in production environments

## What's Next?

Proceed to Module 06: **[Evaluating Your Multi-Agent Application](./Module-05.md)**
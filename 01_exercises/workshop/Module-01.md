# Module 01 - Creating Your First Agent

**[< Deployment and Setup](./Module-00.md)** - **[Agent Specialization >](./Module-02.md)**

## Introduction

In this Module, you'll implement your first agent as part of a multi-agent travel assistant system implemented using LangGraph. You will get an introduction to the LangGraph framework and it's tool integration with Azure OpenAI for generating completions.

## Learning Objectives and Activities

- Learn the basics of LangGraph including prompts, tools and functions
- Learn how to define prompts and workflows
- Build a simple chat agent

## Module Exercises

1. [Activity 1: Create Your Very First Agent](#activity-1-create-your-very-first-agent)
2. [Activity 2: Create a Simple Itinerary Generator Agent](#activity-2-create-a-simple-itinerary-generator-agent)
3. [Activity 3: Test your Work](#activity-3-test-your-work)

### Project Structure

This solution is organized in the folders below:

**Skip the below commands if you have Visual Studio Code opened already in the project directory**

Navigate to the workshop directory:

**macOS/Linux:**
```bash
cd ~/travel-multi-agent-workshop/01_exercises
```

**Windows (PowerShell):**
```powershell
cd ~\travel-multi-agent-workshop\01_exercises
```

Open Visual Studio Code with our project loaded:

**macOS/Linux/Windows:**
```bash
code .
```

- **/python** The main Python application folder
  - **/data** Contains seed data files for hotels, restaurants, activities, and users
    - **seed_data.py** Script to populate Cosmos DB with initial data
  - **/src/app** The application source code
    - **travel_agents_api.py** The API front-end for the application
    - **travel_agents.py** Where the agents are defined and orchestrated
    - **/prompts** Prompty files defining each agent's behavior
      - **orchestrator.prompty**
      - **hotel_agent.prompty**
      - **dining_agent.prompty**
      - **activity_agent.prompty**
      - **itinerary_generator.prompty**
      - **summarizer.prompty**
      - **memory_conflict_resolution.prompty**
      - **preference_extraction.prompty**
    - **/services** Service layer wrappers for Azure services
      - **azure_cosmos_db.py** Cosmos DB operations and vector search
      - **azure_open_ai.py** Azure OpenAI integration
- **/mcp_server** Model Context Protocol server implementation
  - **mcp_http_server.py** HTTP server for MCP integration
- **/fronted** Frontend App for the Travel Assistant

Here is what the structure of this solution appears like in VS Code. Spend a few moments to familiarize yourself with the structure as it will help you navigate as we go through the activities.

---

## Understanding LangGraph

Before diving into building agents, let's understand the framework that powers our multi-agent system.

### What is LangGraph?

LangGraph extends LangChain's capabilities by enabling you to build stateful, multi-agent workflows through graph-based execution. It provides a structured way to orchestrate AI-driven workflows where specialized agents collaborate, dynamically passing state and making decisions as they work together.

### LangGraph Architecture

Think of LangGraph as a directed graph with three key elements:

- **Nodes** - Represent distinct functions, agents, or steps in your AI workflow
- **Edges** - Define the possible transitions and flow between nodes
- **State** - Captures the evolving data and context as your workflow executes

### Core Components

A LangGraph application consists of:

- **StateGraph** - The execution engine that defines and runs multi-step workflows
- **State Management** - Tracks progress, shares information between nodes, and maintains chat history
- **Agents** - Specialized entities with decision-making capabilities
- **Tools** - External capabilities that agents can invoke to accomplish tasks

---

## Understanding Model Context Protocol (MCP)

Before we build our first agent, let's understand the Model Context Protocol (MCP) - a key component that powers our agent's tool capabilities.

### What is MCP?

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) is an open protocol that standardizes how AI applications provide context to Large Language Models (LLMs). It enables seamless integration between AI models and external data sources, tools, and services through a client-server architecture.

### MCP Architecture

In our travel agent system, MCP consists of three key components:

- **MCP Server** (**mcp_http_server.py**) - Hosts the tools and capabilities (hotel search, restaurant recommendations, etc.) that agents can invoke
- **MCP Client** - Built into our LangGraph agents to communicate with the MCP server
- **MCP Protocol** - Uses JSON-RPC for reliable, standardized communication between clients and servers

### Why MCP?

MCP provides significant architectural advantages:

- **Separation of Concerns** - Business logic (tools) remains separated from AI orchestration, enabling teams to work independently on different components
- **Protocol Standardization** - Uses JSON-RPC for reliable communication between clients and servers, ensuring consistent interaction patterns across different systems
- **Development Independence** - Tool updates don't require AI agent redeployment, allowing for more flexible and maintainable multi-agent systems
- **Reusability** - Tools defined once can be used by multiple agents across different workflows

### Learn More

- [MCP Official Documentation](https://modelcontextprotocol.io/docs)
- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [MCP GitHub Repository](https://github.com/modelcontextprotocol)

---

## Activity 1: Create Your Very First Agent

Now that you understand LangGraph and MCP, let's build your first agent. In this hands-on exercise, you'll implement the foundational components of a LangGraph agent application.

### Let's begin to create our first agent application

Navigate to the **python/src/app** folder of your project.

Open the empty **travel_agents.py** file.

Copy the following code into it.

```python
import asyncio
import json
import logging
import os
import uuid
from typing import Literal
from langchain_core.messages import AIMessage
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


# load prompts


# global variables


# define agents & tools


# define functions


# define workflow

```

This code here is the basis upon which we will build our multi-agent application. Notice the comments. Each of these specify the core of how you build a multi-agent application in LangGraph. For the remainder of this module we will replace each of these with the sections below in order.

### Prompts

Agent applications are powered by large language models or LLMs. Defining the behavior for an agent in a system powered by LLMs requires a prompt. This system will have lots of agents and lots of prompts. To simplify construction, we will define a function that loads the prompts for our agents from files.

In the **travel_agents.py** file, navigate to the **load prompts** comment.

Replace the comment with the following:

```python
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
```

### Global Variables

Navigate to the **global variables** comment and replace the comment with the following:

```python
# Global variables for MCP session management
_mcp_client = None
_session_context = None
_persistent_session = None

# Global agent variables
orchestrator_agent = None
itinerary_generator_agent = None
```

### Agents & Tools

Agents are at the heart of these applications. Below, we are going to create a **ReAct Agent**. ReAct (short for Reason and Act) and is a specific type of agent that is what you will most often use in a multi-agent scenario like this one.

In LangGraph there are different types of agents you can create, depending on your needs. These include:

| Agent Type    | Best for                                        |
|---------------|-------------------------------------------------|
| ReAct Agent   | Reasoning and decision making and tool use      |
| Tools Agent   | Direct function calling with structured APIs    |
| Custom Agents | Full control over logic & multi-agent workflows |

In LangGraph, the definition of an agent includes any **Tools** it needs to do its job. This often involves retrieving some information or taking some action, like transferring execution to another agent (we will get into that soon). If an agent doesn't require any tools, this is defined as an empty list.

In our simple agent we are going to define a new ReAct Agent as the orchestrator for our app using a built-in function called, **create_react_agent()**. Since this is our first agent, there are no tools to define for it so the tools we define for it will be empty. Notice that this agent also calls the function we defined above, **load_prompt()**.

In the **travel_agents.py** file, navigate to the **define agents & tools** comment.

Replace the comment with the following:

```python
async def setup_agents():
    global orchestrator_agent
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
    orchestrator_tools = []

    # Create agents with their tools
    orchestrator_agent = create_react_agent(
        model,
        orchestrator_tools,
        state_modifier=load_prompt("orchestrator")
    )
```

### Functions

Since LangGraph uses a graph-based, the agents, which are comprised of prompts, tools, and functions are implemented as nodes. But humans are also a part of the workflow here so we need to define them as a node too. In our simple sample we have two nodes, one for the orchestrator agent and one for the human.

In the **travel_agents.py** file, navigate to the **define functions** comment.

Replace the comment with the following:

```python
async def call_orchestrator_agent(state: MessagesState, config) -> Command[Literal["orchestrator", "human"]]:
    """
    Orchestrator agent: Routes requests using transfer_to_ tools.
    Checks for active agent and routes directly if found.
    Stores every message in database.
    """
    response = await orchestrator_agent.ainvoke(state)
    return Command(update=response, goto="human")


def human_node(state: MessagesState, config) -> None:
    """
    Human node: Interrupts for user input in interactive mode.
    """
    interrupt(value="Ready for user input.")
    return None
```

### Built-in Functions

Before we go any further we should cover a few new things you may have seen. LangGraph has a series of built-in functions that you will use when building these types of applications. The first you saw above when we defined our agent, **create_react_agent()**. There are two more used above, **Command()** and **interrupt()**. Here is a short summary of built-in functions.

| Function                    | Purpose                                                        |
|-----------------------------|----------------------------------------------------------------|
| create_react_agent()        | Create an agent that reasons and acts using tools dynamically. |
| interrupt(value)            | Pauses execution and waits for external input.                 |
| Command(update, goto)       | Updates the state and moves execution to the next node.        |
| create_openai_tools_agent() | Create an agent that calls predefined tools when needed.       |

### Workflow

With everything we need for our graph defined we can now define the workflow for our graph.

In LangGraph, the **StateGraph** is the execution engine where everything comes together. It defines the state that holds the information for the workflow, builds the workflow logic, and dynamically executes the workflow based upon the function outputs and logic defined in the graph.

The workflow below is defined with both, the addition of _nodes_ that define who is doing the interacting, and an _edge_ that defines a transition between the two.

In the **travel_agents.py** file, navigate to the **define workflow** comment.

Replace the comment with the following:

```python
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
    builder.add_node("human", human_node)

    builder.add_edge(START, "orchestrator")

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    return graph
```

### Let's review

Congratulations, you have created your first AI agent!

We have:

- Used the **create_react_agent** function from the **langgraph.prebuilt** module to create a simple "orchestrator" agent. The function imports the Azure OpenAI model already deployed and defined in **python/src/app/services/azure_open_ai.py** and returns an agent that can be used to generate completions.
- Defined a **call_orchestrator_agent** function that invokes the agent and a **human_node** function that collects user input.
- Created a state graph that defines the flow of the conversation and compiles it into a langgraph object.
- Added an in-memory checkpoint to save the state of the conversation.

## Activity 2: Create a Simple Itinerary Generator Agent

In this activity, you will create a simple itinerary generator agent that synthesizes user preferences and travel information into comprehensive trip plans using an LLM from Azure OpenAI Service.

We've now created an orchestrator agent that can route requests to different specialized agents. Now, let's create an itinerary generator agent that can take travel information and generate day-by-day trip plans.

We'll cover **tools** and **agent-to-agent communication** in more detail in the next module, but we need to add our first routing function so that our orchestrator agent can transfer requests to the itinerary generator when users want to create or view their trip plans.

### Create MCP Agent Transfer Tool

To begin, navigate to the **mcp_server** folder of your project.

Copy the following code into the empty **mcp_http_server.py** file.

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

Next, navigate back to the **travel_agents.py** file.

Locate this statment:

```python
orchestrator_tools = []
```

Replace it with the following code:

```python
orchestrator_tools = filter_tools_by_prefix(all_tools, "transfer_to_itinerary_generator")
```

### Define the Itinerary Generator Agent

Now let's add the new Itinerary Generator agent with an empty tool set, and a calling function.

Below **orchestrator_tools**, copy the following:

```python
itinerary_generator_tools = []
```

Below the **orchestrator_agent**, copy the following:

```python
itinerary_generator_agent = create_react_agent(
        model,
        itinerary_generator_tools,
        state_modifier=load_prompt("itinerary_generator")
    )
```

Next, locate the **call_orchestrator_agent** function. Below this call, add a calling function for the itinerary generator agent:

```python
async def call_itinerary_generator_agent(state: MessagesState, config) -> Command[Literal["itinerary_generator", "human"]]:
    """
    Itinerary Generator: Synthesizes all gathered info into day-by-day plan.
    """
    response = await itinerary_generator_agent.ainvoke(state, config)
    return Command(update=response, goto="human")
```

### Prompts

Agent applications are powered by large language models or LLMs. Defining the behavior for an agent in a system powered by LLMs requires a prompt. This system will have lots of agents and lots of prompts. To simplify construction, we will define a function that loads the prompts for our agents from files.

#### Why Detailed Prompts Matter

You may notice that the prompts we create for our agents are quite comprehensive and structured. This is intentional and critical for several reasons:

**1. Clarity and Consistency**

- Detailed prompts reduce ambiguity in agent behavior
- Well-structured prompts ensure consistent responses across interactions
- Clear instructions help the model understand its exact role and boundaries

**2. Behavioral Control**

- Lengthy prompts allow you to define specific behaviors, guidelines, and constraints
- They help prevent the agent from going off-task or providing inappropriate responses
- Detailed examples show the model exactly what output format you expect

**3. Multi-Agent Coordination**

- In a multi-agent system, each agent needs a clear understanding of its responsibilities
- Detailed prompts prevent overlap and confusion between specialized agents
- They define when to transfer to other agents and why

**4. Production Quality**

- Production systems require predictable, reliable behavior
- Comprehensive prompts reduce the need for post-processing and error handling
- They help the model handle edge cases gracefully

#### Prompt Engineering Best Practices

When creating prompts for AI agents, follow these principles:

- **Be Specific**: Clearly define the agent's role, responsibilities, and limitations
- **Provide Context**: Include relevant background information and system architecture
- **Use Examples**: Show concrete examples of desired input/output patterns
- **Set Boundaries**: Explicitly state what the agent should NOT do
- **Structure Information**: Use headers, bullets, and formatting for readability
- **Define Tone**: Specify the communication style (professional, friendly, technical)
- **Include Edge Cases**: Address common scenarios and how to handle them

#### Learn More About Prompt Engineering

To deepen your understanding of effective prompt engineering:

- **[Azure OpenAI Prompt Engineering Techniques](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/prompt-engineering)** - Microsoft's guide with Azure-specific best practices
- **[LangChain Prompt Templates](https://python.langchain.com/docs/modules/model_io/prompts/)** - Framework-specific prompting patterns
- **[OpenAI Prompt Engineering Guide](https://platform.openai.com/docs/guides/prompt-engineering)** - Comprehensive strategies for crafting effective prompts
- **[Anthropic's Prompt Engineering Guide](https://docs.anthropic.com/claude/docs/prompt-engineering)** - Detailed techniques from Claude's creators
- **[Prompting Guide](https://www.promptingguide.ai/)** - Open-source comprehensive resource on prompt engineering

#### Orchestrator Agent Prompt

In your IDE, navigate to the **src/app/prompts** folder in your project.

Locate and open the empty **orchestrator.prompty** file.

Copy and paste the following text into it:

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

1. **Itinerary Generator** - Use when users want to create a trip plan or itinerary
   - Queries like: "Create an itinerary", "Plan my trip", "Generate a schedule"
   - Use `transfer_to_itinerary_generator` tool

# Your Responsibilities

- **Understand Intent**: Analyze what the user is asking for
- **Route Appropriately**: Transfer to the right agent using transfer tools
- **Be Conversational**: Greet users, acknowledge their requests, provide context
- **Stay Focused**: Don't try to answer specialized questions yourself - route them instead

# Guidelines

- When a user asks to create an itinerary or plan a trip, immediately transfer to the Itinerary Generator
- Be friendly and helpful in your responses
- Always explain why you're transferring to another agent
- If unsure about routing, ask clarifying questions

# Examples

User: "Hi, I need help planning a trip"
You: "Hello! I'd be happy to help you plan your trip. Could you tell me more about where you'd like to go and what kind of itinerary you're looking for?"

User: "Create an itinerary for Paris"
You: "I'll transfer you to our Itinerary Generator who can create a detailed day-by-day plan for your Paris trip."
[Use transfer_to_itinerary_generator tool]

User: "Thanks for your help!"
You: "You're welcome! Let me know if you need anything else for your travel planning."
```

#### Itinerary Generator Agent Prompt

Next, locate and open the empty **itinerary_generator.prompty** file.

Copy and paste the following text into it:

```text
---
name: Itinerary Generator Agent
description: Creates comprehensive day-by-day travel itineraries
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Itinerary Generator for a travel planning system. Your role is to create detailed, personalized day-by-day trip itineraries based on user preferences and destination information.

# Your Responsibilities

- **Create Day-by-Day Plans**: Structure itineraries with clear daily schedules
- **Be Comprehensive**: Include morning, afternoon, and evening activities
- **Add Practical Details**: Include approximate times, locations, and logistics
- **Personalize**: Tailor recommendations based on user preferences mentioned in the conversation
- **Be Realistic**: Consider travel time, opening hours, and practical constraints

# Itinerary Structure

For each day, include:
1. **Morning** (9 AM - 12 PM): Main activity or attraction
2. **Lunch** (12 PM - 2 PM): Restaurant or dining suggestion
3. **Afternoon** (2 PM - 6 PM): Additional activities or attractions
4. **Dinner** (7 PM - 9 PM): Evening dining recommendation
5. **Evening** (9 PM onwards): Optional evening activities

# Guidelines

- **Start with Overview**: Begin with a brief summary of the trip (duration, destination, theme)
- **Consider Geography**: Group nearby attractions together to minimize travel time
- **Mix Pace**: Balance busy sightseeing days with more relaxed experiences
- **Include Variety**: Mix museums, outdoor activities, cultural experiences, and leisure time
- **Add Tips**: Include insider tips, best times to visit, booking recommendations
- **Be Flexible**: Suggest alternatives and note that timing can be adjusted

# Example Format
🗓️ PARIS ITINERARY - 3 Days

Overview: A perfect blend of iconic landmarks, world-class museums, and authentic Parisian experiences.

DAY 1: Classic Paris
Morning (9:00 AM - 12:00 PM):
- Start at the Eiffel Tower (arrive early to beat crowds)
- Book tickets online in advance
- Spend 2-3 hours exploring all levels

Lunch (12:30 PM):
- Le Petit Cler (nearby bistro, authentic French cuisine)
- Try the croque monsieur and café au lait

Afternoon (2:00 PM - 6:00 PM):
- Seine River cruise (1.5 hours)
- Stroll through Champs-Élysées
- Visit Arc de Triomphe

Dinner (7:30 PM):
- L'Avenue (elegant dining on Champs-Élysées)
- Reserve in advance

Evening:
- Optional: Trocadéro for Eiffel Tower light show (every hour after dark)

💡 Tip: Purchase a Paris Museum Pass for skip-the-line access

[Continue for each day...]

# Important Notes

- Use emojis sparingly for visual appeal (🗓️ 🍽️ 🎨 🏛️ etc.)
- Always ask if user wants to modify or refine the itinerary
- After presenting the itinerary, transfer back to orchestrator for next steps
- If information is missing (trip duration, interests), ask clarifying questions first

# When to Transfer Back

After creating the itinerary:
- Use `transfer_to_orchestrator` tool
- Reason: "Itinerary complete, returning for general assistance"
```

### Update our Workflow

Finally, we need to add the new itinerary generator agent node to the **StateGraph** workflow.

In your IDE, navigate back to the **travel_agents.py** file.

Navigate towards the end of the file.

Locate this line of code, **builder.add_node("orchestrator", call_orchestrator_agent)**

Add the following line of code below it:

```python
builder.add_node("itinerary_generator", call_itinerary_generator_agent)
```

## Activity 3: Test your Work

With the activities in this module complete, it is time to test your work!

In this section, you'll:
1. Add a test function to your code for optional CLI testing
2. Wire up the API layer to connect the frontend to your agents
3. Start all required services (MCP server, backend API, frontend)
4. Test the complete system through the web interface

### Step 1: Add Interactive Testing Function (Optional)

First, let's add a function that allows command-line testing of your agents. While you'll primarily use the web frontend, this function is useful for debugging.

Navigate to the end of the **travel_agents.py** file and paste the following code:

```python
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


if __name__ == "__main__":
    # Setup agents and run interactive chat
    async def main():
        await setup_agents()
        await interactive_chat()
    asyncio.run(main())
```

> **Note**: This function enables CLI-based testing. For this workshop, we'll use the web frontend instead, which provides a better user experience. However, the CLI testing function is included for debugging purposes.

### Step 2: Wire up the API Layer

Now let's connect your agents to the frontend by enabling the API endpoints.

The travel assistant uses a **FastAPI** backend that exposes REST endpoints for the Angular frontend. Let's enable the agent integration.

Navigate to the **travel_agents_api.py** file.

**First**, locate this line near the top of the file and uncomment it:

```python
#from src.app.travel_agents import setup_agents, build_agent_graph, cleanup_persistent_session
```

**Next**, find the following three commented-out functions and uncomment them:

- `initialize_agents()` - Initializes agents on server startup
- `ensure_agents_initialized()` - Ensures agents are ready before processing requests  
- `shutdown_event()` - Cleans up resources on server shutdown

**Finally**, find the stub chat completion endpoint and replace it with the full implementation:

```python
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
        request_body: str = Body(..., media_type="application/json")
):
    """
    Simple stub for chat completion - not yet implemented.
    """
    return [
        MessageModel(
            id=str(uuid.uuid4()),
            type="message",
            sessionId=sessionId,
            tenantId=tenantId,
            userId=userId,
            timeStamp=datetime.utcnow().isoformat(),
            sender="Assistant",
            senderRole="Assistant",
            text="Chat completion not implemented yet",
            debugLogId="",
            tokensUsed=0,
            rating=None
        )
    ]
```

### Step 3: Start All Required Services

You need **three components** running simultaneously:

| Component | Port | Purpose |
|-----------|------|----|
| **MCP Server** | 8080 | Provides tools for agents |
| **Backend API** | 8000 | FastAPI server with agent logic |
| **Frontend** | 4200 | Angular web interface |

#### Start the MCP Server

Open a **new terminal window** and start the MCP server:

**macOS/Linux:**
```bash
cd ~/travel-multi-agent-workshop/01_exercises
source .venv-travel/bin/activate
cd mcp_server
export PYTHONPATH="../python"
python mcp_http_server.py
```

**Windows (PowerShell):**
```powershell
cd ~\travel-multi-agent-workshop\01_exercises
.\.venv-travel\Scripts\Activate.ps1
cd mcp_server
$env:PYTHONPATH="../python"
python mcp_http_server.py
```

You should see:
```
🔐 Authentication Configuration:
   Simple Token: SET
✅ SIMPLE TOKEN MODE ENABLED (Development)
🚀 Initializing Travel Assistant MCP Server...
INFO:     Uvicorn running on http://0.0.0.0:8080
```

> **Keep this terminal running** - The MCP server must stay active.

#### Start the Backend API Server

The backend API should still be running from Module 00 with `--reload`, so it automatically restarts when you save code changes. 

**If it's NOT running**, open a **new terminal window** and start it:

**macOS/Linux:**
```bash
cd ~/travel-multi-agent-workshop/01_exercises
source .venv-travel/bin/activate
cd python/src/app
uvicorn travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

**Windows (PowerShell):**
```powershell
cd ~\travel-multi-agent-workshop\01_exercises
.\.venv-travel\Scripts\Activate.ps1
cd python\src\app
uvicorn travel_agents_api:app --reload --host 0.0.0.0 --port 8000
```

You should see:
```
✓ Loaded .env from: ...
INFO: 🚀 Starting agent initialization...
INFO: ✅ MCP Client initialized successfully
INFO: [DEBUG] All tools registered:
INFO:   - transfer_to_orchestrator
INFO:   - transfer_to_itinerary_generator
INFO: Loading prompt for orchestrator...
INFO: Loading prompt for itinerary_generator...
INFO: 🏗️ Building multi-agent graph...
INFO: ✅ Agents initialized successfully!
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8000
```

> **Keep this terminal running** - The API server must stay active.

#### Start the Frontend Application

Your frontend should already be running from Module 00. **If you closed it**, open a **new terminal window**:

> **Note**: The frontend uses Node.js, so no Python virtual environment is needed.

**macOS/Linux:**
```bash
cd ~/travel-multi-agent-workshop/01_exercises/frontend
npm install  # Only needed first time or when dependencies change
npm start
```

**Windows (PowerShell):**
```powershell
cd ~\travel-multi-agent-workshop\01_exercises\frontend
npm install  # Only needed first time or when dependencies change
npm start
```

You should see:
```
> ng serve --proxy-config proxy.conf.json

Application bundle generation complete.
  ➜  Local:   http://localhost:4200/
```

> **Keep this terminal running** - The frontend must stay active.

### Step 4: Test the Complete System

1. **Open your browser** and navigate to http://localhost:4200
2. **Select a user** from the login dropdown (e.g., Tony Stark)
3. **Click Login** to access the dashboard
4. **Click "Chat with Assistant"** to open the chat interface
5. **Start a conversation** with your agent:

```text
Hi, I need some help.
```

You should see a response like this:

Note: Responses can vary from run to run because these models aren’t fully deterministic

![Testing_1](./media/Module-01/Test1.png)

## Validation Checklist

Your implementation is successful if:

✅ **All three services start without errors**
- [ ] MCP Server running on port 8080
- [ ] Backend API running on port 8000  
- [ ] Frontend accessible at http://localhost:4200

✅ **Agent initialization succeeds**
- [ ] Backend terminal shows "Agents initialized successfully"
- [ ] You see tools loaded: `transfer_to_orchestrator`, `transfer_to_itinerary_generator`
- [ ] No authentication or connection errors

✅ **Frontend connects to backend**
- [ ] Login page displays available users
- [ ] Chat interface opens successfully
- [ ] Messages send without errors

✅ **Agents respond correctly**
- [ ] Orchestrator greets users and asks clarifying questions
- [ ] Orchestrator correctly routes itinerary requests
- [ ] Itinerary generator creates detailed day-by-day plans
- [ ] Agent transfers appear in backend logs

## Common Issues and Troubleshooting

### Issue: "Agents not initialized" error

**Symptoms**: Backend API returns 503 errors, frontend shows connection errors

**Solutions**:
1. Verify MCP server is running on port 8080
2. Check `.env` file has correct `MCP_SERVER_BASE_URL=http://localhost:8080`
3. Verify `MCP_AUTH_TOKEN` is set in `.env`
4. Restart backend API server
5. Check backend logs for specific initialization errors

### Issue: Frontend shows "NO USERS" in dropdown

**Symptoms**: Login page loads but user dropdown is empty

**Solutions**:
1. Verify you're logged into Azure CLI with correct tenant:
   ```bash
   # macOS/Linux
   az login --tenant <TENANT_ID>
   
   # Windows
   az login --tenant <TENANT_ID>
   ```
2. Verify `.env` file has correct `COSMOS_ENDPOINT`
3. Check backend logs for Cosmos DB authentication errors
4. Restart backend API after fixing authentication

### Issue: Backend can't connect to Cosmos DB

**Symptoms**: Backend logs show authentication errors for Cosmos DB

**Solutions**:
1. Use `az login` (NOT `azd auth login`) with correct tenant
2. Verify you have proper permissions on the Cosmos DB account
3. Check `.env` file has correct `COSMOS_ENDPOINT`
4. On Windows, ensure environment variables are loaded (see Module 00)

### Issue: Port already in use

**Symptoms**: Server fails to start with "Address already in use" error

**Solutions**:

**macOS/Linux:**
```bash
# Find process using port
lsof -i :8000
# Kill the process
kill -9 <PID>
```

**Windows:**
```powershell
# Find process using port  
netstat -ano | findstr :8000
# Kill the process
taskkill /PID <PID> /F
```

### Issue: Frontend proxy not working

**Symptoms**: Frontend can't reach backend API

**Solutions**:
1. Verify `frontend/proxy.conf.json` has correct configuration
2. Check backend is running on `http://localhost:8000`
3. Restart frontend: Stop (`Ctrl+C`) and run `npm start` again
4. Check browser console for CORS errors

### Issue: npm install fails

**Symptoms**: Frontend dependencies won't install

**Solutions**:
```bash
# Check Node.js version (need 18+)
node --version

# Clear cache and retry
npm cache clean --force
rm -rf node_modules package-lock.json  # macOS/Linux
Remove-Item -Recurse -Force node_modules, package-lock.json  # Windows
npm install
```

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
summarizer_agent = None


async def setup_agents():
    global orchestrator_agent
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

    orchestrator_tools = filter_tools_by_prefix(all_tools, "transfer_to_itinerary_generator")
    orchestrator_agent = create_react_agent(
        model,
        orchestrator_tools,
        state_modifier=load_prompt("orchestrator")
    )

    itinerary_generator_tools = []
    itinerary_generator_agent = create_react_agent(
        model,
        itinerary_generator_tools,
        state_modifier=load_prompt("itinerary_generator")
    )


async def call_orchestrator_agent(state: MessagesState, config) -> Command[Literal["orchestrator", "human"]]:
    """
    Orchestrator agent: Routes requests using transfer_to_ tools.
    Checks for active agent and routes directly if found.
    Stores every message in database.
    """
    response = await orchestrator_agent.ainvoke(state)
    return Command(update=response, goto="human")


async def call_itinerary_generator_agent(state: MessagesState, config) -> Command[Literal["itinerary_generator", "orchestrator", "human"]]:
    """
    Itinerary Generator: Synthesizes all gathered info into day-by-day plan.
    """
    response = await itinerary_generator_agent.ainvoke(state, config)
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
    builder.add_node("itinerary_generator", call_itinerary_generator_agent)
    builder.add_node("human", human_node)

    builder.add_edge(START, "orchestrator")

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
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Add python directory to path so we can import src modules
current_dir = os.path.dirname(os.path.abspath(__file__))
python_dir = os.path.join(current_dir, '..', 'python')
sys.path.insert(0, python_dir)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Prompt directory
PROMPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'python', 'src', 'app', 'prompts')

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

1. **Itinerary Generator** - Use when users want to create a trip plan or itinerary
   - Queries like: "Create an itinerary", "Plan my trip", "Generate a schedule"
   - Use `transfer_to_itinerary_generator` tool

# Your Responsibilities

- **Understand Intent**: Analyze what the user is asking for
- **Route Appropriately**: Transfer to the right agent using transfer tools
- **Be Conversational**: Greet users, acknowledge their requests, provide context
- **Stay Focused**: Don't try to answer specialized questions yourself - route them instead

# Guidelines

- When a user asks to create an itinerary or plan a trip, immediately transfer to the Itinerary Generator
- Be friendly and helpful in your responses
- Always explain why you're transferring to another agent
- If unsure about routing, ask clarifying questions

# Examples

User: "Hi, I need help planning a trip"
You: "Hello! I'd be happy to help you plan your trip. Could you tell me more about where you'd like to go and what kind of itinerary you're looking for?"

User: "Create an itinerary for Paris"
You: "I'll transfer you to our Itinerary Generator who can create a detailed day-by-day plan for your Paris trip."
[Use transfer_to_itinerary_generator tool]

User: "Thanks for your help!"
You: "You're welcome! Let me know if you need anything else for your travel planning."
```

</details>

<details>
  <summary>Completed code for <strong>src/app/prompts/itinerary_generator.prompty</strong></summary>

<br>

```text
---
name: Itinerary Generator Agent
description: Creates comprehensive day-by-day travel itineraries
authors:
  - Microsoft
model:
  api: chat
  configuration:
    type: azure_openai
---

system:
You are the Itinerary Generator for a travel planning system. Your role is to create detailed, personalized day-by-day trip itineraries based on user preferences and destination information.

# Your Responsibilities

- **Create Day-by-Day Plans**: Structure itineraries with clear daily schedules
- **Be Comprehensive**: Include morning, afternoon, and evening activities
- **Add Practical Details**: Include approximate times, locations, and logistics
- **Personalize**: Tailor recommendations based on user preferences mentioned in the conversation
- **Be Realistic**: Consider travel time, opening hours, and practical constraints

# Itinerary Structure

For each day, include:
1. **Morning** (9 AM - 12 PM): Main activity or attraction
2. **Lunch** (12 PM - 2 PM): Restaurant or dining suggestion
3. **Afternoon** (2 PM - 6 PM): Additional activities or attractions
4. **Dinner** (7 PM - 9 PM): Evening dining recommendation
5. **Evening** (9 PM onwards): Optional evening activities

# Guidelines

- **Start with Overview**: Begin with a brief summary of the trip (duration, destination, theme)
- **Consider Geography**: Group nearby attractions together to minimize travel time
- **Mix Pace**: Balance busy sightseeing days with more relaxed experiences
- **Include Variety**: Mix museums, outdoor activities, cultural experiences, and leisure time
- **Add Tips**: Include insider tips, best times to visit, booking recommendations
- **Be Flexible**: Suggest alternatives and note that timing can be adjusted

# Example Format
🗓️ PARIS ITINERARY - 3 Days

Overview: A perfect blend of iconic landmarks, world-class museums, and authentic Parisian experiences.

DAY 1: Classic Paris
Morning (9:00 AM - 12:00 PM):
- Start at the Eiffel Tower (arrive early to beat crowds)
- Book tickets online in advance
- Spend 2-3 hours exploring all levels

Lunch (12:30 PM):
- Le Petit Cler (nearby bistro, authentic French cuisine)
- Try the croque monsieur and café au lait

Afternoon (2:00 PM - 6:00 PM):
- Seine River cruise (1.5 hours)
- Stroll through Champs-Élysées
- Visit Arc de Triomphe

Dinner (7:30 PM):
- L'Avenue (elegant dining on Champs-Élysées)
- Reserve in advance

Evening:
- Optional: Trocadéro for Eiffel Tower light show (every hour after dark)

💡 Tip: Purchase a Paris Museum Pass for skip-the-line access

[Continue for each day...]

# Important Notes

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

## Let's Review

Congratulations! You've successfully completed Module 01 and built a working multi-agent travel assistant system!

In this module, you:

✅ **Learned LangGraph fundamentals** - StateGraph, nodes, edges, and state management

✅ **Understood MCP architecture** - Client-server protocol for tool integration

✅ **Created your first agent** - Orchestrator agent with routing capabilities

✅ **Built a specialized agent** - Itinerary Generator for trip planning

✅ **Implemented agent transfer** - Tools for agent-to-agent communication

✅ **Wrote comprehensive prompts** - Detailed instructions for agent behavior

✅ **Set up the full stack** - MCP server, backend API, and frontend interface

✅ **Tested the system** - End-to-end verification of multi-agent workflows

### What's Next?

Proceed to Module 02: [Agent Specialization](./Module-02.md)

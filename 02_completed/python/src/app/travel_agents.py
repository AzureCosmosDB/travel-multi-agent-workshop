import logging
import os
import sys
import uuid
import asyncio
import json
from typing import Literal
from datetime import datetime, UTC

# Add the project root to Python path to enable imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv(override=False)

from langchain_core.messages import ToolMessage, SystemMessage, AIMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command, interrupt
from langsmith import traceable

from src.app.services.azure_open_ai import model
from src.app.services.azure_cosmos_db import (
    sessions_container, patch_active_agent,
    update_session_container, aget_checkpoint_saver
)

# Setup logging - reduce clutter by setting specific loggers to WARNING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Reduce noise from verbose libraries
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)

# Local interactive mode flag
local_interactive_mode = False

# Prompt directory
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


async def setup_agents():
    """
    Initialize all agents with their respective MCP tools.
    This creates a persistent MCP session and loads domain-aware tools.
    
    Agent Structure:
    - Orchestrator: Entry point, routes to specialized agents
    - Hotel Agent: Searches accommodations, stores hotel preferences
    - Activity Agent: Searches attractions, stores activity preferences  
    - Dining Agent: Searches restaurants, stores dining preferences
    - Itinerary Generator: Synthesizes all results into day-by-day plan
    """
    global orchestrator_agent, hotel_agent, activity_agent, dining_agent
    global itinerary_generator_agent
    global _mcp_client, _session_context, _persistent_session
    
    logger.info("🚀 Starting Travel Assistant MCP client...")
    
    # Load authentication configuration
    try:
        simple_token = os.getenv("MCP_AUTH_TOKEN")
        github_client_id = os.getenv("GITHUB_CLIENT_ID")
        github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")
        
        logger.info("🔐 Client Authentication Configuration:")
        logger.info(f"   Simple Token: {'SET' if simple_token else 'NOT SET'}")
        logger.info(f"   GitHub OAuth: {'SET' if github_client_id and github_client_secret else 'NOT SET'}")
        
        # Determine authentication mode
        if github_client_id and github_client_secret:
            auth_mode = "github_oauth"
            logger.info("   Mode: GitHub OAuth (Production)")
        elif simple_token:
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
    if auth_mode == "simple_token" and simple_token:
        client_config["travel_tools"]["headers"] = {
            "Authorization": f"Bearer {simple_token}"
        }
        logger.info("🔐 Added Bearer token authentication to client")
    elif auth_mode == "github_oauth":
        client_config["travel_tools"]["auth"] = "oauth"
        logger.info("🔐 Enabled OAuth authentication for client")
    
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
    # Tool Distribution for Specialized Agents
    # ========================================================================
    
    # Orchestrator: Session management + memory tools + all transfer tools
    orchestrator_tools = filter_tools_by_prefix(all_tools, [
        "create_session", "get_session_context", "append_turn",
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_"  # All transfer tools
    ])

    hotel_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search hotels
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])

    activity_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search attractions
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])

    dining_tools = filter_tools_by_prefix(all_tools, [
        "discover_places",  # Search restaurants
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator", "transfer_to_itinerary_generator"
    ])

    itinerary_generator_tools = filter_tools_by_prefix(all_tools, [
        "create_new_trip", "update_trip", "get_trip_details",
        "add_turn", "recall_memories", "get_user_summary",
        "transfer_to_orchestrator"
    ])
    
    logger.info(f"\n📊 Tool Distribution (4 Specialized Agents):")
    logger.info(f"   Orchestrator: {len(orchestrator_tools)} tools")
    logger.info(f"   Hotel Agent: {len(hotel_tools)} tools")
    logger.info(f"   Activity Agent: {len(activity_tools)} tools")
    logger.info(f"   Dining Agent: {len(dining_tools)} tools")
    logger.info(f"   Itinerary Generator: {len(itinerary_generator_tools)} tools")
    
    # Create agents with their tools
    orchestrator_agent = create_react_agent(
        model, 
        orchestrator_tools, 
        state_modifier=load_prompt("orchestrator")
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
    
    itinerary_generator_agent = create_react_agent(
        model,
        itinerary_generator_tools,
        state_modifier=load_prompt("itinerary_generator")
    )
    
    logger.info("✅ All agents created successfully\n")


async def cleanup_persistent_session():
    """Clean up the persistent MCP session when the application shuts down"""
    global _session_context, _persistent_session
    
    if _session_context is not None and _persistent_session is not None:
        try:
            await _session_context.__aexit__(None, None, None)
            logger.info("✅ MCP persistent session cleaned up successfully")
        except Exception as e:
            logger.error(f"Error cleaning up MCP session: {e}")


# ============================================================================
# Helper: Store Message in Database at Every Turn
# ============================================================================

# ============================================================================
# Agent Node Functions
# ============================================================================

@traceable(run_type="llm")
async def call_orchestrator_agent(state: MessagesState, config) -> Command[Literal["orchestrator", "hotel", "activity", "dining", "itinerary_generator", "human"]]:
    """
    Orchestrator agent: Routes requests using transfer_to_ tools.
    Checks for active agent and routes directly if found.
    Stores every message in database.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info(f"🎯 Calling orchestrator agent with Thread: {thread_id}, User: {user_id}, Tenant: {tenant_id}")
    
    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', thread_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
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


@traceable(run_type="llm")
async def call_hotel_agent(state: MessagesState, config) -> Command[Literal["hotel", "itinerary_generator", "orchestrator", "human"]]:
    """
    Hotel Agent: Searches accommodations and stores hotel preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("🏨 ========== HOTEL AGENT CALLED ==========")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "hotel")

    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', thread_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))
    
    logger.info(f"🏨 Invoking hotel_agent...")
    response = await hotel_agent.ainvoke(state, config)
    logger.info(f"🏨 hotel_agent.ainvoke completed")
    
    # Log tool calls if any
    if isinstance(response, dict) and "messages" in response:
        tool_calls = [msg for msg in response["messages"] if isinstance(msg, ToolMessage)]
        if tool_calls:
            logger.info(f"🔧 Hotel Agent made {len(tool_calls)} tool calls")
            for tc in tool_calls:
                logger.info(f"🔧 Tool: {tc.name if hasattr(tc, 'name') else 'unknown'}")
        else:
            logger.warning(f"⚠️  Hotel Agent made NO tool calls!")
        
        ai_messages = [msg for msg in response["messages"] if isinstance(msg, AIMessage) and msg.content]
        if ai_messages:
            logger.info(f"💬 Hotel Agent response: {ai_messages[-1].content[:200]}...")
        
        # Remove system message
        response["messages"] = [
            msg for msg in response["messages"]
            if not isinstance(msg, SystemMessage)
        ]
    
    logger.info(f"🏨 ========== HOTEL AGENT COMPLETED ==========")
    return Command(update=response, goto="human")


@traceable(run_type="llm")
async def call_activity_agent(state: MessagesState, config) -> Command[Literal["activity", "itinerary_generator", "orchestrator", "human"]]:
    """
    Activity Agent: Searches attractions and stores activity preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("🎭 Activity Agent searching attractions...")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "activity")
    
    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', thread_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))
    
    response = await activity_agent.ainvoke(state, config)
    
    # Remove system message
    if isinstance(response, dict) and "messages" in response:
        response["messages"] = [
            msg for msg in response["messages"]
            if not isinstance(msg, SystemMessage)
        ]
    
    return Command(update=response, goto="human")


@traceable(run_type="llm")
async def call_dining_agent(state: MessagesState, config) -> Command[Literal["dining", "itinerary_generator", "orchestrator", "human"]]:
    """
    Dining Agent: Searches restaurants and stores dining preferences.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("🍽️  Dining Agent searching restaurants...")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "dining")
    
    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', thread_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))
    
    response = await dining_agent.ainvoke(state, config)
    
    # Remove system message
    if isinstance(response, dict) and "messages" in response:
        response["messages"] = [
            msg for msg in response["messages"]
            if not isinstance(msg, SystemMessage)
        ]
    
    return Command(update=response, goto="human")


@traceable(run_type="llm")
async def call_itinerary_generator_agent(state: MessagesState, config) -> Command[Literal["itinerary_generator", "orchestrator", "human"]]:
    """
    Itinerary Generator: Synthesizes all gathered info into day-by-day plan.
    """
    thread_id = config["configurable"].get("thread_id", "UNKNOWN_THREAD_ID")
    user_id = config["configurable"].get("userId", "UNKNOWN_USER_ID")
    tenant_id = config["configurable"].get("tenantId", "UNKNOWN_TENANT_ID")
    
    logger.info("📋 Itinerary Generator synthesizing plan...")
    
    # Patch active agent in database
    if local_interactive_mode:
        patch_active_agent(tenant_id or "cli-test", user_id or "cli-test", thread_id, "itinerary_generator")
    
    # Add context about available parameters
    state["messages"].append(SystemMessage(
        content=f"If tool to be called requires tenantId='{tenant_id}', userId='{user_id}', session_id='{thread_id}', thread_id='{thread_id}', include these in the JSON parameters when invoking the tool. Do not ask the user for them."
    ))
    
    response = await itinerary_generator_agent.ainvoke(state, config)
    
    # Remove system message
    if isinstance(response, dict) and "messages" in response:
        response["messages"] = [
            msg for msg in response["messages"]
            if not isinstance(msg, SystemMessage)
        ]
    
    return Command(update=response, goto="human")



@traceable
def human_node(state: MessagesState, config) -> None:
    """
    Human node: Interrupts for user input in interactive mode.
    """
    interrupt(value="Ready for user input.")
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
    
    valid_agents = {"orchestrator", "hotel", "activity", "dining", "itinerary_generator", "human"}
    if activeAgent in [None, "unknown"] or activeAgent not in valid_agents:
        logger.info(f"activeAgent is '{activeAgent}', defaulting to orchestrator")
        activeAgent = "orchestrator"
    
    return activeAgent


# ============================================================================
# Build Agent Graph
# ============================================================================

def build_agent_graph(checkpointer):
    """
    Build the multi-agent graph using LangGraph.
    
    Graph structure:
    - User input → Orchestrator (entry point)
    - Orchestrator routes via transfer_to_ tools
    - Specialized agents (Hotel, Activity, Dining) → Itinerary Generator or Orchestrator
    - Itinerary Generator → Orchestrator only
    - All agents → Human node (for user interrupts)
    """
    logger.info("🏗️  Building multi-agent graph...")
    
    builder = StateGraph(MessagesState)
    
    # Add all agent nodes (5 agents total)
    builder.add_node("orchestrator", call_orchestrator_agent)
    builder.add_node("hotel", call_hotel_agent)
    builder.add_node("activity", call_activity_agent)
    builder.add_node("dining", call_dining_agent)
    builder.add_node("itinerary_generator", call_itinerary_generator_agent)
    builder.add_node("human", human_node)
    
    # Set entry point - always start with orchestrator
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
    
    # Compile with the caller-provided checkpointer
    graph = builder.compile(checkpointer=checkpointer)
    
    logger.info("✅ Multi-agent graph built successfully")
    logger.info("📊 Graph structure:")
    logger.info("   Entry: User → Orchestrator")
    logger.info("   Orchestrator → Hotel/Activity/Dining/Itinerary")
    logger.info("   Hotel/Activity/Dining → Itinerary Generator or Orchestrator")
    logger.info("   Itinerary Generator → Orchestrator only")
    logger.info("   Agents: 5 total (Orchestrator, Hotel, Activity, Dining, Itinerary Generator)")
    
    return graph


# ============================================================================
# Interactive Chat Function (for CLI testing)
# ============================================================================

async def interactive_chat():
    """
    Interactive CLI for testing the travel assistant.
    Similar to banking app's interactive mode.
    """
    global local_interactive_mode
    local_interactive_mode = True
    
    thread_id = str(uuid.uuid4())
    # thread_id = "thread-7ab201e9-2bbc-41cc-a220-995558523a4f"
    thread_config = {
        "configurable": {
            "thread_id": thread_id,
            "userId": "Tony",
            "tenantId": "Marvel"
        }
    }
    
    print("\n" + "="*70)
    print("🌍 Travel Assistant - Interactive Test Mode")
    print("="*70)
    print("Type 'exit' to end the conversation")
    print("="*70 + "\n")
    
    # Build graph (await the async checkpointer first)
    checkpointer = await aget_checkpoint_saver()
    graph = build_agent_graph(checkpointer)
    
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


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    # Setup agents and run interactive chat
    async def main():
        await setup_agents()
        await interactive_chat()
    
    asyncio.run(main())

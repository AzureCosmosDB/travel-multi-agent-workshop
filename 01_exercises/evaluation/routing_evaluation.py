"""
Tool Routing Evaluation Script for Travel Assistant

Tests whether the supervisor picks the correct top-level tool wrapper
(``find_places``, ``create_or_update_itinerary``, or ``recall_memories``)
for each user request. When the supervisor answers directly without invoking
a tool, the actual route is reported as ``"none"``.

Usage:
    python routing_evaluation.py
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from langsmith import Client
from langchain_core.messages import HumanMessage

# Configure logging
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.identity").setLevel(logging.WARNING)
logging.getLogger("mcp").setLevel(logging.WARNING)
logging.getLogger("azure.cosmos").setLevel(logging.WARNING)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from src.app.travel_agents import setup_agents, build_agent_graph
from src.app.services.azure_cosmos_db import initialize_cosmos_client
from evaluators.heuristic_evaluators import correct_tool_routing

# Ensure stdout/stderr use UTF-8 so emoji in prints don't crash on Windows,
# where the console defaults to cp1252 and raises UnicodeEncodeError on emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


# The three top-level tool wrappers the supervisor exposes. Inner MCP tools
# (discover_places, create_new_trip, ...) fire on_tool_start events too, but
# routing is measured by which wrapper the supervisor itself chose first.
SUPERVISOR_TOOL_WRAPPERS = {
    "find_places",
    "create_or_update_itinerary",
    "recall_memories",
}


def load_dataset(dataset_path: str) -> list:
    """Load dataset from JSON file."""
    with open(dataset_path, 'r') as f:
        return json.load(f)


async def run_travel_agent_routing(inputs: dict) -> dict:
    """
    Track which supervisor tool wrapper handles the request first.

    The supervisor exposes three top-level tool wrappers; this returns the
    name of the first wrapper invoked. When the supervisor responds directly
    without calling any wrapper (e.g., a greeting), ``actual_tool`` is
    ``"none"``.

    Args:
        inputs: Dictionary containing the question

    Returns:
        Dictionary with ``actual_tool`` and ``all_supervisor_tools``
    """
    question = inputs["question"]
    unique_id = f"{hash(question)}_{id(inputs)}_{os.urandom(4).hex()}"
    thread_id = f"route_eval_{unique_id}"

    first_tool: str | None = None
    all_supervisor_tools: list[str] = []

    async for event in graph.astream_events(
        {"messages": [HumanMessage(content=question)]},
        config={
            "configurable": {
                "thread_id": thread_id,
                "userId": f"eval_user_{unique_id}",
                "tenantId": f"eval_tenant_{unique_id}"
            }
        },
        version="v2"
    ):
        if event["event"] == "on_tool_start":
            tool_name = event.get("name", "")
            if tool_name in SUPERVISOR_TOOL_WRAPPERS:
                if first_tool is None:
                    first_tool = tool_name
                if tool_name not in all_supervisor_tools:
                    all_supervisor_tools.append(tool_name)

    return {
        "actual_tool": first_tool or "none",
        "all_supervisor_tools": all_supervisor_tools,
    }


async def main():
    """Main evaluation execution."""
    print("=" * 60)
    print("🧭 TOOL ROUTING EVALUATION - Travel Assistant")
    print("=" * 60)
    
    # Load environment variables
    load_dotenv(override=True)
    os.environ["LANGCHAIN_TRACING_V2"] = "false"  # Disable tracing for faster evaluation
    
    # Paths
    eval_dir = Path(__file__).parent
    dataset_path = eval_dir / "datasets" / "routing_dataset.json"
    
    # Initialize Cosmos DB
    print("\n🔄 Initializing Cosmos DB...")
    initialize_cosmos_client()
    print("✅ Cosmos DB initialized")
    
    # Setup agents
    print("🔄 Setting up agents...")
    await setup_agents()
    print("✅ Agents initialized")
    
    # Build graph
    print("🔄 Building agent graph...")
    global graph
    graph = build_agent_graph()
    print("✅ Agent graph ready")
    
    # Load dataset
    print(f"\n📊 Loading dataset from {dataset_path}...")
    dataset_examples = load_dataset(dataset_path)
    print(f"✅ Loaded {len(dataset_examples)} examples")
    
    # Create LangSmith client
    client = Client(
        api_key=os.environ["LANGCHAIN_API_KEY"],
        api_url="https://api.smith.langchain.com"
    )
    
    # Create or update dataset
    dataset_name = "travel-assistant-routing"
    if client.has_dataset(dataset_name=dataset_name):
        print(f"🔄 Deleting existing dataset '{dataset_name}'...")
        dataset = client.read_dataset(dataset_name=dataset_name)
        client.delete_dataset(dataset_id=dataset.id)
    
    print(f"🔄 Creating dataset '{dataset_name}'...")
    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description="Supervisor tool-routing evaluation for travel assistant"
    )
    client.create_examples(dataset_id=dataset.id, examples=dataset_examples)
    print(f"✅ Dataset created with {len(dataset_examples)} examples")
    
    # Run evaluation
    print("\n" + "=" * 60)
    print("🚀 RUNNING EVALUATION")
    print("=" * 60)
    
    results = await client.aevaluate(
        run_travel_agent_routing,
        data=dataset_name,
        evaluators=[correct_tool_routing],
        experiment_prefix="travel-routing",
        num_repetitions=1,
        max_concurrency=4,
        metadata={
            "version": "v1.0",
            "description": "Test supervisor tool-wrapper routing decisions"
        }
    )
    
    print("\n" + "=" * 60)
    print("✅ EVALUATION COMPLETE")
    print("=" * 60)
    
    # Clean up MCP session
    print("\n🔄 Cleaning up resources...")
    from src.app.travel_agents import cleanup_persistent_session
    await cleanup_persistent_session()
    print("✅ Cleanup complete")


if __name__ == "__main__":
    asyncio.run(main())

"""
Agent Routing Evaluation Script for Travel Assistant

Tests if the orchestrator correctly routes requests to specialist agents.

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
from src.app.services.azure_cosmos_db import (
    initialize_cosmos_client,
    aget_checkpoint_saver,
    close_async_cosmos_client,
)
from evaluators.heuristic_evaluators import correct_routing


def load_dataset(dataset_path: str) -> list:
    """Load dataset from JSON file."""
    with open(dataset_path, 'r') as f:
        return json.load(f)


async def run_travel_agent_routing(inputs: dict) -> dict:
    """
    Track which agent handles the request.
    
    Args:
        inputs: Dictionary containing the question
        
    Returns:
        Dictionary with actual_route and all_agents visited
    """
    question = inputs["question"]
    unique_id = f"{hash(question)}_{id(inputs)}_{os.urandom(4).hex()}"
    thread_id = f"route_eval_{unique_id}"
    
    agents_visited = []
    
    # Stream events to track agent execution
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
        # Track when nodes are invoked
        if event["event"] == "on_chain_start":
            name = event.get("name", "")
            # Track actual node names
            if name in ["orchestrator", "hotel", "dining", "activity", "itinerary_generator", "summarizer"]:
                if name not in agents_visited:
                    agents_visited.append(name)
    
    # Determine the actual route:
    # If orchestrator delegated to a specialist, return the specialist
    # If orchestrator handled it alone, return orchestrator
    specialist_agents = [a for a in agents_visited if a != "orchestrator"]
    
    if specialist_agents:
        # Orchestrator delegated - return the specialist that handled it
        actual_route = specialist_agents[-1]  # Use last specialist in case of multiple
    else:
        # Orchestrator handled it alone
        actual_route = "orchestrator"
    
    return {
        "actual_route": actual_route,
        "all_agents": agents_visited
    }


async def main():
    """Main evaluation execution."""
    print("=" * 60)
    print("🧭 AGENT ROUTING EVALUATION - Travel Assistant")
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
    
    # Build graph (now requires an async Cosmos checkpointer)
    print("🔄 Building agent graph...")
    global graph
    checkpointer = await aget_checkpoint_saver()
    graph = build_agent_graph(checkpointer)
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
        description="Agent routing evaluation for multi-agent travel assistant"
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
        evaluators=[correct_routing],
        experiment_prefix="travel-routing",
        num_repetitions=1,
        max_concurrency=4,
        metadata={
            "version": "v1.0",
            "description": "Test orchestrator routing to specialist agents"
        }
    )
    
    print("\n" + "=" * 60)
    print("✅ EVALUATION COMPLETE")
    print("=" * 60)
    
    # Clean up MCP session
    print("\n🔄 Cleaning up resources...")
    from src.app.travel_agents import cleanup_persistent_session
    await cleanup_persistent_session()
    await close_async_cosmos_client()
    print("✅ Cleanup complete")


if __name__ == "__main__":
    asyncio.run(main())

"""
Tool Usage Evaluation Script for Travel Assistant

Tests if agents call the correct tools for different scenarios.

Usage:
    python tool_usage_evaluation.py
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
from evaluators.heuristic_evaluators import required_tools_called, tool_call_accuracy

# Ensure stdout/stderr use UTF-8 so emoji in prints don't crash on Windows,
# where the console defaults to cp1252 and raises UnicodeEncodeError on emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass




def load_dataset(dataset_path: str) -> list:
    """Load dataset from JSON file."""
    with open(dataset_path, 'r') as f:
        return json.load(f)


async def run_travel_agent_tools(inputs: dict) -> dict:
    """
    Track which tools are called during execution.
    
    Args:
        inputs: Dictionary containing the question
        
    Returns:
        Dictionary with tools_called list
    """
    question = inputs["question"]
    unique_id = f"{hash(question)}_{id(inputs)}_{os.urandom(4).hex()}"
    thread_id = f"tool_eval_{unique_id}"
    
    tools_called = []
    
    # Stream events to track tool calls
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
        # Track tool calls
        if event["event"] == "on_tool_start":
            tool_name = event.get("name", "")
            if tool_name and tool_name not in tools_called:
                tools_called.append(tool_name)
    
    return {
        "tools_called": tools_called
    }


async def main():
    """Main evaluation execution."""
    print("=" * 60)
    print("🔧 TOOL USAGE EVALUATION - Travel Assistant")
    print("=" * 60)
    
    # Load environment variables
    load_dotenv(override=True)
    os.environ["LANGCHAIN_TRACING_V2"] = "false"  # Disable tracing for faster evaluation
    
    # Paths
    eval_dir = Path(__file__).parent
    dataset_path = eval_dir / "datasets" / "tool_usage_dataset.json"
    
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
    dataset_name = "travel-assistant-tools"
    if client.has_dataset(dataset_name=dataset_name):
        print(f"🔄 Deleting existing dataset '{dataset_name}'...")
        dataset = client.read_dataset(dataset_name=dataset_name)
        client.delete_dataset(dataset_id=dataset.id)
    
    print(f"🔄 Creating dataset '{dataset_name}'...")
    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description="Tool usage evaluation for multi-agent travel assistant"
    )
    client.create_examples(dataset_id=dataset.id, examples=dataset_examples)
    print(f"✅ Dataset created with {len(dataset_examples)} examples")
    
    # Run evaluation
    print("\n" + "=" * 60)
    print("🚀 RUNNING EVALUATION")
    print("=" * 60)
    
    results = await client.aevaluate(
        run_travel_agent_tools,
        data=dataset_name,
        evaluators=[
            required_tools_called,
            tool_call_accuracy
        ],
        experiment_prefix="travel-tools",
        num_repetitions=1,
        max_concurrency=4,
        metadata={
            "version": "v1.0",
            "description": "Test correct tool calling patterns"
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

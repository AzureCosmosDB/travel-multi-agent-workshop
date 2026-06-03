# Travel Multi-Agent Workshop - Complete Solution

This is the complete implementation of the Travel Multi-Agent Workshop. Here you'll find a fully functional multi-agent travel assistant system with specialized AI agents that work together using Python, LangGraph, Azure OpenAI, and Azure Cosmos DB.

## Getting Started

This complete solution demonstrates the final result of the workshop with all modules implemented. You can deploy this directly to Azure or use it as a reference while working through the workshop exercises.

Deploy the complete solution 👉  **[Deploy to Azure](../README.md#deployment-instructions-for-complete-solution-02_completed)**

📖 **[User Guide](./USER_GUIDE.md)** — how to use the travel assistant, interact with agents, manage memories, and get the best results.

## Memory layer

Memory is provided by the **`azure-cosmos-agent-memory`** PyPI package (import path `azure.cosmos.agent_memory`), pinned in `python/src/app/requirements.txt`. The SDK partitions records by `(user_id, thread_id)` and writes them into three Cosmos DB containers — `memories_turns` (raw turns, TTL 30 days), `memories` (facts, episodics, procedurals — vector + full-text indexed at 1536 dims), and `memories_summaries` (thread and user summaries, composite-indexed by `(user_id, thread_id, version)`). All three containers are provisioned by Bicep (`infra/shared/cosmosdb.bicep`) so the runtime SDK and `seed_data.py` can write without any container-create round-trip. Every 10 chat turns a background auto-flush produces a thread summary plus extracted facts/episodics, and a `user_summary` is synthesized across threads. Memory prompts ship inside the SDK, so `preference_extraction.prompty`, `memory_conflict_resolution.prompty`, and `summarizer.prompty` have been removed from this repo.

## Project Structure

```
02_completed/
├── python/       # Fully implemented Python application
│   ├── data/     # Complete sample data with seed scripts
│   └── src/      # Complete application source code
├── frontend/     # Complete Angular web application
├── infra/        # Complete Azure infrastructure as code
└── mcp_server/   # Complete MCP server
```

This structure contains the complete, production-ready implementation of all workshop modules with full multi-agent functionality, memory systems, and Azure integrations.
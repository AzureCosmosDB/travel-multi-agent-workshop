"""Async singleton wrapper around azure.cosmos.agent_memory.aio.AsyncCosmosMemoryClient.

All workshop memory access (MCP, REST, agents) flows through `get_memory_client()`.
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

from azure.cosmos.agent_memory.aio import AsyncCosmosMemoryClient

load_dotenv(override=False)

_client: AsyncCosmosMemoryClient | None = None
_init_lock = asyncio.Lock()


def _get_required_env(name: str) -> str:
    value = os.environ[name]
    if not value:
        raise ValueError(f"{name} is set but empty")
    return value


async def _create_memory_client() -> AsyncCosmosMemoryClient:
    cosmos_endpoint = _get_required_env("COSMOSDB_ENDPOINT")
    cosmos_database = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    ai_foundry_endpoint = _get_required_env("AZURE_OPENAI_ENDPOINT")
    chat_deployment = (
        os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        or os.environ.get("OPENAI_CHAT_DEPLOYMENT_NAME")
        or "gpt-4o-mini"
    )
    embedding_deployment = (
        os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        or os.environ.get("OPENAI_EMBEDDING_DEPLOYMENT_NAME")
        or "text-embedding-3-small"
    )

    cosmos_key = os.environ.get("COSMOSDB_KEY") or None

    cosmos_container = os.environ.get("COSMOS_MEMORIES_CONTAINER") or "memories"
    cosmos_turns_container = os.environ.get("COSMOS_TURNS_CONTAINER") or "memories_turns"
    cosmos_summaries_container = (
        os.environ.get("COSMOS_SUMMARIES_CONTAINER") or "memories_summaries"
    )
    cosmos_counter_container = os.environ.get("COSMOS_COUNTER_CONTAINER") or "counter"

    client_kwargs = dict(
        cosmos_endpoint=cosmos_endpoint,
        cosmos_database=cosmos_database,
        cosmos_container=cosmos_container,
        cosmos_turns_container=cosmos_turns_container,
        cosmos_summaries_container=cosmos_summaries_container,
        cosmos_counter_container=cosmos_counter_container,
        ai_foundry_endpoint=ai_foundry_endpoint,
        chat_deployment_name=chat_deployment,
        embedding_deployment_name=embedding_deployment,
    )
    if cosmos_key:
        client_kwargs["cosmos_key"] = cosmos_key

    client = AsyncCosmosMemoryClient(**client_kwargs)
    await client.connect_cosmos()
    return client


async def get_memory_client() -> AsyncCosmosMemoryClient:
    """Return the process-wide connected Cosmos memory client."""
    global _client

    if _client is None:
        async with _init_lock:
            if _client is None:
                try:
                    _client = await _create_memory_client()
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"azure-cosmos-agent-memory failed to connect: {exc}"
                    ) from exc
    return _client

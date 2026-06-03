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
        or os.environ.get("OPENAI_CHAT_DEPLOYMENT_NAME")
        or "gpt-4o"
    )
    embedding_deployment = (
        os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
        or os.environ.get("OPENAI_EMBEDDING_DEPLOYMENT_NAME")
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
                try:
                    _client = _create_memory_client()
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        f"azure-cosmos-agent-memory failed to connect: {exc}"
                    ) from exc
    return _client


def get_memory_write_lock() -> threading.Lock:
    """Return the lock guarding the toolkit's shared in-process buffer."""
    return _memory_write_lock

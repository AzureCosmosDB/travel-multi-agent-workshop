from __future__ import annotations

import sys
import unittest
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from src.app.services.agent_memory import (  # noqa: E402
    MemoryNotFoundError,
    delete_memory_by_id,
)


class _FakeMemoryClient:
    def __init__(self, memories):
        self.memories = memories
        self.get_calls = []
        self.delete_calls = []

    async def get_memories(self, **kwargs):
        self.get_calls.append(kwargs)
        return self.memories

    async def delete_cosmos(self, memory_id, **kwargs):
        self.delete_calls.append((memory_id, kwargs))


class MemoryDeletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_uses_exact_lookup_and_record_type(self):
        client = _FakeMemoryClient(
            [{
                "id": "memory-1",
                "user_id": "tony",
                "thread_id": "session-1",
                "type": "fact",
            }]
        )

        await delete_memory_by_id(
            client,
            memory_id="memory-1",
            user_id="tony",
            thread_id="session-1",
        )

        self.assertEqual(
            client.get_calls,
            [{
                "memory_id": "memory-1",
                "user_id": "tony",
                "thread_id": "session-1",
                "include_superseded": True,
            }],
        )
        self.assertEqual(
            client.delete_calls,
            [(
                "memory-1",
                {
                    "user_id": "tony",
                    "thread_id": "session-1",
                    "memory_type": "fact",
                },
            )],
        )

    async def test_missing_or_mismatched_record_is_isolated_as_not_found(self):
        for memories in (
            [],
            [{
                "id": "different-memory",
                "user_id": "tony",
                "thread_id": "session-1",
                "type": "fact",
            }],
        ):
            client = _FakeMemoryClient(memories)
            with self.assertRaises(MemoryNotFoundError):
                await delete_memory_by_id(
                    client,
                    memory_id="requested-memory",
                    user_id="tony",
                    thread_id="session-1",
                )
            self.assertEqual(client.delete_calls, [])


if __name__ == "__main__":
    unittest.main()

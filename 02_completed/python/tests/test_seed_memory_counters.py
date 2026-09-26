from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PYTHON_ROOT = Path(__file__).resolve().parents[1]
SEED_DATA_PATH = PYTHON_ROOT / "data" / "seed_data.py"
FIXED_NOW = "2026-09-23T13:47:57+00:00"


def _load_seed_data_module():
    not_found_error = type("CosmosResourceNotFoundError", (Exception,), {})
    cosmos = types.ModuleType("azure.cosmos")
    cosmos.CosmosClient = object
    cosmos_exceptions = types.ModuleType("azure.cosmos.exceptions")
    cosmos_exceptions.CosmosHttpResponseError = type(
        "CosmosHttpResponseError", (Exception,), {}
    )
    cosmos_exceptions.CosmosResourceNotFoundError = not_found_error
    identity = types.ModuleType("azure.identity")
    identity.DefaultAzureCredential = object
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: None
    fake_modules = {
        "azure": types.ModuleType("azure"),
        "azure.cosmos": cosmos,
        "azure.cosmos.exceptions": cosmos_exceptions,
        "azure.identity": identity,
        "dotenv": dotenv,
    }
    spec = importlib.util.spec_from_file_location("seed_data_under_test", SEED_DATA_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, fake_modules):
        spec.loader.exec_module(module)
    return module, not_found_error


class _FakeCounterContainer:
    def __init__(self, not_found_error, items=None):
        self.not_found_error = not_found_error
        self.items = {
            key: dict(value)
            for key, value in (items or {}).items()
        }
        self.upserts = []

    def read_item(self, item, partition_key):
        key = (item, tuple(partition_key))
        if key not in self.items:
            raise self.not_found_error()
        return dict(self.items[key])

    def upsert_item(self, item):
        key = (item["id"], (item["user_id"], item["thread_id"]))
        self.items[key] = dict(item)
        self.upserts.append(dict(item))


class SeedMemoryCounterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_data, cls.not_found_error = _load_seed_data_module()

    @staticmethod
    def _turns():
        with open(PYTHON_ROOT / "data" / "turns.json", encoding="utf-8") as file:
            return json.load(file)

    def test_groups_stored_turns_by_user_and_thread(self):
        turns = self._turns() + [{"user_id": "tony"}, {"thread_id": "ignored"}]

        self.assertEqual(
            self.seed_data._count_turns_by_user_thread(turns),
            {
                ("steve", "session_steve_2025_001"): 14,
                ("tony", "session_tony_2025_001"): 14,
            },
        )

    def test_creates_exact_thread_and_user_counter_documents(self):
        container = _FakeCounterContainer(self.not_found_error)

        self.seed_data.seed_memory_counters(
            container,
            self._turns(),
            now=FIXED_NOW,
        )

        expected = []
        for user_id, thread_id in (
            ("steve", "session_steve_2025_001"),
            ("tony", "session_tony_2025_001"),
        ):
            expected.append({
                "id": f"thread:{user_id}:{thread_id}",
                "user_id": user_id,
                "thread_id": thread_id,
                "count": 14,
                "last_batch_lsn": None,
                "last_batch_old_count": 0,
                "created_at": FIXED_NOW,
                "updated_at": FIXED_NOW,
            })
        for user_id in ("steve", "tony"):
            expected.append({
                "id": f"user:{user_id}",
                "user_id": user_id,
                "thread_id": "__counters__",
                "count": 14,
                "last_batch_lsn": None,
                "last_batch_old_count": 0,
                "created_at": FIXED_NOW,
                "updated_at": FIXED_NOW,
            })
        self.assertCountEqual(container.upserts, expected)

    def test_rerun_is_idempotent(self):
        container = _FakeCounterContainer(self.not_found_error)
        turns = self._turns()
        self.seed_data.seed_memory_counters(container, turns, now=FIXED_NOW)
        first_items = dict(container.items)
        container.upserts.clear()

        self.seed_data.seed_memory_counters(container, turns, now="later")

        self.assertEqual(container.upserts, [])
        self.assertEqual(container.items, first_items)

    def test_preserves_higher_existing_counts_and_metadata(self):
        thread_id = "session_tony_2025_001"
        existing_thread = {
            "id": f"thread:tony:{thread_id}",
            "user_id": "tony",
            "thread_id": thread_id,
            "count": 20,
            "last_batch_lsn": "lsn-20",
            "last_batch_old_count": 15,
            "last_failure": {"message": "retry later"},
            "last_owner": "worker-7",
            "created_at": "2026-09-20T00:00:00+00:00",
            "updated_at": "2026-09-22T00:00:00+00:00",
        }
        existing_user = {
            **existing_thread,
            "id": "user:tony",
            "thread_id": "__counters__",
            "count": 25,
        }
        container = _FakeCounterContainer(
            self.not_found_error,
            {
                (existing_thread["id"], ("tony", thread_id)): existing_thread,
                (existing_user["id"], ("tony", "__counters__")): existing_user,
            },
        )

        self.seed_data.seed_memory_counters(
            container,
            [
                {"user_id": "tony", "thread_id": thread_id}
                for _ in range(14)
            ],
            now=FIXED_NOW,
        )

        self.assertEqual(container.upserts, [])
        self.assertEqual(
            container.items[(existing_thread["id"], ("tony", thread_id))],
            existing_thread,
        )
        self.assertEqual(
            container.items[(existing_user["id"], ("tony", "__counters__"))],
            existing_user,
        )

    def test_raises_lower_count_without_losing_toolkit_metadata(self):
        thread_id = "session_tony_2025_001"
        existing = {
            "id": f"thread:tony:{thread_id}",
            "user_id": "tony",
            "thread_id": thread_id,
            "count": 10,
            "last_batch_lsn": "lsn-10",
            "last_batch_old_count": 5,
            "last_failure": {"message": "retry later"},
            "last_owner": "worker-3",
            "created_at": "2026-09-20T00:00:00+00:00",
            "updated_at": "2026-09-21T00:00:00+00:00",
            "_etag": "system-field",
        }
        container = _FakeCounterContainer(
            self.not_found_error,
            {(existing["id"], ("tony", thread_id)): existing},
        )

        self.seed_data.seed_memory_counters(
            container,
            [
                {"user_id": "tony", "thread_id": thread_id}
                for _ in range(14)
            ],
            now=FIXED_NOW,
        )

        updated = container.items[(existing["id"], ("tony", thread_id))]
        self.assertEqual(updated["count"], 14)
        self.assertEqual(updated["created_at"], existing["created_at"])
        self.assertEqual(updated["last_batch_lsn"], existing["last_batch_lsn"])
        self.assertEqual(
            updated["last_batch_old_count"],
            existing["last_batch_old_count"],
        )
        self.assertEqual(updated["last_failure"], existing["last_failure"])
        self.assertEqual(updated["last_owner"], existing["last_owner"])
        self.assertEqual(updated["updated_at"], FIXED_NOW)
        self.assertNotIn("_etag", updated)


if __name__ == "__main__":
    unittest.main()

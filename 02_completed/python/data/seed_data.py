#!/usr/bin/env python3
"""
Travel Assistant Cosmos DB Seeding Script.

Seeds JSON data into existing Cosmos DB containers (created by ``azd up`` /
the Bicep templates under ``infra/``). This script does NOT create containers
and does NOT call any LLM — embeddings are pre-baked into the JSON files so
the seed is fully offline and deterministic.

Reads from ``data/``:
    - users.json                   → Users container
    - hotels_all_cities.json       → Places container (~490 hotels)
    - restaurants_all_cities.json  → Places container (~980 restaurants)
    - activities_all_cities.json   → Places container (~1,470 activities)
    - trips.json                   → Trips container
    - turns.json                   → memories_turns container
    - memories.json                → memories container (toolkit-shape records)

Run: ``python data/seed_data.py``
"""

import concurrent.futures
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure stdout/stderr use UTF-8 so emoji in logs/prints don't crash on Windows,
# where the console defaults to cp1252 and raises UnicodeEncodeError on emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import (
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()


# ============================================================================
# Configuration
# ============================================================================

COSMOS_ENDPOINT = os.getenv("COSMOSDB_ENDPOINT")
DATABASE_NAME = os.getenv("COSMOSDB_DATABASE_NAME", "TravelAssistant")

# Memory container names (env-overridable to match agent_memory.py / toolkit)
MEMORIES_CONTAINER = os.getenv("COSMOS_MEMORIES_CONTAINER", "memories")
TURNS_CONTAINER = os.getenv("COSMOS_TURNS_CONTAINER", "memories_turns")

# Concurrency / retry knobs (tuned for Cosmos serverless)
MAX_CONCURRENT_WORKERS = 5
BATCH_SIZE = 25
RATE_LIMIT_DELAY = 0.2
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 1.0

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR

print(f"📂 Data directory: {DATA_DIR}")
print(f"🌐 Cosmos endpoint: {COSMOS_ENDPOINT}")
print(f"🗄️  Database: {DATABASE_NAME}")


# ============================================================================
# Cosmos client + upload helpers (concurrent batches with 429 retry)
# ============================================================================

def get_cosmos_client() -> CosmosClient:
    """Return a Cosmos client authenticated with the local AAD identity."""
    return CosmosClient(COSMOS_ENDPOINT, DefaultAzureCredential())


def _upsert_with_retry(container, item: Dict[str, Any]) -> None:
    """Upsert one item, retrying 429 responses with exponential backoff."""
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            container.upsert_item(item)
            return
        except CosmosHttpResponseError as exc:
            if exc.status_code == 429 and attempt < RETRY_MAX_ATTEMPTS - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                print(
                    f"      ⏱️  Rate limited, retrying in {delay:.1f}s "
                    f"(attempt {attempt + 1}/{RETRY_MAX_ATTEMPTS})..."
                )
                time.sleep(delay)
                continue
            raise


def _upload_batch(container, batch: List[Dict[str, Any]]) -> tuple:
    success = 0
    errors: List[str] = []
    for item in batch:
        try:
            _upsert_with_retry(container, item)
            success += 1
        except Exception as exc:
            errors.append(f"id={item.get('id', '<?>')}: {exc}")
    return success, errors


def upload_items_concurrent(
    container,
    items: List[Dict[str, Any]],
    label: str,
) -> None:
    """Upload ``items`` to ``container`` in concurrent batches."""
    if not items:
        print(f"   ⚠️  No {label} to upload")
        return

    print(f"   🚀 Uploading {len(items)} {label}...")
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]

    total_success = 0
    all_errors: List[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WORKERS) as executor:
        futures = []
        for i, batch in enumerate(batches):
            if i > 0:
                time.sleep(RATE_LIMIT_DELAY * 2)  # gentle stagger for serverless
            futures.append(executor.submit(_upload_batch, container, batch))
        for future in concurrent.futures.as_completed(futures):
            ok, errs = future.result()
            total_success += ok
            all_errors.extend(errs)

    print(f"   ✅ {total_success}/{len(items)} {label} uploaded")
    if all_errors:
        print(f"   ❌ {len(all_errors)} errors")
        for err in all_errors[:3]:
            print(f"      • {err}")
        if len(all_errors) > 3:
            print(f"      • ... and {len(all_errors) - 3} more")


# ============================================================================
# JSON loading
# ============================================================================

def load_json_file(filename: str) -> List[Dict[str, Any]]:
    """Load a list-of-records JSON file from ``data/``."""
    path = DATA_DIR / filename
    if not path.exists():
        print(f"   ⚠️  File not found: {path}")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"   ✅ Loaded {len(data)} items from {filename}")
        return data
    except Exception as exc:
        print(f"   ❌ Error loading {filename}: {exc}")
        return []


# ============================================================================
# Seeders
# ============================================================================

def seed_users(container) -> None:
    print("\n👤 Seeding USERS...")
    upload_items_concurrent(container, load_json_file("users.json"), "users")


def seed_places(container) -> None:
    print("\n🏨 Seeding PLACES...")
    hotels = load_json_file("hotels_all_cities.json")
    restaurants = load_json_file("restaurants_all_cities.json")
    activities = load_json_file("activities_all_cities.json")
    all_places = hotels + restaurants + activities
    if not all_places:
        print("   ⚠️  No places to seed")
        return
    print(
        f"   📊 hotels={len(hotels)}, restaurants={len(restaurants)}, "
        f"activities={len(activities)}, total={len(all_places)}"
    )
    upload_items_concurrent(container, all_places, "places")


def seed_trips(container) -> None:
    print("\n✈️  Seeding TRIPS...")
    upload_items_concurrent(container, load_json_file("trips.json"), "trips")


def seed_memories(database) -> None:
    """Seed the memory containers — pure JSON-to-upsert, no transformations.

    All ids, content hashes, source-id cross-references, prompt metadata and
    embeddings are pre-baked into ``memories.json`` and ``turns.json``. The
    seed only needs to push records as-is.
    """
    print("\n🧠 Seeding MEMORIES (JSON → memories / memories_turns)...")

    try:
        memories_container = database.get_container_client(MEMORIES_CONTAINER)
        turns_container = database.get_container_client(TURNS_CONTAINER)
        memories_container.read()
        turns_container.read()
    except CosmosResourceNotFoundError as exc:
        print(
            f"   ⚠️  Memory containers missing "
            f"({MEMORIES_CONTAINER}, {TURNS_CONTAINER}). "
            "Run `azd up` (or deploy the Cosmos Bicep) before seeding."
        )
        print(f"      Details: {exc}")
        return

    turns = load_json_file("turns.json")
    if turns:
        upload_items_concurrent(turns_container, turns, "memory turns")

    memories = load_json_file("memories.json")
    if memories:
        upload_items_concurrent(memories_container, memories, "memories")


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    print("\n" + "=" * 70)
    print("🌍 TRAVEL ASSISTANT - COSMOS DB SEED")
    print("=" * 70)

    if not COSMOS_ENDPOINT:
        print("\n❌ Error: COSMOSDB_ENDPOINT not set in environment")
        print("   Please set COSMOSDB_ENDPOINT in your .env file")
        return

    client = get_cosmos_client()
    database = client.get_database_client(DATABASE_NAME)

    start = time.time()
    seed_users(database.get_container_client("Users"))
    seed_places(database.get_container_client("Places"))
    seed_trips(database.get_container_client("Trips"))
    seed_memories(database)
    print(f"\n✅ Seed complete in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()

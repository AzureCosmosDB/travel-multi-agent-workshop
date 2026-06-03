#!/usr/bin/env python3
"""
Travel Assistant Cosmos DB Seeding Script

Containers are provisioned by the Bicep templates in ``infra/`` — this script
does **not** create databases or containers, it only uploads pre-canned seed
data into containers that already exist.

This script:
1. Connects to an existing Cosmos DB database (created by Bicep).
2. Loads data from JSON files in the data/ directory and upserts them
   concurrently into the matching containers:
   - users.json                          → Users
   - hotels_all_cities.json              → Places
   - restaurants_all_cities.json         → Places
   - activities_all_cities.json          → Places
   - trips.json                          → Trips
   - turns.json                          → memories_turns
   - memories.json                       → memories
   (memories_summaries is created by Bicep but seeded at runtime by the SDK.)

Embeddings used by vector containers (Places, memories) are already baked into
the JSON files; this script never calls Azure OpenAI.

Run: python data/seed_data.py
"""

import json
import os
import concurrent.futures
import time
import random
from typing import List, Dict, Any
from pathlib import Path

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

COSMOS_ENDPOINT = os.getenv("COSMOSDB_ENDPOINT")
DATABASE_NAME = os.getenv("COSMOSDB_DATABASE_NAME", "TravelAssistant")

# Concurrency / retry settings (apply to all uploads)
MAX_CONCURRENT_WORKERS = 5  # Concurrent upload threads (tuned for serverless)
BATCH_SIZE = 25             # Items per upload batch
RATE_LIMIT_DELAY = 0.2      # Inter-batch delay to soften thundering herd
RETRY_MAX_ATTEMPTS = 5      # Max retries for 429 (TooManyRequests)
RETRY_BASE_DELAY = 1.0      # Base delay for exponential backoff (seconds)

# Data directory
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"

# Container names — created by Bicep, opened (not created) by this script.
CONTAINER_NAMES = [
    "Sessions",
    "Messages",
    "Places",
    "Trips",
    "Users",
    "ApiEvents",
    "Debug",
    "Checkpoints",
    "memories_turns",
    "memories",
    "memories_summaries",
]

print(f"📂 Data directory: {DATA_DIR}")
print(f"🌐 Cosmos endpoint: {COSMOS_ENDPOINT}")
print(f"🗄️  Database: {DATABASE_NAME}")


# ============================================================================
# Retry Mechanism for Rate Limiting
# ============================================================================

def retry_with_backoff(func):
    """Decorator to add exponential backoff retry for rate limit errors"""
    def wrapper(*args, **kwargs):
        for attempt in range(RETRY_MAX_ATTEMPTS):
            try:
                return func(*args, **kwargs)
            except CosmosHttpResponseError as e:
                if e.status_code == 429:  # TooManyRequests
                    if attempt < RETRY_MAX_ATTEMPTS - 1:
                        # Exponential backoff with jitter
                        delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                        print(f"      ⏱️  Rate limited, retrying in {delay:.1f}s (attempt {attempt + 1}/{RETRY_MAX_ATTEMPTS})...")
                        time.sleep(delay)
                        continue
                    else:
                        print(f"      ❌ Max retries exceeded for rate limit error")
                        raise
                else:
                    # Non-rate-limit error, don't retry
                    raise
            except Exception as e:
                # Other exceptions, don't retry
                raise
        return None
    return wrapper


def upsert_item_with_retry(container, item):
    """Upsert item with retry mechanism for rate limiting"""
    @retry_with_backoff
    def _upsert():
        return container.upsert_item(item)

    return _upsert()


# ============================================================================
# Concurrent Data Upload Functions
# ============================================================================

def upload_items_batch(container, items_batch: List[Dict[str, Any]]) -> tuple:
    """Upload a batch of items to container with retry mechanism"""
    success_count = 0
    error_count = 0
    errors = []

    for item in items_batch:
        try:
            upsert_item_with_retry(container, item)
            success_count += 1
        except CosmosHttpResponseError as e:
            error_count += 1
            if e.status_code == 429:
                errors.append(f"Item {item.get('id', 'unknown')}: Rate limit exceeded after retries")
            else:
                errors.append(f"Item {item.get('id', 'unknown')}: {str(e)}")
        except Exception as e:
            error_count += 1
            errors.append(f"Item {item.get('id', 'unknown')}: {str(e)}")

    return success_count, error_count, errors


def upload_items_concurrent(container, items: List[Dict[str, Any]], item_type: str) -> None:
    """Upload items to container using concurrent processing"""
    if not items:
        print(f"   ⚠️  No {item_type} to upload")
        return

    print(f"   🚀 Uploading {len(items)} {item_type} using concurrent processing...")

    # Split into batches
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]

    total_success = 0
    total_errors = 0
    all_errors = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WORKERS) as executor:
        # Submit all batches with small delays to avoid overwhelming serverless
        future_to_batch = {}
        for i, batch in enumerate(batches):
            # Add progressive delay to avoid thundering herd
            if i > 0:
                time.sleep(RATE_LIMIT_DELAY * 2)  # Increased delay for serverless
            future = executor.submit(upload_items_batch, container, batch)
            future_to_batch[future] = batch

        # Collect results
        for future in concurrent.futures.as_completed(future_to_batch):
            try:
                success_count, error_count, errors = future.result()
                total_success += success_count
                total_errors += error_count
                all_errors.extend(errors)

                # Progress update
                if total_success % 100 == 0:
                    print(f"      Progress: {total_success}/{len(items)} {item_type} uploaded")

            except Exception as e:
                batch = future_to_batch[future]
                total_errors += len(batch)
                all_errors.append(f"Batch upload failed: {str(e)}")

    # Final summary
    print(f"   ✅ Upload complete: {total_success}/{len(items)} {item_type} uploaded successfully")
    if total_errors > 0:
        print(f"   ❌ {total_errors} errors encountered")
        # Show first few errors
        for error in all_errors[:3]:
            print(f"      • {error}")
        if len(all_errors) > 3:
            print(f"      • ... and {len(all_errors) - 3} more errors")

# ============================================================================
# Cosmos DB Client Initialization
# ============================================================================

def get_cosmos_client() -> CosmosClient:
    """Initialize Cosmos DB client with Azure AD authentication"""
    credential = DefaultAzureCredential()
    return CosmosClient(COSMOS_ENDPOINT, credential)

# ============================================================================
# Data Loading Functions
# ============================================================================

def load_json_file(filename: str) -> List[Dict[str, Any]]:
    """Load data from JSON file"""
    file_path = DATA_DIR / filename

    if not file_path.exists():
        print(f"   ⚠️  File not found: {file_path}")
        return []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print(f"   ✅ Loaded {len(data)} items from {filename}")
        return data
    except Exception as e:
        print(f"   ❌ Error loading {filename}: {e}")
        return []


def seed_users(container):
    """Load users from users.json"""
    print("\n👤 Seeding USERS...")

    users = load_json_file("users.json")

    if not users:
        print("   ⚠️  No users to seed")
        return

    # Upload users concurrently (though users are typically few)
    upload_items_concurrent(container, users, "users")

    print(f"   ✅ Seeded {len(users)} users")


def seed_memories(containers: Dict[str, Any]):
    """Seed two of the three ``memories*`` containers used by ``azure.cosmos.agent_memory``.

    Loads pre-generated JSON files (with embeddings already computed) into the
    matching Cosmos container:

        turns.json    → ``memories_turns`` container (turn records, no embeddings)
        memories.json → ``memories`` container (fact / episodic / procedural, 1536-dim)

    The ``memories_summaries`` container is created (so the runtime SDK can write
    into it later) but is **not** pre-seeded — thread/user summaries are produced
    on the fly by the agent_memory pipeline as users chat.

    The JSON files are committed to source control with their embeddings already
    computed, so seeding is fully deterministic and does not require Azure OpenAI
    access at seed time.

    Tony and Steve are seeded with realistic conversations; Peter and Bruce are
    intentionally left empty as "blank slate" personas for the workshop modules.
    """
    print("\n🧠 Seeding MEMORIES (agent_memory containers)...")

    targets = [
        ("turns.json", "memories_turns", "turn records"),
        ("memories.json", "memories", "fact / episodic / procedural"),
    ]

    seeded_total = 0
    for filename, container_name, label in targets:
        container = containers.get(container_name)
        if container is None:
            print(f"   ⚠️  Container '{container_name}' missing — skipping {filename}")
            continue

        print(f"\n   📂 Loading {filename} → {container_name} ({label})")
        records = load_json_file(filename)
        if not records:
            print(f"      ⚠️  No records found in {filename}")
            continue

        upload_items_concurrent(container, records, label)
        seeded_total += len(records)

    print(f"\n   ✅ Seeded {seeded_total} memory records across 2 containers")
    print("   ℹ️  memories_summaries is intentionally left empty — populated by the runtime SDK")
    print("   ℹ️  peter and bruce intentionally left empty for workshop exercises")


def seed_places(container):
    """Load places from three separate JSON files and generate embeddings concurrently"""
    print("\n🏨 Seeding PLACES...")

    # Load all three files
    print("   📂 Loading data files...")
    hotels = load_json_file("hotels_all_cities.json")
    restaurants = load_json_file("restaurants_all_cities.json")
    activities = load_json_file("activities_all_cities.json")

    # Combine all places
    all_places = hotels + restaurants + activities

    if not all_places:
        print("   ⚠️  No places to seed")
        return

    # Display statistics
    print(f"\n   📊 Data loaded:")
    print(f"      • Hotels: {len(hotels)} (49 cities × 10 hotels = 490 expected)")
    print(f"      • Restaurants: {len(restaurants)} (49 cities × 20 restaurants = 980 expected)")
    print(f"      • Activities: {len(activities)} (49 cities × 30 activities = 1,470 expected)")
    print(f"      • Total places: {len(all_places)}")

    # Count by type for verification
    type_counts = {}
    for place in all_places:
        place_type = place.get("type", "unknown")
        type_counts[place_type] = type_counts.get(place_type, 0) + 1

    print(f"\n   📋 Breakdown by type:")
    for place_type, count in sorted(type_counts.items()):
        print(f"      • {place_type}: {count}")

    # Upload data concurrently
    upload_items_concurrent(container, all_places, "places")

    # Final summary
    print(f"\n   ✅ Seeding complete")
    print(f"      • Hotels: {len(hotels)}")
    print(f"      • Restaurants: {len(restaurants)}")
    print(f"      • Activities: {len(activities)}")
    print(f"      • Total: {len(all_places)} places")


def seed_trips(container):
    """Load trips from trips.json"""
    print("\n✈️  Seeding TRIPS...")

    trips = load_json_file("trips.json")

    if not trips:
        print("   ⚠️  No trips to seed")
        return

    # Upload trips concurrently
    upload_items_concurrent(container, trips, "trips")

    print(f"   ✅ Seeded {len(trips)} trips")


def seed_all_data(containers: Dict[str, Any]):
    """Seed all data from JSON files with concurrent processing"""
    print("\n" + "=" * 70)
    print("📝 DATA SEEDING (CONCURRENT MODE)")
    print("=" * 70)
    print(f"⚙️  Concurrency settings:")
    print(f"   • Max workers: {MAX_CONCURRENT_WORKERS} (optimized for serverless)")
    print(f"   • Batch size: {BATCH_SIZE}")
    print(f"   • Retry attempts: {RETRY_MAX_ATTEMPTS}")
    print(f"   • Retry base delay: {RETRY_BASE_DELAY}s")
    print("=" * 70)

    start_time = time.time()

    # Seed each container
    seed_users(containers["Users"])
    seed_places(containers["Places"])
    seed_trips(containers["Trips"])
    seed_memories(containers)

    end_time = time.time()
    total_time = end_time - start_time

    print("\n" + "=" * 70)
    print(f"✅ Data seeding complete in {total_time:.1f} seconds!")
    print(f"🚀 Performance improved with concurrent processing")
    print("=" * 70)


# ============================================================================
# Main
# ============================================================================

def main():
    """Main entry point"""

    print("\n" + "=" * 70)
    print("🌍 TRAVEL ASSISTANT - COSMOS DB SETUP")
    print("=" * 70)

    if not COSMOS_ENDPOINT:
        print("\n❌ Error: COSMOSDB_ENDPOINT not set in environment")
        print("   Please set COSMOSDB_ENDPOINT in your .env file")
        return

    # Initialize Cosmos client
    client = get_cosmos_client()

    database = client.get_database_client(DATABASE_NAME)
    containers = {
        name: database.get_container_client(name)
        for name in CONTAINER_NAMES
    }

    # Seed data from JSON files
    seed_all_data(containers)

    print("\n" + "=" * 70)
    print("🎉 ALL DONE!")
    print("=" * 70)
    print("\n📝 Next Steps:")
    print("   1. Verify containers in Azure Portal")
    print("   2. Check vector and full-text indexing policies")
    print("   3. Start MCP server: python -m mcp_server.mcp_http_server")
    print("   4. Start API server: uvicorn src.app.travel_agents_api:app --reload")
    print("   5. Test endpoints at http://localhost:8000/docs\n")


if __name__ == "__main__":
    main()

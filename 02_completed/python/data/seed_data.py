#!/usr/bin/env python3
"""
Travel Assistant Cosmos DB Seeding Script

This script:
1. Creates the Cosmos DB database (if it doesn't exist)
2. Creates all required containers with proper indexing policies
3. Loads data from JSON files in the data/ directory:
   - users.json (4 users)
   - memories.json (10 memories)
   - places.json (1,700 places across 35 cities)
   - trips.json (5 sample trips)

Container List:
- Sessions
- Messages (chat messages)
- Summaries (conversation summaries)
- Memories (user preferences - loaded from JSON)
- Places (hotels, restaurants, attractions - loaded from JSON)
- Trips (trip itineraries - loaded from JSON)
- Users (user profiles - loaded from JSON)
- ApiEvents (API call logs)
- Checkpoints (LangGraph state)
- Debug (chat completion logs)

Run: python src/seed_data_new.py
"""

import json
import os
import sys
import asyncio
import concurrent.futures
import time
import random
from typing import List, Dict, Any
from pathlib import Path

from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError, CosmosHttpResponseError
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

COSMOS_ENDPOINT = os.getenv("COSMOSDB_ENDPOINT")
COSMOS_KEY = os.getenv("COSMOS_KEY")
DATABASE_NAME = os.getenv("COSMOS_DB_DATABASE_NAME", "TravelAssistant")

# Azure OpenAI configuration
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")

# Vector search configuration
VECTOR_DIMENSIONS = 1024
VECTOR_INDEX_TYPE = "diskANN"
SIMILARITY_METRIC = "cosine"

# Full-text search configuration
FULL_TEXT_LOCALE = "en-us"

# Concurrency settings
MAX_CONCURRENT_WORKERS = 5  # Number of concurrent threads for data processing (reduced for serverless)
BATCH_SIZE = 25  # Items to process per batch
EMBEDDING_BATCH_SIZE = 5  # Concurrent embedding generations
RATE_LIMIT_DELAY = 0.2  # Delay between batches to avoid rate limiting (increased for serverless)
RETRY_MAX_ATTEMPTS = 5  # Maximum retry attempts for rate limit errors
RETRY_BASE_DELAY = 1.0  # Base delay for exponential backoff (seconds)

# Data directory
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"

print(f"📂 Data directory: {DATA_DIR}")
print(f"🌐 Cosmos endpoint: {COSMOS_ENDPOINT}")
print(f"🤖 Azure OpenAI endpoint: {AZURE_OPENAI_ENDPOINT}")
print(f"📊 Embedding model: {AZURE_OPENAI_EMBEDDING_DEPLOYMENT}")


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
# Azure OpenAI Client Initialization
# ============================================================================

def get_openai_client() -> AzureOpenAI:
    """Initialize Azure OpenAI client with Azure AD authentication"""
    credential = DefaultAzureCredential()

    def token_provider():
        return credential.get_token("https://cognitiveservices.azure.com/.default").token

    return AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token_provider=token_provider,
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    )

def generate_embedding(text: str) -> List[float]:
    """Generate embedding for given text using Azure OpenAI"""
    try:
        client = get_openai_client()
        response = client.embeddings.create(
            input=text,
            model=AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"⚠️ Warning: Could not generate embedding for text: {e}")
        # Return a dummy embedding of the correct dimension if embedding fails
        return [0.0] * VECTOR_DIMENSIONS


def generate_embeddings_batch(texts: List[str]) -> List[List[float]]:
    """Generate embeddings for multiple texts in a single API call"""
    try:
        client = get_openai_client()
        response = client.embeddings.create(
            input=texts,
            model=AZURE_OPENAI_EMBEDDING_DEPLOYMENT
        )
        return [data.embedding for data in response.data]
    except Exception as e:
        print(f"⚠️ Warning: Batch embedding generation failed: {e}")
        # Fallback to individual generation
        return [generate_embedding(text) for text in texts]


def generate_embeddings_concurrent(items: List[Dict[str, Any]], text_field: str) -> List[Dict[str, Any]]:
    """Generate embeddings for multiple items concurrently using batch processing"""
    print(f"   🔄 Generating embeddings for {len(items)} items using batch processing...")

    # Filter items that need embeddings
    items_needing_embeddings = [
        (idx, item) for idx, item in enumerate(items)
        if not item.get("embedding") or item["embedding"] == []
    ]

    if not items_needing_embeddings:
        print(f"   ✅ All items already have embeddings")
        return items

    print(f"   📊 {len(items_needing_embeddings)} items need embeddings")

    # Process in batches
    with concurrent.futures.ThreadPoolExecutor(max_workers=EMBEDDING_BATCH_SIZE) as executor:
        futures = []

        # Split into batches
        for i in range(0, len(items_needing_embeddings), BATCH_SIZE):
            batch = items_needing_embeddings[i:i + BATCH_SIZE]
            batch_texts = [item[1][text_field] for item in batch]

            future = executor.submit(generate_embeddings_batch, batch_texts)
            futures.append((future, batch))

            # Add small delay to avoid rate limiting
            if i > 0:
                time.sleep(RATE_LIMIT_DELAY)

        # Collect results
        completed_count = 0
        for future, batch in futures:
            try:
                embeddings = future.result(timeout=60)  # 60 second timeout

                # Apply embeddings to items
                for (idx, item), embedding in zip(batch, embeddings):
                    items[idx]["embedding"] = embedding
                    completed_count += 1

                # Progress update
                if completed_count % 50 == 0 or completed_count == len(items_needing_embeddings):
                    print(f"      Progress: {completed_count}/{len(items_needing_embeddings)} embeddings generated")

            except Exception as e:
                print(f"   ❌ Batch embedding failed: {e}")
                # Fallback to individual processing for this batch
                for idx, item in batch:
                    try:
                        items[idx]["embedding"] = generate_embedding(item[text_field])
                        completed_count += 1
                    except Exception as e2:
                        print(f"   ❌ Individual embedding failed for item {idx}: {e2}")

    print(f"   ✅ Generated {completed_count} embeddings")
    return items


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
# Container Definitions with Vector + Full-Text Indexing
# ============================================================================

CONTAINER_CONFIGS = {
    "Sessions": {
        "partition_key": ["/tenantId", "/userId", "/sessionId"],
        "hierarchical": True,
        "vector_search": False,
        "full_text_search": False,
        "description": "Conversation sessions"
    },
    "Messages": {
        "partition_key": ["/tenantId", "/userId", "/sessionId"],
        "hierarchical": True,
        "vector_search": True,
        "full_text_search": True,
        "vector_paths": ["/embedding"],
        "full_text_paths": ["/content", "/keywords"],
        "description": "Chat messages with embeddings"
    },
    "Summaries": {
        "partition_key": ["/tenantId", "/userId", "/sessionId"],
        "hierarchical": True,
        "vector_search": True,
        "full_text_search": True,
        "vector_paths": ["/embedding"],
        "full_text_paths": ["/text"],
        "description": "Conversation summaries with embeddings"
    },
    "Memories": {
        "partition_key": ["/tenantId", "/userId", "/memoryId"],
        "hierarchical": True,
        "vector_search": True,
        "full_text_search": True,
        "vector_paths": ["/embedding"],
        "full_text_paths": ["/text"],
        "description": "User memories (declarative, episodic, procedural)"
    },
    "Places": {
        "partition_key": "/geoScopeId",
        "hierarchical": False,
        "vector_search": True,
        "full_text_search": True,
        "vector_paths": ["/embedding"],
        "full_text_paths": ["/name", "/description", "/tags"],
        "description": "Places across cities (hotels, restaurants, attractions)"
    },
    "Trips": {
        "partition_key": ["/tenantId", "/userId", "/tripId"],
        "hierarchical": True,
        "vector_search": False,
        "full_text_search": False,
        "description": "Trip itineraries and plans"
    },
    "Users": {
        "partition_key": "/userId",
        "hierarchical": False,
        "vector_search": False,
        "full_text_search": False,
        "description": "User profiles"
    },
    "ApiEvents": {
        "partition_key": ["/tenantId", "/userId", "/sessionId"],
        "hierarchical": True,
        "vector_search": False,
        "full_text_search": False,
        "description": "External API call logs"
    },
    "Debug": {
        "partition_key": ["/tenantId", "/userId", "/sessionId"],
        "hierarchical": True,
        "vector_search": False,
        "full_text_search": False,
        "description": "Debug logs for chat completions with token usage and metadata"
    },
    "Checkpoints": {
        "partition_key": "/session_id",
        "hierarchical": False,
        "vector_search": False,
        "full_text_search": False,
        "description": "LangGraph checkpoints for state persistence"
    }
}


def create_container_with_indexing(
        database,
        container_name: str,
        config: Dict[str, Any]
) -> Any:
    """
    Create a Cosmos DB container with optional vector and full-text search indexing.
    
    Args:
        database: Cosmos database client
        container_name: Name of the container
        config: Container configuration dictionary
        
    Returns:
        Container client object
    """
    print(f"\n📦 Creating container: {container_name}")
    print(f"   Description: {config['description']}")

    # Build partition key
    if config["hierarchical"]:
        partition_key_paths = config["partition_key"]
        partition_key = PartitionKey(
            path=partition_key_paths,
            kind="MultiHash"
        )
        print(f"   Partition key: {partition_key_paths} (hierarchical)")
    else:
        partition_key = PartitionKey(path=config["partition_key"])
        print(f"   Partition key: {config['partition_key']}")

    # Build indexing policy
    indexing_policy = {
        "automatic": True,
        "indexingMode": "consistent",
        "includedPaths": [{"path": "/*"}],
        "excludedPaths": [{"path": "/\"_etag\"/?"}]
    }

    # Add vector embedding policies
    vector_embedding_policy = None
    if config.get("vector_search", False):
        print(f"   ✅ Vector search enabled (dimensions: {VECTOR_DIMENSIONS})")
        vector_paths = config.get("vector_paths", ["/embedding"])
        vector_embedding_policy = {
            "vectorEmbeddings": [
                {
                    "path": path,
                    "dataType": "float32",
                    "dimensions": VECTOR_DIMENSIONS,
                    "distanceFunction": SIMILARITY_METRIC
                }
                for path in vector_paths
            ]
        }

        # Add vector indexes
        indexing_policy["vectorIndexes"] = [
            {
                "path": path,
                "type": VECTOR_INDEX_TYPE
            }
            for path in vector_paths
        ]

    # Add full-text search policies
    full_text_policy = None
    if config.get("full_text_search", False):
        print(f"   ✅ Full-text search enabled (locale: {FULL_TEXT_LOCALE})")
        full_text_paths = config.get("full_text_paths", [])
        full_text_policy = {
            "defaultLanguage": "en-US",
            "fullTextPaths": [
                {
                    "path": path,
                    "language": "en-US"
                }
                for path in full_text_paths
            ]
        }
        indexing_policy["fullTextIndexes"] = [
            {
                "path": path,
                "language": FULL_TEXT_LOCALE
            }
            for path in full_text_paths
        ]

    # Create container
    try:
        container = database.create_container(
            id=container_name,
            partition_key=partition_key,
            indexing_policy=indexing_policy,
            vector_embedding_policy=vector_embedding_policy,
            full_text_policy=full_text_policy,
        )
        print(f"   ✅ Container created successfully")
        return container

    except CosmosResourceExistsError:
        print(f"   ⚠️  Container already exists, using existing container")
        return database.get_container_client(container_name)


# ============================================================================
# Database and Container Creation
# ============================================================================

def create_database_and_containers(client: CosmosClient) -> tuple:
    """Create database and all containers"""
    print("\n" + "=" * 70)
    print("🗄️  DATABASE SETUP")
    print("=" * 70)

    # Create database
    try:
        # Try to get existing database first
        database = client.get_database_client(DATABASE_NAME)
        print(f"✅ Using existing database: {DATABASE_NAME}")
    except CosmosResourceNotFoundError:
        # Only create if it doesn't exist
        database = client.create_database(id=DATABASE_NAME)
        print(f"✅ Created database: {DATABASE_NAME}")

    # Create all containers
    print("\n" + "=" * 70)
    print("📦 CONTAINER CREATION")
    print("=" * 70)

    containers = {}
    for container_name, config in CONTAINER_CONFIGS.items():
        container = create_container_with_indexing(database, container_name, config)
        containers[container_name] = container

    print(f"\n✅ Created/verified {len(containers)} containers")
    return database, containers


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


def seed_memories(container):
    """Load memories from memories.json and generate embeddings concurrently"""
    print("\n🧠 Seeding MEMORIES...")

    memories = load_json_file("memories.json")

    if not memories:
        print("   ⚠️  No memories to seed")
        return

    # # Generate embeddings concurrently
    # memories = generate_embeddings_concurrent(memories, "text")

    # Upload data concurrently
    upload_items_concurrent(container, memories, "memories")

    print(f"   ✅ Seeded {len(memories)} memories with embeddings")


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

    # print(f"\n   � Processing {len(all_places)} places with concurrent embedding generation...")
    # print("      💡 Using batch processing and concurrent uploads for optimal performance")
    #
    # # Generate embeddings concurrently using batch processing
    # start_time = time.time()
    # all_places = generate_embeddings_concurrent(all_places, "description")

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
    print(f"   • Embedding batch size: {EMBEDDING_BATCH_SIZE}")
    print(f"   • Retry attempts: {RETRY_MAX_ATTEMPTS}")
    print(f"   • Retry base delay: {RETRY_BASE_DELAY}s")
    print("=" * 70)

    start_time = time.time()

    # Seed each container
    seed_users(containers["Users"])
    seed_memories(containers["Memories"])
    seed_places(containers["Places"])
    seed_trips(containers["Trips"])

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
        for name in CONTAINER_CONFIGS.keys()
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

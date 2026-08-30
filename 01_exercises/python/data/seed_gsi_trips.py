#!/usr/bin/env python3
"""
GSI Trip Data Generator and Seeder

Generates 25,000 deterministic trip documents and seeds them into the provisioned
Cosmos DB account. After seeding, scales down throughput to reduce costs while
preserving the physical partition layout.

Trip distribution: 50 tenants x 10 users x 50 trips = 25,000
Destinations cycle through 50 cities for even partition distribution.

Run: python data/seed_gsi_trips.py
"""

import os
import sys
import time
import random
import concurrent.futures
from datetime import datetime, timedelta
from typing import List, Dict, Any
from urllib.parse import urlparse

# Ensure stdout/stderr use UTF-8 so emoji in logs/prints don't crash on Windows,
# where the console defaults to cp1252 and raises UnicodeEncodeError on emoji.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import requests as http_requests
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# Configuration
# ============================================================================

COSMOS_ENDPOINT = os.getenv("COSMOSDB_ENDPOINT")
DATABASE_NAME = os.getenv("COSMOSDB_DATABASE_NAME", "TravelAssistant")
TRIPS_CONTAINER_NAME = "Trips"

# ARM management plane config (for throughput scaling)
SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID")
RESOURCE_GROUP = os.getenv("RG_NAME")
ARM_API_VERSION = "2024-12-01-preview"

def _get_account_name() -> str:
    """Extract Cosmos account name from the endpoint URL."""
    if not COSMOS_ENDPOINT:
        return ""
    host = urlparse(COSMOS_ENDPOINT).hostname or ""
    return host.split(".")[0]

# Throughput targets (after seeding)
FINAL_DATABASE_THROUGHPUT = 5000
FINAL_TRIPS_THROUGHPUT = 10000

# Concurrency settings (higher than serverless since provisioned)
MAX_CONCURRENT_WORKERS = 10
BATCH_SIZE = 50
RATE_LIMIT_DELAY = 0.1
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 1.0

# ============================================================================
# Trip Generator — Fully Deterministic
# ============================================================================

NUM_TENANTS = 50
USERS_PER_TENANT = 10
TRIPS_PER_USER = 50
TOTAL_TRIPS = NUM_TENANTS * USERS_PER_TENANT * TRIPS_PER_USER  # 25,000

DESTINATIONS = [
    "Paris, France", "London, UK", "Tokyo, Japan", "New York, USA",
    "Barcelona, Spain", "Rome, Italy", "Sydney, Australia", "Dubai, UAE",
    "Bangkok, Thailand", "Amsterdam, Netherlands", "Berlin, Germany",
    "Prague, Czech Republic", "Vienna, Austria", "Istanbul, Turkey",
    "Singapore", "Hong Kong, China", "Seoul, South Korea",
    "Mexico City, Mexico", "Buenos Aires, Argentina", "Cape Town, South Africa",
    "Mumbai, India", "Cairo, Egypt", "Lisbon, Portugal", "Dublin, Ireland",
    "Stockholm, Sweden", "Copenhagen, Denmark", "Oslo, Norway",
    "Helsinki, Finland", "Athens, Greece", "Zurich, Switzerland",
    "Brussels, Belgium", "Warsaw, Poland", "Budapest, Hungary",
    "Bucharest, Romania", "Marrakech, Morocco", "Nairobi, Kenya",
    "Lima, Peru", "Bogota, Colombia", "Santiago, Chile", "Havana, Cuba",
    "Reykjavik, Iceland", "Edinburgh, UK", "Venice, Italy",
    "Florence, Italy", "Nice, France", "Munich, Germany",
    "Kyoto, Japan", "Bali, Indonesia", "Maldives",
    "Queenstown, New Zealand",
]

STATUSES = ["confirmed", "planning", "completed"]

ACTIVITIES = [
    "City walking tour", "Museum visit", "Local food tasting",
    "Boat cruise", "Hiking excursion", "Shopping at markets",
    "Beach relaxation", "Temple visit", "Cooking class",
    "Wine tasting", "Snorkeling", "Photography walk",
    "Spa day", "Historical site tour", "Street art tour",
    "Sunset viewpoint", "Kayaking", "Cycling tour",
    "Night market visit", "Waterfall hike",
]


def _generate_days(start_date: datetime, duration: int, global_idx: int) -> List[Dict[str, Any]]:
    """Generate a deterministic days array with activities for each day."""
    days = []
    for day_num in range(duration):
        day_date = start_date + timedelta(days=day_num)
        # Each day gets 2-4 activities, deterministically chosen
        num_activities = (global_idx + day_num) % 3 + 2
        day_activities = []
        for a in range(num_activities):
            act_idx = (global_idx * 7 + day_num * 3 + a) % len(ACTIVITIES)
            day_activities.append({
                "time": f"{8 + a * 3:02d}:00",
                "activity": ACTIVITIES[act_idx],
                "location": f"Location {(global_idx + day_num + a) % 20 + 1}",
                "notes": f"Booked for {(global_idx + a) % 4 + 1} guests. Confirmation #{global_idx * 100 + day_num * 10 + a}",
            })
        days.append({
            "dayNumber": day_num + 1,
            "date": day_date.strftime("%Y-%m-%d"),
            "activities": day_activities,
        })
    return days


def generate_trips() -> List[Dict[str, Any]]:
    """Generate 25,000 deterministic trip documents.

    Uses a fixed formula (no randomness) so every run produces identical output.
    """
    trips = []
    base_date = datetime(2025, 1, 1)

    for t_idx in range(NUM_TENANTS):
        tenant_id = f"tenant_{t_idx + 1:03d}"
        for u_idx in range(USERS_PER_TENANT):
            user_id = f"user_{u_idx + 1:03d}"
            for trip_idx in range(TRIPS_PER_USER):
                global_idx = (
                    t_idx * USERS_PER_TENANT * TRIPS_PER_USER
                    + u_idx * TRIPS_PER_USER
                    + trip_idx
                )

                destination = DESTINATIONS[global_idx % len(DESTINATIONS)]
                duration = (global_idx % 6) + 2  # 2-7 days
                start_date = base_date + timedelta(days=(global_idx % 365))
                end_date = start_date + timedelta(days=duration - 1)
                status = STATUSES[global_idx % len(STATUSES)]

                trip_id = f"trip_{tenant_id}_{user_id}_{trip_idx + 1:03d}"

                trips.append({
                    "id": trip_id,
                    "tripId": trip_id,
                    "userId": user_id,
                    "tenantId": tenant_id,
                    "destination": destination,
                    "startDate": start_date.strftime("%Y-%m-%d"),
                    "endDate": end_date.strftime("%Y-%m-%d"),
                    "tripDuration": duration,
                    "status": status,
                    "days": _generate_days(start_date, duration, global_idx),
                    "createdAt": (
                        base_date + timedelta(days=global_idx % 300)
                    ).isoformat() + "Z",
                })

    return trips


# ============================================================================
# Upload with Retry
# ============================================================================


def upload_item_with_retry(container, item: Dict[str, Any]) -> bool:
    """Upsert a single item with exponential backoff retry."""
    for attempt in range(RETRY_MAX_ATTEMPTS):
        try:
            container.upsert_item(item)
            return True
        except CosmosHttpResponseError as e:
            if e.status_code == 429 and attempt < RETRY_MAX_ATTEMPTS - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(delay)
            else:
                raise
    return False


def upload_batch(container, batch: List[Dict[str, Any]]):
    """Upload a batch of items, returning (success_count, error_count)."""
    success = 0
    errors = 0
    for item in batch:
        try:
            upload_item_with_retry(container, item)
            success += 1
        except Exception:
            errors += 1
    return success, errors


def upload_items_concurrent(container, items: List[Dict[str, Any]], label: str):
    """Upload items using concurrent workers."""
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    total_success = 0
    total_errors = 0

    print(f"   🚀 Uploading {len(items):,} {label} in {len(batches)} batches...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WORKERS) as executor:
        futures = {}
        for i, batch in enumerate(batches):
            if i > 0:
                time.sleep(RATE_LIMIT_DELAY)
            futures[executor.submit(upload_batch, container, batch)] = i

        for future in concurrent.futures.as_completed(futures):
            s, e = future.result()
            total_success += s
            total_errors += e
            if total_success % 1000 == 0 and total_success > 0:
                print(f"      Progress: {total_success:,}/{len(items):,} uploaded")

    print(f"   ✅ Upload complete: {total_success:,}/{len(items):,} ({total_errors} errors)")


# ============================================================================
# Throughput Management
# ============================================================================


def _get_arm_token(credential) -> str:
    """Get an ARM management plane token."""
    token = credential.get_token("https://management.azure.com/.default")
    return token.token


def scale_database_throughput(credential, throughput: int):
    """Scale the shared database throughput via ARM REST API."""
    account_name = _get_account_name()
    if not all([SUBSCRIPTION_ID, RESOURCE_GROUP, account_name]):
        print("   ⚠️  Missing ARM config (AZURE_SUBSCRIPTION_ID, RG_NAME, or account name) — skipping database scale")
        return

    url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.DocumentDB/databaseAccounts/{account_name}"
        f"/sqlDatabases/{DATABASE_NAME}/throughputSettings/default"
        f"?api-version={ARM_API_VERSION}"
    )
    token = _get_arm_token(credential)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Read current throughput
    resp = http_requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"   ⚠️  Could not read database throughput: {resp.status_code} {resp.text[:200]}")
        return

    data = resp.json()
    # Handle both autoscale and manual throughput
    resource = data.get("properties", {}).get("resource", {})
    current = resource.get("throughput") or resource.get("autoscaleSettings", {}).get("maxThroughput", 0)
    if current == throughput:
        print(f"   ℹ️  Database throughput already at {throughput:,} RU/s")
        return

    print(f"   📉 Scaling database: {current:,} → {throughput:,} RU/s...")
    body = {
        "properties": {
            "resource": {
                "throughput": throughput
            }
        }
    }
    resp = http_requests.put(url, headers=headers, json=body)
    if resp.status_code in (200, 202):
        print(f"   ✅ Database throughput set to {throughput:,} RU/s")
    else:
        print(f"   ⚠️  Could not scale database throughput: {resp.status_code} {resp.text[:200]}")


def scale_container_throughput(credential, container_name: str, throughput: int):
    """Scale a container's dedicated throughput via ARM REST API."""
    account_name = _get_account_name()
    if not all([SUBSCRIPTION_ID, RESOURCE_GROUP, account_name]):
        print(f"   ⚠️  Missing ARM config — skipping {container_name} scale")
        return

    url = (
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.DocumentDB/databaseAccounts/{account_name}"
        f"/sqlDatabases/{DATABASE_NAME}/containers/{container_name}/throughputSettings/default"
        f"?api-version={ARM_API_VERSION}"
    )
    token = _get_arm_token(credential)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Read current throughput
    resp = http_requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"   ⚠️  Could not read {container_name} throughput: {resp.status_code} {resp.text[:200]}")
        return

    data = resp.json()
    resource = data.get("properties", {}).get("resource", {})
    current = resource.get("throughput") or resource.get("autoscaleSettings", {}).get("maxThroughput", 0)
    if current == throughput:
        print(f"   ℹ️  {container_name} throughput already at {throughput:,} RU/s")
        return

    print(f"   📉 Scaling {container_name}: {current:,} → {throughput:,} RU/s...")
    body = {
        "properties": {
            "resource": {
                "throughput": throughput
            }
        }
    }
    resp = http_requests.put(url, headers=headers, json=body)
    if resp.status_code in (200, 202):
        print(f"   ✅ {container_name} throughput set to {throughput:,} RU/s")
    else:
        print(f"   ⚠️  Could not scale {container_name} throughput: {resp.status_code} {resp.text[:200]}")


# ============================================================================
# Main
# ============================================================================


def main():
    if not COSMOS_ENDPOINT:
        print("❌ COSMOSDB_ENDPOINT not set")
        sys.exit(1)

    print("=" * 70)
    print("🔧 GSI TRIP SEEDER — Provisioned Cosmos DB Account")
    print("=" * 70)
    print(f"   Endpoint:     {COSMOS_ENDPOINT}")
    print(f"   Database:     {DATABASE_NAME}")
    print(f"   Container:    {TRIPS_CONTAINER_NAME}")
    print(f"   Total trips:  {TOTAL_TRIPS:,}")
    print(f"   Workers:      {MAX_CONCURRENT_WORKERS}")
    print(f"   Batch size:   {BATCH_SIZE}")
    print("=" * 70)

    # Connect
    credential = DefaultAzureCredential()
    client = CosmosClient(COSMOS_ENDPOINT, credential)
    db = client.get_database_client(DATABASE_NAME)
    container = db.get_container_client(TRIPS_CONTAINER_NAME)

    # Generate trips
    print("\n📝 Generating trip data...")
    start = time.time()
    trips = generate_trips()
    gen_time = time.time() - start
    print(f"   ✅ Generated {len(trips):,} trips in {gen_time:.1f}s")

    # Verify distribution
    dest_counts: Dict[str, int] = {}
    tenant_counts: Dict[str, int] = {}
    for t in trips:
        dest_counts[t["destination"]] = dest_counts.get(t["destination"], 0) + 1
        tenant_counts[t["tenantId"]] = tenant_counts.get(t["tenantId"], 0) + 1
    print(f"   📊 Destinations: {len(dest_counts)} unique")
    print(f"   📊 Tenants: {len(tenant_counts)} unique")
    print(f"   📊 Trips per tenant: {USERS_PER_TENANT * TRIPS_PER_USER}")

    # Seed trips
    print("\n✈️  Seeding trips...")
    start = time.time()
    upload_items_concurrent(container, trips, "GSI trips")
    seed_time = time.time() - start
    print(f"   ⏱️  Seeding took {seed_time:.1f}s")

    # Scale down throughput via ARM management plane
    print("\n📉 Scaling down throughput...")
    scale_container_throughput(credential, TRIPS_CONTAINER_NAME, FINAL_TRIPS_THROUGHPUT)
    scale_database_throughput(credential, FINAL_DATABASE_THROUGHPUT)

    print("\n" + "=" * 70)
    print("✅ GSI trip seeding complete!")
    print(f"   • {len(trips):,} trips seeded across {len(tenant_counts)} tenants")
    print(f"   • Trips throughput scaled to {FINAL_TRIPS_THROUGHPUT} RU/s")
    print(f"   • Database throughput scaled to {FINAL_DATABASE_THROUGHPUT} RU/s")
    print(f"   • Physical partitions preserved at lower throughput")
    print("=" * 70)


if __name__ == "__main__":
    main()

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


def _rebase_turn_times(items: List[Dict[str, Any]], window_minutes: int = 120) -> None:
    """Spread OptimizationTurns timestamps uniformly across the last ``window_minutes``
    (ending now), in place. The seed JSON bakes fixed historical dates, which make the
    analytics report's time-series charts look stale/bunched on every deploy; re-basing
    to 'now' at seed time keeps them recent and dense. Timestamps only — turn content is
    untouched, and every KPI/cost is time-independent."""
    now = int(time.time())
    start = now - window_minutes * 60
    for it in items:
        e = random.randint(start, now)
        it["turn_epoch"] = e
        it["timeStamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(e))


def seed_conversations(database) -> None:
    """Seed the pre-baked generated data — conversation history + analytics signal.

    These are captured once from a live deployment by ``export_conversations.py`` so
    attendees/demo users get a fully-populated app + analytics with **no LLM**:

        sessions.json           -> Sessions
        messages.json           -> Messages
        debug.json              -> Debug (02_completed deep per-turn telemetry)
        optimization_turns.json -> OptimizationTurns (derived from Debug; analytics)

    ``Debug`` / ``OptimizationTurns`` only exist when the analytics infra is deployed
    (deployAnalytics=true); missing containers are skipped with a note.

    Node-grain (``NodeExecutions``, feeding the agent scorecard) is reconstructed from the
    seeded OptimizationTurns — see ``seed_node_executions`` — so the scorecard has data offline.
    """
    print("\n💬 Seeding CONVERSATIONS + ANALYTICS SIGNAL (offline, no LLM)...")
    opt_turns: List[Dict[str, Any]] = []
    for filename, container_name, label in (
        ("sessions.json", "Sessions", "sessions"),
        ("messages.json", "Messages", "messages"),
        ("debug.json", "Debug", "debug turn logs"),
        ("optimization_turns.json", "OptimizationTurns", "optimization turns"),
        ("optimization_policies.json", "OptimizationPolicies", "optimization policies"),
    ):
        items = load_json_file(filename)
        if not items:
            continue
        if filename == "optimization_turns.json":
            _rebase_turn_times(items)  # keep the report's time charts recent on every seed
            opt_turns = items
        try:
            container = database.get_container_client(container_name)
            container.read()
        except CosmosResourceNotFoundError:
            print(f"   ⚠️  Container '{container_name}' not found — skipping {label} "
                  "(deploy analytics infra to seed it).")
            continue
        upload_items_concurrent(container, items, label)

    # Reconstruct + seed per-agent node-grain from the same turns (agent scorecard signal).
    seed_node_executions(database, opt_turns)


# ============================================================================
# Node-grain reconstruction (agent scorecard signal)
# ============================================================================
# The live app captures TRUE per-node token usage (travel_agents_api.py -> NodeExecutions),
# but the committed OptimizationTurns seed predates that capture and stores only per-TURN
# totals. To give the agent scorecard realistic data offline, we reconstruct node-grain from
# each turn's agent_path: the turn's REAL input/output/cached totals are split across its
# nodes by a per-agent profile so the node sums reconcile EXACTLY to the captured turn. The
# totals are measured; only the per-node split is modeled — real traffic supersedes this with
# the true split the app records at runtime.

NODE_EXECUTIONS_CONTAINER = "NodeExecutions"

# (input_weight, output_weight) per agent. Output weights are the mean output tokens from the
# sanctioned node-grain distribution in engine/simulation/traffic.py (TOKEN_PROFILE); input
# weights model each node's share of the turn's context (the itinerary node carries the most).
_NODE_PROFILE = {
    "supervisor": (1.0, 179.0),
    "find_places": (1.1, 463.0),
    "create_or_update_itinerary": (1.4, 2100.0),
}
_DEFAULT_NODE_PROFILE = (1.0, 300.0)


def _split_int(total: Any, weights: List[float]) -> List[int]:
    """Split integer ``total`` across ``weights`` proportionally and EXACTLY (residual to last)."""
    total = int(total or 0)
    wsum = sum(weights) or 1.0
    parts = [int(total * w / wsum) for w in weights]
    if parts:
        parts[-1] += total - sum(parts)  # reconcile rounding so sum(parts) == total
    return parts


def build_node_execution_docs(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One NodeExecutions doc per turn holding the reconstructed per-agent executions.

    Reconciles exactly to each turn's captured input/output/cached tokens (see note above).
    Shape matches services/node_executions.py::store_node_executions so the app/scorecard read it.
    """
    docs: List[Dict[str, Any]] = []
    for t in turns:
        agents = [a.strip() for a in str(t.get("agent_path") or "").split(",") if a.strip()]
        if not agents:
            agents = ["supervisor"]  # every turn runs through the supervisor at minimum
        in_w = [_NODE_PROFILE.get(a, _DEFAULT_NODE_PROFILE)[0] for a in agents]
        out_w = [_NODE_PROFILE.get(a, _DEFAULT_NODE_PROFILE)[1] for a in agents]
        ins = _split_int(t.get("input_tokens"), in_w)
        outs = _split_int(t.get("output_tokens"), out_w)
        cached = _split_int(t.get("cached_tokens"), in_w)
        dep = t.get("model_deployment") or t.get("model_name") or "gpt-5.1"
        name = t.get("model_name") or dep
        nodes = [{
            "seq": i, "agent": a, "model_deployment": dep, "model_name": name,
            "input_tokens": ins[i], "output_tokens": outs[i], "cached_tokens": cached[i],
            "tool_calls": 0, "recall_used": False,
        } for i, a in enumerate(agents)]
        turn_id = t.get("id") or f"{t.get('sessionId')}:{t.get('turn_epoch')}"
        docs.append({
            "id": f"nodeexec::{turn_id}",
            "tenantId": t.get("tenantId", ""), "userId": t.get("userId", ""),
            "sessionId": t.get("sessionId", ""), "turnId": turn_id, "debugLogId": None,
            "nodeExecutions": nodes, "nodeCount": len(nodes),
            "timeStamp": t.get("timeStamp"), "turn_epoch": t.get("turn_epoch"),
        })
    return docs


def seed_node_executions(database, turns: List[Dict[str, Any]]) -> None:
    """Reconstruct + seed per-agent node-grain into the NodeExecutions container.

    Self-provisions the container (like services/node_executions.py) so it works even where
    the analytics Bicep hasn't (re)deployed it yet. No-op when there are no turns to seed.
    """
    print("\n🧩 Seeding NODE EXECUTIONS (agent scorecard signal, reconstructed offline)...")
    docs = build_node_execution_docs(turns)
    if not docs:
        print("   ⚠️  No node executions to seed (OptimizationTurns empty/absent)")
        return
    from azure.cosmos import PartitionKey
    try:
        container = database.create_container_if_not_exists(
            id=NODE_EXECUTIONS_CONTAINER,
            partition_key=PartitionKey(path=["/tenantId", "/userId", "/sessionId"], kind="MultiHash"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"   ⚠️  Could not ensure NodeExecutions container: {exc}")
        return
    total_nodes = sum(d["nodeCount"] for d in docs)
    print(f"   📊 {len(docs)} turns -> {total_nodes} node executions (reconciled to turn totals)")
    upload_items_concurrent(container, docs, "node-execution turns")


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
    seed_conversations(database)
    print(f"\n✅ Seed complete in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()

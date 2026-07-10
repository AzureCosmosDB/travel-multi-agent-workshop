"""
Traffic simulator — drives a realistic, continuous stream of optimization turns
into Cosmos so you can watch the near-real-time analytics story: turns land in
Cosmos (transactional) -> mirror to Fabric -> Power BI / Console update live.

The travel app is one-user-at-a-time, which makes "watch the dashboard move"
hard to show live. This simulator solves that for a demo: it writes turns (and
occasional confirmed trips) at a controllable rate with a realistic tier mix, so
the dashboards visibly change as it runs.

Two modes:
  --mode direct  (default): write OptimizationTurns docs straight to Cosmos.
                  Fast, no LLM cost, controllable rate. Best for the live demo.
  --mode app:     drive the real completion endpoint (real agent turns).
                  Realistic but slower and incurs model cost.

Usage (repo root, Cosmos access via DefaultAzureCredential):
  python analytics/traffic_simulator.py --tenant DemoLive --rate 60 --minutes 10
  python analytics/traffic_simulator.py --tenant DemoLive --forever --rate 120
"""
from __future__ import annotations

import argparse
import os
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / "02_completed" / "python" / ".env")

# Realistic tier mix + per-tier token/model profile (matches observed baselines).
# weight = share of turns; in/out = (min,max) token ranges; model = deployment.
TIERS = [
    {"tier": "trivial", "weight": 0.48, "deployment": "gpt-5-nano",
     "model": "gpt-5-nano-2025-08-07", "in": (2800, 3600), "out": (250, 520)},
    {"tier": "routine", "weight": 0.40, "deployment": "gpt-4.1-mini",
     "model": "gpt-4.1-mini-2025-04-14", "in": (6000, 16000), "out": (200, 450)},
    {"tier": "complex", "weight": 0.12, "deployment": "gpt-5.1",
     "model": "gpt-5.1-2025-11-13", "in": (28000, 33000), "out": (1400, 1900)},
]
CITIES = ["Amsterdam", "Paris", "Tokyo", "Rome", "Barcelona", "London", "New York"]


def _pick_tier() -> dict:
    r = random.random()
    cum = 0.0
    for t in TIERS:
        cum += t["weight"]
        if r <= cum:
            return t
    return TIERS[-1]


def _turn_doc(tenant: str, user: str, session: str, tier: dict) -> dict:
    it = random.randint(*tier["in"])
    ot = random.randint(*tier["out"])
    return {
        "id": str(uuid.uuid4()),
        "type": "optimization_turn",
        "tenantId": tenant, "userId": user, "sessionId": session,
        "model_tier": tier["tier"], "model_deployment": tier["deployment"],
        "model_name": tier["model"],
        "input_tokens": it, "output_tokens": ot, "total_tokens": it + ot,
        "cached_tokens": int(it * random.uniform(0.6, 0.9)),
        "timeStamp": datetime.now(timezone.utc).isoformat(),
    }


def _trip_doc(tenant: str, user: str) -> dict:
    trip_id = str(uuid.uuid4())
    return {
        "id": trip_id,
        "tenantId": tenant, "userId": user, "tripId": trip_id,
        "destination": random.choice(CITIES),
        "status": "confirmed",
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def run_direct(args) -> None:
    endpoint = os.environ["COSMOSDB_ENDPOINT"]
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)
    turns = db.get_container_client("OptimizationTurns")
    trips = db.get_container_client("Trips")

    interval = 60.0 / max(args.rate, 1)
    deadline = None if args.forever else time.monotonic() + args.minutes * 60
    print(f"[simulator] tenant={args.tenant} rate={args.rate}/min "
          f"mode=direct db={db_name} {'(forever)' if args.forever else f'for {args.minutes} min'}")

    n_turns = n_trips = 0
    users = [f"demo-user-{i}" for i in range(1, args.users + 1)]
    sessions = {u: f"sess-{uuid.uuid4().hex[:8]}" for u in users}
    try:
        while args.forever or time.monotonic() < deadline:
            user = random.choice(users)
            # occasionally rotate a user's session (new conversation)
            if random.random() < 0.05:
                sessions[user] = f"sess-{uuid.uuid4().hex[:8]}"
            tier = _pick_tier()
            turns.upsert_item(_turn_doc(args.tenant, user, sessions[user], tier))
            n_turns += 1
            # a complex turn sometimes results in a confirmed trip (an outcome)
            if tier["tier"] == "complex" and random.random() < 0.35:
                trips.upsert_item(_trip_doc(args.tenant, user))
                n_trips += 1
            if n_turns % 20 == 0:
                print(f"  wrote {n_turns} turns, {n_trips} confirmed trips "
                      f"({datetime.now().strftime('%H:%M:%S')})")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[simulator] stopped by user")
    print(f"[simulator] done: {n_turns} turns, {n_trips} trips for tenant {args.tenant}")


def run_app(args) -> None:
    import requests
    base = args.endpoint.rstrip("/")
    msgs = ["hi", "thanks!", "hotels in Amsterdam", "good restaurants near the Rijksmuseum",
            "what is the Krasnapolsky?", "please build me an itinerary for 3 days in Paris",
            "plan my trip to Tokyo", "ok sounds good"]
    interval = 60.0 / max(args.rate, 1)
    deadline = None if args.forever else time.monotonic() + args.minutes * 60
    print(f"[simulator] mode=app endpoint={base} rate={args.rate}/min")
    n = 0
    while args.forever or time.monotonic() < deadline:
        user = f"demo-user-{random.randint(1, args.users)}"
        session = f"sess-{uuid.uuid4().hex[:8]}"
        # create session then send a message
        try:
            requests.post(f"{base}/tenant/{args.tenant}/user/{user}/sessions",
                          params={"activeAgent": "orchestrator"}, timeout=30)
            requests.post(f"{base}/tenant/{args.tenant}/user/{user}/sessions/{session}/completion",
                          data=f'"{random.choice(msgs)}"',
                          headers={"Content-Type": "application/json"}, timeout=120)
            n += 1
            if n % 5 == 0:
                print(f"  sent {n} app turns")
        except Exception as e:  # noqa: BLE001
            print("  app turn failed:", e)
        time.sleep(interval)
    print(f"[simulator] done: {n} app turns")


def main() -> None:
    ap = argparse.ArgumentParser(description="Continuous optimization-turn traffic simulator.")
    ap.add_argument("--tenant", default="DemoLive")
    ap.add_argument("--mode", choices=["direct", "app"], default="direct")
    ap.add_argument("--rate", type=int, default=60, help="turns per minute")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--forever", action="store_true")
    ap.add_argument("--users", type=int, default=8)
    ap.add_argument("--endpoint", default="http://localhost:8000", help="API base (app mode)")
    args = ap.parse_args()
    (run_app if args.mode == "app" else run_direct)(args)


if __name__ == "__main__":
    main()

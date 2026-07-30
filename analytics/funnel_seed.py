"""
Conversion-funnel demo dataset — models WHY sessions don't convert.

The cost-per-outcome signal (SCEN-003) says *how much* is spent on sessions that
never book. This dataset lets the analytics go the "extra mile" — business impact,
not just mechanical cost — by encoding realistic **abandonment causes** so a funnel
diagnostic can show *where* sessions leak and *why*, pointing at the fix.

It writes a set of sessions to the ``funnel_demo`` tenant with a controlled outcome:

  Funnel stages (from each session's Debug agent_path):
    Engaged -> Searched -> Planned -> Confirmed

  Outcomes / causes:
    - converted        : Engaged -> Searched -> Planned -> Confirmed (a booked Trip)
    - no_engagement    : never searched (vague/greeting-only)
    - city_friction    : searched, stalled re-asking "which city?" (the SCEN-001 gap)
    - no_results       : searched, the place search dead-ended ("couldn't find any…")
    - cart_abandon     : got a full itinerary, never confirmed (last-mile drop)

Each session writes authentic-shaped OptimizationTurns (agent_path, tokens,
handoff_count), a few Messages carrying the friction signal, and — for converted
sessions — a Trip (status=confirmed) that records the sessionId so conversion is
session-level.

Deterministic (fixed seed) and idempotent (stable ids). Turns land in
OptimizationTurns/Messages/Trips (read by the Module 09 notebook via the Fabric mirror).

Usage (repo root; Cosmos via DefaultAzureCredential):
  python analytics/funnel_seed.py                 # ~120 sessions
  python analytics/funnel_seed.py --sessions 200
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv  # noqa: B018  (imported above; env resolution happens below)

# Resolve the deployed Cosmos endpoint. Priority: an already-set COSMOSDB_ENDPOINT
# (e.g. exported by azd during a hook) > a .env in the current directory (the deployed
# tree's python/ dir, where azd postprovision runs) > the known workshop trees.
_repo_root = Path(__file__).resolve().parents[1]
if not os.environ.get("COSMOSDB_ENDPOINT"):
    _env_candidates = [Path.cwd() / ".env"]
    _env_candidates += [_repo_root / _tree / "python" / ".env" for _tree in ("01_exercises", "02_completed")]
    for _env_path in _env_candidates:
        if _env_path.exists():
            load_dotenv(_env_path)
            if os.environ.get("COSMOSDB_ENDPOINT"):
                break

TENANT = "funnel_demo"
CITIES = ["Amsterdam", "Paris", "Tokyo", "Rome", "Barcelona", "London", "New York"]

# Outcome mix (must sum to ~1.0). Tuned so the funnel has a clear, teachable leak:
# the biggest addressable loss is city_friction at the Searched->Planned step.
OUTCOMES = [
    ("converted", 0.40),
    ("city_friction", 0.22),
    ("cart_abandon", 0.18),
    ("no_results", 0.12),
    ("no_engagement", 0.08),
]

# Per-stage turn profile: (agent_path, input range, output range, handoff_count).
_SUPERVISOR = ("supervisor", (3000, 6000), (80, 300), 0)
_SEARCH = ("supervisor,find_places", (8000, 16000), (200, 500), 1)
_PLAN = ("supervisor,find_places,create_or_update_itinerary", (28000, 33000), (1400, 1900), 2)


def _pick_outcome(rng: random.Random) -> str:
    r = rng.random()
    cum = 0.0
    for name, w in OUTCOMES:
        cum += w
        if r <= cum:
            return name
    return OUTCOMES[0][0]


def _turn_doc(tenant, user, session, stage, ts, idx):
    """Flat OptimizationTurns doc (matches record_optimization_turn's schema, plus
    agent_path) so the Module 09 notebook can read it from the mirror."""
    path, in_r, out_r, handoffs = stage
    it = random.randint(*in_r)
    ot = random.randint(*out_r)
    timestamp = ts.isoformat()
    return {
        "id": f"funnel::{session}::{idx}",
        "type": "optimization_turn",
        "tenantId": tenant, "userId": user, "sessionId": session,
        "model_tier": "default",
        "model_deployment": "gpt-5.1",
        "model_name": "gpt-5.1-2025-11-13",
        "input_tokens": it,
        "output_tokens": ot,
        "total_tokens": it + ot,
        "cached_tokens": int(it * 0.7),
        "handoff_count": handoffs,
        "agent_path": path,
        "timeStamp": timestamp,
        "turn_epoch": int(ts.timestamp()),
    }


def _msg_doc(tenant, user, session, role, content, ts, idx):
    return {
        "id": f"funnel::{session}::msg::{idx}",
        "type": "message",
        "tenantId": tenant, "userId": user, "sessionId": session,
        "role": role, "content": content,
        "timeStamp": ts.isoformat(),
    }


def _trip_doc(tenant, user, session, ts):
    trip_id = f"funnel-{session}-trip"
    return {
        "id": trip_id, "tripId": trip_id,
        "tenantId": tenant, "userId": user, "sessionId": session,
        "destination": random.choice(CITIES),
        "status": "confirmed",
        "createdAt": ts.isoformat(),
    }


def build_session(outcome, rng):
    """Return (debug_stages, messages, converts) for one session's outcome."""
    city = rng.choice(CITIES)
    if outcome == "converted":
        stages = [_SUPERVISOR, _SEARCH, _SEARCH, _PLAN]
        msgs = [("assistant", f"Here is a 3-day plan for {city}. Shall I book it?")]
        return stages, msgs, True
    if outcome == "cart_abandon":
        stages = [_SUPERVISOR, _SEARCH, _SEARCH, _PLAN]
        msgs = [("assistant", f"Here is your itinerary for {city}.")]
        return stages, msgs, False  # planned, never confirmed
    if outcome == "city_friction":
        # searched but stalls re-asking which city (the SCEN-001 gap)
        stages = [_SUPERVISOR, _SEARCH, _SUPERVISOR, _SUPERVISOR]
        msgs = [
            ("user", "book the Krasnapolsky"),
            ("assistant", "Which city is that hotel in?"),
            ("user", "the one for my trip"),
            ("assistant", "Sorry, which city are you asking about?"),
        ]
        return stages, msgs, False
    if outcome == "no_results":
        stages = [_SUPERVISOR, _SEARCH]
        msgs = [("assistant", "I couldn't find any matching places for that search.")]
        return stages, msgs, False
    # no_engagement
    stages = [_SUPERVISOR]
    msgs = [("assistant", "Happy to help — where would you like to go?")]
    return stages, msgs, False


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the conversion-funnel demo dataset.")
    ap.add_argument("--sessions", type=int, default=120)
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    random.seed(args.seed)  # _debug_doc/_trip_doc use module random for token jitter

    endpoint = os.environ["COSMOSDB_ENDPOINT"]
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)
    turns = db.get_container_client("OptimizationTurns")
    messages = db.get_container_client("Messages")
    trips = db.get_container_client("Trips")

    now = datetime.now(timezone.utc)
    step = timedelta(hours=args.hours) / max(args.sessions, 1)
    counts: dict[str, int] = {}
    n_conv = 0
    for i in range(args.sessions):
        user = f"funnel-user-{i:04d}"
        session = f"fsess-{i:04d}"
        outcome = _pick_outcome(rng)
        counts[outcome] = counts.get(outcome, 0) + 1
        ts0 = now - timedelta(hours=args.hours) + step * i
        stages, msgs, converts = build_session(outcome, rng)
        for j, stage in enumerate(stages):
            turns.upsert_item(_turn_doc(TENANT, user, session, stage, ts0 + timedelta(seconds=j * 30), j))
        for k, (role, content) in enumerate(msgs):
            messages.upsert_item(_msg_doc(TENANT, user, session, role, content, ts0 + timedelta(seconds=k * 20), k))
        if converts:
            trips.upsert_item(_trip_doc(TENANT, user, session, ts0 + timedelta(seconds=len(stages) * 30)))
            n_conv += 1

    print(f"✅ Funnel dataset for tenant '{TENANT}': {args.sessions} sessions, {n_conv} converted")
    print(f"   outcomes: {counts}")


if __name__ == "__main__":
    main()

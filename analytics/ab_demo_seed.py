"""
A/B demo dataset — a paired before/after for the model-selection optimization.

Writes the SAME synthetic workload to two tenants so a Power BI tenant slicer can
flip a true apples-to-apples before/after with zero live-traffic risk in a session:

  - ``before_demo``: every turn runs on the single premium model (gpt-5.1) with
    ``model_tier="default"`` — the pre-optimization baseline (one model for all).
  - ``after_demo``:  the identical workload, tiered — trivial->gpt-5-nano,
    routine->gpt-5-mini, complex->gpt-5.1 — i.e. capability-tiered selection applied.

Because each workload item (its input/output tokens, handoffs, session, and
timestamp) is written identically to both tenants and ONLY the model/tier differ,
the cost delta between the two tenants is exactly the optimization saving — nothing
is hand-waved. Token ranges reuse the realistic per-tier profiles from
traffic_simulator.py (kept consistent with observed data).

Deterministic (fixed seed) and idempotent (stable doc ids), so re-running replaces
the dataset cleanly. Turns land in OptimizationTurns / Trips, which already mirror
to Fabric, so the report picks them up with no mirror change.

Usage (repo root; Cosmos access via DefaultAzureCredential):
  python analytics/ab_demo_seed.py                 # 240 paired turns over the last 24h
  python analytics/ab_demo_seed.py --turns 400 --hours 48
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

# Resolve the deployed Cosmos endpoint: an already-set COSMOSDB_ENDPOINT (e.g. exported
# by azd) > a .env in the current dir > either workshop tree's python/.env.
if not os.environ.get("COSMOSDB_ENDPOINT"):
    _repo_root = Path(__file__).resolve().parents[1]
    for _env_path in [Path.cwd() / ".env"] + [_repo_root / _t / "python" / ".env" for _t in ("01_exercises", "02_completed")]:
        if _env_path.exists():
            load_dotenv(_env_path)
            if os.environ.get("COSMOSDB_ENDPOINT"):
                break

BEFORE_TENANT = "before_demo"
AFTER_TENANT = "after_demo"

# Single premium model everything runs on in the "before" world.
DEFAULT_DEPLOYMENT = "gpt-5.1"
DEFAULT_MODEL = "gpt-5.1-2025-11-13"

# Per-tier workload profile (token ranges/handoffs match traffic_simulator.py, which
# keeps them consistent with observed data). Weights: a realistic ~10% trivial share.
TIERS = [
    {"tier": "trivial", "weight": 0.10, "deployment": "gpt-5-nano",
     "model": "gpt-5-nano-2025-08-07", "in": (2800, 3600), "out": (20, 55), "handoffs": 0},
    {"tier": "routine", "weight": 0.55, "deployment": "gpt-5-mini",
     "model": "gpt-5-mini-2025-08-07", "in": (6000, 16000), "out": (200, 450), "handoffs": 1},
    {"tier": "complex", "weight": 0.35, "deployment": "gpt-5.1",
     "model": "gpt-5.1-2025-11-13", "in": (28000, 33000), "out": (1400, 1900), "handoffs": 2},
]
CITIES = ["Amsterdam", "Paris", "Tokyo", "Rome", "Barcelona", "London", "New York"]


def _pick_tier(rng: random.Random) -> dict:
    r = rng.random()
    cum = 0.0
    for t in TIERS:
        cum += t["weight"]
        if r <= cum:
            return t
    return TIERS[-1]


def _turn_doc(tenant, user, session, tier, in_tok, out_tok, cached, ts, idx, applied) -> dict:
    """One OptimizationTurn. ``applied`` False -> baseline (default/gpt-5.1);
    True -> tiered (this workload item's tier + its model)."""
    if applied:
        model_tier, deployment, model = tier["tier"], tier["deployment"], tier["model"]
    else:
        model_tier, deployment, model = "default", DEFAULT_DEPLOYMENT, DEFAULT_MODEL
    return {
        "id": f"ab::{tenant}::{idx}",
        "type": "optimization_turn",
        "tenantId": tenant, "userId": user, "sessionId": session,
        "model_tier": model_tier, "model_deployment": deployment, "model_name": model,
        "input_tokens": in_tok, "output_tokens": out_tok, "total_tokens": in_tok + out_tok,
        "cached_tokens": cached,
        "handoff_count": tier["handoffs"],
        "timeStamp": ts.isoformat(),
        "turn_epoch": int(ts.timestamp()),
    }


def _trip_doc(tenant, user, idx, ts) -> dict:
    return {
        "id": f"ab::{tenant}::trip::{idx}",
        "tenantId": tenant, "userId": user, "tripId": f"ab-{tenant}-trip-{idx}",
        "destination": CITIES[idx % len(CITIES)],
        "status": "confirmed",
        "createdAt": ts.isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the paired before/after A/B demo dataset.")
    ap.add_argument("--turns", type=int, default=240, help="workload items (written to EACH tenant)")
    ap.add_argument("--hours", type=float, default=24, help="spread timestamps over the last N hours")
    ap.add_argument("--users", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    endpoint = os.environ["COSMOSDB_ENDPOINT"]
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)
    turns = db.get_container_client("OptimizationTurns")
    trips = db.get_container_client("Trips")

    users = [f"demo-user-{i}" for i in range(1, args.users + 1)]
    sessions = {u: f"sess-{uuid.uuid4().hex[:8]}" for u in users}
    now = datetime.now(timezone.utc)
    step = timedelta(hours=args.hours) / max(args.turns, 1)

    counts = {BEFORE_TENANT: {}, AFTER_TENANT: {}}
    n_trips = 0
    for i in range(args.turns):
        user = rng.choice(users)
        if rng.random() < 0.05:
            sessions[user] = f"sess-{uuid.uuid4().hex[:8]}"
        session = sessions[user]
        tier = _pick_tier(rng)
        in_tok = rng.randint(*tier["in"])
        out_tok = rng.randint(*tier["out"])
        cached = int(in_tok * rng.uniform(0.6, 0.9))
        ts = now - timedelta(hours=args.hours) + step * i

        # identical workload -> two tenants; only model/tier differ
        turns.upsert_item(_turn_doc(BEFORE_TENANT, user, session, tier, in_tok, out_tok, cached, ts, i, applied=False))
        turns.upsert_item(_turn_doc(AFTER_TENANT, user, session, tier, in_tok, out_tok, cached, ts, i, applied=True))
        counts[BEFORE_TENANT]["default"] = counts[BEFORE_TENANT].get("default", 0) + 1
        counts[AFTER_TENANT][tier["tier"]] = counts[AFTER_TENANT].get(tier["tier"], 0) + 1

        # a complex turn sometimes converts -> identical confirmed trip in BOTH tenants
        if tier["tier"] == "complex" and rng.random() < 0.35:
            trips.upsert_item(_trip_doc(BEFORE_TENANT, user, i, ts))
            trips.upsert_item(_trip_doc(AFTER_TENANT, user, i, ts))
            n_trips += 1

    print(f"✅ A/B dataset written: {args.turns} paired turns over {args.hours}h, {n_trips} matched trips/tenant")
    print(f"   {BEFORE_TENANT}: {counts[BEFORE_TENANT]}  (all on {DEFAULT_DEPLOYMENT})")
    print(f"   {AFTER_TENANT} : {counts[AFTER_TENANT]}")


if __name__ == "__main__":
    main()

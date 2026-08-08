"""
Traffic simulator — drives a realistic, continuous stream of optimization turns
into Cosmos so you can watch the near-real-time analytics story: turns land in
Cosmos (transactional) -> mirror to Fabric -> Power BI / Console update live.

The travel app is one-user-at-a-time, which makes "watch the dashboard move"
hard to show live. This simulator solves that for a demo: it writes turns (and
occasional confirmed trips) at a controllable rate with a realistic complexity-tier mix, so
the dashboards visibly change as it runs.

Two modes:
  --mode direct  (default): write OptimizationTurns docs straight to Cosmos.
                  Fast, no LLM cost, controllable rate. Best for the live demo.
  --mode app:     drive the real completion endpoint (real agent turns).
                  Realistic but slower and incurs model cost.

Policy-aware (direct mode): the *workload* (per-turn token profile, handoffs,
complexity mix) is fixed, but which MODEL serves each turn depends on the active
`model-selection` OptimizationPolicy for the tenant — so apply -> simulate ->
re-measure shows a REAL cost delta, not a canned one:
  - no active policy  -> every turn runs on the single premium model (baseline).
  - policy active      -> capability-tiered (trivial->nano, routine->mini,
                          complex->premium). Only the model differs, so the cost
                          delta vs baseline is exactly the optimization saving.
The policy is re-checked every ~10s, so applying/reverting it mid-run visibly
changes the stream. Override with --assume {auto,baseline,tiered}.

Usage (repo root, Cosmos access via DefaultAzureCredential):
  python analytics/scripts/traffic_simulator.py --tenant analytics --rate 60 --minutes 10
  python analytics/scripts/traffic_simulator.py --tenant analytics --forever --rate 120
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

load_dotenv  # noqa: B018  (imported above; env resolution happens below)

# Resolve the deployed Cosmos endpoint. Priority: an already-set COSMOSDB_ENDPOINT
# (e.g. exported by azd during a hook) > a .env in the current directory (the deployed
# tree's python/ dir) > the known workshop trees.
_repo_root = Path(__file__).resolve().parents[2]
if not os.environ.get("COSMOSDB_ENDPOINT"):
    _env_candidates = [Path.cwd() / ".env"]
    _env_candidates += [_repo_root / _tree / "python" / ".env" for _tree in ("01_exercises", "02_completed")]
    for _env_path in _env_candidates:
        if _env_path.exists():
            load_dotenv(_env_path)
            if os.environ.get("COSMOSDB_ENDPOINT"):
                break

# Realistic complexity-tier mix + per-complexity-tier token/model profile. Kept consistent with the canonical
# trivial definition used everywhere (handoff_count == 0 AND output_tokens < 60): only the
# trivial complexity tier has 0 handoffs and <60 output tokens. Trivial share ~10% matches the real
# opportunity measured on the seeded conversations (not an inflated demo number).
COMPLEXITY_PROFILES = [
    {"complexity_tier": "trivial", "weight": 0.10, "deployment": "gpt-5-nano",
     "model": "gpt-5-nano-2025-08-07", "in": (2800, 3600), "out": (20, 55), "handoffs": 0},
    {"complexity_tier": "routine", "weight": 0.55, "deployment": "gpt-5-mini",
     "model": "gpt-5-mini-2025-08-07", "in": (6000, 16000), "out": (200, 450), "handoffs": 1},
    {"complexity_tier": "complex", "weight": 0.35, "deployment": "gpt-5.1",
     "model": "gpt-5.1-2025-11-13", "in": (28000, 33000), "out": (1400, 1900), "handoffs": 2},
]
CITIES = ["Amsterdam", "Paris", "Tokyo", "Rome", "Barcelona", "London", "New York"]

# The single premium model everything runs on in the pre-optimization baseline.
DEFAULT_DEPLOYMENT = "gpt-5.1"
DEFAULT_MODEL = "gpt-5.1-2025-11-13"
MODEL_SELECTION_SCENARIO = "model-selection"


def _pick_complexity_profile() -> dict:
    r = random.random()
    cum = 0.0
    for profile in COMPLEXITY_PROFILES:
        cum += profile["weight"]
        if r <= cum:
            return profile
    return COMPLEXITY_PROFILES[-1]


def _model_selection_active(policies) -> bool:
    """True iff the tenant's model-selection policy is active AND enabled.

    Reads the OptimizationPolicies container the app's apply-loop writes. Any
    error (no container, no policy, 404) means 'not applied' -> baseline, which
    is the safe default.
    """
    if policies is None:
        return False
    try:
        doc = policies.read_item(item=MODEL_SELECTION_SCENARIO, partition_key=MODEL_SELECTION_SCENARIO)
    except Exception:  # noqa: BLE001 -- 404 == no policy yet
        return False
    return doc.get("status") == "active" and bool((doc.get("params") or {}).get("enabled", False))


def _turn_doc(tenant: str, user: str, session: str, profile: dict, applied: bool) -> dict:
    """One OptimizationTurn. The workload (tokens/handoffs) comes from ``profile``;
    ``applied`` decides which model served it — tiered (True) vs the single
    premium baseline (False). Only the model/complexity-tier fields differ between the two,
    so the cost delta between a baseline run and an applied run is exactly the
    optimization saving."""
    it = random.randint(*profile["in"])
    ot = random.randint(*profile["out"])
    now = datetime.now(timezone.utc)
    if applied:
        complexity_tier, deployment, model = profile["complexity_tier"], profile["deployment"], profile["model"]
    else:
        complexity_tier, deployment, model = "default", DEFAULT_DEPLOYMENT, DEFAULT_MODEL
    return {
        "id": str(uuid.uuid4()),
        "type": "optimization_turn",
        "tenantId": tenant, "userId": user, "sessionId": session,
        "complexity_tier": complexity_tier, "model_deployment": deployment,
        "model_name": model,
        "input_tokens": it, "output_tokens": ot, "total_tokens": it + ot,
        "cached_tokens": int(it * random.uniform(0.6, 0.9)),
        "handoff_count": profile["handoffs"],
        "timeStamp": now.isoformat(),
        "turn_epoch": int(now.timestamp()),
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


def _resolve_applied(assume: str, policies) -> bool:
    if assume == "baseline":
        return False
    if assume == "tiered":
        return True
    return _model_selection_active(policies)  # auto


def run_direct(args) -> None:
    endpoint = os.environ["COSMOSDB_ENDPOINT"]
    db_name = os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)
    turns = db.get_container_client("OptimizationTurns")
    trips = db.get_container_client("Trips")
    policies = db.get_container_client("OptimizationPolicies")

    interval = 60.0 / max(args.rate, 1)
    deadline = None if args.forever else time.monotonic() + args.minutes * 60
    applied = _resolve_applied(args.assume, policies)

    def _mode_label(a: bool) -> str:
        if args.assume == "auto":
            return "TIERED (model-selection policy active)" if a else "baseline (single premium model)"
        return f"{args.assume} (forced)"

    print(f"[simulator] tenant={args.tenant} rate={args.rate}/min "
          f"mode=direct db={db_name} {'(forever)' if args.forever else f'for {args.minutes} min'}")
    print(f"[simulator] model policy: {_mode_label(applied)}")

    n_turns = n_trips = 0
    last_policy_check = time.monotonic()
    users = [f"demo-user-{i}" for i in range(1, args.users + 1)]
    sessions = {u: f"sess-{uuid.uuid4().hex[:8]}" for u in users}
    try:
        while args.forever or time.monotonic() < deadline:
            # Re-check the policy periodically so applying/reverting it mid-run
            # visibly flips the stream between baseline and tiered.
            if args.assume == "auto" and time.monotonic() - last_policy_check > 10:
                new_applied = _model_selection_active(policies)
                if new_applied != applied:
                    print(f"[simulator] model policy changed -> {_mode_label(new_applied)}")
                applied = new_applied
                last_policy_check = time.monotonic()

            user = random.choice(users)
            # occasionally rotate a user's session (new conversation)
            if random.random() < 0.05:
                sessions[user] = f"sess-{uuid.uuid4().hex[:8]}"
            profile = _pick_complexity_profile()
            turns.upsert_item(_turn_doc(args.tenant, user, sessions[user], profile, applied))
            n_turns += 1
            # a complex turn sometimes results in a confirmed trip (an outcome)
            if profile["complexity_tier"] == "complex" and random.random() < 0.35:
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
    ap.add_argument("--tenant", default="analytics")
    ap.add_argument("--mode", choices=["direct", "app"], default="direct")
    ap.add_argument("--rate", type=int, default=60, help="turns per minute")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--forever", action="store_true")
    ap.add_argument("--users", type=int, default=8)
    ap.add_argument("--assume", choices=["auto", "baseline", "tiered"], default="auto",
                    help="direct mode: auto reads the model-selection policy (baseline vs tiered); "
                         "baseline/tiered force the model mix regardless of policy")
    ap.add_argument("--endpoint", default="http://localhost:8000", help="API base (app mode)")
    args = ap.parse_args()
    (run_app if args.mode == "app" else run_direct)(args)


if __name__ == "__main__":
    main()

"""
Demo live turns — fire a few authentic turns through the REAL app during a session.

This is the "and here's it happening for real" moment: after you apply the
model-selection policy in the Optimization Console, run this to send a small,
representative set of turns through the running app. The app's classifier routes
each one by tier, so you can refresh the report and watch NEW tiered turns land
(a greeting on gpt-5-nano, a full itinerary on gpt-5.1) — proof the mechanism
works, on top of the pre-baked A/B that carries the at-scale story.

It sends ONE turn per tier so the routing is obvious, then derives those turns
into OptimizationTurns (on 02_completed the app writes Debug telemetry and
OptimizationTurns is derived from it) so they appear in the report:
  - "hi"                                   -> trivial  -> gpt-5-nano
  - "thanks, that's perfect!"              -> trivial  -> gpt-5-nano
  - "good hotels in Amsterdam near centre" -> routine  -> gpt-5-mini
  - "plan a detailed 3-day Tokyo itinerary -> complex  -> gpt-5.1
     with hotels, activities and dining"

Prereqs:
  - The app is running and reachable at --endpoint. Local: http://localhost:8000.
    Hosted: the web app URL + "/api" (the API container app is internal-only; the
    frontend proxies /api to it), e.g. https://<web-app>.azurecontainerapps.io/api.
  - The model-selection policy is ACTIVE (apply it in the Console first, or the
    turns will be recorded as tier "default"). This is intentional — applying is
    the on-stage moment.

Usage:
  python analytics/demo_live_turns.py --endpoint http://localhost:8000
  python analytics/demo_live_turns.py --endpoint https://<web-app>.azurecontainerapps.io/api
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

import requests

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Ordered so the tier routing reads clearly on stage.
PROMPTS = [
    ("trivial", "hi"),
    ("trivial", "thanks, that's perfect!"),
    ("routine", "what are some good hotels in Amsterdam near the centre?"),
    ("complex", "plan me a detailed 3-day itinerary for Tokyo with hotels, activities, and places to eat"),
]


def send_turns(base: str, tenant: str, user: str, session: str) -> None:
    base = base.rstrip("/")
    # create the session (idempotent enough for a demo)
    try:
        requests.post(f"{base}/tenant/{tenant}/user/{user}/sessions",
                      params={"activeAgent": "orchestrator"}, timeout=30)
    except requests.RequestException as exc:
        print(f"⚠️  could not pre-create session ({exc}); sending anyway")
    for expected, text in PROMPTS:
        print(f"→ [{expected:7}] {text}")
        t0 = time.time()
        try:
            r = requests.post(
                f"{base}/tenant/{tenant}/user/{user}/sessions/{session}/completion",
                data=json.dumps(text), headers={"Content-Type": "application/json"}, timeout=180,
            )
            r.raise_for_status()
            print(f"   ✓ responded in {time.time() - t0:.1f}s")
        except requests.RequestException as exc:
            print(f"   ✗ failed: {exc}")


def _bag(doc):
    pb = doc.get("propertyBag")
    return {i["key"]: i["value"] for i in pb} if isinstance(pb, list) else (pb or {})


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _epoch(iso):
    if not iso:
        return 0
    try:
        from datetime import datetime, timezone
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())
    except (ValueError, TypeError):
        return 0


def capture(tenant: str, session: str, retries: int = 6) -> None:
    """Derive OptimizationTurns from this session's Debug telemetry and upsert them.

    On 02_completed the app writes per-turn **Debug** telemetry; OptimizationTurns is
    derived from it (see data/export_conversations.py). This does that derive for JUST
    the turns we sent — so they show up in the report — without touching the golden
    data/*.json. If every turn reads 'default', the model-selection policy isn't active.
    """
    try:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential
        from dotenv import load_dotenv
    except ImportError:
        print("capture needs azure-cosmos/azure-identity/python-dotenv; skipping")
        return
    load_dotenv(Path(__file__).resolve().parents[1] / "02_completed" / "python" / ".env")
    endpoint = os.environ.get("COSMOSDB_ENDPOINT")
    if not endpoint:
        print("COSMOSDB_ENDPOINT not set; skipping capture")
        return
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(
        os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant"))
    debug = db.get_container_client("Debug")
    opt = db.get_container_client("OptimizationTurns")

    rows = []
    for _ in range(retries):
        rows = list(debug.query_items(
            query="SELECT * FROM c WHERE c.sessionId=@s",
            parameters=[{"name": "@s", "value": session}], enable_cross_partition_query=True))
        if len(rows) >= len(PROMPTS):
            break
        time.sleep(2)

    written = 0
    print(f"\nCaptured {len(rows)} turn(s) for session {session}:")
    for d in rows:
        b = _bag(d)
        base_id = d.get("debugLogId") or d.get("id") or uuid.uuid4().hex
        ts = d.get("timeStamp")
        turn = {
            "id": f"turn-{base_id}", "type": "optimization_turn",
            "tenantId": d.get("tenantId"), "userId": d.get("userId"), "sessionId": d.get("sessionId"),
            "model_tier": b.get("model_tier", "default"),
            "model_deployment": b.get("model_deployment", "Unknown"),
            "model_name": b.get("model_name", "Unknown"),
            "input_tokens": _int(b.get("input_tokens")), "output_tokens": _int(b.get("output_tokens")),
            "total_tokens": _int(b.get("total_tokens")), "cached_tokens": _int(b.get("cached_tokens")),
            "handoff_count": _int(b.get("handoff_count")),
            "timeStamp": ts, "turn_epoch": _epoch(ts),
        }
        opt.upsert_item(turn)
        written += 1
        print(f"   {turn['model_tier']:8} -> {turn['model_deployment']} (out={turn['output_tokens']})")
    print(f"   ✓ {written} turn(s) written to OptimizationTurns")
    if rows and all(_bag(d).get("model_tier", "default") == "default" for d in rows):
        print("   ⚠️  all 'default' — the model-selection policy isn't active yet (apply it first).")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fire a few live turns through the app for a demo.")
    ap.add_argument("--endpoint", default="http://localhost:8000", help="API base URL")
    ap.add_argument("--tenant", default="demo_live")
    ap.add_argument("--user", default="presenter")
    ap.add_argument("--no-capture", action="store_true",
                    help="just send turns; skip deriving them into OptimizationTurns")
    args = ap.parse_args()

    session = f"demo-{uuid.uuid4().hex[:8]}"
    print(f"tenant={args.tenant} user={args.user} session={session} endpoint={args.endpoint}\n")
    send_turns(args.endpoint, args.tenant, args.user, session)
    if not args.no_capture:
        capture(args.tenant, session)
    print(f"\nDone. Refresh the report (filter tenant = '{args.tenant}') to see the new tiered turns.")


if __name__ == "__main__":
    main()

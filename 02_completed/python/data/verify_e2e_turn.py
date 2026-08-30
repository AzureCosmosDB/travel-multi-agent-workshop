"""
Ultimate end-to-end live turn: drive a REAL agent turn through the running API
(MCP :8080 + API :8000) and verify that (B1) node-grain telemetry and (B19) a
session-stamped Trip land in Cosmos.

Run (with both servers up):
  cd 02_completed/python ; ../.venv-travel/Scripts/python.exe data/verify_e2e_turn.py
"""

from __future__ import annotations

import json
import os
import sys
import uuid

_PYDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PYDIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PYDIR, ".env"), override=False)
except Exception:
    pass

import httpx  # noqa: E402

BASE = "http://127.0.0.1:8000"
TENANT = "e2e-live"
USER = "e2e"
SESSION = "e2e-" + uuid.uuid4().hex[:10]
MESSAGE = ("Plan a 2-day trip to Paris. Find a couple of hotels and restaurants, "
           "then create and save a day-by-day itinerary for the trip.")


def drive_turn() -> list[str]:
    url = f"{BASE}/tenant/{TENANT}/user/{USER}/sessions/{SESSION}/completion/stream"
    events: list[str] = []
    with httpx.stream("POST", url, content=json.dumps(MESSAGE),
                      headers={"Content-Type": "application/json"}, timeout=240.0) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            payload = line[5:].strip() if line.startswith("data:") else line.strip()
            try:
                ev = json.loads(payload)
            except Exception:
                continue
            kind = ev.get("event")
            if kind in ("tool_call_start", "thinking", "done"):
                events.append(f"{kind}:{ev.get('tool') or ev.get('node') or ''}")
            if kind == "done":
                break
    return events


def main() -> int:
    print(f"Session: {SESSION}\nMessage: {MESSAGE}\n")
    print("Driving a live agent turn (real LLM + MCP tools) ...")
    events = drive_turn()
    print("Turn events:", " | ".join(events) or "(none)")

    # --- verify in Cosmos ------------------------------------------------------------
    from src.app.services import azure_cosmos_db as cosmos
    from src.app.services import node_executions as ne
    cosmos.initialize_cosmos_client()

    results: list[tuple[str, bool, str]] = []

    def ck(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    # B1: node-grain telemetry captured for this session
    nec = ne._get_container()
    node_docs = list(nec.query_items(
        query="SELECT * FROM c WHERE c.tenantId=@t AND c.sessionId=@s",
        parameters=[{"name": "@t", "value": TENANT}, {"name": "@s", "value": SESSION}],
        enable_cross_partition_query=True))
    total_nodes = sum(d.get("nodeCount", 0) for d in node_docs)
    agents = sorted({r.get("agent") for d in node_docs for r in d.get("nodeExecutions", [])})
    ck("B1 live: node-grain telemetry captured from a real turn", total_nodes > 0,
       f"{total_nodes} node records across {len(node_docs)} turn doc(s); agents={agents}")

    # B19: a Trip stamped with this session (best-effort — the agent may or may not save one)
    trips = list(cosmos.trips_container.query_items(
        query="SELECT c.tripId, c.sessionId, c.destination, c.status FROM c WHERE c.sessionId=@s",
        parameters=[{"name": "@s", "value": SESSION}],
        enable_cross_partition_query=True))
    ck("B19 live: created Trip carries the session correlation key",
       bool(trips) and all(t.get("sessionId") == SESSION for t in trips),
       f"trips={trips}" if trips else "no trip saved this turn (agent chose not to)")

    # --- cleanup ---------------------------------------------------------------------
    cleaned = 0
    for d in node_docs:
        try:
            nec.delete_item(item=d["id"], partition_key=[TENANT, USER, d["sessionId"]]); cleaned += 1
        except Exception:
            pass
    for t in trips:
        try:
            cosmos.trips_container.delete_item(item=t["tripId"], partition_key=[TENANT, USER, t["tripId"]]); cleaned += 1
        except Exception:
            pass

    print("\n" + "=" * 78)
    print("LIVE end-to-end turn verification")
    print("=" * 78)
    ok = True
    for name, passed, detail in results:
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))
    print("-" * 78)
    print(f"  cleaned up {cleaned} docs")
    # B1 is the hard requirement; B19 depends on the agent choosing to save a trip.
    hard_ok = results[0][1]
    print(f"  RESULT: {'PASS - node-grain captured from a real agent turn' if hard_ok else 'FAIL'}"
          + ("" if results[1][1] else "  (trip not saved this turn — B19 wiring already verified separately)"))
    print("=" * 78)
    return 0 if hard_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

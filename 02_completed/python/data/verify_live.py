"""
Live verification of the constructed engine wiring against the deployed Cosmos
account (keyless / DefaultAzureCredential). Exercises the REAL app code:

  B19  create_trip(session_id=...) persists sessionId on the Trip
  B1   store_node_executions() provisions + writes the NodeExecutions container
  Loop the engine reads node executions back from Cosmos and discovers the
       model-selection opportunity from LIVE data

Writes under an isolated tenant ('engine-verify') and cleans up afterward.

Run:  cd 02_completed/python ; ../.venv-travel/Scripts/python.exe data/verify_live.py
"""

from __future__ import annotations

import os
import sys
import uuid
from collections import defaultdict

_PYDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PYDIR)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PYDIR, ".env"), override=False)
except Exception:
    pass

from src.app.services import azure_cosmos_db as cosmos          # noqa: E402
from src.app.services import node_executions as ne              # noqa: E402
from src.app.engine import simulation, analyze                  # noqa: E402
from data.run_engine_analysis import _nodes_from_cosmos, declared_surface  # noqa: E402

TENANT = "engine-verify"
USER = "live-verify"


def main() -> int:
    cosmos.initialize_cosmos_client()
    if cosmos.database is None:
        print("FAIL: could not connect to Cosmos (check az login / .env)")
        return 1

    results: list[tuple[str, bool, str]] = []

    def ck(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    created_trip_id = None
    stored_docs: list[tuple[str, str]] = []  # (id, sessionId) for cleanup

    # --- B19: trip persists the session correlation key ------------------------------
    session = "verify-sess-" + uuid.uuid4().hex[:8]
    created_trip_id = cosmos.create_trip(
        USER, TENANT, "Verify City, Testland", "2026-09-01", "2026-09-03",
        days=[{"dayNumber": 1}], session_id=session,
    )
    trip = cosmos.get_trip(created_trip_id, USER, TENANT)
    ck("B19 live: trip persists sessionId", trip and trip.get("sessionId") == session,
       f"sessionId={trip.get('sessionId') if trip else None}")

    # --- B1: store node-grain telemetry to the live NodeExecutions container ----------
    nodes = simulation.simulate(seed=123, n_turns=120, tenant=TENANT, user=USER)
    by_turn = defaultdict(list)
    for n in nodes:
        by_turn[(n.session_id, n.turn_id)].append(n)
    stored = 0
    for (sid, turn), recs in by_turn.items():
        rd = [{"seq": r.seq, "agent": r.agent, "model_deployment": r.model_deployment,
               "model_name": r.model_name, "input_tokens": r.input_tokens,
               "output_tokens": r.output_tokens, "total_tokens": r.total_tokens,
               "cached_tokens": r.cached_tokens} for r in recs]
        doc_id = f"verify-{turn}"
        stored += ne.store_node_executions(TENANT, USER, sid, turn, doc_id, rd)
        stored_docs.append((doc_id, sid))
    ck("B1 live: node executions written to Cosmos", stored > 0,
       f"{stored} node records across {len(by_turn)} turns")

    # --- Loop: engine reads live telemetry and discovers the opportunity --------------
    loaded = _nodes_from_cosmos(TENANT)
    ck("engine: reads node executions back from Cosmos", len(loaded) >= stored, f"loaded {len(loaded)}")
    cards = analyze(loaded, declared_surface())
    msel = [c for c in cards if c["opportunity_id"] == "opp-modelfit-supervisor"]
    ck("engine: discovers model-selection opportunity from LIVE data",
       len(msel) == 1 and msel[0]["saving"] > 0,
       f"cards={[c['opportunity_id'] for c in cards]}, saving={msel[0]['saving'] if msel else None}")

    # --- cleanup ---------------------------------------------------------------------
    cleaned = 0
    try:
        if created_trip_id:
            cosmos.trips_container.delete_item(item=created_trip_id, partition_key=[TENANT, USER, created_trip_id])
            cleaned += 1
    except Exception as exc:
        print(f"  (cleanup trip skipped: {exc})")
    nec = ne._get_container()
    for doc_id, sid in stored_docs:
        try:
            nec.delete_item(item=doc_id, partition_key=[TENANT, USER, sid])
            cleaned += 1
        except Exception:
            pass

    # --- report ----------------------------------------------------------------------
    print("=" * 78)
    print("LIVE verification against Cosmos (keyless / DefaultAzureCredential)")
    print("=" * 78)
    ok = True
    for name, passed, detail in results:
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))
    print("-" * 78)
    print(f"  cleaned up {cleaned} verify docs")
    print(f"  RESULT: {'ALL PASS - constructed wiring works against live Cosmos' if ok else 'FAILURES'}")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

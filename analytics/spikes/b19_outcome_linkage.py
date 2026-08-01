"""
Spike B19 — business-outcome linkage via a correlation key (ADR-0012 B19, guide §10.4).

Grounded gap: `create_trip` (02_completed/python/src/app/services/azure_cosmos_db.py:819)
persists a Trip with `status` but NO `sessionId`/`turn_id`, and Trips are partitioned
`[tenantId, userId, tripId]`. So today the outcome<->execution join is coarse
(`[tenant,user]` + time), not per-session.

This spike proves:
  (1) WITHOUT the correlation key, per-session cost-per-outcome cannot be computed
      (you can only attribute at the user grain — ambiguous when a user has many sessions).
  (2) WITH one stamped key (sessionId), `WorkflowExecution (turns) JOIN outcome (trips)
      ON sessionId` yields correct per-session cost-per-outcome.
  (3) The fix is a one-field change to create_trip (shown at the bottom).

Pure stdlib, deterministic. `python b19_outcome_linkage.py` (exit 0 = pass).
"""

from __future__ import annotations


# Execution telemetry (turns) — already carries tenant/user/session (Debug/OptimizationTurns).
TURNS = [
    {"tenantId": "marvel", "userId": "tony", "sessionId": "s1", "total_tokens": 1000},
    {"tenantId": "marvel", "userId": "tony", "sessionId": "s1", "total_tokens": 1500},
    {"tenantId": "marvel", "userId": "tony", "sessionId": "s2", "total_tokens": 8000},  # a costly, non-converting session
    {"tenantId": "marvel", "userId": "tony", "sessionId": "s2", "total_tokens": 9000},
]

# Outcome (trips) — CURRENT shape: no sessionId. Tony confirmed a trip in session s1.
TRIPS_CURRENT = [
    {"tripId": "trip1", "tenantId": "marvel", "userId": "tony", "status": "confirmed"},
]

# Outcome (trips) — PROPOSED shape: correlation key stamped (which session produced it).
TRIPS_WITH_KEY = [
    {"tripId": "trip1", "tenantId": "marvel", "userId": "tony", "status": "confirmed", "sessionId": "s1"},
]

SUCCESS = {"confirmed", "completed"}


def session_cost(turns):
    out = {}
    for t in turns:
        out[t["sessionId"]] = out.get(t["sessionId"], 0) + t["total_tokens"]
    return out


def cost_per_outcome_session_grain(turns, trips):
    """Join execution -> outcome ON sessionId. Requires the correlation key on trips."""
    if not all("sessionId" in tr for tr in trips):
        return None  # cannot join at session grain without the key
    converting_sessions = {tr["sessionId"] for tr in trips if tr["status"] in SUCCESS}
    costs = session_cost(turns)
    spend_on_converting = sum(c for s, c in costs.items() if s in converting_sessions)
    n_outcomes = len(converting_sessions)
    return spend_on_converting / n_outcomes if n_outcomes else None


def run() -> bool:
    results: list[tuple[str, bool, str]] = []

    def check(name, cond, detail):
        results.append((name, cond, detail))

    # (1) current shape -> cannot join at session grain
    got = cost_per_outcome_session_grain(TURNS, TRIPS_CURRENT)
    check("current Trips (no sessionId) -> session-grain join impossible", got is None,
          f"result={got} (expected None — coarse per-user only)")

    # (2) with the key -> correct per-session cost-per-outcome.
    # Ground truth: only s1 converted; s1 spend = 1000+1500 = 2500; 1 outcome -> 2500.
    got = cost_per_outcome_session_grain(TURNS, TRIPS_WITH_KEY)
    check("with sessionId -> correct cost-per-outcome (attributes to converting session)",
          got == 2500.0, f"cost-per-outcome={got} (expected 2500.0)")

    # (3) the fix isolates converting spend from the costly non-converting session (s2=17000).
    costs = session_cost(TURNS)
    check("costly non-converting session (s2) is correctly excluded from cost-per-outcome",
          costs["s2"] == 17000 and got == 2500.0,
          f"s2 spend={costs['s2']} excluded; cost-per-outcome stays {got}")

    print("=" * 78)
    print("B19 — business-outcome linkage (correlation key)")
    print("=" * 78)
    all_pass = True
    for name, ok, detail in results:
        all_pass = all_pass and ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}\n         {detail}")
    print("-" * 78)
    print("  The one-field fix (create_trip):")
    print("     def create_trip(user_id, tenant_id, destination, ..., session_id: str | None = None):")
    print("         trip = { ..., 'status': 'planning', 'sessionId': session_id }   # <-- stamp the key")
    print("  (thread session_id from the request context through the create_new_trip MCP tool.)")
    print("-" * 78)
    print(f"  RESULT: {'ALL PASS - correlation key enables session-grain cost-per-outcome' if all_pass else 'FAILURES'}")
    print("=" * 78)
    return all_pass


if __name__ == "__main__":
    import sys
    sys.exit(0 if run() else 1)

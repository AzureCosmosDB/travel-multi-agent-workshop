"""
Optimization-scenario data mining — first-pass "data-first" discovery tool.

Runs the Tier-1 metric queries from `docs/optimization-scenarios/README.md` over a
Cosmos DB tenant and prints the evidence behind each candidate scenario (cost per
outcome, agent_path cost, delegation rate, model/cache usage, memory staleness, drift).

It reads only signal the app already captures (ADR-0007 Debug re-wire + Messages +
Trips + the Agent Memory Toolkit containers) — no new instrumentation. Results feed
`docs/optimization-scenarios/baseline-findings.md`.

Usage (repo root, with the v2 venv and Cosmos access via DefaultAzureCredential):
    python analytics/optimization_mining.py --tenant v2_analytics

Env: reads COSMOSDB_ENDPOINT (+ COSMOSDB_DATABASE_NAME, default TravelAssistant)
from the active azd environment (or either tree's python/.env), matching the running app.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import statistics
from pathlib import Path

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

PLACE_RE = re.compile(
    r"hotel|restaurant|dining|activit|museum|things to do|place|eat|stay|attraction", re.I
)


def _bag(doc: dict) -> dict:
    p = doc.get("propertyBag")
    return {i["key"]: i["value"] for i in p} if isinstance(p, list) else (p or {})


# Estimated USD per 1M tokens (input, output). ESTIMATE — verify on the Azure
# pricing calculator before quoting. Used only for the SCEN-007 verify report.
_EST_PRICING = {
    "gpt-5.1": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
}


def _price_for(deployment: str) -> tuple[float, float]:
    return _EST_PRICING.get((deployment or "").split("-2025")[0].split("-2024")[0], (1.25, 10.00))


def verify_model_selection(db, tenant: str, container: str = "OptimizationTurns") -> None:
    """SCEN-007 verify stage: per-tier token + estimated-cost breakdown.

    Reads the model_tier / model_deployment signal recorded per turn, so you can
    compare tiers (and before/after applying the policy). Works with both the
    flat ``OptimizationTurns`` schema (Module 07 workshop path) and the
    propertyBag ``Debug`` schema (the deep 02_completed instrumentation).
    """
    rows_in = list(
        db.get_container_client(container).query_items(
            query="SELECT * FROM d WHERE d.tenantId=@t",
            parameters=[{"name": "@t", "value": tenant}],
            enable_cross_partition_query=True,
        )
    )
    by_tier: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: {"turns": 0, "in": 0, "out": 0, "total": 0, "cost": 0.0}
    )
    for d in rows_in:
        # Flat OptimizationTurns docs put fields at top level; Debug uses propertyBag.
        b = _bag(d) if d.get("propertyBag") else d
        tier = b.get("model_tier") or "unlabeled"
        dep = b.get("model_deployment") or b.get("model_name") or "unknown"
        pin, pout = _price_for(dep)
        i, o = int(b.get("input_tokens") or 0), int(b.get("output_tokens") or 0)
        row = by_tier[f"{tier} ({dep})"]
        row["turns"] += 1
        row["in"] += i
        row["out"] += o
        row["total"] += int(b.get("total_tokens") or 0)
        row["cost"] += (i * pin + o * pout) / 1_000_000

    print(f"\n=== SCEN-007 VERIFY - per-tier cost for tenant '{tenant}' (container: {container}) ===")
    print(f"  (estimated USD, prices are list-price estimates)\n")
    print(f"  {'tier (deployment)':<40}{'turns':>6}{'in':>9}{'out':>7}{'total':>9}{'est $':>10}")
    grand = 0.0
    for name, r in sorted(by_tier.items(), key=lambda x: -x[1]["cost"]):
        grand += r["cost"]
        print(f"  {name:<40}{int(r['turns']):>6}{int(r['in']):>9}{int(r['out']):>7}"
              f"{int(r['total']):>9}{r['cost']:>10.5f}")
    print(f"  {'TOTAL':<40}{'':>6}{'':>9}{'':>7}{'':>9}{grand:>10.5f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Mine a tenant for optimization-scenario evidence.")
    ap.add_argument("--tenant", default="v2_analytics")
    ap.add_argument("--database", default=os.environ.get("COSMOSDB_DATABASE_NAME", "TravelAssistant"))
    ap.add_argument("--verify", action="store_true",
                    help="Only print the SCEN-007 per-tier cost verify report (needs model_tier signal).")
    ap.add_argument("--container", default="OptimizationTurns",
                    help="Container to read for --verify (default OptimizationTurns; use 'Debug' for the 02_completed deep instrumentation).")
    args = ap.parse_args()

    db = CosmosClient(os.environ["COSMOSDB_ENDPOINT"], DefaultAzureCredential()).get_database_client(
        args.database
    )
    T = args.tenant

    if args.verify:
        verify_model_selection(db, T, container=args.container)
        return

    def q(container: str, query: str) -> list:
        return list(
            db.get_container_client(container).query_items(query=query, enable_cross_partition_query=True)
        )

    dbg = q("Debug", f"SELECT * FROM d WHERE d.tenantId='{T}'")
    msgs = q("Messages", f"SELECT d.sessionId, d.role, d.content FROM d WHERE d.tenantId='{T}'")
    trips = q("Trips", f"SELECT d.userId, d.status FROM d WHERE d.tenantId='{T}'")
    mems = q("memories", "SELECT d.type, d.salience, d.superseded_by FROM d")
    print(f"[{T}] Debug={len(dbg)} Messages={len(msgs)} Trips={len(trips)} Memories={len(mems)}\n")

    # SCEN-005 — cost by agent_path
    path_tokens: dict[str, list[int]] = collections.defaultdict(list)
    hops = collections.Counter()
    for d in dbg:
        b = _bag(d)
        path_tokens[b.get("agent_path", "?")].append(int(b.get("total_tokens") or 0))
        hops[str(b.get("handoff_count"))] += 1
    print("=== SCEN-005 cost by agent_path ===")
    for ap_, toks in sorted(path_tokens.items(), key=lambda x: -sum(x[1])):
        print(f"  {ap_:<52} n={len(toks):>3} total={sum(toks):>8} avg={int(statistics.mean(toks)):>6}")
    print("handoff_count distribution:", dict(hops))

    # SCEN-001/008 — delegation on place-intent sessions
    user_texts: dict[str, list[str]] = collections.defaultdict(list)
    for m in msgs:
        if (m.get("role") or "").lower() == "user":
            user_texts[m["sessionId"]].append(m.get("content") or "")
    place_turns = nodeleg = 0
    for d in dbg:
        if PLACE_RE.search(" ".join(user_texts.get(d.get("sessionId"), []))):
            place_turns += 1
            if str(_bag(d).get("handoff_count")) == "0":
                nodeleg += 1
    print("\n=== SCEN-001/008 delegation on place-intent sessions ===")
    print(f"  turns={place_turns} no-delegation={nodeleg} ({100*nodeleg/max(place_turns,1):.0f}%)")

    # SCEN-003 — cost per outcome
    sess_tokens: dict[str, int] = collections.defaultdict(int)
    sess_user: dict[str, str] = {}
    for d in dbg:
        sess_tokens[d["sessionId"]] += int(_bag(d).get("total_tokens") or 0)
        sess_user[d["sessionId"]] = d.get("userId")
    confirmed_users = {t["userId"] for t in trips if t.get("status") in ("confirmed", "completed")}
    total = sum(sess_tokens.values())
    confirmed = sum(1 for t in trips if t.get("status") in ("confirmed", "completed"))
    wasted = sum(tk for s, tk in sess_tokens.items() if sess_user[s] not in confirmed_users)
    print("\n=== SCEN-003 cost per outcome ===")
    print(f"  total_tokens={total} confirmed_trips={confirmed} tokens_per_outcome={int(total/max(confirmed,1))}")
    print(f"  tokens on users who never confirmed: {wasted} ({100*wasted/max(total,1):.0f}%)")

    # SCEN-007 — model + cache + trivial turns
    models = collections.Counter()
    cached = inp = trivial = 0
    for d in dbg:
        b = _bag(d)
        models[b.get("model_name")] += 1
        cached += int(b.get("cached_tokens") or 0)
        inp += int(b.get("input_tokens") or 0)
        if str(b.get("handoff_count")) == "0" and int(b.get("output_tokens") or 0) < 60:
            trivial += 1
    print("\n=== SCEN-007 model / cache ===")
    print(f"  models={dict(models)} cache_hit={100*cached/max(inp,1):.0f}% trivial_turns={trivial}/{len(dbg)}")

    # SCEN-004 — memory staleness
    superseded = sum(1 for m in mems if m.get("superseded_by"))
    sal = [m["salience"] for m in mems if isinstance(m.get("salience"), (int, float))]
    print("\n=== SCEN-004 memory staleness ===")
    print(f"  superseded={superseded}/{len(mems)} ({100*superseded/max(len(mems),1):.0f}%)"
          f" salience_mean={statistics.mean(sal):.2f}" if sal else f"  superseded={superseded}/{len(mems)}")


if __name__ == "__main__":
    main()

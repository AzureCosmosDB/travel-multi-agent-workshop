#!/usr/bin/env python3
"""Export a pre-baked "golden" demo dataset from a live Cosmos account.

The base app data (users, places, trips, memories) is already committed as offline
JSON and loaded by ``seed_data.py`` with no LLM. What was missing is the *generated*
data — conversation history and the analytics signal — which otherwise forces every
attendee/demo user to run the expensive, slow LLM ``data_generator`` + enricher.

This maintainer tool captures that generated data **once** from a live deployment so it
can be committed and replayed offline:

    Sessions   -> data/sessions.json
    Messages   -> data/messages.json
    Debug      -> data/debug.json            (02_completed deep per-turn telemetry)
    Debug      -> data/optimization_turns.json + OptimizationTurns container

``OptimizationTurns`` is **derived from the real ``Debug`` telemetry** (actual
input/output/cached tokens, model tier, deployment, timestamp) — not synthesized — so
the analytics/optimization + Fabric modules have authentic data with zero LLM. It also
upserts the derived turns back into the live ``OptimizationTurns`` container so the
source account's analytics + Fabric mirror work immediately.

Run once from ``<tree>/python`` with the account you generated data against:

    python data/export_conversations.py            # export + write OptimizationTurns
    python data/export_conversations.py --no-write  # export JSON only

Then commit the produced ``data/*.json`` files. Cosmos system fields (_rid/_self/_etag/
_attachments/_ts) are stripped so the JSON is clean and portable across accounts.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# Windows consoles default to cp1252 and raise UnicodeEncodeError on emoji in prints.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent
_SYS_FIELDS = ("_rid", "_self", "_etag", "_attachments", "_ts")


def _clean(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in _SYS_FIELDS}


def _bag(doc: dict[str, Any]) -> dict[str, Any]:
    pb = doc.get("propertyBag")
    return {i["key"]: i["value"] for i in pb} if isinstance(pb, list) else (pb or {})


def _dump(name: str, rows: list[dict[str, Any]]) -> None:
    path = DATA_DIR / name
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"   \u2705 wrote {len(rows):>5} records -> {name}")


def _query_all(container) -> list[dict[str, Any]]:
    return list(container.query_items("SELECT * FROM c", enable_cross_partition_query=True))


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _epoch(iso: Any) -> int:
    """Convert an ISO-8601 timeStamp to epoch seconds (0 if unparseable).

    OptimizationTurns time-series visuals should key off this real turn time, NOT the
    Cosmos ``_ts`` (which for the offline seed is the single moment the rows were written,
    so it collapses every turn into one minute).
    """
    if not iso:
        return 0
    try:
        from datetime import datetime, timezone

        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
                   .astimezone(timezone.utc).timestamp())
    except (ValueError, TypeError):
        return 0


def derive_optimization_turn(doc: dict[str, Any]) -> dict[str, Any]:
    """Flatten one Debug telemetry doc into an OptimizationTurns record (authentic)."""
    bag = _bag(doc)
    base_id = doc.get("debugLogId") or doc.get("id") or uuid.uuid4().hex
    ts = doc.get("timeStamp")
    return {
        "id": f"turn-{base_id}",
        "type": "optimization_turn",
        "tenantId": doc.get("tenantId"),
        "userId": doc.get("userId"),
        "sessionId": doc.get("sessionId"),
        "complexity_tier": bag.get("complexity_tier", "default"),
        "model_deployment": bag.get("model_deployment", "Unknown"),
        "model_name": bag.get("model_name", "Unknown"),
        "input_tokens": _int(bag.get("input_tokens")),
        "output_tokens": _int(bag.get("output_tokens")),
        "total_tokens": _int(bag.get("total_tokens")),
        "cached_tokens": _int(bag.get("cached_tokens")),
        "handoff_count": _int(bag.get("handoff_count")),
        "agent_path": bag.get("agent_path"),
        "timeStamp": ts,
        "turn_epoch": _epoch(ts),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-write", action="store_true",
                    help="only export JSON; do not upsert derived turns into OptimizationTurns")
    args = ap.parse_args()

    endpoint = os.getenv("COSMOSDB_ENDPOINT")
    db_name = os.getenv("COSMOSDB_DATABASE_NAME", "TravelAssistant")
    if not endpoint:
        raise SystemExit("COSMOSDB_ENDPOINT not set (source your python/.env)")
    print(f"\U0001F310 {endpoint}  db={db_name}")
    db = CosmosClient(endpoint, DefaultAzureCredential()).get_database_client(db_name)

    print("\n\U0001F4E6 Exporting conversation history...")
    sessions = [_clean(d) for d in _query_all(db.get_container_client("Sessions"))]
    messages = [_clean(d) for d in _query_all(db.get_container_client("Messages"))]
    debug = [_clean(d) for d in _query_all(db.get_container_client("Debug"))]
    _dump("sessions.json", sessions)
    _dump("messages.json", messages)
    _dump("debug.json", debug)

    print("\n\U0001F4CA Deriving OptimizationTurns from Debug telemetry...")
    turns = [derive_optimization_turn(d) for d in debug if d.get("tenantId")]
    _dump("optimization_turns.json", turns)

    if not args.no_write:
        print("\n\u21A9\uFE0F  Upserting derived turns into OptimizationTurns container...")
        cont = db.get_container_client("OptimizationTurns")
        ok = 0
        for t in turns:
            try:
                cont.upsert_item(t)
                ok += 1
            except Exception as exc:  # noqa: BLE001
                print(f"   \u26A0\uFE0F  {t['id']}: {exc}")
        print(f"   \u2705 {ok}/{len(turns)} turns written to OptimizationTurns")

    print("\n\u2705 Export complete. Commit the data/*.json files.")


if __name__ == "__main__":
    main()

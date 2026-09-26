"""Deterministic source fixture for the controlled Demo 4 baseline."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURE_VERSION = "controlled-demo4-v1"
DEFAULT_ANCHOR = "2026-09-24T12:00:00Z"
TURN_COUNT = 200
SESSION_COUNT = 192
CONFIRMED_TRIP_COUNT = 56
WINDOW_MINUTES = 20
CANONICAL_MINUTE_PROFILE = (
    5, 6, 8, 9, 10, 12, 14, 16, 15, 13,
    11, 10, 11, 13, 12, 10, 8, 7, 6, 4,
)
BURST_VERSION = "controlled-demo4-after-v1"
BURST_ANCHOR = "2026-09-24T13:00:00Z"
PRICING_VERSION = "model-pricing-v1"
ROUNDING_TOLERANCE_USD = 0.00005
ROUNDING_TOLERANCE_PCT = 0.05
EVALUATION_FIELDS = (
    "tenant_id",
    "policy_status",
    "dataset_phase",
    "display_state",
    "state_valid",
    "state_reason",
    "measurement_status",
    "fixture_version",
    "burst_version",
    "burst_anchor",
    "burst_window_minutes",
    "baseline_expected_count",
    "baseline_observed_count",
    "baseline_expected_ids",
    "baseline_observed_ids",
    "burst_expected_count",
    "burst_observed_count",
    "burst_expected_ids",
    "burst_observed_ids",
    "model_counts",
    "measurement",
)
MEASUREMENT_FIELDS = (
    "measurement_status",
    "measurement_kind",
    "measurement_scope",
    "measurement_tenant",
    "fixture_version",
    "burst_version",
    "burst_anchor",
    "burst_window_minutes",
    "expected_count",
    "observed_count",
    "observed_ids",
    "manifest_identity",
    "model_counts",
    "pricing_source",
    "pricing_version",
    "pricing_sha256",
    "validation_status",
    "validation_reason",
    "rounding_tolerance_usd",
    "rounding_tolerance_pct",
    "baseline_cost_usd_unrounded",
    "actual_cost_usd_unrounded",
    "saving_usd_unrounded",
    "saving_pct_unrounded",
    "baseline_cost_usd",
    "actual_cost_usd",
    "saving_usd",
    "saving_pct",
    "positive_measured_result",
)
TENANTS = ("analytics", "marvel")
COHORT_CONTAINERS = (
    "OptimizationTurns",
    "Debug",
    "NodeExecutions",
    "Sessions",
    "Messages",
    "Trips",
)
DERIVED_CONTAINERS = ("OptimizationInsights", "OptimizationGovernance")
CONTROLLED_DERIVED_TYPES = frozenset({
    "agent_opportunity",
    "controlled_demo4_derived",
    "controlled_demo4_state",
    "recommendation_card",
    "turn_metrics",
    "funnel_stage",
    "conversion_kpi",
    "abandonment_cause",
    "agent_path_cost",
    "memory_retention",
    "agent_scorecard",
    "memory_kpi",
    "memory_type",
    "memory_salience",
    "memory_health",
    "optimization_result",
    "slo_metric",
    "slo_policy",
})
PREMIUM_DEPLOYMENT = "gpt-5.1"
PREMIUM_MODEL = "gpt-5.1-2025-11-13"
BURST_PROFILES = {
    "complex": {
        "weight": 0.35,
        "deployment": PREMIUM_DEPLOYMENT,
        "model": PREMIUM_MODEL,
    },
    "routine": {
        "weight": 0.55,
        "deployment": "gpt-5-mini",
        "model": "gpt-5-mini-2025-08-07",
    },
    "trivial": {
        "weight": 0.10,
        "deployment": "gpt-5-nano",
        "model": "gpt-5-nano-2025-08-07",
    },
}
OUTCOME_COUNTS = {
    "converted": 56,
    "city_friction": 52,
    "cart_abandon": 36,
    "no_results": 24,
    "search_stall": 16,
    "no_engagement": 8,
}
EXPECTED_FUNNEL = {
    "engaged": 192,
    "searched": 184,
    "planned": 92,
    "confirmed": 56,
}

_IDENTITY_FIELDS = {
    "id",
    "tenantId",
    "userId",
    "sessionId",
    "turnId",
    "debugLogId",
    "messageId",
    "tripId",
}
_TURN_SPECIALIZED_FIELDS = {
    "fixture_version",
    "fixture_ordinal",
    "burst_version",
    "controlled_namespace",
    "burst_ordinal",
    "burst_anchor",
    "burst_count",
    "burst_window_minutes",
    "complexity_tier",
    "model_deployment",
    "model_name",
    "input_tokens",
    "output_tokens",
}


def controlled_fixture_session_prefix(
    tenant: str,
    *,
    fixture_version: str = FIXTURE_VERSION,
) -> str:
    """Return the canonical session prefix owned by one baseline fixture tenant."""
    return f"{fixture_version}-{tenant}-session-"


def controlled_trip_session_prefixes(
    tenant: str,
    *,
    fixture_version: str = FIXTURE_VERSION,
    burst_version: str = BURST_VERSION,
) -> tuple[str, str]:
    """Return every controlled Demo 4 session prefix that can own Trip rows."""
    return (
        controlled_fixture_session_prefix(tenant, fixture_version=fixture_version),
        f"{burst_version}-{tenant}-session-",
    )


def is_controlled_trip(
    row: dict[str, Any],
    tenant: str,
    *,
    fixture_version: str = FIXTURE_VERSION,
    burst_version: str = BURST_VERSION,
) -> bool:
    """Whether a Trip is an exact controlled fixture row, not merely a prefix collision."""
    return is_controlled_fixture_row(
        "Trips",
        row,
        tenant,
        fixture_version=fixture_version,
        burst_version=burst_version,
    )


@lru_cache(maxsize=None)
def _controlled_ids(
    container_name: str,
    tenant: str,
    fixture_version: str,
    burst_version: str,
) -> tuple[frozenset[str], frozenset[str]]:
    baseline = build_tenant_manifest(tenant, fixture_version=fixture_version)
    baseline_ids = frozenset(str(row["id"]) for row in baseline[container_name])
    burst_ids: frozenset[str] = frozenset()
    if tenant == "analytics":
        burst = build_after_burst_manifest(
            tenant=tenant,
            fixture_version=fixture_version,
            burst_version=burst_version,
        )
        burst_ids = frozenset(str(row["id"]) for row in burst[container_name])
    return baseline_ids, burst_ids


def is_controlled_fixture_row(
    container_name: str,
    row: dict[str, Any],
    tenant: str,
    *,
    fixture_version: str = FIXTURE_VERSION,
    burst_version: str = BURST_VERSION,
) -> bool:
    """Return true only for an exact, fully namespaced controlled fixture row."""
    if tenant not in TENANTS or row.get("tenantId") != tenant:
        return False
    if container_name in DERIVED_CONTAINERS:
        return (
            row.get("fixture_version") == fixture_version
            and row.get("controlled_namespace")
            == f"{fixture_version}:derived:{tenant}"
            and row.get("type") in CONTROLLED_DERIVED_TYPES
        )
    if container_name not in COHORT_CONTAINERS:
        return False
    baseline_ids, burst_ids = _controlled_ids(
        container_name, tenant, fixture_version, burst_version
    )
    row_id = str(row.get("id") or "")
    if row_id in baseline_ids:
        return (
            row.get("fixture_version") == fixture_version
            and row.get("burst_version") in (None, "")
        )
    if row_id in burst_ids:
        return (
            row.get("fixture_version") == fixture_version
            and row.get("burst_version") == burst_version
            and row.get("controlled_namespace")
            == f"{fixture_version}:{burst_version}:{tenant}"
        )
    return False


def parse_anchor(value: str) -> datetime:
    """Parse a minute-aligned UTC fixture anchor."""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("anchor must be an ISO-8601 UTC value ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("anchor must be a valid ISO-8601 UTC value") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError("anchor must use UTC")
    if parsed.second or parsed.microsecond:
        raise ValueError("anchor must be aligned to a minute")
    return parsed


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_turn(ordinal: int) -> dict[str, Any]:
    input_tokens = 9000 + ((ordinal * 137) % 12000)
    output_tokens = 350 + ((ordinal * 29) % 900)
    cached_tokens = input_tokens * (60 + ordinal % 25) // 100
    return {
        "ordinal": ordinal,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cached_tokens": cached_tokens,
        "destination": ("Paris", "Tokyo", "Seattle", "London")[ordinal % 4],
    }


CONTROLLED_DEMO4_V1 = tuple(_canonical_turn(ordinal) for ordinal in range(TURN_COUNT))


def _split_int(total: int, count: int) -> list[int]:
    quotient, remainder = divmod(total, count)
    return [quotient + (1 if index < remainder else 0) for index in range(count)]


def _session_for_turn(turn_ordinal: int) -> tuple[int, int]:
    if turn_ordinal < 16:
        return turn_ordinal // 2, turn_ordinal % 2
    return turn_ordinal - 8, 0


def _outcome_for_session(session_ordinal: int) -> str:
    offset = 0
    for outcome, count in OUTCOME_COUNTS.items():
        offset += count
        if session_ordinal < offset:
            return outcome
    raise ValueError(f"session ordinal outside controlled fixture: {session_ordinal}")


def _journey_for_turn(
    outcome: str,
    turn_index: int,
    multi_turn: bool,
) -> tuple[tuple[str, ...], str]:
    if outcome == "converted":
        agents = (
            ("supervisor", "find_places")
            if multi_turn and turn_index == 0
            else ("supervisor", "find_places", "itinerary_generator")
        )
        return agents, "Your itinerary is ready and the trip is confirmed."
    if outcome == "city_friction":
        return ("supervisor", "find_places"), "Which city is that hotel in?"
    if outcome == "cart_abandon":
        return (
            "supervisor",
            "find_places",
            "itinerary_generator",
        ), "Here is your complete itinerary. Shall I book it?"
    if outcome == "no_results":
        return ("supervisor", "find_places"), "I couldn't find any matching places for that search."
    if outcome == "search_stall":
        return ("supervisor", "find_places"), "I found several options. Tell me how you want to continue."
    return ("supervisor",), "Happy to help. Where would you like to go?"


def build_tenant_manifest(
    tenant: str,
    *,
    fixture_version: str = FIXTURE_VERSION,
    anchor: str = DEFAULT_ANCHOR,
    count: int = TURN_COUNT,
) -> dict[str, list[dict[str, Any]]]:
    """Build the exact six-container baseline manifest for one controlled tenant."""
    if tenant not in TENANTS:
        raise ValueError(f"unsupported controlled tenant: {tenant}")
    if fixture_version != FIXTURE_VERSION:
        raise ValueError(f"unsupported fixture version: {fixture_version}")
    if count != TURN_COUNT:
        raise ValueError(f"controlled fixture count must be exactly {TURN_COUNT}")
    anchor_dt = parse_anchor(anchor)

    manifest = {name: [] for name in COHORT_CONTAINERS}
    session_turns: dict[int, list[tuple[dict[str, Any], str]]] = {
        ordinal: [] for ordinal in range(SESSION_COUNT)
    }
    for canonical in CONTROLLED_DEMO4_V1:
        ordinal = canonical["ordinal"]
        session_ordinal, turn_index = _session_for_turn(ordinal)
        outcome = _outcome_for_session(session_ordinal)
        agents, message_content = _journey_for_turn(
            outcome,
            turn_index,
            multi_turn=session_ordinal < 8,
        )
        agent_path = ",".join(agents)
        handoff_count = len(agents) - 1
        timestamp_dt = _profile_timestamp(anchor_dt, ordinal)
        timestamp = _iso(timestamp_dt)
        turn_epoch = int(timestamp_dt.timestamp())
        turn_suffix = f"{ordinal:03d}"
        session_suffix = f"{session_ordinal:03d}"
        user_id = f"{fixture_version}-{tenant}-user-{session_suffix}"
        session_id = f"{fixture_version}-{tenant}-session-{session_suffix}"
        turn_id = f"{fixture_version}-{tenant}-turn-{turn_suffix}"
        debug_id = f"{fixture_version}-{tenant}-debug-{turn_suffix}"
        node_id = f"{fixture_version}-{tenant}-nodes-{turn_suffix}"
        message_id = f"{fixture_version}-{tenant}-message-{turn_suffix}"

        turn = {
            "id": turn_id,
            "type": "optimization_turn",
            "fixture_version": fixture_version,
            "fixture_ordinal": ordinal,
            "session_ordinal": session_ordinal,
            "session_outcome": outcome,
            "tenantId": tenant,
            "userId": user_id,
            "sessionId": session_id,
            "debugLogId": debug_id,
            "complexity_tier": "default",
            "model_deployment": PREMIUM_DEPLOYMENT,
            "model_name": PREMIUM_MODEL,
            "input_tokens": canonical["input_tokens"],
            "output_tokens": canonical["output_tokens"],
            "total_tokens": canonical["total_tokens"],
            "cached_tokens": canonical["cached_tokens"],
            "handoff_count": handoff_count,
            "agent_path": agent_path,
            "timeStamp": timestamp,
            "turn_epoch": turn_epoch,
        }
        bag_values = {
            "agent_selected": agents[-1],
            "model_deployment": PREMIUM_DEPLOYMENT,
            "model_name": PREMIUM_MODEL,
            "complexity_tier": "default",
            "model_tier": "default",
            "input_tokens": canonical["input_tokens"],
            "output_tokens": canonical["output_tokens"],
            "total_tokens": canonical["total_tokens"],
            "cached_tokens": canonical["cached_tokens"],
            "handoff_count": handoff_count,
            "agent_path": agent_path,
            "tool_calls": "[]",
            "turn_epoch": turn_epoch,
        }
        debug = {
            "id": debug_id,
            "debugLogId": debug_id,
            "messageId": message_id,
            "turnId": turn_id,
            "type": "debug_log",
            "fixture_version": fixture_version,
            "fixture_ordinal": ordinal,
            "session_ordinal": session_ordinal,
            "session_outcome": outcome,
            "tenantId": tenant,
            "userId": user_id,
            "sessionId": session_id,
            "timeStamp": timestamp,
            "turn_epoch": turn_epoch,
            "propertyBag": [
                {"key": key, "value": value, "timeStamp": timestamp}
                for key, value in bag_values.items()
            ],
        }
        input_parts = _split_int(canonical["input_tokens"], len(agents))
        output_parts = _split_int(canonical["output_tokens"], len(agents))
        cached_parts = _split_int(canonical["cached_tokens"], len(agents))
        node_execution = {
            "id": node_id,
            "fixture_version": fixture_version,
            "fixture_ordinal": ordinal,
            "session_ordinal": session_ordinal,
            "session_outcome": outcome,
            "tenantId": tenant,
            "userId": user_id,
            "sessionId": session_id,
            "turnId": turn_id,
            "debugLogId": debug_id,
            "nodeExecutions": [
                {
                    "seq": index,
                    "agent": agent,
                    "model_deployment": PREMIUM_DEPLOYMENT,
                    "model_name": PREMIUM_MODEL,
                    "input_tokens": input_parts[index],
                    "output_tokens": output_parts[index],
                    "cached_tokens": cached_parts[index],
                    "tool_calls": 0,
                    "recall_used": False,
                }
                for index, agent in enumerate(agents)
            ],
            "nodeCount": len(agents),
            "timeStamp": timestamp,
            "turn_epoch": turn_epoch,
        }
        message = {
            "id": message_id,
            "messageId": message_id,
            "fixture_version": fixture_version,
            "fixture_ordinal": ordinal,
            "session_ordinal": session_ordinal,
            "session_outcome": outcome,
            "tenantId": tenant,
            "userId": user_id,
            "sessionId": session_id,
            "turnId": turn_id,
            "role": "assistant",
            "content": message_content,
            "toolCalls": [],
            "ts": timestamp,
            "timeStamp": timestamp,
            "keywords": ["controlled", outcome, canonical["destination"].lower()],
            "superseded": False,
        }
        manifest["OptimizationTurns"].append(turn)
        manifest["Debug"].append(debug)
        manifest["NodeExecutions"].append(node_execution)
        manifest["Messages"].append(message)
        session_turns[session_ordinal].append((turn, message_id))

    for session_ordinal, linked_turns in session_turns.items():
        first_turn = linked_turns[0][0]
        last_turn = linked_turns[-1][0]
        session_id = first_turn["sessionId"]
        user_id = first_turn["userId"]
        outcome = first_turn["session_outcome"]
        session_suffix = f"{session_ordinal:03d}"
        manifest["Sessions"].append({
            "id": session_id,
            "sessionId": session_id,
            "fixture_version": fixture_version,
            "fixture_ordinal": session_ordinal,
            "session_outcome": outcome,
            "tenantId": tenant,
            "userId": user_id,
            "title": f"Controlled Demo 4 journey {session_suffix}",
            "activeAgent": "orchestrator",
            "createdAt": first_turn["timeStamp"],
            "lastActivityAt": last_turn["timeStamp"],
            "status": "active",
            "messageCount": len(linked_turns),
        })
        if outcome == "converted":
            trip_id = f"{fixture_version}-{tenant}-trip-{session_suffix}"
            manifest["Trips"].append({
                "id": trip_id,
                "tripId": trip_id,
                "fixture_version": fixture_version,
                "fixture_ordinal": session_ordinal,
                "session_outcome": outcome,
                "tenantId": tenant,
                "userId": user_id,
                "sessionId": session_id,
                "turnId": last_turn["id"],
                "destination": CONTROLLED_DEMO4_V1[last_turn["fixture_ordinal"]]["destination"],
                "startDate": "2027-01-10",
                "endDate": "2027-01-12",
                "tripDuration": 3,
                "status": "confirmed",
                "days": [],
                "createdAt": last_turn["timeStamp"],
                "updatedAt": last_turn["timeStamp"],
                "timeStamp": last_turn["timeStamp"],
            })
    return manifest


def allocate_burst_tiers(count: int) -> dict[str, int]:
    """Allocate the 10/55/35 model mix with largest remainder and stable name ties."""
    if not isinstance(count, int) or isinstance(count, bool) or count < 1 or count > TURN_COUNT:
        raise ValueError(f"controlled burst count must be between 1 and {TURN_COUNT}")
    exact = {
        tier: count * profile["weight"]
        for tier, profile in BURST_PROFILES.items()
    }
    allocated = {tier: int(value) for tier, value in exact.items()}
    remaining = count - sum(allocated.values())
    order = sorted(exact, key=lambda tier: (-(exact[tier] - allocated[tier]), tier))
    for tier in order[:remaining]:
        allocated[tier] += 1
    return allocated


def _tier_ordinals(count: int) -> list[str]:
    targets = allocate_burst_tiers(count)
    used = {tier: 0 for tier in targets}
    result: list[str] = []
    for ordinal in range(count):
        tier = min(
            targets,
            key=lambda name: (
                -((ordinal + 1) * targets[name] / count - used[name]),
                name,
            ),
        )
        used[tier] += 1
        result.append(tier)
    if used != targets:
        raise RuntimeError(f"controlled tier allocation drifted: {used} != {targets}")
    return result


def _burst_timestamp(anchor: datetime, ordinal: int, count: int, window_minutes: int) -> datetime:
    minute = (ordinal * window_minutes) // count
    indexes = [
        index
        for index in range(count)
        if (index * window_minutes) // count == minute
    ]
    position = indexes.index(ordinal)
    second = (position * 60) // max(len(indexes), 1)
    return anchor + timedelta(minutes=minute, seconds=second)


def _profile_timestamp(anchor: datetime, ordinal: int) -> datetime:
    offset = ordinal
    for minute, bucket_count in enumerate(CANONICAL_MINUTE_PROFILE):
        if offset < bucket_count:
            second = (offset * 60) // bucket_count
            return anchor + timedelta(minutes=minute, seconds=second)
        offset -= bucket_count
    raise ValueError(f"profile ordinal must be between 0 and {sum(CANONICAL_MINUTE_PROFILE) - 1}")


def build_after_burst_manifest(
    *,
    tenant: str = "analytics",
    fixture_version: str = FIXTURE_VERSION,
    burst_version: str = BURST_VERSION,
    anchor: str = BURST_ANCHOR,
    count: int = TURN_COUNT,
    window_minutes: int = WINDOW_MINUTES,
) -> dict[str, list[dict[str, Any]]]:
    """Build the deterministic Analytics after-burst from the canonical business workload."""
    if tenant != "analytics":
        raise ValueError("controlled traffic is supported only for tenant 'analytics'")
    if fixture_version != FIXTURE_VERSION:
        raise ValueError(f"unsupported fixture version: {fixture_version}")
    if not isinstance(burst_version, str) or not burst_version.strip():
        raise ValueError("burst version must be non-empty")
    if not isinstance(window_minutes, int) or isinstance(window_minutes, bool) or window_minutes < 1:
        raise ValueError("controlled burst window must be a positive integer")
    anchor_dt = parse_anchor(anchor)
    tiers = _tier_ordinals(count)
    baseline = build_tenant_manifest(tenant)  # canonical workload; identity is replaced below
    selected_turns = baseline["OptimizationTurns"][:count]
    selected_session_ids = {turn["sessionId"] for turn in selected_turns}
    namespace = f"{fixture_version}:{burst_version}:{tenant}"

    manifest = {name: [] for name in COHORT_CONTAINERS}
    timestamps: dict[int, str] = {}
    epochs: dict[int, int] = {}
    turn_ids: dict[int, str] = {}
    debug_ids: dict[int, str] = {}
    message_ids: dict[int, str] = {}
    session_ids: dict[str, str] = {}
    user_ids: dict[str, str] = {}
    session_ordinals = {
        session_id: index
        for index, session_id in enumerate(
            dict.fromkeys(turn["sessionId"] for turn in selected_turns)
        )
    }
    for old_session_id, session_ordinal in session_ordinals.items():
        suffix = f"{session_ordinal:03d}"
        session_ids[old_session_id] = f"{burst_version}-{tenant}-session-{suffix}"
        user_ids[old_session_id] = f"{burst_version}-{tenant}-user-{suffix}"

    for ordinal, baseline_turn in enumerate(selected_turns):
        timestamp_dt = (
            _profile_timestamp(anchor_dt, ordinal)
            if count == TURN_COUNT and window_minutes == WINDOW_MINUTES
            else _burst_timestamp(anchor_dt, ordinal, count, window_minutes)
        )
        timestamps[ordinal] = _iso(timestamp_dt)
        epochs[ordinal] = int(timestamp_dt.timestamp())
        suffix = f"{ordinal:03d}"
        turn_ids[ordinal] = f"{burst_version}-{tenant}-turn-{suffix}"
        debug_ids[ordinal] = f"{burst_version}-{tenant}-debug-{suffix}"
        message_ids[ordinal] = f"{burst_version}-{tenant}-message-{suffix}"

        tier = tiers[ordinal]
        profile = BURST_PROFILES[tier]
        old_session_id = baseline_turn["sessionId"]
        turn = copy.deepcopy(baseline_turn)
        turn.update({
            "id": turn_ids[ordinal],
            "fixture_version": fixture_version,
            "burst_version": burst_version,
            "controlled_namespace": namespace,
            "burst_ordinal": ordinal,
            "burst_anchor": anchor,
            "burst_count": count,
            "burst_window_minutes": window_minutes,
            "tenantId": tenant,
            "userId": user_ids[old_session_id],
            "sessionId": session_ids[old_session_id],
            "debugLogId": debug_ids[ordinal],
            "complexity_tier": tier,
            "model_deployment": profile["deployment"],
            "model_name": profile["model"],
            "timeStamp": timestamps[ordinal],
            "turn_epoch": epochs[ordinal],
        })
        manifest["OptimizationTurns"].append(turn)

        debug = copy.deepcopy(baseline["Debug"][ordinal])
        debug.update({
            "id": debug_ids[ordinal],
            "debugLogId": debug_ids[ordinal],
            "messageId": message_ids[ordinal],
            "turnId": turn_ids[ordinal],
            "fixture_version": fixture_version,
            "burst_version": burst_version,
            "controlled_namespace": namespace,
            "burst_ordinal": ordinal,
            "burst_anchor": anchor,
            "burst_count": count,
            "burst_window_minutes": window_minutes,
            "userId": user_ids[old_session_id],
            "sessionId": session_ids[old_session_id],
            "timeStamp": timestamps[ordinal],
            "turn_epoch": epochs[ordinal],
        })
        bag_updates = {
            "model_deployment": profile["deployment"],
            "model_name": profile["model"],
            "complexity_tier": tier,
            "model_tier": tier,
            "turn_epoch": epochs[ordinal],
        }
        for item in debug["propertyBag"]:
            if item["key"] in bag_updates:
                item["value"] = bag_updates[item["key"]]
            item["timeStamp"] = timestamps[ordinal]
        manifest["Debug"].append(debug)

        nodes = copy.deepcopy(baseline["NodeExecutions"][ordinal])
        nodes.update({
            "id": f"{burst_version}-{tenant}-nodes-{suffix}",
            "turnId": turn_ids[ordinal],
            "debugLogId": debug_ids[ordinal],
            "fixture_version": fixture_version,
            "burst_version": burst_version,
            "controlled_namespace": namespace,
            "burst_ordinal": ordinal,
            "burst_anchor": anchor,
            "burst_count": count,
            "burst_window_minutes": window_minutes,
            "userId": user_ids[old_session_id],
            "sessionId": session_ids[old_session_id],
            "timeStamp": timestamps[ordinal],
            "turn_epoch": epochs[ordinal],
        })
        for node in nodes["nodeExecutions"]:
            node["model_deployment"] = profile["deployment"]
            node["model_name"] = profile["model"]
        manifest["NodeExecutions"].append(nodes)

        message = copy.deepcopy(baseline["Messages"][ordinal])
        message.update({
            "id": message_ids[ordinal],
            "messageId": message_ids[ordinal],
            "turnId": turn_ids[ordinal],
            "fixture_version": fixture_version,
            "burst_version": burst_version,
            "controlled_namespace": namespace,
            "burst_ordinal": ordinal,
            "burst_anchor": anchor,
            "burst_count": count,
            "burst_window_minutes": window_minutes,
            "userId": user_ids[old_session_id],
            "sessionId": session_ids[old_session_id],
            "ts": timestamps[ordinal],
            "timeStamp": timestamps[ordinal],
        })
        manifest["Messages"].append(message)

    turns_by_old_session: dict[str, list[int]] = {}
    for ordinal, turn in enumerate(selected_turns):
        turns_by_old_session.setdefault(turn["sessionId"], []).append(ordinal)
    for baseline_session in baseline["Sessions"]:
        old_session_id = baseline_session["sessionId"]
        if old_session_id not in selected_session_ids:
            continue
        ordinals = turns_by_old_session[old_session_id]
        session_ordinal = session_ordinals[old_session_id]
        session = copy.deepcopy(baseline_session)
        session.update({
            "id": session_ids[old_session_id],
            "sessionId": session_ids[old_session_id],
            "fixture_version": fixture_version,
            "burst_version": burst_version,
            "controlled_namespace": namespace,
            "burst_ordinal": session_ordinal,
            "burst_anchor": anchor,
            "burst_count": count,
            "burst_window_minutes": window_minutes,
            "userId": user_ids[old_session_id],
            "createdAt": timestamps[ordinals[0]],
            "lastActivityAt": timestamps[ordinals[-1]],
            "messageCount": len(ordinals),
        })
        manifest["Sessions"].append(session)

    trip_by_session = {trip["sessionId"]: trip for trip in baseline["Trips"]}
    for old_session_id, ordinals in turns_by_old_session.items():
        if old_session_id not in trip_by_session:
            continue
        session_ordinal = session_ordinals[old_session_id]
        last_ordinal = ordinals[-1]
        trip = copy.deepcopy(trip_by_session[old_session_id])
        trip_id = f"{burst_version}-{tenant}-trip-{session_ordinal:03d}"
        trip.update({
            "id": trip_id,
            "tripId": trip_id,
            "fixture_version": fixture_version,
            "burst_version": burst_version,
            "controlled_namespace": namespace,
            "burst_ordinal": session_ordinal,
            "burst_anchor": anchor,
            "burst_count": count,
            "burst_window_minutes": window_minutes,
            "userId": user_ids[old_session_id],
            "sessionId": session_ids[old_session_id],
            "turnId": turn_ids[last_ordinal],
            "createdAt": timestamps[last_ordinal],
            "updatedAt": timestamps[last_ordinal],
            "timeStamp": timestamps[last_ordinal],
        })
        manifest["Trips"].append(trip)

    for rows in manifest.values():
        rows.sort(key=lambda item: item["id"])
    return manifest


def _normalized(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _normalized(item)
            for key, item in sorted(value.items())
            if key not in _IDENTITY_FIELDS and not key.startswith("_")
        }
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    return value


def normalized_fingerprint(manifest: dict[str, list[dict[str, Any]]]) -> str:
    """Hash a manifest after removing tenant/document identity and Cosmos metadata."""
    normalized = {
        name: [_normalized(copy.deepcopy(item)) for item in items]
        for name, items in sorted(manifest.items())
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _invalid_evaluation(
    tenant: str,
    policy_status: str,
    reason: str,
    *,
    baseline_expected_ids: list[str] | None = None,
    baseline_observed_ids: list[str] | None = None,
    burst_expected_ids: list[str] | None = None,
    burst_observed_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "policy_status": policy_status,
        "dataset_phase": "invalid",
        "display_state": "Invalid controlled dataset",
        "state_valid": False,
        "state_reason": reason,
        "measurement_status": "invalid" if reason else "missing",
        "fixture_version": FIXTURE_VERSION,
        "burst_version": BURST_VERSION if tenant == "analytics" else None,
        "burst_anchor": BURST_ANCHOR if tenant == "analytics" else None,
        "burst_window_minutes": WINDOW_MINUTES if tenant == "analytics" else None,
        "baseline_expected_count": len(baseline_expected_ids or []),
        "baseline_observed_count": len(baseline_observed_ids or []),
        "baseline_expected_ids": baseline_expected_ids or [],
        "baseline_observed_ids": baseline_observed_ids or [],
        "burst_expected_count": len(burst_expected_ids or []),
        "burst_observed_count": len(burst_observed_ids or []),
        "burst_expected_ids": burst_expected_ids or [],
        "burst_observed_ids": burst_observed_ids or [],
        "model_counts": {},
        "measurement": None,
    }


def _query_controlled_rows(
    db: Any,
    container_name: str,
    tenant: str,
) -> list[dict[str, Any]]:
    container = db.get_container_client(container_name)
    return list(container.query_items(
        query="SELECT * FROM c WHERE c.tenantId=@tenant",
        parameters=[{"name": "@tenant", "value": tenant}],
        enable_cross_partition_query=True,
    ))


def _raw_policy_status(db: Any, tenant: str) -> str:
    try:
        policy = db.get_container_client("OptimizationPolicies").read_item(
            item=f"{tenant}::model-selection",
            partition_key="model-selection",
        )
        return str(policy.get("status") or "not_proposed")
    except Exception:  # noqa: BLE001
        return "not_proposed"


def _group_expected_rows(
    rows: list[dict[str, Any]],
    expected_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], list[str], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row_id = row.get("id")
        if row_id in expected_ids:
            grouped.setdefault(str(row_id), []).append(row)
    duplicates = sorted(row_id for row_id, values in grouped.items() if len(values) > 1)
    conflicts = sorted(
        row_id
        for row_id, values in grouped.items()
        if len(values) > 1
        and any(
            json.dumps(value, sort_keys=True, default=str)
            != json.dumps(values[0], sort_keys=True, default=str)
            for value in values[1:]
        )
    )
    return {row_id: values[0] for row_id, values in grouped.items()}, duplicates, conflicts


def _contains_expected(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains_expected(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _contains_expected(actual_item, expected_item)
                for actual_item, expected_item in zip(actual, expected)
            )
        )
    return actual == expected


def _validate_manifest(
    db: Any,
    tenant: str,
    manifest: dict[str, list[dict[str, Any]]],
    phase: str,
) -> tuple[dict[str, dict[str, dict[str, Any]]], str | None]:
    observed: dict[str, dict[str, dict[str, Any]]] = {}
    first_error: str | None = None
    for container_name in COHORT_CONTAINERS:
        expected = {row["id"]: row for row in manifest[container_name]}
        rows = _query_controlled_rows(db, container_name, tenant)
        grouped, duplicates, conflicts = _group_expected_rows(rows, set(expected))
        observed[container_name] = grouped
        label = f"{phase} {container_name}"
        if conflicts:
            first_error = first_error or (
                f"conflicting expected {phase} IDs in {container_name}: "
                f"{', '.join(conflicts)}"
            )
            continue
        if duplicates:
            first_error = first_error or (
                f"duplicate expected {phase} IDs in {container_name}: "
                f"{', '.join(duplicates)}"
            )
            continue
        missing = sorted(set(expected) - set(grouped))
        if missing:
            first_error = first_error or (
                f"missing expected {phase} IDs in {container_name}: "
                f"{', '.join(missing)}"
            )
            continue
        for row_id, actual in grouped.items():
            expected_row = expected[row_id]
            if container_name == "OptimizationTurns":
                expected_row = {
                    key: value
                    for key, value in expected_row.items()
                    if key not in _TURN_SPECIALIZED_FIELDS
                }
            if not _contains_expected(actual, expected_row):
                first_error = first_error or (
                    f"{label} metadata/linkage mismatch for {row_id}"
                )
                break
    return observed, first_error


def _token_decimal(row: dict[str, Any], field: str) -> Decimal:
    if field not in row or isinstance(row[field], bool) or not isinstance(row[field], (int, float, Decimal)):
        raise ValueError(f"{row.get('id', '<unknown>')} has missing/non-numeric {field}")
    try:
        value = Decimal(str(row[field]))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{row.get('id', '<unknown>')} has missing/non-numeric {field}") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{row.get('id', '<unknown>')} has negative/non-finite {field}")
    return value


def _canonical_controlled_deployment(row: dict[str, Any]) -> str:
    deployment = row.get("model_deployment")
    model = row.get("model_name")
    if deployment in {PREMIUM_DEPLOYMENT, PREMIUM_MODEL} and model in {
        PREMIUM_DEPLOYMENT,
        PREMIUM_MODEL,
    }:
        return PREMIUM_DEPLOYMENT
    exact = {
        ("gpt-5-mini", "gpt-5-mini-2025-08-07"): "gpt-5-mini",
        ("gpt-5-nano", "gpt-5-nano-2025-08-07"): "gpt-5-nano",
    }
    canonical = exact.get((deployment, model))
    if canonical is None:
        raise ValueError(
            f"{row.get('id', '<unknown>')} has unknown or conflicting deployment/model "
            f"{deployment!r}/{model!r}"
        )
    return canonical


def _load_checked_in_pricing() -> tuple[dict[str, dict[str, Decimal]], str, str]:
    embedded = globals().get("CONTROLLED_DEMO4_EMBEDDED_PRICING")
    if embedded is not None:
        raw = embedded
        payload = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
        source = str(
            globals().get(
                "CONTROLLED_DEMO4_EMBEDDED_PRICING_SOURCE",
                "embedded python/data/model_pricing.json",
            )
        )
        pricing_hash = str(
            globals().get(
                "CONTROLLED_DEMO4_EMBEDDED_PRICING_SHA256",
                hashlib.sha256(payload).hexdigest(),
            )
        )
        pricing = {
            model: {
                "input": Decimal(str(values["input"])),
                "output": Decimal(str(values["output"])),
            }
            for model, values in raw.items()
        }
        return pricing, source, pricing_hash
    path = Path(__file__).resolve().parents[3] / "data" / "model_pricing.json"
    payload = path.read_bytes()
    raw = json.loads(payload)
    pricing = {
        model: {
            "input": Decimal(str(values["input"])),
            "output": Decimal(str(values["output"])),
        }
        for model, values in raw.items()
    }
    return pricing, r"python\data\model_pricing.json", hashlib.sha256(payload).hexdigest()


def _build_measurement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pricing, pricing_source, pricing_hash = _load_checked_in_pricing()
    premium = pricing[PREMIUM_DEPLOYMENT]
    baseline_cost = Decimal("0")
    actual_cost = Decimal("0")
    model_counts: Counter[str] = Counter()
    for row in rows:
        deployment = _canonical_controlled_deployment(row)
        if deployment not in pricing:
            raise ValueError(f"{row.get('id', '<unknown>')} uses unpriced deployment {deployment}")
        input_tokens = _token_decimal(row, "input_tokens")
        output_tokens = _token_decimal(row, "output_tokens")
        baseline_cost += (
            input_tokens * premium["input"] + output_tokens * premium["output"]
        ) / Decimal("1000000")
        actual = pricing[deployment]
        actual_cost += (
            input_tokens * actual["input"] + output_tokens * actual["output"]
        ) / Decimal("1000000")
        model_counts[deployment] += 1
    saving = baseline_cost - actual_cost
    saving_pct = (
        Decimal("100") * saving / baseline_cost
        if baseline_cost > 0
        else Decimal("0")
    )
    positive = baseline_cost > 0 and actual_cost < baseline_cost
    return {
        "measurement_status": "measured",
        "measurement_kind": "Measured",
        "measurement_scope": "Analytics controlled after burst",
        "measurement_tenant": "analytics",
        "fixture_version": FIXTURE_VERSION,
        "burst_version": BURST_VERSION,
        "burst_anchor": BURST_ANCHOR,
        "burst_window_minutes": WINDOW_MINUTES,
        "expected_count": TURN_COUNT,
        "observed_count": len(rows),
        "observed_ids": sorted(str(row["id"]) for row in rows),
        "manifest_identity": f"{FIXTURE_VERSION}:{BURST_VERSION}:analytics",
        "model_counts": dict(sorted(model_counts.items())),
        "pricing_source": pricing_source,
        "pricing_version": PRICING_VERSION,
        "pricing_sha256": pricing_hash,
        "validation_status": "valid",
        "validation_reason": (
            "complete controlled burst priced below all-premium baseline"
            if positive
            else "complete controlled burst has zero measured saving"
        ),
        "rounding_tolerance_usd": ROUNDING_TOLERANCE_USD,
        "rounding_tolerance_pct": ROUNDING_TOLERANCE_PCT,
        "baseline_cost_usd_unrounded": str(baseline_cost),
        "actual_cost_usd_unrounded": str(actual_cost),
        "saving_usd_unrounded": str(saving),
        "saving_pct_unrounded": str(saving_pct),
        "baseline_cost_usd": round(float(baseline_cost), 4),
        "actual_cost_usd": round(float(actual_cost), 4),
        "saving_usd": round(float(saving), 4),
        "saving_pct": round(float(saving_pct), 1),
        "positive_measured_result": positive,
    }


def evaluate_controlled_demo4(
    db: Any,
    tenant: str,
    *,
    policy_status: str | None = None,
) -> dict[str, Any]:
    """Total source-derived state and measurement evaluator for controlled Demo 4."""
    raw_policy_status = str(policy_status or _raw_policy_status(db, tenant))
    if tenant not in TENANTS:
        return _invalid_evaluation(tenant, raw_policy_status, f"unsupported controlled tenant: {tenant}")
    try:
        baseline_manifest = build_tenant_manifest(tenant)
        baseline_observed, baseline_error = _validate_manifest(
            db, tenant, baseline_manifest, "baseline"
        )
        baseline_rows = baseline_manifest["OptimizationTurns"]
        baseline_expected = {row["id"]: row for row in baseline_rows}
        observed_baseline = baseline_observed["OptimizationTurns"]
        baseline_expected_ids = sorted(baseline_expected)
        baseline_observed_ids = sorted(observed_baseline)
        if baseline_error:
            return _invalid_evaluation(
                tenant, raw_policy_status, baseline_error,
                baseline_expected_ids=baseline_expected_ids,
                baseline_observed_ids=baseline_observed_ids,
            )
        for row_id, observed in observed_baseline.items():
            expected = baseline_expected[row_id]
            if (
                observed.get("fixture_version") != FIXTURE_VERSION
                or observed.get("fixture_ordinal") != expected["fixture_ordinal"]
                or observed.get("complexity_tier") != "default"
                or _canonical_controlled_deployment(observed) != PREMIUM_DEPLOYMENT
            ):
                return _invalid_evaluation(
                    tenant, raw_policy_status, f"baseline metadata/model mismatch for {row_id}",
                    baseline_expected_ids=baseline_expected_ids,
                    baseline_observed_ids=baseline_observed_ids,
                )
            _token_decimal(observed, "input_tokens")
            _token_decimal(observed, "output_tokens")

        if tenant == "marvel":
            return {
                **_invalid_evaluation(
                    tenant, raw_policy_status, "",
                    baseline_expected_ids=baseline_expected_ids,
                    baseline_observed_ids=baseline_observed_ids,
                ),
                "dataset_phase": "before",
                "display_state": "Not Applied · Before",
                "state_valid": True,
                "state_reason": "complete all-premium Marvel baseline",
                "measurement_status": "missing",
            }

        burst_manifest = build_after_burst_manifest()
        burst_observed, burst_error = _validate_manifest(
            db, tenant, burst_manifest, "burst"
        )
        burst_rows = burst_manifest["OptimizationTurns"]
        burst_expected = {row["id"]: row for row in burst_rows}
        observed_burst = burst_observed["OptimizationTurns"]
        burst_expected_ids = sorted(burst_expected)
        burst_observed_ids = sorted(observed_burst)
        common = {
            "baseline_expected_ids": baseline_expected_ids,
            "baseline_observed_ids": baseline_observed_ids,
            "burst_expected_ids": burst_expected_ids,
            "burst_observed_ids": burst_observed_ids,
        }
        any_burst_rows = any(rows for rows in burst_observed.values())
        if any_burst_rows and burst_error:
            return _invalid_evaluation(
                tenant, raw_policy_status, burst_error, **common
            )
        if not any_burst_rows:
            display = (
                "Policy Active · Awaiting Traffic · Before"
                if raw_policy_status == "active"
                else "Not Applied · Before"
            )
            result = _invalid_evaluation(tenant, raw_policy_status, "", **common)
            result.update({
                "dataset_phase": "before",
                "display_state": display,
                "state_valid": True,
                "state_reason": "complete all-premium Analytics baseline; no controlled after burst",
                "measurement_status": "missing",
            })
            return result
        if burst_error:
            return _invalid_evaluation(
                tenant, raw_policy_status, burst_error, **common
            )

        model_counts: Counter[str] = Counter()
        for row_id, observed in observed_burst.items():
            expected = burst_expected[row_id]
            required = {
                "fixture_version": FIXTURE_VERSION,
                "burst_version": BURST_VERSION,
                "controlled_namespace": f"{FIXTURE_VERSION}:{BURST_VERSION}:analytics",
                "burst_ordinal": expected["burst_ordinal"],
                "burst_anchor": BURST_ANCHOR,
                "burst_count": TURN_COUNT,
                "burst_window_minutes": WINDOW_MINUTES,
                "tenantId": "analytics",
                "complexity_tier": expected["complexity_tier"],
            }
            if any(observed.get(key) != value for key, value in required.items()):
                return _invalid_evaluation(
                    tenant, raw_policy_status, f"burst metadata mismatch for {row_id}", **common
                )
            model_counts[_canonical_controlled_deployment(observed)] += 1
            _token_decimal(observed, "input_tokens")
            _token_decimal(observed, "output_tokens")
        expected_model_counts = {
            BURST_PROFILES[tier]["deployment"]: count
            for tier, count in allocate_burst_tiers(TURN_COUNT).items()
        }
        if dict(model_counts) != expected_model_counts:
            result = _invalid_evaluation(
                tenant, raw_policy_status,
                f"wrong controlled burst model mix: {dict(model_counts)} != {expected_model_counts}",
                **common,
            )
            result["model_counts"] = dict(sorted(model_counts.items()))
            return result
        if raw_policy_status not in {"active", "reverted"}:
            return _invalid_evaluation(
                tenant, raw_policy_status,
                f"complete burst conflicts with unsupported policy lifecycle {raw_policy_status!r}",
                **common,
            )
        measurement = _build_measurement(list(observed_burst.values()))
        result = _invalid_evaluation(tenant, raw_policy_status, "", **common)
        result.update({
            "dataset_phase": "after",
            "display_state": (
                "Applied · After"
                if raw_policy_status == "active"
                else "Policy Reverted · After Traffic Captured"
            ),
            "state_valid": True,
            "state_reason": "complete deterministic Analytics after burst",
            "measurement_status": "measured",
            "model_counts": dict(sorted(model_counts.items())),
            "measurement": measurement,
        })
        return result
    except Exception as exc:  # noqa: BLE001
        return _invalid_evaluation(tenant, raw_policy_status, str(exc))


def assert_evaluation_schema(result: dict[str, Any]) -> None:
    """Reject evaluator drift across app, Fabric notebook, and fixture validators."""
    if tuple(result) != EVALUATION_FIELDS:
        raise AssertionError(
            f"controlled Demo 4 evaluation schema drift: {tuple(result)} != {EVALUATION_FIELDS}"
        )
    measurement = result["measurement"]
    if measurement is not None and tuple(measurement) != MEASUREMENT_FIELDS:
        raise AssertionError(
            "controlled Demo 4 measurement schema drift: "
            f"{tuple(measurement)} != {MEASUREMENT_FIELDS}"
        )

from __future__ import annotations

import ast
import copy
import json
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

cosmos_stub = types.ModuleType("src.app.services.azure_cosmos_db")
cosmos_stub.database = None
cosmos_stub.debug_logs_container = None
cosmos_stub.initialize_cosmos_client = lambda: None
cosmos_stub.record_api_event = lambda **kwargs: None
sys.modules.setdefault("src.app.services.azure_cosmos_db", cosmos_stub)

from src.app.services import demo_data
from src.app.services.controlled_demo4 import (
    BURST_ANCHOR,
    BURST_VERSION,
    CANONICAL_MINUTE_PROFILE,
    COHORT_CONTAINERS,
    FIXTURE_VERSION,
    allocate_burst_tiers,
    build_after_burst_manifest,
    build_tenant_manifest,
)


class FakeContainer:
    def __init__(self, name: str, items=None):
        self.name = name
        self.items = copy.deepcopy(items or [])
        self.queries = []
        self.deletes = []
        self.upserts = []

    def read(self):
        return {"partitionKey": {"paths": ["/tenantId", "/userId", "/sessionId"]}}

    def query_items(self, query, parameters=None, enable_cross_partition_query=False):
        self.queries.append((query, copy.deepcopy(parameters)))
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        rows = self.items
        if "@tenant" in values:
            rows = [row for row in rows if row.get("tenantId") == values["@tenant"]]
        if "@burst_version" in values:
            rows = [row for row in rows if row.get("burst_version") == values["@burst_version"]]
        return copy.deepcopy(rows)

    def delete_item(self, item, partition_key):
        self.deletes.append(item)
        self.items = [row for row in self.items if row["id"] != item]

    def upsert_item(self, item):
        document = copy.deepcopy(item)
        self.upserts.append(document)
        self.items = [row for row in self.items if row["id"] != document["id"]]
        self.items.append(document)
        return document


class FakePolicyContainer:
    def __init__(self, active: bool):
        self.active = active
        self.reads = 0
        self.items = []

    def read_item(self, item, partition_key):
        self.reads += 1
        self.items.append((item, partition_key))
        return {
            "id": "model-selection",
            "status": "active" if self.active else "reverted",
            "params": {"enabled": self.active},
        }


class FakeDatabase:
    def __init__(self, *, active=True):
        analytics = build_tenant_manifest("analytics")
        marvel = build_tenant_manifest("marvel")
        self.containers = {
            name: FakeContainer(name, analytics[name] + marvel[name])
            for name in COHORT_CONTAINERS
        }
        self.containers["OptimizationPolicies"] = FakePolicyContainer(active)
        self.accessed = []

    def get_container_client(self, name):
        self.accessed.append(name)
        return self.containers[name]


def _raw_snapshot(database: FakeDatabase, tenant: str) -> str:
    return json.dumps(
        {
            name: [row for row in database.containers[name].items if row.get("tenantId") == tenant]
            for name in COHORT_CONTAINERS
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def test_default_burst_manifest_is_sorted_complete_linked_and_deterministic():
    first = build_after_burst_manifest()
    second = build_after_burst_manifest()

    assert first == second
    assert {name: len(rows) for name, rows in first.items()} == {
        "OptimizationTurns": 200,
        "Debug": 200,
        "NodeExecutions": 200,
        "Sessions": 192,
        "Messages": 200,
        "Trips": 56,
    }
    assert all(rows == sorted(rows, key=lambda row: row["id"]) for rows in first.values())
    assert all(len({row["id"] for row in rows}) == len(rows) for rows in first.values())
    assert Counter(row["model_deployment"] for row in first["OptimizationTurns"]) == {
        "gpt-5-nano": 20,
        "gpt-5-mini": 110,
        "gpt-5.1": 70,
    }
    bucket_counts = Counter(
        row["timeStamp"][:16] for row in first["OptimizationTurns"]
    )
    assert tuple(bucket_counts.values()) == CANONICAL_MINUTE_PROFILE
    assert len(bucket_counts) == 20
    assert min(bucket_counts.values()) == 4
    assert max(bucket_counts.values()) == 16
    assert len({row["timeStamp"] for row in first["OptimizationTurns"]}) == 200
    debug = {row["turnId"]: row for row in first["Debug"]}
    nodes = {row["turnId"]: row for row in first["NodeExecutions"]}
    messages = {row["turnId"]: row for row in first["Messages"]}
    sessions = {row["sessionId"]: row for row in first["Sessions"]}
    trips = {row["sessionId"]: row for row in first["Trips"]}
    assert all(
        row["fixture_version"] == FIXTURE_VERSION
        and row["burst_version"] == BURST_VERSION
        and row["burst_anchor"] == BURST_ANCHOR
        and row["burst_count"] == 200
        and row["burst_window_minutes"] == 20
        and row["controlled_namespace"] == (
            f"{FIXTURE_VERSION}:{BURST_VERSION}:analytics"
        )
        for rows in first.values()
        for row in rows
    )
    for turn in first["OptimizationTurns"]:
        assert turn["id"] in debug and turn["id"] in nodes and turn["id"] in messages
        assert turn["sessionId"] in sessions
        assert {
            turn["timeStamp"],
            debug[turn["id"]]["timeStamp"],
            nodes[turn["id"]]["timeStamp"],
            messages[turn["id"]]["timeStamp"],
        } == {turn["timeStamp"]}
        assert messages[turn["id"]]["ts"] == turn["timeStamp"]
        assert all(
            item["timeStamp"] == turn["timeStamp"]
            for item in debug[turn["id"]]["propertyBag"]
        )
        assert all(
            node["model_deployment"] == turn["model_deployment"]
            for node in nodes[turn["id"]]["nodeExecutions"]
        )
    for trip in trips.values():
        assert trip["turnId"] in {
            turn["id"]
            for turn in first["OptimizationTurns"]
            if turn["sessionId"] == trip["sessionId"]
        }
        assert trip["timeStamp"] == trip["createdAt"] == trip["updatedAt"]
    turns_by_session = {
        session_id: [
            turn for turn in first["OptimizationTurns"]
            if turn["sessionId"] == session_id
        ]
        for session_id in sessions
    }
    for session_id, session in sessions.items():
        assert session["createdAt"] == turns_by_session[session_id][0]["timeStamp"]
        assert session["lastActivityAt"] == turns_by_session[session_id][-1]["timeStamp"]


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, {"complex": 0, "routine": 1, "trivial": 0}),
        (7, {"complex": 2, "routine": 4, "trivial": 1}),
        (11, {"complex": 4, "routine": 6, "trivial": 1}),
    ],
)
def test_deterministic_nondefault_largest_remainder_allocation(count, expected):
    assert allocate_burst_tiers(count) == expected
    manifest = build_after_burst_manifest(count=count, window_minutes=3)
    assert len(manifest["OptimizationTurns"]) == count
    assert len({row["timeStamp"][:16] for row in manifest["OptimizationTurns"]}) == min(count, 3)
    anchor = BURST_ANCHOR.removesuffix("Z")
    expected_timestamps = []
    for ordinal in range(count):
        minute = (ordinal * 3) // count
        indexes = [
            index for index in range(count)
            if (index * 3) // count == minute
        ]
        second = (indexes.index(ordinal) * 60) // len(indexes)
        expected_timestamps.append(
            f"{anchor[:-5]}{int(anchor[-5:-3]) + minute:02d}:{second:02d}Z"
        )
    assert [
        row["timeStamp"] for row in manifest["OptimizationTurns"]
    ] == expected_timestamps


def test_same_parameter_rerun_and_partial_namespace_reconstruct_complete_manifest():
    database = FakeDatabase(active=True)
    first = demo_data.generate_controlled_traffic(db=database)
    expected = _raw_snapshot(database, "analytics")

    database.containers["Messages"].items = [
        row for row in database.containers["Messages"].items
        if row.get("burst_version") != BURST_VERSION or row.get("burst_ordinal", 0) < 50
    ]
    second = demo_data.generate_controlled_traffic(db=database)

    assert _raw_snapshot(database, "analytics") == expected
    assert first["per_container_counts"] == second["per_container_counts"]
    assert all(first["per_container_counts"][name] > 0 for name in COHORT_CONTAINERS)


def test_namespace_conflict_fails_before_mutation():
    database = FakeDatabase(active=True)
    demo_data.generate_controlled_traffic(db=database)
    database.containers["OptimizationTurns"].items[-1]["burst_anchor"] = "2026-09-24T14:00:00Z"
    before = _raw_snapshot(database, "analytics")
    calls = {
        name: (len(database.containers[name].deletes), len(database.containers[name].upserts))
        for name in COHORT_CONTAINERS
    }

    with pytest.raises(ValueError, match="conflicting parameters"):
        demo_data.generate_controlled_traffic(db=database)

    assert _raw_snapshot(database, "analytics") == before
    assert calls == {
        name: (len(database.containers[name].deletes), len(database.containers[name].upserts))
        for name in COHORT_CONTAINERS
    }


def test_controlled_traffic_internal_failure_restores_previous_namespace():
    database = FakeDatabase(active=True)
    demo_data.generate_controlled_traffic(db=database)
    before = _raw_snapshot(database, "analytics")
    messages = database.containers["Messages"]
    original_upsert = messages.upsert_item
    failed = False

    def fail_once(document):
        nonlocal failed
        if not failed and document.get("burst_version") == BURST_VERSION:
            failed = True
            raise RuntimeError("injected burst failure")
        return original_upsert(document)

    messages.upsert_item = fail_once

    with pytest.raises(RuntimeError, match="rollback restored pre-traffic state"):
        demo_data.generate_controlled_traffic(db=database)

    assert _raw_snapshot(database, "analytics") == before


def test_controlled_inactive_policy_returns_409_and_has_zero_writes():
    database = FakeDatabase(active=False)
    with pytest.raises(demo_data.ControlledTrafficInactiveError):
        demo_data.generate_controlled_traffic(db=database)
    assert all(
        not database.containers[name].deletes and not database.containers[name].upserts
        for name in COHORT_CONTAINERS
    )

    api = (
        Path(__file__).parents[1] / "src" / "app" / "optimization_api.py"
    ).read_text(encoding="utf-8")
    assert "except demo_data.ControlledTrafficInactiveError as exc:" in api
    assert "HTTPException(status_code=409" in api


def test_ordinary_inactive_traffic_remains_premium_only():
    database = FakeDatabase(active=False)
    result = demo_data.generate_traffic("analytics", count=9, minutes=1, db=database)

    assert result["mode"] == "baseline"
    assert result["by_model"] == {"gpt-5.1": 9}
    written = database.containers["OptimizationTurns"].upserts
    assert {row["model_deployment"] for row in written} == {"gpt-5.1"}
    assert {row["complexity_tier"] for row in written} == {"default"}


def test_controlled_burst_never_calls_apply_and_marvel_is_byte_equivalent():
    database = FakeDatabase(active=True)
    marvel_before = _raw_snapshot(database, "marvel")
    api_path = Path(__file__).parents[1] / "src" / "app" / "optimization_api.py"
    api_tree = ast.parse(api_path.read_text(encoding="utf-8"))
    apply_node = next(
        node
        for node in api_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "apply"
    )
    apply_calls = {
        ast.unparse(node.func)
        for node in ast.walk(apply_node)
        if isinstance(node, ast.Call)
    }
    assert not any(call.startswith("demo_data.") for call in apply_calls)
    assert not any(container in ast.unparse(apply_node) for container in COHORT_CONTAINERS)
    assert _raw_snapshot(database, "marvel") == marvel_before

    result = demo_data.generate_controlled_traffic(db=database)

    assert result["mode"] == "controlled"
    assert database.containers["OptimizationPolicies"].reads == 1
    assert database.containers["OptimizationPolicies"].items == [
        ("analytics::model-selection", "model-selection")
    ]
    assert _raw_snapshot(database, "marvel") == marvel_before
    assert all(
        not [row for row in database.containers[name].upserts if row.get("tenantId") == "marvel"]
        for name in COHORT_CONTAINERS
    )


def test_controlled_rejects_non_analytics_before_any_container_access():
    database = FakeDatabase(active=True)
    with pytest.raises(ValueError, match="only for tenant 'analytics'"):
        demo_data.generate_controlled_traffic(tenant="marvel", db=database)
    assert database.accessed == []

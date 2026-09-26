from __future__ import annotations

import copy
import json
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

cosmos_stub = types.ModuleType("src.app.services.azure_cosmos_db")
cosmos_stub.database = None
cosmos_stub = sys.modules.setdefault("src.app.services.azure_cosmos_db", cosmos_stub)

from src.app.services import demo_data
from src.app.services.controlled_demo4 import (
    CANONICAL_MINUTE_PROFILE,
    COHORT_CONTAINERS,
    CONFIRMED_TRIP_COUNT,
    DEFAULT_ANCHOR,
    DERIVED_CONTAINERS,
    EXPECTED_FUNNEL,
    FIXTURE_VERSION,
    OUTCOME_COUNTS,
    SESSION_COUNT,
    TENANTS,
    TURN_COUNT,
    build_tenant_manifest,
    is_controlled_fixture_row,
    normalized_fingerprint,
)

EXPECTED_CARDINALITIES = {
    "OptimizationTurns": TURN_COUNT,
    "Debug": TURN_COUNT,
    "NodeExecutions": TURN_COUNT,
    "Sessions": SESSION_COUNT,
    "Messages": TURN_COUNT,
    "Trips": CONFIRMED_TRIP_COUNT,
}


class FakeContainer:
    def __init__(self, name: str, items: list[dict] | None = None):
        self.name = name
        self.items = copy.deepcopy(items or [])
        self.queries: list[tuple[str, list[dict] | None]] = []
        self.deletes: list[str] = []
        self.upserts: list[dict] = []

    def read(self):
        return {
            "id": self.name,
            "partitionKey": {
                "paths": ["/tenantId", "/userId", "/sessionId"],
            },
        }

    def query_items(self, query, parameters=None, enable_cross_partition_query=False):
        self.queries.append((query, copy.deepcopy(parameters)))
        tenant = next(
            (parameter["value"] for parameter in parameters or [] if parameter["name"] == "@tenant"),
            None,
        )
        if tenant is None:
            raise AssertionError("controlled reset queries must be tenant-bounded")
        return [copy.deepcopy(item) for item in self.items if item.get("tenantId") == tenant]

    def delete_item(self, item, partition_key):
        self.deletes.append(item)
        self.items = [document for document in self.items if document["id"] != item]

    def upsert_item(self, item):
        document = copy.deepcopy(item)
        self.upserts.append(document)
        self.items = [
            existing
            for existing in self.items
            if not (
                existing["id"] == document["id"]
                and existing.get("tenantId") == document.get("tenantId")
            )
        ]
        self.items.append(document)
        return document


class FakeDatabase:
    def __init__(self):
        self.containers = {}
        affected = (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)
        for name in affected:
            items = [
                {
                    "id": f"legacy-{name}-{tenant}",
                    "tenantId": tenant,
                    "userId": f"legacy-{tenant}",
                    "sessionId": (
                        f"{FIXTURE_VERSION}-{tenant}-session-stale"
                        if name == "Trips" and tenant in TENANTS
                        else f"legacy-{tenant}"
                    ),
                    "legacy": True,
                }
                for tenant in (*TENANTS, "protected")
            ]
            self.containers[name] = FakeContainer(name, items)
        for name in ("Users", "Memories", "Checkpoints", "ApiEvents", "GlobalMemory"):
            self.containers[name] = FakeContainer(
                name,
                [{"id": f"{name}-protected", "tenantId": "analytics", "payload": name}],
            )

    def get_container_client(self, name):
        return self.containers[name]


class FakePolicyService:
    def __init__(self, policy: dict | None = None):
        self.policies = {
            tenant: {
                **copy.deepcopy(policy),
                "id": f"{tenant}::model-selection",
                "tenant_id": tenant,
            }
            for tenant in TENANTS
        } if policy is not None else {}
        self.revert_calls = []
        self.restore_calls = []

    def get_policy(self, scenario, tenant_id=None):
        assert scenario == "model-selection"
        return copy.deepcopy(self.policies.get(tenant_id))

    def revert_policy(self, scenario, by="dashboard", tenant_id=None):
        self.revert_calls.append((scenario, by, tenant_id))
        if tenant_id not in self.policies:
            return None
        self.policies[tenant_id]["status"] = "reverted"
        self.policies[tenant_id]["version"] = int(
            self.policies[tenant_id].get("version", 1)
        ) + 1
        return copy.deepcopy(self.policies[tenant_id])

    def restore_policy_snapshot(self, snapshot):
        self.restore_calls.append(copy.deepcopy(snapshot))
        self.policies[snapshot["tenant_id"]] = copy.deepcopy(snapshot)
        return copy.deepcopy(snapshot)


@pytest.fixture
def policy_service():
    return FakePolicyService({
        "id": "model-selection",
        "scenario": "model-selection",
        "status": "active",
        "version": 4,
        "params": {"enabled": True},
        "audit": [],
    })


def _snapshot(database: FakeDatabase, names: tuple[str, ...]) -> str:
    payload = {
        name: database.containers[name].items
        for name in names
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _normalized_snapshot(database: FakeDatabase, names: tuple[str, ...]) -> str:
    payload = {
        name: sorted(
            database.containers[name].items,
            key=lambda row: (
                str(row.get("tenantId")),
                str(row.get("id")),
                str(row.get("userId")),
                str(row.get("sessionId")),
            ),
        )
        for name in names
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _run_reset(tmp_path: Path, database=None, policy_service=None):
    database = database or FakeDatabase()
    policy_service = policy_service or FakePolicyService({
        "id": "model-selection",
        "scenario": "model-selection",
        "status": "active",
        "version": 1,
        "params": {"enabled": True},
    })
    result = demo_data.reset_controlled_demo4(
        db=database,
        backup_dir=tmp_path,
        policy_service=policy_service,
    )
    return database, policy_service, result


def test_manifest_has_exact_cardinalities_linkages_and_premium_models():
    manifest = build_tenant_manifest("analytics")

    assert set(manifest) == set(COHORT_CONTAINERS)
    assert {name: len(items) for name, items in manifest.items()} == EXPECTED_CARDINALITIES
    sessions = {item["sessionId"]: item for item in manifest["Sessions"]}
    trips = {item["sessionId"]: item for item in manifest["Trips"]}
    messages_per_session = Counter(item["sessionId"] for item in manifest["Messages"])
    turns_per_session = Counter(item["sessionId"] for item in manifest["OptimizationTurns"])
    assert Counter(item["session_outcome"] for item in manifest["Sessions"]) == OUTCOME_COUNTS
    assert len([count for count in turns_per_session.values() if count == 2]) == 8
    assert len([count for count in turns_per_session.values() if count == 1]) == 184
    for ordinal in range(TURN_COUNT):
        turn = manifest["OptimizationTurns"][ordinal]
        debug = manifest["Debug"][ordinal]
        nodes = manifest["NodeExecutions"][ordinal]
        message = manifest["Messages"][ordinal]
        session = sessions[turn["sessionId"]]
        assert {
            turn["sessionId"],
            debug["sessionId"],
            nodes["sessionId"],
            session["sessionId"],
            message["sessionId"],
        } == {session["id"]}
        assert {
            debug["turnId"],
            nodes["turnId"],
            message["turnId"],
        } == {turn["id"]}
        assert debug["debugLogId"] == nodes["debugLogId"] == turn["debugLogId"]
        assert debug["messageId"] == message["id"]
        assert turn["model_deployment"] == "gpt-5.1"
        assert turn["model_name"] == "gpt-5.1-2025-11-13"
        assert turn["complexity_tier"] == "default"
        assert all(node["model_deployment"] == "gpt-5.1" for node in nodes["nodeExecutions"])
    for session_id, session in sessions.items():
        assert session["messageCount"] == messages_per_session[session_id]
        assert session["messageCount"] == turns_per_session[session_id]
        if session["session_outcome"] == "converted":
            trip = trips[session_id]
            assert trip["tripId"] == trip["id"]
            assert trip["turnId"] in {
                turn["id"]
                for turn in manifest["OptimizationTurns"]
                if turn["sessionId"] == session_id
            }
        else:
            assert session_id not in trips


def test_manifest_uses_exact_twenty_buckets_and_paired_timestamps():
    manifest = build_tenant_manifest("analytics")
    bucket_counts = Counter(
        turn["timeStamp"][:16]
        for turn in manifest["OptimizationTurns"]
    )

    assert len(bucket_counts) == 20
    assert tuple(bucket_counts.values()) == CANONICAL_MINUTE_PROFILE
    assert sum(bucket_counts.values()) == 200
    assert min(bucket_counts.values()) == 4
    assert max(bucket_counts.values()) == 16
    assert len({turn["timeStamp"] for turn in manifest["OptimizationTurns"]}) == TURN_COUNT
    for ordinal, turn in enumerate(manifest["OptimizationTurns"]):
        timestamp = turn["timeStamp"]
        epoch = turn["turn_epoch"]
        debug = manifest["Debug"][ordinal]
        nodes = manifest["NodeExecutions"][ordinal]
        message = manifest["Messages"][ordinal]
        assert debug["timeStamp"] == nodes["timeStamp"] == timestamp
        assert message["ts"] == message["timeStamp"] == timestamp
        assert debug["turn_epoch"] == nodes["turn_epoch"] == epoch
        assert all(item["timeStamp"] == timestamp for item in debug["propertyBag"])
        assert next(item["value"] for item in debug["propertyBag"] if item["key"] == "turn_epoch") == epoch
    turns_by_session: dict[str, list[dict]] = {}
    for turn in manifest["OptimizationTurns"]:
        turns_by_session.setdefault(turn["sessionId"], []).append(turn)
    for session in manifest["Sessions"]:
        turns = turns_by_session[session["sessionId"]]
        assert session["createdAt"] == turns[0]["timeStamp"]
        assert session["lastActivityAt"] == turns[-1]["timeStamp"]
    for trip in manifest["Trips"]:
        turns = turns_by_session[trip["sessionId"]]
        assert trip["timeStamp"] == trip["createdAt"] == trip["updatedAt"] == turns[-1]["timeStamp"]


def test_normalized_fingerprints_are_identical_and_deterministic():
    analytics = build_tenant_manifest("analytics")
    marvel = build_tenant_manifest("marvel")

    assert normalized_fingerprint(analytics) == normalized_fingerprint(marvel)
    assert analytics == build_tenant_manifest("analytics")
    assert [row["timeStamp"] for row in analytics["OptimizationTurns"]] == [
        row["timeStamp"] for row in marvel["OptimizationTurns"]
    ]
    assert analytics["OptimizationTurns"][0]["timeStamp"] == DEFAULT_ANCHOR


class FunnelQueryContainer:
    def __init__(self, items):
        self.items = copy.deepcopy(items)

    def query_items(self, query, parameters=None, enable_cross_partition_query=False):
        tenant = next(
            (parameter["value"] for parameter in parameters or [] if parameter["name"] == "@t"),
            None,
        )
        return [copy.deepcopy(item) for item in self.items if item.get("tenantId") == tenant]


class FunnelDatabase:
    def __init__(self, manifest):
        self.containers = {
            "Trips": FunnelQueryContainer(manifest["Trips"]),
            "Messages": FunnelQueryContainer(manifest["Messages"]),
        }

    def get_container_client(self, name):
        return self.containers[name]


def test_existing_funnel_and_insight_logic_produce_required_business_story(monkeypatch):
    from src.app.services import optimization_insights
    from src.app.services import optimization_recommendations as recommendations

    manifest = build_tenant_manifest("analytics")
    cosmos_stub.database = FunnelDatabase(manifest)
    cosmos_stub.debug_logs_container = FunnelQueryContainer(manifest["Debug"])
    cosmos_stub.initialize_cosmos_client = lambda: None

    diagnostic = recommendations.build_cost_per_outcome_diagnostic("analytics")
    evidence = diagnostic["evidence"]
    assert evidence["funnel"] == EXPECTED_FUNNEL
    assert evidence["confirmed_sessions"] == CONFIRMED_TRIP_COUNT
    assert evidence["abandonment"] == {
        "cart_abandon": 36,
        "city_friction": 52,
        "no_results": 24,
        "search_stall": 16,
        "no_engagement": 8,
    }
    assert "Biggest addressable leak: city friction (52 sessions)" in diagnostic["note"]

    monkeypatch.setattr(
        recommendations,
        "build_agent_path_diagnostic",
        lambda tenant_id: {"evidence": {"paths": []}},
    )
    monkeypatch.setattr(
        recommendations,
        "build_memory_retention_recommendation",
        lambda tenant_id: {
            "evidence": {
                "total_memories": 0,
                "superseded_memories": 0,
                "superseded_pct": 0,
                "avoided_recall_tokens": 0,
                "measured_saving_usd": 0,
            },
        },
    )
    rows = optimization_insights.build_insight_rows("analytics")
    kpi = next(row for row in rows if row["type"] == "conversion_kpi")
    assert kpi["engaged"] == SESSION_COUNT
    assert kpi["confirmed"] == CONFIRMED_TRIP_COUNT
    assert kpi["conversion_rate"] == 29.2
    assert kpi["biggest_leak"] == "city_friction"


def test_bounded_reset_clears_derived_insights_governance_and_preserves_protected_unrelated(
    tmp_path,
    policy_service,
):
    database = FakeDatabase()
    protected_names = ("Users", "Memories", "Checkpoints", "ApiEvents", "GlobalMemory")
    protected_before = _snapshot(database, protected_names)

    _, _, result = _run_reset(tmp_path, database, policy_service)

    assert result["policy_statuses"] == {
        "analytics": "reverted",
        "marvel": "reverted",
    }
    assert result["derived_state_empty"] is True
    assert policy_service.revert_calls == [
        ("model-selection", "controlled-demo4-reset", "analytics"),
        ("model-selection", "controlled-demo4-reset", "marvel"),
    ]
    for name in (*COHORT_CONTAINERS, *DERIVED_CONTAINERS):
        container = database.containers[name]
        assert len(container.queries) == 2
        assert all("c.tenantId = @tenant" in query for query, _ in container.queries)
        assert all(
            parameters in (
                [{"name": "@tenant", "value": "analytics"}],
                [{"name": "@tenant", "value": "marvel"}],
            )
            for _, parameters in container.queries
        )
        protected = [item for item in container.items if item["tenantId"] == "protected"]
        assert protected == [{
            "id": f"legacy-{name}-protected",
            "tenantId": "protected",
            "userId": "legacy-protected",
            "sessionId": "legacy-protected",
            "legacy": True,
        }]
        if name in DERIVED_CONTAINERS:
            assert not [
                item for item in container.items
                if any(
                    is_controlled_fixture_row(name, item, tenant)
                    for tenant in TENANTS
                )
            ]
            assert container.upserts == []
        else:
            assert Counter(item["tenantId"] for item in container.items) == {
                "analytics": EXPECTED_CARDINALITIES[name] + 1,
                "marvel": EXPECTED_CARDINALITIES[name] + 1,
                "protected": 1,
            }
    assert _snapshot(database, protected_names) == protected_before
    assert all(database.containers[name].deletes == [] for name in protected_names)
    assert all(database.containers[name].upserts == [] for name in protected_names)


def test_controlled_reset_is_idempotent_with_stable_ids_and_no_duplicates(tmp_path):
    database, policy, first = _run_reset(tmp_path)
    first_source = _snapshot(database, COHORT_CONTAINERS)

    second = demo_data.reset_controlled_demo4(
        db=database,
        backup_dir=tmp_path,
        policy_service=policy,
    )

    assert _snapshot(database, COHORT_CONTAINERS) == first_source
    assert first["fingerprints"] == second["fingerprints"]
    for name in COHORT_CONTAINERS:
        ids = [
            item["id"]
            for item in database.containers[name].items
            if any(
                is_controlled_fixture_row(name, item, tenant)
                for tenant in TENANTS
            )
        ]
        assert len(ids) == EXPECTED_CARDINALITIES[name] * len(TENANTS)
        assert len(ids) == len(set(ids))


def test_controlled_reset_preserves_operational_trip_and_replaces_fixture_trips(
    tmp_path,
    policy_service,
):
    database = FakeDatabase()
    tony_trip = {
        "id": "tony-paris",
        "tripId": "tony-paris",
        "tenantId": "marvel",
        "userId": "tony",
        "sessionId": "tony-paris-session",
        "status": "confirmed",
        "destination": "Paris",
    }
    stale_fixture_trip = {
        "id": f"{FIXTURE_VERSION}-marvel-trip-000",
        "tenantId": "marvel",
        "userId": f"{FIXTURE_VERSION}-marvel-user-000",
        "sessionId": f"{FIXTURE_VERSION}-marvel-session-000",
        "fixture_version": FIXTURE_VERSION,
        "fixture_ordinal": 0,
        "status": "confirmed",
    }
    stale_burst_trip = {
        "id": "controlled-demo4-after-v1-marvel-trip-000",
        "tenantId": "marvel",
        "userId": "stale-controlled-burst-user",
        "sessionId": "controlled-demo4-after-v1-marvel-session-000",
        "fixture_version": FIXTURE_VERSION,
        "burst_version": "controlled-demo4-after-v1",
        "controlled_namespace": (
            "controlled-demo4-v1:controlled-demo4-after-v1:marvel"
        ),
        "status": "confirmed",
    }
    trips = database.containers["Trips"]
    trips.items.extend([tony_trip, stale_fixture_trip, stale_burst_trip])

    _, _, result = _run_reset(tmp_path, database, policy_service)

    marvel_trips = [row for row in trips.items if row.get("tenantId") == "marvel"]
    assert tony_trip in marvel_trips
    assert stale_fixture_trip not in marvel_trips
    assert stale_burst_trip in marvel_trips
    assert len([
        row
        for row in marvel_trips
        if is_controlled_fixture_row("Trips", row, "marvel")
    ]) == CONFIRMED_TRIP_COUNT
    assert result["deleted"]["Trips"]["marvel"] == 1


def test_fixture_id_collision_without_complete_metadata_fails_before_mutation(
    tmp_path,
    policy_service,
):
    database = FakeDatabase()
    collision = {
        "id": f"{FIXTURE_VERSION}-marvel-trip-001",
        "tripId": f"{FIXTURE_VERSION}-marvel-trip-001",
        "tenantId": "marvel",
        "userId": "operational",
        "sessionId": f"{FIXTURE_VERSION}-marvel-session-001",
        "status": "confirmed",
    }
    database.containers["Trips"].items.append(collision)
    before = _snapshot(database, (*COHORT_CONTAINERS, *DERIVED_CONTAINERS))

    with pytest.raises(RuntimeError, match="protected fixture id collision"):
        demo_data.reset_controlled_demo4(
            db=database,
            backup_dir=tmp_path,
            policy_service=policy_service,
        )

    assert _snapshot(database, (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)) == before
    assert policy_service.revert_calls == []
    assert list(tmp_path.iterdir()) == []


def test_backup_contains_all_pre_reset_rows_and_policy(tmp_path, policy_service):
    database = FakeDatabase()

    _, _, result = _run_reset(tmp_path, database, policy_service)
    backup = json.loads(Path(result["backup_path"]).read_text(encoding="utf-8"))

    assert backup["fixture_version"] == FIXTURE_VERSION
    assert backup["anchor"] == DEFAULT_ANCHOR
    assert {
        tenant: policy["status"]
        for tenant, policy in backup["model_selection_policies"].items()
    } == {"analytics": "active", "marvel": "active"}
    assert set(backup["containers"]) == set((*COHORT_CONTAINERS, *DERIVED_CONTAINERS))
    assert all(
        len(backup["containers"][name][tenant]) == 1
        for name in (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)
        for tenant in TENANTS
    )


def test_backup_failure_aborts_before_policy_or_container_mutation(tmp_path, policy_service):
    database = FakeDatabase()
    affected = (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)
    before = _normalized_snapshot(database, affected)
    not_a_directory = tmp_path / "backup-target"
    not_a_directory.write_text("occupied", encoding="utf-8")

    with pytest.raises(FileExistsError):
        demo_data.reset_controlled_demo4(
            db=database,
            backup_dir=not_a_directory,
            policy_service=policy_service,
        )

    assert _normalized_snapshot(database, affected) == before
    assert policy_service.revert_calls == []
    assert all(database.containers[name].deletes == [] for name in affected)
    assert all(database.containers[name].upserts == [] for name in affected)


def test_reset_internal_failure_restores_rows_and_both_policy_lifecycles(
    tmp_path,
    policy_service,
):
    database = FakeDatabase()
    affected = (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)
    before = _normalized_snapshot(database, affected)
    policies_before = copy.deepcopy(policy_service.policies)
    messages = database.containers["Messages"]
    original_upsert = messages.upsert_item
    failed = False

    def fail_once(document):
        nonlocal failed
        if not failed and document.get("fixture_version") == FIXTURE_VERSION:
            failed = True
            raise RuntimeError("injected seed failure")
        return original_upsert(document)

    messages.upsert_item = fail_once

    with pytest.raises(RuntimeError, match="rollback restored pre-reset state"):
        demo_data.reset_controlled_demo4(
            db=database,
            backup_dir=tmp_path,
            policy_service=policy_service,
        )

    assert _normalized_snapshot(database, affected) == before
    assert policy_service.policies == policies_before


def test_missing_policy_fails_closed_without_synthesizing_or_mutating(tmp_path):
    database = FakeDatabase()
    policy = FakePolicyService(None)
    affected = (*COHORT_CONTAINERS, *DERIVED_CONTAINERS)
    before = _snapshot(database, affected)

    with pytest.raises(RuntimeError, match="tenant-qualified model-selection policies"):
        demo_data.reset_controlled_demo4(
            db=database,
            backup_dir=tmp_path,
            policy_service=policy,
        )

    assert _snapshot(database, affected) == before
    assert policy.revert_calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"fixture_version": "unknown"}, "unsupported fixture version"),
        ({"anchor": "2026-09-24T12:00:01Z"}, "aligned to a minute"),
        ({"count": 199}, "exactly 200"),
        ({"tenants": ("analytics",)}, "exactly these tenants"),
    ],
)
def test_invalid_fixture_inputs_fail_before_mutation(tmp_path, kwargs, message):
    database = FakeDatabase()
    policy = FakePolicyService({
        "id": "model-selection",
        "scenario": "model-selection",
        "status": "active",
        "params": {"enabled": True},
    })

    with pytest.raises(ValueError, match=message):
        demo_data.reset_controlled_demo4(
            db=database,
            backup_dir=tmp_path,
            policy_service=policy,
            **kwargs,
        )

    assert policy.revert_calls == []
    assert all(
        container.deletes == [] and container.upserts == []
        for container in database.containers.values()
    )

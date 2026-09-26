from __future__ import annotations

import copy
import importlib.util
import json
import sys
import types
from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest

cosmos_stub = types.ModuleType("src.app.services.azure_cosmos_db")
cosmos_stub.database = None
cosmos_stub.debug_logs_container = None
cosmos_stub.initialize_cosmos_client = lambda: None
cosmos_stub.record_api_event = lambda **kwargs: None
sys.modules.setdefault("src.app.services.azure_cosmos_db", cosmos_stub)

from src.app.services import optimization_insights, optimization_recommendations
from src.app.services.controlled_demo4 import (
    BURST_ANCHOR,
    BURST_VERSION,
    COHORT_CONTAINERS,
    FIXTURE_VERSION,
    ROUNDING_TOLERANCE_PCT,
    ROUNDING_TOLERANCE_USD,
    TURN_COUNT,
    WINDOW_MINUTES,
    assert_evaluation_schema,
    build_after_burst_manifest,
    build_tenant_manifest,
    controlled_fixture_session_prefix,
    evaluate_controlled_demo4,
)


class FakeContainer:
    def __init__(self, name: str, items=None, events=None):
        self.name = name
        self.items = copy.deepcopy(items or [])
        self.events = events if events is not None else []
        self.queries = []
        self.deletes = []
        self.upserts = []
        self.fail_on_type = None

    def query_items(self, query, parameters=None, enable_cross_partition_query=False):
        params = {item["name"]: item["value"] for item in parameters or []}
        self.queries.append((query, copy.deepcopy(parameters)))
        self.events.append(("query", self.name, params.get("@tenant")))
        rows = self.items
        if "@tenant" in params:
            rows = [row for row in rows if row.get("tenantId") == params["@tenant"]]
        if "c.type='optimization_result'" in query:
            rows = [row for row in rows if row.get("type") == "optimization_result"]
        if "c.provider='memory'" in query:
            rows = [
                row for row in rows
                if row.get("provider") == "memory"
                and row.get("operation") == "recall_pruned_avoided"
            ]
        return copy.deepcopy(rows)

    def read_item(self, item, partition_key):
        self.events.append(("read", self.name, partition_key, item))
        for row in self.items:
            if row.get("id") == item:
                return copy.deepcopy(row)
        raise KeyError(item)

    def delete_item(self, item, partition_key):
        self.events.append(("delete", self.name, partition_key, item))
        self.deletes.append(item)
        self.items = [
            row for row in self.items
            if not (row.get("id") == item and row.get("tenantId") == partition_key)
        ]

    def upsert_item(self, item):
        if self.fail_on_type and item.get("type") == self.fail_on_type:
            raise RuntimeError("injected Analytics/shared failure")
        doc = copy.deepcopy(item)
        self.events.append(("upsert", self.name, doc.get("tenantId"), doc.get("type")))
        self.upserts.append(doc)
        self.items = [
            row for row in self.items
            if not (
                row.get("id") == doc.get("id")
                and row.get("tenantId") == doc.get("tenantId")
            )
        ]
        self.items.append(doc)
        return doc


class FakeDatabase:
    def __init__(self, *, policy_status="active", include_burst=False):
        self.events = []
        analytics = build_tenant_manifest("analytics")
        marvel = build_tenant_manifest("marvel")
        if include_burst:
            burst = build_after_burst_manifest()
            for name in COHORT_CONTAINERS:
                analytics[name] += burst[name]
        self.containers = {
            name: FakeContainer(name, analytics[name] + marvel[name], self.events)
            for name in COHORT_CONTAINERS
        }
        self.containers["OptimizationPolicies"] = FakeContainer(
            "OptimizationPolicies",
            [
                {
                    "id": "model-selection",
                    "scenario": "model-selection",
                    "status": "reverted",
                    "params": {"enabled": False},
                },
                {
                    "id": "analytics::model-selection",
                    "scenario": "model-selection",
                    "status": policy_status,
                    "params": {"enabled": policy_status == "active"},
                },
                {
                    "id": "marvel::model-selection",
                    "scenario": "model-selection",
                    "status": policy_status,
                    "params": {"enabled": policy_status == "active"},
                },
            ],
            self.events,
        )
        self.containers["OptimizationInsights"] = FakeContainer(
            "OptimizationInsights", [], self.events
        )
        self.containers["OptimizationGovernance"] = FakeContainer(
            "OptimizationGovernance", [], self.events
        )
        self.containers["ApiEvents"] = FakeContainer("ApiEvents", [], self.events)
        self.containers["memories"] = FakeContainer("memories", [], self.events)
        self.containers["Configuration"] = FakeContainer("Configuration", [], self.events)
        for name in ("Users", "Memories", "Checkpoints", "GlobalMemory"):
            self.containers[name] = FakeContainer(
                name, [{"id": f"{name}-protected", "tenantId": "analytics"}], self.events
            )

    def get_container_client(self, name):
        self.events.append(("get", name))
        return self.containers[name]


def _turns(db: FakeDatabase, tenant: str) -> list[dict]:
    return [
        row
        for row in db.containers["OptimizationTurns"].items
        if row.get("tenantId") == tenant
    ]


def test_evaluator_reads_tenant_qualified_model_selection_policy():
    db = FakeDatabase(policy_status="active")
    db.containers["OptimizationPolicies"].items[0]["status"] = "active"
    db.containers["OptimizationPolicies"].items[1]["status"] = "reverted"

    result = evaluate_controlled_demo4(db, "analytics")

    assert result["policy_status"] == "reverted"
    assert (
        "read",
        "OptimizationPolicies",
        "model-selection",
        "analytics::model-selection",
    ) in db.events
    assert (
        "read",
        "OptimizationPolicies",
        "model-selection",
        "model-selection",
    ) not in db.events


def _burst_turns(db: FakeDatabase) -> list[dict]:
    return [
        row
        for row in _turns(db, "analytics")
        if row.get("burst_version") == BURST_VERSION
    ]


def _snapshot(db: FakeDatabase, names) -> str:
    return json.dumps(
        {name: db.containers[name].items for name in names},
        sort_keys=True,
        separators=(",", ":"),
    )


@pytest.mark.parametrize(
    ("tenant", "policy_status", "include_burst", "phase", "display"),
    [
        ("marvel", "active", False, "before", "Not Applied · Before"),
        (
            "analytics",
            "active",
            False,
            "before",
            "Policy Active · Awaiting Traffic · Before",
        ),
        ("analytics", "active", True, "after", "Applied · After"),
        (
            "analytics",
            "reverted",
            True,
            "after",
            "Policy Reverted · After Traffic Captured",
        ),
    ],
)
def test_state_valid_mappings(tenant, policy_status, include_burst, phase, display):
    result = evaluate_controlled_demo4(
        FakeDatabase(policy_status=policy_status, include_burst=include_burst),
        tenant,
    )
    assert result["policy_status"] == policy_status
    assert result["dataset_phase"] == phase
    assert result["display_state"] == display
    assert result["state_valid"] is True


def test_state_baseline_integrity_error_is_not_successful_before():
    db = FakeDatabase()
    expected_id = build_tenant_manifest("analytics")["OptimizationTurns"][0]["id"]
    db.containers["OptimizationTurns"].items = [
        row for row in db.containers["OptimizationTurns"].items if row["id"] != expected_id
    ]
    result = evaluate_controlled_demo4(db, "analytics")
    assert result["state_valid"] is False
    assert result["dataset_phase"] == "invalid"
    assert "missing expected baseline IDs in OptimizationTurns" in result["state_reason"]


def test_state_missing_burst_ids_is_integrity_error():
    db = FakeDatabase(include_burst=True)
    missing = _burst_turns(db)[0]["id"]
    db.containers["OptimizationTurns"].items = [
        row for row in db.containers["OptimizationTurns"].items if row["id"] != missing
    ]
    result = evaluate_controlled_demo4(db, "analytics")
    assert result["state_valid"] is False
    assert "missing expected burst IDs in OptimizationTurns" in result["state_reason"]


@pytest.mark.parametrize("conflicting", [False, True])
def test_state_duplicate_or_conflicting_expected_ids(conflicting):
    db = FakeDatabase(include_burst=True)
    duplicate = copy.deepcopy(_burst_turns(db)[0])
    if conflicting:
        duplicate["input_tokens"] += 1
    db.containers["OptimizationTurns"].items.append(duplicate)
    result = evaluate_controlled_demo4(db, "analytics")
    assert result["state_valid"] is False
    assert ("conflicting" if conflicting else "duplicate") in result["state_reason"]


@pytest.mark.parametrize("container_name", COHORT_CONTAINERS)
def test_baseline_requires_every_controlled_container(container_name):
    db = FakeDatabase()
    expected = build_tenant_manifest("analytics")[container_name][0]
    db.containers[container_name].items = [
        row for row in db.containers[container_name].items
        if row.get("id") != expected["id"]
    ]
    result = evaluate_controlled_demo4(db, "analytics")
    assert result["state_valid"] is False
    assert result["dataset_phase"] == "invalid"
    assert f"missing expected baseline IDs in {container_name}" in result["state_reason"]


@pytest.mark.parametrize("container_name", COHORT_CONTAINERS)
def test_after_requires_every_controlled_container_and_rejects_corruption(container_name):
    db = FakeDatabase(include_burst=True)
    expected = build_after_burst_manifest()[container_name][0]
    actual = next(
        row for row in db.containers[container_name].items
        if row.get("id") == expected["id"]
    )
    actual["tenantId"] = "analytics-corrupt"
    result = evaluate_controlled_demo4(db, "analytics")
    assert result["state_valid"] is False
    assert result["dataset_phase"] == "invalid"
    assert result["measurement"] is None
    assert f"missing expected burst IDs in {container_name}" in result["state_reason"]


def test_state_wrong_mix_and_unknown_deployment_are_rejected():
    wrong_mix = FakeDatabase(include_burst=True)
    row = _burst_turns(wrong_mix)[0]
    row["model_deployment"] = "gpt-5.1"
    row["model_name"] = "gpt-5.1-2025-11-13"
    result = evaluate_controlled_demo4(wrong_mix, "analytics")
    assert result["state_valid"] is False
    assert "wrong controlled burst model mix" in result["state_reason"]

    unknown = FakeDatabase(include_burst=True)
    row = _burst_turns(unknown)[0]
    row["model_deployment"] = row["model_name"] = "unknown-deployment"
    result = evaluate_controlled_demo4(unknown, "analytics")
    assert result["state_valid"] is False
    assert "unknown or conflicting deployment/model" in result["state_reason"]


def test_integrity_mismatched_burst_metadata_is_rejected():
    db = FakeDatabase(include_burst=True)
    _burst_turns(db)[0]["burst_anchor"] = "2026-09-24T14:00:00Z"
    result = evaluate_controlled_demo4(db, "analytics")
    assert result["state_valid"] is False
    assert "burst metadata mismatch" in result["state_reason"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("input_tokens", None, "missing/non-numeric"),
        ("output_tokens", "10", "missing/non-numeric"),
        ("input_tokens", -1, "negative/non-finite"),
    ],
)
def test_integrity_missing_non_numeric_or_negative_tokens(field, value, reason):
    db = FakeDatabase(include_burst=True)
    row = _burst_turns(db)[0]
    if value is None:
        row.pop(field)
    else:
        row[field] = value
    result = evaluate_controlled_demo4(db, "analytics")
    assert result["state_valid"] is False
    assert reason in result["state_reason"]


@pytest.mark.parametrize(
    "mutation",
    (
        "valid-baseline",
        "valid-after",
        "incomplete",
        "duplicate",
        "conflicting",
        "malformed-token",
        "unknown-deployment",
        "wrong-model-mix",
    ),
)
def test_fabric_parity_uses_canonical_evaluator_and_exact_schema(mutation):
    generator_path = Path("../../analytics/fabric/_gen_funnel_notebook.py").resolve()
    spec = importlib.util.spec_from_file_location("funnel_notebook_generator", generator_path)
    generator = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(generator)
    notebook = {
        "CONTROLLED_DEMO4_EMBEDDED_PRICING": json.loads(
            Path("data/model_pricing.json").read_text(encoding="utf-8")
        ),
        "CONTROLLED_DEMO4_EMBEDDED_PRICING_SOURCE": r"python\data\model_pricing.json",
        "CONTROLLED_DEMO4_EMBEDDED_PRICING_SHA256": generator.CONTROLLED_DEMO4_PRICING_SHA256,
    }
    exec(generator.CONTROLLED_DEMO4_SOURCE, notebook)

    include_burst = mutation != "valid-baseline"
    db = FakeDatabase(include_burst=include_burst)
    if mutation == "incomplete":
        missing = build_after_burst_manifest()["Debug"][0]["id"]
        db.containers["Debug"].items = [
            row for row in db.containers["Debug"].items if row["id"] != missing
        ]
    elif mutation in {"duplicate", "conflicting"}:
        duplicate = copy.deepcopy(_burst_turns(db)[0])
        if mutation == "conflicting":
            duplicate["input_tokens"] += 1
        db.containers["OptimizationTurns"].items.append(duplicate)
    elif mutation == "malformed-token":
        _burst_turns(db)[0]["input_tokens"] = "not-a-number"
    elif mutation == "unknown-deployment":
        row = _burst_turns(db)[0]
        row["model_deployment"] = row["model_name"] = "unknown-deployment"
    elif mutation == "wrong-model-mix":
        row = next(
            item for item in _burst_turns(db)
            if item["model_deployment"] != "gpt-5.1"
        )
        row["model_deployment"] = "gpt-5.1"
        row["model_name"] = "gpt-5.1-2025-11-13"

    app_result = evaluate_controlled_demo4(db, "analytics", policy_status="active")
    fabric_result = notebook["evaluate_controlled_demo4"](
        db, "analytics", policy_status="active"
    )
    assert_evaluation_schema(app_result)
    notebook["assert_evaluation_schema"](fabric_result)
    assert fabric_result == app_result


def test_cohort_manifest_immunity_and_exact_pricing_math():
    db = FakeDatabase(include_burst=True)
    before = evaluate_controlled_demo4(db, "analytics")
    ordinary = copy.deepcopy(_turns(db, "analytics")[0])
    ordinary.update({"id": "ordinary-analytics", "fixture_version": None})
    other_version = copy.deepcopy(_burst_turns(db)[0])
    other_version.update({
        "id": "controlled-demo4-after-v2-analytics-turn-000",
        "burst_version": "controlled-demo4-after-v2",
    })
    foreign = copy.deepcopy(_burst_turns(db)[0])
    foreign.update({"id": "foreign-turn", "tenantId": "foreign"})
    db.containers["OptimizationTurns"].items.extend([ordinary, other_version, foreign])
    after = evaluate_controlled_demo4(db, "analytics")

    assert before["measurement"] == after["measurement"]
    measured = after["measurement"]
    assert measured["model_counts"] == {
        "gpt-5-mini": 110,
        "gpt-5-nano": 20,
        "gpt-5.1": 70,
    }
    assert measured["expected_count"] == measured["observed_count"] == TURN_COUNT
    assert measured["fixture_version"] == FIXTURE_VERSION
    assert measured["burst_version"] == BURST_VERSION
    assert measured["burst_anchor"] == BURST_ANCHOR
    assert measured["burst_window_minutes"] == WINDOW_MINUTES
    assert measured["pricing_source"].endswith("python\\data\\model_pricing.json")
    assert len(measured["pricing_sha256"]) == 64
    assert measured["rounding_tolerance_usd"] == ROUNDING_TOLERANCE_USD
    assert measured["rounding_tolerance_pct"] == ROUNDING_TOLERANCE_PCT
    assert measured["positive_measured_result"] is True

    pricing = json.loads(Path("data/model_pricing.json").read_text())
    baseline = actual = Decimal("0")
    for row in _burst_turns(db):
        dep = row["model_deployment"]
        i, o = Decimal(row["input_tokens"]), Decimal(row["output_tokens"])
        baseline += (
            i * Decimal(str(pricing["gpt-5.1"]["input"]))
            + o * Decimal(str(pricing["gpt-5.1"]["output"]))
        ) / Decimal(1_000_000)
        actual += (
            i * Decimal(str(pricing[dep]["input"]))
            + o * Decimal(str(pricing[dep]["output"]))
        ) / Decimal(1_000_000)
    assert Decimal(measured["baseline_cost_usd_unrounded"]) == baseline
    assert Decimal(measured["actual_cost_usd_unrounded"]) == actual
    assert measured["saving_usd"] > 0


def test_confirmed_trip_count_ignores_operational_and_after_burst_trips(monkeypatch):
    fixture = build_tenant_manifest("analytics")["Trips"]
    operational = {
        "tenantId": "analytics",
        "sessionId": "tony-style-operational-session",
        "status": "confirmed",
    }
    after_burst = {
        "tenantId": "analytics",
        "sessionId": "controlled-demo4-after-v1-analytics-session-000",
        "status": "confirmed",
    }

    class CountContainer:
        def query_items(self, query, parameters=None, enable_cross_partition_query=False):
            values = {item["name"]: item["value"] for item in parameters or []}
            assert "STARTSWITH(d.sessionId, @fixture_session_prefix)" in query
            assert values["@fixture_session_prefix"] == controlled_fixture_session_prefix(
                "analytics"
            )
            rows = fixture + [operational, after_burst]
            return [
                sum(
                    row.get("tenantId") == values["@t"]
                    and str(row.get("sessionId", "")).startswith(
                        values["@fixture_session_prefix"]
                    )
                    and row.get("status") in {"confirmed", "completed"}
                    for row in rows
                )
            ]

    database = type(
        "Database",
        (),
        {"get_container_client": lambda self, name: CountContainer()},
    )()
    monkeypatch.setattr(optimization_recommendations.cosmos, "database", database)

    assert optimization_recommendations.count_confirmed_trips("analytics") == 56


def test_complete_zero_saving_is_a_valid_measurement():
    db = FakeDatabase(include_burst=True)
    for row in _burst_turns(db):
        if row["model_deployment"] != "gpt-5.1":
            row["input_tokens"] = 0
            row["output_tokens"] = 0
    result = evaluate_controlled_demo4(db, "analytics")
    assert result["state_valid"] is True
    assert result["measurement_status"] == "measured"
    assert result["measurement"]["positive_measured_result"] is False
    assert result["measurement"]["measurement_status"] == "measured"
    assert result["measurement"]["saving_usd"] == 0.0
    assert result["measurement"]["validation_reason"] == (
        "complete controlled burst has zero measured saving"
    )


def test_measurement_status_distinguishes_missing_invalid_and_measured():
    missing_db = FakeDatabase(include_burst=False)
    missing = evaluate_controlled_demo4(missing_db, "analytics")
    assert missing["measurement_status"] == "missing"
    missing_row = next(
        row
        for row in optimization_insights.build_optimization_result_rows(missing_db)
        if row["scenario"] == "model-selection"
    )
    assert missing_row["measurement_status"] == "missing"
    assert "saving_usd" not in missing_row
    assert "baseline_cost_usd" not in missing_row

    invalid_db = FakeDatabase(include_burst=True)
    _burst_turns(invalid_db)[0]["burst_anchor"] = "2026-09-24T14:00:00Z"
    invalid = evaluate_controlled_demo4(invalid_db, "analytics")
    assert invalid["measurement_status"] == "invalid"
    invalid_row = next(
        row
        for row in optimization_insights.build_optimization_result_rows(invalid_db)
        if row["scenario"] == "model-selection"
    )
    assert invalid_row["measurement_status"] == "invalid"
    assert "saving_usd" not in invalid_row

    measured = evaluate_controlled_demo4(
        FakeDatabase(policy_status="reverted", include_burst=True),
        "analytics",
    )
    assert measured["measurement_status"] == "measured"
    assert measured["measurement"]["saving_usd"] >= 0.0

    marvel = evaluate_controlled_demo4(
        FakeDatabase(policy_status="active", include_burst=True),
        "marvel",
    )
    assert marvel["measurement_status"] == "missing"
    assert marvel["measurement"] is None


def test_api_and_portal_facing_parity_and_marvel_tenant_scope(monkeypatch):
    db = FakeDatabase(include_burst=True)
    result_rows = optimization_insights.build_optimization_result_rows(db)
    db.containers["OptimizationInsights"].items = copy.deepcopy(result_rows)
    monkeypatch.setattr(optimization_recommendations.cosmos, "database", db)
    monkeypatch.setattr(
        optimization_recommendations, "_insights_container", db.containers["OptimizationInsights"]
    )
    api_response = optimization_recommendations.read_optimization_result_from_insights("marvel")
    assert api_response["dataset_state"]["display_state"] == "Not Applied · Before"
    assert not any(
        row["scenario"] == "model-selection" for row in api_response["results"]
    )

    portal = Path("../analytics-portal/index.html").read_text(encoding="utf-8")
    api_source = Path("src/app/optimization_api.py").read_text(encoding="utf-8")
    assert '"dataset_state": _controlled_state(tenant_id)' in api_source
    assert "Policy: ${policyStateLabel" in portal
    assert "r.display_state" in portal
    assert "Dataset validation error" in portal
    assert "Analytics controlled after burst" in portal
    assert 'r.saving_kind || "Estimated"' in portal
    assert "controlled=true&count=200&minutes=20" in portal
    assert 'mode === "tiered" || mode === "controlled"' in portal
    assert "count=150&minutes=5" not in portal
    assert 'tenantState.includes("Not Applied · Before")' in portal
    assert 'tenantState.includes("Policy Active") || tenantState === "Applied · After"' in portal
    assert 'tenantState.includes("Policy Reverted")' in portal
    assert 'raw === "reverted"' in portal
    assert "policyStateLabel(raw, currentDatasetDisplayState())" in portal
    assert "function visibleActivePolicies()" in portal
    assert 'scenario === "model-selection"' in portal
    assert 'return scenario === "memory-retention"' in portal
    assert "active = visibleActivePolicies().length" in portal
    assert "const pols = visibleActivePolicies()" in portal
    assert "function tenantMeasuredResults()" in portal
    assert "r.measurement_tenant === tenant()" in portal
    assert "const measuredRows = tenantMeasuredResults()" in portal
    assert "measured = measuredRows.reduce" in portal
    assert "const rows = tenantMeasuredResults()" in portal


def test_invalid_live_dataset_marks_stale_measurement_invalid_without_money(monkeypatch):
    db = FakeDatabase(include_burst=True)
    result_rows = optimization_insights.build_optimization_result_rows(db)
    db.containers["OptimizationInsights"].items = copy.deepcopy(result_rows)
    debug_id = build_after_burst_manifest()["Debug"][0]["id"]
    db.containers["Debug"].items = [
        row for row in db.containers["Debug"].items if row.get("id") != debug_id
    ]
    monkeypatch.setattr(optimization_recommendations.cosmos, "database", db)
    monkeypatch.setattr(
        optimization_recommendations, "_insights_container",
        db.containers["OptimizationInsights"],
    )

    service_response = optimization_recommendations.read_optimization_result_from_insights(
        "analytics"
    )
    assert service_response["dataset_state"]["state_valid"] is False
    measured = next(
        row for row in service_response["results"]
        if row.get("measurement_kind") == "Measured"
    )
    assert measured["measurement_status"] == "invalid"
    assert "saving_usd" not in measured
    assert "baseline_cost_usd" not in measured
    assert "invalid" in service_response["note"]

    portal = Path("../analytics-portal/index.html").read_text(encoding="utf-8")
    api_source = Path("src/app/optimization_api.py").read_text(encoding="utf-8")
    assert "res = read_optimization_result_from_insights(tenant_id)" in api_source
    assert "return res" in api_source
    assert "function resultDatasetValid()" in portal
    assert "state_valid === true" in portal
    for renderer in (
        "renderOppBand",
        "renderBaselineActual",
        "renderProjection",
        "renderResult",
        "renderBaBar",
    ):
        body = portal.split(f"function {renderer}", 1)[1].split("\n}", 1)[0]
        assert "resultDatasetValid()" in body
        if renderer == "renderResult":
            assert body.index("resultDatasetValid()") < body.index("const rows")


def _configure_recompute_builders(monkeypatch):
    calls = []

    def tenant_rows(tenant):
        calls.append(("build_tenant", tenant))
        return [{
            "id": f"fresh-{tenant}",
            "tenantId": tenant,
            "type": "tenant_result",
        }]

    def shared_results(db):
        calls.append(("build_shared", "optimization"))
        return [{
            "id": "result::model-selection",
            "tenantId": "_global_optimizations",
            "type": "optimization_result",
        }]

    def shared_memory(db):
        calls.append(("build_shared", "memory"))
        return [{
            "id": "memory::global",
            "tenantId": "_global_memory",
            "type": "memory_kpi",
        }]

    monkeypatch.setattr(optimization_insights, "_tenant_rows", tenant_rows)
    monkeypatch.setattr(optimization_insights, "build_optimization_result_rows", shared_results)
    monkeypatch.setattr(optimization_insights, "build_memory_intelligence_rows", shared_memory)
    return calls


def test_recompute_ordering_exact_replacement_stale_removal_existing_only_shared_once(monkeypatch):
    calls = _configure_recompute_builders(monkeypatch)
    db = FakeDatabase(include_burst=True)
    db.containers["OptimizationInsights"].items = [
        {"id": "stale-a", "tenantId": "analytics", "type": "stale",
         "fixture_version": FIXTURE_VERSION,
         "controlled_namespace": f"{FIXTURE_VERSION}:derived:analytics"},
        {"id": "stale-m", "tenantId": "marvel", "type": "stale",
         "fixture_version": FIXTURE_VERSION,
         "controlled_namespace": f"{FIXTURE_VERSION}:derived:marvel"},
        {"id": "stale-o", "tenantId": "_global_optimizations", "type": "stale",
         "fixture_version": FIXTURE_VERSION,
         "controlled_namespace": f"{FIXTURE_VERSION}:derived:shared"},
        {"id": "stale-g", "tenantId": "_global_memory", "type": "stale",
         "fixture_version": FIXTURE_VERSION,
         "controlled_namespace": f"{FIXTURE_VERSION}:derived:shared"},
        {"id": "unrelated", "tenantId": "protected", "type": "keep"},
    ]
    db.containers["OptimizationGovernance"].items = [
        {"id": "decision-a", "tenantId": "analytics", "type": "decision"},
        {"id": "slo-a", "tenantId": "analytics", "type": "slo_policy"},
        {"id": "schema-a", "tenantId": "analytics", "type": "declared_schema"},
        {"id": "arbitrary-a", "tenantId": "analytics", "type": "stale"},
        {
            "id": "derived-a",
            "tenantId": "analytics",
            "type": "controlled_demo4_derived",
            "fixture_version": FIXTURE_VERSION,
            "controlled_namespace": f"{FIXTURE_VERSION}:derived:analytics",
        },
        {"id": "decision-m", "tenantId": "marvel", "type": "decision"},
        {"id": "slo-m", "tenantId": "marvel", "type": "slo_policy"},
        {"id": "schema-m", "tenantId": "marvel", "type": "declared_schema"},
        {"id": "arbitrary-m", "tenantId": "marvel", "type": "stale"},
        {
            "id": "derived-m",
            "tenantId": "marvel",
            "type": "controlled_demo4_derived",
            "fixture_version": FIXTURE_VERSION,
            "controlled_namespace": f"{FIXTURE_VERSION}:derived:marvel",
        },
        {"id": "gov-p", "tenantId": "protected", "type": "keep"},
    ]

    result = optimization_insights.recompute_controlled_demo4(db)

    assert result["order"] == ["analytics", "shared", "marvel"]
    assert result["shared_written_once"] is True
    assert calls == [
        ("build_tenant", "analytics"),
        ("build_shared", "optimization"),
        ("build_shared", "memory"),
        ("build_tenant", "marvel"),
    ]
    rows = db.containers["OptimizationInsights"].items
    assert {row["id"] for row in rows} == {
        "fresh-analytics",
        "state::analytics",
        "fresh-marvel",
        "state::marvel",
        "result::model-selection",
        "memory::global",
        "unrelated",
    }
    states = {
        row["tenantId"]: row
        for row in rows
        if row.get("type") == "controlled_demo4_state"
    }
    assert states["analytics"]["display_state"] == "Applied · After"
    assert states["marvel"]["display_state"] == "Not Applied · Before"
    assert result["by_type"]["controlled_demo4_state"] == 2
    assert {row["id"] for row in db.containers["OptimizationGovernance"].items} == {
        "decision-a", "slo-a", "schema-a", "arbitrary-a",
        "decision-m", "slo-m", "schema-m", "arbitrary-m", "gov-p",
    }
    assert result["deleted"]["analytics_governance"] == 1
    assert result["deleted"]["marvel_governance"] == 1
    assert not hasattr(db, "create_container_if_not_exists")
    shared_upserts = [
        event for event in db.events
        if event[:2] == ("upsert", "OptimizationInsights")
        and event[2] in {"_global_optimizations", "_global_memory"}
    ]
    assert len(shared_upserts) == 2


def test_recompute_analytics_shared_failure_aborts_before_marvel(monkeypatch):
    _configure_recompute_builders(monkeypatch)
    db = FakeDatabase(include_burst=True)
    db.containers["OptimizationInsights"].fail_on_type = "optimization_result"
    with pytest.raises(RuntimeError, match="injected"):
        optimization_insights.recompute_controlled_demo4(db)
    assert not any(
        event[0] in {"query", "delete", "upsert"}
        and len(event) > 2
        and event[2] == "marvel"
        for event in db.events
    )


def test_recompute_marvel_raw_protected_and_global_memory_immutable(monkeypatch):
    _configure_recompute_builders(monkeypatch)
    db = FakeDatabase(include_burst=True)
    immutable = (*COHORT_CONTAINERS, "Users", "Memories", "Checkpoints", "ApiEvents", "GlobalMemory")
    before = _snapshot(db, immutable)
    optimization_insights.recompute_controlled_demo4(db)
    assert _snapshot(db, immutable) == before


def test_memory_global_zero_without_telemetry_and_no_required_path_writes(monkeypatch):
    db = FakeDatabase(include_burst=True)
    monkeypatch.setattr(optimization_recommendations.cosmos, "database", db)
    rows = optimization_insights.build_optimization_result_rows(db)
    memory = next(row for row in rows if row["scenario"] == "memory-retention")
    assert memory["measurement_scope"] == "Global memory recall telemetry"
    assert memory["scope_label"] == "Global"
    assert memory["turns"] == 0
    assert memory["saving_usd"] == 0.0
    assert db.containers["Memories"].upserts == []
    assert db.containers["ApiEvents"].upserts == []
    assert not any(event[0] in {"delete", "upsert"} and event[1] in {"Memories", "memories", "ApiEvents"} for event in db.events)

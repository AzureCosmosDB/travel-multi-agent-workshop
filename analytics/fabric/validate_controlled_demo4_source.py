#!/usr/bin/env python3
"""Execute each delivered notebook evaluator and prove exact application parity."""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP_SOURCE = (
    ROOT / "02_completed" / "python" / "src" / "app" / "services" / "controlled_demo4.py"
)
FIXTURES = HERE / "tests" / "fixtures"
PRICING = ROOT / "02_completed" / "python" / "data" / "model_pricing.json"


def _load_app():
    spec = importlib.util.spec_from_file_location("controlled_demo4_app", APP_SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def _extract_notebook_evaluator(path: Path) -> tuple[str, dict[str, Any]]:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    candidates = [
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell.get("cell_type") == "code"
        and "CONTROLLED_DEMO4_EMBEDDED_PRICING" in "".join(cell.get("source", []))
        and "_controlled_snapshot" in "".join(cell.get("source", []))
    ]
    if len(candidates) != 1:
        raise AssertionError(f"{path.name}: expected one embedded evaluator cell")
    tree = compile(candidates[0], path.name, "exec", ast.PyCF_ONLY_AST)
    assignments: dict[str, Any] = {}
    evaluator_source = ""
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id.startswith("CONTROLLED_DEMO4_EMBEDDED_")
        ):
            assignments[node.targets[0].id] = ast.literal_eval(node.value)
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "exec"
        ):
            evaluator_source = ast.literal_eval(node.value.args[0])
    if not evaluator_source:
        raise AssertionError(f"{path.name}: embedded evaluator exec source not found")
    namespace = {
        **assignments,
    }
    exec(evaluator_source, namespace)
    return evaluator_source, namespace


class Container:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def query_items(self, **_kwargs):
        return copy.deepcopy(self.rows)

    def read_item(self, item, partition_key):
        for row in self.rows:
            if row.get("id") == item or row.get("scenario") == item:
                return copy.deepcopy(row)
        raise KeyError(item)


class Database:
    def __init__(self, containers: dict[str, list[dict[str, Any]]], policy_status: str):
        self.containers = copy.deepcopy(containers)
        self.policy_status = policy_status

    def get_container_client(self, name):
        if name == "OptimizationPolicies":
            return Container([{"id": "model-selection", "status": self.policy_status}])
        return Container(self.containers.get(name, []))


def _base_containers(contract, include_burst: bool) -> dict[str, list[dict[str, Any]]]:
    analytics = contract.build_tenant_manifest("analytics")
    marvel = contract.build_tenant_manifest("marvel")
    if include_burst:
        burst = contract.build_after_burst_manifest()
        for name in contract.COHORT_CONTAINERS:
            analytics[name] += burst[name]
    return {
        name: copy.deepcopy(analytics[name] + marvel[name])
        for name in contract.COHORT_CONTAINERS
    }


def _burst_turns(contract, containers):
    return [
        row
        for row in containers["OptimizationTurns"]
        if row.get("burst_version") == contract.BURST_VERSION
    ]


def _variants(contract, descriptor: dict[str, Any]):
    case = descriptor["case"]
    if case == "valid-baseline":
        containers = _base_containers(contract, False)
        yield "analytics", "active", containers
        yield "analytics-reverted", "reverted", containers
        yield "marvel", "active", containers
        yield "marvel-reverted", "reverted", containers
        return

    containers = _base_containers(contract, True)
    if case == "valid-after":
        yield "analytics", descriptor.get("policy_status", "active"), containers
        yield "analytics-reverted", "reverted", copy.deepcopy(containers)
        yield "analytics-measured-zero", "active", copy.deepcopy(containers)
        yield "marvel", "active", copy.deepcopy(containers)
        yield "marvel-reverted", "reverted", copy.deepcopy(containers)
    elif case == "incomplete":
        missing = contract.build_after_burst_manifest()["Debug"][0]["id"]
        containers["Debug"] = [row for row in containers["Debug"] if row["id"] != missing]
        yield "analytics", "active", containers
    elif case == "duplicate-conflicting":
        duplicate = copy.deepcopy(_burst_turns(contract, containers)[0])
        containers["OptimizationTurns"].append(duplicate)
        yield "analytics-duplicate", "active", containers
        conflicting = copy.deepcopy(containers)
        conflicting["OptimizationTurns"][-1]["input_tokens"] += 1
        yield "analytics-conflicting", "active", conflicting
    elif case == "malformed-token":
        _burst_turns(contract, containers)[0]["input_tokens"] = "not-a-number"
        yield "analytics", "active", containers
    elif case == "unknown-deployment":
        row = _burst_turns(contract, containers)[0]
        row["model_deployment"] = row["model_name"] = "unknown-deployment"
        yield "analytics", "active", containers
    elif case == "wrong-model-mix":
        row = next(
            item
            for item in _burst_turns(contract, containers)
            if item["model_deployment"] != contract.PREMIUM_DEPLOYMENT
        )
        row["model_deployment"] = contract.PREMIUM_DEPLOYMENT
        row["model_name"] = contract.PREMIUM_MODEL
        yield "analytics", "active", containers
    else:
        raise ValueError(f"unknown controlled Demo 4 fixture case: {case}")


def _evaluate_all(app, notebooks, tenant_label, policy_status, containers):
    tenant = tenant_label.split("-", 1)[0]
    pricing_targets = [app, *notebooks.values()]
    original_pricing = []
    if tenant_label.endswith("measured-zero"):
        pricing = json.loads(PRICING.read_text(encoding="utf-8"))
        premium = pricing["gpt-5.1"]
        equal_pricing = {name: dict(premium) for name in pricing}
        for target in pricing_targets:
            namespace = target.__dict__ if hasattr(target, "__dict__") else target
            original_pricing.append(
                (
                    namespace,
                    namespace.get("CONTROLLED_DEMO4_EMBEDDED_PRICING"),
                    namespace.get("CONTROLLED_DEMO4_EMBEDDED_PRICING_SOURCE"),
                    namespace.get("CONTROLLED_DEMO4_EMBEDDED_PRICING_SHA256"),
                )
            )
            namespace["CONTROLLED_DEMO4_EMBEDDED_PRICING"] = equal_pricing
            namespace["CONTROLLED_DEMO4_EMBEDDED_PRICING_SOURCE"] = "synthetic equal-price fixture"
            namespace["CONTROLLED_DEMO4_EMBEDDED_PRICING_SHA256"] = "0" * 64
    app_result = app.evaluate_controlled_demo4(
        Database(containers, policy_status), tenant, policy_status=policy_status
    )
    app.assert_evaluation_schema(app_result)
    notebook_results = {}
    for name, namespace in notebooks.items():
        result = namespace["evaluate_controlled_demo4"](
            Database(containers, policy_status), tenant, policy_status=policy_status
        )
        namespace["assert_evaluation_schema"](result)
        if app_result != result:
            raise AssertionError(
                f"{name}/app evaluator mismatch:\n"
                + json.dumps({"app": app_result, name: result}, indent=2, sort_keys=True)
            )
        notebook_results[name] = result
    if notebook_results["learner"] != notebook_results["solution"]:
        raise AssertionError("learner and solution evaluator results differ")
    for namespace, pricing, source_name, digest in original_pricing:
        namespace["CONTROLLED_DEMO4_EMBEDDED_PRICING"] = pricing
        namespace["CONTROLLED_DEMO4_EMBEDDED_PRICING_SOURCE"] = source_name
        namespace["CONTROLLED_DEMO4_EMBEDDED_PRICING_SHA256"] = digest
    return app_result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", action="append", type=Path)
    args = parser.parse_args()
    paths = args.fixture or sorted(FIXTURES.glob("demo4-*.json"))
    if not paths:
        raise AssertionError(f"no controlled Demo 4 fixtures found under {FIXTURES}")

    app = _load_app()
    learner_source, learner = _extract_notebook_evaluator(
        HERE / "ConversionFunnelReverseETL.ipynb"
    )
    solution_source, solution = _extract_notebook_evaluator(
        HERE / "ConversionFunnelReverseETL_solution.ipynb"
    )
    app_source = APP_SOURCE.read_text(encoding="utf-8")
    if learner_source.encode("utf-8") != solution_source.encode("utf-8"):
        raise AssertionError("learner/solution embedded evaluator bytes differ")
    if learner_source.encode("utf-8") != app_source.encode("utf-8"):
        raise AssertionError("delivered notebook evaluator bytes differ from application source")
    for name, namespace in (("learner", learner), ("solution", solution)):
        if namespace["EVALUATION_FIELDS"] != app.EVALUATION_FIELDS:
            raise AssertionError(f"{name} evaluation schema differs from application")
        if namespace["MEASUREMENT_FIELDS"] != app.MEASUREMENT_FIELDS:
            raise AssertionError(f"{name} measurement schema differs from application")
    notebooks = {"learner": learner, "solution": solution}
    for path in paths:
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        for tenant, policy_status, containers in _variants(app, descriptor):
            result = _evaluate_all(app, notebooks, tenant, policy_status, containers)
            expected_phase = descriptor.get("expected_phase")
            expected_valid = descriptor.get("expected_valid")
            if descriptor["case"] == "valid-after" and tenant.startswith("marvel"):
                expected_phase = "before"
            if expected_phase is not None and result["dataset_phase"] != expected_phase:
                raise AssertionError(f"{path.name}: expected phase {expected_phase}, got {result}")
            if expected_valid is not None and result["state_valid"] is not expected_valid:
                raise AssertionError(f"{path.name}: expected state_valid={expected_valid}, got {result}")
            if descriptor["case"] == "incomplete" and (
                result["dataset_phase"] == "after" or result["measurement"] is not None
            ):
                raise AssertionError("incomplete source published Applied/After measurement")
            if tenant.endswith("measured-zero"):
                measurement = result["measurement"]
                if (
                    result["measurement_status"] != "measured"
                    or measurement is None
                    or measurement["saving_usd"] != 0.0
                    or measurement["positive_measured_result"] is not False
                ):
                    raise AssertionError("measured zero was confused with missing measurement")
            elif descriptor["case"] == "valid-baseline" and result["measurement"] is not None:
                raise AssertionError("baseline missing measurement was not preserved as None")
            print(
                f"PASS {path.name} [{tenant}]: "
                f"{result['dataset_phase'].upper()}/"
                f"{'VALID' if result['state_valid'] else 'INCOMPLETE'}; field parity exact"
            )
    print(
        "PASS delivered evaluator bytes/schema: "
        f"learner=solution=application sha256={hashlib.sha256(app_source.encode('utf-8')).hexdigest()}"
    )


if __name__ == "__main__":
    main()

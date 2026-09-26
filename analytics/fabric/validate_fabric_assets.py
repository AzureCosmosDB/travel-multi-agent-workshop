#!/usr/bin/env python3
"""Static checks for generated notebooks and the provisioned demo-tenant controller."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from fabric_assets import (
    demo_tenant_pipeline_definition,
    validate_demo_tenant_pipeline_definition,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NOTEBOOK_NAMES = (
    "ConversionFunnelReverseETL.ipynb",
    "ConversionFunnelReverseETL_solution.ipynb",
)


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "funnel_notebook_generator", HERE / "_gen_funnel_notebook.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def source(cell: dict) -> str:
    return "".join(cell.get("source", []))


def assigned_names(nodes: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        for child in ast.walk(node):
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
    return names


def assignment_value(tree: ast.AST, name: str) -> ast.expr:
    def target_names(target: ast.expr) -> set[str]:
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            return {
                item.id
                for item in target.elts
                if isinstance(item, ast.Name)
            }
        return set()

    matches = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(name in target_names(target) for target in node.targets)
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one assignment for {name}, found {len(matches)}")
    return matches[0]


def validate_notebook(
    path: Path, expected_bytes: bytes, solution: bool, canonical_evaluator_source: str
) -> None:
    actual_bytes = path.read_bytes()
    if actual_bytes != expected_bytes:
        raise AssertionError(
            f"{path.name} bytes are stale; regenerate with _gen_funnel_notebook.py"
        )
    actual = json.loads(actual_bytes.decode("utf-8"))

    cells = actual["cells"]
    parameter_indexes = [
        index
        for index, cell in enumerate(cells)
        if "parameters" in (cell.get("metadata", {}).get("tags") or [])
    ]
    if parameter_indexes != [3]:
        raise AssertionError(f"{path.name} must have exactly one tagged parameter cell")

    parameter_index = parameter_indexes[0]
    parameter_cell = source(cells[parameter_index])
    parameter_tree = ast.parse(parameter_cell)
    if not parameter_tree.body or any(
        not isinstance(node, (ast.Assign, ast.AnnAssign)) for node in parameter_tree.body
    ):
        raise AssertionError("tagged parameter cell must contain default assignments only")
    if "str(TENANT)" in parameter_cell or "ValueError" in parameter_cell:
        raise AssertionError("parameter normalization leaked into the tagged cell")

    normalization_cell = cells[parameter_index + 1]
    normalization = source(normalization_cell)
    if normalization_cell.get("cell_type") != "code":
        raise AssertionError("normalization must be the immediately following code cell")
    required_normalization = (
        "TENANT = str(TENANT).strip().lower()",
        "if TENANT not in DEMO_TENANTS:",
        "if isinstance(RUN_GLOBAL_INSIGHTS, bool):",
        "if _bool_key not in _bool_values:",
        "RUN_GLOBAL_INSIGHTS = _bool_values[_bool_key]",
    )
    if any(text not in normalization for text in required_normalization):
        raise AssertionError("post-parameter normalization is incomplete")

    def normalized(tenant, run_global):
        namespace = {
            "TENANT": tenant,
            "RUN_GLOBAL_INSIGHTS": run_global,
            "DEMO_TENANTS": ("analytics", "marvel"),
        }
        exec(normalization, namespace)
        return namespace["TENANT"], namespace["RUN_GLOBAL_INSIGHTS"]

    if normalized(" Marvel ", "false") != ("marvel", False):
        raise AssertionError("pipeline string overrides are not normalized")
    if normalized("ANALYTICS", True) != ("analytics", True):
        raise AssertionError("native boolean overrides are not preserved")
    for invalid in ("sometimes", 2, None):
        try:
            normalized("analytics", invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid boolean override was accepted: {invalid!r}")

    code_sources = [source(cell) for cell in cells if cell["cell_type"] == "code"]
    all_source = "\n".join(code_sources)
    state_source = next(text for text in code_sources if "_controlled_snapshot" in text)
    saving_source = next(text for text in code_sources if "_measured_ready" in text)
    if repr(canonical_evaluator_source) not in state_source:
        raise AssertionError("notebook does not embed the canonical app evaluator source")
    for required in (
        '"OptimizationTurns": turns',
        '"Debug": read_sql("Debug")',
        '"NodeExecutions": read_sql("NodeExecutions")',
        '"Sessions": read_sql("Sessions")',
        '"Messages": messages',
        '"Trips": trips',
        "_controlled_state = evaluate_controlled_demo4(_SnapshotDatabase(), TENANT)",
        "assert_evaluation_schema(_controlled_state)",
        "MIRROR_NOT_READY: suppressing stale Applied/After",
        '"controlled_demo4_state"',
    ):
        if required not in state_source:
            raise AssertionError(f"canonical source-state snapshot is incomplete: {required}")
    saving_tree = ast.parse(saving_source)
    saving_guard = next(
        (
            node
            for node in saving_tree.body
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "not RUN_GLOBAL_INSIGHTS"
        ),
        None,
    )
    if saving_guard is None:
        raise AssertionError("global measured-saving guard is missing")
    if not {
        "_measured_ready",
        "_global_baseline",
        "_global_actual",
        "_global_saving",
        "_global_saving_pct",
        "result_df",
    } <= assigned_names(saving_guard.orelse):
        raise AssertionError("global measured-saving computation is outside its guard")
    if "_measured_ready" in assigned_names(saving_guard.body):
        raise AssertionError("Marvel skip branch still computes controlled measurement")
    for forbidden in ("_all_turns", "_global_priced", "_global_agg"):
        if forbidden in saving_source:
            raise AssertionError(f"all-tenant measured-saving path remains: {forbidden}")
    for required in (
        '_controlled_state["state_valid"]',
        '_controlled_state["dataset_phase"] == "after"',
        '_controlled_measurement["positive_measured_result"]',
        '"suppressed_result"',
        '"Measured — Analytics controlled burst "',
        '"Analytics controlled after burst"',
        '"Projected"',
    ):
        if required not in saving_source:
            raise AssertionError(f"controlled result readiness/scope is incomplete: {required}")

    memory_source = next(text for text in code_sources if "MEMORY_PARTITION" in text)
    memory_tree = ast.parse(memory_source)
    memory_guard = next(
        (
            node
            for node in memory_tree.body
            if isinstance(node, ast.If)
            and ast.unparse(node.test) == "not RUN_GLOBAL_INSIGHTS"
        ),
        None,
    )
    if memory_guard is None or "mem" not in assigned_names(memory_guard.orelse):
        raise AssertionError("global memory computation is outside its guard")
    if "Skipping global memory analysis" not in memory_source:
        raise AssertionError("global memory analysis is not guarded")
    for tenant_section in (
        "agent-path cost concentration",
        "turn metrics -> reverse-ETL",
        "agent scorecard -> reverse-ETL",
        "LLM analyst: propose -> guardrail",
    ):
        if tenant_section not in all_source:
            raise AssertionError(f"tenant section missing: {tenant_section}")

    scorecard_index = next(
        index
        for index, text in enumerate(code_sources)
        if "Agent scorecard reverse-ETL complete" in text
    )
    analyst_index = next(
        index for index, text in enumerate(code_sources) if "analyst card [" in text
    )
    scorecard_tree = ast.parse(code_sources[scorecard_index])
    analyst_tree = ast.parse(code_sources[analyst_index])
    detections = assignment_value(analyst_tree, "_detections")
    if not isinstance(detections, ast.List) or not detections.elts:
        raise AssertionError("analyst detections must be a non-empty list")
    model_detection = detections.elts[0]
    if not isinstance(model_detection, ast.Dict):
        raise AssertionError("model-selection detection must be a dictionary")
    model_fields = {
        key.value: value
        for key, value in zip(model_detection.keys, model_detection.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    if ast.unparse(model_fields.get("engine_saving")) != "_ms_saving":
        raise AssertionError("model-selection engine_saving must use tenant projected downgrade saving")
    evidence = model_fields.get("evidence")
    if not isinstance(evidence, ast.Dict):
        raise AssertionError("model-selection evidence must be a dictionary")
    evidence_keys = {
        key.value for key in evidence.keys if isinstance(key, ast.Constant)
    }
    if not {"total_turns", "downgrade_candidates", "downgrade_pct", "model_distribution"} <= evidence_keys:
        raise AssertionError("model-selection evidence must describe tenant downgrade candidates")

    ms_saving = ast.unparse(assignment_value(analyst_tree, "_ms_saving"))
    if "_ms_cost_now - _ms_cost_proposed" not in ms_saving:
        raise AssertionError("tenant model-selection saving is not the candidate re-pricing delta")
    if ast.literal_eval(assignment_value(analyst_tree, "_MS_PREMIUM")) != {"gpt-5.1", "gpt-5"}:
        raise AssertionError("downgrade candidates must be limited to gpt-5.1 and gpt-5")
    if ast.literal_eval(assignment_value(analyst_tree, "_MS_SHORT_OUTPUT_MAX")) != 250:
        raise AssertionError("downgrade candidate output threshold must remain below 250 tokens")
    candidate_tests = [
        ast.unparse(node.test)
        for node in ast.walk(analyst_tree)
        if isinstance(node, ast.If)
        and "_MS_PREMIUM" in ast.unparse(node.test)
        and "_MS_SHORT_OUTPUT_MAX" in ast.unparse(node.test)
    ]
    if candidate_tests != [
        "_deployment in _MS_PREMIUM and _output_tokens < _MS_SHORT_OUTPUT_MAX"
    ]:
        raise AssertionError("downgrade candidate predicate must be premium deployment and output < 250")
    ms_now = ast.unparse(assignment_value(analyst_tree, "_ms_cost_now"))
    ms_proposed = ast.unparse(assignment_value(analyst_tree, "_ms_cost_proposed"))
    if not all(name in ms_now for name in ("_ms_candidate_in", "_ms_candidate_out", "b_in", "b_out")):
        raise AssertionError("candidate current cost must use observed tokens at gpt-5.1 pricing")
    if not all(
        name in ms_proposed
        for name in ("_ms_candidate_in", "_ms_candidate_out", "_nano_in", "_nano_out")
    ):
        raise AssertionError("candidate proposed cost must use observed tokens at gpt-5-nano pricing")
    nano_price = ast.unparse(assignment_value(analyst_tree, "_nano_in"))
    if "_price_map.get('gpt-5-nano'" not in nano_price:
        raise AssertionError("candidate proposed cost must load gpt-5-nano pricing")
    if "downgrade candidates" not in code_sources[analyst_index]:
        raise AssertionError("model-selection evidence wording must say downgrade candidates")
    if "trivial turns" in code_sources[analyst_index]:
        raise AssertionError("model-selection recommendation still calls candidates trivial turns")

    analyst_source = code_sources[analyst_index]
    required_positive_signal = (
        'if _det["scenario"] == "model-selection":',
        'return _ms_candidates > 0 and float(_det["engine_saving"]) > 0',
        'if _det["scenario"] == "tool-call-dedup":',
        'return _td_turns > 0 and float(_det["engine_saving"]) > 0',
        "_positive_detections = [_det for _det in _detections if _has_positive_signal(_det)]",
        "_suppressed_detections = [_det for _det in _detections if not _has_positive_signal(_det)]",
        "for _rank, _det in enumerate(_positive_detections):",
    )
    if any(text not in analyst_source for text in required_positive_signal):
        raise AssertionError("analyst rows are not limited to detections with positive signal")

    def load_function(name: str, namespace: dict) -> object:
        function = next(
            node
            for node in analyst_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        exec(compile(ast.Module(body=[function], type_ignores=[]), path.name, "exec"), namespace)
        return namespace[name]

    signal_namespace = {"_ms_candidates": 1, "_td_turns": 1}
    has_positive_signal = load_function("_has_positive_signal", signal_namespace)
    model_detection = {"scenario": "model-selection", "engine_saving": 0.25}
    tool_detection = {"scenario": "tool-call-dedup", "engine_saving": 0.04}
    if not has_positive_signal(model_detection) or not has_positive_signal(tool_detection):
        raise AssertionError("positive model-selection/tool-call-dedup signals were filtered out")
    signal_namespace["_ms_candidates"] = 0
    if has_positive_signal(model_detection):
        raise AssertionError("zero model-selection candidates still produce analyst rows")
    signal_namespace["_ms_candidates"] = 1
    model_detection["engine_saving"] = 0
    if has_positive_signal(model_detection):
        raise AssertionError("zero model-selection saving still produces analyst rows")
    signal_namespace["_td_turns"] = 0
    if has_positive_signal(tool_detection):
        raise AssertionError("zero redundant tool turns still produce analyst rows")
    signal_namespace["_td_turns"] = 1
    tool_detection["engine_saving"] = 0
    if has_positive_signal(tool_detection):
        raise AssertionError("zero tool-call-dedup saving still produces analyst rows")

    required_tombstones = (
        'f"disc:{TENANT}:{_det[\'opportunity_id\']}"',
        'f"agentopp::{TENANT}::{_det[\'opportunity_id\']}"',
        'f"reccard::{TENANT}::{_det[\'scenario\']}"',
        '"suppressed_opportunity"',
        '["id", "type", "tenantId", "scenario", "reason", "computed_at"]',
    )
    if any(text not in analyst_source for text in required_tombstones):
        raise AssertionError("suppressed opportunities do not overwrite all deterministic report IDs")

    guardrail = next(
        node
        for node in analyst_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_guardrail"
    )
    guardrail_text = ast.unparse(guardrail)
    for required_binding in (
        "_expected = OPPORTUNITY_SEAMS.get(det['opportunity_id'])",
        "if _expected is None:",
        "if (card['seam'], card['target']) != _expected:",
    ):
        if required_binding not in guardrail_text:
            raise AssertionError("guardrail does not bind proposals to the opportunity-specific seam")
    guardrail_calls = [
        node
        for node in ast.walk(analyst_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_guardrail"
    ]
    if len(guardrail_calls) != 2 or any(
        len(call.args) != 2
        or not isinstance(call.args[1], ast.Name)
        or call.args[1].id != "_det"
        for call in guardrail_calls
    ):
        raise AssertionError("guardrail calls must pass the full detection for exact seam binding")
    opportunity_seams = ast.literal_eval(assignment_value(analyst_tree, "OPPORTUNITY_SEAMS"))
    if opportunity_seams.get("opp-repeated-node") != ("prompt", "supervisor.prompty"):
        raise AssertionError("tool-call-dedup must bind to prompt -> supervisor.prompty")
    seam_apply_mode = ast.literal_eval(assignment_value(analyst_tree, "SEAM_APPLY_MODE"))
    seam_ceiling = ast.literal_eval(assignment_value(analyst_tree, "SEAM_CEILING"))
    if seam_apply_mode.get("prompt") != "staged_change" or seam_ceiling.get("prompt") != "L3":
        raise AssertionError("tool-call-dedup prompt recommendation must remain Manual/L3")
    guardrail_namespace = {
        "SURFACE": ast.literal_eval(assignment_value(analyst_tree, "SURFACE")),
        "OPPORTUNITY_SEAMS": opportunity_seams,
        "SEAM_APPLY_MODE": seam_apply_mode,
        "SEAM_CEILING": seam_ceiling,
    }
    run_guardrail = load_function("_guardrail", guardrail_namespace)
    repeated_node = {
        "opportunity_id": "opp-repeated-node",
        "engine_saving": 0.04115,
    }
    cited_card = {
        "agent": "find_places",
        "dimension": "workflow efficiency · tool use",
        "seam": "code",
        "target": "introduce-model-selector",
        "evidence": [
            {
                "detector": "structural.repeated_node",
                "opportunity_id": "opp-repeated-node",
                "traces": ["trace-1"],
            }
        ],
    }
    normalized, why = run_guardrail(cited_card, repeated_node)
    if normalized is not None or "requires prompt -> supervisor.prompty" not in why:
        raise AssertionError("allowed but opportunity-incompatible seam was not rejected")
    cited_card.update({"seam": "prompt", "target": "supervisor.prompty"})
    normalized, why = run_guardrail(cited_card, repeated_node)
    if (
        normalized is None
        or normalized["apply_mode"] != "staged_change"
        or normalized["autonomy_ceiling"] != "L3"
        or normalized["saving"] != 0.04115
    ):
        raise AssertionError("tool-call-dedup fallback is not prompt -> supervisor.prompty, Manual/L3")

    result_rows = assignment_value(saving_tree, "_result_rows")
    result_text = ast.unparse(result_rows)
    for required_global in (
        "_global_n",
        "_global_baseline",
        "_global_actual",
        "_global_saving",
        "_global_saving_pct",
        "_controlled_state",
    ):
        if required_global not in result_text:
            raise AssertionError(
                f"global optimization_result lost measured all-tenant value {required_global}"
            )

    append_calls = [
        node
        for node in ast.walk(analyst_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_agent_opp_rows"
        and node.func.attr == "append"
    ]
    if len(append_calls) != 1 or len(append_calls[0].args) != 1:
        raise AssertionError("expected one agent-opportunity tuple append")
    append_text = ast.unparse(append_calls[0].args[0])
    if not all(field in append_text for field in ("_norm['agent']", "_norm['dimension']")):
        raise AssertionError("agent-opportunity tuple must populate agent and dimension")
    agent_schema_calls = [
        node
        for node in ast.walk(analyst_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "createDataFrame"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "_agent_opp_rows"
    ]
    if len(agent_schema_calls) != 1 or len(agent_schema_calls[0].args) < 2:
        raise AssertionError("agent-opportunity DataFrame schema is missing")
    schema = ast.literal_eval(agent_schema_calls[0].args[1])
    if "agent" not in schema or "dimension" not in schema:
        raise AssertionError("agent-opportunity schema must include agent and dimension")

    total_spend_assignments = [
        node
        for node in analyst_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_total_spend"
            for target in node.targets
        )
    ]
    if len(total_spend_assignments) != 1:
        raise AssertionError("analyst must define exactly one _total_spend expression")
    total_spend_iterators = [
        comprehension.iter
        for comprehension in ast.walk(total_spend_assignments[0].value)
        if isinstance(comprehension, ast.comprehension)
    ]
    if (
        scorecard_index >= analyst_index
        or "_nodes" not in assigned_names(scorecard_tree.body)
        or len(total_spend_iterators) != 1
        or not isinstance(total_spend_iterators[0], ast.Name)
        or total_spend_iterators[0].id != "_nodes"
    ):
        raise AssertionError(
            "analyst total spend must iterate the scorecard-produced _nodes"
        )

    has_todo = 'raise NotImplementedError("Implement the cause classification' in all_source
    has_write_todo = 'raise NotImplementedError("Write funnel_df' in all_source
    if solution and (has_todo or has_write_todo):
        raise AssertionError("solution notebook still contains learner TODO exceptions")
    if not solution and not (has_todo and has_write_todo):
        raise AssertionError("learner notebook TODO behavior was lost")


def _generated_notebooks(directory: Path) -> dict[str, bytes]:
    present = {path.name for path in directory.glob("*.ipynb")}
    expected = set(NOTEBOOK_NAMES)
    if present != expected:
        raise AssertionError(
            f"{directory}: generated notebook set mismatch; "
            f"missing={sorted(expected - present)}, unexpected={sorted(present - expected)}"
        )
    return {name: (directory / name).read_bytes() for name in NOTEBOOK_NAMES}


def validate_double_generation() -> None:
    work_root = HERE / ".validation-work"
    if work_root.exists():
        shutil.rmtree(work_root)
    first = work_root / "generation-a"
    second = work_root / "generation-b"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    command = [sys.executable, str(HERE / "_gen_funnel_notebook.py"), "--output-dir"]
    try:
        for output_dir in (first, second):
            completed = subprocess.run(
                [*command, str(output_dir)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                env=os.environ.copy(),
            )
            if completed.returncode:
                raise AssertionError(
                    f"independent generator process failed for {output_dir.name}:\n"
                    f"{completed.stdout}{completed.stderr}"
                )
        generated_a = _generated_notebooks(first)
        generated_b = _generated_notebooks(second)
        for name in NOTEBOOK_NAMES:
            digest_a = hashlib.sha256(generated_a[name]).hexdigest()
            digest_b = hashlib.sha256(generated_b[name]).hexdigest()
            delivered = (HERE / name).read_bytes()
            digest_delivered = hashlib.sha256(delivered).hexdigest()
            if generated_a[name] != generated_b[name]:
                raise AssertionError(
                    f"{name} is nondeterministic: A={digest_a}, B={digest_b}"
                )
            if generated_a[name] != delivered:
                raise AssertionError(
                    f"{name} differs from delivered bytes: "
                    f"generated={digest_a}, delivered={digest_delivered}"
                )
            print(
                f"PASS: {name} deterministic "
                f"A={digest_a} B={digest_b} delivered={digest_delivered}"
            )
    finally:
        if work_root.exists():
            shutil.rmtree(work_root)


def _static_scan_paths() -> list[Path]:
    paths = [
        HERE / "Provision-Fabric.ps1",
        HERE / "README.md",
        ROOT / "analytics" / "scripts" / "run_integration_verification.py",
        *(HERE / name for name in NOTEBOOK_NAMES),
        *sorted(HERE.glob("*.py")),
        *sorted((HERE / "tests").rglob("*.py")),
    ]
    powerbi = ROOT / "analytics" / "powerbi"
    for pattern in ("*.pbir", "*.tmdl"):
        paths.extend(sorted(powerbi.rglob(pattern)))
    return list(dict.fromkeys(paths))


def validate_sanitized_sources() -> None:
    findings: list[str] = []
    personal_patterns = (
        re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/]+(?!<|placeholder|example)[^\\/\s\"']+"),
        re.compile(r"(?i)/(?:Users|home)/(?!<|placeholder|example)[^/\s\"']+"),
        re.compile(r"(?i)\b[\w.+-]+@(?:microsoft\.com|outlook\.com|gmail\.com)\b"),
        re.compile(
            r"(?i)\b(?:rg|cosmos|fab)[-_](?!connection\b|account\b|placeholder\b)"
            r"(?:mjb|[a-z0-9]{10,})\b"
        ),
    )
    secret_patterns = (
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"),
        re.compile(
            r"(?i)\b(?:client_secret|api_key|access_token|refresh_token)\s*[:=]\s*"
            r"[\"'][^\"'\s{}<>]{8,}[\"']"
        ),
    )
    guid = re.compile(
        r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    )
    allowed_guids = {
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    }
    for path in _static_scan_paths():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for pattern in (*personal_patterns, *secret_patterns):
            for match in pattern.finditer(text):
                findings.append(f"{rel}: forbidden value {match.group(0)!r}")
        for match in guid.finditer(text):
            value = match.group(0).lower()
            context = text[max(0, match.start() - 100):match.end() + 100].lower()
            environment_context = any(
                term in context
                for term in (
                    "workspace",
                    "dataset",
                    "semantic model",
                    "semanticmodel",
                    "connection",
                    "capacity",
                    "mirror",
                    "notebook",
                    "pipeline",
                    "resource group",
                    "subscription",
                    "tenant id",
                )
            )
            if (
                environment_context
                and value not in allowed_guids
                and not value.startswith("00000000-")
            ):
                findings.append(f"{rel}: embedded environment identifier {value}")
    if findings:
        raise AssertionError("static sanitizer findings:\n" + "\n".join(findings))
    print(f"PASS: static sanitizer scanned {len(_static_scan_paths())} owned/delivered sources")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--double-generate",
        action="store_true",
        help="run two clean generator processes and compare both with delivered bytes",
    )
    args = parser.parse_args()
    generator = load_generator()
    validate_notebook(
        HERE / "ConversionFunnelReverseETL.ipynb",
        generator.serialize_notebook(False),
        solution=False,
        canonical_evaluator_source=generator.CONTROLLED_DEMO4_SOURCE,
    )
    validate_notebook(
        HERE / "ConversionFunnelReverseETL_solution.ipynb",
        generator.serialize_notebook(True),
        solution=True,
        canonical_evaluator_source=generator.CONTROLLED_DEMO4_SOURCE,
    )

    workspace_id = "00000000-0000-0000-0000-000000000001"
    notebook_id = "00000000-0000-0000-0000-000000000002"
    definition = demo_tenant_pipeline_definition(workspace_id, notebook_id)
    validate_demo_tenant_pipeline_definition(definition, workspace_id, notebook_id)

    provision_source = (HERE / "provision_fabric.py").read_text(encoding="utf-8")
    for required in (
        "provision_demo_tenant_pipeline(tok, ws_id, notebook_id)",
        '"pipeline-content.json"',
        '"FABRIC_DEMO_TENANTS_PIPELINE_ID"',
    ):
        if required not in provision_source:
            raise AssertionError(f"provisioning integration missing: {required}")

    validate_sanitized_sources()
    if args.double_generate:
        validate_double_generation()

    print("PASS: generated notebook bytes are current")
    print("PASS: canonical app evaluator source and exact result schema are embedded")
    print("PASS: one mirror snapshot gates tenant state and controlled Analytics measurement")
    print("PASS: incomplete/corrupt source tombstones the deterministic measured result")
    print("PASS: parameter defaults and post-override normalization are separated")
    print("PASS: global savings and memory work are Analytics-only")
    print("PASS: analyst total spend uses scorecard-produced _nodes")
    print("PASS: analyst agent opportunities include agent and dimension")
    print("PASS: tenant downgrade-candidate saving feeds cards while global results stay global")
    print("PASS: analyst rows require positive signal and stale deterministic IDs are tombstoned")
    print("PASS: opportunity guardrails enforce the exact declared seam and target")
    print("PASS: learner TODOs and solution behavior are preserved")
    print("PASS: provisioned controller runs Analytics then Marvel without duplicate global work")


if __name__ == "__main__":
    main()

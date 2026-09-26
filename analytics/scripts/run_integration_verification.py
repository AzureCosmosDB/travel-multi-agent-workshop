#!/usr/bin/env python3
"""Metadata-driven, serial integration verification with durable evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "analytics" / "scripts"
VENV_PYTHON = ROOT / "02_completed" / "venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.is_file() else Path(sys.executable))
STATUSES = {"Verified", "Failed", "Unverified"}
MUTATIONS = {"read-only", "state-mutating"}
FABRIC_API = "https://api.fabric.microsoft.com"
DEFAULT_FABRIC_CONNECTION_NAME = "Multi-Agent Travel Workshop"
SENSITIVE_SUBSTITUTIONS = {"FABRIC_COSMOS_CONNECTION_ID"}


class CommandSpec(NamedTuple):
    id: str
    argv: tuple[str, ...]
    cwd: str
    evidence_path: str
    timeout_seconds: int
    credential_requirement: str
    mutation: str
    prerequisites: tuple[str, ...]
    produced_artifacts: tuple[str, ...]
    owner: str
    environment: tuple[tuple[str, str], ...]
    finalizer: bool = False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def create_run_namespace(evidence_root: Path) -> Path:
    evidence_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    for _attempt in range(10):
        run_id = f"{timestamp}-{uuid.uuid4().hex[:12]}"
        run_dir = evidence_root / "runs" / run_id
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            continue
        return run_dir
    raise RuntimeError("could not allocate a unique integration evidence namespace")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def cmd(
    command_id: str,
    argv: list[str],
    *,
    cwd: str = ".",
    timeout: int = 900,
    credentials: str = "none",
    mutation: str = "read-only",
    prerequisites: tuple[str, ...] = (),
    produces: tuple[str, ...] = (),
    owner: str,
    environment: tuple[tuple[str, str], ...] = (),
    finalizer: bool = False,
) -> CommandSpec:
    return CommandSpec(
        command_id,
        tuple(argv),
        cwd,
        f"commands/{command_id}.stdout-stderr.log",
        timeout,
        credentials,
        mutation,
        prerequisites,
        produces,
        owner,
        environment,
        finalizer,
    )


def pytest_command(*tests: str) -> list[str]:
    return [PYTHON, "-m", "pytest", *tests, "-q"]


def command_catalog() -> dict[str, CommandSpec]:
    exercise_python = "01_exercises/python"
    completed_python = "02_completed/python"
    fabric = "analytics/fabric"
    powerbi = "analytics/powerbi"
    evidence = ".local/integration-evidence"
    return {
        "proof-tools-compile": cmd(
            "proof-tools-compile",
            [
                PYTHON,
                "-m",
                "py_compile",
                "analytics/scripts/capture_integration_baseline.py",
                "analytics/scripts/validate_azd_project_config.py",
                "analytics/scripts/validate_deployment_source_builds.py",
                "analytics/scripts/run_integration_verification.py",
                "analytics/scripts/verify_integration_accounting.py",
                "analytics/scripts/validate_changed_symbol_blast_radius.py",
            ],
            prerequisites=(
                "analytics/scripts/capture_integration_baseline.py",
                "analytics/scripts/validate_azd_project_config.py",
                "analytics/scripts/validate_deployment_source_builds.py",
                "analytics/scripts/verify_integration_accounting.py",
                "analytics/scripts/validate_changed_symbol_blast_radius.py",
            ),
            owner="A0/G0",
        ),
        "proof-tools-self-tests": cmd(
            "proof-tools-self-tests",
            [
                PYTHON,
                "-c",
                (
                    "import subprocess,sys;"
                    "files=['capture_integration_baseline.py',"
                    "'validate_azd_project_config.py',"
                    "'validate_deployment_source_builds.py',"
                    "'verify_integration_accounting.py',"
                    "'validate_changed_symbol_blast_radius.py'];"
                    "raise SystemExit(next((r.returncode for f in files "
                    "if (r:=subprocess.run([sys.executable,'analytics/scripts/'+f,"
                    "'--self-test'])).returncode),0))"
                ),
            ],
            prerequisites=(
                "analytics/scripts/capture_integration_baseline.py",
                "analytics/scripts/validate_azd_project_config.py",
                "analytics/scripts/validate_deployment_source_builds.py",
                "analytics/scripts/verify_integration_accounting.py",
                "analytics/scripts/validate_changed_symbol_blast_radius.py",
            ),
            owner="A0/G0",
        ),
        "capture-baseline": cmd(
            "capture-baseline",
            [
                PYTHON,
                "analytics/scripts/capture_integration_baseline.py",
                "--output",
                f"{evidence}/baseline.json",
                "--require-complete-coverage",
            ],
            prerequisites=("analytics/scripts/capture_integration_baseline.py",),
            produces=(f"{evidence}/baseline.json",),
            owner="A1",
        ),
        "angular-parity": cmd(
            "angular-parity",
            ["npm", "run", "test:parity"],
            cwd="01_exercises/frontend",
            timeout=1800,
            prerequisites=("01_exercises/frontend/package.json",),
            owner="A2",
        ),
        "excluded-artifacts": cmd(
            "excluded-artifacts",
            [
                PYTHON,
                "-c",
                (
                    "import hashlib,json;from pathlib import Path;"
                    "m=json.loads(Path('.local/integration-evidence/openspec-relocation.json').read_text());"
                    "assert m['verified_before_source_delete'] is True;"
                    "assert m['source_file_count']==m['destination_file_count']==len(m['files']);"
                    "assert not Path('openspec').exists();"
                    "assert not Path('analytics/docs/presenter-handoff-talk-track.md').exists();"
                    "assert not list(Path('01_exercises/frontend').rglob('*.parity.spec.ts'));"
                    "b=json.loads(Path('.local/integration-evidence/brief-f/relocation.json').read_text(encoding='utf-8-sig'));"
                    "assert b['verified_before_source_delete'] is True;"
                    "assert b['source_file_count']==b['destination_file_count']==len(b['files'])==2;"
                    "assert all(x['byte_for_byte_verified'] for x in b['files']);"
                    "assert all(Path(x['destination_path']).is_file() for x in b['files']);"
                    "assert all(Path(x['destination_path']).stat().st_size==x['bytes'] for x in b['files']);"
                    "assert all(hashlib.sha256(Path(x['destination_path']).read_bytes()).hexdigest()==x['sha256'] for x in b['files']);"
                    "assert not Path('analytics/qa_report_f.txt').exists();"
                    "assert not Path('validate-brief-f.ps1').exists()"
                ),
            ],
            prerequisites=(
                f"{evidence}/openspec-relocation.json",
                f"{evidence}/brief-f/relocation.json",
            ),
            owner="A3",
        ),
        "deployment-source-static": cmd(
            "deployment-source-static",
            [PYTHON, "analytics/scripts/validate_deployment_source_builds.py"],
            prerequisites=("analytics/scripts/validate_deployment_source_builds.py",),
            owner="A4",
        ),
        "azd-project-config": cmd(
            "azd-project-config",
            [
                PYTHON,
                "analytics/scripts/validate_azd_project_config.py",
                "--evidence",
                f"{evidence}/azd-project-config.json",
            ],
            prerequisites=(
                "analytics/scripts/validate_azd_project_config.py",
                "02_completed/azure.yaml",
            ),
            produces=(f"{evidence}/azd-project-config.json",),
            owner="A4/G2",
        ),
        "deployment-source-build-all": cmd(
            "deployment-source-build-all",
            [
                PYTHON,
                "analytics/scripts/validate_deployment_source_builds.py",
                "--build-all",
                "--evidence-dir",
                f"{evidence}/source-builds",
            ],
            timeout=7200,
            prerequisites=("analytics/scripts/validate_deployment_source_builds.py",),
            produces=(f"{evidence}/source-builds",),
            owner="A4/G2",
        ),
        "parity-validator-self-test": cmd(
            "parity-validator-self-test",
            [PYTHON, "analytics/scripts/validate_cross_tree_parity.py", "--self-test"],
            prerequisites=("analytics/scripts/validate_cross_tree_parity.py",),
            owner="B0",
        ),
        "exercise-memory-profile": cmd(
            "exercise-memory-profile",
            pytest_command(
                "tests/test_memory_deletion.py",
                "tests/test_memory_dependency_compatibility.py",
                "tests/test_user_preferences_service.py",
                "tests/test_traveller_context.py",
            ),
            cwd=exercise_python,
            prerequisites=(f"{exercise_python}/tests",),
            owner="B1",
        ),
        "completed-memory-profile": cmd(
            "completed-memory-profile",
            pytest_command(
                "tests/test_memory_dependency_compatibility.py",
                "tests/test_user_preferences_service.py",
                "tests/test_traveller_context.py",
                "tests/test_travel_agent_regressions.py",
            ),
            cwd=completed_python,
            prerequisites=(f"{completed_python}/tests",),
            owner="B1",
        ),
        "exercise-shared-trips": cmd(
            "exercise-shared-trips",
            pytest_command(
                "tests/test_start_trip_validation.py",
                "tests/test_start_trip_cosmos.py",
                "tests/test_start_trip_endpoint.py",
                "tests/test_traveller_context.py",
                "tests/test_bound_trip_agent_updates.py",
            ),
            cwd=exercise_python,
            prerequisites=(f"{exercise_python}/tests",),
            owner="B2",
        ),
        "completed-shared-trips": cmd(
            "completed-shared-trips",
            pytest_command(
                "tests/test_start_trip_validation.py",
                "tests/test_start_trip_cosmos.py",
                "tests/test_start_trip_endpoint.py",
                "tests/test_traveller_context.py",
                "tests/test_travel_agent_regressions.py",
            ),
            cwd=completed_python,
            prerequisites=(f"{completed_python}/tests",),
            owner="B2",
        ),
        "cross-tree-parity": cmd(
            "cross-tree-parity",
            [
                PYTHON,
                "analytics/scripts/validate_cross_tree_parity.py",
                "--allowlist",
                "analytics/config/cross-tree-parity-allowlist.json",
                "--normalize-seeds",
            ],
            prerequisites=(
                "analytics/scripts/validate_cross_tree_parity.py",
                "analytics/config/cross-tree-parity-allowlist.json",
            ),
            owner="B3",
        ),
        "exercise-tenant-policy": cmd(
            "exercise-tenant-policy",
            pytest_command("tests/test_optimization_tenant_scope.py"),
            cwd=exercise_python,
            prerequisites=(f"{exercise_python}/tests/test_optimization_tenant_scope.py",),
            owner="B4",
        ),
        "completed-tenant-policy": cmd(
            "completed-tenant-policy",
            pytest_command("tests/test_optimization_tenant_scope.py"),
            cwd=completed_python,
            prerequisites=(f"{completed_python}/tests/test_optimization_tenant_scope.py",),
            owner="B4",
        ),
        "exercise-python-full": cmd(
            "exercise-python-full",
            pytest_command("tests"),
            cwd=exercise_python,
            timeout=3600,
            prerequisites=(f"{exercise_python}/tests",),
            owner="G1",
        ),
        "completed-python-full": cmd(
            "completed-python-full",
            pytest_command("tests"),
            cwd=completed_python,
            timeout=3600,
            prerequisites=(f"{completed_python}/tests",),
            owner="G1",
        ),
        "exercise-frontend-build": cmd(
            "exercise-frontend-build",
            ["npm", "run", "build"],
            cwd="01_exercises/frontend",
            timeout=1800,
            prerequisites=("01_exercises/frontend/package.json",),
            owner="B5/G1",
        ),
        "exercise-frontend-tests": cmd(
            "exercise-frontend-tests",
            ["npm", "test", "--", "--watch=false", "--browsers=ChromeHeadless"],
            cwd="01_exercises/frontend",
            timeout=2400,
            prerequisites=("01_exercises/frontend/package.json",),
            owner="B5/G1",
            environment=(("CHROME_BIN", "available-chromium"),),
        ),
        "completed-frontend-build": cmd(
            "completed-frontend-build",
            ["npm", "run", "build"],
            cwd="02_completed/frontend",
            timeout=1800,
            prerequisites=("02_completed/frontend/package.json",),
            owner="B5/G1",
        ),
        "completed-frontend-tests": cmd(
            "completed-frontend-tests",
            ["npm", "test", "--", "--watch=false", "--browsers=ChromeHeadless"],
            cwd="02_completed/frontend",
            timeout=2400,
            prerequisites=("02_completed/frontend/package.json",),
            owner="B5/G1",
            environment=(("CHROME_BIN", "available-chromium"),),
        ),
        "controlled-http": cmd(
            "controlled-http",
            pytest_command("tests/test_controlled_demo4_http.py"),
            cwd=completed_python,
            prerequisites=(f"{completed_python}/tests/test_controlled_demo4_http.py",),
            owner="C0",
        ),
        "controlled-fixture": cmd(
            "controlled-fixture",
            pytest_command(
                "tests/test_controlled_demo4_dataset.py",
                "tests/test_controlled_demo4_transition.py",
                "tests/test_controlled_demo4_reporting.py",
                "tests/test_controlled_demo4_verifier.py",
                "tests/test_optimization_insight_alignment.py",
            ),
            cwd=completed_python,
            prerequisites=(f"{completed_python}/tests/test_controlled_demo4_dataset.py",),
            owner="C1/C3",
        ),
        "controlled-controls-tests": cmd(
            "controlled-controls-tests",
            pytest_command(
                "tests/test_lifecycle_coordinator.py",
                "tests/test_controlled_demo4_http.py",
            ),
            cwd=completed_python,
            prerequisites=(f"{completed_python}/tests/test_lifecycle_coordinator.py",),
            owner="C2",
        ),
        "controlled-controls-static": cmd(
            "controlled-controls-static",
            [PYTHON, "analytics/scripts/validate_controlled_demo4_controls.py"],
            prerequisites=("analytics/scripts/validate_controlled_demo4_controls.py",),
            owner="C2",
        ),
        "controlled-local-simulation": cmd(
            "controlled-local-simulation",
            [PYTHON, "data/verify_controlled_demo4.py", "--mode", "local-simulation"],
            cwd=completed_python,
            prerequisites=(f"{completed_python}/data/verify_controlled_demo4.py",),
            owner="C3/G2",
        ),
        "fabric-generation": cmd(
            "fabric-generation",
            [PYTHON, f"{fabric}/validate_fabric_assets.py", "--double-generate"],
            timeout=1800,
            prerequisites=(f"{fabric}/validate_fabric_assets.py",),
            owner="D1",
        ),
        "fabric-tests": cmd(
            "fabric-tests",
            pytest_command(f"{fabric}/tests"),
            prerequisites=(f"{fabric}/tests",),
            owner="D2",
        ),
        "fabric-source": cmd(
            "fabric-source",
            [PYTHON, f"{fabric}/validate_controlled_demo4_source.py"],
            prerequisites=(f"{fabric}/validate_controlled_demo4_source.py",),
            owner="D2",
        ),
        "powerbi-semantic": cmd(
            "powerbi-semantic",
            [PYTHON, f"{powerbi}/validate_tenant_switching.py"],
            prerequisites=(f"{powerbi}/validate_tenant_switching.py",),
            owner="E1",
        ),
        "powerbi-visual-freeze": cmd(
            "powerbi-visual-freeze",
            [
                PYTHON,
                f"{powerbi}/validate_tenant_switching.py",
                "--check-visual-freeze",
                "--intended-diff-manifest",
                f"{powerbi}/controlled_demo4_intended_diff.json",
            ],
            prerequisites=(
                f"{powerbi}/validate_tenant_switching.py",
                f"{powerbi}/controlled_demo4_visual_freeze.json",
                f"{powerbi}/controlled_demo4_intended_diff.json",
            ),
            owner="E2",
        ),
        "docs-validator-self-tests": cmd(
            "docs-validator-self-tests",
            [
                PYTHON,
                "-c",
                (
                    "import subprocess,sys;"
                    "files=['validate_workshop_contract_docs.py',"
                    "'validate_marvel_only_workshop.py','validate_word_flow_traceability.py'];"
                    "raise SystemExit(next((r.returncode for f in files "
                    "if (r:=subprocess.run([sys.executable,'analytics/scripts/'+f,"
                    "'--self-test'])).returncode),0))"
                ),
            ],
            prerequisites=(
                "analytics/scripts/validate_workshop_contract_docs.py",
                "analytics/scripts/validate_marvel_only_workshop.py",
                "analytics/scripts/validate_word_flow_traceability.py",
            ),
            owner="F0",
        ),
        "workshop-contract-docs": cmd(
            "workshop-contract-docs",
            [
                PYTHON,
                "analytics/scripts/validate_workshop_contract_docs.py",
                "--pins",
                "--delete",
                "--profile-vs-memory",
                "--trip-invariants",
                "--non-breakfast",
            ],
            prerequisites=("analytics/scripts/validate_workshop_contract_docs.py",),
            owner="F1",
        ),
        "markdown-links": cmd(
            "markdown-links",
            [
                PYTHON,
                "analytics/scripts/validate_markdown_links.py",
                "01_exercises/workshop",
                "02_completed",
                "analytics/docs",
                "analytics/fabric",
                "analytics/powerbi",
            ],
            prerequisites=("analytics/scripts/validate_markdown_links.py",),
            owner="F1",
        ),
        "marvel-only-workshop": cmd(
            "marvel-only-workshop",
            [
                PYTHON,
                "analytics/scripts/validate_marvel_only_workshop.py",
                "--modules",
                "07",
                "08",
                "09",
                "--allow-presenter-reference",
            ],
            prerequisites=("analytics/scripts/validate_marvel_only_workshop.py",),
            owner="F2",
        ),
        "presenter-docs": cmd(
            "presenter-docs",
            [
                PYTHON,
                "analytics/scripts/validate_word_flow_traceability.py",
                "--checklist",
                f"{evidence}/word-flow-traceability.json",
                "--docs",
                "analytics/docs/demo-script.md",
                "02_completed/README.md",
                "02_completed/USER_GUIDE.md",
                "analytics/powerbi/PowerBI_Optimization_Build_Guide.md",
            ],
            prerequisites=(
                "analytics/scripts/validate_word_flow_traceability.py",
                f"{evidence}/word-flow-traceability.json",
            ),
            owner="F3",
        ),
        "controlled-docs": cmd(
            "controlled-docs",
            [PYTHON, "analytics/scripts/validate_controlled_demo4_docs.py"],
            prerequisites=("analytics/scripts/validate_controlled_demo4_docs.py",),
            owner="F3/G2",
        ),
        "static-portal-freeze": cmd(
            "static-portal-freeze",
            [PYTHON, "analytics/scripts/validate_static_portal_freeze.py"],
            prerequisites=(
                "analytics/scripts/validate_static_portal_freeze.py",
                "analytics/config/static-portal-freeze.json",
            ),
            owner="G2",
        ),
        "changed-symbol-blast-radius": cmd(
            "changed-symbol-blast-radius",
            [
                PYTHON,
                "analytics/scripts/validate_changed_symbol_blast_radius.py",
                "--config",
                "analytics/config/changed-symbol-blast-radius.json",
                "--output",
                f"{evidence}/changed-symbol-blast-radius.json",
            ],
            prerequisites=(
                "analytics/scripts/validate_changed_symbol_blast_radius.py",
                "analytics/config/changed-symbol-blast-radius.json",
            ),
            produces=(f"{evidence}/changed-symbol-blast-radius.json",),
            owner="G0/G1",
        ),
        "runner-manifest-tests": cmd(
            "runner-manifest-tests",
            pytest_command(
                "analytics/scripts/tests/test_run_integration_verification.py",
                "analytics/scripts/tests/test_integration_accounting.py",
                "analytics/scripts/tests/test_validate_azd_project_config.py",
                "analytics/scripts/tests/test_validate_changed_symbol_blast_radius.py",
                "analytics/scripts/tests/test_validate_controlled_demo4_docs.py",
            ),
            prerequisites=(
                "analytics/scripts/tests/test_run_integration_verification.py",
                "analytics/scripts/tests/test_integration_accounting.py",
                "analytics/scripts/tests/test_validate_azd_project_config.py",
                "analytics/scripts/tests/test_validate_changed_symbol_blast_radius.py",
                "analytics/scripts/tests/test_validate_controlled_demo4_docs.py",
            ),
            owner="G0",
        ),
        "fabric-provision-staging": cmd(
            "fabric-provision-staging",
            [
                PYTHON,
                f"{fabric}/provision_fabric.py",
                "--environment",
                "staging",
                "--solution",
                "--verify-semantic-model",
                "--verify-report",
                "--connection-id",
                "${FABRIC_COSMOS_CONNECTION_ID}",
                "--subscription",
                "${AZURE_SUBSCRIPTION_ID}",
                "--resource-group",
                "${RG_NAME}",
                "--cosmos-endpoint",
                "${COSMOSDB_ENDPOINT}",
                "--capacity",
                "${FABRIC_CAPACITY_NAME}",
                "--evidence-output",
                "${FABRIC_STAGING_EVIDENCE_PATH}",
            ],
            timeout=7200,
            credentials="azure-fabric-staging",
            mutation="state-mutating",
            prerequisites=(f"{fabric}/provision_fabric.py",),
            produces=("${FABRIC_STAGING_EVIDENCE_PATH}",),
            owner="D2/G3",
        ),
        "final-accounting": cmd(
            "final-accounting",
            [
                PYTHON,
                "analytics/scripts/verify_integration_accounting.py",
                "--baseline",
                f"{evidence}/baseline.json",
                "--require-unchanged-head",
                "--require-unchanged-upstream",
                "--require-unchanged-index",
                "--require-complete-dirty-coverage",
                "--require-no-pr",
            ],
            prerequisites=(
                "analytics/scripts/verify_integration_accounting.py",
                f"{evidence}/baseline.json",
            ),
            owner="G3",
            finalizer=True,
        ),
    }


TASK_PHASES: dict[str, tuple[str, ...]] = {
    "a0-proof-tools": ("proof-tools-compile", "proof-tools-self-tests"),
    "a1-baseline": ("capture-baseline",),
    "a2-angular-parity": ("angular-parity",),
    "a3-excluded-artifacts": ("excluded-artifacts",),
    "a4-deployment-source": (
        "azd-project-config",
        "deployment-source-static",
        "deployment-source-build-all",
    ),
    "b0-cross-tree-validator": ("parity-validator-self-test",),
    "b1-memory-profile": ("exercise-memory-profile", "completed-memory-profile"),
    "b2-shared-trips": ("exercise-shared-trips", "completed-shared-trips"),
    "b3-cross-tree-parity": ("cross-tree-parity",),
    "b4-tenant-policy": ("exercise-tenant-policy", "completed-tenant-policy"),
    "b5-frontends": (
        "exercise-frontend-build",
        "exercise-frontend-tests",
        "completed-frontend-build",
        "completed-frontend-tests",
    ),
    "c0-controlled-http": ("controlled-http",),
    "c1-controlled-fixture": ("controlled-fixture",),
    "c2-controlled-controls": ("controlled-controls-tests", "controlled-controls-static"),
    "c3-controlled-reporting": ("controlled-fixture", "controlled-local-simulation"),
    "d1-fabric-generation": ("fabric-generation",),
    "d2-fabric-provisioning": ("fabric-tests", "fabric-source"),
    "e1-powerbi-semantic": ("powerbi-semantic",),
    "e2-powerbi-visual-freeze": ("powerbi-visual-freeze",),
    "f0-docs-validator-self-test": ("docs-validator-self-tests",),
    "f1-workshop-contract-docs": ("workshop-contract-docs", "markdown-links"),
    "f2-marvel-only-workshop": ("marvel-only-workshop",),
    "f3-presenter-docs": ("presenter-docs", "controlled-docs"),
}

def deduplicate_command_ids(*manifests: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(command_id for manifest in manifests for command_id in manifest))


_SHARED_COMMANDS = (
    "exercise-python-full",
    "completed-python-full",
    "exercise-frontend-build",
    "exercise-frontend-tests",
    "completed-frontend-build",
    "completed-frontend-tests",
    "cross-tree-parity",
    "changed-symbol-blast-radius",
)

_ANALYTICS_LOCAL_COMMANDS = (
    "controlled-fixture",
    "controlled-controls-tests",
    "controlled-controls-static",
    "controlled-local-simulation",
    "docs-validator-self-tests",
    "workshop-contract-docs",
    "marvel-only-workshop",
    "presenter-docs",
    "controlled-docs",
    "markdown-links",
    "fabric-generation",
    "fabric-tests",
    "fabric-source",
    "powerbi-semantic",
    "powerbi-visual-freeze",
    "static-portal-freeze",
    "azd-project-config",
    "deployment-source-static",
    "deployment-source-build-all",
)

AGGREGATE_PHASES: dict[str, tuple[str, ...]] = {
    "manifest-self-test": (
        "proof-tools-compile",
        "proof-tools-self-tests",
        "runner-manifest-tests",
    ),
    "shared": _SHARED_COMMANDS,
    "analytics-local": _ANALYTICS_LOCAL_COMMANDS,
    "comprehensive-local": deduplicate_command_ids(
        _SHARED_COMMANDS, _ANALYTICS_LOCAL_COMMANDS
    ),
    "staging-and-final-accounting": (
        "fabric-provision-staging",
        "final-accounting",
    ),
}

ALIASES: dict[str, str] = {
    "proof-tools-self-test": "a0-proof-tools",
    "angular-parity": "a2-angular-parity",
    "cross-tree-validator-self-test": "b0-cross-tree-validator",
    "memory-profile": "b1-memory-profile",
    "shared-trips": "b2-shared-trips",
    "cross-tree-parity": "b3-cross-tree-parity",
    "tenant-policy": "b4-tenant-policy",
    "frontends": "b5-frontends",
    "frontend-contract-specs": "b5-frontends",
    "controlled-fixture": "c1-controlled-fixture",
    "controlled-controls-http": "c2-controlled-controls",
    "controlled-local-simulation": "controlled-local-simulation",
    "fabric-generation": "d1-fabric-generation",
    "fabric-provision-staging": "fabric-provision-staging",
    "docs-validator-self-test": "f0-docs-validator-self-test",
    "presenter-docs": "f3-presenter-docs",
    "documentation-static": "f1-workshop-contract-docs",
    "deployment-source-builds": "deployment-source-static",
    "deployment-source-builds-all": "deployment-source-build-all",
    "final-accounting": "final-accounting",
}


def phase_manifest() -> dict[str, tuple[str, ...]]:
    return {**TASK_PHASES, **AGGREGATE_PHASES}


def resolve_phase(phase: str) -> tuple[CommandSpec, ...]:
    catalog = command_catalog()
    target = ALIASES.get(phase, phase)
    phases = phase_manifest()
    command_ids = phases.get(target, (target,))
    unknown = [command_id for command_id in command_ids if command_id not in catalog]
    if unknown:
        raise KeyError(f"unknown phase: {phase}")
    return tuple(catalog[command_id] for command_id in command_ids)


def metadata_errors(specs: tuple[CommandSpec, ...]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    produced: set[str] = set()
    for spec in specs:
        if spec.id in seen:
            errors.append(f"duplicate command id: {spec.id}")
        seen.add(spec.id)
        values = (
            spec.argv,
            spec.cwd,
            spec.evidence_path,
            spec.timeout_seconds,
            spec.credential_requirement,
            spec.mutation,
            spec.owner,
        )
        if any(value in (None, "", (), 0) for value in values):
            errors.append(f"incomplete metadata: {spec.id}")
        if spec.mutation not in MUTATIONS:
            errors.append(f"invalid mutation classification: {spec.id}")
        if spec.timeout_seconds <= 0:
            errors.append(f"invalid timeout: {spec.id}")
        for variable, provider in spec.environment:
            if not variable or not provider:
                errors.append(f"incomplete environment metadata: {spec.id}")
            if provider != "available-chromium":
                errors.append(
                    f"unknown environment provider: {spec.id}: {variable}={provider}"
                )
        for artifact in spec.prerequisites:
            if artifact.startswith(".local/") and artifact not in produced and not (ROOT / artifact).exists():
                errors.append(
                    f"artifact prerequisite is neither present nor produced earlier: "
                    f"{spec.id}: {artifact}"
                )
        produced.update(spec.produced_artifacts)
    return errors


def resolve_executable(
    executable: str, *, cwd: Path, env: dict[str, str] | None = None
) -> str | None:
    candidate = Path(executable)
    if candidate.is_absolute():
        return str(candidate) if candidate.is_file() else None
    if candidate.parent != Path("."):
        relative = (cwd / candidate).resolve()
        return str(relative) if relative.is_file() else None
    search_path = (env or os.environ).get("PATH")
    return shutil.which(executable, path=search_path)


def prepare_argv(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    substitutions: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
) -> list[str]:
    materialized = materialize_argv(argv, substitutions or {})
    resolved = resolve_executable(materialized[0], cwd=cwd, env=env)
    if resolved is None:
        raise FileNotFoundError(f"executable not found: {materialized[0]}")
    materialized[0] = resolved
    return materialized


def command_existence_errors(spec: CommandSpec) -> list[str]:
    errors: list[str] = []
    cwd = ROOT / spec.cwd
    if not cwd.is_dir():
        errors.append(f"cwd does not exist: {spec.cwd}")
    executable = spec.argv[0]
    if resolve_executable(executable, cwd=cwd) is None:
        errors.append(f"executable not found: {executable}")
    for prerequisite in spec.prerequisites:
        if prerequisite.startswith(".local/"):
            continue
        if not (ROOT / prerequisite).exists():
            errors.append(f"prerequisite does not exist: {prerequisite}")
    return errors


def validate_all_registered_commands() -> list[str]:
    errors: list[str] = []
    catalog = command_catalog()
    expected_tasks = {
        f"{letter}{number}"
        for letter, maximum in (("a", 4), ("b", 5), ("c", 3), ("d", 2), ("e", 2), ("f", 3))
        for number in range(0 if letter in {"a", "b", "c", "f"} else 1, maximum + 1)
    }
    actual_tasks = {name.split("-", 1)[0] for name in TASK_PHASES}
    if actual_tasks != expected_tasks:
        errors.append(
            f"leaf phase coverage mismatch: missing={sorted(expected_tasks-actual_tasks)} "
            f"extra={sorted(actual_tasks-expected_tasks)}"
        )
    for phase, command_ids in phase_manifest().items():
        specs = tuple(catalog[command_id] for command_id in command_ids)
        errors.extend(f"{phase}: {error}" for error in metadata_errors(specs))
        for spec in specs:
            errors.extend(
                f"{phase}: {spec.id}: {error}" for error in command_existence_errors(spec)
            )
    return sorted(set(errors))


def _azd_values() -> dict[str, str]:
    cwd = ROOT / "02_completed"
    try:
        argv = prepare_argv(
            ("azd", "env", "get-values", "--output", "json"), cwd=cwd
        )
        completed = subprocess.run(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode:
        return {}
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def _fabric_access_token() -> tuple[str | None, str]:
    commands: list[tuple[str, ...]] = []
    if sys.platform.startswith("win"):
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if powershell:
            script = (
                "$ProgressPreference='SilentlyContinue';"
                "$WarningPreference='SilentlyContinue';"
                "$token=(Get-AzAccessToken -ResourceUrl "
                f"'{FABRIC_API}' -ErrorAction Stop -WarningAction SilentlyContinue).Token;"
                "if($token -is [System.Security.SecureString]){"
                "$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($token);"
                "try{[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)}"
                "finally{[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}}"
                "else{$token}"
            )
            commands.append(
                (powershell, "-NoProfile", "-NonInteractive", "-Command", script)
            )
    az = shutil.which("az")
    if az:
        commands.append(
            (
                az,
                "account",
                "get-access-token",
                "--resource",
                FABRIC_API,
                "--query",
                "accessToken",
                "--output",
                "tsv",
            )
        )
    if not commands:
        return None, "Fabric authentication tools are unavailable"
    for argv in commands:
        try:
            completed = subprocess.run(
                list(argv),
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                check=False,
                timeout=30,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
        token = completed.stdout.strip() if completed.returncode == 0 else ""
        if token:
            return token, ""
    return None, "Fabric authentication is unavailable"


def _fabric_connections(token: str) -> tuple[list[dict[str, Any]] | None, str]:
    request = urllib.request.Request(
        f"{FABRIC_API}/v1/connections",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return None, f"Fabric connections API returned HTTP {exc.code}"
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None, "Fabric connections API is unavailable"
    values = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return None, "Fabric connections API returned an invalid response"
    return [item for item in values if isinstance(item, dict)], ""


def _connection_detail_strings(value: Any, key: str = "") -> list[str]:
    strings: list[str] = []
    if isinstance(value, dict):
        parameter_name = str(value.get("name", "")).casefold()
        if parameter_name in {
            "accountendpoint",
            "cosmosdbendpoint",
            "endpoint",
            "host",
            "server",
            "url",
        }:
            strings.extend(_connection_detail_strings(value.get("value"), parameter_name))
        for child_key, child_value in value.items():
            strings.extend(_connection_detail_strings(child_value, str(child_key)))
    elif isinstance(value, list):
        for item in value:
            strings.extend(_connection_detail_strings(item, key))
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                strings.extend(_connection_detail_strings(json.loads(stripped), key))
            except json.JSONDecodeError:
                pass
        if key.casefold() in {
            "accountendpoint",
            "cosmosdbendpoint",
            "endpoint",
            "host",
            "server",
            "url",
        }:
            strings.append(stripped)
    return strings


def _host(value: str) -> str:
    parsed = urlparse(value if "://" in value else f"//{value}")
    return (parsed.hostname or "").rstrip(".").casefold()


def _is_cosmos_shareable_cloud(connection: dict[str, Any]) -> bool:
    if str(connection.get("connectivityType", "")).casefold() != "shareablecloud":
        return False
    type_values = [
        connection.get("type"),
        connection.get("connectionType"),
        connection.get("dataSourceType"),
    ]
    details = connection.get("connectionDetails")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except json.JSONDecodeError:
            details = {}
    if isinstance(details, dict):
        type_values.extend(
            details.get(key)
            for key in ("type", "connectionType", "dataSourceType", "moduleName")
        )
    return any(
        "cosmos" in str(value).casefold()
        for value in type_values
        if value is not None
    )


def _select_fabric_cosmos_connection(
    connections: list[dict[str, Any]],
    *,
    cosmos_endpoint: str,
    preferred_names: tuple[str, ...],
) -> tuple[str | None, str]:
    target_host = _host(cosmos_endpoint)
    if not target_host:
        return None, "COSMOSDB_ENDPOINT does not contain a valid host"
    host_matches = [
        connection
        for connection in connections
        if _is_cosmos_shareable_cloud(connection)
        and target_host
        in {
            _host(value)
            for value in _connection_detail_strings(
                connection.get("connectionDetails", {})
            )
        }
    ]
    if not host_matches:
        return None, f"no Fabric Cosmos connection matches host {target_host}"
    for preferred_name in preferred_names:
        preferred_matches = [
            connection
            for connection in host_matches
            if str(connection.get("displayName", "")) == preferred_name
        ]
        if len(preferred_matches) == 1 and preferred_matches[0].get("id"):
            return str(preferred_matches[0]["id"]), ""
        if len(preferred_matches) > 1:
            return (
                None,
                f"multiple preferred Fabric Cosmos connections named "
                f"{preferred_name!r} match host {target_host}",
            )
    if len(host_matches) == 1 and host_matches[0].get("id"):
        return str(host_matches[0]["id"]), ""
    return (
        None,
        f"multiple Fabric Cosmos connections match host {target_host}",
    )


def _discover_fabric_cosmos_connection(
    values: dict[str, str],
) -> tuple[str | None, str]:
    token, reason = _fabric_access_token()
    if token is None:
        return None, reason
    connections, reason = _fabric_connections(token)
    token = ""
    if connections is None:
        return None, reason
    configured_names = tuple(
        dict.fromkeys(
            name
            for name in (
                values.get("FABRIC_WORKSPACE_NAME"),
                values.get("FABRIC_WORKSPACE_DISPLAY_NAME"),
                values.get("WORKSPACE_NAME"),
            )
            if name
        )
    )
    preferred_names = tuple(
        dict.fromkeys((*configured_names, DEFAULT_FABRIC_CONNECTION_NAME))
    )
    return _select_fabric_cosmos_connection(
        connections,
        cosmos_endpoint=values.get("COSMOSDB_ENDPOINT", ""),
        preferred_names=preferred_names,
    )


def credential_preflight(requirement: str) -> tuple[bool, str, dict[str, str]]:
    if requirement == "none":
        return True, "", {}
    if requirement != "azure-fabric-staging":
        return False, f"unknown credential requirement: {requirement}", {}
    if not shutil.which("azd"):
        return False, "azd is required for staging configuration", {}
    values = _azd_values()
    connection_id = (
        os.environ.get("FABRIC_COSMOS_CONNECTION_ID")
        or os.environ.get("FABRIC_CONNECTION_ID")
        or values.get("FABRIC_COSMOS_CONNECTION_ID")
        or values.get("FABRIC_CONNECTION_ID")
    )
    required_groups = {
        "subscription": values.get("AZURE_SUBSCRIPTION_ID") or values.get("SUBSCRIPTION_ID"),
        "resource group": values.get("AZURE_RESOURCE_GROUP") or values.get("RG_NAME"),
        "Cosmos endpoint": values.get("COSMOSDB_ENDPOINT"),
        "Fabric capacity": values.get("FABRIC_CAPACITY_NAME"),
    }
    missing = [name for name, value in required_groups.items() if not value]
    if missing:
        return False, f"missing staging configuration: {', '.join(missing)}", {}
    if not connection_id:
        connection_id, reason = _discover_fabric_cosmos_connection(values)
        if connection_id is None:
            return False, reason, {}
    return True, "", {
        "FABRIC_COSMOS_CONNECTION_ID": str(connection_id),
        "AZURE_SUBSCRIPTION_ID": str(required_groups["subscription"]),
        "RG_NAME": str(required_groups["resource group"]),
        "COSMOSDB_ENDPOINT": str(required_groups["Cosmos endpoint"]),
        "FABRIC_CAPACITY_NAME": str(required_groups["Fabric capacity"]),
    }


def materialize_argv(argv: tuple[str, ...], substitutions: dict[str, str]) -> list[str]:
    result: list[str] = []
    for value in argv:
        if value.startswith("${") and value.endswith("}"):
            key = value[2:-1]
            if key not in substitutions:
                raise KeyError(key)
            result.append(substitutions[key])
        else:
            result.append(value)
    return result


def redact_argv(
    declared_argv: tuple[str, ...],
    executed_argv: list[str],
    substitutions: dict[str, str],
) -> list[str]:
    redacted = list(executed_argv)
    for index, declared in enumerate(declared_argv):
        if declared.startswith("${") and declared.endswith("}"):
            key = declared[2:-1]
            if key in substitutions and key in SENSITIVE_SUBSTITUTIONS:
                redacted[index] = f"<redacted:{key}>"
    return redacted


def redact_output(output: bytes, substitutions: dict[str, str]) -> bytes:
    redacted = output
    for key, value in substitutions.items():
        if key not in SENSITIVE_SUBSTITUTIONS:
            continue
        if value:
            redacted = redacted.replace(value.encode("utf-8"), b"<redacted>")
    return redacted


def find_available_chromium(environment: dict[str, str]) -> str | None:
    configured = environment.get("CHROME_BIN")
    candidates = [
        configured,
        str(Path(environment.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe"),
        str(
            Path(environment.get("PROGRAMFILES(X86)", ""))
            / "Google/Chrome/Application/chrome.exe"
        ),
        str(Path(environment.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe"),
        str(
            Path(environment.get("PROGRAMFILES(X86)", ""))
            / "Microsoft/Edge/Application/msedge.exe"
        ),
        str(
            Path(environment.get("LOCALAPPDATA", ""))
            / "Google/Chrome/Application/chrome.exe"
        ),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    for executable in ("google-chrome", "chrome", "chromium", "chromium-browser", "msedge"):
        resolved = shutil.which(executable, path=environment.get("PATH"))
        if resolved and Path(resolved).is_file():
            return str(Path(resolved).resolve())
    return None


def environment_preflight(
    requirements: tuple[tuple[str, str], ...],
    environment: dict[str, str],
) -> tuple[bool, str, dict[str, str], dict[str, Any]]:
    updates: dict[str, str] = {}
    selected_executables: dict[str, str] = {}
    for variable, provider in requirements:
        if provider != "available-chromium":
            return (
                False,
                f"unknown environment provider: {variable}={provider}",
                {},
                {},
            )
        executable = find_available_chromium({**environment, **updates})
        if executable is None:
            return (
                False,
                f"no Chrome, Chromium, or Microsoft Edge executable found for {variable}",
                {},
                {},
            )
        updates[variable] = executable
        selected_executables[variable] = executable
    evidence = {
        "variable_names": [variable for variable, _provider in requirements],
        "selected_executables": selected_executables,
    }
    return True, "", updates, evidence


def evidence_record(
    spec: CommandSpec,
    *,
    status: str,
    started: str,
    completed: str,
    exit_code: int | None,
    output: bytes,
    output_path: Path,
    reason: str = "",
    executed_argv: list[str] | None = None,
    environment_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(status)
    return {
        "schema_version": 1,
        "id": spec.id,
        "owner": spec.owner,
        "argv": list(spec.argv),
        "executed_argv": executed_argv,
        "cwd": spec.cwd,
        "evidence_path": rel(output_path),
        "timeout_seconds": spec.timeout_seconds,
        "credential_requirement": spec.credential_requirement,
        "mutation": spec.mutation,
        "prerequisites": list(spec.prerequisites),
        "produced_artifacts": list(spec.produced_artifacts),
        "environment": environment_evidence
        or {
            "variable_names": [variable for variable, _provider in spec.environment],
            "selected_executables": {},
        },
        "finalizer": spec.finalizer,
        "started_utc": started,
        "completed_utc": completed,
        "exit_code": exit_code,
        "combined_output_bytes": len(output),
        "combined_output_sha256": hashlib.sha256(output).hexdigest(),
        "status": status,
        "reason": reason,
    }


def write_record(record: dict[str, Any], output_path: Path) -> None:
    record_path = output_path.with_suffix(".json")
    record_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def unverified_record(
    spec: CommandSpec,
    evidence_dir: Path,
    reason: str,
    environment_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_path = evidence_dir / spec.evidence_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = (reason + "\n").encode("utf-8")
    output_path.write_bytes(output)
    timestamp = utc_now()
    record = evidence_record(
        spec,
        status="Unverified",
        started=timestamp,
        completed=timestamp,
        exit_code=None,
        output=output,
        output_path=output_path,
        reason=reason,
        environment_evidence=environment_evidence,
    )
    write_record(record, output_path)
    return record


def execute_command(spec: CommandSpec, evidence_dir: Path) -> dict[str, Any]:
    output_path = evidence_dir / spec.evidence_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    missing = command_existence_errors(spec)
    missing.extend(
        f"artifact not found: {path}"
        for path in spec.prerequisites
        if path.startswith(".local/") and not (ROOT / path).exists()
    )
    if missing:
        return unverified_record(spec, evidence_dir, "; ".join(missing))
    ready, reason, substitutions = credential_preflight(spec.credential_requirement)
    if not ready:
        return unverified_record(spec, evidence_dir, reason)
    substitutions["FABRIC_STAGING_EVIDENCE_PATH"] = str(
        evidence_dir / "fabric-provision-staging.json"
    )
    started = utc_now()
    executed_argv: list[str] | None = None
    real_argv: list[str] | None = None
    environment_evidence: dict[str, Any] | None = None
    try:
        environment = os.environ.copy()
        environment_ready, environment_reason, environment_updates, environment_evidence = (
            environment_preflight(spec.environment, environment)
        )
        if not environment_ready:
            return unverified_record(
                spec,
                evidence_dir,
                environment_reason,
                environment_evidence=environment_evidence,
            )
        environment.update(environment_updates)
        real_argv = prepare_argv(
            spec.argv,
            cwd=ROOT / spec.cwd,
            substitutions=substitutions,
            env=environment,
        )
        executed_argv = redact_argv(spec.argv, real_argv, substitutions)
        completed = subprocess.run(
            real_argv,
            cwd=ROOT / spec.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            check=False,
            timeout=spec.timeout_seconds,
            env=environment,
        )
        output = redact_output(completed.stdout, substitutions)
        exit_code: int | None = completed.returncode
        status = "Verified" if completed.returncode == 0 else "Failed"
        reason = "" if completed.returncode == 0 else f"exit code {completed.returncode}"
        if spec.credential_requirement != "none" and completed.returncode == 2:
            status = "Unverified"
            reason = "staging command reported unavailable credentials/configuration/infrastructure"
    except subprocess.TimeoutExpired as exc:
        output = redact_output(
            (exc.stdout or b"") + (exc.stderr or b""), substitutions
        )
        exit_code = None
        status = "Failed"
        reason = f"timed out after {spec.timeout_seconds} seconds"
    except FileNotFoundError as exc:
        reason = f"executable could not be started: {spec.argv[0]} ({exc})"
        output = (reason + "\n").encode("utf-8")
        exit_code = None
        status = "Unverified"
    except OSError as exc:
        reason = f"command could not be started: {exc}"
        output = (reason + "\n").encode("utf-8")
        exit_code = None
        status = "Failed"
    reason = redact_output(reason.encode("utf-8"), substitutions).decode("utf-8")
    output = redact_output(output, substitutions)
    output_path.write_bytes(output)
    record = evidence_record(
        spec,
        status=status,
        started=started,
        completed=utc_now(),
        exit_code=exit_code,
        output=output,
        output_path=output_path,
        reason=reason,
        executed_argv=executed_argv,
        environment_evidence=environment_evidence,
    )
    write_record(record, output_path)
    return record


def run_specs(
    specs: tuple[CommandSpec, ...], evidence_dir: Path
) -> tuple[int, list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    blocking_failure = False
    for spec in specs:
        if blocking_failure and not spec.finalizer:
            records.append(
                unverified_record(
                    spec, evidence_dir, "blocked by an earlier blocking failure"
                )
            )
            continue
        record = execute_command(spec, evidence_dir)
        records.append(record)
        if record["status"] != "Verified" and not spec.finalizer:
            blocking_failure = True
    statuses = {record["status"] for record in records}
    if "Failed" in statuses:
        return 1, records
    if "Unverified" in statuses:
        return 2, records
    return 0, records


def write_phase_summary(
    phase: str, evidence_dir: Path, records: list[dict[str, Any]]
) -> Path:
    summary = {
        "schema_version": 1,
        "run_id": evidence_dir.name,
        "run_evidence_path": rel(evidence_dir),
        "phase": phase,
        "completed_utc": utc_now(),
        "status": (
            "Failed"
            if any(record["status"] == "Failed" for record in records)
            else "Unverified"
            if any(record["status"] == "Unverified" for record in records)
            else "Verified"
        ),
        "commands": records,
    }
    path = evidence_dir / "phases" / f"{phase}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_latest_run_pointer(
    evidence_root: Path, phase: str, summary_path: Path
) -> Path:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    pointer = {
        "schema_version": 1,
        "run_id": summary["run_id"],
        "phase": phase,
        "status": summary["status"],
        "completed_utc": summary["completed_utc"],
        "phase_summary_path": rel(summary_path),
    }
    path = evidence_root / "latest-run.json"
    temporary = evidence_root / f".latest-run.{uuid.uuid4().hex}.tmp"
    temporary.write_text(
        json.dumps(pointer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--phase")
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--evidence-dir", default=".local/integration-evidence")
    parser.add_argument("--list-phases", action="store_true")
    # Retained for command-line compatibility; the fixture command itself owns the contract.
    parser.add_argument("--require-fixture-versions", action="store_true")
    parser.add_argument("--require-exact-tenant-counts", action="store_true")
    parser.add_argument("--require-exact-model-mixes", action="store_true")
    parser.add_argument("--require-normalized-canonical-seeds", action="store_true")
    parser.add_argument("--require-derived-clear", action="store_true")
    parser.add_argument("--require-reset-count", type=int)
    parser.add_argument("--require-backup-restore", action="store_true")
    parser.add_argument("--require-operational-trip-protection", action="store_true")
    return parser


def validate_controlled_fixture_requirements(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    names = (
        "require_fixture_versions",
        "require_exact_tenant_counts",
        "require_exact_model_mixes",
        "require_normalized_canonical_seeds",
        "require_derived_clear",
        "require_backup_restore",
        "require_operational_trip_protection",
    )
    supplied = any(getattr(args, name) for name in names) or args.require_reset_count is not None
    target = ALIASES.get(args.phase or "", args.phase or "")
    if target != "c1-controlled-fixture":
        if supplied:
            parser.error("controlled fixture requirement flags require --phase controlled-fixture")
        return
    missing = [name.replace("_", "-") for name in names if not getattr(args, name)]
    if supplied and (missing or args.require_reset_count != 2):
        parser.error(
            "controlled-fixture requires every require-* contract flag and "
            f"--require-reset-count 2 (missing: {', '.join(missing) if missing else 'none'})"
        )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.list_phases:
        print("\n".join(sorted(phase_manifest())))
        return 0
    if args.local:
        if args.phase:
            parser.error("--local and --phase are mutually exclusive")
        phase = "comprehensive-local"
        specs = resolve_phase(phase)
    else:
        if not args.phase:
            parser.error("--phase is required unless --local or --list-phases is used")
        phase = args.phase
        try:
            specs = resolve_phase(phase)
        except KeyError as exc:
            parser.error(str(exc))
    validate_controlled_fixture_requirements(args, parser)
    manifest_issues = validate_all_registered_commands()
    selected_issues = metadata_errors(specs)
    evidence_root = (ROOT / args.evidence_dir).resolve()
    evidence_dir = create_run_namespace(evidence_root)
    if manifest_issues or selected_issues:
        reason = "manifest preflight failed: " + "; ".join(
            sorted(set(manifest_issues + selected_issues))
        )
        records = [unverified_record(spec, evidence_dir, reason) for spec in specs]
        summary = write_phase_summary(phase, evidence_dir, records)
        write_latest_run_pointer(evidence_root, phase, summary)
        print(reason, file=sys.stderr)
        print(f"PHASE_EVIDENCE={rel(summary)}")
        return 2
    result, records = run_specs(specs, evidence_dir)
    summary = write_phase_summary(phase, evidence_dir, records)
    write_latest_run_pointer(evidence_root, phase, summary)
    for record in records:
        print(f"{record['status']}: {record['id']} ({record['reason'] or 'exit 0'})")
    print(f"PHASE_EVIDENCE={rel(summary)}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())

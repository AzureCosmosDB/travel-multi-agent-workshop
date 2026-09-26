from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "run_integration_verification.py"
SPEC = importlib.util.spec_from_file_location("run_integration_verification", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def parse(*arguments: str):
    return runner.build_parser().parse_args(arguments)


def test_all_a_through_f_leaf_phases_and_required_aggregates_are_registered():
    expected_leaf_phases = {
        "a0-proof-tools",
        "a1-baseline",
        "a2-angular-parity",
        "a3-excluded-artifacts",
        "a4-deployment-source",
        "b0-cross-tree-validator",
        "b1-memory-profile",
        "b2-shared-trips",
        "b3-cross-tree-parity",
        "b4-tenant-policy",
        "b5-frontends",
        "c0-controlled-http",
        "c1-controlled-fixture",
        "c2-controlled-controls",
        "c3-controlled-reporting",
        "d1-fabric-generation",
        "d2-fabric-provisioning",
        "e1-powerbi-semantic",
        "e2-powerbi-visual-freeze",
        "f0-docs-validator-self-test",
        "f1-workshop-contract-docs",
        "f2-marvel-only-workshop",
        "f3-presenter-docs",
    }
    assert set(runner.TASK_PHASES) == expected_leaf_phases
    assert {
        "manifest-self-test",
        "shared",
        "analytics-local",
        "comprehensive-local",
        "staging-and-final-accounting",
    } <= set(runner.AGGREGATE_PHASES)


def test_every_command_has_complete_required_metadata():
    for spec in runner.command_catalog().values():
        assert spec.argv
        assert spec.cwd
        assert spec.evidence_path
        assert spec.timeout_seconds > 0
        assert spec.credential_requirement
        assert spec.mutation in runner.MUTATIONS
        assert spec.owner
        assert isinstance(spec.prerequisites, tuple)
        assert isinstance(spec.produced_artifacts, tuple)
        assert isinstance(spec.environment, tuple)


def test_all_registered_commands_and_prerequisites_exist():
    assert runner.validate_all_registered_commands() == []


def test_artifact_dependency_must_be_present_or_produced_earlier(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    producer = runner.cmd(
        "producer",
        ["python", "-c", "pass"],
        owner="test",
        produces=(".local/evidence.json",),
    )
    consumer = runner.cmd(
        "consumer",
        ["python", "-c", "pass"],
        owner="test",
        prerequisites=(".local/evidence.json",),
    )

    assert runner.metadata_errors((producer, consumer)) == []
    errors = runner.metadata_errors((consumer, producer))
    assert any("neither present nor produced earlier" in error for error in errors)


def test_shared_phase_contains_full_suites_frontends_parity_and_blast_radius():
    command_ids = [spec.id for spec in runner.resolve_phase("shared")]

    assert command_ids == [
        "exercise-python-full",
        "completed-python-full",
        "exercise-frontend-build",
        "exercise-frontend-tests",
        "completed-frontend-build",
        "completed-frontend-tests",
        "cross-tree-parity",
        "changed-symbol-blast-radius",
    ]


def test_frontend_test_commands_require_available_chromium():
    catalog = runner.command_catalog()

    assert catalog["exercise-frontend-tests"].environment == (
        ("CHROME_BIN", "available-chromium"),
    )
    assert catalog["completed-frontend-tests"].environment == (
        ("CHROME_BIN", "available-chromium"),
    )


def test_browser_preflight_prefers_valid_chrome_bin(tmp_path, monkeypatch):
    configured = tmp_path / "configured-browser.exe"
    configured.write_bytes(b"browser")
    monkeypatch.setattr(runner.shutil, "which", lambda *_args, **_kwargs: None)

    selected = runner.find_available_chromium(
        {"CHROME_BIN": str(configured), "PATH": ""}
    )

    assert selected == str(configured.resolve())


def test_browser_preflight_falls_back_to_installed_edge(tmp_path, monkeypatch):
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_bytes(b"browser")
    monkeypatch.setattr(runner.shutil, "which", lambda *_args, **_kwargs: None)

    selected = runner.find_available_chromium(
        {"PROGRAMFILES(X86)": str(tmp_path), "PATH": ""}
    )

    assert selected == str(edge.resolve())


def test_environment_preflight_records_names_and_browser_path_only(tmp_path):
    browser = tmp_path / "browser.exe"
    browser.write_bytes(b"browser")
    source_environment = {
        "CHROME_BIN": str(browser),
        "SECRET_TOKEN": "must-not-appear",
    }

    ready, reason, updates, evidence = runner.environment_preflight(
        (("CHROME_BIN", "available-chromium"),),
        source_environment,
    )

    assert ready is True
    assert reason == ""
    assert updates == {"CHROME_BIN": str(browser.resolve())}
    assert evidence == {
        "variable_names": ["CHROME_BIN"],
        "selected_executables": {"CHROME_BIN": str(browser.resolve())},
    }
    assert "SECRET_TOKEN" not in str(evidence)


def test_analytics_local_registers_all_required_local_gates():
    command_ids = {spec.id for spec in runner.resolve_phase("analytics-local")}

    assert {
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
    } <= command_ids


def test_comprehensive_local_is_shared_then_analytics_local_deduplicated():
    shared = [spec.id for spec in runner.resolve_phase("shared")]
    analytics = [spec.id for spec in runner.resolve_phase("analytics-local")]
    comprehensive = [
        spec.id for spec in runner.resolve_phase("comprehensive-local")
    ]

    assert comprehensive == list(dict.fromkeys(shared + analytics))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_successful_parity_runs_blast_radius_and_evidence_is_immutable(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    evidence_root = tmp_path / "evidence"
    parity = runner.cmd(
        "cross-tree-parity",
        [
            sys.executable,
            "-c",
            "print('cross-tree parity: PASS (canonical trees match)')",
        ],
        owner="test",
    )
    blast = runner.cmd(
        "changed-symbol-blast-radius",
        [sys.executable, "-c", "print('changed-symbol blast radius: PASS')"],
        owner="test",
    )

    first_run = runner.create_run_namespace(evidence_root)
    first_code, first_records = runner.run_specs((parity, blast), first_run)
    first_summary = runner.write_phase_summary("shared", first_run, first_records)
    runner.write_latest_run_pointer(evidence_root, "shared", first_summary)

    assert first_code == 0
    assert [(record["id"], record["status"], record["exit_code"]) for record in first_records] == [
        ("cross-tree-parity", "Verified", 0),
        ("changed-symbol-blast-radius", "Verified", 0),
    ]
    parity_log = first_run / parity.evidence_path
    assert "cross-tree parity: PASS" in parity_log.read_text(encoding="utf-8")
    first_hashes = {
        path: file_sha256(path)
        for path in (
            parity_log,
            parity_log.with_suffix(".json"),
            first_run / blast.evidence_path,
            first_run / blast.evidence_path.replace(".log", ".json"),
            first_summary,
        )
    }
    first_summary_document = json.loads(first_summary.read_text(encoding="utf-8"))
    assert first_summary_document["commands"][0]["evidence_path"] == runner.rel(parity_log)

    second_run = runner.create_run_namespace(evidence_root)
    second_code, second_records = runner.run_specs((parity, blast), second_run)
    second_summary = runner.write_phase_summary("shared", second_run, second_records)
    runner.write_latest_run_pointer(evidence_root, "shared", second_summary)

    assert second_code == 0
    assert first_run != second_run
    assert first_summary != second_summary
    assert all(file_sha256(path) == digest for path, digest in first_hashes.items())
    latest = json.loads((evidence_root / "latest-run.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == second_run.name
    assert latest["phase_summary_path"] == runner.rel(second_summary)


def test_nonzero_parity_is_failed_and_blocks_blast_radius(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    marker = tmp_path / "blast-ran"
    parity = runner.cmd(
        "cross-tree-parity",
        [
            sys.executable,
            "-c",
            "print('cross-tree parity: PASS text is not an exit code');raise SystemExit(1)",
        ],
        owner="test",
    )
    blast = runner.cmd(
        "changed-symbol-blast-radius",
        [sys.executable, "-c", f"from pathlib import Path;Path({str(marker)!r}).touch()"],
        owner="test",
    )
    run_dir = runner.create_run_namespace(tmp_path / "evidence")

    code, records = runner.run_specs((parity, blast), run_dir)

    assert code == 1
    assert records[0]["status"] == "Failed"
    assert records[0]["exit_code"] == 1
    assert records[1]["status"] == "Unverified"
    assert records[1]["reason"] == "blocked by an earlier blocking failure"
    assert not marker.exists()


def test_azd_project_gate_precedes_source_builds_and_has_evidence_metadata():
    command_ids = [spec.id for spec in runner.resolve_phase("a4-deployment-source")]
    catalog = runner.command_catalog()

    assert command_ids == [
        "azd-project-config",
        "deployment-source-static",
        "deployment-source-build-all",
    ]
    gate = catalog["azd-project-config"]
    assert gate.owner == "A4/G2"
    assert gate.mutation == "read-only"
    assert gate.produced_artifacts == (
        ".local/integration-evidence/azd-project-config.json",
    )
    assert gate.prerequisites == (
        "analytics/scripts/validate_azd_project_config.py",
        "02_completed/azure.yaml",
    )


def test_staging_uses_real_cloud_interface_and_accounting_is_finalizer():
    staging, accounting = runner.resolve_phase("staging-and-final-accounting")

    assert staging.mutation == "state-mutating"
    assert staging.credential_requirement == "azure-fabric-staging"
    assert "--environment" in staging.argv
    assert "staging" in staging.argv
    assert "--solution" in staging.argv
    assert "--verify-semantic-model" in staging.argv
    assert "--verify-report" in staging.argv
    assert "--no-cloud" not in staging.argv
    assert (
        "--subscription",
        "${AZURE_SUBSCRIPTION_ID}",
        "--resource-group",
        "${RG_NAME}",
        "--cosmos-endpoint",
        "${COSMOSDB_ENDPOINT}",
        "--capacity",
        "${FABRIC_CAPACITY_NAME}",
    ) == staging.argv[staging.argv.index("--subscription") : staging.argv.index("--evidence-output")]
    assert staging.argv[-1] == "${FABRIC_STAGING_EVIDENCE_PATH}"
    assert accounting.finalizer is True
    assert accounting.mutation == "read-only"


def test_excluded_artifacts_requires_brief_f_relocation_evidence():
    (spec,) = runner.resolve_phase("a3-excluded-artifacts")

    assert (
        ".local/integration-evidence/brief-f/relocation.json"
        in spec.prerequisites
    )
    command = " ".join(spec.argv)
    assert "analytics/qa_report_f.txt" in command
    assert "validate-brief-f.ps1" in command


def test_first_blocking_failure_skips_normal_commands_but_runs_finalizer(
    tmp_path, monkeypatch
):
    calls: list[str] = []
    first = runner.cmd("first", ["python", "-c", "pass"], owner="test")
    second = runner.cmd("second", ["python", "-c", "pass"], owner="test")
    final = runner.cmd(
        "final", ["python", "-c", "pass"], owner="test", finalizer=True
    )

    def fake_execute(spec, evidence_dir):
        calls.append(spec.id)
        return {
            "id": spec.id,
            "status": "Failed" if spec.id == "first" else "Verified",
            "reason": "",
        }

    monkeypatch.setattr(runner, "execute_command", fake_execute)
    code, records = runner.run_specs((first, second, final), tmp_path)

    assert code == 1
    assert calls == ["first", "final"]
    assert [record["status"] for record in records] == [
        "Failed",
        "Unverified",
        "Verified",
    ]
    assert records[1]["reason"] == "blocked by an earlier blocking failure"


def test_unverified_is_blocking_and_never_reported_as_verified(tmp_path, monkeypatch):
    spec = runner.cmd("cloud", ["python", "-c", "pass"], owner="test")
    monkeypatch.setattr(
        runner,
        "execute_command",
        lambda *_: {"id": "cloud", "status": "Unverified", "reason": "no auth"},
    )

    code, records = runner.run_specs((spec,), tmp_path)

    assert code == 2
    assert records[0]["status"] == "Unverified"
    assert set(record["status"] for record in records) <= runner.STATUSES


def test_missing_live_credentials_produce_blocking_unverified_evidence(
    tmp_path, monkeypatch
):
    spec = runner.cmd(
        "staging",
        [runner.PYTHON, "-c", "raise SystemExit('must not run')"],
        owner="test",
        credentials="azure-fabric-staging",
    )
    monkeypatch.setattr(
        runner,
        "credential_preflight",
        lambda _requirement: (False, "Azure CLI authentication is unavailable", {}),
    )

    record = runner.execute_command(spec, tmp_path)

    assert record["status"] == "Unverified"
    assert record["exit_code"] is None
    assert "authentication is unavailable" in record["reason"]
    assert (tmp_path / spec.evidence_path).is_file()
    assert (tmp_path / spec.evidence_path).with_suffix(".json").is_file()


def test_azd_values_uses_completed_tree_as_exact_cwd(tmp_path, monkeypatch):
    completed_root = tmp_path / "02_completed"
    completed_root.mkdir()
    azd = tmp_path / "azd.cmd"
    azd.write_text("@echo off\n", encoding="utf-8")
    observed: dict[str, object] = {}

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda executable, path=None: str(azd) if executable == "azd" else None,
    )

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["cwd"] = kwargs["cwd"]
        return runner.subprocess.CompletedProcess(
            argv, 0, stdout='{"COSMOSDB_ENDPOINT":"https://acct.documents.azure.com:443/"}'
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    values = runner._azd_values()

    assert observed == {
        "argv": [str(azd), "env", "get-values", "--output", "json"],
        "cwd": completed_root,
    }
    assert values["COSMOSDB_ENDPOINT"].startswith("https://acct.")


def fabric_connection(
    connection_id: str,
    display_name: str,
    host: str = "https://acct.documents.azure.com:443/",
):
    return {
        "id": connection_id,
        "displayName": display_name,
        "connectivityType": "ShareableCloud",
        "connectionDetails": {
            "type": "AzureCosmosDB",
            "parameters": [{"name": "host", "value": host}],
        },
    }


def staging_values():
    return {
        "AZURE_SUBSCRIPTION_ID": "subscription",
        "AZURE_RESOURCE_GROUP": "resource-group",
        "COSMOSDB_ENDPOINT": "https://acct.documents.azure.com:443/",
        "FABRIC_CAPACITY_NAME": "capacity",
    }


def staging_substitutions(connection_id: str):
    return {
        "FABRIC_COSMOS_CONNECTION_ID": connection_id,
        "AZURE_SUBSCRIPTION_ID": "subscription",
        "RG_NAME": "resource-group",
        "COSMOSDB_ENDPOINT": "https://acct.documents.azure.com:443/",
        "FABRIC_CAPACITY_NAME": "capacity",
    }


def configure_discovery(monkeypatch, connections):
    monkeypatch.delenv("FABRIC_COSMOS_CONNECTION_ID", raising=False)
    monkeypatch.delenv("FABRIC_CONNECTION_ID", raising=False)
    monkeypatch.setattr(
        runner.shutil, "which", lambda executable, path=None: "azd" if executable == "azd" else None
    )
    monkeypatch.setattr(runner, "_azd_values", staging_values)
    monkeypatch.setattr(runner, "_fabric_access_token", lambda: ("secret-token", ""))
    monkeypatch.setattr(runner, "_fabric_connections", lambda _token: (connections, ""))


def test_credential_preflight_discovers_unique_host_match(monkeypatch):
    configure_discovery(
        monkeypatch,
        [fabric_connection("connection-1", "Another connection")],
    )

    ready, reason, substitutions = runner.credential_preflight(
        "azure-fabric-staging"
    )

    assert ready is True
    assert reason == ""
    assert substitutions == staging_substitutions("connection-1")


def test_fabric_connections_authenticates_without_persisting_token(monkeypatch):
    token = "secret-fabric-token"
    observed: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"value": []}'

    def fake_urlopen(request, timeout):
        observed["authorization"] = request.get_header("Authorization")
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)

    connections, reason = runner._fabric_connections(token)

    assert connections == []
    assert reason == ""
    assert observed == {
        "authorization": f"Bearer {token}",
        "timeout": 30,
    }


def test_credential_preflight_prefers_exact_name_among_host_matches(monkeypatch):
    configure_discovery(
        monkeypatch,
        [
            fabric_connection(
                "connection-default", runner.DEFAULT_FABRIC_CONNECTION_NAME
            ),
            fabric_connection(
                "connection-preferred", "Configured workshop workspace"
            ),
        ],
    )
    configured = staging_values()
    configured["FABRIC_WORKSPACE_NAME"] = "Configured workshop workspace"
    monkeypatch.setattr(runner, "_azd_values", lambda: configured)

    ready, reason, substitutions = runner.credential_preflight(
        "azure-fabric-staging"
    )

    assert ready is True
    assert reason == ""
    assert substitutions == staging_substitutions("connection-preferred")


def test_credential_preflight_blocks_ambiguous_host_matches(monkeypatch):
    configure_discovery(
        monkeypatch,
        [
            fabric_connection("connection-1", "First"),
            fabric_connection("connection-2", "Second"),
        ],
    )

    ready, reason, substitutions = runner.credential_preflight(
        "azure-fabric-staging"
    )

    assert ready is False
    assert "multiple Fabric Cosmos connections match host acct.documents.azure.com" == reason
    assert substitutions == {}
    assert "connection-1" not in reason


def test_credential_preflight_blocks_when_no_connection_matches_host(monkeypatch):
    configure_discovery(
        monkeypatch,
        [
            fabric_connection(
                "connection-other-host",
                "Other host",
                host="https://other.documents.azure.com:443/",
            )
        ],
    )

    ready, reason, substitutions = runner.credential_preflight(
        "azure-fabric-staging"
    )

    assert ready is False
    assert reason == "no Fabric Cosmos connection matches host acct.documents.azure.com"
    assert substitutions == {}


@pytest.mark.parametrize(
    ("token_result", "connections_result", "expected_reason"),
    [
        ((None, "Fabric authentication is unavailable"), None, "authentication"),
        (
            ("secret-token", ""),
            (None, "Fabric connections API is unavailable"),
            "API is unavailable",
        ),
    ],
)
def test_credential_preflight_blocks_auth_or_api_unavailable(
    monkeypatch, token_result, connections_result, expected_reason
):
    configure_discovery(monkeypatch, [])
    monkeypatch.setattr(runner, "_fabric_access_token", lambda: token_result)
    if connections_result is not None:
        monkeypatch.setattr(
            runner, "_fabric_connections", lambda _token: connections_result
        )

    ready, reason, substitutions = runner.credential_preflight(
        "azure-fabric-staging"
    )

    assert ready is False
    assert expected_reason in reason
    assert substitutions == {}
    assert "secret-token" not in reason


def test_prepare_argv_resolves_windows_command_shim_without_shell(
    tmp_path, monkeypatch
):
    npm_cmd = tmp_path / "npm.CMD"
    npm_cmd.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda executable, path=None: str(npm_cmd) if executable == "npm" else None,
    )

    argv = runner.prepare_argv(
        ("npm", "run", "build"), cwd=tmp_path, env={"PATH": "ignored"}
    )

    assert argv == [str(npm_cmd), "run", "build"]


def test_execute_command_uses_resolved_executable_and_preserves_declared_argv(
    tmp_path, monkeypatch
):
    npm_cmd = tmp_path / "npm.CMD"
    npm_cmd.write_text("@echo off\n", encoding="utf-8")
    spec = runner.cmd("frontend", ["npm", "run", "build"], owner="test")
    observed: dict[str, object] = {}

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda executable, path=None: str(npm_cmd) if executable == "npm" else None,
    )

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["shell"] = kwargs["shell"]
        return runner.subprocess.CompletedProcess(argv, 0, stdout=b"ok\n")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    record = runner.execute_command(spec, tmp_path / "evidence")

    assert observed == {
        "argv": [str(npm_cmd), "run", "build"],
        "shell": False,
    }
    assert record["status"] == "Verified"
    assert record["argv"] == ["npm", "run", "build"]
    assert record["executed_argv"] == [str(npm_cmd), "run", "build"]


def test_execute_command_redacts_substitution_but_runs_with_real_value(
    tmp_path, monkeypatch
):
    executable = tmp_path / "python.exe"
    executable.write_bytes(b"placeholder")
    connection_id = "real-sensitive-connection-id"
    spec = runner.cmd(
        "staging",
        ["python", "--connection-id", "${FABRIC_COSMOS_CONNECTION_ID}"],
        owner="test",
        credentials="azure-fabric-staging",
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "credential_preflight",
        lambda _requirement: (
            True,
            "",
            {"FABRIC_COSMOS_CONNECTION_ID": connection_id},
        ),
    )
    monkeypatch.setattr(
        runner.shutil, "which", lambda *_args, **_kwargs: str(executable)
    )

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        return runner.subprocess.CompletedProcess(
            argv, 0, stdout=f"used {connection_id}\n".encode()
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    evidence_dir = tmp_path / "evidence"
    record = runner.execute_command(spec, evidence_dir)

    assert observed["argv"] == [
        str(executable),
        "--connection-id",
        connection_id,
    ]
    assert record["argv"] == [
        "python",
        "--connection-id",
        "${FABRIC_COSMOS_CONNECTION_ID}",
    ]
    assert record["executed_argv"] == [
        str(executable),
        "--connection-id",
        "<redacted:FABRIC_COSMOS_CONNECTION_ID>",
    ]
    assert connection_id not in str(record)
    assert connection_id.encode() not in (evidence_dir / spec.evidence_path).read_bytes()


def test_execute_command_applies_environment_and_records_safe_evidence(
    tmp_path, monkeypatch
):
    npm_cmd = tmp_path / "npm.CMD"
    npm_cmd.write_text("@echo off\n", encoding="utf-8")
    browser = tmp_path / "msedge.exe"
    browser.write_bytes(b"browser")
    spec = runner.cmd(
        "frontend-tests",
        ["npm", "test"],
        owner="test",
        environment=(("CHROME_BIN", "available-chromium"),),
    )
    observed: dict[str, str] = {}

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setenv("CHROME_BIN", str(browser))
    monkeypatch.setenv("SECRET_TOKEN", "must-not-appear")
    monkeypatch.setattr(
        runner.shutil,
        "which",
        lambda executable, path=None: str(npm_cmd) if executable == "npm" else None,
    )

    def fake_run(argv, **kwargs):
        observed["chrome_bin"] = kwargs["env"]["CHROME_BIN"]
        return runner.subprocess.CompletedProcess(argv, 0, stdout=b"ok\n")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    record = runner.execute_command(spec, tmp_path / "evidence")

    assert observed["chrome_bin"] == str(browser.resolve())
    assert record["environment"] == {
        "variable_names": ["CHROME_BIN"],
        "selected_executables": {"CHROME_BIN": str(browser.resolve())},
    }
    assert "must-not-appear" not in str(record)


def test_missing_executable_is_structured_unverified_evidence(
    tmp_path, monkeypatch
):
    spec = runner.cmd("missing", ["definitely-not-installed"], owner="test")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.shutil, "which", lambda *_args, **_kwargs: None)

    record = runner.execute_command(spec, tmp_path / "evidence")

    assert record["status"] == "Unverified"
    assert record["exit_code"] is None
    assert record["executed_argv"] is None
    assert record["reason"] == "executable not found: definitely-not-installed"
    assert (tmp_path / "evidence" / spec.evidence_path).is_file()
    assert (tmp_path / "evidence" / spec.evidence_path).with_suffix(".json").is_file()


def test_launch_time_missing_executable_is_captured_without_traceback(
    tmp_path, monkeypatch
):
    executable = tmp_path / "tool.exe"
    executable.write_bytes(b"placeholder")
    spec = runner.cmd("race", ["tool"], owner="test")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.shutil, "which", lambda *_args, **_kwargs: str(executable))
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError(2, "The system cannot find the file specified")
        ),
    )

    record = runner.execute_command(spec, tmp_path / "evidence")

    assert record["status"] == "Unverified"
    assert record["exit_code"] is None
    assert "executable could not be started: tool" in record["reason"]
    assert record["executed_argv"] == [str(executable)]


def test_state_mutating_commands_are_serial_by_construction(tmp_path, monkeypatch):
    active = 0
    maximum_active = 0
    order: list[str] = []
    specs = tuple(
        runner.cmd(
            f"mutation-{index}",
            ["python", "-c", "pass"],
            owner="test",
            mutation="state-mutating",
        )
        for index in range(3)
    )

    def fake_execute(spec, evidence_dir):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        order.append(spec.id)
        active -= 1
        return {"id": spec.id, "status": "Verified", "reason": ""}

    monkeypatch.setattr(runner, "execute_command", fake_execute)
    code, _ = runner.run_specs(specs, tmp_path)

    assert code == 0
    assert maximum_active == 1
    assert order == ["mutation-0", "mutation-1", "mutation-2"]


def test_exact_controlled_fixture_plan_flags_are_accepted():
    args = parse(
        "--phase",
        "controlled-fixture",
        "--require-fixture-versions",
        "--require-exact-tenant-counts",
        "--require-exact-model-mixes",
        "--require-normalized-canonical-seeds",
        "--require-derived-clear",
        "--require-reset-count",
        "2",
        "--require-backup-restore",
        "--require-operational-trip-protection",
    )

    runner.validate_controlled_fixture_requirements(args, runner.build_parser())


def test_incomplete_controlled_fixture_contract_is_rejected():
    args = parse("--phase", "controlled-fixture", "--require-reset-count", "1")

    with pytest.raises(SystemExit):
        runner.validate_controlled_fixture_requirements(args, runner.build_parser())

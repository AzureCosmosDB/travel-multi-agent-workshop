#!/usr/bin/env python3
"""Validate azure.yaml with the installed stable azd contract."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[2]
COMPLETED = ROOT / "02_completed"
AZURE_YAML = COMPLETED / "azure.yaml"
DEFAULT_EVIDENCE = ROOT / ".local" / "integration-evidence" / "azd-project-config.json"
MCP_ALPHA_SCHEMA_URI = (
    "https://raw.githubusercontent.com/Azure/azure-dev/refs/heads/main/"
    "schemas/alpha/azure.yaml.json#"
)
MCP_ERROR_CATEGORIES = (
    "project-name-format",
    "docker-service-schema-recognition",
)
EXPECTED_SERVICES = {
    "api": "python",
    "frontend": "node",
    "mcp-server": "python",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_azd(executable: str) -> str:
    return shutil.which(executable) or executable


def run_azd(
    argv: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(
        argv,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def require_success(
    label: str, result: subprocess.CompletedProcess[str]
) -> subprocess.CompletedProcess[str]:
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise AssertionError(f"{label} rejected the project (exit {result.returncode}): {detail}")
    return result


def parse_version(output: str) -> dict[str, str]:
    match = re.search(
        r"(?im)^azd version (?P<version>\S+)"
        r"(?: \(commit (?P<commit>[0-9a-f]+)\))?"
        r"(?: \((?P<channel>[^)]+)\))?",
        output,
    )
    if not match:
        raise AssertionError("installed azd version output was not recognized")
    return {key: value for key, value in match.groupdict().items() if value}


def validate_show(payload: dict) -> dict:
    if payload.get("name") != "TravelAssistant":
        raise AssertionError("installed azd did not resolve project name TravelAssistant")
    services = payload.get("services")
    if not isinstance(services, dict):
        raise AssertionError("installed azd show did not return a services object")
    if set(services) != set(EXPECTED_SERVICES):
        raise AssertionError(
            f"installed azd resolved unexpected services: {sorted(services)}"
        )

    safe_services = {}
    expected_project = COMPLETED.resolve()
    for name, expected_language in EXPECTED_SERVICES.items():
        project = services[name].get("project", {})
        path = Path(project.get("path", "")).resolve()
        language = project.get("language")
        if path != expected_project:
            raise AssertionError(f"{name} resolved project path {path}, expected {expected_project}")
        if language != expected_language:
            raise AssertionError(
                f"{name} resolved language {language!r}, expected {expected_language!r}"
            )
        safe_services[name] = {
            "project_path": path.relative_to(ROOT).as_posix(),
            "language": language,
        }
    return {"name": payload["name"], "services": safe_services}


def service_block(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\s+.*?(?=^  [a-zA-Z][^:\n]*:|^hooks:)",
        text,
    )
    if not match:
        raise AssertionError(f"azure.yaml is missing service {name}")
    return match.group(0)


def validate_azure_yaml(text: str) -> dict:
    dockerfiles = {
        "api": "Dockerfile.api",
        "frontend": "Dockerfile.frontend",
        "mcp-server": "Dockerfile.mcp",
    }
    source = {}
    for name, dockerfile in dockerfiles.items():
        block = service_block(text, name)
        required = (
            f"path: ./{dockerfile}",
            "context: .",
            "remoteBuild: true",
        )
        missing = [item for item in required if item not in block]
        if missing:
            raise AssertionError(f"{name} source deployment invariants missing: {missing}")
        if re.search(r"(?m)^    image:\s*\S+", block):
            raise AssertionError(f"{name} contains a deployed-image source")
        source[name] = {
            "docker_path": f"./{dockerfile}",
            "context": ".",
            "remote_build": True,
        }

    prohibited = {
        "automatic-reset-hook": r"(?i)reset_optimization_state\.py",
        "deployed-image-overlay": r"(?i)deployed[-_ ]image[-_ ]overlay",
        "prebuilt-image-bypass": r"(?i)prebuilt[-_ ]image[-_ ]bypass",
        "acr-image-source": r"(?i)(?:FROM|COPY\s+--from=)\s+\S*\.azurecr\.io/",
        "image-import-hook": r"(?im)^\s*az\s+acr\s+import\b",
    }
    present = [name for name, pattern in prohibited.items() if re.search(pattern, text)]
    if present:
        raise AssertionError(f"prohibited deployment hooks or overlays found: {present}")
    return {
        "path": AZURE_YAML.relative_to(ROOT).as_posix(),
        "services": source,
        "automatic_reset_hook": False,
        "deployed_image_overlay": False,
    }


def environment_names(output: str) -> list[str]:
    names = []
    for line in output.splitlines():
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)=", line)
        if match:
            names.append(match.group(1))
    return sorted(set(names))


def collect_evidence(
    *,
    azd: str = "azd",
    schema_uri: str = MCP_ALPHA_SCHEMA_URI,
    error_categories: tuple[str, ...] = MCP_ERROR_CATEGORIES,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    azure_text: str | None = None,
) -> dict:
    executable = resolve_azd(azd)
    version_result = require_success(
        "azd version", run_azd([executable, "version"], runner=runner)
    )
    show_result = require_success(
        "azd show",
        run_azd(
            [executable, "show", "-C", str(COMPLETED), "--output", "json"],
            runner=runner,
        ),
    )
    env_result = require_success(
        "azd env get-values",
        run_azd(
            [executable, "env", "get-values", "-C", str(COMPLETED)],
            runner=runner,
        ),
    )
    try:
        show_payload = json.loads(show_result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"azd show returned invalid JSON: {exc}") from exc

    return {
        "schema_version": 1,
        "classification": "schema-version-mismatch-explained",
        "observed_utc": utc_now(),
        "mcp_validation": {
            "schema_uri": schema_uri,
            "error_categories": sorted(set(error_categories)),
        },
        "installed_azd": {
            "version": parse_version(version_result.stdout + "\n" + version_result.stderr),
            "show": validate_show(show_payload),
            "environment_parse": {
                "command": "azd env get-values -C 02_completed",
                "exit_code": env_result.returncode,
                "variable_names": environment_names(env_result.stdout),
                "values_recorded": False,
            },
        },
        "deployment_source": validate_azure_yaml(
            azure_text if azure_text is not None else AZURE_YAML.read_text(encoding="utf-8")
        ),
    }


def self_test() -> int:
    valid = """
services:
  mcp-server:
    docker:
      path: ./Dockerfile.mcp
      context: .
      remoteBuild: true
  api:
    docker:
      path: ./Dockerfile.api
      context: .
      remoteBuild: true
  frontend:
    docker:
      path: ./Dockerfile.frontend
      context: .
      remoteBuild: true
hooks:
  postdeploy:
    run: echo restart
"""
    validate_azure_yaml(valid)
    try:
        validate_azure_yaml(valid.replace("remoteBuild: true", "remoteBuild: false", 1))
    except AssertionError:
        pass
    else:
        raise AssertionError("remoteBuild regression fixture was not rejected")
    print("validate_azd_project_config self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--azd", default="azd")
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--mcp-schema-uri", default=MCP_ALPHA_SCHEMA_URI)
    parser.add_argument(
        "--mcp-error-category",
        action="append",
        dest="mcp_error_categories",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    evidence = collect_evidence(
        azd=args.azd,
        schema_uri=args.mcp_schema_uri,
        error_categories=tuple(args.mcp_error_categories or MCP_ERROR_CATEGORIES),
    )
    output = args.evidence.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("azd project config validation: PASS")
    print(f"classification: {evidence['classification']}")
    print(f"evidence: {output.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

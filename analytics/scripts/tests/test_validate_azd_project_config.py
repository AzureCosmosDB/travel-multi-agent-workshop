from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "validate_azd_project_config.py"
SPEC = importlib.util.spec_from_file_location("validate_azd_project_config", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


VALID_YAML = """
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


def completed(argv: list[str], stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(argv, returncode, stdout, "")


def successful_runner(argv, **_kwargs):
    if argv[1:] == ["version"]:
        return completed(argv, "azd version 1.27.0 (commit abc123) (stable)\n")
    if argv[1:3] == ["show", "-C"]:
        services = {
            name: {
                "project": {
                    "path": str(validator.COMPLETED),
                    "language": language,
                }
            }
            for name, language in validator.EXPECTED_SERVICES.items()
        }
        return completed(argv, json.dumps({"name": "TravelAssistant", "services": services}))
    if argv[1:3] == ["env", "get-values"]:
        return completed(argv, 'SECRET_TOKEN="do-not-record"\nSAFE_NAME="value"\n')
    raise AssertionError(f"unexpected command: {argv}")


def test_collect_evidence_classifies_alpha_schema_mismatch_without_secrets(monkeypatch):
    monkeypatch.setattr(validator, "resolve_azd", lambda executable: executable)

    evidence = validator.collect_evidence(
        runner=successful_runner,
        azure_text=VALID_YAML,
    )

    assert evidence["classification"] == "schema-version-mismatch-explained"
    assert evidence["mcp_validation"]["schema_uri"] == validator.MCP_ALPHA_SCHEMA_URI
    assert evidence["installed_azd"]["version"]["version"] == "1.27.0"
    assert evidence["installed_azd"]["version"]["channel"] == "stable"
    assert set(evidence["installed_azd"]["show"]["services"]) == {
        "api",
        "frontend",
        "mcp-server",
    }
    assert evidence["installed_azd"]["environment_parse"]["values_recorded"] is False
    assert "do-not-record" not in json.dumps(evidence)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace("remoteBuild: true", "remoteBuild: false", 1),
        lambda text: text + "\n# reset_optimization_state.py\n",
        lambda text: text.replace(
            "  api:\n",
            "  api:\n    image: example.azurecr.io/travel-api:latest\n",
        ),
    ],
)
def test_source_deployment_regressions_fail(mutation):
    with pytest.raises(AssertionError):
        validator.validate_azure_yaml(mutation(VALID_YAML))


def test_installed_azd_rejection_fails(monkeypatch):
    monkeypatch.setattr(validator, "resolve_azd", lambda executable: executable)

    def rejecting_runner(argv, **kwargs):
        if argv[1:] == ["version"]:
            return successful_runner(argv, **kwargs)
        return subprocess.CompletedProcess(argv, 1, "", "invalid azure.yaml")

    with pytest.raises(AssertionError, match="rejected the project"):
        validator.collect_evidence(runner=rejecting_runner, azure_text=VALID_YAML)


def test_unexpected_service_language_fails(monkeypatch):
    monkeypatch.setattr(validator, "resolve_azd", lambda executable: executable)

    def wrong_language_runner(argv, **kwargs):
        result = successful_runner(argv, **kwargs)
        if argv[1:3] == ["show", "-C"]:
            payload = json.loads(result.stdout)
            payload["services"]["frontend"]["project"]["language"] = "typescript"
            return completed(argv, json.dumps(payload))
        return result

    with pytest.raises(AssertionError, match="resolved language"):
        validator.collect_evidence(runner=wrong_language_runner, azure_text=VALID_YAML)

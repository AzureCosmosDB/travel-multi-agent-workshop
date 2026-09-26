from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from fabric_assets import (  # noqa: E402
    demo_tenant_pipeline_definition,
    validate_demo_tenant_pipeline_definition,
)


def test_pipeline_preserves_analytics_then_marvel_ordering() -> None:
    definition = demo_tenant_pipeline_definition("workspace", "notebook")
    validate_demo_tenant_pipeline_definition(definition, "workspace", "notebook")
    activities = definition["properties"]["activities"]
    assert [activity["name"] for activity in activities] == [
        "Refresh Analytics",
        "Refresh Marvel",
    ]
    assert activities[1]["dependsOn"] == [
        {
            "activity": "Refresh Analytics",
            "dependencyConditions": ["Succeeded"],
        }
    ]


def test_pipeline_validator_rejects_parallel_marvel() -> None:
    definition = demo_tenant_pipeline_definition("workspace", "notebook")
    definition["properties"]["activities"][1]["dependsOn"] = []
    with pytest.raises(ValueError, match="depend"):
        validate_demo_tenant_pipeline_definition(definition, "workspace", "notebook")


def test_powershell_is_only_an_argument_forwarder() -> None:
    source = (HERE / "Provision-Fabric.ps1").read_text(encoding="utf-8")
    assert "ValueFromRemainingArguments" in source
    assert "& python $provisioner @Arguments" in source
    assert "exit $LASTEXITCODE" in source
    for forbidden in ("Read-Host", "Save-State", "Get-AzContext", "azd env", "function "):
        assert forbidden not in source


def test_staging_no_cloud_writes_blocking_unverified_evidence() -> None:
    work = ROOT / ".local" / "fabric-tests" / "staging"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    evidence = work / "evidence.json"
    result = subprocess.run(
        [
            sys.executable,
            str(HERE / "provision_fabric.py"),
            "--environment",
            "staging",
            "--solution",
            "--verify-semantic-model",
            "--verify-report",
            "--no-cloud",
            "--evidence-output",
            str(evidence),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        assert result.returncode != 0
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        assert payload["status"] == "Unverified"
        assert payload["environment"] == "staging"
        assert set(payload["ids"]) == {
            "workspace",
            "mirror",
            "notebook",
            "pipeline",
            "udf",
            "semantic_model",
            "report",
        }
        assert all(payload["source_definition_hashes"].values())
        assert payload["query_evidence"] == {
            "semantic_model": None,
            "report": None,
        }
        assert "disabled" in payload["reason"]
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_static_validator_and_delivered_evaluator_parity() -> None:
    for script in (
        "validate_fabric_assets.py",
        "validate_controlled_demo4_source.py",
    ):
        result = subprocess.run(
            [sys.executable, str(HERE / script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

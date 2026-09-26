from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "verify_integration_accounting.py"
SPEC = importlib.util.spec_from_file_location("verify_integration_accounting", SCRIPT)
assert SPEC and SPEC.loader
accounting = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(accounting)


def baseline_fixture():
    return {
        "head": "head",
        "branch": "main",
        "upstream_ref": "origin/main",
        "upstream_sha": "upstream",
        "index_tree": "index",
        "staged_paths": [],
        "status_entries": [
            {"path": "preserved.txt", "xy": " M", "original_path": None}
        ],
        "dirty_manifest": [
            {
                "path": "preserved.txt",
                "classification": "unrelated",
                "task_coverage": "preserve",
                "planned_output": False,
                "present_at_capture": True,
                "expected_final_disposition": "present-dirty",
                "expected_porcelain_xy": " M",
                "expected_original_path": None,
                "preservation_fingerprint": {
                    "kind": "file",
                    "bytes": 4,
                    "sha256": "hash",
                },
            },
            {
                "path": "excluded.txt",
                "classification": "temporary/excluded",
                "task_coverage": "remove",
                "planned_output": False,
                "present_at_capture": False,
                "expected_final_disposition": "absent",
                "expected_porcelain_xy": None,
                "expected_original_path": None,
                "preservation_fingerprint": None,
            },
        ],
        "publication": {"exit_code": 0, "current_prs": []},
    }


def compare(baseline, **overrides):
    values = {
        "head": "head",
        "branch": "main",
        "upstream_ref": "origin/main",
        "upstream_sha": "upstream",
        "index_tree": "index",
        "staged_paths": [],
        "status_records": [
            {"path": "preserved.txt", "xy": " M", "original_path": None}
        ],
        "publication": {"exit_code": 0, "current_prs": []},
        "require_head": True,
        "require_upstream": True,
        "require_index": True,
        "require_coverage": True,
        "require_no_pr": True,
        "fingerprints": {
            "preserved.txt": {
                "kind": "file",
                "bytes": 4,
                "sha256": "hash",
            }
        },
    }
    values.update(overrides)
    original_paths = set(accounting.PLANNED_OUTPUT_PATHS)
    original_dispositions = dict(accounting.EXPECTED_FINAL_DISPOSITIONS)
    try:
        accounting.PLANNED_OUTPUT_PATHS.clear()
        accounting.EXPECTED_FINAL_DISPOSITIONS.clear()
        return accounting.compare(baseline, **values)
    finally:
        accounting.PLANNED_OUTPUT_PATHS.update(original_paths)
        accounting.EXPECTED_FINAL_DISPOSITIONS.update(original_dispositions)


def test_exact_coverage_and_preservation_pass():
    assert compare(baseline_fixture()) == []


def test_unexpected_addition_and_unexplained_removal_fail():
    errors = compare(
        baseline_fixture(),
        status_records=[
            {"path": "unexpected.txt", "xy": "??", "original_path": None}
        ],
    )

    assert any("unexpected dirty additions" in error for error in errors)
    assert any("unexplained dirty removals" in error for error in errors)


def test_porcelain_staged_branch_and_fingerprint_drift_fail():
    errors = compare(
        baseline_fixture(),
        branch="feature",
        staged_paths=["preserved.txt"],
        status_records=[
            {"path": "preserved.txt", "xy": "M ", "original_path": None}
        ],
        fingerprints={
            "preserved.txt": {
                "kind": "file",
                "bytes": 5,
                "sha256": "changed",
            }
        },
    )

    assert any("branch changed" in error for error in errors)
    assert any("staged paths changed" in error for error in errors)
    assert any("porcelain state changed" in error for error in errors)
    assert any("preserved unrelated path changed" in error for error in errors)


def test_legacy_baseline_derives_explicit_disposition(monkeypatch):
    monkeypatch.setattr(accounting, "is_tracked", lambda _path: False)
    legacy = {
        "status_entries": [],
        "dirty_manifest": [
            {
                "path": "new-proof.py",
                "classification": "validator/test",
                "task_coverage": "proof",
                "planned_output": True,
                "present_at_capture": False,
            }
        ],
    }
    original_paths = set(accounting.PLANNED_OUTPUT_PATHS)
    original_dispositions = dict(accounting.EXPECTED_FINAL_DISPOSITIONS)
    try:
        accounting.PLANNED_OUTPUT_PATHS.clear()
        accounting.EXPECTED_FINAL_DISPOSITIONS.clear()
        normalized = accounting.normalize_manifest(legacy)
    finally:
        accounting.PLANNED_OUTPUT_PATHS.update(original_paths)
        accounting.EXPECTED_FINAL_DISPOSITIONS.update(original_dispositions)

    assert normalized[0]["expected_final_disposition"] == "present-dirty"
    assert normalized[0]["expected_porcelain_xy"] == "??"


def test_compatibility_entries_have_explicit_coverage_and_disposition(monkeypatch):
    monkeypatch.setattr(
        accounting,
        "is_tracked",
        lambda path: path == "02_completed/frontend/README.md",
    )
    baseline = {"status_entries": [], "dirty_manifest": []}
    original_paths = set(accounting.PLANNED_OUTPUT_PATHS)
    try:
        accounting.PLANNED_OUTPUT_PATHS.clear()
        accounting.PLANNED_OUTPUT_PATHS.update(
            accounting.COMPATIBILITY_MANIFEST_ENTRIES
        )
        normalized = {
            item["path"]: item for item in accounting.normalize_manifest(baseline)
        }
    finally:
        accounting.PLANNED_OUTPUT_PATHS.clear()
        accounting.PLANNED_OUTPUT_PATHS.update(original_paths)

    checklist = normalized["analytics/checklist.json"]
    assert checklist["classification"] == "docs"
    assert checklist["task_coverage"] == "F3-presenter-docs-traceability"
    assert checklist["expected_final_disposition"] == "present-dirty"
    assert checklist["expected_porcelain_xy"] == "??"

    readme = normalized["02_completed/frontend/README.md"]
    assert readme["classification"] == "docs"
    assert readme["task_coverage"] == "G2-authored-link-correction"
    assert readme["expected_final_disposition"] == "present-dirty"
    assert readme["expected_porcelain_xy"] == " M"

    controlled_docs = normalized[
        "analytics/scripts/tests/test_validate_controlled_demo4_docs.py"
    ]
    assert controlled_docs["classification"] == "validator/test"
    assert controlled_docs["task_coverage"] == "F3/G2-regression"
    assert controlled_docs["expected_final_disposition"] == "present-dirty"
    assert controlled_docs["expected_porcelain_xy"] == "??"

    markdown_links = normalized[
        "analytics/scripts/tests/test_validate_markdown_links.py"
    ]
    assert markdown_links["classification"] == "validator/test"
    assert markdown_links["task_coverage"] == "F1/G2-regression"
    assert markdown_links["expected_final_disposition"] == "present-dirty"
    assert markdown_links["expected_porcelain_xy"] == "??"

    for path in ("analytics/qa_report_f.txt", "validate-brief-f.ps1"):
        evidence = normalized[path]
        assert evidence["classification"] == "temporary/excluded"
        assert evidence["task_coverage"] == "G3-relocate-brief-f-qa-evidence"
        assert evidence["expected_final_disposition"] == "absent"
        assert evidence["expected_porcelain_xy"] is None


def test_design_brief_g_outputs_are_in_exact_planned_accounting():
    paths = {
        "analytics/scripts/validate_azd_project_config.py",
        "analytics/scripts/tests/test_validate_azd_project_config.py",
    }
    assert paths <= accounting.PLANNED_OUTPUT_PATHS
    for path in paths:
        entry = accounting.COMPATIBILITY_MANIFEST_ENTRIES[path]
        assert entry == {
            "classification": "validator/test",
            "task_coverage": "A4/G2-azd-schema-reconciliation",
            "expected_final_disposition": "present-dirty",
        }

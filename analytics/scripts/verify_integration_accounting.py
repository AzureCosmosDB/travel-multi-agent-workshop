#!/usr/bin/env python3
"""Compare final repository/publication state with a preservation-aware baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_integration_baseline import (  # noqa: E402
    COMPATIBILITY_MANIFEST_ENTRIES,
    EXPECTED_FINAL_DISPOSITIONS,
    PLANNED_OUTPUT_PATHS,
    is_tracked,
    parse_porcelain_v1_z,
    path_fingerprint,
    publication_snapshot,
)


EXCLUDED_FINAL_PATHS = {
    "analytics/docs/presenter-handoff-talk-track.md",
    "01_exercises/frontend/tsconfig.parity-spec.json",
}


def git_text(args: list[str]) -> str:
    return subprocess.check_output(args, cwd=ROOT).decode().strip()


def derive_disposition(item: dict[str, Any]) -> str:
    if item.get("classification") == "temporary/excluded":
        return "absent"
    if item.get("planned_output") or item.get("present_at_capture"):
        return "present-dirty"
    # Legacy baselines may list bootstrap-only paths already intentionally removed.
    return "absent"


def normalize_manifest(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    baseline_records = {
        item["path"]: item for item in baseline.get("status_entries", [])
    }
    normalized: list[dict[str, Any]] = []
    known: set[str] = set()
    for source in baseline.get("dirty_manifest", []):
        item = dict(source)
        path = item["path"]
        known.add(path)
        disposition = EXPECTED_FINAL_DISPOSITIONS.get(
            path, item.get("expected_final_disposition") or derive_disposition(item)
        )
        record = baseline_records.get(path)
        item["expected_final_disposition"] = disposition
        if "expected_porcelain_xy" not in item or disposition == "absent":
            item["expected_porcelain_xy"] = (
                record.get("xy")
                if record
                else " M"
                if disposition == "present-dirty"
                and item.get("planned_output")
                and is_tracked(path)
                else "??"
                if disposition == "present-dirty" and item.get("planned_output")
                else None
            )
        if "expected_original_path" not in item:
            item["expected_original_path"] = (
                record.get("original_path") if record else None
            )
        item.setdefault("preservation_fingerprint", None)
        normalized.append(item)
    # Compatibility for schema <=2: durable proof outputs added after baseline capture
    # are explicit planned additions, never arbitrary uncovered files.
    for path in sorted(PLANNED_OUTPUT_PATHS - known):
        compatibility = COMPATIBILITY_MANIFEST_ENTRIES.get(path, {})
        normalized.append(
            {
                "path": path,
                "classification": compatibility.get(
                    "classification", "validator/test"
                ),
                "task_coverage": compatibility.get(
                    "task_coverage", "G0-proof-tools"
                ),
                "planned_output": True,
                "tracked_at_capture": is_tracked(path),
                "present_in_bootstrap": False,
                "present_at_capture": False,
                "expected_final_disposition": EXPECTED_FINAL_DISPOSITIONS[path],
                "expected_porcelain_xy": (
                    " M"
                    if EXPECTED_FINAL_DISPOSITIONS[path] == "present-dirty"
                    and is_tracked(path)
                    else "??"
                    if EXPECTED_FINAL_DISPOSITIONS[path] == "present-dirty"
                    else None
                ),
                "expected_original_path": None,
                "preservation_fingerprint": None,
                "derived_for_legacy_baseline": True,
            }
        )
    return normalized


def compare(
    baseline: dict[str, Any],
    *,
    head: str,
    branch: str,
    upstream_ref: str,
    upstream_sha: str,
    index_tree: str,
    staged_paths: list[str],
    status_records: list[dict[str, Any]],
    publication: dict[str, Any],
    require_head: bool,
    require_upstream: bool,
    require_index: bool,
    require_coverage: bool,
    require_no_pr: bool,
    fingerprints: dict[str, dict[str, Any] | None] | None = None,
) -> list[str]:
    errors: list[str] = []
    if require_head and head != baseline["head"]:
        errors.append(f"HEAD changed: {baseline['head']} -> {head}")
    if require_head and branch != baseline.get("branch", branch):
        errors.append(f"branch changed: {baseline.get('branch')} -> {branch}")
    if require_upstream and (
        upstream_ref != baseline["upstream_ref"]
        or upstream_sha != baseline["upstream_sha"]
    ):
        errors.append("upstream ref/SHA changed")
    if require_index and index_tree != baseline["index_tree"]:
        errors.append("index tree changed")
    if require_index and sorted(staged_paths) != sorted(baseline.get("staged_paths", [])):
        errors.append(
            "staged paths changed: "
            f"{sorted(baseline.get('staged_paths', []))} -> {sorted(staged_paths)}"
        )

    manifest = normalize_manifest(baseline)
    if len({item["path"] for item in manifest}) != len(manifest):
        errors.append("baseline manifest contains duplicate paths")
    if any(
        not item.get("classification")
        or not item.get("task_coverage")
        or item.get("expected_final_disposition") not in {"present-dirty", "absent"}
        for item in manifest
    ):
        errors.append("baseline manifest has incomplete coverage or disposition")

    final = {item["path"]: item for item in status_records}
    expected_present = {
        item["path"]
        for item in manifest
        if item["expected_final_disposition"] == "present-dirty"
    }
    expected_absent = {
        item["path"]
        for item in manifest
        if item["expected_final_disposition"] == "absent"
    }
    if require_coverage:
        unexpected = sorted(set(final) - expected_present)
        removals = sorted(expected_present - set(final))
        unexplained_present = sorted(expected_absent & set(final))
        if unexpected:
            errors.append(f"unexpected dirty additions: {unexpected}")
        if removals:
            errors.append(f"unexplained dirty removals: {removals}")
        if unexplained_present:
            errors.append(f"paths expected absent remain dirty: {unexplained_present}")
        for item in manifest:
            path = item["path"]
            if path not in final:
                continue
            expected_xy = item.get("expected_porcelain_xy")
            expected_original = item.get("expected_original_path")
            if expected_xy is not None and final[path]["xy"] != expected_xy:
                errors.append(
                    f"porcelain state changed for {path}: "
                    f"{expected_xy!r} -> {final[path]['xy']!r}"
                )
            if final[path].get("original_path") != expected_original:
                errors.append(f"rename/copy source changed for {path}")

    leaked = sorted(
        path
        for path in final
        if path in EXCLUDED_FINAL_PATHS
        or path.startswith("openspec/")
        or path.endswith(".parity.spec.ts")
    )
    if leaked:
        errors.append(f"excluded paths remain: {leaked}")

    fingerprints = fingerprints or {}
    for item in manifest:
        expected = item.get("preservation_fingerprint")
        if expected is None:
            continue
        actual = fingerprints.get(item["path"])
        if actual != expected:
            errors.append(f"preserved unrelated path changed: {item['path']}")

    if require_no_pr:
        before = baseline.get("publication", {})
        if publication.get("exit_code") != before.get("exit_code"):
            errors.append("publication check availability changed")
        if publication.get("current_prs") != before.get("current_prs"):
            errors.append("current-branch PR publication state changed")
    return errors


def self_test() -> int:
    baseline = {
        "head": "h",
        "branch": "main",
        "upstream_ref": "origin/main",
        "upstream_sha": "u",
        "index_tree": "i",
        "staged_paths": [],
        "status_entries": [
            {
                "path": "kept",
                "xy": " M",
                "original_path": None,
            }
        ],
        "dirty_manifest": [
            {
                "path": "kept",
                "classification": "unrelated",
                "task_coverage": "preserve",
                "present_at_capture": True,
                "planned_output": False,
                "expected_final_disposition": "present-dirty",
                "expected_porcelain_xy": " M",
                "expected_original_path": None,
                "preservation_fingerprint": {
                    "kind": "file",
                    "bytes": 1,
                    "sha256": "x",
                },
            },
            {
                "path": "removed",
                "classification": "temporary/excluded",
                "task_coverage": "delete",
                "present_at_capture": False,
                "planned_output": False,
                "expected_final_disposition": "absent",
                "expected_porcelain_xy": None,
                "expected_original_path": None,
            },
        ],
        "publication": {"exit_code": 0, "current_prs": []},
    }
    common = {
        "head": "h",
        "branch": "main",
        "upstream_ref": "origin/main",
        "upstream_sha": "u",
        "index_tree": "i",
        "staged_paths": [],
        "status_records": [{"path": "kept", "xy": " M", "original_path": None}],
        "publication": {"exit_code": 0, "current_prs": []},
        "require_head": True,
        "require_upstream": True,
        "require_index": True,
        "require_coverage": True,
        "require_no_pr": True,
        "fingerprints": {
            "kept": {"kind": "file", "bytes": 1, "sha256": "x"}
        },
    }
    # Limit compatibility-added planned paths for the isolated fixture.
    original = set(PLANNED_OUTPUT_PATHS)
    try:
        PLANNED_OUTPUT_PATHS.clear()
        assert not compare(baseline, **common)
        broken = dict(common)
        broken["status_records"] = [
            {"path": "unexpected", "xy": "??", "original_path": None}
        ]
        assert any("unexpected dirty additions" in item for item in compare(baseline, **broken))
        broken = dict(common)
        broken["fingerprints"] = {
            "kept": {"kind": "file", "bytes": 2, "sha256": "y"}
        }
        assert any("preserved unrelated" in item for item in compare(baseline, **broken))
    finally:
        PLANNED_OUTPUT_PATHS.update(original)
    legacy = {
        "dirty_manifest": [
            {
                "path": "legacy",
                "classification": "validator/test",
                "task_coverage": "task",
                "planned_output": True,
                "present_at_capture": False,
            }
        ],
        "status_entries": [],
    }
    original = set(PLANNED_OUTPUT_PATHS)
    try:
        PLANNED_OUTPUT_PATHS.clear()
        normalized = normalize_manifest(legacy)
        assert normalized[0]["expected_final_disposition"] == "present-dirty"
        assert normalized[0]["expected_porcelain_xy"] == "??"
    finally:
        PLANNED_OUTPUT_PATHS.update(original)
    compatibility = {
        "dirty_manifest": [],
        "status_entries": [],
    }
    original = set(PLANNED_OUTPUT_PATHS)
    try:
        PLANNED_OUTPUT_PATHS.clear()
        PLANNED_OUTPUT_PATHS.update(COMPATIBILITY_MANIFEST_ENTRIES)
        normalized = {
            item["path"]: item for item in normalize_manifest(compatibility)
        }
        assert normalized["analytics/checklist.json"]["classification"] == "docs"
        assert (
            normalized["analytics/checklist.json"]["task_coverage"]
            == "F3-presenter-docs-traceability"
        )
        assert (
            normalized["analytics/checklist.json"]["expected_final_disposition"]
            == "present-dirty"
        )
        assert normalized["02_completed/frontend/README.md"]["classification"] == "docs"
        assert (
            normalized["02_completed/frontend/README.md"]["task_coverage"]
            == "G2-authored-link-correction"
        )
        assert (
            normalized["02_completed/frontend/README.md"][
                "expected_final_disposition"
            ]
            == "present-dirty"
        )
        assert (
            normalized[
                "analytics/scripts/tests/test_validate_controlled_demo4_docs.py"
            ]["task_coverage"]
            == "F3/G2-regression"
        )
        assert (
            normalized["analytics/scripts/tests/test_validate_markdown_links.py"][
                "task_coverage"
            ]
            == "F1/G2-regression"
        )
        assert (
            normalized["analytics/qa_report_f.txt"]["expected_final_disposition"]
            == "absent"
        )
        assert (
            normalized["validate-brief-f.ps1"]["expected_final_disposition"]
            == "absent"
        )
    finally:
        PLANNED_OUTPUT_PATHS.clear()
        PLANNED_OUTPUT_PATHS.update(original)
    print("verify_integration_accounting self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline")
    parser.add_argument("--require-unchanged-head", action="store_true")
    parser.add_argument("--require-unchanged-upstream", action="store_true")
    parser.add_argument("--require-unchanged-index", action="store_true")
    parser.add_argument("--require-complete-dirty-coverage", action="store_true")
    parser.add_argument("--require-no-pr", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.baseline:
        parser.error("--baseline is required unless --self-test is used")
    baseline = json.loads((ROOT / args.baseline).read_text(encoding="utf-8"))
    upstream_ref = git_text(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
    )
    payload = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=ROOT,
    )
    status_records = parse_porcelain_v1_z(payload)
    staged_paths = [
        value.replace("\\", "/")
        for value in subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "-z"], cwd=ROOT
        )
        .decode("utf-8", "surrogateescape")
        .split("\0")
        if value
    ]
    manifest = normalize_manifest(baseline)
    fingerprints = {
        item["path"]: path_fingerprint(item["path"])
        for item in manifest
        if item.get("preservation_fingerprint") is not None
    }
    errors = compare(
        baseline,
        head=git_text(["git", "rev-parse", "HEAD"]),
        branch=git_text(["git", "branch", "--show-current"]),
        upstream_ref=upstream_ref,
        upstream_sha=git_text(["git", "rev-parse", upstream_ref]),
        index_tree=git_text(["git", "write-tree"]),
        staged_paths=staged_paths,
        status_records=status_records,
        publication=publication_snapshot(),
        require_head=args.require_unchanged_head,
        require_upstream=args.require_unchanged_upstream,
        require_index=args.require_unchanged_index,
        require_coverage=args.require_complete_dirty_coverage,
        require_no_pr=args.require_no_pr,
        fingerprints=fingerprints,
    )
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(
        "integration accounting: PASS "
        f"(HEAD={baseline['head']} index={baseline['index_tree']} "
        f"exact_dirty_paths={len(status_records)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

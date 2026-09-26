#!/usr/bin/env python3
"""Capture a NUL-safe integration baseline without recording file contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_NAME = "brief-a-bootstrap-baseline.json"
COMPATIBILITY_MANIFEST_ENTRIES = {
    "02_completed/frontend/README.md": {
        "classification": "docs",
        "task_coverage": "G2-authored-link-correction",
        "expected_final_disposition": "present-dirty",
    },
    "analytics/checklist.json": {
        "classification": "docs",
        "task_coverage": "F3-presenter-docs-traceability",
        "expected_final_disposition": "present-dirty",
    },
    "analytics/qa_report_f.txt": {
        "classification": "temporary/excluded",
        "task_coverage": "G3-relocate-brief-f-qa-evidence",
        "expected_final_disposition": "absent",
    },
    "validate-brief-f.ps1": {
        "classification": "temporary/excluded",
        "task_coverage": "G3-relocate-brief-f-qa-evidence",
        "expected_final_disposition": "absent",
    },
    "analytics/scripts/tests/test_validate_controlled_demo4_docs.py": {
        "classification": "validator/test",
        "task_coverage": "F3/G2-regression",
        "expected_final_disposition": "present-dirty",
    },
    "analytics/scripts/tests/test_validate_markdown_links.py": {
        "classification": "validator/test",
        "task_coverage": "F1/G2-regression",
        "expected_final_disposition": "present-dirty",
    },
    "analytics/scripts/validate_azd_project_config.py": {
        "classification": "validator/test",
        "task_coverage": "A4/G2-azd-schema-reconciliation",
        "expected_final_disposition": "present-dirty",
    },
    "analytics/scripts/tests/test_validate_azd_project_config.py": {
        "classification": "validator/test",
        "task_coverage": "A4/G2-azd-schema-reconciliation",
        "expected_final_disposition": "present-dirty",
    },
}
PLANNED_DIRTY_PATHS = {
    "analytics/scripts/capture_integration_baseline.py",
    "analytics/scripts/validate_azd_project_config.py",
    "analytics/scripts/validate_deployment_source_builds.py",
    "analytics/scripts/run_integration_verification.py",
    "analytics/scripts/verify_integration_accounting.py",
    "analytics/scripts/validate_changed_symbol_blast_radius.py",
    "analytics/scripts/tests/test_run_integration_verification.py",
    "analytics/scripts/tests/test_integration_accounting.py",
    "analytics/scripts/tests/test_validate_azd_project_config.py",
    "analytics/scripts/tests/test_validate_changed_symbol_blast_radius.py",
    "analytics/config/changed-symbol-blast-radius.json",
    "01_exercises/frontend/src/app/services/travel-api.service.spec.ts",
    "01_exercises/frontend/src/app/app.component.spec.ts",
    "01_exercises/frontend/src/app/components/explore/explore.component.spec.ts",
    "01_exercises/frontend/src/app/components/home/home.component.spec.ts",
    "01_exercises/frontend/src/app/components/login/login.component.spec.ts",
    "01_exercises/frontend/src/app/components/profile/profile.component.spec.ts",
    "01_exercises/frontend/src/app/components/shared/message/message.component.spec.ts",
    "01_exercises/frontend/src/app/components/shared/place-card/place-card.component.spec.ts",
    "02_completed/frontend/src/app/app.component.spec.ts",
    "02_completed/frontend/src/app/components/login/login.component.spec.ts",
    "02_completed/frontend/src/app/components/shared/message/message.component.spec.ts",
    "02_completed/frontend/src/app/components/shared/place-card/place-card.component.spec.ts",
    "01_exercises/workshop/Module-02.md",
    "01_exercises/workshop/Module-05.md",
    "02_completed/python/src/app/services/lifecycle_coordinator.py",
    "02_completed/python/tests/conftest.py",
    "02_completed/python/tests/test_controlled_demo4_http.py",
    "02_completed/python/tests/test_lifecycle_coordinator.py",
    "02_completed/python/tests/test_traveller_context.py",
    "analytics/config/cross-tree-parity-allowlist.json",
    "analytics/config/static-portal-freeze.json",
    "analytics/fabric/tests/test_fabric_contracts.py",
    "analytics/fabric/tests/test_generation_contract.py",
    "analytics/powerbi/controlled_demo4_intended_diff.json",
    "analytics/powerbi/controlled_demo4_visual_fixture.json",
    "analytics/scripts/validate_cross_tree_parity.py",
    "analytics/scripts/validate_marvel_only_workshop.py",
    "analytics/scripts/validate_static_portal_freeze.py",
    "analytics/scripts/validate_word_flow_traceability.py",
    "analytics/scripts/validate_workshop_contract_docs.py",
    *(
        path
        for path, entry in COMPATIBILITY_MANIFEST_ENTRIES.items()
        if entry["expected_final_disposition"] == "present-dirty"
    ),
}
EXPECTED_CLEAN_PATHS = {
    ".gitignore",
    "01_exercises/frontend/src/app/components/home/home.component.contract.spec.ts",
    "01_exercises/frontend/src/app/components/explore/explore.component.contract.spec.ts",
    "01_exercises/frontend/src/app/components/profile/profile.component.contract.spec.ts",
    "02_completed/frontend/angular.json",
    "02_completed/frontend/package.json",
    "02_completed/frontend/tsconfig.preferences-spec.json",
    "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition/pages/1cb8e89d583fa5784a65/visuals/fd02aa117627df1fb997/visual.json",
    "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition/pages/1ec0950511c6f38d7609/visuals/829a38b84371fc26b415/visual.json",
    "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition/pages/b219be7fdc6775327c11/visuals/968fc40d0294c8711c9a/visual.json",
    "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition/pages/cec777f691a5019c61b3/visuals/2204f9e3fd2d877fe926/visual.json",
    "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition/pages/db6a6a2ea325e58c2d72/visuals/3a4d11281503eb3fbe4b/visual.json",
    "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition/pages/fe153ccbd76573b28722/visuals/3faa4194fb661055aceb/visual.json",
    *(
        path
        for path, entry in COMPATIBILITY_MANIFEST_ENTRIES.items()
        if entry["expected_final_disposition"] == "absent"
    ),
}
EXPECTED_FINAL_DISPOSITIONS = {
    **{path: "present-dirty" for path in PLANNED_DIRTY_PATHS},
    **{path: "absent" for path in EXPECTED_CLEAN_PATHS},
}
PLANNED_OUTPUT_PATHS = set(EXPECTED_FINAL_DISPOSITIONS)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run(args: list[str], *, check: bool = True) -> bytes:
    result = subprocess.run(
        args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(
            f"{args!r} failed ({result.returncode}): "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result.stdout


def text(args: list[str], *, check: bool = True) -> str:
    return run(args, check=check).decode("utf-8", "surrogateescape").strip()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def path_fingerprint(path: str) -> dict[str, Any] | None:
    candidate = ROOT / path
    if candidate.is_symlink():
        target = os.readlink(candidate)
        return {
            "kind": "symlink",
            "bytes": len(target.encode("utf-8", "surrogateescape")),
            "sha256": sha256_bytes(target.encode("utf-8", "surrogateescape")),
        }
    if candidate.is_file():
        payload = candidate.read_bytes()
        return {
            "kind": "file",
            "bytes": len(payload),
            "sha256": sha256_bytes(payload),
        }
    return None


def is_tracked(path: str) -> bool:
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


def parse_porcelain_v1_z(payload: bytes) -> list[dict[str, Any]]:
    fields = payload.split(b"\0")
    records: list[dict[str, Any]] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        decoded = field.decode("utf-8", "surrogateescape")
        if len(decoded) < 3 or decoded[2] != " ":
            raise ValueError(f"invalid porcelain record: {decoded!r}")
        xy = decoded[:2]
        path = normalize_path(decoded[3:])
        original_path = None
        if "R" in xy or "C" in xy:
            if index >= len(fields) or not fields[index]:
                raise ValueError(f"missing rename/copy source for {path!r}")
            original_path = normalize_path(
                fields[index].decode("utf-8", "surrogateescape")
            )
            index += 1
        records.append(
            {
                "xy": xy,
                "path": path,
                "original_path": original_path,
                "staged": xy[0] not in (" ", "?"),
                "unstaged": xy[1] not in (" ", "?"),
                "untracked": xy == "??",
            }
        )
    return records


def bootstrap_paths(document: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for entry in document.get("status_entries", []):
        if not isinstance(entry, str):
            continue
        entry = entry.rstrip("\r\n")
        if len(entry) < 4 or entry[:2].strip() == "":
            continue
        raw_path = entry[3:]
        if " -> " in raw_path:
            raw_path = raw_path.rsplit(" -> ", 1)[1]
        path = normalize_path(raw_path)
        if path:
            paths.append(path)
    return paths


def discover_bootstrap(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if not candidate.is_file():
            raise FileNotFoundError(candidate)
        return candidate
    env_path = os.environ.get("INTEGRATION_BOOTSTRAP_BASELINE")
    if env_path:
        return discover_bootstrap(env_path)
    candidates = sorted(
        (Path.home() / ".copilot" / "session-state").glob(
            f"*/files/{BOOTSTRAP_NAME}"
        ),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    repository = str(ROOT.resolve()).casefold()
    head = text(["git", "rev-parse", "HEAD"])
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            str(Path(data.get("repository", "")).resolve()).casefold() == repository
            and data.get("head") == head
        ):
            return candidate
    raise FileNotFoundError(
        f"could not discover {BOOTSTRAP_NAME}; pass --bootstrap"
    )


def classify(path: str) -> tuple[str, str]:
    lower = path.casefold()
    name = Path(path).name.casefold()
    compatibility = COMPATIBILITY_MANIFEST_ENTRIES.get(path)
    if compatibility:
        return compatibility["classification"], compatibility["task_coverage"]
    if lower.startswith(".local/"):
        return "temporary/excluded", "A1-preserve-local-evidence"
    if lower.startswith("openspec/") or name == "presenter-handoff-talk-track.md":
        return "temporary/excluded", "A3-relocate-or-delete"
    if (
        ".parity.spec.ts" in lower
        or name == "tsconfig.parity-spec.json"
        or path in {
            "01_exercises/frontend/angular.json",
            "01_exercises/frontend/package.json",
        }
    ):
        return "temporary/excluded", "A2-A3-parity-evidence-and-removal"
    if path in {
        ".gitignore",
        "analytics/scripts/capture_integration_baseline.py",
        "analytics/scripts/validate_azd_project_config.py",
        "analytics/scripts/validate_deployment_source_builds.py",
        "analytics/scripts/run_integration_verification.py",
        "analytics/scripts/verify_integration_accounting.py",
    }:
        return "validator/test", "A0-proof-tools"
    if path in PLANNED_OUTPUT_PATHS:
        return "validator/test", "A3-parity-assertion-migration"
    if path in {
        "02_completed/azure.yaml",
        "02_completed/.gitignore",
        "02_completed/Dockerfile.api",
        "02_completed/Dockerfile.frontend",
        "02_completed/Dockerfile.mcp",
    }:
        return "completed-only demo", "A4-deployment-cleanup"
    if "/tests/" in lower or name.startswith("validate_") or name.startswith("verify_"):
        return "validator/test", "preserve-preexisting-follow-on-work"
    if lower.endswith((".ipynb", ".pbix")) or "/powerbi/" in lower:
        return "generated derivative", "preserve-preexisting-follow-on-work"
    if lower.endswith((".md", ".docx")):
        return "docs", "preserve-preexisting-follow-on-work"
    if lower.startswith("01_exercises/") or (
        lower.startswith("02_completed/")
        and any(token in lower for token in ("/frontend/", "/python/", "/mcp_server/"))
    ):
        return "shared runtime", "preserve-preexisting-follow-on-work"
    if lower.startswith(("02_completed/", "analytics/")):
        return "completed-only demo", "preserve-preexisting-follow-on-work"
    return "unrelated", "preserve-unrelated-dirty-work"


def publication_snapshot() -> dict[str, Any]:
    branch = text(["git", "branch", "--show-current"])
    command = [
        "gh",
        "pr",
        "list",
        "--head",
        branch,
        "--state",
        "open",
        "--json",
        "number,url,headRefName,state",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    parsed = None
    if result.returncode == 0:
        try:
            parsed = json.loads(result.stdout.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = None
    return {
        "command": command,
        "exit_code": result.returncode,
        "current_prs": parsed if isinstance(parsed, list) else None,
        "stdout_sha256": sha256_bytes(result.stdout),
        "stderr_sha256": sha256_bytes(result.stderr),
    }


def capture(bootstrap_file: Path) -> dict[str, Any]:
    bootstrap_bytes = bootstrap_file.read_bytes()
    bootstrap = json.loads(bootstrap_bytes.decode("utf-8-sig"))
    head = text(["git", "rev-parse", "HEAD"])
    index_tree = text(["git", "write-tree"])
    if bootstrap.get("head") != head:
        raise RuntimeError("bootstrap HEAD does not match current HEAD")
    if bootstrap.get("index_tree") != index_tree:
        raise RuntimeError("bootstrap index tree does not match current index")

    bootstrap_dirty = bootstrap_paths(bootstrap)
    if len(bootstrap_dirty) != len(set(bootstrap_dirty)):
        raise RuntimeError("bootstrap dirty paths are not unique")
    expected_count = bootstrap.get("status_entry_count")
    ignored_bootstrap_entries = sum(
        1
        for entry in bootstrap.get("status_entries", [])
        if not isinstance(entry, str) or len(entry.rstrip("\r\n")) < 4
    )
    if (
        expected_count is not None
        and expected_count != len(bootstrap_dirty) + ignored_bootstrap_entries
    ):
        raise RuntimeError(
            "bootstrap count mismatch: "
            f"declared {expected_count}, parsed {len(bootstrap_dirty)} paths plus "
            f"{ignored_bootstrap_entries} non-path framing entries"
        )

    status_payload = run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"]
    )
    status = parse_porcelain_v1_z(status_payload)
    current_paths = [record["path"] for record in status]
    current_records = {record["path"]: record for record in status}
    all_paths = sorted(set(bootstrap_dirty) | set(current_paths) | PLANNED_OUTPUT_PATHS)
    manifest = []
    for path in all_paths:
        classification, task = classify(path)
        current = current_records.get(path)
        if classification == "temporary/excluded":
            disposition = "absent"
            expected_xy = None
        elif path in PLANNED_OUTPUT_PATHS:
            disposition = EXPECTED_FINAL_DISPOSITIONS[path]
            expected_xy = (
                current["xy"]
                if disposition == "present-dirty" and current
                else " M"
                if disposition == "present-dirty" and is_tracked(path)
                else "??"
                if disposition == "present-dirty"
                else None
            )
        elif path in set(bootstrap_dirty) or path in set(current_paths):
            disposition = "present-dirty"
            expected_xy = current["xy"] if current else None
        else:
            disposition = "absent"
            expected_xy = None
        manifest.append(
            {
                "path": path,
                "classification": classification,
                "task_coverage": task,
                "present_in_bootstrap": path in set(bootstrap_dirty),
                "present_at_capture": path in set(current_paths),
                "planned_output": path in PLANNED_OUTPUT_PATHS,
                "tracked_at_capture": is_tracked(path),
                "expected_final_disposition": disposition,
                "expected_porcelain_xy": expected_xy,
                "expected_original_path": (
                    current.get("original_path") if current else None
                ),
                "preservation_fingerprint": (
                    path_fingerprint(path)
                    if classification == "unrelated" and current is not None
                    else None
                ),
            }
        )
    if len(manifest) != len(all_paths) or any(
        not item["classification"] or not item["task_coverage"] for item in manifest
    ):
        raise RuntimeError("dirty manifest coverage is incomplete")

    branch = text(["git", "branch", "--show-current"])
    upstream_ref = text(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"]
    )
    upstream_sha = text(["git", "rev-parse", upstream_ref])
    behind, ahead = (
        text(["git", "rev-list", "--left-right", "--count", f"{upstream_ref}...HEAD"])
        .replace("\t", " ")
        .split()
    )
    staged_paths = [
        normalize_path(value)
        for value in text(
            ["git", "diff", "--cached", "--name-only", "-z"]
        ).split("\0")
        if value
    ]
    return {
        "schema_version": 3,
        "captured_utc": utc_now(),
        "repository": str(ROOT),
        "bootstrap": {
            "source_path": str(bootstrap_file),
            "source_bytes": len(bootstrap_bytes),
            "source_sha256": sha256_bytes(bootstrap_bytes),
            "captured_utc": bootstrap.get("captured_utc"),
            "status_format": bootstrap.get("status_format"),
            "dirty_path_count": len(bootstrap_dirty),
            "non_path_framing_entry_count": ignored_bootstrap_entries,
            "validated": True,
        },
        "head": head,
        "branch": branch,
        "upstream_ref": upstream_ref,
        "upstream_sha": upstream_sha,
        "ahead": int(ahead),
        "behind": int(behind),
        "index_tree": index_tree,
        "staged_paths": staged_paths,
        "status_format": "git status --porcelain=v1 -z --untracked-files=all",
        "status_sha256": sha256_bytes(status_payload),
        "status_entry_count": len(status),
        "status_entries": status,
        "unstaged_paths": sorted(
            {record["path"] for record in status if record["unstaged"]}
        ),
        "untracked_paths": sorted(
            {record["path"] for record in status if record["untracked"]}
        ),
        "dirty_manifest": manifest,
        "dirty_manifest_count": len(manifest),
        "bootstrap_dirty_paths_covered": len(bootstrap_dirty),
        "capture_dirty_paths_covered": len(set(current_paths)),
        "publication": publication_snapshot(),
    }


def self_test() -> int:
    payload = (
        b" M ordinary.txt\0?? spaced name.txt\0"
        b"R  renamed.txt\0old-name.txt\0"
    )
    parsed = parse_porcelain_v1_z(payload)
    assert [item["path"] for item in parsed] == [
        "ordinary.txt",
        "spaced name.txt",
        "renamed.txt",
    ]
    assert parsed[2]["original_path"] == "old-name.txt"
    assert classify("openspec/change/spec.md") == (
        "temporary/excluded",
        "A3-relocate-or-delete",
    )
    assert classify("analytics/checklist.json") == (
        "docs",
        "F3-presenter-docs-traceability",
    )
    assert classify("02_completed/frontend/README.md") == (
        "docs",
        "G2-authored-link-correction",
    )
    assert classify(
        "analytics/scripts/tests/test_validate_controlled_demo4_docs.py"
    ) == ("validator/test", "F3/G2-regression")
    assert classify("analytics/scripts/tests/test_validate_markdown_links.py") == (
        "validator/test",
        "F1/G2-regression",
    )
    fixture = ROOT / ".local" / "integration-evidence" / "baseline-self-test.txt"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("fingerprint", encoding="utf-8")
    try:
        fingerprint = path_fingerprint(
            ".local/integration-evidence/baseline-self-test.txt"
        )
        assert fingerprint and fingerprint["bytes"] == 11
    finally:
        fixture.unlink()
    print("capture_integration_baseline self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--bootstrap")
    parser.add_argument("--require-complete-coverage", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.output:
        parser.error("--output is required unless --self-test is used")
    document = capture(discover_bootstrap(args.bootstrap))
    if args.require_complete_coverage:
        manifest = document["dirty_manifest"]
        if (
            len({item["path"] for item in manifest}) != len(manifest)
            or document["bootstrap_dirty_paths_covered"]
            != document["bootstrap"]["dirty_path_count"]
        ):
            raise RuntimeError("complete dirty-path coverage check failed")
    output = (ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output.write_bytes(encoded)
    reread = json.loads(output.read_text(encoding="utf-8"))
    if reread["dirty_manifest_count"] != len(reread["dirty_manifest"]):
        raise RuntimeError("baseline reread verification failed")
    print(
        f"baseline captured: {output.relative_to(ROOT)} "
        f"({reread['dirty_manifest_count']} classified paths)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

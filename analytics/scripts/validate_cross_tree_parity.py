#!/usr/bin/env python3
"""Strict allowlisted parity validation for shared workshop trees."""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WILDCARDS = ("*", "?", "[", "]")


class ParityError(AssertionError):
    pass


def _relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ParityError(f"{label} must be a non-empty repository-relative path")
    if any(token in value for token in WILDCARDS):
        raise ParityError(f"{label} must not contain wildcards: {value}")
    normalized = Path(value)
    if ".." in normalized.parts:
        raise ParityError(f"{label} must not escape the repository: {value}")
    return value.replace("\\", "/")


def _load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ParityError("schema_version must be 1")
    for key in ("file_pairs", "allowances", "seed_manifest"):
        if not isinstance(config.get(key), list):
            raise ParityError(f"{key} must be a list")
    return config


def _validate_pair(entry: dict[str, Any], label: str) -> tuple[str, str]:
    return (
        _relative_path(entry.get("left"), f"{label}.left"),
        _relative_path(entry.get("right"), f"{label}.right"),
    )


def _compare_files(root: Path, config: dict[str, Any]) -> tuple[int, int]:
    compared = 0
    allowed = 0
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(config["file_pairs"]):
        left, right = _validate_pair(entry, f"file_pairs[{index}]")
        pair = (left, right)
        if pair in seen:
            raise ParityError(f"duplicate paired paths: {left} :: {right}")
        seen.add(pair)
        left_path, right_path = root / left, root / right
        if not left_path.is_file() or not right_path.is_file():
            raise ParityError(f"paired file missing: {left} :: {right}")
        if left_path.read_bytes() != right_path.read_bytes():
            raise ParityError(f"unallowlisted file difference: {left} :: {right}")
        compared += 1

    for index, entry in enumerate(config["allowances"]):
        left, right = _validate_pair(entry, f"allowances[{index}]")
        pair = (left, right)
        if pair in seen:
            raise ParityError(f"pair cannot be both compared and allowed: {left} :: {right}")
        seen.add(pair)
        for field in ("reason", "owner", "review_condition"):
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                raise ParityError(f"allowances[{index}].{field} is required")
        left_path, right_path = root / left, root / right
        if not left_path.is_file() or not right_path.is_file():
            raise ParityError(f"allowlisted file missing: {left} :: {right}")
        if left_path.read_bytes() == right_path.read_bytes():
            raise ParityError(f"stale allowance for equal files: {left} :: {right}")
        allowed += 1
    return compared, allowed


def _remove_path(record: dict[str, Any], dotted_path: str) -> None:
    parts = dotted_path.split(".")
    current: Any = record
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ParityError(f"stale removable field: {dotted_path}")
        current = current[part]
    if not isinstance(current, dict) or parts[-1] not in current:
        raise ParityError(f"stale removable field: {dotted_path}")
    del current[parts[-1]]


def _record_map(path: Path, id_field: str) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ParityError(f"seed file must contain a list: {path}")
    records: dict[str, dict[str, Any]] = {}
    for record in data:
        if not isinstance(record, dict) or not isinstance(record.get(id_field), str):
            raise ParityError(f"seed record missing string {id_field}: {path}")
        record_id = record[id_field]
        if record_id in records:
            raise ParityError(f"duplicate seed id {record_id}: {path}")
        records[record_id] = record
    return records


def _compare_seeds(root: Path, config: dict[str, Any]) -> tuple[int, int]:
    manifests = 0
    records_compared = 0
    names: set[str] = set()
    for index, entry in enumerate(config["seed_manifest"]):
        name = entry.get("name")
        if not isinstance(name, str) or not name or name in names:
            raise ParityError(f"seed_manifest[{index}].name must be unique")
        names.add(name)
        left, right = _validate_pair(entry, f"seed_manifest[{index}]")
        id_field = entry.get("id_field")
        record_ids = entry.get("record_ids")
        remove_fields = entry.get("remove_fields")
        if not isinstance(id_field, str) or not id_field:
            raise ParityError(f"{name}: id_field is required")
        if (
            not isinstance(record_ids, list)
            or not record_ids
            or any(not isinstance(value, str) or not value for value in record_ids)
            or len(record_ids) != len(set(record_ids))
        ):
            raise ParityError(f"{name}: record_ids must be a non-empty unique string list")
        if not isinstance(remove_fields, list) or any(
            not isinstance(value, str)
            or not value
            or any(token in value for token in WILDCARDS)
            for value in remove_fields
        ):
            raise ParityError(f"{name}: remove_fields must contain exact dotted paths")

        left_records = _record_map(root / left, id_field)
        right_records = _record_map(root / right, id_field)
        for record_id in record_ids:
            if record_id not in left_records or record_id not in right_records:
                raise ParityError(f"{name}: changed membership for record {record_id}")
            left_record = copy.deepcopy(left_records[record_id])
            right_record = copy.deepcopy(right_records[record_id])
            for dotted_path in remove_fields:
                _remove_path(left_record, dotted_path)
                _remove_path(right_record, dotted_path)
            if left_record != right_record:
                raise ParityError(f"{name}: semantic seed difference for record {record_id}")
            records_compared += 1
        manifests += 1
    return manifests, records_compared


def validate(root: Path, config_path: Path, normalize_seeds: bool) -> dict[str, int]:
    config = _load_config(config_path)
    compared, allowed = _compare_files(root, config)
    manifests = records = 0
    if normalize_seeds:
        manifests, records = _compare_seeds(root, config)
    return {
        "equal_file_pairs": compared,
        "reviewed_allowances": allowed,
        "seed_manifests": manifests,
        "seed_records": records,
    }


def self_test() -> int:
    fixture = ROOT / ".local" / "integration-evidence" / "self-test" / "cross-tree-parity"
    if fixture.exists():
        shutil.rmtree(fixture)
    (fixture / "left").mkdir(parents=True)
    (fixture / "right").mkdir(parents=True)
    (fixture / "left" / "equal.txt").write_text("same\n", encoding="utf-8")
    (fixture / "right" / "equal.txt").write_text("same\n", encoding="utf-8")
    (fixture / "left" / "allowed.txt").write_text("learner\n", encoding="utf-8")
    (fixture / "right" / "allowed.txt").write_text("completed\n", encoding="utf-8")
    seed = [{"id": "one", "tenantId": "left", "payload": {"value": 7}}]
    (fixture / "left" / "seed.json").write_text(json.dumps(seed), encoding="utf-8")
    seed[0]["tenantId"] = "right"
    (fixture / "right" / "seed.json").write_text(json.dumps(seed), encoding="utf-8")
    base = {
        "schema_version": 1,
        "file_pairs": [{"left": "left/equal.txt", "right": "right/equal.txt"}],
        "allowances": [{
            "left": "left/allowed.txt",
            "right": "right/allowed.txt",
            "reason": "fixture",
            "owner": "self-test",
            "review_condition": "always",
        }],
        "seed_manifest": [{
            "name": "fixture",
            "left": "left/seed.json",
            "right": "right/seed.json",
            "id_field": "id",
            "record_ids": ["one"],
            "remove_fields": ["tenantId"],
        }],
    }

    def run_case(name: str, mutate, should_pass: bool) -> None:
        candidate = copy.deepcopy(base)
        mutate(candidate)
        path = fixture / f"{name}.json"
        path.write_text(json.dumps(candidate), encoding="utf-8")
        try:
            validate(fixture, path, True)
        except ParityError:
            if should_pass:
                raise
        else:
            if not should_pass:
                raise AssertionError(f"negative self-test unexpectedly passed: {name}")

    run_case("positive", lambda _: None, True)
    run_case(
        "unallowlisted-difference",
        lambda value: value["file_pairs"].append(
            {"left": "left/allowed.txt", "right": "right/allowed.txt"}
        ),
        False,
    )
    run_case(
        "stale-allowance",
        lambda value: (
            value.__setitem__("file_pairs", []),
            value.__setitem__("allowances", [{
                "left": "left/equal.txt",
                "right": "right/equal.txt",
                "reason": "stale",
                "owner": "self-test",
                "review_condition": "always",
            }]),
        ),
        False,
    )
    run_case(
        "wildcard",
        lambda value: value["file_pairs"].append(
            {"left": "left/*.txt", "right": "right/equal.txt"}
        ),
        False,
    )
    run_case(
        "changed-membership",
        lambda value: value["seed_manifest"][0]["record_ids"].append("missing"),
        False,
    )
    semantic_path = fixture / "right" / "seed.json"
    original = semantic_path.read_text(encoding="utf-8")
    semantic_path.write_text(
        json.dumps([{"id": "one", "tenantId": "right", "payload": {"value": 8}}]),
        encoding="utf-8",
    )
    run_case("semantic-difference", lambda _: None, False)
    semantic_path.write_text(original, encoding="utf-8")
    shutil.rmtree(fixture)
    print("cross-tree parity self-test: PASS (1 positive, 5 negative cases)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allowlist",
        default="analytics/config/cross-tree-parity-allowlist.json",
    )
    parser.add_argument("--normalize-seeds", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    config_path = Path(args.allowlist)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    try:
        counts = validate(ROOT, config_path, args.normalize_seeds)
    except (ParityError, OSError, json.JSONDecodeError) as exc:
        print(f"cross-tree parity: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "cross-tree parity: PASS "
        f"equal_file_pairs={counts['equal_file_pairs']} "
        f"reviewed_allowances={counts['reviewed_allowances']} "
        f"seed_manifests={counts['seed_manifests']} "
        f"seed_records={counts['seed_records']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

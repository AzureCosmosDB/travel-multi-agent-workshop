#!/usr/bin/env python3
"""Map changed public symbols to consumers and proof coverage."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "analytics" / "config" / "changed-symbol-blast-radius.json"
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".tmdl", ".json"}
SEARCH_SUFFIXES = SOURCE_SUFFIXES | {".js", ".jsx", ".md", ".html"}
TS_DEFINITION = re.compile(
    r"^\s*(?:(?:export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:class|function|interface|type|enum|const|let|var))|"
    r"(?:class|function|interface|type|enum))\s+"
    r"([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
TMDL_MEASURE = re.compile(r"^\s*measure\s+'([^']+)'\s*=", re.MULTILINE)
PBIR_QUERY_REF = re.compile(r'"queryRef"\s*:\s*"([^"]+)"')


def git(args: list[str], *, check: bool = True) -> bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def normalize(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")


def configured_path(path: str, scopes: list[str]) -> bool:
    normalized = normalize(path)
    return any(
        normalized == normalize(scope).rstrip("/")
        or normalized.startswith(normalize(scope).rstrip("/") + "/")
        for scope in scopes
    )


def changed_files(config: dict[str, Any]) -> list[str]:
    tracked = {
        normalize(item)
        for item in git(["diff", "--name-only", "--diff-filter=ACMRD", "HEAD"])
        .decode("utf-8", "surrogateescape")
        .splitlines()
        if Path(item).suffix.casefold() in SOURCE_SUFFIXES
    }
    untracked = {
        normalize(item)
        for item in git(["ls-files", "--others", "--exclude-standard"])
        .decode("utf-8", "surrogateescape")
        .splitlines()
        if Path(item).suffix.casefold() in SOURCE_SUFFIXES
    }
    scopes = config["production_scopes"]
    test_scopes = config["test_scopes"]
    return sorted(
        path
        for path in tracked | untracked
        if configured_path(path, scopes) and not configured_path(path, test_scopes)
    )


def file_at_head(path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else ""


def changed_line_sets(path: str, current_text: str, base_text: str) -> tuple[set[int], set[int]]:
    if not base_text:
        return set(range(1, current_text.count("\n") + 2)), set()
    patch = git(["diff", "--unified=0", "HEAD", "--", path], check=False).decode(
        "utf-8", "replace"
    )
    current: set[int] = set()
    base: set[int] = set()
    pattern = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    for line in patch.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        old_start, old_count, new_start, new_count = (
            int(match.group(1)),
            int(match.group(2) or "1"),
            int(match.group(3)),
            int(match.group(4) or "1"),
        )
        base.update(range(old_start, old_start + old_count))
        current.update(range(new_start, new_start + new_count))
    return current, base


def python_symbols(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    symbols: list[dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(
                {
                    "name": node.name,
                    "qualified_name": node.name,
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "start": node.lineno,
                    "end": getattr(node, "end_lineno", node.lineno),
                }
            )
            if isinstance(node, ast.ClassDef):
                for member in node.body:
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(
                            {
                                "name": member.name,
                                "qualified_name": f"{node.name}.{member.name}",
                                "kind": "method",
                                "start": member.lineno,
                                "end": getattr(member, "end_lineno", member.lineno),
                            }
                        )
    return symbols


def regex_symbols(text: str, suffix: str) -> list[dict[str, Any]]:
    pattern = TMDL_MEASURE if suffix == ".tmdl" else TS_DEFINITION
    kind = "measure" if suffix == ".tmdl" else "typescript"
    symbols: list[dict[str, Any]] = []
    for match in pattern.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        symbols.append(
            {
                "name": match.group(1),
                "qualified_name": match.group(1),
                "kind": kind,
                "start": line,
                "end": line,
            }
        )
    return symbols


def symbols_for(path: str, text: str) -> list[dict[str, Any]]:
    suffix = Path(path).suffix.casefold()
    if suffix == ".py":
        return python_symbols(text)
    if suffix in {".ts", ".tsx", ".tmdl"}:
        return regex_symbols(text, suffix)
    if suffix == ".json" and ".Report/" in path.replace("\\", "/"):
        return [
            {
                "name": name,
                "qualified_name": name,
                "kind": "pbir-query-reference",
                "start": text.count("\n", 0, match.start()) + 1,
                "end": text.count("\n", 0, match.start()) + 1,
            }
            for match in PBIR_QUERY_REF.finditer(text)
            for name in [match.group(1)]
        ]
    return []


def public_symbol(symbol: dict[str, Any], config: dict[str, Any]) -> bool:
    name = symbol["name"]
    return (
        len(name) >= int(config.get("minimum_symbol_length", 4))
        and not name.startswith("_")
        and name.casefold() not in {item.casefold() for item in config.get("generic_names", [])}
    )


def overlaps(symbol: dict[str, Any], lines: set[int]) -> bool:
    return any(symbol["start"] <= line <= symbol["end"] for line in lines)


def repository_search_files(config: dict[str, Any]) -> list[Path]:
    ignored = {normalize(item).rstrip("/") for item in config.get("ignored_scopes", [])}
    result: list[Path] = []
    for raw_directory, directories, filenames in os.walk(ROOT):
        directory = Path(raw_directory)
        relative_directory = (
            directory.relative_to(ROOT).as_posix() if directory != ROOT else ""
        )
        directories[:] = [
            name
            for name in directories
            if name
            not in {
                ".git",
                ".local",
                ".angular",
                ".venv",
                "__pycache__",
                "dist",
                "node_modules",
                "venv",
            }
            if not any(
                candidate == ignored_path
                or candidate.startswith(ignored_path + "/")
                for ignored_path in ignored
                for candidate in [
                    f"{relative_directory}/{name}".strip("/")
                ]
            )
        ]
        for filename in filenames:
            path = directory / filename
            if path.suffix.casefold() in SEARCH_SUFFIXES:
                result.append(path)
    return result


def build_reference_index(
    files: list[Path], config: dict[str, Any]
) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
    index: dict[str, list[dict[str, str]]] = {}
    corpus: dict[str, str] = {}
    token_pattern = re.compile(r"[A-Za-z_$][\w$]*")
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        corpus[relative] = text
        names = set(token_pattern.findall(text))
        names.update(TMDL_MEASURE.findall(text))
        names.update(PBIR_QUERY_REF.findall(text))
        reference = {
            "path": relative,
            "classification": classify_reference(relative, config),
        }
        for name in names:
            index.setdefault(name, []).append(reference)
    return index, corpus


def file_level_coverage(
    defining_path: str,
    source_text: str,
    corpus: dict[str, str],
    config: dict[str, Any],
) -> list[dict[str, str]]:
    stem = Path(defining_path).stem.casefold()
    module_name = defining_path.rsplit(".", 1)[0].replace("/", ".").casefold()
    coverage: list[dict[str, str]] = []
    if re.search(r"def\s+(?:run_)?self_test\s*\(", source_text):
        coverage.append(
            {
                "path": defining_path,
                "classification": "self-test",
            }
        )
    for path, text in corpus.items():
        classification = classify_reference(path, config)
        if classification not in {"test", "validator"} or path == defining_path:
            continue
        folded_path = path.casefold()
        folded_text = text.casefold()
        applicable = stem in folded_path or stem in folded_text or module_name in folded_text
        if defining_path.endswith(".tmdl") or ".Report/" in defining_path:
            applicable = applicable or path.endswith(
                "analytics/powerbi/validate_tenant_switching.py"
            )
        if defining_path.startswith("analytics/fabric/"):
            applicable = applicable or path.startswith("analytics/fabric/tests/")
        if "/frontend/src/app/" in defining_path:
            expected_spec = str(Path(defining_path).with_suffix(".spec.ts")).replace(
                "\\", "/"
            )
            applicable = applicable or path == expected_spec
        if applicable:
            coverage.append({"path": path, "classification": classification})
    return coverage


def classify_reference(path: str, config: dict[str, Any]) -> str:
    if configured_path(path, config["test_scopes"]):
        return "test"
    if configured_path(path, config["validator_scopes"]):
        return "validator"
    if configured_path(path, config["production_scopes"]):
        return "production"
    return "other"


def references(
    symbol: dict[str, Any],
    defining_path: str,
    files: list[Path],
    config: dict[str, Any],
    index: dict[str, list[dict[str, str]]] | None = None,
) -> list[dict[str, str]]:
    name = symbol["name"]
    if index is not None:
        return [
            reference
            for reference in index.get(name, [])
            if reference["path"] != defining_path
        ]
    escaped = re.escape(name)
    if re.fullmatch(r"[A-Za-z_$][\w$]*", name):
        pattern = re.compile(rf"(?<![\w$]){escaped}(?![\w$])")
    else:
        pattern = re.compile(escaped)
    found: list[dict[str, str]] = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if relative == defining_path:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not pattern.search(text):
            continue
        classification = classify_reference(relative, config)
        found.append({"path": relative, "classification": classification})
    return found


def symbol_status(
    disposition: str,
    production_refs: list[dict[str, str]],
    applicable: list[dict[str, str]],
) -> tuple[str, str]:
    if disposition == "removed" and production_refs:
        return "Failed", "removed symbol remains referenced by production code"
    if disposition == "changed" and not applicable:
        return "Failed", "changed production symbol has no applicable test or validator"
    return "Verified", ""


def analyze(config: dict[str, Any]) -> dict[str, Any]:
    files = repository_search_files(config)
    reference_index, corpus = build_reference_index(files, config)
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for path in changed_files(config):
        current_path = ROOT / path
        current_text = (
            current_path.read_text(encoding="utf-8") if current_path.is_file() else ""
        )
        base_text = file_at_head(path)
        current_lines, base_lines = changed_line_sets(path, current_text, base_text)
        current_symbols = {
            item["qualified_name"]: item
            for item in symbols_for(path, current_text)
            if public_symbol(item, config)
        }
        base_symbols = {
            item["qualified_name"]: item
            for item in symbols_for(path, base_text)
            if public_symbol(item, config)
        }
        changed = [
            item for item in current_symbols.values() if overlaps(item, current_lines)
        ]
        removed = [
            item
            for name, item in base_symbols.items()
            if overlaps(item, base_lines) and name not in current_symbols
        ]
        file_coverage = file_level_coverage(path, current_text, corpus, config)
        for disposition, symbols in (("changed", changed), ("removed", removed)):
            for symbol in symbols:
                refs = references(symbol, path, files, config, reference_index)
                exact_applicable = [
                    ref
                    for ref in refs
                    if ref["classification"] in {"test", "validator"}
                ]
                applicable = list(exact_applicable)
                if disposition == "changed":
                    for item in file_coverage:
                        if item not in applicable:
                            applicable.append(item)
                production_refs = [
                    ref for ref in refs if ref["classification"] == "production"
                ]
                result = {
                    "path": path,
                    "symbol": symbol["qualified_name"],
                    "search_name": symbol["name"],
                    "kind": symbol["kind"],
                    "disposition": disposition,
                    "references": refs,
                    "production_consumers": production_refs,
                    "applicable_tests_or_validators": applicable,
                    "status": "",
                    "reason": "",
                }
                result["status"], result["reason"] = symbol_status(
                    disposition, production_refs, applicable
                )
                if result["status"] == "Failed":
                    failures.append(f"{path}:{symbol['qualified_name']}: {result['reason']}")
                results.append(result)
    return {
        "schema_version": 1,
        "status": "Failed" if failures else "Verified",
        "changed_files": changed_files(config),
        "symbols": results,
        "failures": failures,
    }


def fixture_config(root: Path) -> dict[str, Any]:
    return {
        "production_scopes": ["src"],
        "test_scopes": ["tests"],
        "validator_scopes": ["validators"],
        "ignored_scopes": [".git"],
        "minimum_symbol_length": 4,
        "generic_names": ["main", "data", "value", "result"],
        "_fixture_root": str(root),
    }


def self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="blast-radius-self-test-") as raw:
        root = Path(raw)
        (root / "src").mkdir()
        (root / "tests").mkdir()
        source = "def calculate_total(value):\n    return value + 1\n"
        test = "from src.module import calculate_total\n\ndef test_total():\n    assert calculate_total(1) == 2\n"
        (root / "src" / "module.py").write_text(source, encoding="utf-8")
        (root / "tests" / "test_module.py").write_text(test, encoding="utf-8")
        symbols = python_symbols(source)
        assert [item["name"] for item in symbols] == ["calculate_total"]
        config = fixture_config(root)
        original_root = globals()["ROOT"]
        try:
            globals()["ROOT"] = root
            refs = references(
                symbols[0],
                "src/module.py",
                [root / "src" / "module.py", root / "tests" / "test_module.py"],
                config,
            )
            assert refs == [
                {"path": "tests/test_module.py", "classification": "test"}
            ]
            removed_refs = references(
                {"name": "calculate_total"},
                "src/module.py",
                [root / "tests" / "test_module.py"],
                config,
            )
            assert removed_refs[0]["classification"] == "test"
            assert not public_symbol(
                {"name": "data"}, config
            ), "generic local names must be ignored"
            assert symbol_status(
                "removed",
                [{"path": "src/consumer.py", "classification": "production"}],
                [],
            )[0] == "Failed"
            assert symbol_status("changed", [], [refs[0]])[0] == "Verified"
            assert symbol_status("changed", [], [])[0] == "Failed"
        finally:
            globals()["ROOT"] = original_root
    print("validate_changed_symbol_blast_radius self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    config = json.loads(config_path.read_text(encoding="utf-8"))
    report = analyze(config)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
        print(f"BLAST_RADIUS_EVIDENCE={output.relative_to(ROOT).as_posix()}")
    else:
        print(encoded, end="")
    for failure in report["failures"]:
        print(f"FAIL: {failure}", file=sys.stderr)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

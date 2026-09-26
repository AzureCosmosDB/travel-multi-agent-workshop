#!/usr/bin/env python3
"""Validate the local Word-flow traceability checklist and its documentation targets."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
DEMO_NAMES = [
    "Frontend application",
    "Cosmos, mirroring, and SQL endpoint",
    "Fabric notebook",
    "User Data Function",
    "Power BI and web analytics portal",
]
REQUIRED_REQUIREMENTS = {
    "conceptual-talk-track",
    "browser-target",
    "runtime-truth",
    "operational-preparation",
    "live-vs-prepared",
}
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)")
HANDOFF_RE = re.compile(r"(?i)\bpresenter[- ]handoff\b|\bhandoff dependency\b")


def _slug(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-")


def _contains_forbidden(value: Any) -> str | None:
    if isinstance(value, dict):
        for child in value.values():
            result = _contains_forbidden(child)
            if result:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _contains_forbidden(child)
            if result:
                return result
    elif isinstance(value, str):
        if URL_RE.search(value):
            return "URL"
        if HANDOFF_RE.search(value):
            return "presenter-handoff dependency"
    return None


def validate(checklist: Path, docs: list[Path], root: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(checklist.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{checklist}: invalid checklist JSON: {exc}"]

    forbidden = _contains_forbidden(data)
    if forbidden:
        errors.append(f"{checklist}: checklist contains forbidden {forbidden}")
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{checklist}: schema_version must be {SCHEMA_VERSION}")
    if data.get("source") != "Multi-Agent Travel Demo.docx":
        errors.append(f"{checklist}: source must name the supplied Word document without a path")
    if data.get("demo_order") != DEMO_NAMES:
        errors.append(f"{checklist}: demo_order must exactly match the five-demo Word sequence")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        errors.append(f"{checklist}: items must be a non-empty array")
        return errors

    doc_map: dict[str, tuple[Path, str]] = {}
    for doc in docs:
        resolved = doc if doc.is_absolute() else root / doc
        if not resolved.is_file():
            errors.append(f"{resolved}: documentation target is missing")
            continue
        text = resolved.read_text(encoding="utf-8")
        if HANDOFF_RE.search(text):
            errors.append(f"{resolved}: document contains forbidden presenter-handoff dependency")
        if resolved.name == "demo-script.md" and URL_RE.search(text):
            errors.append(f"{resolved}: demo script contains a forbidden URL")
        try:
            key = str(resolved.relative_to(root)).replace("\\", "/")
        except ValueError:
            key = str(resolved)
        doc_map[key] = (resolved, text)

    seen_ids: set[str] = set()
    seen_orders: list[int] = []
    demos_seen: set[int] = set()
    for index, item in enumerate(items):
        prefix = f"{checklist}:items[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix}: item must be an object")
            continue
        required = ("id", "demo", "order", "source_item", "browser", "target", "requirements")
        for field in required:
            if field not in item:
                errors.append(f"{prefix}: missing {field}")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{prefix}: id must be a non-empty string")
        elif item_id in seen_ids:
            errors.append(f"{prefix}: duplicate id {item_id}")
        else:
            seen_ids.add(item_id)

        demo = item.get("demo")
        if not isinstance(demo, int) or not 1 <= demo <= 5:
            errors.append(f"{prefix}: demo must be an integer from 1 through 5")
        else:
            demos_seen.add(demo)
        order = item.get("order")
        if not isinstance(order, int):
            errors.append(f"{prefix}: order must be an integer")
        else:
            seen_orders.append(order)

        browser = item.get("browser")
        if not isinstance(browser, dict):
            errors.append(f"{prefix}: browser must be an object")
        else:
            for field in ("instance", "tab", "location"):
                if not isinstance(browser.get(field), str) or not browser[field].strip():
                    errors.append(f"{prefix}: browser.{field} is required")
            if demo == 4 and "optimization-apply-loop" not in str(browser.get("location", "")):
                errors.append(f"{prefix}: Demo 4 location must name optimization-apply-loop")

        target = item.get("target")
        if not isinstance(target, dict):
            errors.append(f"{prefix}: target must be an object")
        else:
            document = str(target.get("document", "")).replace("\\", "/")
            section = target.get("section")
            anchor = target.get("anchor")
            if document not in doc_map:
                errors.append(f"{prefix}: target.document is not one of the supplied docs: {document}")
            elif not isinstance(section, str) or not section:
                errors.append(f"{prefix}: target.section is required")
            elif not isinstance(anchor, str) or anchor != _slug(section):
                errors.append(f"{prefix}: target.anchor must be the stable slug of target.section")
            else:
                _, text = doc_map[document]
                heading = re.compile(rf"(?m)^#+\s+{re.escape(section)}\s*$", re.I)
                if not heading.search(text):
                    errors.append(f"{prefix}: target section not found in {document}: {section}")

        requirements = item.get("requirements")
        if (
            not isinstance(requirements, list)
            or not requirements
            or not all(isinstance(value, str) and value for value in requirements)
        ):
            errors.append(f"{prefix}: requirements must be a non-empty string array")
        elif not set(requirements) <= REQUIRED_REQUIREMENTS:
            errors.append(f"{prefix}: requirements contains an unknown operational requirement")

    expected_orders = list(range(1, len(items) + 1))
    if seen_orders != expected_orders:
        errors.append(f"{checklist}: item order must be contiguous and already sorted")
    if demos_seen != {1, 2, 3, 4, 5}:
        errors.append(f"{checklist}: every demo number must have at least one traceability item")
    return errors


def _fixture(root: Path) -> tuple[Path, list[Path], dict[str, Any]]:
    docs: list[Path] = []
    for name, heading in (
        ("analytics/docs/demo-script.md", "Five-demo sequence"),
        ("02_completed/README.md", "Presenter flow"),
        ("02_completed/USER_GUIDE.md", "Browser setup"),
        ("analytics/powerbi/PowerBI_Optimization_Build_Guide.md", "Prepared mode"),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Test\n\n## {heading}\n\nSafe local documentation.\n", encoding="utf-8")
        docs.append(Path(name))
    sections = ["Five-demo sequence", "Presenter flow", "Browser setup", "Prepared mode", "Five-demo sequence"]
    documents = [
        "analytics/docs/demo-script.md",
        "02_completed/README.md",
        "02_completed/USER_GUIDE.md",
        "analytics/powerbi/PowerBI_Optimization_Build_Guide.md",
        "analytics/docs/demo-script.md",
    ]
    items = []
    for demo in range(1, 6):
        location = "optimization-apply-loop / apply, revert, and internal status-write functions" if demo == 4 else f"Demo {demo} artifact"
        items.append(
            {
                "id": f"word-{demo:02d}",
                "demo": demo,
                "order": demo,
                "source_item": f"Word sequence item {demo}",
                "browser": {"instance": f"Browser {demo}", "tab": f"Tab {demo}", "location": location},
                "target": {
                    "document": documents[demo - 1],
                    "section": sections[demo - 1],
                    "anchor": _slug(sections[demo - 1]),
                },
                "requirements": ["conceptual-talk-track", "browser-target"],
            }
        )
    data = {
        "schema_version": 1,
        "source": "Multi-Agent Travel Demo.docx",
        "demo_order": DEMO_NAMES,
        "items": items,
    }
    checklist = root / "checklist.json"
    return checklist, docs, data


def run_self_test() -> int:
    mutations = {
        "positive": lambda data: None,
        "schema": lambda data: data.update(schema_version=2),
        "sequence": lambda data: data["demo_order"].reverse(),
        "browser-target": lambda data: data["items"][3]["browser"].update(location="UDF"),
        "target": lambda data: data["items"][0]["target"].update(section="Missing section", anchor="missing-section"),
        "requirement": lambda data: data["items"][0].update(requirements=[]),
        "url": lambda data: data["items"][0]["browser"].update(location="https://example.invalid"),
        "handoff": lambda data: data["items"][0].update(source_item="presenter handoff dependency"),
    }
    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="word-flow-self-test-") as raw:
        root = Path(raw)
        checklist, docs, pristine = _fixture(root)
        for name, mutate in mutations.items():
            data = json.loads(json.dumps(pristine))
            mutate(data)
            checklist.write_text(json.dumps(data), encoding="utf-8")
            has_errors = bool(validate(checklist, docs, root))
            expected = name != "positive"
            if has_errors != expected:
                failed.append(name)
    if failed:
        print("SELF-TEST FAILED: " + ", ".join(failed), file=sys.stderr)
        return 1
    print(f"SELF-TEST PASS: {len(mutations)} cases across 7 rule families")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checklist", type=Path)
    parser.add_argument("--docs", nargs="+", type=Path)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if not args.checklist or not args.docs:
        raise SystemExit("--checklist and --docs are required")
    root = args.root.resolve()
    checklist = args.checklist if args.checklist.is_absolute() else root / args.checklist
    errors = validate(checklist, args.docs, root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"FAILED: {len(errors)} diagnostic(s)", file=sys.stderr)
        return 1
    print(f"PASS: {len(json.loads(checklist.read_text(encoding='utf-8'))['items'])} Word-flow items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

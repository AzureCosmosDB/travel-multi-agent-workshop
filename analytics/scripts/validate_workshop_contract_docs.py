#!/usr/bin/env python3
"""Validate durable workshop documentation contracts owned by Design Brief F."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    "02": Path("01_exercises/workshop/Module-02.md"),
    "03": Path("01_exercises/workshop/Module-03.md"),
    "05": Path("01_exercises/workshop/Module-05.md"),
}
EXACT_PINS = {
    "prompty": "2.0.0b3",
    "azure-cosmos-agent-memory": "0.2.0b3",
}


@dataclass(frozen=True)
class Diagnostic:
    path: Path
    line: int
    message: str

    def render(self, root: Path) -> str:
        try:
            display = self.path.relative_to(root)
        except ValueError:
            display = self.path
        return f"{display}:{self.line}: {self.message}"


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _read(root: Path, key: str) -> tuple[Path, str]:
    path = root / MODULES[key]
    if not path.is_file():
        return path, ""
    return path, path.read_text(encoding="utf-8")


def _missing(path: Path, text: str, needle: str, message: str) -> list[Diagnostic]:
    if needle.lower() in text.lower():
        return []
    return [Diagnostic(path, 1, message)]


def check_pins(root: Path) -> list[Diagnostic]:
    path, text = _read(root, "03")
    errors: list[Diagnostic] = []
    if not text:
        return [Diagnostic(path, 1, "file is missing")]
    for package, expected in EXACT_PINS.items():
        matches = list(re.finditer(rf"(?im)\b{re.escape(package)}==([0-9A-Za-z.\-]+)", text))
        if not matches:
            errors.append(Diagnostic(path, 1, f"missing exact pin {package}=={expected}"))
            continue
        for match in matches:
            actual = match.group(1)
            if actual != expected:
                errors.append(
                    Diagnostic(
                        path,
                        _line(text, match.start()),
                        f"{package} must be pinned to {expected}, found {actual}",
                    )
                )
    return errors


def _python_fences(text: str) -> list[tuple[int, str]]:
    fences: list[tuple[int, str]] = []
    for match in re.finditer(r"(?ms)^```python\s*\n(.*?)^```\s*$", text):
        fences.append((_line(text, match.start(1)), match.group(1)))
    return fences


def check_delete(root: Path) -> list[Diagnostic]:
    path, text = _read(root, "03")
    errors: list[Diagnostic] = []
    if not text:
        return [Diagnostic(path, 1, "file is missing")]

    helpers = [(line, code) for line, code in _python_fences(text) if "def delete_memory_by_id" in code]
    if len(helpers) < 2:
        errors.append(
            Diagnostic(
                path,
                1,
                "main and duplicated solution snippets must both define delete_memory_by_id",
            )
        )
    helper_requirements = {
        "memory_id=memory_id": "exact lookup must include memory_id",
        "user_id=user_id": "exact lookup/delete must include user_id",
        "thread_id=thread_id": "exact lookup/delete must include thread_id",
        '"type", "memory_type"': "helper must read the stored memory type",
        "raise MemoryNotFoundError": "not-found must be isolated",
        "delete_cosmos(": "helper must call delete_cosmos",
        "memory_type=memory_type": "delete_cosmos must receive the stored memory type",
    }
    for base_line, code in helpers:
        for needle, message in helper_requirements.items():
            if needle not in code:
                errors.append(Diagnostic(path, base_line, message))
        broad = re.search(r"delete_cosmos\s*\((.*?)\)", code, re.S)
        if broad and "memory_type=" not in broad.group(1):
            errors.append(
                Diagnostic(path, base_line + _line(code, broad.start()) - 1, "broadened delete_cosmos call")
            )

    endpoints = [(line, code) for line, code in _python_fences(text) if "async def delete_memory(" in code]
    if not endpoints:
        errors.append(Diagnostic(path, 1, "missing delete endpoint snippet"))
    for base_line, code in endpoints:
        required = (
            "if not thread_id:",
            "delete_memory_by_id(",
            "except MemoryNotFoundError",
            "status_code=404",
        )
        for needle in required:
            if needle not in code:
                errors.append(
                    Diagnostic(path, base_line, f"delete endpoint missing required behavior: {needle}")
                )

    for match in re.finditer(r"delete_cosmos\s*\((.*?)\)", text, re.S):
        if "memory_type=" not in match.group(1):
            errors.append(
                Diagnostic(path, _line(text, match.start()), "every delete_cosmos call must be type-aware")
            )
    return errors


def check_profile_vs_memory(root: Path) -> list[Diagnostic]:
    path, text = _read(root, "03")
    errors: list[Diagnostic] = []
    requirements = (
        ("User.preferences", "name persisted User.preferences"),
        ("authoritative", "state that persisted profile preferences are authoritative"),
        ("inferred", "distinguish inferred conversational memory"),
        ("absent", "allow inferred memory to fill absent profile values"),
        ("scoped", "allow scoped trip/conversation context"),
        ("must not override", "forbid inferred memory from overriding the persisted profile"),
    )
    for needle, message in requirements:
        errors.extend(_missing(path, text, needle, message))
    return errors


def check_trip_invariants(root: Path) -> list[Diagnostic]:
    docs = [_read(root, "02"), _read(root, "05")]
    combined = "\n".join(text for _, text in docs)
    errors: list[Diagnostic] = []
    path = docs[-1][0]
    requirements = (
        (r"authoritative", "resolve authoritative trip identity before mutation"),
        (r"\bzero\b", "clarify when zero plausible planning trips exist"),
        (r"\bmultiple\b", "clarify when multiple plausible planning trips exist"),
        (r"concrete\s+candidate", "discover a concrete candidate; do not use placeholders"),
        (r"read\s+the\s+existing", "read existing trip state before mutation"),
        (r"merge\s+only", "merge only the requested change"),
        (r"trip\s+ID", "preserve the trip ID"),
        (r"\bdates\b", "preserve dates"),
        (r"\bplanning\b", "preserve planning status"),
        (r"unrelated\s+itinerary", "preserve unrelated itinerary fields"),
        (r"\bunchanged\b", "verify the trip count is unchanged"),
        (r"\bduplicate\b", "verify no duplicate trip is created"),
    )
    for pattern, message in requirements:
        if not re.search(pattern, combined, re.I):
            errors.append(Diagnostic(path, 1, message))
    return errors


def check_non_breakfast(root: Path) -> list[Diagnostic]:
    docs = [_read(root, "02"), _read(root, "05")]
    combined = "\n".join(text for _, text in docs).lower()
    errors: list[Diagnostic] = []
    path = docs[-1][0]
    families = {
        "hotel": ("hotel",),
        "restaurant or meal": ("restaurant", "meal", "dining"),
        "activity": ("activity",),
    }
    for label, alternatives in families.items():
        if not any(value in combined for value in alternatives):
            errors.append(Diagnostic(path, 1, f"safe-mutation scenario must include {label}"))
    if "breakfast" in combined and not all(
        any(value in combined for value in alternatives) for alternatives in families.values()
    ):
        errors.append(Diagnostic(path, 1, "breakfast may be an example but cannot be the sole scenario"))
    return errors


CHECKS = {
    "pins": check_pins,
    "delete": check_delete,
    "profile-vs-memory": check_profile_vs_memory,
    "trip-invariants": check_trip_invariants,
    "non-breakfast": check_non_breakfast,
}


def _valid_module03() -> str:
    helper = """
```python
class MemoryNotFoundError(LookupError):
    pass
async def delete_memory_by_id(client, *, memory_id, user_id, thread_id):
    memories = await client.get_memories(
        memory_id=memory_id, user_id=user_id, thread_id=thread_id
    )
    memory = next((m for m in memories if m["id"] == memory_id), None)
    if memory is None:
        raise MemoryNotFoundError()
    memory_type = _memory_field(memory, "type", "memory_type")
    await client.delete_cosmos(
        memory_id, user_id=user_id, thread_id=thread_id, memory_type=memory_type
    )
```
"""
    return f"""# Memory
prompty==2.0.0b3
azure-cosmos-agent-memory==0.2.0b3
Persisted User.preferences are authoritative over inferred conversational memory.
Inferred memory may fill an absent value or scoped trip context, but it must not override the profile.
{helper}
{helper}
```python
async def delete_memory(user_id, memory_id, thread_id=None):
    if not thread_id:
        raise HTTPException(status_code=400)
    try:
        await delete_memory_by_id(client, memory_id=memory_id, user_id=user_id, thread_id=thread_id)
    except MemoryNotFoundError:
        raise HTTPException(status_code=404)
```
"""


def _valid_trip_text() -> str:
    return """# Safe existing planning trip
Resolve the authoritative identity. If zero or multiple plausible planning trips exist, clarify.
Discover a concrete candidate hotel, restaurant or meal, or activity. Read the existing trip state,
merge only the requested change, and preserve the trip ID, dates, planning status, and unrelated
itinerary fields. Verify the trip count is unchanged and no duplicate trip was created.
Breakfast is one optional meal example.
"""


def run_self_test() -> int:
    case_count = 0
    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="workshop-contract-self-test-") as raw:
        root = Path(raw)
        workshop = root / "01_exercises/workshop"
        workshop.mkdir(parents=True)

        def write(module03: str | None = None, trip: str | None = None) -> None:
            (workshop / "Module-03.md").write_text(module03 or _valid_module03(), encoding="utf-8")
            value = trip or _valid_trip_text()
            (workshop / "Module-02.md").write_text(value, encoding="utf-8")
            (workshop / "Module-05.md").write_text(value, encoding="utf-8")

        for family, checker in CHECKS.items():
            write()
            case_count += 1
            if checker(root):
                failed.append(f"{family}/positive")

            if family == "pins":
                write(module03=_valid_module03().replace("prompty==2.0.0b3", "prompty==2.0.0b2"))
            elif family == "delete":
                write(module03=_valid_module03().replace(", memory_type=memory_type", ""))
            elif family == "profile-vs-memory":
                write(module03=_valid_module03().replace("authoritative", "helpful"))
            elif family == "trip-invariants":
                write(trip=_valid_trip_text().replace("the trip ID, ", ""))
            else:
                write(trip="# Existing trip\nBreakfast is the scenario.\n")
            case_count += 1
            if not checker(root):
                failed.append(f"{family}/isolated-negative")
        if failed:
            print("SELF-TEST FAILED: " + ", ".join(failed), file=sys.stderr)
            return 1
    print(f"SELF-TEST PASS: {case_count} cases across {len(CHECKS)} rule families")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for name in CHECKS:
        parser.add_argument(f"--{name}", action="store_true")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    selected = [name for name in CHECKS if getattr(args, name.replace("-", "_"))]
    if not selected:
        raise SystemExit("select at least one check")
    errors: list[Diagnostic] = []
    root = args.root.resolve()
    for name in selected:
        errors.extend(CHECKS[name](root))
    if errors:
        for error in errors:
            print(error.render(root), file=sys.stderr)
        print(f"FAILED: {len(errors)} diagnostic(s)", file=sys.stderr)
        return 1
    print(f"PASS: {', '.join(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

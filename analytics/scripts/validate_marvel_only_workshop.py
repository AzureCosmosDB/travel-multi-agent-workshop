#!/usr/bin/env python3
"""Enforce the Marvel-only learner boundary in workshop Modules 07-09."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BEGIN = "<!-- BEGIN PRESENTER REFERENCE -->"
END = "<!-- END PRESENTER REFERENCE -->"
BOUNDARY = "Every learner exercise in this module uses the Marvel tenant and dataset."


@dataclass(frozen=True)
class Diagnostic:
    path: Path
    line: int
    message: str


FORBIDDEN = (
    (re.compile(r"(?i)\bTENANT(?:_ID)?\s*=\s*[\"']analytics[\"']"), "learner tenant selection"),
    (re.compile(r"(?i)(?:-Tenant|--tenant)\s+analytics\b"), "learner tenant command"),
    (re.compile(r"(?i)\b(?:Dataset|Tenant)\s*(?:→|=|:|to)\s*`?Analytics`?"), "learner dataset selection"),
    (re.compile(r"(?i)\bselect\s+(?:the\s+)?Analytics\s+(?:tenant|dataset)"), "learner dataset result"),
    (re.compile(r"\b[a-z0-9_-]+::model-selection\b", re.I), "tenant-qualified policy id"),
    (re.compile(r"(?i)\bcross-tenant\b"), "cross-tenant policy architecture"),
    (re.compile(r"(?i)\btenant-aware\s+(?:DAX|PBIR)\b"), "tenant-aware report implementation"),
    (re.compile(r"(?i)\bPBIR\s+(?:internals?|implementation|JSON)\b"), "PBIR implementation detail"),
    (
        re.compile(
            r"(?im)^(?=[^\n]*\b(?:PBIR|TMDL)\b)"
            r"(?=[^\n]*\b(?:architecture|deploy(?:ed|ment)?|DirectQuery|hydrat(?:e|ed|ion)|"
            r"implementation|internals?|JSON|placeholders?|semantic model|source-controlled|SSO)\b)"
            r"[^\n]+$"
        ),
        "PBIR/TMDL deployment architecture",
    ),
    (re.compile(r"(?i)\bglobal\s+model-selection\s+policy\b"), "false global-policy implication"),
)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _learner_text(path: Path, allow: bool) -> tuple[str, list[Diagnostic]]:
    text = path.read_text(encoding="utf-8")
    errors: list[Diagnostic] = []
    output: list[str] = []
    inside = False
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        stripped = line.strip()
        if stripped == BEGIN:
            if inside:
                errors.append(Diagnostic(path, number, "nested presenter reference marker"))
            inside = True
            continue
        if stripped == END:
            if not inside:
                errors.append(Diagnostic(path, number, "unmatched presenter reference end marker"))
            inside = False
            continue
        if not inside or not allow:
            output.append(line)
    if inside:
        errors.append(Diagnostic(path, len(text.splitlines()), "unclosed presenter reference marker"))
    return "".join(output), errors


def validate(root: Path, modules: list[str], allow: bool) -> list[Diagnostic]:
    errors: list[Diagnostic] = []
    for module in modules:
        path = root / f"01_exercises/workshop/Module-{module}.md"
        if not path.is_file():
            errors.append(Diagnostic(path, 1, "file is missing"))
            continue
        full = path.read_text(encoding="utf-8")
        if BOUNDARY.lower() not in "\n".join(full.splitlines()[:25]).lower():
            errors.append(Diagnostic(path, 1, "missing Marvel-only learner boundary near module start"))
        learner, marker_errors = _learner_text(path, allow)
        errors.extend(marker_errors)
        for pattern, label in FORBIDDEN:
            for match in pattern.finditer(learner):
                errors.append(Diagnostic(path, _line(learner, match.start()), f"forbidden {label}: {match.group(0)!r}"))
    return errors


def run_self_test() -> int:
    fixtures = {
        "positive": (
            f"# Module\n\n{BOUNDARY}\n\n"
            "Open and use the Power BI report; no Power BI Desktop editing is needed.\n"
        ),
        "presenter-reference": (
            f"# Module\n\n{BOUNDARY}\n{BEGIN}\nTENANT = \"analytics\"\n"
            "TravelAssistant.Report/report.pbir and its TMDL semantic model are deployed from source.\n"
            f"{END}\nLearners use TENANT = \"marvel\".\n"
        ),
        "learner-tenant": f"# Module\n\n{BOUNDARY}\nTENANT = \"analytics\"\n",
        "qualified-id": f"# Module\n\n{BOUNDARY}\nUse analytics::model-selection.\n",
        "architecture": f"# Module\n\n{BOUNDARY}\nStudy cross-tenant tenant-aware DAX.\n",
        "pbir-tmdl-architecture": (
            f"# Module\n\n{BOUNDARY}\n"
            "Provision-Fabric.ps1 deployed the source-controlled PBIR report and TMDL semantic model, "
            "hydrated their placeholders, configured DirectQuery SSO, and ran a validation query.\n"
        ),
        "marker": f"# Module\n\n{BOUNDARY}\n{BEGIN}\nTENANT = \"analytics\"\n",
    }
    expectations = {
        "positive": False,
        "presenter-reference": False,
        "learner-tenant": True,
        "qualified-id": True,
        "architecture": True,
        "pbir-tmdl-architecture": True,
        "marker": True,
    }
    failed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="marvel-only-self-test-") as raw:
        root = Path(raw)
        folder = root / "01_exercises/workshop"
        folder.mkdir(parents=True)
        for name, content in fixtures.items():
            for module in ("07", "08", "09"):
                (folder / f"Module-{module}.md").write_text(content, encoding="utf-8")
            has_errors = bool(validate(root, ["07", "08", "09"], allow=True))
            if has_errors != expectations[name]:
                failed.append(name)
    if failed:
        print("SELF-TEST FAILED: " + ", ".join(failed), file=sys.stderr)
        return 1
    print(f"SELF-TEST PASS: {len(fixtures)} cases across 5 rule families")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modules", nargs="+", choices=("07", "08", "09"))
    parser.add_argument("--allow-presenter-reference", action="store_true")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if not args.modules:
        raise SystemExit("--modules is required")
    root = args.root.resolve()
    errors = validate(root, args.modules, args.allow_presenter_reference)
    if errors:
        for error in errors:
            try:
                display = error.path.relative_to(root)
            except ValueError:
                display = error.path
            print(f"{display}:{error.line}: {error.message}", file=sys.stderr)
        print(f"FAILED: {len(errors)} diagnostic(s)", file=sys.stderr)
        return 1
    print(f"PASS: Marvel-only learner boundary for modules {', '.join(args.modules)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

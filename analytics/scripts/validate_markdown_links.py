"""Validate relative Markdown links in files or recursively supplied directories."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


INLINE_LINK = re.compile(
    r"!?\[[^\]]*\]\(\s*(?P<target><[^>]+>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)"
)
REFERENCE_DEF = re.compile(r"^\s*\[[^\]]+\]:\s*(?P<target><[^>]+>|\S+)", re.MULTILINE)
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel", "data"}
IGNORED_DIRECTORY_NAMES = {
    ".angular",
    ".azure",
    ".cache",
    ".eggs",
    ".git",
    ".gradle",
    ".hypothesis",
    ".idea",
    ".local",
    ".mypy_cache",
    ".next",
    ".nox",
    ".npm",
    ".nuxt",
    ".nyc_output",
    ".parcel-cache",
    ".pnpm-store",
    ".pytest_cache",
    ".ruff_cache",
    ".terraform",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "__pypackages__",
    "_build",
    "bower_components",
    "build",
    "cache",
    "coverage",
    "dist",
    "evidence",
    "htmlcov",
    "integration-evidence",
    "jspm_packages",
    "node_modules",
    "out",
    "playwright-report",
    "site",
    "storybook-static",
    "target",
    "temp",
    "test-results",
    "tmp",
    "venv",
    "web_modules",
    "wheels",
}


def ignored_directory(name: str) -> bool:
    normalized = name.casefold()
    return (
        normalized in IGNORED_DIRECTORY_NAMES
        or normalized.startswith((".venv-", "venv-"))
        or normalized.endswith(("-cache", "_cache", "-evidence", "_evidence"))
    )


def markdown_files(inputs: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for item in inputs:
        if item.is_dir():
            for directory, directories, filenames in os.walk(item, topdown=True):
                directories[:] = sorted(
                    name for name in directories if not ignored_directory(name)
                )
                files.update(
                    Path(directory) / filename
                    for filename in filenames
                    if Path(filename).suffix.casefold() == ".md"
                )
        elif item.is_file():
            files.add(item)
        else:
            raise FileNotFoundError(item)
    return sorted(files)


def targets(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for pattern in (INLINE_LINK, REFERENCE_DEF):
        for match in pattern.finditer(text):
            target = match.group("target").strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            found.append((text.count("\n", 0, match.start()) + 1, target))
    return found


def is_ignored(target: str) -> bool:
    if not target or target.startswith("#"):
        return True
    parsed = urlsplit(target)
    return bool(parsed.scheme and parsed.scheme.casefold() in EXTERNAL_SCHEMES) or target.startswith("//")


def resolve(source: Path, target: str) -> Path | None:
    parsed = urlsplit(target)
    path_text = unquote(parsed.path)
    if not path_text:
        return None
    candidate = Path(path_text)
    if candidate.is_absolute():
        return None
    return (source.parent / candidate).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    try:
        files = markdown_files(args.paths)
    except FileNotFoundError as exc:
        print(f"BROKEN INPUT: {exc}", file=sys.stderr)
        return 2

    broken: list[str] = []
    checked = 0
    for source in files:
        text = source.read_text(encoding="utf-8")
        for line, target in targets(text):
            if is_ignored(target):
                continue
            destination = resolve(source, target)
            if destination is None:
                continue
            checked += 1
            if not destination.exists():
                broken.append(f"{source}:{line}: {target}")

    if broken:
        print("Broken relative Markdown links:")
        for item in broken:
            print(f"  {item}")
        print(f"FAILED: {len(broken)} broken link(s) across {len(files)} Markdown file(s).")
        return 1

    print(f"PASS: {checked} relative link(s) across {len(files)} Markdown file(s); 0 broken.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "validate_markdown_links.py"
SPEC = importlib.util.spec_from_file_location("validate_markdown_links", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def run_validator(monkeypatch, *paths: Path) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), *(str(path) for path in paths)],
    )
    return validator.main()


def test_recursive_scan_prunes_generated_dependency_cache_and_evidence_directories(
    tmp_path, monkeypatch, capsys
):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("# Authored\n", encoding="utf-8")
    for relative in (
        "node_modules/package/README.md",
        ".venv-travel/Lib/package/README.md",
        ".pytest_cache/README.md",
        "run-evidence/README.md",
    ):
        markdown = docs / relative
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text("[missing](does-not-exist.md)\n", encoding="utf-8")

    assert run_validator(monkeypatch, docs) == 0
    output = capsys.readouterr().out
    assert "1 Markdown file(s)" in output
    assert "does-not-exist.md" not in output


def test_authored_broken_link_under_supplied_root_still_fails(
    tmp_path, monkeypatch, capsys
):
    docs = tmp_path / "docs"
    docs.mkdir()
    authored = docs / "guide.md"
    authored.write_text("[missing](does-not-exist.md)\n", encoding="utf-8")

    assert run_validator(monkeypatch, docs) == 1
    output = capsys.readouterr().out
    assert str(authored) in output
    assert "does-not-exist.md" in output
    assert "FAILED: 1 broken link(s) across 1 Markdown file(s)." in output


def test_explicit_markdown_file_is_validated_even_inside_ignored_directory(
    tmp_path, monkeypatch, capsys
):
    markdown = tmp_path / "node_modules" / "README.md"
    markdown.parent.mkdir()
    markdown.write_text("[missing](does-not-exist.md)\n", encoding="utf-8")

    assert run_validator(monkeypatch, markdown) == 1
    assert str(markdown) in capsys.readouterr().out

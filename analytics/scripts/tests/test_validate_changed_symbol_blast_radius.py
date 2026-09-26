from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "validate_changed_symbol_blast_radius.py"
)
SPEC = importlib.util.spec_from_file_location("validate_changed_symbol_blast_radius", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def test_python_symbol_extraction_ignores_locals():
    symbols = validator.python_symbols(
        "CONSTANT = 1\n"
        "def public_function():\n"
        "    def local_function():\n"
        "        return 1\n"
        "    return local_function()\n"
        "class Service:\n"
        "    def execute(self):\n"
        "        return 2\n"
    )

    assert [item["qualified_name"] for item in symbols] == [
        "public_function",
        "Service",
        "Service.execute",
    ]


def test_typescript_tmdl_and_pbir_symbols_are_supported():
    assert [item["name"] for item in validator.regex_symbols(
        "export class TravelService {}\nexport function buildTrip() {}\n", ".ts"
    )] == ["TravelService", "buildTrip"]
    assert [item["name"] for item in validator.regex_symbols(
        "measure 'Measured Savings' = 1\n", ".tmdl"
    )] == ["Measured Savings"]
    assert [item["name"] for item in validator.symbols_for(
        "analytics/powerbi/Test.Report/definition/pages/a/visual.json",
        '{"queryRef":"TravelAssistant Measured Savings"}',
    )] == ["TravelAssistant Measured Savings"]


def test_generic_names_do_not_become_coverage_failures(tmp_path):
    config = validator.fixture_config(tmp_path)

    assert not validator.public_symbol({"name": "result"}, config)
    assert validator.public_symbol({"name": "calculate_total"}, config)


def test_reference_classification_maps_tests_and_validators(tmp_path, monkeypatch):
    source = tmp_path / "src" / "module.py"
    test = tmp_path / "tests" / "test_module.py"
    check = tmp_path / "validators" / "check.py"
    source.parent.mkdir()
    test.parent.mkdir()
    check.parent.mkdir()
    source.write_text("def calculate_total():\n    return 1\n", encoding="utf-8")
    test.write_text("calculate_total()\n", encoding="utf-8")
    check.write_text("calculate_total()\n", encoding="utf-8")
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    config = validator.fixture_config(tmp_path)

    references = validator.references(
        {"name": "calculate_total"},
        "src/module.py",
        [source, test, check],
        config,
    )

    assert references == [
        {"path": "tests/test_module.py", "classification": "test"},
        {"path": "validators/check.py", "classification": "validator"},
    ]


def test_stale_removed_and_uncovered_changed_symbols_fail():
    production_reference = {
        "path": "src/consumer.py",
        "classification": "production",
    }
    test_reference = {
        "path": "tests/test_module.py",
        "classification": "test",
    }

    assert validator.symbol_status("removed", [production_reference], [])[0] == "Failed"
    assert validator.symbol_status("changed", [], [])[0] == "Failed"
    assert validator.symbol_status("changed", [], [test_reference]) == ("Verified", "")

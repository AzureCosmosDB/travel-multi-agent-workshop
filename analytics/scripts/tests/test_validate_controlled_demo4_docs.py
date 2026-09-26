from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "validate_controlled_demo4_docs.py"
SPEC = importlib.util.spec_from_file_location("validate_controlled_demo4_docs", SCRIPT)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def test_validator_targets_only_the_seven_durable_demo4_docs():
    assert tuple(validator.DOCS) == (
        "user",
        "demo",
        "fabric",
        "powerbi",
        "module07",
        "module08",
        "module09",
    )
    assert all(
        path.name != "presenter-handoff-talk-track.md"
        for path in validator.DOCS.values()
    )


def test_contract_groups_retain_durable_operator_and_state_coverage():
    assert validator.OPERATOR == ("user", "demo", "fabric", "powerbi")
    assert validator.MODE_DOCS == (
        "user",
        "demo",
        "powerbi",
        "module09",
    )
    assert validator.STATE_DOCS == (
        "user",
        "demo",
        "fabric",
        "powerbi",
        "module08",
        "module09",
    )


def test_sequence_checks_follow_each_durable_docs_existing_flow_language():
    assert tuple(validator.SEQUENCES) == ("user", "demo", "module09")
    assert validator.SEQUENCES["user"][0] == "## Presentation modes"
    assert validator.SEQUENCES["demo"][0] == "## Controlled preparation"
    assert validator.SEQUENCES["module09"][0] == (
        "Portal Live mode (reference solution)"
    )
    assert all(
        "Reset" in tokens[0] and "recompute" in " ".join(tokens).casefold()
        for _, tokens in validator.SEQUENCES.values()
    )


def test_cross_document_contract_checks_do_not_require_duplicate_docs():
    texts = {"first": "fixture reset", "second": "policy recompute"}

    validator.require_across(
        texts,
        ("first", "second"),
        ("fixture", "policy", "recompute"),
        "distributed contract",
    )


def test_consolidated_demo_uses_documented_bucket_and_burst_contract():
    demo = validator.DOCS["demo"].read_text(encoding="utf-8")

    assert validator.contains_all(
        demo,
        (
            "20 populated minute buckets",
            "200 Analytics turns across 20 minutes",
            "20 nano, 110 mini, and 70 premium",
        ),
    )

"""Validate the controlled Demo 4 documentation contract without requiring duplication everywhere."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCS = {
    "user": ROOT / "02_completed" / "USER_GUIDE.md",
    "demo": ROOT / "analytics" / "docs" / "demo-script.md",
    "fabric": ROOT / "analytics" / "fabric" / "README.md",
    "powerbi": ROOT / "analytics" / "powerbi" / "PowerBI_Optimization_Build_Guide.md",
    "module07": ROOT / "01_exercises" / "workshop" / "Module-07.md",
    "module08": ROOT / "01_exercises" / "workshop" / "Module-08.md",
    "module09": ROOT / "01_exercises" / "workshop" / "Module-09.md",
}

OPERATOR = ("user", "demo", "fabric", "powerbi")
MODE_DOCS = ("user", "demo", "powerbi", "module09")
STATE_DOCS = ("user", "demo", "fabric", "powerbi", "module08", "module09")
SEQUENCES = {
    "user": (
        "## Presentation modes",
        (
            "controlled Reset",
            "direct Cosmos baseline",
            "Apply the Analytics",
            "Generate",
            "recompute",
            "refresh Power BI",
        ),
    ),
    "demo": (
        "## Controlled preparation",
        (
            "Reset to baseline",
            "direct Cosmos baseline",
            "Select the Analytics",
            "Apply",
            "Generate traffic",
            "Recompute insights",
            "compare",
        ),
    ),
    "module09": (
        "Portal Live mode (reference solution)",
        ("Reset", "live/raw", "select", "Apply", "generate", "Recompute", "compare"),
    ),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def contains_all(text: str, values: tuple[str, ...]) -> bool:
    folded = re.sub(r"\s+", " ", text.casefold())
    return all(value.casefold() in folded for value in values)


def require_group(
    texts: dict[str, str], names: tuple[str, ...], values: tuple[str, ...], label: str
) -> None:
    missing = [
        name for name in names if not contains_all(texts[name], values)
    ]
    require(not missing, f"{label}: {', '.join(names)}" if not missing else f"{label}; missing {missing}")


def require_across(
    texts: dict[str, str], names: tuple[str, ...], values: tuple[str, ...], label: str
) -> None:
    combined = "\n".join(texts[name] for name in names)
    missing = [value for value in values if not contains_all(combined, (value,))]
    require(
        not missing,
        f"{label}: {', '.join(names)}" if not missing else f"{label}; missing {missing}",
    )


def require_order(text: str, tokens: tuple[str, ...], name: str, anchor: str) -> None:
    folded = text.casefold()
    cursor = folded.find(anchor.casefold())
    positions: list[int] = []
    for token in tokens:
        cursor = folded.find(token.casefold(), max(cursor, 0))
        positions.append(cursor)
        if cursor >= 0:
            cursor += len(token)
    require(
        all(position >= 0 for position in positions)
        and positions == sorted(positions),
        f"{name} documents the ordered Reset -> baseline inspection -> Analytics Apply -> Generate -> Recompute -> comparison flow",
    )


def freshen_is_prohibited(text: str) -> bool:
    folded = re.sub(r"\s+", " ", text.casefold())
    return bool(
        "never use freshen turn times" in folded
        or "freshen turn times during this controlled" in folded
        or re.search(r"do not.{0,180}freshen turn times", folded)
        or re.search(r"freshen turn times.{0,80}prohibit", folded)
    )


def main() -> None:
    missing = [str(path.relative_to(ROOT)) for path in DOCS.values() if not path.is_file()]
    require(not missing, "all seven durable controlled Demo 4 documentation files exist")
    texts = {name: path.read_text(encoding="utf-8") for name, path in DOCS.items()}
    corpus = "\n".join(texts.values())

    for name, (anchor, tokens) in SEQUENCES.items():
        require_order(texts[name], tokens, name, anchor)

    exact_values = (
        "controlled-demo4-v1",
        "controlled-demo4-after-v1",
        "2026-09-24T13:00:00Z",
        "200 turns",
        "20 minutes",
        "nano=20",
        "mini=110",
        "premium=70",
        "192 → 184 → 92 → 56",
        "29.2%",
        "city_friction",
    )
    require_across(
        texts,
        OPERATOR,
        exact_values,
        "durable operator docs collectively contain exact fixture, burst, funnel, and mix",
    )
    documented_time_profile = (
        "20 populated minute buckets",
        "200 Analytics turns across 20 minutes",
        "20 nano, 110 mini, and 70 premium",
    )
    require_group(
        texts,
        ("demo",),
        documented_time_profile,
        "consolidated demo script contains the exact baseline buckets and controlled burst shape",
    )

    reseed = ("OptimizationTurns", "Debug", "NodeExecutions", "Sessions", "Messages", "Trips")
    derived = ("OptimizationInsights", "OptimizationGovernance")
    protected = (
        "Users",
        "Memories",
        "Checkpoints",
        "ApiEvents",
        "unrelated tenants",
        "protected stores",
    )
    require_across(
        texts,
        OPERATOR + ("module09",),
        reseed + derived,
        "durable operator/workshop docs collectively contain exact mutation manifests",
    )
    require_across(
        texts,
        OPERATOR + ("module09",),
        protected,
        "durable operator/workshop docs collectively name every protected scope",
    )
    require_across(
        texts,
        OPERATOR + ("module09",),
        ("fixture-owned", "operational Trips", "session prefix", "exactly 56"),
        "durable docs protect operational Trips and scope the confirmed-trip metric",
    )
    require_across(
        texts,
        OPERATOR + ("module09",),
        ("controlled-tenant", "model-selection", "revert"),
        "durable docs retain the model-selection policy revert contract",
    )

    require_across(
        texts,
        MODE_DOCS,
        ("Portal Live mode", "Prepared Fabric / Power BI mode"),
        "durable operator/workshop docs distinguish live and prepared modes",
    )
    require_group(
        texts,
        MODE_DOCS,
        ("do not", "run the full notebook"),
        "prepared-mode docs prohibit unrehearsed full notebook execution",
    )
    for name in MODE_DOCS:
        require(freshen_is_prohibited(texts[name]), f"{name} prohibits Freshen Turn Times in controlled flow")

    require_across(
        texts,
        OPERATOR,
        ("rehears", "backup", "deterministic", "idempotent", "rollback"),
        "durable operator docs cover rehearsal, backup, deterministic rerun, and targeted rollback",
    )

    states = (
        "Not Applied · Before",
        "Policy Active · Awaiting Traffic · Before",
        "Applied · After",
        "Policy Reverted · After Traffic Captured",
    )
    require_across(
        texts,
        STATE_DOCS,
        states,
        "durable state-bearing docs collectively contain the exact four-state matrix",
    )

    invalid = (
        "incomplete",
        "missing",
        "duplicate",
        "conflicting",
        "malformed-token",
        "unknown-deployment",
        "wrong-model-mix",
        "invalid",
        "never",
        "Before",
        "After",
    )
    require_across(
        texts,
        STATE_DOCS,
        invalid,
        "durable state-bearing docs collectively reject every malformed cohort class",
    )
    require_across(
        texts,
        STATE_DOCS,
        ("Revert", "future policy behavior", "After data"),
        "durable state-bearing docs preserve captured After data on Revert",
    )

    require_across(
        texts,
        STATE_DOCS,
        ("Measured", "Projected", "Estimated", "Global", "Marvel", "Analytics", "measurement"),
        "durable state-bearing docs distinguish value labels and shared scope",
    )
    require_across(
        texts,
        ("user", "demo", "fabric", "powerbi", "module08", "module09"),
        ("memory retention", "optional", "global", "$0", "recall telemetry"),
        "durable docs establish optional/global memory and zero until recall telemetry",
    )

    require_across(
        texts,
        ("demo", "module07", "module08", "module09"),
        ("learner", "completed/reference"),
        "workshop-facing docs collectively distinguish learner and completed/reference steps",
    )
    require(
        not re.search(r"leave\s+both.{0,40}\bactive\b", corpus, flags=re.IGNORECASE | re.DOTALL),
        "no prerequisite instructs learners to leave both policies active",
    )

    historical_marker = "Historical example — not controlled Demo 4 acceptance data"
    for name, text in texts.items():
        historical_claim = re.search(
            r"(≈\s*28%|~\s*120 sessions|83 simulated turns|120 sessions engaged|106 searched)",
            text,
            flags=re.IGNORECASE,
        )
        if historical_claim:
            preceding = text[max(0, historical_claim.start() - 320) : historical_claim.start()]
            require(
                historical_marker in preceding,
                f"{name} labels retained historical figures with the exact required caveat",
            )

    forbidden = {
        "random timestamp": "random timestamp guidance",
        "all tenants measured": "all-tenant measured-savings guidance",
        "leave both active": "required dual-policy-active guidance",
    }
    for phrase, label in forbidden.items():
        require(phrase not in corpus.casefold(), f"corpus excludes {label}")

    print("Controlled Demo 4 documentation validation passed.")


if __name__ == "__main__":
    main()

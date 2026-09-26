"""Validate the source-controlled tenant-switching Power BI report and semantic model."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
REPORT = HERE / "TravelAssistantAnalyticsReport.Report" / "definition"
MODEL = HERE / "TravelAssistantAnalyticsReport.SemanticModel" / "definition"
VISUAL_FREEZE = HERE / "controlled_demo4_visual_freeze.json"
VISUAL_FIXTURE = HERE / "controlled_demo4_visual_fixture.json"
OPTIMIZATIONS_PAGE_ID = "cec777f691a5019c61b3"
OPTIMIZATIONS_PAGE = (
    REPORT
    / "pages"
    / OPTIMIZATIONS_PAGE_ID
)
OPPORTUNITY_SPEND_SUMMARY = "db56f75fd9ec24498717"
RANKED_OPPORTUNITY_TABLE = "e865a83f0dc86edb594c"
CANONICAL_RECOMMENDATION_TABLE = "815fe72b858309797e3d"
OPTIMIZATIONS_TENANT_SLICER = "c55565f335827bc5cae6"


def fail(message: str) -> None:
    raise AssertionError(message)


def measure_expression(text: str, name: str) -> str:
    match = re.search(
        rf"^\tmeasure '{re.escape(name)}' =(?P<body>.*?)(?=^\t(?:measure|column|hierarchy|partition) |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        fail(f"Missing measure: {name}")
    return match.group("body")


def git_text(commit: str, relative_path: str) -> str:
    return subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout


def git_paths(commit: str, prefix: str) -> list[str]:
    output = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit, "--", prefix],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return [line for line in output.splitlines() if line]


def git_changed_paths(commit: str, prefix: str) -> set[str]:
    output = subprocess.run(
        ["git", "diff", "--name-only", commit, "--", prefix],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return {line for line in output.splitlines() if line}


def git_untracked_paths(*prefixes: str) -> set[str]:
    output = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "-z",
            "--untracked-files=all",
            "--",
            *prefixes,
        ],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return {
        line[3:].replace("\\", "/")
        for line in output.split("\0")
        if line.startswith("?? ")
    }


def is_fixed_analytics_filter(item: dict) -> bool:
    property_name = item.get("field", {}).get("Column", {}).get("Property")
    return property_name == "tenantId" and "'analytics'" in json.dumps(item)


def filter_property(item: dict) -> str | None:
    field = item.get("field", {})
    return (
        field.get("Column", {}).get("Property")
        or field.get("Measure", {}).get("Property")
    )


def filter_comparison(item: dict) -> tuple[int | None, str | None]:
    comparison = (
        item.get("filter", {})
        .get("Where", [{}])[0]
        .get("Condition", {})
        .get("Comparison", {})
    )
    value = (
        comparison.get("Right", {})
        .get("Literal", {})
        .get("Value")
    )
    return comparison.get("ComparisonKind"), value


def without_fixed_analytics_filter(doc: dict) -> dict:
    expected = copy.deepcopy(doc)
    filter_config = expected.get("filterConfig")
    if filter_config is None:
        return expected
    filters = [
        item
        for item in filter_config.get("filters", [])
        if not is_fixed_analytics_filter(item)
    ]
    if filters:
        filter_config["filters"] = filters
    else:
        expected.pop("filterConfig", None)
    return expected


def named_tmdl_blocks(text: str) -> dict[tuple[str, str], str]:
    starts = list(
        re.finditer(
            r"^\t(?P<kind>measure|column|hierarchy|partition)\s+"
            r"(?:'(?P<quoted>[^']+)'|(?P<plain>[^=\r\n]+?))(?=\s*=|\s*$)",
            text,
            re.MULTILINE,
        )
    )
    blocks: dict[tuple[str, str], str] = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        name = (match.group("quoted") or match.group("plain")).strip()
        blocks[(match.group("kind"), name)] = text[match.start() : end]
    return blocks


def without_named_tmdl_blocks(
    text: str, omitted: set[tuple[str, str]]
) -> str:
    starts = list(
        re.finditer(
            r"^\t(?P<kind>measure|column|hierarchy|partition)\s+"
            r"(?:'(?P<quoted>[^']+)'|(?P<plain>[^=\r\n]+?))(?=\s*=|\s*$)",
            text,
            re.MULTILINE,
        )
    )
    pieces = []
    cursor = 0
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        name = (match.group("quoted") or match.group("plain")).strip()
        key = (match.group("kind"), name)
        if key in omitted:
            pieces.append(text[cursor : match.start()])
            cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def validate_visual_freeze(manifest: dict) -> None:
    baseline = manifest["baseline_commit"]
    pages_prefix = (
        "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition/pages"
    )
    baseline_paths = git_paths(baseline, pages_prefix)
    baseline_pages = [path for path in baseline_paths if path.endswith("/page.json")]
    baseline_visuals = [path for path in baseline_paths if path.endswith("/visual.json")]
    if len(baseline_pages) != manifest["preexisting_page_count"]:
        fail("Visual freeze baseline page count does not match committed HEAD")
    if len(baseline_visuals) != manifest["preexisting_visual_count"]:
        fail("Visual freeze baseline visual count does not match committed HEAD")

    for relative_path in baseline_pages:
        current_path = REPO / relative_path
        if not current_path.exists():
            fail(f"Pre-existing page was deleted: {relative_path}")
        before = json.loads(git_text(baseline, relative_path))
        after = json.loads(current_path.read_text(encoding="utf-8"))
        for field in ("name", "displayName", "width", "height"):
            if before.get(field) != after.get(field):
                fail(f"Frozen page field changed: {relative_path} /{field}")

    for relative_path in baseline_visuals:
        current_path = REPO / relative_path
        if not current_path.exists():
            fail(f"Pre-existing visual was deleted: {relative_path}")
        before = json.loads(git_text(baseline, relative_path))
        after = json.loads(current_path.read_text(encoding="utf-8"))
        for field in (
            "name",
            "position",
            "parentGroupName",
            "layout",
            "visualContainerObjects",
        ):
            if before.get(field) != after.get(field):
                fail(f"Frozen visual field changed: {relative_path} /{field}")
        before_visual = before.get("visual", {})
        after_visual = after.get("visual", {})
        for field in ("visualType", "objects", "visualContainerObjects", "syncGroup"):
            if before_visual.get(field) != after_visual.get(field):
                fail(f"Frozen visual style/type changed: {relative_path} /visual/{field}")

    allowed_slicers = manifest["allowed_new_slicers"]
    current_visuals = {
        path.relative_to(REPO).as_posix()
        for path in REPORT.glob("pages/*/visuals/*/visual.json")
    }
    new_visuals = current_visuals - set(baseline_visuals)
    expected_new_visuals = {
        (
            "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition/"
            f"pages/{page_id}/visuals/{visual_id}/visual.json"
        )
        for page_id, visual_id in allowed_slicers.items()
    }
    if new_visuals != expected_new_visuals:
        fail(
            "Only the seven declared tenant slicers may be added; "
            f"expected={sorted(expected_new_visuals)}, actual={sorted(new_visuals)}"
        )
    print(
        "VISUAL_FREEZE: "
        f"{len(baseline_pages)} pages; {len(baseline_visuals)} pre-existing visuals; "
        f"{len(new_visuals)} approved slicers; HEAD-anchored"
    )


def validate_intended_diff(path: Path) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    baseline = manifest["baseline_commit"]
    subprocess.run(
        ["git", "cat-file", "-e", f"{baseline}^{{commit}}"],
        cwd=REPO,
        check=True,
        capture_output=True,
    )

    report_prefix = "analytics/powerbi/TravelAssistantAnalyticsReport.Report/definition"
    pbir = manifest["pbir"]
    remove_paths = {
        f"{report_prefix}/{relative_path}"
        for relative_path in pbir["remove_fixed_analytics_filter"]
    }
    ranked_path = f"{report_prefix}/{pbir['ranked_feed']}"
    interaction_path = f"{report_prefix}/{pbir['interaction_file']}"
    approved_pbir = (
        remove_paths
        | {ranked_path, interaction_path}
        | set(pbir["new_slicers"])
    )
    changed_pbir = git_changed_paths(baseline, report_prefix) | git_untracked_paths(
        report_prefix
    )
    if changed_pbir != approved_pbir:
        fail(
            "PBIR changed-path set differs from intended manifest; "
            f"unapproved={sorted(changed_pbir - approved_pbir)}, "
            f"missing={sorted(approved_pbir - changed_pbir)}"
        )

    for relative_path in sorted(remove_paths):
        before = json.loads(git_text(baseline, relative_path))
        after = json.loads((REPO / relative_path).read_text(encoding="utf-8"))
        if after != without_fixed_analytics_filter(before):
            fail(
                "PBIR delta contains more than fixed Analytics filter removal: "
                f"{relative_path}"
            )

    ranked_before = without_fixed_analytics_filter(
        json.loads(git_text(baseline, ranked_path))
    )
    ranked_after = json.loads((REPO / ranked_path).read_text(encoding="utf-8"))
    ranked_filters = ranked_after.get("filterConfig", {}).get("filters", [])
    ranked_without_filters = copy.deepcopy(ranked_after)
    ranked_without_filters["filterConfig"]["filters"] = ranked_before["filterConfig"][
        "filters"
    ]
    if ranked_without_filters != ranked_before:
        fail("Ranked-feed delta contains an unapproved non-filter change")
    filter_text = json.dumps(ranked_filters)
    for required in (
        "'agent_opportunity'",
        "Opportunity Selected Tenant Row",
        "saving_usd",
    ):
        if required not in filter_text:
            fail(f"Ranked-feed filter is missing: {required}")
    if len(ranked_filters) != 3:
        fail(f"Ranked feed must have exactly three filters, found {len(ranked_filters)}")
    saving_filter = next(
        (item for item in ranked_filters if filter_property(item) == "saving_usd"),
        None,
    )
    selected_filter = next(
        (
            item
            for item in ranked_filters
            if filter_property(item) == "Opportunity Selected Tenant Row"
        ),
        None,
    )
    if not saving_filter or filter_comparison(saving_filter) != (2, "0D"):
        fail("Ranked feed saving_usd filter must compare against numeric zero")
    if not selected_filter or filter_comparison(selected_filter) != (0, "1L"):
        fail("Ranked feed selected-tenant row filter must equal numeric one")

    interaction_before = json.loads(git_text(baseline, interaction_path))
    interaction_after = json.loads(
        (REPO / interaction_path).read_text(encoding="utf-8")
    )
    expected_page = copy.deepcopy(interaction_before)
    expected_page["visualInteractions"] = interaction_before.get(
        "visualInteractions", []
    ) + pbir["approved_interactions"]
    if interaction_after != expected_page:
        fail("Optimizations page has unapproved interaction or metadata changes")

    for relative_path, expected_hash in pbir["new_slicers"].items():
        asset = REPO / relative_path
        if not asset.exists():
            fail(f"Approved tenant slicer is missing: {relative_path}")
        if hashlib.sha256(asset.read_bytes()).hexdigest() != expected_hash:
            fail(f"Approved tenant slicer content changed: {relative_path}")

    tmdl = manifest["tmdl"]
    for relative_path, specification in tmdl["new_tables"].items():
        asset = REPO / relative_path
        if not asset.exists():
            fail(f"Approved new TMDL table is missing: {relative_path}")
        if hashlib.sha256(asset.read_bytes()).hexdigest() != specification["sha256"]:
            fail(f"Approved new TMDL table content changed: {relative_path}")
        if not re.search(
            rf"^table '{re.escape(specification['table'])}'",
            asset.read_text(encoding="utf-8"),
            re.MULTILINE,
        ):
            fail(f"Approved TMDL table declaration is missing: {relative_path}")

    allowed_tmdl_paths = set(tmdl["allowed_named_objects"])
    model_path = tmdl["model"]["path"]
    semantic_prefix = (
        "analytics/powerbi/TravelAssistantAnalyticsReport.SemanticModel/definition"
    )
    expected_tmdl_changes = allowed_tmdl_paths | {model_path} | set(tmdl["new_tables"])
    changed_tmdl = git_changed_paths(
        baseline, semantic_prefix
    ) | git_untracked_paths(semantic_prefix)
    if changed_tmdl != expected_tmdl_changes:
        fail(
            "TMDL changed-path set differs from named intended semantics; "
            f"unapproved={sorted(changed_tmdl - expected_tmdl_changes)}, "
            f"missing={sorted(expected_tmdl_changes - changed_tmdl)}"
        )
    for relative_path, allowed in tmdl["allowed_named_objects"].items():
        before_blocks = named_tmdl_blocks(git_text(baseline, relative_path))
        after_blocks = named_tmdl_blocks(
            (REPO / relative_path).read_text(encoding="utf-8")
        )
        allowed_keys = {
            (kind, name)
            for kind, names in allowed.items()
            for name in names
        }
        changed_keys = {
            key
            for key in set(before_blocks) | set(after_blocks)
            if before_blocks.get(key) != after_blocks.get(key)
        }
        if changed_keys != allowed_keys:
            fail(
                f"Named TMDL delta mismatch in {relative_path}; "
                f"unapproved={sorted(changed_keys - allowed_keys)}, "
                f"missing={sorted(allowed_keys - changed_keys)}"
            )
        if without_named_tmdl_blocks(
            git_text(baseline, relative_path), allowed_keys
        ) != without_named_tmdl_blocks(
            (REPO / relative_path).read_text(encoding="utf-8"), allowed_keys
        ):
            fail(f"TMDL contains an unapproved change outside named objects: {relative_path}")
    baseline_model = git_text(baseline, model_path)
    table_name = tmdl["model"]["added_table"]
    expected_model = baseline_model.replace(
        ',"TravelAssistant Configuration"]',
        f',"TravelAssistant Configuration","{table_name}"]',
        1,
    ).replace(
        "ref table 'TravelAssistant Configuration'\n",
        "ref table 'TravelAssistant Configuration'\n"
        f"ref table '{table_name}'\n",
        1,
    )
    relationships = "".join(
        "\n"
        f"relationship {item['id']}\n"
        f"\tfromColumn: {item['from']}\n"
        f"\ttoColumn: {item['to']}\n"
        for item in tmdl["model"]["relationships"]
    )
    expected_model = expected_model.replace(
        "\nref cultureInfo en-US",
        f"{relationships}\nref cultureInfo en-US",
        1,
    )
    model_text = (REPO / model_path).read_text(encoding="utf-8")
    if model_text != expected_model:
        fail("model.tmdl contains changes beyond the named tenant table/relationships")
    print(
        "INTENDED_DIFF: exact PBIR paths/deltas and named TMDL semantics match "
        f"{path.relative_to(REPO)}"
    )


parser = argparse.ArgumentParser()
parser.add_argument("--visual-baseline", type=Path)
parser.add_argument("--write-visual-freeze", action="store_true")
parser.add_argument("--check-visual-freeze", action="store_true")
parser.add_argument("--intended-diff-manifest", type=Path)
args = parser.parse_args()

if args.write_visual_freeze:
    fail(
        "--write-visual-freeze is disabled: the freeze must remain anchored to a "
        "committed baseline, not the current working tree"
    )
if args.visual_baseline:
    fail("--visual-baseline is obsolete; use the committed freeze manifest")
if args.check_visual_freeze:
    validate_visual_freeze(json.loads(VISUAL_FREEZE.read_text(encoding="utf-8")))
if args.intended_diff_manifest:
    validate_intended_diff(args.intended_diff_manifest.resolve())


json_files = sorted(REPORT.rglob("*.json"))
for path in json_files:
    json.loads(path.read_text(encoding="utf-8"))
print(f"REPORT_JSON: parsed {len(json_files)} files")

optimization_visuals = sorted((OPTIMIZATIONS_PAGE / "visuals").glob("*/visual.json"))
agent_opportunity_visuals = []
for path in optimization_visuals:
    visual = json.loads(path.read_text(encoding="utf-8"))
    for item in visual.get("filterConfig", {}).get("filters", []):
        if (
            item.get("field", {}).get("Column", {}).get("Property") == "type"
            and "'agent_opportunity'" in json.dumps(item)
        ):
            agent_opportunity_visuals.append(path.parent.name)
            break
if set(agent_opportunity_visuals) != {
    OPPORTUNITY_SPEND_SUMMARY,
    RANKED_OPPORTUNITY_TABLE,
}:
    fail(
        "Optimizations page must contain the ranked opportunity table and its spend "
        f"summary, both filtered to type=agent_opportunity: {agent_opportunity_visuals}"
    )
if not (
    OPTIMIZATIONS_PAGE / "visuals" / OPPORTUNITY_SPEND_SUMMARY / "visual.json"
).exists():
    fail(f"Opportunity spend summary visual is missing: {OPPORTUNITY_SPEND_SUMMARY}")
ranked_opportunity = json.loads(
    (
        OPTIMIZATIONS_PAGE
        / "visuals"
        / RANKED_OPPORTUNITY_TABLE
        / "visual.json"
    ).read_text(encoding="utf-8")
)
ranked_filters = ranked_opportunity.get("filterConfig", {}).get("filters", [])
ranked_filter_text = json.dumps(ranked_filters)
for required in (
    "'agent_opportunity'",
    "saving_usd",
    "Opportunity Selected Tenant Row",
):
    if required not in ranked_filter_text:
        fail(f"Ranked opportunity table lacks required filter: {required}")
if len(ranked_filters) != 3:
    fail("Ranked opportunity table must have exactly three filters")
saving_filter = next(
    (item for item in ranked_filters if filter_property(item) == "saving_usd"),
    None,
)
selected_filter = next(
    (
        item
        for item in ranked_filters
        if filter_property(item) == "Opportunity Selected Tenant Row"
    ),
    None,
)
if not saving_filter or filter_comparison(saving_filter) != (2, "0D"):
    fail("Ranked opportunity table must filter saving_usd > 0")
if not selected_filter or filter_comparison(selected_filter) != (0, "1L"):
    fail("Ranked opportunity table must filter Opportunity Selected Tenant Row = 1")
optimization_page = json.loads(
    (OPTIMIZATIONS_PAGE / "page.json").read_text(encoding="utf-8")
)
interactions = {
    (item.get("source"), item.get("target"), item.get("type"))
    for item in optimization_page.get("visualInteractions", [])
}
for target in (OPPORTUNITY_SPEND_SUMMARY, RANKED_OPPORTUNITY_TABLE):
    required = (OPTIMIZATIONS_TENANT_SLICER, target, "DataFilter")
    if required not in interactions:
        fail(f"Optimizations tenant slicer must explicitly filter {target}")

recommendation_table_path = (
    OPTIMIZATIONS_PAGE
    / "visuals"
    / CANONICAL_RECOMMENDATION_TABLE
    / "visual.json"
)
recommendation_table = json.loads(
    recommendation_table_path.read_text(encoding="utf-8")
)
recommendation_type_filter = next(
    (
        item
        for item in recommendation_table.get("filterConfig", {}).get("filters", [])
        if item.get("field", {}).get("Column", {}).get("Property") == "type"
        and "'recommendation_card'" in json.dumps(item)
    ),
    None,
)
if not recommendation_type_filter:
    fail(
        f"Canonical recommendation table {CANONICAL_RECOMMENDATION_TABLE} "
        "must filter type=recommendation_card"
    )
print(
    f"OPTIMIZATIONS_PAGE: ranked table {RANKED_OPPORTUNITY_TABLE} filters "
    f"agent_opportunity; canonical table {CANONICAL_RECOMMENDATION_TABLE} "
    "filters recommendation_card"
)

table_files = sorted((MODEL / "tables").glob("*.tmdl"))
tables: dict[str, set[str]] = {}
for path in table_files:
    text = path.read_text(encoding="utf-8")
    table_match = re.search(r"^table (?:'([^']+)'|([^\r\n]+))", text, re.MULTILINE)
    if not table_match:
        fail(f"Missing table declaration: {path}")
    table_name = table_match.group(1) or table_match.group(2).strip()
    columns = set()
    for match in re.finditer(r"^\tcolumn (?:'([^']+)'|([^\r\n=]+))", text, re.MULTILINE):
        columns.add(match.group(1) or match.group(2).strip())
    tables[table_name] = columns

model_text = (MODEL / "model.tmdl").read_text(encoding="utf-8")
referenced_tables = {
    match.group(1) or match.group(2).strip()
    for match in re.finditer(r"^ref table (?:'([^']+)'|([^\r\n]+))", model_text, re.MULTILINE)
}
missing_tables = sorted(referenced_tables - tables.keys())
if missing_tables:
    fail(f"Referenced tables do not exist: {missing_tables}")

all_tmdl = "\n".join(path.read_text(encoding="utf-8") for path in MODEL.rglob("*.tmdl"))
dax_table_refs = set(re.findall(r"'([^']+)'\[", all_tmdl))
missing_dax_tables = sorted(dax_table_refs - tables.keys())
if missing_dax_tables:
    fail(f"DAX references missing tables: {missing_dax_tables}")

insights_text = (
    MODEL / "tables" / "TravelAssistant OptimizationInsights.tmdl"
).read_text(encoding="utf-8")
policies_text = (
    MODEL / "tables" / "TravelAssistant OptimizationPolicies.tmdl"
).read_text(encoding="utf-8")
turns_text = (
    MODEL / "tables" / "TravelAssistant OptimizationTurns.tmdl"
).read_text(encoding="utf-8")
for column in (
    "policy_status",
    "dataset_phase",
    "display_state",
    "state_valid",
    "state_reason",
    "measurement_kind",
    "measurement_scope",
    "measurement_tenant",
    "burst_version",
):
    if column not in tables["TravelAssistant OptimizationInsights"]:
        fail(f"Controlled Demo 4 semantic column missing: {column}")

dataset_phase = measure_expression(insights_text, "Demo Dataset Phase")
for required in (
    "'TravelAssistant OptimizationTurns'",
    '"gpt-5.1"',
    '"gpt-5-mini"',
    '"gpt-5-nano"',
    "_total = 200",
    "_total = 400",
    "_premium = 270",
    "_mini = 110",
    "_nano = 20",
):
    if required not in dataset_phase:
        fail(f"Dataset phase is not derived from the controlled turn manifest: {required}")
dataset_display = measure_expression(insights_text, "Demo Dataset Display State")
for required in (
    "[Demo Dataset Phase]",
    "[Demo Policy Status Raw]",
    '"Not Applied · Before"',
    '"Policy Active · Awaiting Traffic · Before"',
    '"Applied · After"',
    '"Policy Reverted · After Traffic Captured"',
):
    if required not in dataset_display:
        fail(f"Dataset display state matrix is incomplete: {required}")
demo_policy_status = measure_expression(insights_text, "Demo Policy Status Raw")
for required in (
    "'Demo Tenant'[Tenant Key]",
    '_tenant & "::model-selection"',
    "'TravelAssistant OptimizationPolicies'[id] = _policyId",
):
    if required not in demo_policy_status:
        fail(f"Demo Policy Status Raw is not tenant policy ID scoped: {required}")
if "'TravelAssistant OptimizationPolicies'[scenario]" in demo_policy_status:
    fail("Demo Policy Status Raw still looks up policy status by scenario")
for name in (
    "Recommendation Panel",
    "Recommendation Footer",
    "Recommendation State Display",
    "Selected Recommendation Status",
):
    expression = measure_expression(insights_text, name)
    for required in (
        "'Demo Tenant'[Tenant Key]",
        '"model-selection"',
        '_tenant & "::model-selection"',
        "'TravelAssistant OptimizationPolicies'[id] = _policyId",
    ):
        if required not in expression:
            fail(f"{name} does not use an exact tenant-aware policy ID: {required}")
    if "'TravelAssistant OptimizationPolicies'[scenario] = _scenario" in expression:
        fail(f"{name} still looks up policy status by scenario")
for name in ("Recommendation Panel", "Recommendation Footer", "Recommendation State Display"):
    if "[Demo Dataset Display State]" not in measure_expression(insights_text, name):
        fail(f"{name} does not use source-derived model-selection state")
if "[Demo Dataset Display State]" not in measure_expression(
    insights_text, "Opportunity State Display"
):
    fail("Opportunity State Display does not use source-derived tenant state")
active_policies = measure_expression(policies_text, "Active Policies")
for required in (
    "'Demo Tenant'[Tenant Key]",
    '_tenant & "::model-selection"',
    "'TravelAssistant OptimizationPolicies'[id] = _modelPolicyId",
    "'TravelAssistant OptimizationPolicies'[id] = \"memory-retention\"",
):
    if required not in active_policies:
        fail(f"Active Policies is not exact-ID scoped: {required}")
if "'TravelAssistant OptimizationPolicies'[scenario]" in active_policies:
    fail("Active Policies still counts policies by scenario")
for name in ("Measured Saving USD", "MS Saving USD", "MS Turns"):
    expression = measure_expression(insights_text, name)
    for required in (
        "'Demo Tenant'[Tenant Key]",
        '[type] = "optimization_result"',
        '[scenario] = "model-selection"',
        "[measurement_tenant] = _tenant",
    ):
        if required not in expression:
            fail(f"{name} is not scoped to the selected measurement tenant: {required}")
    for forbidden in ("[Demo Dataset Display State]", '"Applied · After"'):
        if forbidden in expression:
            fail(f"{name} is still gated on current policy/dataset state: {forbidden}")
measured_saving = measure_expression(insights_text, "Measured Saving USD")
if "COALESCE(" in measured_saving:
    fail("Measured Saving USD must remain BLANK when no tenant measurement exists")
if "SUM(" not in measured_saving:
    fail("Measured Saving USD must preserve a present numeric zero from SUM")
for name in ("MS Saving USD", "MS Turns"):
    if "COALESCE(" in measure_expression(insights_text, name):
        fail(f"{name} should remain blank when no tenant measurement exists")
confirmed_trips = measure_expression(turns_text, "Confirmed Trips")
for required in (
    "'Demo Tenant'[Tenant Key]",
    '"controlled-demo4-v1-"',
    "'TravelAssistant Trips'[sessionId]",
    "LEFT(",
    "LEN(_fixtureSessionPrefix)",
):
    if required not in confirmed_trips:
        fail(f"Confirmed Trips is not scoped to fixture-owned session IDs: {required}")
model_scope = measure_expression(insights_text, "Model Result Scope Label")
for required in (
    "[measurement_kind]",
    "[burst_version]",
    '" — Analytics controlled burst "',
):
    if required not in model_scope:
        fail(f"Model measured-result label is incomplete: {required}")
if (
    measure_expression(insights_text, "Memory Result Scope Label").strip()
    != '"Measured — Global memory recall telemetry"'
):
    fail("Memory result scope is not explicitly global")
for name in ("Recommendation Panel", "Recommendation Footer"):
    if "Projected saving" not in measure_expression(insights_text, name):
        fail(f"{name} does not label recommendation savings as projected")
opportunity_saving = measure_expression(insights_text, "Opportunity Saving Display")
for required in (
    "COUNTROWS('TravelAssistant OptimizationInsights')",
    '[type] = "agent_opportunity"',
    "ISBLANK(_saving)",
    "BLANK()",
):
    if required not in opportunity_saving:
        fail(f"Opportunity Saving Display ghost-row guard missing: {required}")

recommendation_saving = measure_expression(insights_text, "Recommendation Saving Display")
for required in (
    "COUNTROWS('TravelAssistant OptimizationInsights')",
    '[type] = "recommendation_card"',
    "_matchingRows = 0",
    "BLANK()",
):
    if required not in recommendation_saving:
        fail(f"Recommendation Saving Display ghost-row guard missing: {required}")

normalized_measures = (
    "Recommendation Panel",
    "Recommendation Footer",
    "Recommendation State Display",
    "Selected Recommendation Status",
)
for name in normalized_measures:
    expression = measure_expression(insights_text, name)
    compact = re.sub(r"\s+", " ", expression)
    if not re.search(
        r'IF\(\s*_rawState\s*=\s*"reverted"\s*,\s*"not_proposed"\s*,\s*_rawState\s*\)',
        compact,
    ):
        fail(f"{name} does not normalize reverted to not_proposed")

for name in ("Apply Enabled Scenario", "Revert Enabled Scenario", "Selected Action Label"):
    if "[Selected Recommendation Status]" not in measure_expression(insights_text, name):
        fail(f"{name} bypasses normalized Selected Recommendation Status")
selected_action_label = measure_expression(insights_text, "Selected Action Label")
if not re.search(
    r'"NOT_PROPOSED"\s*,\s*"NOT APPLIED"',
    re.sub(r"\s+", " ", selected_action_label),
):
    fail("Selected Action Label does not display normalized not_proposed as NOT APPLIED")

policy_text = (
    MODEL / "tables" / "TravelAssistant OptimizationPolicies.tmdl"
).read_text(encoding="utf-8")
if '"reverted", "🟡 REVERTED"' not in policy_text:
    fail("raw policy/governance reverted state was altered")
print(
    "DAX: source-derived tenant state; Analytics measured scope; projected recommendations; "
    "global memory; opportunity/recommendation ghosts blank"
)

relationships = []
for block in re.finditer(
    r"^relationship ([^\r\n]+)\s+"
    r"fromColumn: (?:'([^']+)'|([^.]+))\.(?:'([^']+)'|([^\r\n]+))\s+"
    r"toColumn: (?:'([^']+)'|([^.]+))\.(?:'([^']+)'|([^\r\n]+))",
    model_text,
    re.MULTILINE,
):
    from_table = block.group(2) or block.group(3).strip()
    from_column = block.group(4) or block.group(5).strip()
    to_table = block.group(6) or block.group(7).strip()
    to_column = block.group(8) or block.group(9).strip()
    for table, column in ((from_table, from_column), (to_table, to_column)):
        if table not in tables:
            fail(f"Relationship {block.group(1)} targets missing table {table}")
        if column not in tables[table]:
            fail(f"Relationship {block.group(1)} targets missing column {table}.{column}")
    relationships.append((from_table, from_column, to_table, to_column))
if len(relationships) != 3:
    fail(f"Expected 3 tenant relationships, found {len(relationships)}")
print(
    f"TMDL: {len(tables)} tables; {len(referenced_tables)} model refs; "
    f"{len(relationships)} valid relationships"
)

page_root = REPORT / "pages"
page_dirs = sorted(path for path in page_root.iterdir() if path.is_dir())
tenant_slicers = []
fixed_filters = []
sync_groups = set()
for page_dir in page_dirs:
    page = json.loads((page_dir / "page.json").read_text(encoding="utf-8"))
    page_slicers = []
    page_visuals = []
    for visual_path in sorted((page_dir / "visuals").glob("*/visual.json")):
        visual_doc = json.loads(visual_path.read_text(encoding="utf-8"))
        page_visuals.append((visual_path, visual_doc))
        for item in visual_doc.get("filterConfig", {}).get("filters", []):
            property_name = item.get("field", {}).get("Column", {}).get("Property")
            if property_name == "tenantId" and "'analytics'" in json.dumps(item):
                fixed_filters.append(str(visual_path.relative_to(REPORT)))

        visual = visual_doc.get("visual", {})
        projections = (
            visual.get("query", {})
            .get("queryState", {})
            .get("Values", {})
            .get("projections", [])
        )
        is_tenant_slicer = visual.get("visualType") == "slicer" and any(
            projection.get("field", {})
            .get("Column", {})
            .get("Expression", {})
            .get("SourceRef", {})
            .get("Entity")
            == "Demo Tenant"
            and projection.get("field", {}).get("Column", {}).get("Property") == "Tenant"
            for projection in projections
        )
        if not is_tenant_slicer:
            continue
        selection = visual.get("objects", {}).get("selection", [])
        single_select = any(
            item.get("properties", {})
            .get("singleSelect", {})
            .get("expr", {})
            .get("Literal", {})
            .get("Value")
            == "true"
            for item in selection
        )
        if not single_select:
            fail(f"Tenant slicer is not single-select: {visual_path}")
        if "'Analytics'" not in json.dumps(visual.get("objects", {}).get("general", [])):
            fail(f"Tenant slicer does not default to Analytics: {visual_path}")
        sync_group = visual.get("syncGroup", {})
        if not (
            sync_group.get("groupName") == "demo-tenant"
            and sync_group.get("filterChanges") is True
            and sync_group.get("fieldChanges") is True
        ):
            fail(f"Tenant slicer sync metadata is invalid: {visual_path}")
        sync_groups.add(sync_group["groupName"])
        page_slicers.append(visual_doc["name"])
    if len(page_slicers) != 1:
        fail(f"{page.get('displayName')} has {len(page_slicers)} tenant slicers")
    slicer_path, slicer_doc = next(
        item for item in page_visuals if item[1]["name"] == page_slicers[0]
    )
    slicer_position = slicer_doc["position"]
    for other_path, other_doc in page_visuals:
        if other_path == slicer_path:
            continue
        other_position = other_doc.get("position", {})
        overlaps = (
            slicer_position["x"] < other_position.get("x", 0) + other_position.get("width", 0)
            and slicer_position["x"] + slicer_position["width"] > other_position.get("x", 0)
            and slicer_position["y"] < other_position.get("y", 0) + other_position.get("height", 0)
            and slicer_position["y"] + slicer_position["height"] > other_position.get("y", 0)
        )
        if overlaps:
            fail(
                f"Tenant slicer overlaps {other_path.relative_to(REPORT)} "
                f"on {page.get('displayName')}"
            )
    tenant_slicers.append((page.get("displayName"), page_slicers[0]))

if fixed_filters:
    fail(f"Hidden tenantId=analytics visual filters remain: {fixed_filters}")
print("FILTERS: 0 visual-level tenantId=analytics filters")
print(
    f"SLICERS: {len(tenant_slicers)}/{len(page_dirs)} pages; "
    "single-select; default Analytics; sync group demo-tenant; no overlaps"
)
for page_name, visual_name in tenant_slicers:
    print(f"  {page_name}: {visual_name}")

fixture = json.loads(VISUAL_FIXTURE.read_text(encoding="utf-8"))
fixture_rows = fixture["insights"]
expected_ranked = {
    "analytics": [
        {
            "tenant": "analytics",
            "saving_usd": 18.176147,
            "state": "active",
            "title": "Model selection opportunity",
        }
    ],
    "marvel": [
        {
            "tenant": "marvel",
            "saving_usd": 13.17991,
            "state": "not_proposed",
            "title": "Model selection opportunity",
        }
    ],
    "no-opportunity": [],
}
for tenant in fixture["selected_tenants"]:
    ranked_rows = [
        {
            "tenant": row["tenant"],
            "saving_usd": row["saving_usd"],
            "state": row["state"],
            "title": row["title"],
        }
        for row in fixture_rows
        if row.get("tenant") == tenant
        and row.get("type") == "agent_opportunity"
        and row.get("saving_usd", 0) > 0
    ]
    if ranked_rows != expected_ranked[tenant]:
        fail(f"Visual-shaped ranked rows are incorrect for {tenant}: {ranked_rows}")
    if any(row["tenant"] != tenant for row in ranked_rows):
        fail(f"Ranked opportunity state/saving leaked across tenants for {tenant}")
    print(
        f"VISUAL_ROWS[{tenant}]: {len(ranked_rows)} "
        f"{json.dumps(ranked_rows, sort_keys=True)}"
    )


def measured_fixture_value(tenant: str) -> float | None:
    values = [
        row["saving_usd"]
        for row in fixture_rows
        if row.get("type") == "optimization_result"
        and row.get("scenario") == "model-selection"
        and row.get("measurement_tenant") == tenant
    ]
    return sum(values) if values else None


analytics_measured = measured_fixture_value("analytics")
marvel_measured = measured_fixture_value("marvel")
zero_measured = measured_fixture_value("zero-saving")
if analytics_measured != 2.8005:
    fail("Completed Analytics measurement was not retained after policy revert")
if marvel_measured is not None:
    fail("Missing Marvel measurement must remain BLANK")
if zero_measured != 0:
    fail("A present zero-saving measurement must remain numeric zero")
print(
    "MEASURED_SAVING: "
    f"analytics={analytics_measured}; marvel=BLANK; zero-saving={zero_measured}"
)

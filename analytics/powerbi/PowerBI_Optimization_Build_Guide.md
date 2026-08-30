# Power BI Analytics Report Maintainer Guide

`TravelAssistantAnalyticsReport` is the Power BI companion to the web analytics portal. It is
source-controlled as PBIR/TMDL and deployed by the Fabric provisioner; a checked-in PBIX is no
longer used.

## Source layout

- `TravelAssistantAnalyticsReport.Report/` — PBIR report definition and seven report pages.
- `TravelAssistantAnalyticsReport.SemanticModel/` — TMDL DirectQuery semantic model.
- `../fabric/provision_fabric.py` — hydrates deployment-specific values, creates or updates both
  Fabric items, binds DirectQuery SSO, and validates the deployed model.
- `../fabric/udf/optimization_policy_functions.py` — Fabric User Data Function used by the
  Optimizations page's Apply and Revert buttons.

Do not put live workspace, semantic-model, UDF, mirror, or SQL endpoint identifiers into source.
The definitions intentionally contain these placeholders:

```text
{{MIRROR_SQL_ENDPOINT}}
{{MIRROR_DATABASE}}
{{FABRIC_WORKSPACE_NAME}}
{{FABRIC_WORKSPACE_ID}}
{{FABRIC_SEMANTIC_MODEL_ID}}
{{FABRIC_UDF_ID}}
```

## Report pages

The report has seven pages, in this order:

1. **Portfolio Overview** — portfolio KPIs, optimization summary, model distribution, and activity.
2. **Optimizations** — measured spend, ranked opportunities, data-driven recommendations,
   selected-recommendation detail, and state-aware Apply/Revert actions.
3. **Model Selection** — model distribution, trivial-turn share, baseline vs actual cost,
   complexity-tier cost, and volume projections.
4. **Memory** — memory KPIs, type and health distributions, and salience distribution.
5. **Agents** — per-agent scorecard and agent-path cost detail.
6. **Business** — conversion funnel, conversion KPI, biggest leak, and abandonment causes.
7. **Governance** — current policies, SLO gate, measured savings, cost comparison, and decision
   history.

Keep this page order aligned with Module 09 screenshots and instructions.

## Data contract

The semantic model uses DirectQuery over the Fabric mirrored database. Raw operational visuals
read mirrored tables such as:

- `OptimizationTurns`
- `Trips`
- `OptimizationPolicies`
- `OptimizationGovernance`
- `Configuration`

Computed visuals read flat rows from `OptimizationInsights`. The main row types are:

| Row type | Used for |
|---|---|
| `turn_metrics` | Portfolio and model-selection KPIs |
| `funnel_stage`, `abandonment_cause`, `conversion_kpi` | Business page |
| `agent_path_cost`, `agent_scorecard`, `agent_opportunity` | Agents and Optimizations pages |
| `recommendation_card` | Dynamic recommendation master-detail experience |
| `slo_policy`, `slo_metric` | Governance SLO display |
| `optimization_result` | Measured savings and baseline-vs-actual cost |
| `memory_kpi`, `memory_type`, `memory_health`, `memory_salience` | Memory page |

Fabric's mirrored SQL schema may not immediately expose properties first introduced on newer
Cosmos documents. Producers therefore project report values into established sparse columns and
always filter measures by `type`. Keep the notebook generator and
`02_completed/python/src/app/services/optimization_insights.py` aligned when changing this
contract.

## Data-driven recommendations and actions

The Optimizations page uses a native Power BI master-detail pattern:

1. A table lists every `recommendation_card` row.
2. Selecting a row sets the scenario context.
3. Measures populate the detail panel.
4. Standalone data-function buttons pass the selected scenario to the UDF.

Power BI does not support embedding a Fabric data-function button in each native Table/Matrix
row. Do not replace the standalone buttons with fixed scenario cards; that would stop newly
reverse-ETL'd recommendations from appearing automatically.

Apply/Revert state is resolved from the live `OptimizationPolicies` table when a matching policy
exists, with the recommendation snapshot as the fallback. This keeps the button state tied to the
operational source of truth:

- active policy: Apply disabled, Revert enabled;
- not applied or reverted: Apply enabled, Revert disabled;
- manual or diagnostic recommendation: both disabled.

The UDF performs only a scoped, reversible policy-state write. Synthetic traffic, insight
recomputation, timestamp maintenance, and baseline reset remain web/API or notebook operations.

## Editing workflow

Prefer Power BI Desktop's PBIP project mode or Fabric's source-aware editing workflow:

1. Work from the PBIR/TMDL directories, not a tenant-bound PBIX export.
2. Preserve the placeholder values in committed source.
3. Keep visual changes within the existing dark theme and validate at the report's target canvas
   size.
4. Check long labels, table density, selection behavior, and the absence of visual scrollbars
   before publishing.
5. If a model measure changes, validate both its unfiltered result and the page-specific filter
   context.

Service-exported PBIX files may inherit tenant sensitivity protection and are not a portable
deployment artifact. The source directories are the canonical report.

## Deployment

From the repository root:

```powershell
.\analytics\fabric\Provision-Fabric.ps1 -Phase 3
```

Or call the Python provisioner directly:

```powershell
python analytics\fabric\provision_fabric.py --phase report
```

The provisioner:

1. resolves the workspace, mirror, UDF, and report/model configuration;
2. hydrates placeholders in memory;
3. creates or updates the semantic model and report;
4. binds DirectQuery SSO; and
5. runs a DAX validation query.

Deployment fails if validation fails.

`--report` and `--pbit` remain explicit compatibility overrides for external binary artifacts,
but they are not the workshop's default or source of truth.

## Validation checklist

- PBIR files parse as JSON.
- TMDL contains no unresolved deployment placeholders after hydration.
- The deployed DAX validation query returns `OptimizationInsights` rows.
- All seven pages render without clipped text or unexpected scrollbars.
- Selecting different recommendation rows updates the detail panel.
- Apply/Revert enablement matches `OptimizationPolicies.status`.
- Applying and reverting `model-selection` writes a new policy version and audit entry.
- Module 09 screenshots and page descriptions still match the deployed report.

## Power BI limitations reflected in the design

- Data-function actions must be standalone buttons; they cannot repeat inside native table rows.
- Native legends do not show category, value, and percentage together, so companion tables are
  used where all three are needed.
- Native Table/Matrix conditional formatting is used for state, apply mode, and SLO indicators.
- Power BI owns scoped policy Apply/Revert actions; broad demo-maintenance actions stay outside the
  report.

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

The semantic model includes the calculated `Demo Tenant` dimension (`Analytics`, `Marvel`) with
one-to-many relationships to `OptimizationTurns.tenantId`, `Trips.tenantId`, and
`OptimizationInsights.Report Tenant Key`. The DirectQuery partition duplicates only the reserved
`_global_optimizations` and `_global_memory` rows once per demo tenant key, so shared measured
savings and memory intelligence remain visible under either slicer selection. Policy state is
evaluated for the selected tenant.

Every page has the same synchronized, single-select **Tenant** slicer. Its committed default is
**Analytics**. Keep the slicers in the `demo-tenant` sync group and do not reintroduce hidden
visual-level `tenantId = analytics` filters.

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

## Controlled Demo 4 operating contract

Power BI is an observation and optional policy-writeback surface; it does not own controlled reset,
traffic generation, or recomputation.

### Portal Live mode

1. Create a complete pre-mutation backup of all affected Marvel and Analytics rows and their
   existing model-selection policies.
2. Run controlled Reset with fixture `controlled-demo4-v1`. Reseed exactly
   `OptimizationTurns`, `Debug`, `NodeExecutions`, `Sessions`, `Messages`, and fixture-owned
   `Trips`; preserve operational Trips without a controlled fixture session prefix; clear
   tenant-derived `OptimizationInsights` and `OptimizationGovernance`; revert the existing
   controlled-tenant model-selection policies; preserve `Users`, `Memories`, `Checkpoints`,
   `ApiEvents`, unrelated tenants, and protected stores.
3. Inspect live/raw baseline while derived rows are absent. Both tenants must have 200 all-premium
   turns across 20 populated minute buckets and funnel `192 → 184 → 92 → 56`, `29.2%`, with
   `city_friction` the largest cause.
   `[Confirmed Trips]` filters fixture-owned session IDs and remains exactly 56; operational
   confirmed Trips remain available to the travel app.
4. Select Analytics and Apply the existing model-selection control.
5. Generate Analytics-only `controlled-demo4-after-v1` at inclusive
   `2026-09-24T13:00:00Z`, 200 turns over 20 minutes, nano=20, mini=110, premium=70.
6. Explicitly Recompute and compare frozen Marvel Before with Analytics After.

Do not use **Freshen Turn Times** in this flow. Reset and burst reruns are deterministic and
idempotent. A repeated run recreates stable IDs and repairs partial data. Targeted rollback restores
only the complete backup and restores the policy through its lifecycle service.

### Prepared Fabric / Power BI mode

Prepare and validate the snapshot off-stage. Do not reset, apply/revert, generate traffic, use
Freshen Turn Times, or run the full notebook on stage unless that exact action was separately
rehearsed.

### Required semantic states

| Source data | Global policy | Exact label |
|---|---|---|
| Marvel all-premium | active or reverted | `Not Applied · Before` |
| Analytics all-premium | active | `Policy Active · Awaiting Traffic · Before` |
| Complete Analytics burst | active | `Applied · After` |
| Complete Analytics burst | reverted | `Policy Reverted · After Traffic Captured` |

Incomplete, missing, duplicate, conflicting, malformed-token, unknown-deployment, or
wrong-model-mix expected rows are invalid, never a successful Before/After. Revert affects future
policy behavior, not captured After data.

The controlled Analytics burst result is **Measured**. Recommendation/card/volume values are
**Projected** or **Estimated**. Policy, memory, and shared scope are **Global** where applicable.
A shared measured result visible under Marvel must identify Analytics measurement while Marvel
remains Before. Memory retention is an optional extension, not a Demo 4 prerequisite; its
measured saving remains `$0` until actual recall telemetry exists.

## Presenter flow

This report is used in Demo 5, after the frontend, Cosmos/mirroring/SQL endpoint, notebook, and
`optimization-apply-loop` User Data Function demonstrations. Prepare:

- **Browser instance:** Fabric.
- **Tabs:** Power BI report and User Data Function.
- **Locations:** Portfolio Overview, Optimizations, and the UDF apply, revert, and internal
  status-write functions.

In Portal Live mode, refresh the report only after direct Cosmos validation, explicit recompute,
and mirror convergence. In Prepared Fabric / Power BI mode, use the validated snapshot and do not
reset, apply/revert, generate traffic, freshen timestamps, or run the full notebook on stage.

`azd up` may create or idempotently ensure initial seed data. It never invokes controlled reset or
silently restages an existing presentation.

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
- All seven Tenant slicers are visible, single-select, default to Analytics, and share the
  `demo-tenant` sync group.
- No visual has a hidden hardcoded `tenantId = analytics` filter.
- Every TMDL table reference and relationship endpoint resolves to an existing table/column.
- TMDL contains no unresolved deployment placeholders after hydration.
- The deployed DAX validation query returns `OptimizationInsights` rows.
- All seven pages render without clipped text or unexpected scrollbars.
- Selecting different recommendation rows updates the detail panel.
- Apply/Revert enablement matches `OptimizationPolicies.status`.
- Applying and reverting `model-selection` writes a new policy version and audit entry.
- Controlled state labels match the four-state matrix above and invalid cohorts never resolve to
  successful Before/After.
- The shared measured result remains Analytics-scoped under the Marvel slicer.
- Module 09 screenshots and page descriptions still match the deployed report.

## Power BI limitations reflected in the design

- Data-function actions must be standalone buttons; they cannot repeat inside native table rows.
- Native legends do not show category, value, and percentage together, so companion tables are
  used where all three are needed.
- Native Table/Matrix conditional formatting is used for state, apply mode, and SLO indicators.
- Power BI owns scoped policy Apply/Revert actions; broad demo-maintenance actions stay outside the
  report.

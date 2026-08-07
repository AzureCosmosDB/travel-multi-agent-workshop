# Power BI build notes (maintainer / agent reference)

Hard-won gotchas from building the optimization report against the Fabric mirror. This is
**not** attendee-facing content — it's kept out of `PowerBI_Optimization_Build_Guide.md` on
purpose (that guide is concise, first-timer instructions). Put build-time reasoning here so
humans and agents can find it later without cluttering the learning content.

## Connection / schema
- **Auth must be Microsoft/Entra ("Microsoft account" tab), not Windows.** Windows auth throws
  `Microsoft SQL: Integrated Security not supported.` Fix: File → Options → Data source settings →
  Clear Permissions, reconnect with Microsoft account. (This one *is* in the guide — attendees hit it.)
- **Mirror table schema = the Cosmos DB name** (e.g. `TravelAssistant`), not `dbo`. Power BI's
  navigator names each model table `<schema> <table>` → `TravelAssistant OptimizationTurns`.

## Time axis
- **Use `turn_epoch` / `updated_epoch`, never Cosmos `_ts`.** For the offline seed every row is
  written at once, so `_ts` collapses all turns into ~one minute (flat line). `turn_epoch` is the real
  per-turn time (epoch seconds derived from `timeStamp`) and works for live traffic too.
- **Float division (`/ 86400.0`, `/ 1440`).** In DirectQuery this folds to T-SQL; `bigint / bigint` is
  integer division and truncates the time-of-day to midnight, so time filters show nothing.
- `timeStamp` is ISO-8601 **text** — don't put it on a time axis directly.

## Trivial definition
- Canonical = the classifier's output **`complexity_tier == "trivial"`** (from `classify_complexity_tier`).
  The original `handoff_count == 0 AND output_tokens < 60` was a pre-optimization proxy on the old
  gpt-4.1-mini baseline; the shipped gpt-5.1 seed is ~23% trivial by `complexity_tier`.

## Renaming model tables (dropping the `V2`/schema prefix) without breaking the report
- **Do it with Power BI Desktop's native rename** (Fields pane / Model view → double-click). It
  cascades the new name into every measure, calculated column, relationship, **and report visual**.
- **Do NOT use Tabular Editor for the rename** — it edits the model only, leaving report visuals bound
  to the old names (broken visuals).
- **TMDL view find/replace fails** on renames: `createOrReplace` matches by name, so a renamed block
  with the same `lineageTag` collides ("object with lineage-tag … already exists"). Apply rolls back.
- After a rename, DAX IntelliSense can be **stale** (autocomplete still shows the old name) even though
  the rename applied — save/reopen to refresh. Renames don't propagate while a table is in an **error
  state**, so fix data errors first.

## Empty tables
- Fabric mirroring derives a table's columns from actual data. A container with **0 rows** mirrors a
  table with **no columns**, so DAX like `[status]` errors. Seed at least one row (e.g. the active
  `model-selection` policy) so the columns exist.

## Sensitivity labels
- A Microsoft Purview sensitivity label (inherited from the Fabric source) can be applied to the
  `.pbix`. Before **Save As → .pbit**, set it to a non-encrypting/public label (Home → Sensitivity) or
  remove it, or external users may be unable to open the template.

## Adding a table to an already-running mirror (e.g. `Configuration`)
- The mirror's mounted-table list is fixed at creation. `provision_fabric.update_mirror_tables()`
  adds any missing `MIRROR_TABLES` to the definition (`updateDefinition`), but a **running** Cosmos
  mirror does **not** pick up a newly-mounted table until mirroring is **stopped and started** —
  `get_or_create_mirror` now calls `_restart_mirroring()` when it adds tables. Symptom if you skip
  the restart: `getTablesMirroringStatus` keeps showing only the original tables.
- After the restart, all tables re-snapshot (`Snapshotting` → `Replicating`); `Configuration` shows
  4 rows (3 `model_pricing` + 1 `model_selection_defaults`).
- The mirror's **SQL analytics endpoint** surfaces the new table automatically, but its metadata can
  lag — hit **Refresh** on the SQL endpoint in the Fabric portal if `Configuration` isn't yet visible
  in Power BI's navigator.

## Adding `NodeExecutions` to the mirror (agent scorecard, Page 6b)
- `NodeExecutions` (per-agent node-grain that feeds the agent scorecard) is in `MIRROR_TABLES`. On a
  **fresh** deploy it mirrors automatically. On an **existing** deploy, add it the same way as
  `Configuration` above:
  - **Automated:** re-run `.\Provision-Fabric.ps1 -ConnectionId <your-connection-id>` (or
    `python provision_fabric.py --phase 2 --connection-id <id>`). `get_or_create_mirror` detects
    `NodeExecutions` is missing, `update_mirror_tables` mounts it, and `_restart_mirroring` stops/starts
    so the running mirror re-snapshots it.
  - **Portal fallback:** open the mirrored database → **Manage/Configure replication** → add
    `NodeExecutions` → **Stop** then **Start** mirroring → **Refresh** the SQL endpoint.
- **Prerequisite:** the Cosmos `NodeExecutions` container must exist and hold data first
  (`python data/seed_data.py` seeds it via `seed_node_executions`; live turns also populate it). After
  the restart it re-snapshots (`Snapshotting` → `Replicating`); then the Module 09 notebook's agent
  scorecard section can read it.

> **`ApiEvents` + `OptimizationGovernance` are mirrored the same way.** Both were added to
> `MIRROR_TABLES` (and `OptimizationGovernance` to the Bicep), so the **same re-run/restart adds all
> three at once**. Rationale (scale): high-volume telemetry is computed in the **analytics plane**,
> not scanned from operational Cosmos — the notebook aggregates `ApiEvents` (`recall_pruned_avoided`
> → the memory-retention saving) and `NodeExecutions` (the agent scorecard) over the mirror.
> `OptimizationGovernance` (the C1–C5 decision audit) is mirrored so the report can show the same
> governance trail the console does.

## Pointing an existing report at `Configuration` pricing (migrating off the old CSV)
An earlier build loaded pricing from `model_pricing.csv` as a `ModelPricing` table. To switch a
report that already has that:
1. **Add the table:** Home → **Transform data** (or **Get data** → your mirror SQL endpoint) →
   Navigator → schema `TravelAssistant` → check **`Configuration`** → Load. It arrives as
   `'TravelAssistant Configuration'`.
2. **Replace `Est Cost USD`** with the `LOOKUPVALUE(... 'TravelAssistant Configuration' ... [type],
   "model_pricing" ...)` version in `PowerBI_Optimization_Build_Guide.md` (Step 3). No relationship
   is needed — `LOOKUPVALUE` doesn't require one.
3. **Remove** the old `ModelPricing` CSV query (Transform data → right-click → Delete) so there's no
   stale second source.
4. **Refresh**. `Est Cost USD` should be unchanged (same numbers, now from the mirror).

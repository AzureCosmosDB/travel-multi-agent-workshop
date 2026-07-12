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
- Canonical = the classifier's output **`model_tier == "trivial"`** (from `classify_turn_tier`).
  The original `handoff_count == 0 AND output_tokens < 60` was a pre-optimization proxy on the old
  gpt-4.1-mini baseline; the shipped gpt-5.1 seed is ~23% trivial by `model_tier`.

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

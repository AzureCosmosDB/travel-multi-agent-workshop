# ADR-0009: Align the product (report + Console) with the general optimization framework

- **Status:** Proposed
- **Date:** 2026-07-31
- **Deciders:** Mark Brown (@markjbrown), with agent analysis
- **Related:** `../vision/agent-analytics-and-optimization-vision.md`, `../optimization-scenarios/README.md`, `adr-0001-optimization-loop-surface-architecture.md`, `adr-0008-optimization-apply-loop-model-selection.md`, `../../PowerBI_Optimization_Build_Guide.md`

## Context

Reviewing the shipped Power BI report and Optimization Console (PR #73), the owner flagged that the
analytics "feels disjointed and does not really live up to the vision of a **generalized** analytics
and optimization framework for [multi-agent] applications" — the stated north-star (teach a general
framework *and* how to build it), not a single-app showcase.

The critical finding: **the framework already exists and is rigorous — the product surfaces just
drifted from it.** The generalized "what to measure" backbone the owner is reaching for is already
documented:

- **`optimization-scenarios/README.md`** defines the **eight optimization dimensions** (agent
  quality, workflow efficiency, memory effectiveness, routing, tool utilization, model selection,
  cost efficiency, business outcomes) — each with its primary signal and safe fix seam — plus a
  **scenario catalog** where every SCEN-NNN is **tagged to dimension(s)**, fix seam, risk domain,
  and maturity ceiling; **discovery methods** for finding new scenarios; a **classification schema**;
  and a coverage goal (≥1 scenario per dimension).
- **The vision** (`vision/agent-analytics-and-optimization-vision.md`) frames the two tiers
  (analytical questions → actions) and the Cosmos-operational / Fabric-analytical split.
- **ADR-0001** defines the loop seam (generate/recommend = analytical; apply/act = operational) and
  the maturity + risk models.

So the scenarios (`model-selection`, `memory-retention`, `tool-call-dedup`) are **not** meant to be a general framework — they are **worked examples,
instances of dimensions**, discovered by exploration (data-first mining / behavioral probes / naive
UI use). The owner's instinct — "these aren't something you can apply as a general framework" — is
correct *and already the documented intent*. The problem is that **the report and Console don't
embody that structure**, so a reader can't tell the framework from the examples.

### What "drifted" concretely

The report/Console grew around **SCEN-007 (model selection)** — the easiest dimension to quantify —
and inherited generic-sounding names that overclaim generality:

| Surface today | What it actually shows | Problem |
|---|---|---|
| Page: **Optimization Overview** | trivial-% (×2) + model-usage donut | It's a *model-selection baseline*, not a portfolio overview across the 8 dimensions. |
| Page: **Optimization Opportunity** | the model-selection pitch (gauge + recommendation) | Reads as "all opportunities"; it's one dimension. |
| Page: **Cost by Tier** | cost/cache-hit by tier | Fine — but the field `complexity_tier` is really the **task's** difficulty tier, not a property of the model. |
| Page: **Applied Optimizations** | read-only policy log + one Apply button | Should be the **apply/revert surface** (parity with the Console), not a static table. |
| Page: **Measured Savings** | scenario-switchable before/after | ✅ Already framework-general (the one page that is). |
| Console cards | 6 detected recommendations (4 applyable + 2 lenses) | No visible mapping to the 8 dimensions or the SCEN-NNN catalog. |

Two further issues surfaced:

1. **No "portfolio" surface.** Nothing in the product answers *"across the 8 dimensions, which are
   covered, which have detected opportunities, which are applied, and what has each saved?"* — which
   is the generalized story. The dimension backbone lives only in docs.
2. **Terminology drift.** The product/docs use two groupings of the same space: **"six analytics
   pillars"** (ADR-0001, charter) vs **"eight optimization dimensions"** (scenarios README,
   Module-07). One canonical taxonomy is needed so the framework reads coherently.

## Decision drivers

- Teach a **general framework** (dimensions × maturity × risk × measurement × the loop), using the
  scenarios as **instances** — not a model-selection showcase.
- **Honest naming**: no surface should imply generality it doesn't have.
- Make the **8 dimensions the explicit backbone** across report, Console, and data (dimension-tagged
  rows), so "what to measure" is legible and **new scenarios slot into a dimension**.
- Preserve the working reverse-ETL loop and the operational/analytical seam (ADR-0001) — this is
  alignment, not re-architecture.
- Scope discipline: PR #73 landed the loop; a full realignment is its own effort.

## Options considered

### Option A — Leave as-is
The report works and demos well. **Verdict:** rejected — it misrepresents the framework as a
model-selection tool and buries the generalizable IP the workshop is meant to teach.

### Option B — Rename-only (cosmetic)
Rename the overclaiming pages/fields; change nothing structural. **Verdict:** partial — necessary
but insufficient; it fixes honesty but not the missing dimension backbone / portfolio view.

### Option C — Full product alignment to the documented framework (phased)
Make the report + Console + insight rows mirror `optimization-scenarios/README.md`: dimensions as the
backbone, scenarios as dimension-tagged instances, a portfolio/coverage view, and honest per-scenario
naming. **Verdict:** chosen, **phased** so the low-risk clarity fixes can ship with/near #73 and the
structural work is a deliberate follow-up.

## Evidence

- Framework already documented: `optimization-scenarios/README.md` (8 dimensions table L29–38;
  catalog with dimension tags L155–164; discovery methods L128–141; coverage goal L166–172).
- Report is model-selection-centric: `PowerBI_Optimization_Build_Guide.md` Pages 1–3 are all the
  model-selection story; Page 5 (Measured Savings) is the only scenario-general page.
- Console cards vs report (live, 2026-07-31, deployed 02): Console returns 6 cards
  (`model-selection`, `memory-retention`, `tool-call-dedup`,
  `cost-per-outcome`, `agent-path-cost`); `OptimizationPolicies` has 2 (`model-selection` active,
  `tool-call-dedup` staged); `optimization_result` has the 4 applyable scenarios. Confirms
  the surfaces show different loop stages and that lenses never become policies.
- Terminology drift: "six pillars" (ADR-0001) vs "eight dimensions" (scenarios README, Module-07).
- Scenario mix is intentional per the catalog: prompt-fix (specific, prompt, L3 ceiling) vs
  SCEN-004/007 (policy, L4/L5) — the catalog deliberately spans both, tagged by dimension.

## Decision

Adopt the **eight optimization dimensions as the explicit backbone** of the product, and treat the
wired scenarios as **dimension-tagged worked examples**. Phase the work:

**Phase 1 — clarity (low-risk, ship with/near #73):**
- Rename overclaiming report pages so they don't imply generality: **Optimization Overview →
  "Model Selection — Baseline"**, **Optimization Opportunity → "Model Selection — Opportunity"**.
  Keep **Cost by Tier**, **Measured Savings**, and **Memory Intelligence**. (Display-name only — no
  data/field changes.)
- Frame **Applied Optimizations** as the apply/revert surface (parity with the Console) in the docs.
- Reconcile the taxonomy: **canonical term = "the eight optimization dimensions."** Active/learner
  surfaces (Module 07, scenarios catalog, report, Console, USER_GUIDE) use "dimensions"; the older
  "six pillars" wording is left **as-is in the frozen vision doc and Accepted ADRs** (ADR process:
  don't rewrite history) — new content uses "dimensions."

**Phase 2 — the generalized framework in-product (follow-up design + PR):**
- **`complexity_tier → task_tier`** (a.k.a. capability tier) — deferred here on purpose: it's a
  cross-cutting **data** migration (~15 code files across both trees, ~745 records in `debug.json` /
  `optimization_turns.json`, the notebook, the `.pbix` field binding), it re-seeds Cosmos, and it
  breaks the deployed report until re-imported. It belongs with the other data-model work, not the
  clarity pass.
- **Tag every recommendation/scenario/result row with its dimension** (`dimension` field on
  `recommendation_card` / `optimization_result`), sourced from the SCEN-NNN catalog.
- Add a **Portfolio / Overview page** that is a *real* overview: per-dimension coverage (has data?
  has a detected opportunity? applied? measured saving?), i.e., the "are we optimizing across all 8
  dimensions" scoreboard.
- Make the Console group cards **by dimension** and link each to its SCEN-NNN doc; distinguish
  *lenses* (diagnostics) from *applyable policies* in the UI.
- Document the **extensibility path** ("add a scenario") as first-class: dimension → detector →
  card → policy → measured result, mirroring the catalog's discovery methods.

## Consequences

- **Positive:** the product finally reads as the *general* framework the vision/catalog already
  describe; the model-selection pages stop overclaiming; new scenarios have an obvious home; the
  workshop can teach "framework vs. instances" explicitly.
- **Negative / costs:** Phase 2 touches capture → reverse-ETL → insight rows → report → Console →
  docs, in **both trees** (`01_exercises` + `02_completed`), plus a report rebuild and re-import.
  The `complexity_tier → task_tier` rename is a cross-cutting field rename with migration considerations
  for existing seeded data.
- **Risks:** scope creep into a re-architecture; the report is DirectQuery over the mirror, so field
  renames require coordinated changes across notebook, seed data, and the `.pbix`.

## Open items to verify

- Canonical taxonomy decision (6 pillars vs 8 dimensions) — owner to choose; then reconcile all docs.
- Whether Phase 1 renames ship inside PR #73 or a fast-follow.
- `complexity_tier → task_tier` blast radius: `record_optimization_turn` / `derive_optimization_turn`,
  `compute_insights.py`, the notebook, `optimization_turns.json`, the report field, and docs.
- Exact shape of the Portfolio page (measures + a `dimension` dimension table) — Phase 2 design.

## References

- `analytics/docs/vision/agent-analytics-and-optimization-vision.md`
- `analytics/docs/optimization-scenarios/README.md` (+ scenario catalog)
- `analytics/docs/adr/adr-0001-optimization-loop-surface-architecture.md`
- `analytics/docs/adr/adr-0008-optimization-apply-loop-model-selection.md`
- `analytics/PowerBI_Optimization_Build_Guide.md`
- `01_exercises/workshop/Module-07.md` (the 8 dimensions / maturity / risk models)

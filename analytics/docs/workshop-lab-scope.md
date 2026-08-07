# Analytics & Optimization — Workshop Lab Scope

**Status:** Approved direction (two modules); detailed build plan for author + maintainer.
**Audience:** author, maintainer, facilitators, and agents building this out.
**Related:** [workshop-integration.md](workshop-integration.md), [ADR-0008](adr/adr-0008-optimization-apply-loop-model-selection.md),
[optimization-scenarios catalog](optimization-scenarios/README.md), vision doc.

This scopes **all** of the Analytics & Optimization user-lab content and the provided assets it depends
on. It supersedes the single-module plan in `workshop-integration.md` §5–§6 (kept for history).

## 1. Goals & principles

- Teach the full optimization loop — **instrument → detect → recommend → apply → verify** — and the
  5-level maturity model (Visibility → Recommendations → Assisted → Autonomous → Adaptive).
- **Learners write logic, not UX.** No learner-built dashboards. Analytics surfaces are **provided**.
- **Additive** — no changes to Modules 01–05; the layer brings its own instrumentation.
- **Infra via Bicep** — containers, model deployments, and any provisioned surface are in place from
  `azd up` (Module 00). No manual `az`/runtime creation in module steps.
- **Sized to the workshop** — two modules, each ~500–600 lines / 6–7 activities (matching Modules
  05–06), so each has a natural break.

## 2. End-state architecture (all analytics surfaces are provided)

```
 app turn ──record_optimization_turn──▶ Cosmos: OptimizationTurns
                                             │
                                             ▼
                              Fabric notebooks (analyze/aggregate,
                              compute recommendation cards + KPIs)
                                   │                     │
                             reverse-ETL             Lakehouse tables
                                   ▼                     ▼
                     Cosmos: OptimizationInsights   Power BI (read-only viz, .pbit)
                                   │
                                   ▼
        Provided "Optimization Console" web app (own port, ≠ 4200):
        reads insights + recommendation cards from Cosmos,
        one-click APPLY / REVERT via the /optimizations REST API
```

- **Power BI** (`TravelAssistantAnalyticsReport.pbix`, exists) — read-only deep visualization.
- **Optimization Console** (to build) — provided web app on its own port; shows the reverse-ETL'd
  insights/cards and applies optimizations via REST. Learners *use* it; they don't build it.
- **REST `/optimizations`** (exists) — the apply/revert/recommend API both surfaces call.

## 3. Module 07 — Agent Analytics (Visibility & Insight)

*Theme: "You can't optimize what you can't see." Instrument → detect → measure. Maturity L1–L2.*
Target ~6–7 activities, ~500–600 lines.

1. **Why analytics for agents** — the vision's business questions, the 8 optimization dimensions, the
   maturity model, and the **risk model** (policy = lower-risk/autonomous; prompt/code = human-governed).
2. **Instrument your app** — add `record_optimization_turn` (the capture hook) so every turn's
   model/tokens/tier land in `OptimizationTurns`. (Provided helper; ~1-line hook + mount the router.)
3. **Generate signal & see it** — drive a little traffic; open the **Optimization Console** and
   **Power BI** (provided) to see per-turn cost, model usage, and agent paths.
4. **The data pipeline** — how signal flows Cosmos → Fabric → reverse-ETL → Console + Power BI
   (conceptual + run/inspect the provided Fabric notebook or its output).
5. **Detect opportunities** — read the recommendation cards; identify the trivial-turn waste and the
   single-model pattern from *your* data (`GET /optimizations/{tenant}` and the Console).
6. **Measure what matters** — cost per successful outcome (SCEN-003) and other KPIs; interpret them.
7. **(Wrap)** From insight to action — set up the hand-off to Module 08.

**Learner builds:** the instrument hook(s). **Learner uses:** Console, Power BI, mining tool.

## 4. Module 08 — Agent Optimization (Apply & Autonomy)

*Theme: "Act on the insight — safely, then automatically." Recommend → apply → verify → autonomous.
Maturity L3–L5.* Target ~6–7 activities, ~500–600 lines.

1. **The apply-loop & the safe surface** — reversible policies vs code changes; why model selection is
   the first autonomous target.
2. **Build the decision** — implement `classify_complexity_tier` (trivial/routine/complex). *(The core code
   exercise.)*
3. **Apply & watch it route (Scenario A, L4/L5 autonomous)** — wire `get_supervisor_for_turn`; apply
   the model-selection policy from the **Console** (or REST); observe live tiering.
4. **Verify from data** — per-tier cost (`--verify`); the reasoning-token caveat; cost per outcome.
5. **A different risk level (Scenario B, L3 human-governed)** — the tool-call-dedup repeated-node prompt example
   (SCEN-008): detect → recommend → **staged/PR apply** (not auto-applied). Teaches the risk model by
   contrast.
6. **(Stretch)** Tier the itinerary **sub-agent** (the worker) — the higher-value production pattern.
7. **(Capstone, L4/L5) Autonomous quality gate** — wire the Module 06 evaluator so an applied
   optimization **auto-reverts** if quality drops. This is the line between assisted and autonomous.

**Learner builds:** `classify_complexity_tier`, the enforcement hooks, the capstone gate. **Learner uses:**
Console apply/revert, verify tool.

## 5. Learner-builds vs provided (summary)

| Item | Module | Learner builds? |
|---|---|---|
| `record_optimization_turn` hook + router mount | 07 | ✅ small hook |
| `classify_complexity_tier` decision | 08 | ✅ the exercise |
| `get_supervisor_for_turn` enforcement hook + factory | 08 | ✅ small hooks |
| capstone quality gate (uses Module 06 eval) | 08 | ✅ wiring |
| `optimization.py` engine + `optimization_api.py` | — | ❌ provided |
| Optimization Console web app | — | ❌ provided |
| Fabric notebook + reverse-ETL | — | ❌ provided |
| Power BI report | — | ❌ provided |
| Cosmos containers + model deployments | — | ❌ Bicep (`azd up`) |

## 6. Provided-asset build backlog (my work) + proposed sequence

1. **DONE:** `optimization.py`, `optimization_api.py`, Bicep (containers + gpt-5-nano/gpt-5.1),
   `--verify` container support.
2. **Scenario B (SCEN-008, L3):** detect + recommend card + a *staged-apply* path (writes a proposed
   prompt change / PR stub rather than a runtime policy). Needed for Module 08 Activity 5.
3. **Optimization Console** (provided web app, own port): read insights/cards from Cosmos + apply via
   REST. Small, framework-light (does **not** need to be Angular; a minimal static+fetch app is fine).
4. **Fabric notebook + reverse-ETL** (`fabric-notebooks-retl` todo): compute recommendation cards/KPIs
   in Fabric and write `OptimizationInsights` back to Cosmos for the Console. Extend `fabric/ConversionFunnelReverseETL.ipynb`.
5. **Module docs 07 + 08** authored to the outlines above; renumber Lessons `08 → 09`; update `Home.md`
   + Module-06 nav.
6. **`02_completed` convergence** (later): adopt the shared layer + Bicep.

## 7. Scenario / dimension coverage

| Scenario | Dimension | Maturity | Module | Role |
|---|---|---|---|---|
| SCEN-007 model selection | model selection / cost | L4/L5 autonomous | 08 | Scenario A (core) |
| SCEN-008 tool-call-dedup | agent quality / prompt | L3 human-governed | 08 | Scenario B (risk contrast) |
| SCEN-003 cost per outcome | cost / business outcome | KPI | 07 | the measure/scoreboard |
| (breadth, discussed) SCEN-004 memory retention | memory effectiveness | L4/L5 | 07/08 | optional 2nd autonomous example |

## 8. Renumbering & doc updates

- New: **Module-07.md** (Analytics), **Module-08.md** (Optimization).
- Renumber current **Module-08.md** (Lessons) → **Module-09.md**; fix nav.
- `Home.md` learning path: add Module 7 Analytics, Module 8 Optimization, Module 9 Lessons.

## 9. Open decisions

1. **Optimization Console tech** — build it as a **purpose-built, didactic dashboard** (static HTML +
   fetch is acceptable and framework-light, but **polished enough to demonstrate the rationale** for
   this architecture and to support **talking points about how to read the surfaced insights** — not
   a bare-bones throwaway). Own port, reads Cosmos insights, applies via REST. *(Confirmed.)*
2. **Build sequence** — author both module docs first (they work via REST today), then Console, then
   Fabric/reverse-ETL. *(Confirmed.)*
3. **Breadth** — v1 focuses on model-selection (Scenario A) + the SCEN-008 risk contrast (Scenario B);
   SCEN-004 (memory retention) noted as an optional extension. *(Confirmed.)*
4. **Fabric dependency** — Modules 07/08 are completable **without** a Fabric workspace (REST + Console
   reading Cosmos directly); Fabric/Power BI are the optional "scale it out" layer. *(Confirmed.)*

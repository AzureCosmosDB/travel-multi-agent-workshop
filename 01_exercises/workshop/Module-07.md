# Module 07 - Agent Analytics (Visibility & Insight)

**[< Evaluating Your Multi-Agent Application](./Module-06.md)** - **[Agent Optimization >](./Module-08.md)**

## Introduction

You've built a capable multi-agent travel assistant, made it **observable** (Module 05, LangSmith traces) and learned to **evaluate** its quality (Module 06). Traces tell you what happened on *one* request; evaluation scores *one* conversation. But to run an agent system well, organizations need to answer **higher-level, fleet-wide** questions:

- Which agents and workflows deliver the best outcomes?
- Which memories improve success — and which are stale or ineffective?
- What is the **cost per successful outcome**, and where is spend wasted?
- How does agent behavior evolve over time?

Answering these requires turning raw execution into **analytics** — structured, queryable signal about how your agents behave and what it costs. This module is about **visibility and insight**: instrumenting your app to capture that signal, moving it into surfaces you can explore, and reading it to find concrete opportunities. In Module 08 you'll *act* on what you find.

Even beyond describing the system, analytics exists to *change* it. The questions that make this strategic are:

- **How can these insights improve agent behavior?**
- **Which optimizations should be applied — and which can be applied safely, automatically?**
- **How can an agent system continuously improve over time?**

Those are the questions this module (visibility) and the next (action) exist to answer.

> **This module is additive.** It bolts onto the app you already built with one small hook and two provided files — **you will not modify Modules 01–05.** The Cosmos containers and the analytics surfaces it uses are provisioned for you by `azd up` (Bicep). You write the capture hook; you *use* the provided dashboards.

## Learning Objectives and Activities

- Understand why fleet-level **analytics** matters for agents, the **8 optimization dimensions**, and the **maturity model** (Visibility → Recommendations → Assisted → Autonomous → Adaptive)
- Learn the **risk model**: policies (memory, routing, model selection, tools) are lower-risk; prompt/workflow/code changes are human-governed
- **Instrument** your app to capture per-turn model, token, and tier signal
- Move that signal into analytics surfaces (**Optimization Console**, **Power BI**, and the Cosmos → Fabric → reverse-ETL path)
- **Detect** opportunities and **measure** what matters — starting with **cost per successful outcome**

## Module Exercises

1. [Activity 1: Why Analytics for Agents](#activity-1-why-analytics-for-agents)
2. [Activity 2: Instrument Your App](#activity-2-instrument-your-app)
3. [Activity 3: Generate Signal and See It](#activity-3-generate-signal-and-see-it)
4. [Activity 4: The Analytics Data Pipeline](#activity-4-the-analytics-data-pipeline)
5. [Activity 5: Detect Opportunities](#activity-5-detect-opportunities)
6. [Activity 6: Measure What Matters](#activity-6-measure-what-matters)
7. [Activity 7: From Insight to Action](#activity-7-from-insight-to-action)

---

## Activity 1: Why Analytics for Agents

### From traces to analytics

Observability (Module 05) is *per-request* debugging: you follow one trace from user message → supervisor → tool → Cosmos. **Analytics** is *aggregate*: across thousands of turns, which patterns cost the most, which produce outcomes, which memories help. Both matter; this module builds the second.

### The 8 optimization dimensions

Organizations want to continuously optimize:

1. **Agent quality** — are responses correct and helpful?
2. **Workflow efficiency** — are the right steps taken, without waste?
3. **Memory effectiveness** — do recalled memories improve success?
4. **Routing effectiveness** — does work go to the right agent/tool?
5. **Tool utilization** — are tools used when they should be?
6. **Model selection** — is each turn on a model sized to its value?
7. **Cost efficiency** — what does an outcome cost?
8. **Business outcomes** — bookings, conversions, satisfaction.

### The maturity model

| Level | Name | What the system does |
|-------|------|----------------------|
| L1 | Visibility | Surfaces data on dashboards |
| L2 | Recommendations | Suggests optimizations |
| L3 | Assisted | Applies with human approval |
| L4 | Autonomous | Applies within guardrails |
| L5 | Adaptive | Continuously self-tunes |

**This module is L1–L2** (visibility and recommendations). Module 08 climbs to L3–L5.

### The risk model (remember this)

Not every optimization is equally safe to automate:

- **Higher-risk (human-governed, ceiling ~L3):** prompts, workflows, code.
- **Lower-risk (can reach L4/L5):** *policies* — memory salience/retention, retrieval weighting, routing thresholds, **model selection**, tool selection.

Analytics doesn't just describe the system — it feeds the decision about *which* optimizations are safe to apply, and how autonomously. Keep the risk model in mind as you read the insights below.

---

## Activity 2: Instrument Your App

You can't analyze what you don't capture. The provided **optimization layer** ships a lightweight per-turn recorder; your job is to call it.

### Tour the provided files

- `python/src/app/services/optimization.py` — the analytics + optimization engine. For this module you'll use `record_optimization_turn(...)` (capture) and `build_recommendations(...)` (the recommendation card). It also contains the policy store and model factory you'll use in Module 08.
- `python/src/app/optimization_api.py` — the `/optimizations` REST surface (recommendations now; apply/revert in Module 08).

Both are provided; the Cosmos containers they use (`OptimizationTurns`, `OptimizationPolicies`) are created by `azd up` (Bicep).

### Hook 1 — mount the REST surface

In `travel_agents_api.py`, next to your other routers/middleware:

```python
from src.app.optimization_api import router as optimization_router
app.include_router(optimization_router)
```

### Hook 2 — record every turn

In your completion handler, after you invoke the graph and extract token usage (you already do this), record the turn. For now every turn runs on the default model, so record tier `"default"`:

```python
from src.app.services import optimization
from src.app.services.azure_open_ai import AZURE_OPENAI_DEPLOYMENT

optimization.record_optimization_turn(
    tenant_id=tenantId, user_id=userId, session_id=sessionId,
    tier="default", deployment=AZURE_OPENAI_DEPLOYMENT,
    usage={"input_tokens": input_tokens, "output_tokens": output_tokens,
           "total_tokens": total_tokens, "cached_tokens": cached_tokens},
    model_name=model_name,
)
```

Restart your API. Nothing behaves differently — but every turn now lands in `OptimizationTurns`. That's the **instrument** step of the loop.

> In Module 08 you'll replace `tier="default"` with the *real* tier the router picks — the same hook then records which model actually served each turn.

---

## Activity 3: Generate Signal and See It

Drive some realistic traffic through the app (frontend or completion endpoint): a few greetings ("hi", "thanks"), several place queries ("hotels in Amsterdam", "good restaurants near the Rijksmuseum"), and an itinerary request ("plan me 3 days in Amsterdam"). Aim for ~15–20 turns across a couple of sessions.

You now have three ways to look at the captured signal:

### The Optimization Console (provided)

Start the **Optimization Console** — the provided analytics web app — on its own port (separate from the `:4200` travel app):

```powershell
# from the 01_exercises folder
python -m http.server 8050 --directory console
```

Open <http://localhost:8050>, set the **Tenant** to the one you drove traffic with, and click **Refresh**. It reads the captured turns and the recommendation cards and presents them with explanations. Take a few minutes to read each panel; these are the talking points that make the data *mean* something:

- **Turns & spend** — total turns, total tokens, and estimated cost. *Talking point: cost scales with usage, but not evenly — a few turns dominate.*
- **Model usage** — a breakdown by model. Right now it's **one model, 100%**. *Talking point: every turn, trivial or complex, pays the same rate — the core inefficiency this lab targets.*
- **Trivial-turn share** — the fraction of turns that are short, no-delegation answers (greetings, acks, one-line clarifications). *Talking point: these are near-zero-work turns paying full price; the share varies by app, but it's usually a meaningful slice worth reclaiming.*
- **Cost per outcome** — total spend divided by confirmed trips. *Talking point: this is the north-star; a turn that never leads to a booking isn't "cheap," it's waste.*
- **Recommendation cards** — each card is a detected opportunity with evidence and a proposed change. In this module you *read* them; in Module 08 you *apply* them.

> **Model pricing is config-driven — one edit, everywhere.** The $/1M-token rates behind "estimated cost" are stored in the Cosmos **`Configuration`** container (`type = "model_pricing"`), seeded at deploy time from the models `azd` actually deployed. The app's recommendation card, the Fabric reverse-ETL notebook, and the Power BI report all read those **same** rows — no CSV, no per-place hardcoding. Models are discovered from your data; any model without a priced row falls back to a default, so a model swap never breaks a report. To change a price or add a model, edit **`python/data/model_pricing.json`** (the committed price reference, format `{"deployment": {"input": x, "output": y}}` USD per 1M tokens) and redeploy. See **[analytics/docs/model-pricing.md](../../analytics/docs/model-pricing.md)** for the default models and how to find a model's price.

Notice what the Console is doing: it turns thousands of individual turns into a handful of **decisions** — which is exactly what a human operator (or, later, the system itself) needs to act.

### Power BI (provided)

For the deep, real-time view, use the provided **`analytics/TravelAssistantAnalyticsReport.pbit`**
template (built with the `analytics/PowerBI_Optimization_Build_Guide.md` guide):

1. Open the `.pbit` in **Power BI Desktop**.
2. When prompted, paste your **mirror SQL analytics endpoint** and **mirror database name** (from your
   Fabric mirrored database — see `analytics/fabric/README.md`).
3. The report loads over **DirectQuery**, so it reflects new turns **near-real-time** as the mirror
   replicates. Turn on **page auto-refresh** and run the traffic simulator to watch it move live:

   ```powershell
   python analytics/traffic_simulator.py --tenant DemoLive --rate 120 --forever
   ```

> The **Console + REST** are enough for this module's detect/measure steps (they read Cosmos directly). The **Cosmos → Fabric mirror + Power BI + reverse-ETL** is the analytical plane — you build it in **Module 09**, which is where the business-impact analytics and the self-optimizing (L4/L5) loop come together.

### The raw signal (REST + CLI)

Everything the surfaces show comes from data you can query directly:

```powershell
# the recommendation card, straight from the API
Invoke-RestMethod "http://localhost:8000/optimizations/<yourTenant>" | ConvertTo-Json -Depth 6
```

The Console and Power BI are *views*; the source of truth is `OptimizationTurns` in Cosmos.

---

## Activity 4: The Analytics Data Pipeline

How does a turn become an insight on a dashboard? The pipeline:

```
 app turn ──record_optimization_turn──▶ Cosmos: OptimizationTurns
                                             │
                                             ▼
                              Fabric notebooks (analyze / aggregate,
                              compute recommendation cards + KPIs)
                                   │                     │
                             reverse-ETL             Lakehouse tables
                                   ▼                     ▼
                     Cosmos: OptimizationInsights   Power BI (read-only viz)
                                   │
                                   ▼
                   Optimization Console (cards + apply)
```

Key ideas to understand (and to talk about):

- **Cosmos is the operational store** — the app writes turns here and reads *insights/cards* here, so the live app and the dashboards share one low-latency source.
- **Fabric does the heavy analysis** — aggregations, trends, and recommendation generation run in notebooks over the lakehouse, not on the request path.
- **Reverse-ETL closes the loop** — computed insights are written *back* into Cosmos so the app and the Console can act on them in real time. This is why the Console can show recommendations and apply them without a analytics round-trip.

> **This module runs on Cosmos alone** — the Console and REST read `OptimizationTurns`/insights directly. The **Cosmos + Fabric via Mirroring** story (the analytical plane, the reverse-ETL loop, and the business-impact conversion funnel) is **Module 09** — that's where you'll see why this pairing is so powerful for AI applications.

---

## Activity 5: Detect Opportunities

Read the recommendation card (Console or REST). With every turn on one model, two things jump out:

- **A single model serves everything** — greetings and full itinerary generation alike.
- **A large share of turns are trivial** — short answers with no delegation. Commonly ~40–50%.

That's the **model-selection** opportunity (dimension 6): trivial turns pay full price; high-value turns might merit a stronger model. The card names it, shows the evidence from *your* data, and proposes a tiered policy — the **recommend** step (maturity L2). A card looks like:

```json
{
  "scenario_id": "SCEN-007",
  "title": "Capability-tiered model selection",
  "status": "not_proposed",
  "evidence": {
    "total_turns": 18,
    "trivial_turns": 8,
    "trivial_pct": 44.4,
    "model_distribution": { "gpt-5.1-...": 18 }
  },
  "estimated_saving_usd": 0.13,
  "estimate_caveat": "ESTIMATE only. gpt-5-nano is a reasoning model ...",
  "proposed_params": { "tiers": { "trivial": "gpt-5-nano", "routine": "gpt-5-mini", "complex": "gpt-5.1" } }
}
```

Read it critically: the `evidence` is *your* measured data; the `estimated_saving_usd` is a projection with an explicit caveat (you'll confirm or refute it by measuring in Module 08).

Look also for other dimensions in the same data:
- **Tool utilization** — how often does a place question get answered from model knowledge instead of a `find_places` search?
- **Cost concentration** — do a few expensive turns (itinerary generation) dominate total spend?

### The Console surfaces more than model selection

`GET /optimizations/<tenant>` (and the Console) returns a **set** of cards — and they're deliberately different *kinds* of action, which is the real lesson: an "optimization" isn't one thing.

- **Apply-able policies** (autonomous, L4/L5): capability-tiered **model selection** (SCEN-007) and **memory retention** (SCEN-004 — prune stale/superseded memories). One-click, reversible toggles.
- **Staged prompt/code changes** (human-governed, L3): **active-trip city context** (SCEN-001) and **redundant tool calls** (SCEN-008). Recorded as a reviewable proposal — never auto-applied.
- **Diagnostic lenses** (no toggle): **cost per outcome & conversion funnel** (SCEN-003) and **agent-path cost concentration** (SCEN-005). SCEN-003 is the *business-impact* view — it doesn't just say "36% of tokens went to sessions that never booked," it builds a funnel (engaged → searched → planned → confirmed), shows **where** sessions leak and **why** (e.g. the agent kept re-asking the city), and names the fix (SCEN-001). These *tell you where to look*; you act via the policies and staged fixes above — a dashboard can't auto-fix a conversion problem, but it can point straight at the cause.

You're not fixing anything yet — you're building the *insight* that Module 08 will act on.

---

## Activity 6: Measure What Matters

The north-star metric for an agent system isn't tokens per turn — it's **cost per successful outcome** (e.g., cost per confirmed trip). A cheap turn that never leads to a booking isn't efficient; an expensive turn that closes one may be.

```powershell
# per-tier cost breakdown from your captured turns
python analytics/optimization_mining.py --tenant <yourTenant> --verify --container OptimizationTurns
```

Right now everything is `default` — a single baseline. Note the totals. In Module 08 you'll re-measure after applying an optimization and compare **cost per outcome** before/after. Two habits to build now:

1. **Measure outcomes, not just cost** — always tie spend to a business result.
2. **Trust measurement over estimates** — especially with reasoning models, whose hidden "reasoning tokens" make naive projections misleading. The measured before/after is the truth.

---

## Activity 7: From Insight to Action

You've completed the first half of the optimization loop:

> **instrument → detect → recommend →** *apply → verify*

You instrumented the app, saw the signal in the Console and Power BI, understood the pipeline that produces it, detected the model-selection opportunity, and established the cost-per-outcome baseline. You're at **maturity L2**: the system can *recommend*, and a human can read the insight.

In **Module 08** you'll close the loop — apply the recommended optimization with one click, verify it from data, contrast a lower-risk autonomous change with a higher-risk human-governed one, and finally make the system **self-correct** with an automated quality gate.

## Test Your Work

- [ ] The two hooks (mount router, `record_optimization_turn`) are wired; the app runs normally.
- [ ] After some traffic, `OptimizationTurns` has one document per turn.
- [ ] `GET /optimizations/<tenant>` returns a recommendation card built from your turns.
- [ ] You can open the Optimization Console (and/or Power BI) and explain, in your own words, the trivial-turn waste and the single-model pattern.
- [ ] `--verify` prints a per-tier (currently all `default`) cost baseline.
- [ ] You can state why **cost per outcome** — not cost per turn — is the metric that matters.

## Troubleshooting

- **`OptimizationTurns` is empty after traffic.** Confirm the `record_optimization_turn` call is *after* you extract token usage and is actually reached (add a log line). Confirm `azd up` created the `OptimizationTurns` container (`az cosmosdb sql container list ...`).
- **Recommendation card shows `total_turns: 0`.** You're querying a different `tenantId` than you drove traffic with — pass the same tenant to `GET /optimizations/{tenant}`.
- **Console shows nothing.** It reads the same Cosmos data as the REST API — verify the API returns a card first, then reload the Console.
- **`--verify` errors on the container.** Pass `--container OptimizationTurns` (the default), and ensure `COSMOSDB_ENDPOINT`/`COSMOSDB_DATABASE_NAME` in your env match your deployment.

## What You Learned

You turned raw execution into **analytics**: you instrumented the app, moved the signal into surfaces you can explore, and read it to find a concrete, data-backed opportunity — all without touching the app's core behavior. You learned the 8 dimensions, the maturity model, and the risk model that governs *how* optimizations can be applied. Next, you'll act on it.

### Return to **[Home](./Home.md)**

**[< Evaluating Your Multi-Agent Application](./Module-06.md)** - **[Agent Optimization >](./Module-08.md)**

# Solution Architecture Guide

> **Purpose.** One place that explains *how this whole solution fits together* — the travel
> multi-agent app **and** the agent analytics & optimization platform built on top of it — and the
> handful of concepts you need to reason about either. It is written for **two audiences**: humans
> (contributors and workshop attendees) and **AI agents** exploring the repo so they can make
> grounded suggestions.
>
> **Relationship to the other docs.** This guide *consolidates and cross-links*; it does not replace:
> - `vision/agent-analytics-and-optimization-vision.md` — the north-star (verbatim, do not edit).
> - `charter.md` — scope, maturity target, first principles. **Read it first for constraints.**
> - `adr/` — the binding decisions with evidence. This guide narrates them; the ADRs are authoritative.
> - `optimization-scenarios/README.md` — the 8 dimensions + the SCEN catalog.
>
> **How to read this.** Sections 1–3 are the mental model (the app, its agents, and *agents ×
> dimensions*). Sections 4–9 are the measurement + optimization concepts (the loop, the three-layer
> engine, detectors, seams, maturity/risk, the analyst). Sections 10–12 are the plumbing, cost, and
> the workshop mapping.

## Status legend (current vs. target)

This solution is **mid-redesign** (ADR-0010). To stay honest per the charter's first principle
("data-grounded, always — 'should work' is not 'works'"), every forward-looking element is marked:

- ✅ **Built** — implemented and verified in `02_completed/` today.
- 🔨 **Target** — the agent-centric redesign (ADR-0010), not yet built; tagged with its phase `P0…P4`.
- ⚠️ **Caveat** — built, but with an honesty caveat (e.g., synthetic-data limitation).

When an AI agent reads this guide: treat 🔨 items as **intended design**, not existing behavior. Do not
assert a 🔨 capability exists; verify against code before relying on it.

---

## 1. What this solution is — two systems in one continuous loop

This repository is a **travel-planning multi-agent app** that doubles as the worked instance for an
**agent analytics & optimization platform**. The two halves map onto the vision's core split:

- **Cosmos DB = the operational system of record.** The app runs against Azure Cosmos DB
  (`TravelAssistant` database): sessions, messages, memories, trips, checkpoints, and the per-turn
  telemetry (`Debug`).
- **Microsoft Fabric = the analytical & optimization system of record.** Cosmos is **mirrored** into
  OneLake; notebooks compute insights; recommendations and applied-optimization results are
  **reverse-ETL'd back into Cosmos** so the operational app can read and act on them.

```
Agents → Operational State → Cosmos DB → Fabric Analytics → Optimization Intelligence → Agents
                                   ▲                                        │
                                   └──────────── reverse-ETL ───────────────┘
```

That reverse-ETL round-trip (ADR-0001) is the spine: analytics doesn't just *observe*, it feeds
recommendations and policies **back** into the running system, closing an *analyze → recommend →
apply → measure* loop.

### 1.1 Runtime topology

Three processes run the app; a fourth "plane" is the analytics layer.

| Plane | Component | Where | Role |
|---|---|---|---|
| App | **Travel API** (FastAPI) | `python/src/app/travel_agents_api.py` | Chat endpoint runs the agent graph; keyed by `tenantId/userId/sessionId`. |
| App | **Agent runtime** | `python/src/app/travel_agents.py` | The supervisor ReAct agent + sub-agents (§2). |
| App | **MCP server** (FastMCP) | `mcp_server/mcp_http_server.py` | Tools the agents call: memory, summarization, `discover_places`, trip CRUD, routing transfers. |
| App | **Frontend** (Angular) | `frontend/` | Chat UI **and** the optimization **Console** (`/console/`). |
| Analytics | **Fabric mirror + notebooks** | `analytics/` | Mirror Cosmos → OneLake; compute insights; reverse-ETL results back. |
| Analytics | **Power BI report** | `analytics/TravelAssistantAnalyticsReport.pbix` | The Level-1 visibility surface (dashboards). |

> **Console vs. report.** The **Console** (in the web app) is the *interactive apply-loop* — stage and
> apply policies, see live effects. The **Power BI report** is the *visibility surface* — dashboards
> over the mirrored analytical data. They are different surfaces of the same loop.

---

## 2. The agent system — what we are actually measuring

You cannot measure agents you cannot name. The completed app (`02_completed/`) is the **v2 supervisor
architecture** (ADR-0006), *not* the classic per-specialist StateGraph. Verified in
`travel_agents.py`:

- One **`supervisor`** ReAct agent (`create_react_agent`, prompt `supervisor.prompty`) orchestrates
  every turn. It's built per-deployment so a routing policy can bind it to a cheaper/pricier model
  (`_build_supervisor`, `get_supervisor_for_turn`).
- It calls two **tool-backed sub-agents**:
  - **`find_places`** (`@tool("find_places")` → `_oneshot_find_places`) — place discovery/grounding.
  - **`create_or_update_itinerary`** (`@tool("create_or_update_itinerary")`) — itinerary assembly.
- A **memory subsystem** (via MCP: `store_user_memory` / `recall_memories`, salience, supersession)
  and a **summarizer** (auto-runs ~every 10 turns) support every agent.

So the **three agents that appear in telemetry** — `supervisor`, `find_places`,
`create_or_update_itinerary` — are the real unit of analysis. (Grounded live, 02, 1,330 turns,
2026-07-31.)

### 2.1 Routing / handoff convention

Handoffs are explicit: an agent calls a `transfer_to_<name>` tool that returns JSON with a `goto`
field; the router scans the most recent `ToolMessage` for that `goto`, falling back to the session
doc's `activeAgent`, then `orchestrator`. `agent_path` is recorded per turn as a **sequence string**
(e.g. `supervisor,find_places,create_or_update_itinerary`).

### 2.2 The measurement gap this creates (the reason for ADR-0010)

The turn is not the right grain. ✅ Today one `OptimizationTurns` row per **turn** carries a single
`total_tokens` / `model_tier` and `agent_path` as a *string* — so cost/quality **cannot be attributed
to an individual agent** inside a multi-agent turn, and **36% of turns (480/1,330) have no
`agent_path`** at all (synthetic-simulator traffic). 🔨 **P0** re-grains telemetry to **one row per
agent execution** (LangGraph node invocation), which the runtime already emits per node but currently
aggregates away. *Re-graining is cost-neutral — more rows, not more LLM calls* (§11).

---

## 3. Agents × dimensions — the core mental model

The single most important idea in the redesign: **the agent is the primary lens, and each agent is
scored across the eight optimization dimensions.** Owners reason about *their agents* ("is the
supervisor using the right model? is its prompt routing efficiently?"); the product must too. That is
a **matrix**:

|  | Agent quality | Workflow eff. | Memory eff. | Routing eff. | Tool util. | Model selection | Cost eff. | Business |
|---|---|---|---|---|---|---|---|---|
| **supervisor** | judge score | hops/turn | recall usage | delegation correctness | over/under-call | **bimodal → routing prize** | cost/outcome | conversion by path |
| **find_places** | grounded/relevant | redundant calls | recall-biased search | — | tool errors | consistently heavy → premium justified | cost/result | contribution to confirmed trips |
| **create_or_update_itinerary** | valid/complete/feasible | — | trip-context reuse | — | — | consistently heavy → premium justified | cost/itinerary | itinerary → confirmed trip |

Each cell resolves to a **health state** — *healthy / watch / unhealthy* — computed by the analysis
engine (§6), plus any detected opportunity and its apply action. 🔨 **P0** — this **Agent Scorecard**
is *the* "how is each of my agents doing?" view; it does not exist today.

> **Why model-fit is per-agent.** `supervisor` is **bimodal** — many light turns (avg ~179 output
> tokens) plus some heavy ones — so it's the model-*routing* prize. `find_places` (~463) and
> `create_or_update_itinerary` (~2,100) are consistently heavy, so a premium model is *justified*.
> A fleet-wide "use a cheaper model" recommendation would be wrong; a *per-agent* one is right.
> (Node counts 1→2→3 = 179→463→2,100 avg output tokens, grounded live.)

### 3.1 The eight optimization dimensions

The canonical axes (from the vision; catalog in `optimization-scenarios/README.md`). `Trips.status`
(confirmed/completed) is the shared **outcome anchor** — every dimension is ultimately judged by
whether it moves business outcomes.

| Dimension | What it means here | Primary signal | Typical fix seam |
|---|---|---|---|
| **Agent quality** | correct, helpful, complete responses | LLM-judge (answer-quality/correctness), trip completion | prompt |
| **Workflow efficiency** | fewest turns/hops/latency to an outcome | `agent_path`, `handoff_count`, turns-to-first-result | prompt / routing |
| **Memory effectiveness** | memories recalled *and* improving outcomes | recall usage, `salience`, `superseded_by` | prompt / config |
| **Routing effectiveness** | supervisor delegates to the right sub-agent | `agent_path` vs expected, delegation-avoidance | prompt |
| **Tool utilization** | tools called when useful, not wastefully | `tool_calls`, over-/under-calling | prompt / config |
| **Model selection** | right model for the task's difficulty | realized complexity × model per agent | config / model-routing |
| **Cost efficiency** | tokens / \$ per successful outcome | `total_tokens`, `cached_tokens` ÷ confirmed `Trips` | prompt / config / model |
| **Business outcomes** | bookings made — the anchor success signal | `Trips.status` | served by all of the above |

---

## 4. The measurement framework — the loop every optimization walks

Every optimization, in this solution, follows the same five-step loop (ADR-0001):

> **instrument → detect (in data) → recommend (a card) → apply (ideally one seam-appropriate action) → verify (before/after)**

A good optimization is **realistic**, **detectable from data we already capture**, **fixable at a
safe seam**, and **measurable** after the fix. Three framework concepts make this rigorous:

### 4.1 Two notions of "complexity" (the code conflates them)

The owner's recurring question — *"how do we determine task complexity to pin a model?"* — has two
distinct answers the current code blurs:

- **Realized complexity (post-hoc, for *analysis*).** Measured from execution: nodes activated,
  output/reasoning tokens, tool calls. Already available, clean, monotonic. Powers the per-agent
  **model-fit** signal and finds **~5× the opportunity** the keyword heuristic does (438 `supervisor`
  turns ran premium at ~179 output tokens; the ≤6-word classifier flagged only 90 as trivial).
- **Predicted complexity (a-priori, for *routing*).** To pick a model *before* the turn runs you need
  a predictor (feature classifier / confidence cascade — RouteLLM/FrugalGPT). This is the harder
  problem, is *itself* the optimization the platform recommends, and its quality is then **measured**
  against realized complexity + outcome.

✅ Today `classify_turn_tier()` (`travel_agents.py:376`) is a **keyword heuristic** (≤6 words + greeting
regex → trivial) standing in weakly for *both*. 🔨 **P2** replaces it with a measured, per-agent
model-fit signal. **Provenance matters:** the tiered router (`classify_turn_tier` /
`select_deployment_for_turn`) was introduced by the analytics track (commit `b717dba`) and is **absent
on `main`** — the base app is **single-model**. This is why "Apply model-selection" is a *code seam*
the first time (§7).

### 4.2 Price-only vs. behavior-changing (how business impact generalizes)

Optimizations split by *what they touch*, which decides how honestly we can project business impact:

- **Price-only** (e.g., route trivial turns to a cheaper model): quality/behavior held constant, so
  cost ↓ ⇒ **cost per outcome ↓** — safe to *project*.
- **Behavior-changing** (e.g., a prompt rule that changes routing): any conversion lift is a
  **hypothesis confirmed by measured before/after** (the funnel), **never a fabricated projection**.

`cost per outcome` (spend ÷ confirmed trips) is the generalizing business metric — reduced-turns and
latency are proxies that feed tokens → cost.

### 4.3 Projection functions & the What-If view

🔨 **P1+.** Every recommendation carries a **projection function** — *which turns it affects and how it
changes tokens/turns* — so the engine estimates a projected saving the same way for all. The
**Projected Impact / What-If** surface shows **baseline vs. optimized cost** (projected, then realized
once applied), a **usage-scaling control** ("at N turns/day ≈ \$X/month"), and **cost per outcome**
before/after. This **generalizes** the model-selection counterfactual (which we already price) to
every optimization — and it's the demo-first "show an audience the impact immediately" view.
*Mechanics of each projection function are an open ADR-0010 item.*

---

## 5. The three-layer engine (ADR-0010)

```
LangGraph exec + Cosmos memory toolkit          (1) INSTRUMENTATION → per-agent (node-grain) telemetry
        │  nodes, routing, tool calls, tokens, recalls, salience, outcomes
        ▼
Fabric: baselines + detectors + LLM-as-analyst  (2) ANALYSIS ENGINE (the "brain")
        │  per (agent × dimension) scorecards; anomalies vs baseline/cohort/SLO;
        │  analyst turns anomalies + traces into ranked, explained recommendations
        ▼
Agent Scorecards · Portfolio · Discovered Opportunities · What-If → apply → re-measure
                                                (3) SURFACES + the existing apply-loop
```

- **Layer 1 — Instrumentation (🔨 P0).** Re-grain to **one record per agent execution**:
  `{ tenantId, userId, sessionId, turn_id, seq, agent, model_deployment, input/output/reasoning_tokens,
  latency_ms, tool_calls[], recall_used, complexity, outcome_link, timeStamp }`. Add the missing
  dimension signals: LLM-judge **quality**, per-node **recall usage**, **tool-call outcomes**, and a
  **measured complexity** signal. The per-turn view stays a rollup; the scorecard reads the node grain.
- **Layer 2 — Analysis engine (🔨 P1/P3).** Two tiers, both in Fabric, both reverse-ETL'd to Cosmos:
  **(2a) statistical detectors** derive baselines/thresholds from the data; **(2b) an LLM-as-analyst**
  turns ranked anomalies + traces into structured recommendation cards. Detailed in §6 and §9.
- **Layer 3 — Surfaces (🔨 P0/P3).** Agent Scorecard (primary), Portfolio/Overview (the fleet across
  8 dimensions), Discovered-Opportunities feed (replaces the fixed cards), Projected Impact/What-If,
  and the retained dimension deep-dives (Model Selection, Memory Intelligence, Business Impact).

> **Scenarios flip from inputs to outputs.** ✅ Today `SCEN-001…008` are hand-authored and the product
> hard-codes six recommendation builders. 🔨 The engine **discovers** issues from telemetry; the SCEN
> catalog is demoted to **evaluation fixtures + seed priors** — the answer key the engine must
> rediscover (§9).

### 5.1 Quality signal — reuse the evaluation harness (Module 06 ↔ analytics)

🔨 The agent-quality / routing / tool dimensions don't need a new judge: the app already ships an
**LLM-as-judge harness** (`01_exercises/evaluation/`): `llm_judges.py` (`answer_quality`,
`correctness`, `humanness` 1–5), the `e2e`/`routing`/`tool_usage` suites (which map 1:1 to those
dimensions), and labeled `datasets/*.json` (calibration gold). Three adaptations make it the
scorecard's quality signal: (1) a **reference-free** rubric mode for live turns (judge groundedness
against retrieved places); (2) **per-agent role rubrics** (`find_places`→relevant/grounded;
`create_or_update_itinerary`→valid/complete/feasible; `supervisor`→coherent synthesis + correct
routing); (3) **calibration** against the labeled datasets. **Decision:** unify Module 06 with the
analytics — evaluation *is* the quality/routing/tool dimensions, reverse-ETL'd per agent, not a
separate "run these scripts" appendix.

---

## 6. Detector taxonomy — three kinds, not one

The owner's honest worry — *"I have no idea what thresholds are correct for healthy vs. unhealthy"* —
mostly **dissolves once detectors are separated by kind**. The two most valuable kinds need **no
authored thresholds**.

| Kind | Asks | Threshold source | Needs history? |
|---|---|---|---|
| **Counterfactual** | "re-simulate a change over historical turns — is the saving *material*?" | materiality (≥X% spend / ≥\$Y/mo) | **no** — any volume |
| **Structural / rule** | "is this pattern *definitionally* wrong?" (repeated tool call, superseded memory recalled) | the rule itself | **no** — fires immediately |
| **Statistical** | "did this metric drift from its baseline / an SLO?" | derived (z-score / percentile / window) or owner **SLO** | **yes** |

Both non-statistical kinds already fire on live data: **counterfactual** = the 438 `supervisor` premium
turns (~5× the keyword tier); **structural** = the `supervisor,find_places,find_places` repeated node
(SCEN-005) — zero thresholds, zero history. So *"what thresholds?"* splits three ways:
worth-acting-on (counterfactual), a definitional rule (structural), or **derived** (statistical) —
**never hand-authored.**

**Per-dimension detector set:**

| Dimension | Metric | Kind | Threshold source |
|---|---|---|---|
| Model selection / cost | low realized-complexity turns on premium (per agent) | counterfactual | re-priced saving materiality |
| Workflow efficiency | repeated node / redundant step; costly non-converting path | structural + cohort | rule; cohort |
| Memory effectiveness | superseded recalled; high-salience never recalled; low-salience bloat | structural + cohort | rule; recall-hit vs -miss conversion |
| Routing effectiveness | `agent_path` vs expected; delegation-avoidance | structural (routing eval) + statistical | eval rule + drift |
| Tool utilization | over/under-calling; tool errors | structural (tool eval) + statistical | eval rule + baseline |
| Agent quality | LLM-judge score per agent | statistical + SLO | drift + owner target (≥3/5 for 95%) |
| Cost efficiency | cost per outcome (agent contribution) | statistical + cohort | baseline + cohort |
| Business outcomes | conversion by path/agent | cohort + funnel | cohort |

**Windows & cold-start.** Rolling adaptive windows (last N turns / T days); cohort baselines over the
current set. Cold-start: lean on **counterfactual + structural** (work at any volume), treat seeded
config constants (`trivial_max_words=6`, salience 0.8/0.5) as **priors/fallbacks**, seed a baseline
from the golden fixture, and **activate statistical detectors only at ≥N samples** (suppressed, not
noisy, before that).

> **Teaching line:** *you don't hand-pick thresholds; you pick detector kinds* — and only the
> statistical few carry a (derived) one.

---

## 7. The optimization seam ladder — what "apply" actually means

The single most consequential architecture concept: **optimizations live on a spectrum of *seams*, and
the seam decides both *how* you apply an optimization and *how autonomously* you can.** An optimization
is only auto-applyable if the app was **built to expose the knob**; building the knob is itself a
one-time, human-governed change.

| Seam | Example | "Apply" = | Maturity ceiling |
|---|---|---|---|
| **Config / policy** (a knob the app *already reads*) | tier→model map, thresholds, memory salience/retention | flip a policy doc in Cosmos (Console / translytical **Apply**) | **L4/L5 autonomous** |
| **Prompt** (`.prompty` text) | add a supervisor rule (SCEN-001) | stage `{file, add}`; human reviews + deploys | **L3 assisted** |
| **Code / new mechanism** (no knob exists yet) | *introduce* per-turn routing on a single-model app | stage a diff/PR; human builds + merges + deploys | **L3 assisted (human-governed)** |

**Corollary — model-selection is a *code* seam the first time.** On the single-model base app, "route
the supervisor's light turns to a cheaper model" is **not** a policy flip — it's the code change that
*creates* `select_deployment_for_turn`. Only *after* a human ships that seam does ongoing tuning (the
tier→model map, thresholds) become an auto-applyable **policy**. ✅ The current workshop *pre-builds* the
router and ships tiered data, so "Apply model-selection" looks like a pure config flip — it only works
because the code was already written to read the policy.

**How a code/prompt recommendation is applied (grounded in existing code).** ✅ The staged-change loop
already exists: `get_city_context_staged_change()` returns `{file, add}`;
`POST /optimizations/{scenario}/stage` records it as `apply_mode: "staged_change"` (never active at
runtime); a human reviews + deploys. 🔨 The redesign has the **LLM analyst *generate*** that diff
(instead of a hardcoded constant), optionally with a DSPy/GEPA prompt optimizer. **Arbitrary code is
never auto-applied** — the hard ceiling of the risk model.

> **The generalizable lesson:** *to make an agent app optimizable, you deliberately instrument seams.*
> The platform recommends across all three, **tuning config autonomously** and **staging reviewable
> prompt/code diffs** where no knob yet exists. This reframes the tiered router from a demo cheat into
> the canonical worked example of a **code-seam optimization** (see the hands-on module, §12).

---

## 8. Maturity & risk models — how a seam sets the autonomy ceiling

The vision's five-level maturity ladder, and the risk model that governs the L4/L5 ceiling:

| Level | Name | What the platform does | Human role |
|---|---|---|---|
| **L1** | Visibility | Dashboards/report surface the metric | identify & implement |
| **L2** | Recommendations | Platform recommends a fix | review & approve |
| **L3** | Assisted | Generates the concrete change + impact analysis | approve/reject before deploy |
| **L4** | Autonomous | For approved **lower-risk** domains: auto-apply + validate (reversible, auditable) | set policy & audit |
| **L5** | Adaptive | Fleets self-tune lower-risk domains; higher-risk stays governed | govern the envelope |

**Risk domains (from the vision) set the ceiling:**

- **Lower-risk → autonomous-eligible (L4/L5):** memory salience tuning, retention policies, retrieval
  weighting, routing thresholds, tool-selection policies, **model-selection policies**, cost policies.
  These are **parameters/policies** — bounded, reversible, measurable → the **config** seam.
- **Higher-risk → human-governed (ceiling L2/L3):** **prompt modifications**, workflow redesign,
  agent-instruction/capability changes, code generation, deployment changes → the **prompt/code** seams.

> ⚠️ **Counter-intuitive but load-bearing:** a prompt edit *feels* safe (it's just text), but the
> vision classifies **prompt modifications as higher-risk / human-governed**. So SCEN-001 (a
> `supervisor.prompty` rule) is a great L1→L3 example but **caps at Assisted (L3)**. The scenarios that
> truly demonstrate **L4/L5 self-adaptation** are the **policy/threshold** ones — which is exactly why
> the catalog deliberately includes both kinds.

**Seam ↔ detector ↔ ceiling map:** counterfactual/structural detections → config/structural fixes
(can reach L4/L5); statistical/quality anomalies → regressions a human investigates (L2/L3).

⚠️ **Honesty caveat (charter):** with synthetic workshop data there is no real outcome signal, so the
L4 "validate it improved outcomes" step is **demonstrative, not proof** — we show the autonomy
*mechanism and safety loop*, transparently flagged. L5 is **conceptual framing only** in this workshop.

---

## 9. The LLM analyst — guardrails & rediscovery

🔨 **P3.** The analyst (Layer 2b) consumes detector outputs (anomalies per agent × dimension) +
representative traces + fix-seam metadata, and emits ranked, structured **recommendation cards**:

```
{ agent, dimension, evidence[], proposed_change{ seam, target, diff|value },
  maturity_ceiling, apply_mode, projected_impact }
```

**Five guardrails** keep it useful and safe:

1. **LLM proposes, engine computes.** The analyst decides *which agent / dimension / change / why*
   (qualitative); the deterministic **projection function** computes the **saving** (quantitative). The
   LLM never invents a dollar figure — this kills hallucinated savings.
2. **Bounded to known seams.** Output is a *structured* card against a config knob / prompt file / code
   diff — never free-form; no unknown action space.
3. **Grounded + cited.** Every card must cite its detector evidence + sample traces; uncited claims are
   rejected.
4. **Risk-model-gated apply.** The seam sets `apply_mode` automatically: **config → auto (L4/5)**;
   **prompt / code → staged diff for human review (L3)**. The LLM doesn't choose its own autonomy.
5. **Human approval** for anything above the auto ceiling.

**Rediscovery as a regression suite (how we know it works).** The flipped `SCEN-001…008` catalog is the
**answer key**: feed the engine the known-issue fixtures and **assert it rediscovers** them from data —
SCEN-005 (double `find_places`, structural), SCEN-007 (model selection, counterfactual), SCEN-004
(stale memory), SCEN-001 (city-context re-ask). A miss = a real gap (missing detector / weak analyst
prompt) = a **failing test**, not a vibe. "Watch the engine find a known problem on its own" is a strong
teaching moment.

---

## 10. Data architecture — Cosmos, the mirror, and the reverse-ETL

**Operational store (Cosmos `TravelAssistant`).** Containers `Sessions`, `Messages`, `Summaries`,
`Memories`, `ApiEvents`, `Debug`, `Places`, `Trips`, `Users`, `Checkpoints`; most use a hierarchical
partition key `[tenant_id, user_id, session_id]`. `Debug` carries the per-turn telemetry;
`OptimizationTurns`-style rows and applied-optimization results are read back by the app. All data
access is centralized in `services/azure_cosmos_db.py` (lazily-initialized module globals — reuse the
accessors, don't spin up new clients).

**Normalization — the Open Agent Analytics Schema.** The app's operational state maps to the vision's
framework-agnostic primitives (`AgentRun`, `AgentStep`, `AgentTransition`, `ToolInvocation`,
`MemoryEvent`, `Checkpoint`, `EvaluationResult`, `TokenUsage`, `UserSession`, `WorkflowExecution`) so
analytics stays portable across frameworks (ADR-0002/0003). 🔨 P0's node grain is an `AgentStep` stream.

**Mirror set.** Fabric Mirroring replicates a subset (Memories, Users, Trips, Places today; the
`Debug`/node-grain telemetry is the redesign's key addition). Notebooks compute insights over OneLake;
`compute_insights.py` produces the KPIs; results are **reverse-ETL'd back into Cosmos** so the app +
Console + report read a single source of truth.

**Surfaces.** ✅ The **Power BI report** (`analytics/TravelAssistantAnalyticsReport.pbix`) is the L1
visibility surface (pages: Model Selection — Baseline / Opportunity, Memory Intelligence, Business
Impact, Measured Savings, Applied Optimizations). ✅ The **Console** is the interactive apply-loop.
🔨 The redesign adds the Agent Scorecard, Discovered-Opportunities feed, and What-If pages.

> **Constraints (verified, charter §Known constraints):** Cosmos is `disableLocalAuth: true`; Fabric
> UDFs' managed connection targets Cosmos-in-Fabric, not the external account; deployed apps can't
> reach Lakehouse SQL endpoints via managed identity — **Cosmos is the operational bridge** for the
> reverse-ETL (ADR-0001).

---

## 11. Cost & data-generation strategy — attendee path ≈ \$0 LLM

Running **live agents** to generate telemetry is prohibitively expensive (hours, ~10M tokens — the
owner's original approach, and the lesson behind the fixture-first pivot, ADR-0004). The redesign must
not reintroduce that cost, and doesn't, because *generating telemetry* is separated from *running the
analysis engine*:

- **Re-graining is cost-neutral.** Nodes already run and make their LLM calls; node-grain simply
  *records* each node's telemetry instead of discarding it. **More rows, not more LLM calls.**
- **Telemetry is fixture-first.** The **golden fixture** is captured once by the maintainer at node
  grain (one expensive live run, exported + committed); attendees load it offline via `seed_data.py`
  → \$0. The **traffic simulator** is upgraded to fabricate **agent-structured node executions**
  (synthetic, realistic distributions), fixing the 36% no-agent gap — still **no LLM**.
- **Engine LLM cost is bounded by pre-baking.** The maintainer runs the judge + analyst once; their
  outputs (per-node quality scores, recommendation cards) are **committed as fixtures**, so attendees
  see a fully-populated platform for \$0. The teaching moment is reading the code that *produces* them,
  and optionally running the judge on ~5 turns / the analyst on pre-computed aggregates (cents, minutes).

**Attendee path:** load fixtures → run the Fabric reverse-ETL (capacity cost only, no tokens) → explore
scorecards + discovered opportunities → apply a policy → re-measure. **No live agents, no hours, no
token bill.** The expensive generation is a maintainer's one-time job behind committed fixtures — itself
a teaching point.

---

## 12. How this maps to the workshop (the teaching path)

The whole solution is a worked instance of the vision's loop: **measure → baseline → detect → analyze →
recommend → apply → re-measure.** The workshop teaches that *general method*, using this app as the
example. Key teaching artifacts and where they live:

- **The loop end-to-end** — Modules 07 (analytics) and 09 (Fabric) walk instrument → mirror → insights
  → report/Console → apply → measure.
- **The hands-on code-seam module (owner directive).** Attendees are *in the code building the app*, so
  the strongest lesson is to have them **live the code-seam optimization** and walk the full maturity
  ladder in one exercise:
  1. Run the analytics engine → it **detects** the supervisor model-selection waste (measured, not
     hand-authored).
  2. The analyst **stages a code diff** — *introduce `select_deployment_for_turn` + a policy read*.
  3. The attendee **implements the seam in code**, learning *why* optimizability requires seams (the
     base app is single-model; there's no knob until they add one).
  4. **Apply** the now-existing policy (config) and **re-measure** the saving.

  **Detect (analytics) → build the seam (L3 code, human) → tune the policy (L4 config, autonomous) →
  verify.** This reframes the tiered router from a demo cheat into the canonical code-seam example.
- **Rediscovery demo.** "Watch the engine find a known problem (SCEN-001 city-context) on its own from
  data" — the SCEN catalog as the engine's regression suite (§9).
- **Detector kinds & thresholds** — teach *you pick detector kinds, not thresholds* (§6).
- **Module 06 unified** — evaluation stops being a separate appendix; its judges *are* the quality /
  routing / tool dimensions of the scorecard (§5.1).

Supporting workshop docs: `workshop-integration.md` (core-app changes + learning objectives),
`workshop-lab-scope.md` (module outlines, learner-builds-vs-provided), `demo-script.md` (the 60-minute
before/after A/B talk track).

---

## 13. Quick reference / glossary

| Term | Meaning |
|---|---|
| **Operational SoR** | Cosmos DB — where the app reads/writes live state. |
| **Analytical SoR** | Fabric — where telemetry is analyzed and optimization intelligence is produced. |
| **Reverse-ETL** | Writing computed insights/recommendations *back* into Cosmos so the app can act on them. |
| **Node grain / agent execution** | One telemetry row per LangGraph node invocation (🔨 P0) — vs. today's per-turn rollup. |
| **Dimension** | One of the eight optimization axes (§3.1). |
| **Seam** | Where a change is applied: **config** (auto-eligible), **prompt** / **code** (staged, human). |
| **Detector kind** | **counterfactual** / **structural** / **statistical** — determines the threshold source (§6). |
| **Realized vs. predicted complexity** | measured post-hoc (analysis) vs. estimated a-priori (routing) (§4.1). |
| **Price-only vs. behavior-changing** | whether an optimization holds quality constant (projectable) or changes behavior (measured) (§4.2). |
| **Projection function** | per-optimization "which turns it affects × how it changes tokens" → projected saving (§4.3). |
| **Maturity ceiling** | the highest autonomy (L1–L5) a change may reach, set by its seam/risk domain (§8). |
| **Cost per outcome** | spend ÷ confirmed `Trips` — the generalizing business metric. |
| **SCEN catalog** | ✅ today: hand-authored recommendation builders. 🔨 target: rediscovery fixtures / answer key. |

---

### Provenance & maintenance

- **Grounding:** live data figures (agents, token averages, 36% no-`agent_path`, 438 premium turns) are
  from `02_completed` Cosmos, 1,330 turns, 2026-07-31. Code citations: `travel_agents.py` (supervisor +
  sub-agents, `classify_turn_tier`:376, `select_deployment_for_turn`:401), `seed_configuration.py:72`,
  `services/azure_cosmos_db.py`, `01_exercises/evaluation/evaluators/llm_judges.py`.
- **Authority:** the ADRs are binding; this guide narrates them. On any conflict, the ADR wins and this
  guide is updated. Keep the ✅/🔨 markers current as phases P0–P4 land.
- **Related ADRs:** 0001 (surface architecture), 0002/0003 (schema + ingestion), 0004 (data generation),
  0008 (model-selection apply-loop), 0009 (product alignment), **0010 (agent-centric engine — the
  redesign this guide describes).**

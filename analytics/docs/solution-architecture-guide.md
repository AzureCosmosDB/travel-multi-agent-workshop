# Solution Architecture Guide

> **Purpose.** One place that explains how this whole solution fits together — the travel
> multi-agent application **and** the agent analytics & optimization platform built around it — and the
> handful of concepts you need to reason about, operate, and extend either. It is written for **two
> audiences**: humans (contributors and workshop attendees) and **AI agents** exploring the repository
> so they can make grounded suggestions.
>
> **How to read this.** Sections 1–3 are the mental model (the two-system loop, the agents, and the
> *agents × dimensions* lens). Sections 4–9 are the measurement and optimization concepts (the loop,
> the analysis engine, detectors, seams, maturity/risk, the analyst). Sections 10–12 are the data
> plumbing, the cost model, and how it all maps to the workshop. Section 13 is a glossary.
>
> Companion docs: `charter.md` (scope and first principles), `vision/…-vision.md` (the north-star), the
> `optimization-scenarios/` catalog, and the `adr/` decision log for the *why* behind each choice.

---

## 1. What this solution is — two systems, one continuous loop

This is a **travel-planning multi-agent application** that also serves as the worked instance for an
**agent analytics & optimization platform**. The two halves map onto a clean operational/analytical
split:

- **Azure Cosmos DB is the operational system of record.** The application runs against Cosmos: agent
  state, conversations, long-term memory, trips, checkpoints, and per-turn execution telemetry.
- **Microsoft Fabric is the analytical & optimization system of record.** Cosmos is **mirrored** into
  OneLake; notebooks compute insights and recommendations; results are **written back into Cosmos** so
  the running application can read and act on them.

```
Agents → Operational State → Cosmos DB → Fabric Analytics → Optimization Intelligence → Agents
                                   ▲                                        │
                                   └──────────── write-back ────────────────┘
```

That write-back round-trip is the spine of the design: analytics does not merely *observe*, it feeds
recommendations and policies **back** into the running system, closing a continuous
**analyze → recommend → apply → measure** loop. This is the same pattern that recommendation, search
ranking, and ML systems have used for years, brought to agentic applications.

### 1.1 Runtime topology

Three processes run the application; a fourth plane is the analytics layer.

| Plane | Component | Location | Role |
|---|---|---|---|
| App | **Travel API** (FastAPI) | `python/src/app/travel_agents_api.py` | Chat endpoint runs the agent; keyed by `tenantId/userId/sessionId`. |
| App | **Agent runtime** | `python/src/app/travel_agents.py` | The supervisor agent + its sub-agents (§2). |
| App | **MCP server** (FastMCP) | `mcp_server/mcp_http_server.py` | Tools the agents call: memory, summarization, place discovery, trip CRUD. |
| App | **Frontend** (Angular) | `frontend/` | Chat UI **and** the optimization **Console** (`/console/`). |
| Analytics | **Fabric mirror + notebooks** | `analytics/` | Mirror Cosmos → OneLake; compute insights; write results back. |
| Analytics | **Power BI report** | `analytics/…Report.pbix` | The visibility surface (dashboards). |

> **Console vs. report.** The **Console** (in the web app) is the *interactive apply-loop* — inspect
> recommendations, apply a policy, see the effect. The **Power BI report** is the *visibility surface*
> — dashboards over the mirrored analytical data. Two surfaces of the same loop.

---

## 2. The agent system — what we are actually measuring

You cannot measure agents you cannot name. The application is organized around a **supervisor** pattern:

- **One `supervisor` agent** (a ReAct agent built with `create_react_agent`, prompt
  `prompts/supervisor.prompty`) orchestrates every turn. **By default the whole system is
  single-model:** the supervisor and its sub-agents all use the one shared chat model built in
  `services/azure_open_ai.py`, so every turn runs on the default deployment. (Per-turn *model
  selection* is an optimization you introduce — a code seam — not a built-in behavior; see §7.)
- It calls two **tool-backed sub-agents**:
  - **`find_places`** (`@tool("find_places")`) — place discovery and grounding against the `Places`
    catalog (vector/hybrid search via the MCP server).
  - **`create_or_update_itinerary`** (`@tool("create_or_update_itinerary")`) — itinerary assembly and
    trip persistence.
- A **memory subsystem** (via MCP: `store_user_memory` / `recall_memories`, with salience and
  supersession) and a **summarizer** (which compresses history periodically) support every agent.

So the three agents that appear in telemetry — **`supervisor`, `find_places`,
`create_or_update_itinerary`** — are the unit of analysis.

### 2.1 How delegation and `agent_path` work

This is a **ReAct** supervisor, not a hand-wired routing graph: the supervisor **delegates by calling a
sub-agent tool** inside its reasoning loop, and control returns to it with the tool result. There is no
explicit transfer/handoff node.

After a turn completes, the API attributes what happened (`travel_agents_api.py`):

- `delegations` = the sub-agent tools the supervisor invoked, in order.
- `agent_path` = `"supervisor"` followed by those delegations, joined as a **sequence string** — e.g.
  `supervisor`, `supervisor,find_places`, or `supervisor,find_places,create_or_update_itinerary`.
- `agent_selected` = the last delegated sub-agent (else `supervisor`); `handoff_count` = the number of
  delegations.

`agent_path` is therefore the shape of a turn: how many sub-agents ran, which ones, and in what order.

### 2.2 The agent is the unit of analysis

Owners reason about *their agents* — "is the supervisor using the right model? is its prompt routing
efficiently? are memories helping?" The platform must too, which drives one instrumentation principle:
**capture telemetry at the agent-execution grain** — one record per agent (per sub-agent invocation
within a turn), carrying that agent's model, tokens, latency, tool calls, memory recalls, and outcome
link. A per-turn rollup is a derived view for turn-level reporting, but per-agent cost, quality, and
model-fit can only be computed when each agent's execution is recorded on its own. This is what makes
the **Agent Scorecard** (§5) possible.

---

## 3. Agents × dimensions — the core mental model

The central idea: **the agent is the primary lens, and each agent is scored across the eight
optimization dimensions.** That is a matrix — agents down one axis, dimensions across the other:

|  | Agent quality | Workflow eff. | Memory eff. | Routing eff. | Tool util. | Model selection | Cost eff. | Business |
|---|---|---|---|---|---|---|---|---|
| **supervisor** | synthesis quality | hops per turn | recall usage | delegation correctness | over/under-calling | mixed-difficulty ⇒ routing prize | cost per outcome | conversion by path |
| **find_places** | relevant / grounded | redundant calls | recall-biased search | — | tool errors | consistently heavy ⇒ premium justified | cost per result | contribution to confirmed trips |
| **create_or_update_itinerary** | valid / complete / feasible | — | trip-context reuse | — | — | consistently heavy ⇒ premium justified | cost per itinerary | itinerary → confirmed trip |

Each cell resolves to a **health state** — *healthy / watch / unhealthy* — computed by the analysis
engine (§6), alongside any detected opportunity and its apply action. The per-agent **Agent Scorecard**
is the "how is each of my agents doing?" view.

> **Model-fit is a per-agent question, not a fleet-wide one.** The `supervisor` handles a mix of very
> light turns (a greeting, an acknowledgement) and occasional heavy ones (synthesizing a full plan), so
> it is the model-*routing* prize — a cheaper model is fine for the light majority. The sub-agents are
> consistently heavy (a place search or an itinerary build does real work), so a capable model is
> justified. A blanket "use a cheaper model" recommendation would be wrong; a *per-agent* one is right.
> For example, a supervisor-only turn may emit a few hundred output tokens while a full itinerary turn
> emits several thousand — an order-of-magnitude spread the scorecard makes visible.

### 3.1 The eight optimization dimensions

The canonical axes (catalog in `optimization-scenarios/`). Confirmed-trip status (`Trips.status`) is the
shared **outcome anchor** — every dimension is ultimately judged by whether it moves business outcomes.

| Dimension | What it means here | Primary signal | Typical fix seam |
|---|---|---|---|
| **Agent quality** | correct, helpful, complete responses | LLM-judge (answer-quality/correctness), trip completion | prompt |
| **Workflow efficiency** | fewest turns/hops/latency to an outcome | `agent_path`, `handoff_count`, turns-to-first-result | prompt / routing |
| **Memory effectiveness** | memories recalled *and* improving outcomes | recall usage, salience, supersession | prompt / config |
| **Routing effectiveness** | supervisor delegates to the right sub-agent | `agent_path` vs. expected, delegation-avoidance | prompt |
| **Tool utilization** | tools called when useful, not wastefully | tool calls, over-/under-calling | prompt / config |
| **Model selection** | right model for the task's difficulty | realized complexity × model, per agent | config / model-routing |
| **Cost efficiency** | tokens / \$ per successful outcome | tokens, cached tokens ÷ confirmed trips | prompt / config / model |
| **Business outcomes** | bookings made — the anchor success signal | `Trips.status` | served by all of the above |

---

## 4. The measurement framework — the loop every optimization walks

Every optimization follows the same five-step loop:

> **instrument → detect (in data) → recommend (a card) → apply (a seam-appropriate action) → verify (before/after)**

A good optimization is **realistic**, **detectable from data we already capture**, **fixable at a safe
seam**, and **measurable** after the fix. Three framework concepts make this rigorous.

### 4.1 Two notions of "complexity"

"How do we determine task complexity to pick a model?" has two distinct answers that are easy to
conflate:

- **Realized complexity (post-hoc, for *analysis*).** Measured from execution — sub-agents activated,
  output/reasoning tokens, tool calls. It is a clean, monotonic signal (more nodes and more tokens =
  more work) and powers the per-agent **model-fit** view.
- **Predicted complexity (a-priori, for *routing*).** To pick a model *before* the turn runs you need a
  predictor — a lightweight classifier or a confidence cascade. This is the harder problem; it is
  *itself* an optimization the platform recommends, and its quality is then measured against realized
  complexity and outcome.

The reference application ships a simple a-priori predictor — a keyword-based turn classifier
(`classify_turn_tier`) that labels short greetings as *trivial* and explicit planning asks as *complex*.
It is intentionally conservative and coarse; the analytics layer's **measured** realized complexity is
the richer signal and typically reveals more model-selection opportunity than a keyword rule can.

### 4.2 Price-only vs. behavior-changing (how business impact generalizes)

Optimizations split by *what they touch*, which decides how honestly impact can be projected:

- **Price-only** (e.g., route light turns to a cheaper model): quality and behavior are held constant,
  so cost ↓ ⇒ **cost per outcome ↓**. Safe to *project*.
- **Behavior-changing** (e.g., a prompt rule that changes routing): any conversion lift is a
  **hypothesis confirmed by measured before/after** (the funnel), **never a projected number**.

`cost per outcome` (spend ÷ confirmed trips) is the generalizing business metric; reduced turns and
latency are proxies that feed tokens → cost.

### 4.3 Projection functions and the What-If view

Every recommendation carries a **projection function** — a description of *which turns it affects and
how it changes their tokens/turns* — so the engine estimates a projected saving the same way for all.
The **Projected Impact / What-If** surface shows **baseline vs. optimized cost** (projected, then
realized once applied) with saving \$/%, a **usage-scaling control** ("at N turns/day ≈ \$X/month"), and
**cost per outcome** before/after. This is the "show the impact immediately" view — and it
**generalizes** the model-selection counterfactual to every optimization.

---

## 5. The analysis engine — three layers

```
Agent execution + memory subsystem          (1) INSTRUMENTATION → per-agent telemetry
        │  nodes, delegations, tool calls, tokens, recalls, salience, outcomes
        ▼
Fabric: baselines + detectors + LLM analyst (2) ANALYSIS ENGINE (the "brain")
        │  per (agent × dimension) scorecards; anomalies vs. baseline/cohort/SLO;
        │  the analyst turns anomalies + traces into ranked, explained recommendations
        ▼
Agent Scorecards · Portfolio · Discovered Opportunities · What-If → apply → re-measure
                                            (3) SURFACES + the apply-loop
```

- **Layer 1 — Instrumentation.** Capture one record per agent execution: agent, model deployment,
  input/output/reasoning tokens, latency, tool calls, memory recall, measured complexity, and an
  outcome link. Raw per-turn telemetry lands in Cosmos and is attributed to agent executions for
  per-agent analysis (§2.2).
- **Layer 2 — The analysis engine.** Two tiers, both in Fabric, both written back to Cosmos:
  **(2a) statistical detectors** derive baselines and thresholds from the data; **(2b) an LLM analyst**
  turns ranked anomalies plus representative traces into structured recommendation cards. Detailed in
  §6 and §9.
- **Layer 3 — Surfaces.** The Agent Scorecard (primary), a Portfolio/Overview across the eight
  dimensions, a Discovered-Opportunities feed, the Projected Impact / What-If view, and dimension
  deep-dives (Model Selection, Memory Intelligence, Business Impact).

### 5.1 The quality signal — reuse the evaluation harness

The agent-quality, routing, and tool dimensions do not need a bespoke judge: the solution includes an
**LLM-as-judge evaluation harness** (`evaluation/`) whose evaluators (`answer_quality`, `correctness`,
reference-based; `humanness`, reference-free) and suites (`e2e`, `routing`, `tool_usage`) map directly
onto those dimensions, with labeled datasets for calibration. Three adaptations make it the scorecard's
quality signal: (1) a **reference-free** mode for live turns (judge groundedness against the retrieved
places); (2) **per-agent role rubrics** (`find_places` → relevant/grounded; `create_or_update_itinerary`
→ valid/complete/feasible; `supervisor` → coherent synthesis + correct routing); (3) **calibration**
against the labeled datasets. Evaluation is thus a first-class *source* of the quality dimensions, not a
separate appendix.

### 5.2 Scenarios as fixtures

The `optimization-scenarios/` catalog is a library of known optimization patterns. It plays two roles:
**teaching examples** (each is a worked walk up the maturity ladder) and the engine's
**rediscovery/regression fixtures** — known issues the detectors and analyst are expected to surface
from data on their own (§9). The engine's job is to *discover* issues from telemetry; the catalog is the
answer key that proves it does.

---

## 6. Detectors and thresholds — three kinds, not one

The worry "what thresholds are healthy vs. unhealthy?" mostly dissolves once detectors are separated by
*kind* — and the two most valuable kinds need **no authored thresholds**:

| Kind | Asks | Threshold source | Needs history? |
|---|---|---|---|
| **Counterfactual** | "re-simulate a change over historical turns — is the saving *material*?" | materiality (≥X% of spend / ≥\$Y/mo) | **no** — any volume |
| **Structural / rule** | "is this pattern *definitionally* wrong?" (repeated tool call, superseded memory recalled, delegation-avoidance) | the rule itself | **no** — fires immediately |
| **Statistical** | "did this metric drift from its baseline or an SLO?" | derived (z-score / percentile / rolling window) or owner **SLO** | **yes** |

The two non-statistical kinds work at any volume with no history — e.g. a **counterfactual** re-pricing
of low-complexity turns running on a premium model, or a **structural** rule that flags a turn calling
the same sub-agent tool twice in a row. So "what thresholds?" resolves three ways: worth-acting-on
(counterfactual), a definitional rule (structural), or **derived** from the data (statistical) — never
hand-picked.

**Per-dimension detector set:**

| Dimension | Metric | Kind | Threshold source |
|---|---|---|---|
| Model selection / cost | low realized-complexity turns on a premium model (per agent) | counterfactual | re-priced saving materiality |
| Workflow efficiency | repeated node / redundant step; costly non-converting path | structural + cohort | rule; cohort |
| Memory effectiveness | superseded recalled; high-salience never recalled; low-salience bloat | structural + cohort | rule; recall-hit vs. -miss conversion |
| Routing effectiveness | `agent_path` vs. expected; delegation-avoidance | structural + statistical | eval rule + drift |
| Tool utilization | over/under-calling; tool errors | structural + statistical | eval rule + baseline |
| Agent quality | LLM-judge score per agent | statistical + SLO | drift + owner target |
| Cost efficiency | cost per outcome (agent contribution) | statistical + cohort | baseline + cohort |
| Business outcomes | conversion by path/agent | cohort + funnel | cohort |

**Windows and cold-start.** Baselines use rolling, adaptive windows (last N turns / T days); cohort
baselines span the current set. When data is thin, lean on the **counterfactual + structural** kinds
(which work at any volume), treat seeded config constants as **priors**, and **activate statistical
detectors only past a minimum sample size** (suppressed, not noisy, before that). The teaching line:
*you don't hand-pick thresholds; you pick detector kinds* — and only the statistical few carry a
(derived) one.

---

## 7. The optimization seam ladder — what "apply" means

The most consequential architecture concept: **optimizations live on a spectrum of *seams*, and the
seam decides both *how* you apply an optimization and *how autonomously* you can.** An optimization is
only auto-applyable if the application was **built to expose the knob**; building the knob is itself a
one-time, human-governed change.

| Seam | Example | "Apply" = | Autonomy ceiling |
|---|---|---|---|
| **Config / policy** (a knob the app *already reads*) | tier→model map, thresholds, memory salience/retention | flip a policy document in Cosmos (Console **Apply**) | **autonomous** |
| **Prompt** (`.prompty` text) | add a supervisor rule | stage a `{file, add}` change; a human reviews and deploys | **assisted (human-approved)** |
| **Code / new mechanism** (no knob exists yet) | *introduce* per-turn model routing on a single-model app | stage a diff/PR; a human builds, merges, deploys | **assisted (human-governed)** |

**Model selection is the canonical *code* seam.** Because the application is single-model by default
(§2), "route the supervisor's light turns to a cheaper model" is **not** a config flip — it is the code
change that *creates* a per-turn model selector and a policy for it to read. Only **after** that seam
exists does ongoing tuning (the tier→model map, thresholds) become an auto-applyable **config** policy.
This is the whole lesson: *to make an agent app optimizable, you deliberately instrument seams.*

**How a prompt or code recommendation is applied.** The apply-loop distinguishes **policy** changes
(written straight to a Cosmos policy document the app reads live) from **staged changes** (a
`{file, add|diff}` proposal recorded as `apply_mode: "staged_change"`, never active at runtime, for a
human to review and deploy). The analyst *generates* the staged diff; **arbitrary code is never
auto-applied** — the hard ceiling of the risk model.

## 7.1 The optimization lifecycle — a state machine

Every discovered opportunity moves through the same lifecycle. The seam (§7) decides only *how* the
apply and revert transitions happen — automatically for **config**, human-attested for **prompt/code**.

```
                                   ┌─ diagnostic (insight-only): stops here, no apply ─┐
                                   │                                                   ▼
Discovered ──▶ Projected ──▶ (appliable?) ──▶ Apply ──▶ Applied ──▶ Observing ──▶ Re-measured ─┬─▶ Kept
              (What-If:                          │       (active)     (dwell        (verdict)    │
               predicted                         │                     window)                   └─▶ Reverted
               impact)              auto (config) ┤
                                    attested (prompt/code)
```

| State | Meaning | Who drives it |
|---|---|---|
| **Discovered** | A detector surfaced an anomaly for an (agent × dimension). | engine |
| **Projected** | The What-If view attaches a **predicted impact** — a real projected number for *price-only* changes; a *hypothesis to be confirmed* for *behavior-changing* ones (§4.2). | engine |
| **(appliable?)** | Branch: **diagnostic** items are insight-only and end here; the rest carry an apply action. | engine |
| **Apply** | The change takes effect. **Config:** written to the policy document, live immediately (auto / autonomous). **Prompt/code:** the human deploys out of band, then **attests** it (see below). | human or autonomous |
| **Applied (active)** | The optimization is in effect; the moment of go-live is **timestamped** as the measurement boundary. | — |
| **Observing** | A dwell window accrues enough post-apply turns for a statistically meaningful verdict (suppressed before the minimum sample). | engine |
| **Re-measured** | The verdict: compares **new actual** vs. **predicted** vs. **prior baseline**, yielding *confirmed* / *insufficient* / *adverse*. | engine |
| **Kept** | Verdict confirmed (or acceptable); the change stays. | — |
| **Reverted** | Verdict adverse or insufficient — the change is rolled back (or a human decides to). | human or autonomous |

**Apply and revert are seam-dependent — this is the crux:**

- **Config seam (the tool owns the state).** Apply and revert are **automatic and reversible** — flip
  the policy document to `active` or back. This makes an autonomous **measure → verdict → auto-revert
  guard** possible: apply, observe, and if the measured verdict is adverse/insufficient, revert without
  a human. This is the safety loop that lets the lower-risk domains reach L4/L5.

- **Prompt/code seam (the tool cannot observe the real code).** The platform holds only a *record of
  intent*; it cannot know whether a diff was merged, deployed, or reverted. So it deliberately does
  **not** model the deployment pipeline (no `merged` / `tested` / `in-production` substates — those are
  unverifiable claims that drift from reality and belong to your normal PR/CI/CD process). Instead the
  two transitions that depend on out-of-band work are **human-attested via a confirmation gate**:
  - **Apply/Deploy:** the human deploys the staged diff, then confirms *"this change is deployed"* →
    state → `deployed`, **timestamped** as the measurement boundary.
  - **Revert:** clicking Revert opens a confirmation — *"Confirm the code has been reverted"* — and only
    on confirmation does the tool flip the recorded state back (and stamp the revert time so re-measure
    stops attributing turns to it).

  The confirmation is doing real work: it keeps the tool's recorded state honest about a world it can't
  observe, and it captures the **effective time boundary** the re-measure step needs. There is no
  auto-revert on this seam — reverting is itself a human-governed change.

**Everything is audited.** Every transition records who, when, and by what (`apply_policy` / `revert`
carry an actor), including the human attestations. That audit trail — measurable, reversible, auditable
— is precisely what makes any autonomy safe to grant.

---

## 8. Maturity and risk models — how a seam sets the ceiling

A five-level maturity ladder runs from observation to self-adaptation:

| Level | Name | What the platform does | Human role |
|---|---|---|---|
| **L1** | Visibility | Dashboards surface the metric | identify & implement |
| **L2** | Recommendations | Platform recommends a fix | review & approve |
| **L3** | Assisted | Generates the concrete change + impact analysis | approve/reject before deploy |
| **L4** | Autonomous | For approved **lower-risk** domains: auto-apply + validate (reversible, auditable) | set policy & audit |
| **L5** | Adaptive | Fleets self-tune lower-risk domains; higher-risk stays governed | govern the envelope |

**Risk domains set the L4/L5 ceiling:**

- **Lower-risk → autonomous-eligible:** memory salience tuning, retention policies, retrieval weighting,
  routing thresholds, tool-selection policies, model-selection policies, cost policies. These are
  **parameters/policies** — bounded, reversible, measurable → the **config** seam.
- **Higher-risk → human-governed:** prompt modifications, workflow redesign, agent-instruction and
  capability changes, code generation, deployment changes → the **prompt/code** seams.

> **Counter-intuitive but load-bearing:** a prompt edit *feels* safe (it's just text), but prompt
> modifications are classified **higher-risk / human-governed**. So a prompt-rule fix is a great
> L1→L3 example but **caps at Assisted (L3)**. The optimizations that truly demonstrate **L4/L5
> self-adaptation** are the **policy/threshold** ones — which is why the design deliberately includes
> both kinds.

The map is: counterfactual/structural detections → config/structural fixes (can reach L4/L5);
statistical/quality anomalies → regressions a human investigates (L2/L3).

> **Honesty caveat.** With synthetic workshop data there is no real business-outcome signal, so an L4
> "validate it improved outcomes" step demonstrates the *mechanism and safety loop*, not proof. L5 is
> framed conceptually. Say so plainly wherever it applies.

---

## 9. The LLM analyst — guardrails and rediscovery

The analyst (Layer 2b) consumes detector outputs (anomalies per agent × dimension) plus representative
traces and fix-seam metadata, and emits ranked, structured **recommendation cards**:

```
{ agent, dimension, evidence[], proposed_change{ seam, target, diff|value },
  autonomy_ceiling, apply_mode, projected_impact }
```

**Five guardrails** keep it useful and safe:

1. **LLM proposes, engine computes.** The analyst decides *which agent / dimension / change / why*
   (qualitative); a deterministic **projection function** computes the **saving** (quantitative). The
   LLM never invents a dollar figure — this kills hallucinated savings.
2. **Bounded to known seams.** Output is a *structured* card against a config knob / prompt file / code
   diff — never free-form; no unknown action space.
3. **Grounded and cited.** Every card must cite its detector evidence and sample traces; uncited claims
   are rejected.
4. **Risk-gated apply.** The seam sets `apply_mode` automatically: **config → auto**; **prompt / code →
   staged diff for human review**. The LLM does not choose its own autonomy.
5. **Human approval** for anything above the auto ceiling.

**Rediscovery as a regression suite.** The scenario catalog (§5.2) is the answer key: feed the engine
the known-issue fixtures and **assert it rediscovers** them from data (a redundant-delegation structural
case, a model-selection counterfactual, a stale-memory case, a context re-ask). A miss is a real gap — a
missing detector or a weak analyst prompt — i.e. a **failing test**, not a matter of taste. "Watch the
engine find a known problem on its own" is also a strong teaching moment.

---

## 10. Data architecture — Cosmos, the mirror, and the write-back

**Operational store (Cosmos `TravelAssistant`).** The application provisions these containers:

- **App state:** `Sessions`, `Messages`, `Places`, `Trips` (+ `TripsByDestination`), `Users`,
  `ApiEvents`, `Debug` (per-turn execution telemetry), `Checkpoints` (LangGraph state).
- **Memory subsystem:** `memories`, `memories_turns`, `memories_summaries`, `Counter`.
- **Analytics (optional):** `OptimizationPolicies` (the policy documents the app reads), `OptimizationTurns`
  (per-turn analytical rows **derived from `Debug`**), `OptimizationInsights` (computed
  recommendations/KPIs written back from Fabric), `Configuration` (e.g. model pricing rows).

Most containers use a hierarchical partition key `[tenantId, userId, sessionId]`. All data access is
centralized in `services/azure_cosmos_db.py` (reuse the accessors; don't create new clients).

**Normalization.** Operational state maps to a framework-agnostic schema of execution primitives
(`AgentRun`, `AgentStep`, `AgentTransition`, `ToolInvocation`, `MemoryEvent`, `Checkpoint`,
`EvaluationResult`, `TokenUsage`, `UserSession`, `WorkflowExecution`) so analytics stays portable across
agent frameworks.

**Mirror + write-back.** Fabric **mirrors** the relevant Cosmos containers into OneLake; notebooks
compute insights over the mirror and **write results back into Cosmos** (`OptimizationInsights`), so the
app, the Console, and the report all read a single source of truth. Because a deployed app cannot reach
a Fabric SQL endpoint via managed identity, **Cosmos is the operational bridge** for that write-back.

**Surfaces.** The **Power BI report** is the visibility surface (dashboards over the mirrored data). The
**Console** in the web app is the interactive apply-loop (inspect a recommendation, apply a policy or
stage a change, re-measure).

---

## 11. Cost and data-generation strategy

Running **live agents** to generate telemetry is expensive (hours and a large token bill). The design
keeps the attendee cost near zero by **separating generating telemetry from running the analysis
engine**:

- **Agent-execution-grain capture is cost-neutral.** The agents already run and already make their LLM
  calls each turn; instrumentation simply *records* each execution instead of discarding the detail.
  More rows, not more LLM calls.
- **Telemetry is fixture-first.** A **golden fixture** is captured once (a single, richer live run,
  exported and committed); everyone else loads it offline via the seed path → \$0. A **traffic
  simulator** fabricates additional agent-structured executions with realistic distributions — still no
  LLM — for volume and "watch it move" demos.
- **Engine LLM cost is bounded by pre-baking.** The judge and analyst run **once**; their outputs
  (per-agent quality scores, recommendation cards) are committed as fixtures, so the platform appears
  fully populated for \$0. The teaching moment is reading the code that *produces* them, and optionally
  running the judge on a handful of live turns (cents, not hours).

The result: load fixtures → run the Fabric analytics (capacity cost only, no tokens) → explore
scorecards and opportunities → apply a policy → re-measure. No live agents, no hours, no token bill.

---

## 12. How this maps to the workshop

The whole solution is a worked instance of the loop **measure → baseline → detect → analyze →
recommend → apply → re-measure**, and the workshop teaches that *general method* using this app as the
example:

- **The loop end-to-end** — modules walk instrument → mirror → insights → report/Console → apply →
  measure.
- **The hands-on code-seam module.** Attendees are *in the code building the app*, so the strongest
  lesson is to have them **live a code-seam optimization** and walk the full maturity ladder in one
  exercise:
  1. Run the analysis engine → it **detects** a model-selection opportunity (measured, not
     hand-authored).
  2. The analyst **stages a code diff** — introduce the per-turn model selector and a policy read.
  3. The attendee **implements the seam in code**, learning *why* optimizability requires seams (the app
     is single-model; there's no knob until they add one).
  4. **Apply** the now-existing policy (config) and **re-measure** the saving.

  Detect (analytics) → build the seam (code, human) → tune the policy (config, autonomous) → verify.
- **Rediscovery demo** — watch the engine surface a known problem from data on its own (§9).
- **Detector kinds** — teach *you pick detector kinds, not thresholds* (§6).
- **Evaluation, unified** — the eval harness's judges *are* the quality/routing/tool dimensions of the
  scorecard (§5.1), not a separate step.

---

## 13. Glossary

| Term | Meaning |
|---|---|
| **Operational SoR** | Cosmos DB — where the app reads/writes live state. |
| **Analytical SoR** | Fabric — where telemetry is analyzed and optimization intelligence is produced. |
| **Write-back** | Writing computed insights/recommendations back into Cosmos so the app can act on them. |
| **Agent-execution grain** | One telemetry record per sub-agent invocation, vs. a per-turn rollup. |
| **`agent_path`** | The sequence of agents in a turn: `"supervisor"` + the sub-agents it delegated to. |
| **Dimension** | One of the eight optimization axes (§3.1). |
| **Seam** | Where a change is applied: **config** (auto-eligible), **prompt** / **code** (staged, human). |
| **Realized vs. predicted complexity** | measured post-hoc (analysis) vs. estimated a-priori (routing) (§4.1). |
| **Price-only vs. behavior-changing** | holds quality constant (projectable) vs. changes behavior (measured) (§4.2). |
| **Projection function** | per-optimization "which turns it affects × how it changes tokens" → projected saving (§4.3). |
| **Detector kind** | counterfactual / structural / statistical — determines the threshold source (§6). |
| **Autonomy ceiling** | the highest maturity level (L1–L5) a change may reach, set by its seam/risk domain (§8). |
| **Confirmation gate** | a human attestation ("deployed" / "reverted") that flips the tool's recorded state for a prompt/code change it cannot observe, and stamps the measurement boundary (§7.1). |
| **Measurement boundary** | the timestamp when a change went live (or was reverted); re-measure windows before/after around it (§7.1). |
| **Cost per outcome** | spend ÷ confirmed trips — the generalizing business metric. |

---

*For the decisions and evidence behind this architecture, see the `adr/` decision log; for scope and
first principles, see `charter.md`.*

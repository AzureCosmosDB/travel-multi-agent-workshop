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

**The judge is the signal; the runner is pluggable.** Keep two layers distinct. The **judge** — the
scoring intelligence — is a plain LLM-as-judge (a model call against a rubric) with no vendor
dependency. The **runner** — what feeds examples to the judge over a dataset and aggregates results — is,
in the reference suites, LangSmith's `evaluate()` harness (the one piece that needs a LangSmith key). That
is a convenience, **not an architectural requirement**: what the platform actually depends on is the
normalized **`EvaluationResult`** primitive, which *any* evaluator can emit — the built-in judge,
LangSmith, Arize Phoenix, MLflow LLM-as-judge, Ragas, OpenAI Evals, or human labels. So generalizing to
other agent frameworks does **not** mandate LangSmith (or any single tool); it mandates *an* evaluation
signal mapped to `EvaluationResult`, with the evaluator chosen per ecosystem. The quality dimension
depends on quality being *measured and normalized*, not on *who measures it*.

### 5.2 How the engine is validated

Because the engine *discovers* issues rather than enumerating them, it is validated on its **detectors** —
with ground truth **constructed, not discovered**:

1. **Fixtures test patterns, keyed to `(detector-kind × dimension)`** (§6), independent of any one app's
   specifics — so the same suite validates the engine across agent apps. (A repeated-node structural
   fixture, a low-complexity-on-premium counterfactual fixture, and so on.)
2. **Ground truth by construction (synthetic injection).** Because schema-primitive telemetry can be
   fabricated (§11), a fixture **injects a known issue of known magnitude** and asserts the engine
   recovers it — including the **quantity** (the projection should recover ≈ the injected saving). The
   truth is definitional, not a matter of opinion.
3. **Matched positive + negative pairs.** Every detector gets an injected-issue dataset (**must fire**)
   and a clean/justified dataset (**must stay silent**) — validating both **recall** and **precision**
   (so a heavy agent that legitimately belongs on a premium model does *not* get flagged).
4. **Coverage is measured over the detector matrix.** Every `(dimension × detector-kind)` cell should
   carry a positive and a negative fixture, so completeness is checkable rather than guessed.

**The suite is living.** Unknown-unknowns cannot be pre-tested, so the fixture set grows from production:
every human-labeled discovery in the outcome ledger (§9.2) becomes a new fixture — a confirmed novel
finding as a positive, a reverted false alarm as a negative — and **generalization** is checked by running
the detectors on held-out telemetry.

The **scenario catalog** (`optimization-scenarios/`) complements this as **teaching narratives** — worked,
end-to-end walks up the maturity ladder on the real app — and as a handful of realistic **acceptance
anchors** that exercise the full pipeline against familiar cases.

### 5.3 Operating model — the three planes

The judge and analyst are **analytical-plane** components. They do not run on the user's turn path, and
they are not embedded in the application; they are coupled to the app **only through Cosmos**.

| Plane | Runs | Contains | Cadence |
|---|---|---|---|
| **App runtime** (deployed containers) | the request path | the agents (the *subject* being optimized); reads policy documents; emits telemetry | synchronous, per turn |
| **Analytical** (Fabric notebook / batch job) | offline, over mirrored data | detectors, the **judge**, the **analyst**, projection + calibration | batch, scheduled |
| **Human / governance** (Console + PR/CI/CD) | out of band | review, apply config, merge staged diffs, attest deploy/revert | on demand |

The optimizer LLMs (**judge, analyst**) live in the **analytical plane** — a Fabric notebook or a batch
service — never in the app request path. What lands back in the app source is not the optimizer but the
**result** of an optimization: a **config policy** the app reads (auto), or a **staged diff** a human
merges (prompt/code). The analyst *proposes* the change as data; a human or a guardrail *disposes*. This
decoupling keeps analysis cost and latency off user turns, gives the analyst zero runtime authority, and
lets it reason over large volumes of history in batch. A code-seam change ends up in source only because
a **human merges the proposed diff** — not because the LLM operates inside the codebase.

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
| **Observing** | A dwell window accrues enough post-apply samples for a statistically meaningful verdict (suppressed before the minimum sample — which is *derived*, not fixed; see below). | engine |
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

**What sets the *minimum sample* for a verdict?** Not a magic constant — it is **derived from statistical
power**: the number of post-apply samples needed to separate the expected effect from noise at a chosen
confidence. It grows for *smaller* effects and *noisier* metrics, and shrinks for large, clean ones.
Concretely it is a **confidence-interval / sequential-test stopping rule** — declare *confirmed* when the
interval on the effect excludes "no effect" in the good direction, *adverse* the other way, *insufficient*
when it straddles "not worth it" — plus an **outcome-events floor** for proportion metrics like conversion
(you need enough *confirmed trips*, not just turns) and a **time-span floor** so one hour/day of traffic
cannot bias the verdict. The **owner sets the policy** (target confidence, minimum effect worth acting on,
minimum outcome events); the **engine computes the n**. Counterfactual and structural detectors need
essentially no minimum — this dwell applies to the statistical verdict (consistent with §6).

## 7.2 The policy store — a canonical envelope, an app-specific body

The config seam is realized by a **policy store**: small, versioned, reversible documents in Cosmos
(`OptimizationPolicies`) the app reads at request time. The way to make it **adoptable and future-proof
without being impossible** is to be **prescriptive about the envelope and the domain taxonomy, and open
about the body** — the §10.3 adapter split, applied to policy.

**Prescriptive — the envelope (stable across apps).** Every policy shares a generic envelope the platform
operates on (stage/apply/revert/observe/measure, §7.1) without understanding the app:

```
{ policyId, domain,          // domain from the taxonomy below
  scope,                     // global | tenant | user | agent
  status,                    // proposed|staged → active → reverted
  enabled, version,
  apply_mode,                // config (auto) | staged_change (human)
  autonomy_ceiling,          // the maturity ceiling this domain may reach
  measurement_boundary,      // go-live timestamp for re-measure
  audit[],                   // { ts, action, by } — every transition
  params { … } }             // APP-DEFINED body (opaque to the platform)
```

**Prescriptive — the domain taxonomy (broadly recognized).** There *is* a canonical set of tunable
surfaces for agentic apps — it maps onto the eight dimensions, the vision's lower-risk domains, and
standard inference knobs. Prescribing the *domains* (not their values) is what lets users adopt the design
and lets the engine reason across apps:

| Policy domain | Tunes | Recognized knobs (examples) | This app |
|---|---|---|---|
| **Model selection / routing** | model per agent/task/complexity | tier→deployment map, complexity thresholds, fallback/cascade | ✓ (the taught seam) |
| **Generation parameters** | per-agent inference | temperature, top_p, max_tokens, reasoning effort, stop | — (uses defaults) |
| **Routing / delegation** | when/whether to delegate | delegation confidence, max handoffs/hops, recursion limit | partial (implicit) |
| **Tool use** | which tools, how much | enabled tools, call budget, timeout/retry, parallel vs. serial | some (`find_places`) |
| **Memory** | recall / salience / retention | top-k, salience threshold, decay/recency weight, TTL, supersession | ✓ |
| **Retrieval / RAG** | grounding search | top-k, similarity threshold, hybrid weights, rerank | ✓ (Places) |
| **Context / summarization** | history & context budget | summarize cadence, context-token budget, truncation depth | ✓ (summarizer) |
| **Cost / budget** | spend ceilings | per-turn/session token or \$ cap, degrade-to-cheaper trigger | — |
| **Prompt selection** | which prompt variant | prompt version/id, A/B split | — (DSPy/GEPA output lands here) |
| **Concurrency / latency** | runtime SLOs | timeouts, max parallelism, rate limits | — |
| **Evaluation / SLO** | quality targets to measure against | min judge score, SLO %, sample/effect floors | cross-cutting |
| **Autonomy / governance** | how policies are applied | per-domain autonomy ceiling, guard/rollback thresholds, verdict confidence & min sample | cross-cutting (governs §7.1) |

**Open — the body.** The `params` inside each domain are **app-specific and cannot be pre-specified**:
this app's model-selection `params` hold a `tier→deployment` map and a complexity classifier; another
app's hold a cascade with different tiers. The platform treats `params` as **opaque**; the **app's
adapter** interprets them. So *future-proofing lives in the contract and lifecycle — the envelope, the
domain taxonomy, and the stage/apply/revert/measure loop — not in a universal parameter set*, which is
both impossible to fix and would break on real apps. Users adopt the envelope + taxonomy + lifecycle for
free and fill in the bodies their app needs.

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

**Acceptance on familiar cases.** Running the engine against the scenario catalog and confirming it
surfaces those cases end-to-end (a redundant-delegation structural case, a model-selection
counterfactual, a stale-memory case, a context re-ask) is a realistic **acceptance** check on the app —
and a strong teaching moment ("watch it find a known problem on its own"). The systematic **recall +
precision** validation lives in the synthetic detector fixtures (§5.2).

### 9.1 How the analyst proposes prompt and code changes without owning the codebase

A fair objection: how can the analyst recommend a **prompt** — let alone a **code** — change if it has
no intimate knowledge of the codebase? The design answers this four ways, and the answer is *not* "the
LLM memorizes the repo."

1. **The seam is pre-identified and localized.** The detector already names *which agent* and *which
   dimension*, and the recommended change targets a **catalogued seam** — a specific prompt file, or a
   known code insertion point (e.g. "introduce a per-turn model selector"). The analyst is not asked to
   reason over the whole system; it works at one small, named location.
2. **Code context is *given*, not memorized.** The relevant slice — the target `.prompty` or the target
   function(s), surrounding code, and the app's conventions — is **retrieved and injected** into the
   analyst's prompt, exactly as a coding assistant is fed the files it edits. It reasons over the
   provided context, not a mental model of the repo.
3. **Ambition scales with the seam.** A **prompt** is a self-contained artifact, so proposals there are
   reliable and can be *optimized* automatically (see DSPy/GEPA below). A **code** proposal is a
   seam-bounded **draft** produced from the injected context plus a catalogued recipe — a reviewable
   starting diff, not a finished feature.
4. **The output is a proposal for a human, never auto-applied.** The human reviewer *does* have codebase
   knowledge; CI/CD tests it; and the re-measure → revert loop (§7.1) is the safety net. So the analyst
   does not need to be a flawless engineer — it needs to produce a grounded, reviewable diff that a
   human finishes. Repo-wide autonomous code authorship is explicitly out of scope (the risk model caps
   code at human-governed).

The deeper the code context and tooling you give it (repo indexing, a coding agent with test access),
the more ambitious the draft it can produce — but the design never *requires* omniscience, because every
change is **seam-bounded and human-governed**.

> **DSPy and GEPA (the prompt-seam optimizers).**
> - **DSPy** is a framework for *programming* LLMs instead of hand-writing prompt strings: you declare a
>   module by its input→output **signature** and a **metric**, and DSPy **compiles** it — automatically
>   searching over prompt wordings and few-shot examples (optionally weights) to maximize that metric on
>   sample data. Prompt engineering becomes a metric-driven compile step.
> - **GEPA** (Genetic-Pareto) is a *reflective* prompt optimizer (usable within DSPy): it runs
>   candidate prompts, collects execution traces and natural-language feedback from the metric, uses an
>   LLM to **reflect** on failures and **mutate** the prompt, and keeps a **Pareto frontier** of the best
>   candidates (evolutionary search) — reaching strong quality in comparatively few trials.
>
> For the **prompt seam** these are the mechanism: generate and *score* candidate prompt revisions
> against held-out turns, using the **judge (§5.1) as the metric** — turning "here's one suggested
> rewrite" into "here's an optimized rewrite proven better on held-out data."

### 9.2 How the system learns — the feedback loop

By default the analyst does **not** fine-tune itself; it is a stateless call per run. The system instead
learns through a **data feedback loop**, so it gets better at "what works" without changing any model
weights:

1. **An outcome ledger.** Every recommendation's lifecycle (§7.1) — predicted impact, measured actual,
   and the verdict (*Kept / Reverted-adverse / insufficient*), with actor and timestamp — is recorded in
   `OptimizationInsights`. This ledger grows over time.
2. **Fed back as evidence.** On the next run the analyst is handed that history as context, so it can
   **down-rank patterns that historically underperformed and up-rank ones that delivered**. This is
   retrieval / in-context learning over an outcome memory, not fine-tuning.
3. **Deterministic calibration.** Because *the LLM proposes and the engine computes* (§9, guardrail 1),
   the **projection functions** are corrected by reality: once actual-vs-predicted is measured for an
   optimization type, future projections apply that observed ratio as a calibration factor. The numbers
   get more accurate every cycle, independent of the LLM.
4. **Standing regression.** The rediscovery fixtures (§5.2) continuously verify the analyst still catches
   known issues as its prompt or the data evolve.

The **judge** has its own calibration loop: its scores are checked against the **labeled datasets** and
periodic human spot-checks; disagreement triggers a rubric/prompt recalibration. Optionally — advanced,
not required — the same outcome ledger can drive offline **prompt-optimization (DSPy/GEPA)** or
fine-tuning of the analyst's *own* prompt. This is how the platform realizes a continuous learning loop:
the *system* improves from operational outcomes, even though no single LLM's weights change on the
request path.

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

**Normalization.** All of this operational state is normalized to a single framework-agnostic
**Open Agent Analytics Schema**, so analytics and optimization never bind to one agent framework, one
memory layer, or one evaluator. The schema, how it is realized in this solution, and how it is fed are
detailed in §10.1–§10.3.

**Mirror + write-back.** Fabric **mirrors** the relevant Cosmos containers into OneLake; notebooks
compute insights over the mirror and **write results back into Cosmos** (`OptimizationInsights`), so the
app, the Console, and the report all read a single source of truth. Because a deployed app cannot reach
a Fabric SQL endpoint via managed identity, **Cosmos is the operational bridge** for that write-back.

**Surfaces.** The **Power BI report** is the visibility surface (dashboards over the mirrored data). The
**Console** in the web app is the interactive apply-loop (inspect a recommendation, apply a policy or
stage a change, re-measure).

### 10.1 The Open Agent Analytics Schema, realized

The schema is a small set of **execution primitives** common to any agentic system. Standardizing on
these — rather than on framework-specific objects — is what lets the same detectors, engine, and surfaces
run across frameworks. Here is each primitive and how it is realized in this Cosmos-based solution:

| Primitive | What it captures | Realized here (source → Cosmos) |
|---|---|---|
| **UserSession** | a user's conversational session/thread | `Sessions` (span, `activeAgent`, status) |
| **WorkflowExecution** | one end-to-end turn and its outcome | per-turn row in `Debug` → `OptimizationTurns` (`agent_path`, `handoff_count`, tokens), outcome-linked to `Trips.status` |
| **AgentRun** | one agent's execution within a turn (the agent-execution grain, §2.2) | per sub-agent invocation, from the runtime's per-node streaming events |
| **AgentStep** | a step inside an agent run (a model call / reasoning step) | `on_chat_model_end` per node; message steps in `Messages` |
| **AgentTransition** | a delegation/handoff between agents | supervisor → sub-agent delegations (the `agent_path` sequence, `handoff_count`) |
| **ToolInvocation** | a tool call and its result | tool calls on the turn (`find_places` / `create_or_update_itinerary` + MCP tools); `Messages.toolCalls` |
| **TokenUsage** | tokens consumed per call/turn/agent | `Debug` input/output/cached/total tokens; per-agent at node grain |
| **MemoryEvent** | memory create / recall / supersede / decay | Cosmos Agent Memory Toolkit: `memories` (salience, `superseded_by`, `lastUsedAt`, `ttl`), `memories_turns`, `memories_summaries` |
| **Checkpoint** | persisted agent/graph state | `Checkpoints` (LangGraph `CosmosDBSaver`) |
| **EvaluationResult** | a quality/eval score | emitted by the evaluator (LLM-judge via LangSmith or another runner), normalized per agent/turn (§5.1) |

`Trips.status` is the **outcome anchor** that hangs off `WorkflowExecution` — the business-success signal
every dimension is ultimately judged against. (Some primitives are captured at turn grain today and at
the richer agent-execution grain where per-agent attribution is needed, per §2.2 — the schema is the same
either way.)

### 10.2 How the schema is fed — source adapters

The schema is populated by **source adapters**, one per producing system. An adapter's only job is to
translate its native events into the primitives and land them in Cosmos (the operational SoR); Fabric
then mirrors and builds the gold schema. In this solution there are three, plus the domain outcome:

| Source adapter | Feeds these primitives | How |
|---|---|---|
| **LangGraph / LangChain** (execution) | AgentRun, AgentStep, AgentTransition, ToolInvocation, TokenUsage, Checkpoint | runtime streaming events (per-node model-end, tool calls, delegations) + the `CosmosDBSaver`, captured to `Debug` / `Checkpoints` |
| **Cosmos Agent Memory Toolkit** (memory) | MemoryEvent (+ memory-state: salience, supersession, TTL, recall) | persists the full memory lifecycle as operational state in `memories` / `memories_turns` / `memories_summaries` |
| **LangSmith / evaluator** (evaluation) | EvaluationResult | the LLM-judge, run via LangSmith's harness (or another runner), normalized per agent/turn (§5.1) |
| **App domain** (outcome) | WorkflowExecution outcome | `Trips.status` links each turn/session to a confirmed booking |

The adapters are the **only framework-specific code** in the pipeline. Everything downstream — the mirror,
the normalized schema, the detectors, the engine, the surfaces — is common and unaware of which
frameworks produced the data.

### 10.3 Portability and productization — pluggable adapters (predicated on Cosmos)

Because the framework-specific surface is isolated in the adapters, the platform can be **productized as
importable modules along an (Agent Framework × Evaluator Framework) matrix** over a common core. What is
fixed vs. swappable:

- **Invariant substrate (fixed):** **Cosmos DB as the operational system of record** + Fabric mirror +
  the Open Agent Analytics Schema + the analysis engine (detectors / analyst / projection) + the
  surfaces. The whole design is **predicated on the solution using Cosmos** — that is the foundation, not
  an option.
- **Swappable adapters:**
  - **Agent-framework adapter** — LangGraph here; Microsoft Agent Framework, OpenAI Agents SDK, or a
    custom framework each map their execution events to AgentRun/Step/Transition/ToolInvocation/
    TokenUsage/Checkpoint. OpenTelemetry GenAI semconv and OpenInference are the interop path for
    frameworks that already emit standard traces.
  - **Evaluator adapter** — LangSmith here; Arize Phoenix, MLflow, Ragas, OpenAI Evals, or human labels
    each emit EvaluationResult (§5.1).

> **Can the memory piece be made pluggable too? (the honest answer.)** *At the contract level, yes:* the
> memory adapter's job is to emit **MemoryEvent** + memory-state, and any memory layer that persists
> salience/recall/supersession can feed the memory dimension. *The catch is depth:* the richness of
> **Memory Intelligence** is bounded by what the memory layer instruments. A naive vector store emits only
> "store/retrieve" — no salience, supersession, or decay — so it yields shallow memory analytics. The
> **Cosmos Agent Memory Toolkit is the reference memory adapter precisely because it emits the full
> lifecycle as operational state in Cosmos**, realizing the vision's "analyze what agents *know, remember,
> and persist*," not just what they do. So memory is pluggable at the `MemoryEvent` contract, but flagship
> memory intelligence assumes a lifecycle-instrumenting memory layer; adapting a third-party one is
> possible but delivers only as much memory intelligence as it records (closing the gap means wrapping it
> to emit the missing MemoryEvent signals into Cosmos). Since the whole platform is Cosmos-predicated
> anyway, the Cosmos-native toolkit is the natural first-class choice — the memory adapter that ships
> "batteries included."

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
- **The foundational seam module — build the policy store.** The base app is representative: it hardcodes
  its model and thresholds, with no policy store. The first optimization module has attendees **externalize
  the tunable surface** (model selection, thresholds, memory salience/retention) into a Cosmos policy
  document the app reads at runtime. This is the **entry ticket to autonomy** — building the config seam
  once is what turns every later optimization into an autonomous config flip. (The model/pricing reference
  is *provided* as data; the policy store is *built*.)
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
| **Analytical plane** | where the judge and analyst run (Fabric notebook / batch), off the request path, coupled to the app only via Cosmos (§5.3). |
| **Outcome ledger** | the recorded history of predicted vs. actual vs. verdict per recommendation; fed back as evidence so the system learns (§9.2). |
| **DSPy** | a framework that *compiles* LLM programs — optimizing prompts/examples against a metric instead of hand-writing them (§9.1). |
| **GEPA** | a reflective, evolutionary prompt optimizer (LLM reflects on traces, mutates the prompt, keeps a Pareto frontier) (§9.1). |
| **Open Agent Analytics Schema** | the framework-agnostic set of execution primitives (AgentRun, AgentStep, …, MemoryEvent, EvaluationResult) that all sources normalize into (§10.1). |
| **Source adapter** | the only framework-specific code: translates one system's native events (execution / memory / evaluation) into schema primitives landed in Cosmos (§10.2–§10.3). |
| **Policy envelope** | the app-agnostic fields of a policy document (domain, scope, status, version, apply_mode, autonomy_ceiling, audit, …) the platform operates on; `params` is the app-defined body (§7.2). |
| **Policy domain** | one of the canonical tunable surfaces (model selection, memory, tools, generation params, budget, …) — prescribed as categories, bespoke in their values (§7.2). |
| **Minimum sample** | the derived (not fixed) number of post-apply samples a statistical verdict needs — a power / CI / sequential-test threshold plus outcome-events and time-span floors (§7.1). |

---

*For the decisions and evidence behind this architecture, see the `adr/` decision log; for scope and
first principles, see `charter.md`.*

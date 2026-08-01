# ADR-0010: Agent-centric, data-driven analysis & optimization engine

- **Status:** Proposed
- **Date:** 2026-07-31
- **Deciders:** Mark Brown (@markjbrown), with agent analysis + external research
- **Related:** `../vision/agent-analytics-and-optimization-vision.md`, `../optimization-scenarios/README.md`, `adr-0009-generalize-optimization-framework-product-alignment.md`, `adr-0004-data-generation-redesign.md`, `adr-0001-optimization-loop-surface-architecture.md`, `adr-0008-optimization-apply-loop-model-selection.md`

> **This ADR supersedes the *organizing principle* of the current analytics** (a hand-authored
> scenario catalog surfaced through model-selection-centric dashboards). It **keeps** the plumbing
> (reverse-ETL loop, apply-loop, measurement framework, the 8 dimensions, maturity/risk models) and
> re-centers the product on **agents × dimensions**, driven by a **data-driven analysis engine** that
> *discovers* issues rather than restating a fixed list. It absorbs ADR-0009's Phase 2.

## Context

Reviewing the shipped product, the owner named the fundamental flaw directly:

> "This is an app with multiple agents. Yet nowhere do we see what those agents are, nowhere do we
> measure how those agents are performing… If I was looking at a dashboard for my app I would first
> want to see how each of my agents is performing. Are we using the right model? Is the prompt
> efficient with its routing/tool-calling? Are memories used efficiently? … The active-trip-city-
> context scenario I *reported* — the system should **detect** that. I shouldn't have to call it out.
> I don't like it in our solution because it is not born from the analytics we constructed."

Three defects fall out of this:

1. **No agent as the unit of analysis.** The app is a LangGraph graph of collaborating agents
   (orchestrator/supervisor + `find_places`/hotel·activity·dining, `create_or_update_itinerary`,
   `summarizer`). Telemetry already carries `agent_selected` / `agent_path` (Debug), but **nothing
   rolls up per agent.** The first question an owner asks — *"how is each agent doing?"* — is
   unanswerable in the product. The vision explicitly lists **"Agent performance analysis"** as a
   Level-1 example (vision §Maturity/L1); we never built it.

2. **Scenarios are hand-authored inputs, not discovered outputs.** `SCEN-001…008` were found by
   humans exploring (`optimization-scenarios/README.md` "Discovery methods"). The product then
   *hard-codes* those six as recommendation builders (`build_recommendations()` calls six fixed
   Python functions). A platform that claims to be a general analytics layer must **derive** issues
   from telemetry — the `active-trip-city-context` case is the tell: a human had to report it.

3. **"Complexity" is a keyword heuristic, and it isn't agent-aware.** Model selection pins a model to
   a turn's tier, but the tier comes from `classify_turn_tier()` (`travel_agents.py:376`): a turn is
   `trivial` iff it is **≤6 words and matches a greeting regex**; explicit "plan/itinerary" → complex;
   else routine. It classifies the *user string*, decoupled from *which agent ran* or any *measured*
   difficulty (tokens, tool calls, handoffs, confidence). This is why "how do we determine task
   complexity?" feels like a mystery — because the current answer is *"we guess from word count."*

The owner's two hard, honest questions:
- **"I have no idea what thresholds are the correct ones for healthy vs unhealthy."**
- **"I have no idea how or what analyzes this to then make correct recommendations."**

Both have well-established answers in the field (see Evidence); the current design simply didn't use
them.

## Decision drivers

- **Agent is the primary lens.** Owners reason about *their agents*; the product must too.
- **Discover, don't enumerate.** Issues (including new ones) must fall out of the data via baselines +
  anomaly detection + an analyst, not a frozen scenario list.
- **Thresholds are derived, not authored.** Healthy/unhealthy = relative to *this system's* baselines,
  cohorts, SLOs — adaptive, explainable.
- **Ingest the frameworks' telemetry.** LangGraph execution (nodes, routing, tool calls, tokens) +
  the Cosmos agent-memory toolkit (recall, salience, supersession) are the raw signal.
- **Teach the fundamentals.** The workshop should teach *how to measure and optimize agent apps* —
  the framework and the engine — using this app as the worked instance.
- **Preserve the working seam** (Cosmos operational / Fabric analytical / reverse-ETL / apply-loop).

## The redesign — three layers

```
LangGraph exec + Cosmos memory toolkit                (1) INSTRUMENTATION → per-agent telemetry
        │  (nodes, routing, tool calls, tokens, recalls, salience, outcomes)
        ▼
Fabric: baselines + detectors + LLM-as-analyst        (2) ANALYSIS ENGINE (the missing brain)
        │  per (agent × dimension) scorecards; anomalies vs baseline/cohort/SLO;
        │  analyst turns anomalies+traces into ranked, explained recommendations
        ▼
Agent Scorecards · Portfolio · Discovered Opportunities → apply (policy) → re-measure
                                                      (3) SURFACES + the existing apply-loop
```

### Layer 1 — Instrumentation: capture at the **agent-execution** grain

The current telemetry is **turn-grained** — one `OptimizationTurns` row per turn with `agent_path` as
a *string* and a single `total_tokens` / `model_tier`. That was shaped for the model-selection story
and **cannot attribute cost/quality to an individual agent** within a multi-agent turn (verified live:
for `supervisor,find_places,create_or_update_itinerary` there is one token figure, not one per node).

Re-grain to **one record per agent execution (LangGraph node invocation)** — which the runtime already
emits (we process `on_chat_model_end` per node in the streaming path and currently aggregate it away).
Proposed node-grain schema:

```
{ tenantId, userId, sessionId, turn_id, seq, agent, model_deployment,
  input_tokens, output_tokens, reasoning_tokens, latency_ms,
  tool_calls[], recall_used, complexity, outcome_link, timeStamp }
```

The per-turn view stays a rollup; the **Agent Scorecard reads the node grain**. Also add the missing
dimension signals: an LLM-judge **quality** score, **memory-recall usage** per node, **tool-call
outcomes**, and a **measured complexity** signal (replacing the keyword tier — see below).

### Layer 2 — The analysis engine (this is "what analyzes it")

Two tiers, both in Fabric, both reverse-ETL'd back to Cosmos:

**(2a) Statistical detectors — derive thresholds from the data.**
For each `(agent × dimension × metric)`, compute a **baseline** (mean/median, spread, percentiles)
over a rolling window and flag deviations by:
- **Self-baseline:** z-score / percentile drift (e.g., this agent's cost/turn jumped past its P95).
- **Cohort/relative:** agent-vs-fleet, model-vs-counterfactual (we already price the counterfactual),
  recall-hit vs recall-miss outcomes.
- **SLO:** owner-set targets (e.g., "≥95% of an agent's turns score ≥3/5 on the LLM-judge").
This answers *"what thresholds?"* — **you don't hardcode them; you learn them per system and compare
relatively.** (The current fixed constants — `trivial_max_words=6`, salience 0.8/0.5 — become
*priors/fallbacks*, not the mechanism.)

**(2b) LLM-as-analyst — turn anomalies into recommendations.**
Feed the ranked anomalies + a few representative traces to an LLM analyst that emits a **recommendation
card**: which agent, which dimension, the evidence, a proposed change, the fix seam, and the safe
maturity ceiling (from the risk model). For prompt-seam issues, a **DSPy/GEPA-style optimizer** can go
further and *generate* candidate prompt revisions scored against held-out turns. This is how
`active-trip-city-context` becomes a **discovered** card ("orchestrator re-asks for a city derivable
from the active trip — N% of its turns, $X wasted") instead of a hand-written builder.

> **Scenarios flip from inputs to outputs.** The `SCEN-NNN` catalog is demoted to **evaluation
> fixtures + seed priors** (known issues the engine *should* rediscover — a great test of the engine),
> not the source of truth the product enumerates.

### Layer 3 — Surfaces (rebuilt around agents)

- **Agent Scorecard (new, primary):** one row/page per agent — model fit, prompt efficiency
  (routing/tool-calling), memory effectiveness, cost, quality, business contribution — each with a
  health state (healthy / watch / unhealthy) from Layer 2, and the detected opportunities + apply
  actions inline. *This is the "how is each agent doing" view the owner asked for.*
- **Portfolio / Overview (from ADR-0009):** the fleet across the 8 dimensions — coverage, open
  opportunities, applied, measured saving.
- **Discovered Opportunities feed:** the analyst's ranked recommendations (replaces the fixed cards),
  each linked to its agent + dimension + evidence.
- **Projected Impact / What-If (new — demo-first):** for any recommendation, **baseline vs optimized
  cost** (projected *and*, once applied, realized) with saving $/%, a **usage-scaling control** to
  project onto future volume ("at N turns/day ≈ $X/month"), and **cost per outcome** before/after.
  This is the "immediately show an audience the impact" view (and a workshop win). It **generalizes**
  the existing model-selection counterfactual: every recommendation carries a **projection function**
  — *which turns it affects and how it changes tokens/turns* — so the engine estimates a projected
  saving the same way for all (reduced-turns / latency are proxies that feed tokens→cost).
  **Business impact generalizes through *cost per outcome*:** *price-only* optimizations hold
  conversion constant (cost ↓ ⇒ cost/outcome ↓ — safe to project); *behavior-changing* ones treat any
  conversion lift as a **hypothesis confirmed by measured before/after** (the funnel), never a
  fabricated projection. (This is the price-only vs behavior-changing split from the measurement
  framework.)
- **Model Selection / Memory Intelligence / Business Impact:** retained as dimension deep-dives.

## Answering the owner's questions directly

- **Task complexity & model pinning — two distinct notions the current code conflates.**
  - **Realized complexity (post-hoc, for *analysis*):** measured from execution — nodes activated,
    output/reasoning tokens, tool calls. We already have it, and it's a clean monotonic signal
    (verified live: 1→2→3 nodes = 179→463→2,100 avg output tokens). It powers the per-agent
    **model-fit** scorecard and finds **~5× the opportunity** the keyword tier does (438 `supervisor`
    turns ran premium at ~179 output tokens; the ≤6-word classifier flagged only 90 as `trivial`).
  - **Predicted complexity (a-priori, for *routing*):** to pick a model *before* a turn runs you need
    a predictor (feature classifier / confidence cascade — RouteLLM/FrugalGPT). This is the harder
    problem and is itself the **optimization the platform recommends**, whose quality the platform then
    **measures** against realized complexity + outcome.
  Model-fit is a **per-agent** question: `supervisor` is *bimodal* (many light turns + some heavy) → the
  routing prize; `find_places` / `create_or_update_itinerary` are consistently heavy → premium justified.
  The current `classify_turn_tier` is a weak a-priori predictor standing in for *both* notions.
- **What thresholds are correct?** None a-priori. Layer 2a derives them from baselines + cohorts +
  SLOs and explains deviations; owners tune SLOs, not magic constants.
- **What analyzes it / makes recommendations?** Layer 2 — statistical detectors feed an LLM-as-analyst
  (+ optional DSPy prompt optimizer). This is the documented industry pattern, not a bespoke idea.

## Optimization seams — what "apply" actually means (and the workshop's hands-on core)

The most important finding of this session: **optimizations live on a spectrum of *seams*, and the
seam decides both *how* you apply an optimization and *how autonomously* you can.** An optimization is
only auto-applyable if the app was **built to expose the knob**; building the knob is itself a
one-time, human-governed change.

| Seam | Example | "Apply" = | Maturity ceiling |
|---|---|---|---|
| **Config / policy** (a knob the app *already reads*) | tier→model map, thresholds, memory salience/retention | flip a policy doc in Cosmos (Console / translytical **Apply**) | **L4/L5 autonomous** |
| **Prompt** (`.prompty` text) | add a supervisor rule (SCEN-001) | stage `{file, add}`; human reviews + deploys | **L3 assisted** |
| **Code / new mechanism** (no knob exists yet) | *introduce* per-turn routing on a single-model app | stage a diff/PR; human builds + merges + deploys | **L3 assisted (human-governed)** |

**Corollary — model-selection is a *code* seam the first time.** On the single-model base app, "route
the supervisor's light turns to a cheaper model" is **not** a policy flip — it's the code change that
*creates* `select_deployment_for_turn`. Only *after* a human ships that seam does ongoing tuning (the
tier→model map, thresholds) become an auto-applyable **policy**. The current workshop hides this by
**pre-building** the router and shipping tiered data, so "Apply model-selection" looks like a pure
config flip; it only works because the code was already written to read the policy.

**How a code/prompt recommendation is applied (grounded in existing code).** The staged-change loop
already exists: the recommender returns `proposed_change = {file, diff}` (today
`get_city_context_staged_change()` → `{file: "supervisor.prompty", add: <text>}`),
`POST /optimizations/{scenario}/stage` records it as `apply_mode: "staged_change"` (never active at
runtime), and a human reviews + deploys. The redesign has the **LLM analyst *generate*** that diff
(instead of a hardcoded constant); DSPy/GEPA can generate + score prompt diffs. **Arbitrary code is
never auto-applied** — the hard ceiling of the risk model.

**Workshop pedagogy (owner directive, 2026-07-31): make the code seam a hands-on module.** Attendees
are already *in the code building the app*, so the strongest teaching moment is to have them **live the
code-seam optimization** at the keyboard — walking the full maturity ladder in one exercise:
1. Run the analytics engine → it **detects** the supervisor model-selection waste (measured, not
   hand-authored).
2. The analyst **stages a code diff** — *introduce `select_deployment_for_turn` + a policy read*.
3. The attendee **implements the seam in code**, sitting in front of it — this is where they learn
   *why* optimizability requires seams (the base app is single-model; there's no knob until they add
   one).
4. **Apply** the now-existing policy (config) and **re-measure** the saving.

Detect (analytics) → build the seam (L3 code, human) → tune the policy (L4 config, autonomous) →
verify. The generalizable lesson attendees leave with: *to make an agent app optimizable, you
deliberately instrument seams — and the platform recommends across all three, tuning config
autonomously and staging reviewable prompt/code diffs where no knob yet exists.* This reframes the
tiered router from a demo cheat into the **canonical worked example of a code-seam optimization**.

## Options considered

### Option A — Keep the scenario catalog; just add per-agent charts
Bolt agent breakdowns onto today's pages. **Verdict:** rejected — leaves scenarios hand-authored and
thresholds hardcoded; treats the symptom, not the cause.

### Option B — Full agent-centric discovery engine (this ADR), phased
Re-center on agents × dimensions; build the detector + analyst engine; scenarios become
outputs/fixtures. **Verdict:** chosen — it's the vision realized and matches the field.

### Option C — Buy/adopt an existing platform (LangSmith/Phoenix/Langfuse)
Use a vendor's per-agent scorecards. **Verdict:** rejected for the *workshop's* purpose (the teaching
goal is to *build* the Cosmos+Fabric loop), but their metric taxonomies are direct design references.

## Evidence

- **Complexity is a keyword heuristic:** `travel_agents.py:376` `classify_turn_tier` (≤6 words +
  greeting regex → trivial); tiers→models in `seed_configuration.py:72`
  (`trivial=gpt-5-nano, routine=gpt-5-mini, complex=gpt-5.1`).
- **Scenarios are hard-coded builders:** `build_recommendations()` calls six fixed functions
  (redesign doc §1); catalog + discovery methods in `optimization-scenarios/README.md`.
- **Per-agent signal is turn-grained, not agent-grained (grounded live, 02, 1,330 turns,
  2026-07-31):** the app has 3 path agents — `supervisor`, `find_places`,
  `create_or_update_itinerary`. `agent_path` is a *sequence* string on the turn (e.g.
  `supervisor,find_places,create_or_update_itinerary`); **480/1,330 (36%) have no `agent_path`** (the
  synthetic simulator traffic carries no agent structure); and the turn holds a single
  `total_tokens` / `model_tier`, so **per-agent cost/quality is not derivable** at the turn grain.
  This corrects an earlier "no new instrumentation" assumption — P0 requires the node-grain re-capture.
- **Provenance — the tiered router is analytics-track code, not a base-app feature:**
  `classify_turn_tier` / `select_deployment_for_turn` were introduced by commit **`b717dba`**
  ("feat(analytics): SCEN-007 apply-loop", 2026-07-09) and are **absent** on `main`,
  `agent_memory_toolkit`, and `agent_memory_toolkit_v2`. The base app is **single-model** (all turns on
  the default). The catalog says so: *"model selection is an opportunity dimension here, not a current
  behavior… exploring it means introducing per-turn routing (SCEN-007)."* The router was **built for the
  demo**, like the hand-authored scenarios.
- **Vision already asks for it:** L1 examples include "Agent performance analysis," "Workflow
  bottleneck identification" (`vision/…-vision.md` §Maturity).
- **State of the art (external research, 2025–26):**
  - Observability platforms (LangSmith, Langfuse, Arize Phoenix, AgentOps) standardize **per-agent
    scorecards**: cost/tokens/latency/error/quality attributed per agent, regression detection.
  - **Data-driven detection over hardcoded rules:** statistical baselines + anomaly detection, with
    LLMs to cluster/explain outliers (e.g., AD-AGENT; "LLMs for forecasting & anomaly detection",
    arXiv 2402.10350).
  - **Thresholds/SLOs:** baselines (mean±Nσ, percentiles), adaptive windows, and **LLM-as-judge**
    quality SLOs, calibrated with human feedback (mlflow LLM-as-a-judge; Monte Carlo, Confident AI).
  - **Complexity-based routing:** classifier / confidence-cascade / semantic routing — **RouteLLM**
    (lm-sys), **FrugalGPT**; "Dynamic Model Routing and Cascading… A Survey."
  - **The analyst/optimizer:** **DSPy** + **GEPA** (reflective prompt evolution), OPRO/TextGrad —
    LLM-as-optimizer reads traces/metrics and proposes prompt/program changes; used in production to
    move workloads to cheaper models while preserving quality.

## Decision

Adopt the **agent-centric, data-driven analysis engine** (Option B), phased. Re-center the product on
**agents × dimensions**; build the two-tier engine (statistical detectors + LLM-as-analyst) that
**discovers** issues and thresholds from telemetry; demote the scenario catalog to eval fixtures/seed
priors; replace the keyword complexity tier with a measured, per-agent model-fit signal. Preserve the
reverse-ETL + apply-loop + measurement framework.

**Phasing (proposed):**
- **P0 — Re-grain to per-agent-execution + Agent Scorecard.** Capture one row per LangGraph node
  invocation (agent, model, tokens, latency, tool calls, recall, complexity), then build the
  per-`(agent × dimension)` scorecard over it. *This is an instrumentation change, **not** just
  aggregation — the current per-turn rollup can't attribute cost/quality to an agent (see Evidence).*
  Delivers the "see your agents" view + the canonical teaching moment.
- **P1 — Statistical detectors + relative baselines.** Baseline per (agent × dimension); emit
  anomaly rows; thresholds become derived. Recompute counterfactual model-fit per agent.
- **P2 — Measured complexity signal** replacing the keyword tier; per-agent model-fit recommendation.
- **P3 — LLM-as-analyst** producing the discovered-opportunities feed (catalog becomes fixtures);
  rediscover `SCEN-001` from data as the canonical demo.
- **P4 — Prompt optimizer (DSPy/GEPA)** for prompt-seam recommendations (aspirational L3+).

## Cost & data-generation strategy (attendee path ≈ $0 LLM)

Running **live agents** to generate telemetry is prohibitively expensive — hours and a large token
bill (the owner's original approach, and the lesson behind the fixture-first pivot, ADR-0004). The
agent-centric redesign **must not** reintroduce that cost, and it doesn't — because *generating
telemetry* is separated from *running the analysis engine*:

- **Re-graining to per-agent-execution is cost-neutral.** The nodes already run and already make their
  LLM calls each turn; node-grain simply *records* each node's telemetry instead of rolling it up and
  discarding it. **More rows, not more LLM calls.**
- **Telemetry is fixture-first (no live agents for attendees):**
  - The **golden fixture** is captured **once, by the maintainer**, at node grain (one expensive live
    run, exported + committed — today's `debug.json` pattern, richer). Attendees load it offline via
    `seed_data.py` → $0.
  - The **traffic simulator** is upgraded to fabricate **agent-structured node executions** (synthetic,
    weighted to realistic distributions) instead of flat turns — fixing the 36% no-agent gap — still
    **no LLM**. Covers the "volume / watch-it-move-live" demos.
- **Engine LLM cost (LLM-judge + LLM-analyst) is bounded by pre-baking:** the maintainer runs the judge
  + analyst **once**; their outputs (per-node quality scores, discovered recommendation cards) are
  **committed as fixtures**, so attendees see a fully-populated platform for $0. The teaching moment is
  reading the notebook/code that *produces* them, and optionally running the judge on ~5 turns and the
  analyst on the pre-computed aggregates once (cents, not hours).

**Attendee path:** load fixtures → run the Fabric reverse-ETL (Spark/capacity cost only, no tokens) →
explore scorecards + discovered opportunities → apply a policy → re-measure. **No live agents, no
hours, no token bill.** The expensive generation is a maintainer's one-time job behind the committed
fixtures — itself a teaching point ("here's the production engine; here's the cheap fixture path a
workshop uses to demonstrate it").

**Phase constraints this imposes:** **P0** must (re)capture the node-grain golden fixture *and* upgrade
the simulator to node-grain; **P1/P3** (judge, analyst) must ship **pre-baked outputs** with an
optional small-sample live run — never a full-dataset attendee run.

## Consequences

- **Positive:** the product finally answers "how are my agents doing?"; issues (incl. novel ones) are
  discovered; thresholds are principled; the workshop teaches the *general* method (measure → baseline
  → detect → analyze → recommend → apply → re-measure), which is the vision.
- **Negative / costs:** substantial build across both trees (instrumentation, Fabric detectors +
  analyst, new surfaces, report rebuild); introduces LLM calls into the analytical path (cost/latency,
  judge calibration); complexity re-classification touches the model-selection story.
- **Risks:** analyst hallucination / bad recommendations (mitigate: evidence-grounded prompts, human
  approval per the risk model, the SCEN fixtures as a regression suite); baseline cold-start (need
  enough traffic — the simulator helps); scope discipline vs. PR #73.

## Open items to verify

- Which per-agent quality signal to adopt (LLM-judge rubric) and how to calibrate it.
- Concrete detector set + baseline windows per dimension; cold-start handling.
- Measured-complexity design (features + small classifier vs confidence cascade) and its accuracy vs
  the keyword heuristic.
- Analyst prompt + guardrails; how the SCEN fixtures validate rediscovery.
- **Projection functions** per optimization type (how each re-simulates over historical telemetry to
  produce a projected saving) + the usage-scaling model for the Projected Impact / What-If view.
- Sequencing vs PR #73 (this is a follow-up initiative, not a #73 change).
- The **traffic simulator emits no agent structure** (36% attribution gap): for per-agent analysis it
  must produce node-level executions, or be replaced by real / behavioral-probe traffic.

## References

- Repo: `../vision/agent-analytics-and-optimization-vision.md`, `../optimization-scenarios/README.md`,
  `adr-0009-…`, `adr-0001-…`, `adr-0008-…`; code: `travel_agents.py:376`, `seed_configuration.py:72`,
  `services/optimization_recommendations.py`, `data/export_conversations.py`.
- RouteLLM (github.com/lm-sys/RouteLLM); FrugalGPT; "Dynamic Model Routing and Cascading for Efficient
  LLM Inference: A Survey" (arXiv).
- DSPy (dspy.ai) + GEPA reflective prompt evolution; OPRO / TextGrad.
- LLM-as-a-judge for agent evaluation (mlflow.org/llm-as-a-judge; Confident AI; Monte Carlo).
- LLM-powered anomaly detection over telemetry (AD-AGENT, arXiv 2505.12594; arXiv 2402.10350).
- Agent observability metric taxonomies: LangSmith, Langfuse, Arize Phoenix, AgentOps.

# ADR-0010: Agent-centric, data-driven analysis & optimization engine

- **Status:** Proposed
- **Date:** 2026-07-31
- **Deciders:** Mark Brown (@markjbrown), with agent analysis + external research
- **Related:** `../vision/agent-analytics-and-optimization-vision.md`, `../optimization-scenarios/README.md`, `adr-0009-generalize-optimization-framework-product-alignment.md`, `adr-0001-optimization-loop-surface-architecture.md`, `adr-0008-optimization-apply-loop-model-selection.md`

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
- **Model Selection / Memory Intelligence / Business Impact:** retained as dimension deep-dives.

## Answering the owner's questions directly

- **Task complexity & model pinning.** Replace the ≤6-word keyword tier with a **measured** signal:
  per-turn features (length, tool calls, handoffs, output/reasoning tokens) and/or a small classifier
  or a **confidence/uncertainty cascade** (try cheap model; escalate on low confidence) — the
  RouteLLM/FrugalGPT approach. Crucially, model-fit becomes a **per-agent** question: *given the
  distribution of complexity each agent actually handles, is its pinned model right?* (Your instinct —
  "complex prompts per agent" — is the per-agent aggregate of a per-turn measured signal.)
- **What thresholds are correct?** None a-priori. Layer 2a derives them from baselines + cohorts +
  SLOs and explains deviations; owners tune SLOs, not magic constants.
- **What analyzes it / makes recommendations?** Layer 2 — statistical detectors feed an LLM-as-analyst
  (+ optional DSPy prompt optimizer). This is the documented industry pattern, not a bespoke idea.

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

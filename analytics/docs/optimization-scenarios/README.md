# Optimization Scenarios — a catalog for the Agent Analytics lab

This catalog turns the **business questions from the vision** into concrete, testable
optimization scenarios. Each scenario follows the same loop (ADR-0001):

> **instrument → detect (in data) → recommend (dashboard card) → apply (ideally one-click) → verify (before/after)**

A good scenario is: **realistic**, **detectable from data we already capture**, **fixable at a safe seam**
(prompt/threshold first), and **measurable** after the fix. Scenarios are discovered three ways
(see *Discovery methods* below) and are always tied back to a vision question so the lab teaches
*business value*, not just plumbing.

## The two tiers of questions (from the vision)

**Tier 1 — analytical (what the data reveals):**
which agents deliver the most value · which workflows produce the best outcomes · which memories
improve success · which memories are stale/ineffective · how behavior evolves over time · cost per
successful outcome · which workflows to optimize · which patterns correlate with success.

**Tier 2 — action (what we do about it):**
how insights improve behavior · which optimizations to apply · which can be automated *safely* ·
how the system improves continuously. Tier 2 is the **apply-loop** (ADR-0001).

## The eight optimization dimensions (what we continuously improve)

Every scenario improves one or more of these axes from the vision. They keep the catalog spanning
*different types of issues* (not just one), and each maps to signal we already capture and a safe fix seam:

| Dimension | What it means here | Primary signal | Typical fix seam |
|---|---|---|---|
| **Agent quality** | correct, helpful, complete responses | e2e answer-quality / correctness (LLM judge), trip completion | prompt |
| **Workflow efficiency** | fewest turns / hops / latency to an outcome | `agent_path`, `handoff_count`, turns-to-first-result | prompt / routing |
| **Memory effectiveness** | memories are recalled and improve outcomes | recall usage, `salience`, `superseded_by` | prompt / config |
| **Routing effectiveness** | supervisor delegates to the *right* sub-agent | `agent_path` vs expected (the v2 routing eval), delegation-avoidance | prompt |
| **Tool utilization** | tools called when useful, not wastefully | `tool_calls`, `find_places` vs direct answer, over-/under-calling | prompt / config |
| **Model selection** | right model for the task's difficulty | `model_name` × `total_tokens` per turn type | config / model-routing |
| **Cost efficiency** | tokens / \$ per successful outcome | `total_tokens`, `cached_tokens` ÷ confirmed `Trips` | prompt / config / model |
| **Business outcomes** | bookings made — the anchor success signal | `Trips.status` (confirmed/completed) | *served by all of the above* |

`Trips.status` is the shared **outcome** anchor: every other dimension is ultimately judged by whether it
moves *business outcomes*. A healthy catalog has at least one scenario per dimension.

> **Note on Model selection (this app is single-model today):** the app builds **one** shared chat
> model (`services/azure_open_ai.py`) that the supervisor and *all* sub-agents use — 100% of baseline
> turns default to `gpt-5.1` until a routing policy is applied. So **model selection is an
> *opportunity dimension* here, not a current behavior**: there is nothing to "tune" yet. Exploring it
> means *introducing* per-turn/per-task model routing (see SCEN-007), not analyzing an existing
> variation. It's included because it's a strong cost lever (~23% of turns are trivial by the
> classifier / `model_tier`) and a vision-listed lower-risk autonomous domain — just be clear it's
> aspirational for this app until the router seam exists.

## What we can measure (signal inventory)

Everything below already lands in `TravelAssistant` (no new instrumentation needed):

| Source | Key fields | Feeds |
|---|---|---|
| **Debug** (per turn) | `agent_selected`, `agent_path`, `handoff_count`, `total_tokens`, `input/output/cached_tokens`, `model_name`, `finish_reason` | cost, routing, drift |
| **Messages** | `role`, `content`, `ts` | intent, clarification vs answer |
| **Memories** | `type` (fact/episodic/procedural), `salience`, `superseded_by`, `supersede_reason`, `source_*`, `created_at` | memory efficacy / staleness |
| **memories_summaries / counter** | summary cadence, per-thread turn counts | summarization tuning |
| **Trips** | `status` (planning/confirmed/completed), `days`, `destination` | **outcome** (the "success" signal) |
| **Sessions** | span, activeAgent | session-level rollups |

The **outcome** anchor is `Trips.status` (confirmed/completed = a successful booking). Almost every
Tier-1 question is *"<some behavior/cost signal> correlated with Trips outcome."*

## Vision question → detectable signal → candidate scenario

| Vision question | Signal (join) | Candidate scenario(s) |
|---|---|---|
| **Cost per successful outcome** | Σ`Debug.total_tokens` per session ÷ confirmed `Trips` | **SCEN-001** (avoidable clarification turns); high-token sessions with **no** confirmed trip (wasted spend) |
| **Which workflows to optimize** | `agent_path` × tokens × conversion | costliest `agent_path` per confirmed trip; paths with many hops but low conversion |
| **Which agents deliver value** | `agent_selected`/`agent_path` × outcome | a sub-agent invoked often but rarely on a path that converts |
| **Which workflows produce best outcomes** | `agent_path` sequences × `Trips.status` | delegation paths that correlate with confirmed vs abandoned trips |
| **Which memories improve success** | recall usage × outcome | high-salience memories that are **never recalled** (recall gap) |
| **Which memories are stale/ineffective** | `superseded_by`, age, `salience` | superseded memories still surfacing; low-salience never-recalled memories bloating context |
| **How behavior evolves over time** | Debug over time (tokens, `handoff_count`) | token/turn creep as memory/context grows (context-bloat drift) |
| **Which patterns correlate with success** | recall/summary/path features × outcome | "sessions that recalled preferences convert better" → recommend always-recall |

Each row is a scenario slot. **SCEN-001** is the first fully worked example; the rest are
**candidates to be validated against the baseline data** (see *Discovery methods*).

## Optimization maturity model (the levels each scenario climbs)

The vision defines a five-level progression from observation to self-adaptation. A scenario is
designed to be walked **up** this ladder — and how far it can safely climb depends on its fix seam
(see risk domains below):

| Level | Name | What the platform does | Human role |
|---|---|---|---|
| **L1** | Visibility | Dashboard/report surfaces the metric | Humans identify & implement |
| **L2** | Recommendations | Platform recommends a fix | Humans review & approve |
| **L3** | Assisted Optimization | Platform generates the concrete change + impact analysis | Humans approve/reject before deploy |
| **L4** | Autonomous Optimization | For approved **lower-risk** domains, auto-applies + validates (reversible, auditable) | Humans set policy & audit |
| **L5** | Adaptive Agent Systems | Fleets continuously self-tune lower-risk domains; higher-risk stays human-governed | Humans govern the envelope |

### Risk domains govern the L4/L5 ceiling (from the vision)

This is the concrete answer to *"which optimizations can be automated safely?"*:

- **Lower-risk → autonomous-eligible (can reach L4/L5):** memory salience tuning, memory retention
  policies, retrieval weighting, routing thresholds, tool-selection policies, model-selection
  policies, cost policies. These are **parameters/policies** — bounded, reversible, measurable.
- **Higher-risk → human-governed (ceiling L2/L3):** **prompt modifications**, workflow redesign,
  agent-instruction changes, agent-capability changes, code generation, deployment changes.

> ⚠️ **Correction of a common intuition:** a prompt edit *feels* safe (it's just text, hot-swappable),
> but the vision classifies **prompt modifications as higher-risk / human-governed**. So SCEN-001,
> whose fix is a `supervisor.prompty` rule, is a great L1→L3 teaching example but **caps at Assisted
> (L3)** — it is applied one-click **with human approval**, not unattended. The scenarios that truly
> demonstrate **L4/L5 self-adaptation** are the **policy/threshold** ones (routing thresholds, memory
> salience, model-selection policy, retention) — which is exactly why the catalog deliberately
> includes both kinds.

## Fix seams & maturity ceiling

| Fix seam | Example | Risk domain | Maturity ceiling |
|---|---|---|---|
| **Policy / threshold (config)** | routing threshold, memory salience, retention, model-selection policy | lower-risk | **L4/L5 autonomous** |
| **Prompt (`.prompty` data)** | add a supervisor rule (SCEN-001) | higher-risk | **L3 assisted** (human-approved) |
| **Tool wiring / code** | name-based `find_places` fallback | higher-risk | **L3 assisted** + test/deploy |

The lab's headline message: **continuous self-improvement (L4/L5) is reached through the lower-risk
policy/threshold domains**; prompt, workflow, and code changes stay human-governed with the platform
providing recommendations, impact analysis, and approval workflows.

## Discovery methods (how we find more scenarios)

1. **Data-first mining** — run the Tier-1 metric queries over the existing baseline
   (`v2_analytics`, 291 Debug logs / 755 memories / 11 trips) and look for anomalies
   (wasted spend, never-recalled memories, costly non-converting paths). Surfaces *structural* issues.
2. **Behavioral probes** — script representative user journeys through the API (the automated
   analog of "naive use") and inspect the resulting Debug/agent_path. Surfaces *behavioral* gaps
   like SCEN-001 reproducibly.
3. **Naive UI use** — manual exploration in the frontend; how SCEN-001 was found. Good for
   discovering gaps the data alone doesn't make obvious.

Recommended sequence: **(1) mine the baseline to rank cost/outcome hotspots → (2) write probes that
reproduce the top few → (3) document each as a SCEN-NNN with detection query, fix seam, and
before/after metric.**

## Scenario classification schema

Each `scen-NNN-*.md` carries: `id`, `category`, **vision question(s)**, `detectable-in-data?`,
`reproducible-in-UI?`, `fix-seam` (prompt/config/code), `auto-apply-safety` (auto / one-click / human-review),
and the `before/after metric`.

## Catalog

Each scenario is exercised up the maturity ladder (L1 visibility → … ) to its **ceiling** — set by
its risk domain. Policy/threshold scenarios reach **L4/L5 (self-adapting)**; prompt/code scenarios cap
at **L3 (assisted, human-approved)**.

| ID | Title | Dimension(s) | Fix seam | Risk domain | Maturity ceiling | Status |
|----|-------|--------------|----------|-------------|------------------|--------|
| [SCEN-001](scen-001-active-trip-city-context.md) | Supervisor re-asks for a city it could infer from the active trip | workflow efficiency · routing · cost | prompt | higher-risk | **L3 assisted** | **documented** |
| [SCEN-002](scen-002-memory-effectiveness-gap.md) | Memory-effectiveness gap — which memories improve outcomes? | memory effectiveness · agent quality | retrieval weighting (policy) | lower-risk | **L4/L5 autonomous** | **documented** (needs instrumentation add) |
| [SCEN-003](scen-003-cost-per-outcome.md) | Cost per successful outcome (north-star KPI) | cost efficiency · business outcomes | *composite metric* | n/a (KPI) | scoreboard for L2–L5 | **documented** |
| [SCEN-004](scen-004-stale-memory-retention.md) | Stale/superseded memories accumulate (retention & salience policy) | memory effectiveness · cost | salience + retention policy | lower-risk | **L4/L5 autonomous** | **documented** |
| [SCEN-005](scen-005-agent-path-cost-concentration.md) | Cost concentrated in a few `agent_path`s (+ double `find_places`) | workflow efficiency · cost | routing threshold / prompt | mixed | L3–L4 | **documented** |
| SCEN-006 | Context-bloat drift (tokens/turn creep over time) | cost efficiency · behavior drift | retention / summary cadence (policy) | lower-risk | L4/L5 | ⚠️ **parked** — data does not support (yet) |
| [SCEN-007](scen-007-model-selection-trivial-turns.md) | Full model used for trivial turns | model selection · cost | model-selection policy | lower-risk | **L4/L5 autonomous** | **documented** |
| [SCEN-008](scen-008-tool-utilization-grounding.md) | Supervisor under-uses `find_places` (answers from knowledge; redundant calls) | tool utilization · routing · agent quality | tool-selection policy / prompt | mixed | L3–L4 | **documented** |

> Candidates are hypotheses to be **confirmed against the data** before promotion. See
> **[baseline-findings.md](baseline-findings.md)** for the first data-first mining pass (real numbers
> per candidate). Coverage goals: (1) at least one scenario per **optimization dimension**, and
> (2) a mix of **prompt (L3-ceiling)** and **policy/threshold (L4/L5-ceiling)** scenarios so the lab
> demonstrates the full maturity ladder — including the self-adapting Level 5 through the lower-risk
> policy domains. **SCEN-001** (L3 prompt) and **SCEN-004 / SCEN-007** (L4/L5 policy) are the worked
> examples spanning that ladder.

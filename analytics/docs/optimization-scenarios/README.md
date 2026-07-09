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

## What we can measure (signal inventory)

Everything below already lands in `TravelAssistantV2` (no new instrumentation needed):

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

## Fix seams & auto-apply safety

Optimizations are ranked not just by impact but by **how safely they can be applied** — this is the
Tier-2 *"which can be automated safely?"* question made concrete:

| Fix seam | Example | Auto-apply safety |
|---|---|---|
| **Prompt (`.prompty` data)** | add a supervisor rule (SCEN-001) | **Safe / one-click** — hot-swapped via `load_prompt`, no redeploy |
| **Threshold / config (env)** | `FACT_EXTRACTION_EVERY_N`, summary cadence | **One-click** — bounded, reversible |
| **Tool wiring / code** | name-based `find_places` fallback | **Human-review** — code path, needs test + deploy |

The lab's headline message: **the safest and highest-leverage optimizations are prompt and threshold
edits**, which is exactly why the apply-loop (ADR-0001) writes `.prompty`/config rather than code.

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

| ID | Title | Dimension(s) | Vision question | Fix seam | Safety | Status |
|----|-------|--------------|-----------------|----------|--------|--------|
| [SCEN-001](scen-001-active-trip-city-context.md) | Supervisor re-asks for a city it could infer from the active trip | workflow efficiency · routing · cost | cost per outcome | prompt | one-click | **documented** |
| SCEN-002 | High-salience memories that are never recalled (recall gap) | memory effectiveness · agent quality | which memories improve success | prompt | one-click | candidate |
| SCEN-003 | High-token sessions with no confirmed trip (wasted spend) | cost efficiency · business outcomes | cost per outcome | prompt/config | one-click | candidate |
| SCEN-004 | Stale/superseded memories still surfacing | memory effectiveness | which memories are stale | config/prompt | one-click | candidate |
| SCEN-005 | Costliest `agent_path` per confirmed trip | workflow efficiency · cost | which workflows to optimize | prompt | one-click | candidate |
| SCEN-006 | Context-bloat drift (tokens/turn creep over time) | cost efficiency · behavior drift | how behavior evolves | config | one-click | candidate |
| SCEN-007 | Full model used for trivial turns (greetings, clarifications) | model selection · cost | cost per outcome | config/model-routing | one-click | candidate |
| SCEN-008 | Supervisor answers place queries from its own knowledge instead of `find_places` | tool utilization · routing · agent quality | which patterns correlate with success | prompt | one-click | candidate |

> Candidates are hypotheses to be **confirmed against the data** before promotion to a full scenario.
> Coverage goal: at least one scenario per optimization dimension. Current spread — workflow efficiency
> (001/005), routing (001/008), memory effectiveness (002/004), cost efficiency (003/005/006/007),
> model selection (007), tool utilization (008), agent quality (002/008), business outcomes (003).

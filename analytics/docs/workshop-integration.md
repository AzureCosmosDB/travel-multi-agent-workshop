# Workshop integration — Analytics & Optimization (apply-loop)

**Status:** Proposal for maintainer + author review (implementation of the apply-loop in
`02_completed` is done; `01_exercises` sync + module authoring are proposed here, not yet applied).
**Audience:** humans (author, maintainer, workshop facilitators) **and** agents working in this repo.
**Related:** [ADR-0008](adr/adr-0008-optimization-apply-loop-model-selection.md),
[ADR-0007](adr/adr-0007-v2-analytics-instrumentation-debug-first.md),
[SCEN-007](optimization-scenarios/scen-007-model-selection-trivial-turns.md),
optimization-scenarios [catalog](optimization-scenarios/README.md).

---

## 1. Why this document exists

We added a working **optimization apply-loop** (`detect → recommend → apply → verify`) to the core
app, using **capability-tiered model selection (SCEN-007)** as the first end-to-end example. This
touches the *core workshop application*, so we must:

1. **Document the underlying changes** to the core app (below, §3).
2. **Update the learning objectives / target** so learners build the correct thing (§5–§6).
3. **Give the maintainer a clear, self-contained summary** of what changes and why (§7).

> **Current divergence to be aware of:** these changes currently exist **only in `02_completed`**
> (the reference solution). `01_exercises` (the learner starting point) and the `workshop/Module-*.md`
> guides have **not** been changed yet. §6 is the plan to bring them in sync.

## 2. How the workshop is structured (the constraint we design within)

- `01_exercises/` is the **learner starting point**. Two core files ship **empty** and are built by
  the learner across the modules: `python/src/app/travel_agents.py` and
  `python/src/app/services/agent_memory.py`. The supporting pieces are **provided**:
  `services/azure_open_ai.py`, `services/azure_cosmos_db.py`, `travel_agents_api.py`, the MCP server,
  frontend, and infra.
- `02_completed/` is the **fully implemented reference** the learner's work should converge to.
- `workshop/Module-00…07.md` are the step-by-step guides. Today: **05 = Observability & Tracing
  (LangSmith)**, 06 = Evaluation (bonus), 07 = Lessons & Future. There is **no analytics/optimization
  module** — that content lives separately under `analytics/`.
- The natural pedagogical arc is **observe (05) → analyze & optimize (new)**: you can only optimize
  what you can measure, and Module 05 + ADR-0007 already give us the `Debug` turn-log signal.

## 3. Underlying changes to the core app (in `02_completed`)

The apply-loop is deliberately split into **plumbing** (generic "make the app optimization-ready"
infrastructure) and a **decision layer** (the analytically-meaningful policy). See ADR-0008 for the
full rationale and the live verification.

| File | Kind | Change |
|---|---|---|
| `services/optimization_policy.py` | **new, plumbing** | Cosmos-backed, versioned, reversible policy store (`OptimizationPolicies` container; `proposed/active/reverted`; short-TTL cache). Apply/revert = a status flip + audit — never a code edit. |
| `services/optimization_recommendations.py` | **new, plumbing** | Turns `Debug` signal into candidate cards (SCEN-007). Prices are labeled **estimates**; the measured verify is authoritative. |
| `optimization_api.py` | **new, plumbing** | `/optimizations` REST surface: recommend, propose, apply, revert. |
| `services/azure_open_ai.py` | modified, plumbing | `get_chat_model(deployment)` — cached per-deployment model factory; reasoning models (`gpt-5*`/o-series) omit `temperature`, use api `2025-04-01-preview`. |
| `services/azure_cosmos_db.py` | modified, plumbing | `store_debug_log` records `model_tier` + `model_deployment`. |
| `travel_agents_api.py` | modified, plumbing | Selects the tiered supervisor per turn; records tier/deployment on the `Debug` log. |
| `travel_agents.py` | modified, **decision + plumbing** | `classify_turn_tier` (**decision layer**) + `get_supervisor_for_turn`/`_build_supervisor` (plumbing: per-tier prebuilt supervisor). |
| `analytics/optimization_mining.py` | modified | `--verify` per-tier token + estimated-cost report from `Debug`. |

**Safe-by-default:** with no *active* policy, `select_deployment_for_turn` returns the default
deployment and the app behaves exactly as before. Nothing changes until a user clicks apply.

**Infra note:** two later-gen deployments were added to the app's AOAI account (`gpt-5-nano`,
`gpt-5.1`) because the app was single-model. `gpt-5.4`/`gpt-5.4-nano` were fully quota-allocated
subscription-wide (see ADR-0008).

## 4. The pedagogical decision (what the learner builds)

**Chosen approach:** *ship the plumbing pre-built; the learner builds the analytics **decision
layer** and drives the loop on their own data.* (Rejected: making the learner build the policy-store /
per-tier supervisor plumbing — that buries the analytics lesson under LangGraph/infra mechanics; and
a pure click-to-demo — too thin to feel real.)

This fits the workshop's file model cleanly:
- The **decision layer** the learner writes is `classify_turn_tier` in `travel_agents.py` — the file
  learners already build. Deciding *what "trivial" means* is a genuine analytics judgment.
- All **plumbing** lives in **provided** files (`optimization_policy.py`,
  `optimization_recommendations.py`, `optimization_api.py`, `get_chat_model`, the API wiring, the
  `Debug` fields), so learners don't re-implement infrastructure.

## 5. Updated / new learning objectives

New module **Module 07 "Analytics & Optimization"** (confirmed). Final module order:
**05** Observability (LangSmith) → **06** Evaluation → **07** Analytics & Optimization *(new)* →
**08** Lessons Learned & Future *(was 07)*. Evaluation precedes Optimization deliberately: the eval
harness from Module 06 becomes the **quality gate** for autonomous apply (see the capstone below).

Learning objectives:

- Explain the optimization loop: **instrument → detect → recommend → apply → verify**, and the
  5-level maturity model (Visibility → Recommendations → Assisted → Autonomous → Adaptive).
- Understand the **risk model**: prompt/workflow/code changes are human-governed (ceiling L3);
  memory/routing/**model-selection**/tool policies are lower-risk and can be autonomous (L4/L5).
- **Detect** an optimization from your own captured data (run `optimization_mining.py`; read the
  SCEN-007 card: ~48% of turns are trivial yet use the full model).
- **Build the decision layer**: implement `classify_turn_tier` (trivial/routine/complex) — the
  learner's judgment about what each tier means.
- **Apply** the policy (one click via the dashboard / REST) and observe live per-turn model routing.
- **Verify** the effect from data (`--verify` per-tier cost), and reason about **cost per successful
  outcome** (SCEN-003), including the honest reasoning-token caveat (a naive "cheaper model" can lose
  once reasoning tokens are counted — the measured verify is the truth).
- **(Advanced / stretch)** Tier the **itinerary sub-agent (the worker)**, not just the supervisor
  turn — the higher-value production pattern that puts the capable model where the quality-sensitive
  generation happens (ties directly to SCEN-005's fat-tail cost and SCEN-003's cost-per-outcome).
- **(Capstone)** Wire the Module 06 **evaluation harness as an automated quality gate**: an applied
  optimization stays active only if answer quality holds above a threshold, else it **auto-reverts**.
  This is what turns "assisted" (L3, human approves) into "autonomous" (L4/L5, self-governing).

**Corrected target for existing modules:** the "What You've Built" recap (now Module 08) and any place
that describes the finished system should note the app is now **optimization-ready** (policy-driven,
reversible, capability-tiered model selection) — an explicit capability learners end with.

## 6. Plan to sync `01_exercises` (decisions resolved; ready to implement)

> **Verified state (2026-07-09):** `01_exercises` is **behind `02_completed`** by more than the
> apply-loop. Its provided `travel_agents_api.py` is a teaching scaffold with the agent integration
> **commented out** (learner enables it) and has **no `chat_event_generator` / ADR-0007 `Debug`
> re-wire** (`agent_path`/`handoff_count`); its `store_debug_log` lacks those fields. The apply-loop
> **depends on that ADR-0007 analytics baseline**, so it cannot be dropped into 01 until 01 is brought
> up to the v2 analytics baseline. **Do not scatter partial apply-loop code into 01 before that
> prerequisite lands** — it would produce broken/misleading scaffolding.

**Prerequisite (new, must precede the port):** bring `01_exercises` (and the relevant modules) up to
the **v2 analytics baseline** — the ADR-0007 `Debug` re-wire (`chat_event_generator` token/agent/tool
capture, `agent_path`/`handoff_count`). This is a larger, maintainer-coordinated workshop update and
is tracked separately from the apply-loop.

Once the prerequisite is in place, port to `01_exercises`:

- **Provided (pre-built) — copy from `02_completed` into the exercise scaffold:**
  `services/optimization_policy.py`, `services/optimization_recommendations.py`,
  `optimization_api.py`; the `get_chat_model` addition to `services/azure_open_ai.py`; the
  `store_debug_log` field additions to `services/azure_cosmos_db.py`; the per-turn tier-selection
  wiring + `Debug` recording in `travel_agents_api.py`; and `get_supervisor_for_turn`/`_build_supervisor`.
- **Learner-built (guided TODO):** `classify_turn_tier` in `travel_agents.py` — the one piece the
  learner implements (Module 07, Activity 5). Note `travel_agents.py` ships **empty** in 01 and is
  built across the modules, so the apply-loop block is delivered **via Module 07** (paste the plumbing;
  implement the classifier), not pre-placed in the empty file.
- **New module doc** `workshop/Module-07.md` (Analytics & Optimization) — **done**; the current
  `Module-07.md` (Lessons) was renumbered to `Module-08.md`, and `Home.md` + `Module-06.md` nav
  updated. Module-07 carries a **prerequisite banner** pointing at the v2 analytics baseline.
- **Deployment/setup:** the module adds the two extra model deployments (`gpt-5-nano`, `gpt-5.1`) via
  documented `az` steps (Module 07, Activity 2), with quota notes.

**Confirmed decisions (previously open):**
1. **Module numbering:** new **Module 07 Analytics & Optimization**; Lessons moves to **Module 08**;
   Observability (05) and Evaluation (06) unchanged.
2. **Sub-agent tiering:** supervisor-turn tiering is the **core** lesson; **worker (itinerary
   sub-agent) tiering is an advanced/stretch activity**.
3. **Dashboard vs REST:** ship the lab **REST/CLI-driven now**; build the **Angular apply card as a
   fast-follow** (it calls the same REST endpoint).
4. **Quality gate:** teach **manual verify in v1**; the **automated eval gate is the capstone** that
   unlocks the autonomous (L4/L5) maturity level.

## 7. For the maintainer — change summary

**What:** a reversible, audited **optimization apply-loop** in the core app, demonstrated with
**capability-tiered model selection** (route trivial turns to a cheap model, complex turns to a
capable one), driven by data the app already captures (ADR-0007 `Debug` logs).

**Why it's safe to land:**
- **No behavior change by default** — inert until a policy is explicitly applied; apply/revert are a
  Cosmos status flip with an audit trail, never a code/prompt edit.
- **Additive** — new files + additive fields; existing analytics stack (Fabric/Power BI/SQL) reads the
  same `Debug` container unchanged.
- **Verified live** on `TravelAssistantV2` (per-turn routing, `Debug` records the actual serving
  model, revert returns to default) — see ADR-0008.

**What it asks of the workshop:**
- One **new module** ("Analytics & Optimization") after Observability, and a small **learner TODO**
  (`classify_turn_tier`); everything else is pre-built/provided.
- Two extra **model deployments** in the target environment (`gpt-5-nano`, `gpt-5.1`).
- The four **open decisions** in §6 need an author/maintainer call before `01_exercises` is finalized.

**What is NOT changing:** the core agent architecture (v2 supervisor + sub-agents-as-tools), the memory
toolkit, the existing modules' code targets (the apply-loop is additive, not a rewrite).

---

*Change log: created alongside the SCEN-007 apply-loop implementation (ADR-0008). Update this doc as
`01_exercises` is synced and the module is authored.*

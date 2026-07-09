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

**Chosen approach:** *an **additive optimization layer** — ship the engine as new drop-in files, have
the learner wire it in with a few small hooks and implement the one decision function, and provision
all infra via Bicep.* No changes to Modules 01–05. (Rejected: backporting the deep 02_completed
apply-loop into 01's diverged provided files + modules — that was open-heart surgery on the whole
exercise track; and a pure click-to-demo — too thin to feel real.)

Why additive works here (verified): `01_exercises` is a *teaching scaffold* significantly behind
`02_completed` (its completion path is a stub the learner builds; it lacks the ADR-0007 `Debug`
re-wire). Rather than force that prerequisite, the optimization layer **brings its own
instrumentation** (`record_optimization_turn` → its own `OptimizationTurns` container), so it doesn't
depend on the earlier modules at all.

What the learner does vs. what's provided:
- **Provided (drop-in, new files):** `services/optimization.py` (policy store, model factory,
  tier selection, per-turn capture, recommendations) and `optimization_api.py` (REST surface).
- **Provisioned by Bicep (`azd up`, in place from Module 00):** `OptimizationPolicies` +
  `OptimizationTurns` Cosmos containers; `gpt-5-nano` + `gpt-5.1` model deployments. Per the workshop
  convention, anything Bicep-deployed is already in place — no manual `az` steps, no runtime
  container creation.
- **Learner writes:** `classify_turn_tier` (the decision) + four small wiring hooks (mount the router,
  register a supervisor factory, swap to `get_supervisor_for_turn`, call `record_optimization_turn`) +
  the stretch (worker tiering) + the capstone (eval quality gate).

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

## 6. Implementation status — the additive optimization layer (done for `01_exercises`)

> **Superseded approach:** an earlier plan was to backport the deep `02_completed` apply-loop into
> 01's provided files, which required first bringing 01 up to the ADR-0007 `Debug` baseline (a large,
> module-touching prerequisite). We **rejected** that in favor of the **additive layer** (§4), which
> carries its own instrumentation and needs **zero changes to Modules 01–05**.

**Implemented (branch `mjbrown/unify-v2`):**

- **Bicep (infra, provisioned by `azd up`):** `01_exercises/infra/shared/cosmosdb.bicep` +
  `main.bicep` add the `OptimizationPolicies` (pk `/scenario`) and `OptimizationTurns` (pk
  `[/tenantId,/userId,/sessionId]`) containers and the `gpt-5-nano` (2025-08-07) + `gpt-5.1`
  (2025-11-13) GlobalStandard deployments. `az bicep build` passes.
- **Provided drop-in code:** `01_exercises/python/src/app/services/optimization.py` (engine) and
  `optimization_api.py` (REST). Self-contained — import only 01's existing `azure_open_ai` vars and
  `azure_cosmos_db.database`; **no self-provisioning** (Bicep owns the containers); no edits to any
  provided file. Compile-checked; all imported symbols verified present in 01.
- **Learner exercise:** `classify_turn_tier` ships as a documented **stub** in `optimization.py`
  (learner implements in Module 07, Activity 6), plus four small wiring hooks (Activity 4).
- **Module doc:** `workshop/Module-07.md` rewritten for the additive flow (confirm Bicep tiers → tour
  the layer → wire the hooks → detect → implement classifier → apply → verify → stretch → capstone).
  Lessons renumbered to `Module-08.md`; `Home.md` + `Module-06.md` nav updated.
- **Verify tool:** `analytics/optimization_mining.py --verify --container OptimizationTurns` reads the
  flat `OptimizationTurns` schema (still supports `--container Debug` for the 02 deep instrumentation).

**Not done / follow-ups:**
- **`02_completed` convergence:** 02 still runs the deep apply-loop (verified live) and self-provisions
  its policy container at runtime; converging it onto the shared `optimization.py` + adding the
  containers/deployments to 02's Bicep is a follow-up (kept as-is for now).
- **Angular apply card:** the lab is REST/CLI-driven; the dashboard card is a fast-follow.
- **End-to-end validation in a fresh 01 environment:** the layer is compile-checked and mirrors the
  live-verified 02 logic, but has not yet been run against a freshly `azd up`-provisioned 01 stack.

**Confirmed decisions:** (1) Module 07 Analytics & Optimization; Lessons → 08. (2) supervisor-turn
tiering core + worker sub-agent tiering stretch. (3) REST/CLI now + Angular card fast-follow.
(4) manual verify v1 + automated eval quality-gate capstone. (5) infra via Bicep, not manual/runtime.


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

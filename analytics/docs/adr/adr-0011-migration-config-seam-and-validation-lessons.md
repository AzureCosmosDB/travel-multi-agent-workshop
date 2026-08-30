# ADR-0011: Migration to the agent-centric design — the configuration seam as a taught step, and engine-validation lessons

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Mark Brown (@markjbrown), with agent analysis
- **Related:** `adr-0010-agent-centric-data-driven-analysis-engine.md` (the target design), `adr-0008-optimization-apply-loop-model-selection.md`, `../solution-architecture-guide.md`, `../solution-architecture-guide.md`

> **Purpose.** The **Solution Architecture Guide** describes the *target* design as a clean green-field
> artifact and deliberately carries **no** history of past-state or prior mistakes. This ADR is where
> that history lives: the **transition decisions and lessons** for getting from the current shipped
> implementation to the agent-centric design. Keeping migration history here keeps the guide a
> description of *what the system is and how it works*, not a change log.

## Context

Two "how do we get from here to there" questions surfaced while consolidating the target design
(ADR-0010). Neither belongs in the green-field guide, but both need a durable, evidenced home:

1. **The configuration/policy store.** The current implementation added a Cosmos policy/configuration
   layer (`OptimizationPolicies`, `OptimizationTurns`, `OptimizationInsights`, `Configuration`) that made
   optimizations easy to apply — including autonomously. The question: **keep it baked into the base
   solution, or roll back to the pre-analytics single-model app** (which is what most real multi-agent
   apps look like — no policy store capturing models, prices, thresholds)?

2. **How the engine is validated.** ADR-0010's rediscovery subsection framed the hand-authored scenario
   catalog (`SCEN-002…008`) as "the engine's test harness / answer key." On reflection that overclaims:
   a discovery engine cannot be regression-tested by a fixed, app-specific, human-authored list.

## Decision drivers

- **Teach the transferable lesson, not a rigged demo.** The workshop's value is showing users how to make
  *their* apps analyzable and optimizable — starting from apps that are *not* yet.
- **The config store is the config seam.** Per ADR-0010's seam ladder, an optimization is auto-applyable
  only if the app was built to expose the knob. The policy store *is* that knob infrastructure — so
  whether to provide it or teach it is the seam-ladder lesson applied to the workshop itself.
- **Representative baseline.** Most multi-agent apps hardcode their model and thresholds; the teaching
  baseline should match that reality.
- **Keep the KB internally consistent.** The validation framing in ADR-0010 and the guide must agree.

## Decision 1 — The configuration seam is a **taught step**, not a pre-provided given (hybrid)

Do **not** treat this as keep-vs-delete. Split the store's contents by kind and treat each accordingly:

- **Base travel app: representative — no policy store.** Model choice and thresholds are hardcoded/inline,
  matching a typical starting app. This preserves the premise of the seam lesson (there is no knob until
  someone builds one).
- **The optimization track introduces the configuration layer in two parts:**
  - **Provided (generic infrastructure): the model / pricing reference data.** A price lookup is generic
    (every cost-optimizing app needs one), externally sourced, and not app behavior — ship it as seed
    data; re-typing prices teaches nothing.
  - **Taught (the seam): the policy store the app reads.** Externalizing the tunable surface (model
    selection, thresholds, memory salience/retention) into a Cosmos policy document the app reads at
    runtime is the **foundational optimization module** — the *entry ticket to autonomy*. Building it
    once turns every subsequent optimization into an autonomous config flip.

This is **not destructive**: `02_completed/` keeps the policy store as the finished reference; `01_exercises/`
teaches building it — exactly the existing exercises-vs-completed split. The result: a representative
start, the seam lesson intact, and the autonomous-apply payoff reached as an *earned* result rather than a
pre-baked given.

**Module scope (provided vs. built).**
- **Provided (generic infrastructure):** the `OptimizationPolicies` container; the lifecycle service
  (`propose`/`stage`/`apply`/`revert` + audit + cache — already exists in `services/optimization_policy.py`);
  the Console; the **policy envelope schema + domain taxonomy** (Solution Architecture Guide §7.2); the
  **policy-binding SDK** (reference param schemas per domain, validate-and-clamp on write, a typed read
  helper with a fail-closed default, a discovery manifest, schema versioning — §7.2 "the params contract");
  and the **model/pricing reference data** (seed).
- **Built by the learner (the seam):** for one domain, (a) **declare its `params` schema** — the app's
  runtime value domains (deployment/tool/agent names), the allowed bounds, and any cross-field invariants —
  and (b) **read one policy domain and act on it** at a real read site. Concretely: declare the
  model-selection schema, then read the active policy and route the turn's model from `params` (the
  `select_deployment_for_turn` read). Optionally extend to a second domain (memory salience/retention) to
  show the pattern generalizes.
- **The learner builds the *read + act* side; the *write/apply* side (Console, lifecycle, engine
  recommendation) is provided** — the reusable lesson is "the app reads a policy and behaves accordingly,"
  which is the config seam in one sentence.

**Prescriptive vs. bespoke (what the module standardizes).** Be prescriptive about the **envelope** and the
**domain taxonomy** (broadly recognized; adopt for free), and leave the per-domain **`params` body**
app-specific (impossible to universalize; interpreted by the app's adapter). Future-proofing lives in the
contract and lifecycle, not a universal parameter set. See Solution Architecture Guide §7.2 for the
envelope, the canonical domain taxonomy, and which domains this app exercises vs. which other apps need.

**Generalizability is the argument *for* teaching it.** That most users' apps lack a policy store is not a
reason to hide one — it is the reason to teach building it. A policy store is the prerequisite for
autonomous (L4/L5) optimization (ADR-0010 §seams/§maturity); making its construction a lesson is the most
transferable takeaway of the workshop.

## Decision 2 — Engine validation is **detector-fixture-based**; the scenario catalog is teaching + acceptance (refines ADR-0010)

The rigorous regression suite for the discovery engine is **synthetic, pattern-keyed, matched
positive/negative detector fixtures with constructed ground truth** (Solution Architecture Guide §5.2):

- Fixtures test **patterns** keyed to `(detector-kind × dimension)`, app-agnostic.
- **Ground truth is constructed** by injecting a known issue of known magnitude and asserting the engine
  recovers it (including the quantity) — definitional truth, not opinion.
- **Matched positive + negative** fixtures validate **recall and precision**.
- **Coverage is measured over the detector matrix** (every cell needs a positive and a negative), and the
  suite is **living** — grown from human-labeled discoveries in the outcome ledger (ADR-0010 §analyst /
  guide §9.2).

The `SCEN-002…008` catalog serves as **teaching narratives** and a few **acceptance anchors** on the real
app — **not** the regression suite.

**Lesson (why the earlier framing was insufficient).** A hand-authored catalog fails as a regression suite
for a *discovery* engine because it is: (a) **instance-specific**, not pattern-level (doesn't generalize
across apps); (b) of **unknown coverage** (human-found; the catalog's own bar is only "≥1 per dimension"
and at least one entry is parked as unsupported by data); (c) **negative-free**, so it cannot test
precision (false positives); and (d) built on **asserted** rather than constructed ground truth. This
refines — does not delete — ADR-0010's rediscovery subsection.

## Options considered (configuration store)

### Option A — Keep the policy store baked into the base solution
Optimization demos work immediately. **Verdict:** rejected as the *base-app* default — it hides the seam
lesson (optimization looks like "just flip config"), is unrepresentative, and can read as a rigged demo.
(Retained only as the `02_completed/` finished reference.)

### Option B — Full rollback: remove the config store from the workshop
Most representative. **Verdict:** rejected — it discards the apply-loop/report/Console that depend on the
policy store and defers the autonomous payoff entirely, losing a key teaching surface.

### Option C — Hybrid: representative base app; provide pricing data; teach building the policy store
**Verdict:** chosen — representative start, seam lesson intact, autonomous payoff reached as an earned
result; aligns with the exercises-vs-completed split.

## Evidence

- **The policy/config store exists and the apply-loop depends on it:** containers `OptimizationPolicies`,
  `OptimizationTurns`, `OptimizationInsights`, `Configuration` (`02_completed/infra/shared/cosmosdb.bicep`,
  `deployAnalytics` gated); `apply_policy` / `revert_policy`
  (`services/optimization_policy.py`); `Configuration` holds mirrored model-pricing rows read by the
  report.
- **The base app is single-model (representative starting point):** one shared model in
  `services/azure_open_ai.py` used by the supervisor and sub-agents; the per-turn model router is
  analytics-track code, absent from the base app (see ADR-0010 Evidence).
- **Scenario-catalog current state supports the validation lesson:** `../solution-architecture-guide.md`
  states the coverage bar as "≥1 scenario per dimension," marks candidates "to be validated," and parks
  SCEN-006 as unsupported by data — i.e. human-authored, app-specific, unknown-coverage, negative-free.

## Consequences

- **Positive:** the workshop teaches the most transferable lesson (make an un-optimizable app
  optimizable); the base app is representative; the engine's validation story is rigorous and honest; the
  green-field guide stays free of migration history.
- **Negative / costs:** optimization demos require the foundational policy-store module first (added
  friction, but pedagogically productive); the exercises track must author that module; ADR-0010's
  rediscovery subsection is refined (a pointer is added there).
- **Risks:** users could get stuck in the policy-store plumbing — mitigate by scoping that module tightly
  and providing the pricing reference as data; the fixture-based validation suite must actually be built
  (tracked in ADR-0010's phases).

## Open items to verify

- The **module scope is defined** under Decision 1 (provided vs. built; the minimal read-one-domain seam)
  and the envelope/taxonomy in Solution Architecture Guide §7.2. Remaining: author the exact `01_exercises/`
  steps and the minimal policy-doc example the app reads.
- Whether any base-app behavior should read `Configuration` at all, or whether pricing lives purely in the
  analytics track (leaning: analytics-track only; the base app needs no price awareness).
- The detector-fixture harness itself (injection format, per-detector positive/negative pairs, the
  coverage-matrix report) — designed and built under ADR-0010's phases.

## References

- ADR-0010 (target design; seam ladder, maturity/risk, analyst, rediscovery); ADR-0008 (apply-loop /
  model selection); `../solution-architecture-guide.md` §5.2, §7, §8, §10; `../solution-architecture-guide.md`.
- Code: `02_completed/infra/shared/cosmosdb.bicep`, `services/optimization_policy.py`,
  `services/azure_open_ai.py`.

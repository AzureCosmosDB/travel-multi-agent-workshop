# ADR-0012: Validation-driven delivery — the de-risking loop and the validation ledger

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Mark Brown (@markjbrown), with agent analysis
- **Related:** `../charter.md` (first principle: data-grounded, "should work" is not "works"), `adr-0010-agent-centric-data-driven-analysis-engine.md` (the target design + phases P0–P4), `adr-0011-migration-config-seam-and-validation-lessons.md`, `../solution-architecture-guide.md`

> **Why this exists.** The Solution Architecture Guide and ADR-0010/0011 describe an ambitious target
> design. Much of it is **not built or validated**, and confident prose made speculative elements *read*
> as settled. This ADR is the antidote: a **spike-gated delivery loop** and a **validation ledger** that
> refuses to let unvalidated design accumulate. Nothing graduates from "designed" to "relied upon"
> without a passing spike and an observed exit criterion.

## Context

The owner's reality check: *"Are we operating in reality? … we're proposing a design we haven't validated
and can actually be built. There should be a loop where you build and test this design and keep going
until all elements are validated with a refined implementation guide and reference implementation —
including every element that requires human input, whose usability is also validated."*

This is the charter's first principle applied to our own design. The correction is not more design; it is a
**process** that grounds each element before we depend on it, and an honest **ledger** of what is real vs.
aspirational today.

## Decision — a spike-gated delivery loop

**The loop (kept deliberately simple):**
1. **Rank** the ledger by *risk × load-bearing-ness*; take the top **un-grounded** element.
2. **Spike:** write the *smallest throwaway proof* that answers its one open question. Define a **binary
   exit criterion up front** — observed, not "should work."
3. **Verdict:** **pass** → promote into the reference implementation + write that section of the
   implementation guide; mark **grounded**. **Fail** → **cut or redesign** the element; update the guide/ADR.
4. **Re-tag** the ledger and repeat until every *load-bearing* element is grounded.

**Cut is not permanent (owner appeal).** A `cut` element is **parked, not deleted** — it moves to a
`cut (revisitable)` state with a one-line note on *why* the spike failed. The owner may **reopen** any cut
item after review by proposing a candidate solution / a new spike; if the new spike passes, it graduates
like any other. So "cut" means "not validated *yet*, on the current approach," never "forbidden."

**Human-in-the-loop steps are validated too.** Every element that requires a human action (attest a deploy,
confirm a revert, review a staged diff, set an SLO, approve a card, declare a params schema) gets its own
**dry-run usability check**: a real person completes it with the affordance we ship. If they can't, that
step is broken design, not a footnote.

**Boundaries this loop enforces (from earlier decisions):** the platform **never runs/builds/tests/merges
code or touches CI/CD** (ADR-0011 / guide §9.1); config apply/revert is automatic, prompt/code is a
human-attested staged diff (§7.1). Any element implying otherwise is *speculative* until a spike says
otherwise.

**Where status lives.** The **guide stays the clean green-field target** (no status tags — per the owner's
directive). **This ledger** carries the honest per-element status. ADR-0010's phases **P0–P4 become
spike-gated**: a phase item ships only when its ledger row is `grounded`.

## The validation ledger

Status: **Grounded** = exists and works today (cited) · **Spike** = plausible, needs a cheap proof ·
**Speculative** = feasibility *or* value genuinely uncertain.

### A. The working spine — already real (Grounded)

| # | Element | Evidence |
|---|---|---|
| A1 | Config **policy store** (propose/stage/apply/revert + audit + cache) | `services/optimization_policy.py` |
| A2 | **Model-selection apply-loop** (per-deployment supervisor, tier classifier, policy read) | `travel_agents.py` (`classify_turn_tier`, `select_deployment_for_turn`, `_build_supervisor`) |
| A3 | **Memory-retention** apply/revert | `services/optimization_recommendations.py` (`apply_memory_retention` / `revert_memory_retention`) |
| A4 | **Staged-change** mechanism (`{file,diff}`, `apply_mode:"staged_change"`, `/stage`) | `optimization_api.py`, `optimization_recommendations.py` (`get_city_context_staged_change`) |
| A5 | **Turn-grain telemetry** (`Debug` → `OptimizationTurns`) + reverse-ETL / `compute_insights` | `data/export_conversations.py`, analytics notebook |
| A6 | **Report + Console** surfaces (dashboards + apply-loop UI) | `analytics/…Report.pbix`, `console/` |
| A7 | **Eval harness** (`answer_quality`/`correctness`/`humanness`; e2e/routing/tool_usage) | `01_exercises/evaluation/` (runner: LangSmith `aevaluate`) |
| A8 | **Hand-authored** recommendation/diagnostic builders (the current SCEN cards) | `services/optimization_recommendations.py` (the thing the redesign *replaces*) |
| A9 | **Pricing / Configuration** reference data (mirrored) | `Configuration` container |

*The core loop — measure → detect → recommend → apply(config) → re-measure — already runs end-to-end for the
config seam. We are not starting from zero.*

### B. The redesign frontier — not yet real

| # | Element | Status | Spike question → exit criterion |
|---|---|---|---|
| B1 | **Agent-execution (node) grain** re-instrumentation | **Built (2026-08-01); live capture pending run** | Spike `analytics/spikes/b1_node_grain_capture.py` proved derivation (reconciles, cost-neutral). **Now wired into the app:** `travel_agents_api.py` captures per-node records on `on_chat_model_end` (`dbg.node_execs`) alongside the rollup; `services/node_executions.py` persists them to a self-provisioning `NodeExecutions` container. Engine `instrumentation/node_grain.py` is the reusable capture. Remaining: verify on a live turn against Cosmos. |
| B2 | **Agent Scorecard** (agent × dimension rollup) | Spike (needs B1) | Render one agent's 8-dimension health from node-grain data |
| B3 | **Structural detectors** (repeated node, superseded-recalled) | Spike (low-risk) | Fires on an injected positive, silent on a clean negative |
| B4 | **Counterfactual detector**, generalized beyond model-selection | Spike (model-sel. version grounded) | Recovers an injected saving within tolerance |
| B5 | **Statistical detectors** + derived thresholds + min-sample/sequential verdict | Speculative | Enough data & not noisy? → stable baseline + "suppressed before N" behavior on fixtures |
| B6 | **Measured realized-complexity** signal (replace keyword tier) | Spike | Correlates with node-grain tokens; finds more opportunity than the keyword tier |
| B7 | **LLM analyst** (grounded, cited, seam-bounded cards) | **Spike — safety half grounded (2026-08-01); quality half pending LLM** | `analytics/spikes/b7_analyst_guardrails.py`: the engine enforces the 5 guardrails deterministically — accepts valid cards, **rejects** uncited / out-of-seam / free-form-seam cards, **overrides an invented \$9999 saving to the engine-computed value** (hallucination killed), and **forces a code-seam's autonomy to staged/L3** (LLM can't self-authorize). Remaining (needs creds): does a *real* model produce cards that pass the rubric at rate ≥X%? |
| B8 | **Projection functions** generalized + **What-If** view | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b8_projection_whatif.py`: projected saving matches analytic ground truth (61% reduction); **usage-scaling** projects onto future volume (~\$12.4k/mo @ 5000 turns/day); **price-only** → cost/outcome projectable & lower (1.62→0.63); **behavior-changing** → conversion NOT projected (measured only). |
| B9 | **Quality signal**: reference-free + per-agent rubrics + calibration | Spike | Reference-free judge agrees with the labeled datasets within tolerance |
| B10 | **Policy manifest + binding SDK** (typed params, validate/clamp, discovery, versioning, fail-closed) | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b10_policy_binding_sdk.py`: params is a typed, bounded, validated contract — clamps out-of-range; **rejects an unknown model** (runtime-bound value domain); enforces a cross-field invariant; **fails closed** to current behavior on missing/invalid/unknown-version; discovery manifest advertises the action space. |
| B11 | **Seam registry** (config-from-manifest, prompt-from-registry, recipe catalog) | Speculative | Engine lists available seams from manifest + prompt registry; a recipe instance renders |
| B12 | **Code-context provider** (read-only retrieval; optional) | Speculative (low priority) | Analyst drafts a diff from retrieved context on one seam |
| B13 | **Detector-fixture harness** (synthetic injection, pos/neg, magnitude) | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b13_fixture_harness.py` — constructed-ground-truth harness. Structural repeated-node: precision (clean = 0) + recall (17/17 injected). Counterfactual model-fit: recall (597/597), **magnitude recovered** (58.653406 vs 58.653406 @ 1e-6), precision (no-opportunity → 0). Pure stdlib, deterministic. Proves detectors are measurable with synthetic ground truth → promote into the real harness. |
| B14 | **Rediscovery acceptance** (engine rediscovers a SCEN end-to-end) | Speculative (needs B3/B4/B7) | Engine surfaces ≥1 SCEN case from data |
| B15 | **Outcome ledger + feedback-as-evidence** (re-rank underperformers) | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b15_outcome_ledger.py`: re-ranks candidates by track record (reliable pattern 100 vs unreliable 10 at equal raw prediction); **deterministic calibration** corrects an over-optimistic prediction toward the realized ratio; new patterns use a neutral prior; high-revert patterns down-ranked. No fine-tuning. |
| B16 | **Autonomy guard** (measure → auto-revert for config) | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b16_autonomy_guard.py`: confirmed→keep; **adverse/insufficient→auto-revert (config) with audit**; below min-sample→observing (no premature verdict); **non-config adverse→flagged, NOT auto-reverted** (human-governed). |
| B17 | **Node-grain golden fixture + agent-structured simulator** | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b17_node_grain_simulator.py`: fabricates agent-structured node executions with **0% missing agent structure** (fixes the ~36% gap), path mix within ±2% of configured weights, per-agent token means within ±10%, reproducible (seeded), no LLM. |
| B18 | **Power BI Option-A surface** (HTML card gallery + selection-bound translytical Apply/Revert) | Spike (every link evidenced; end-to-end build pending) | Assemble one page: recommendation rows as HTML-Content cards (Granularity role) → select a card → shared Apply/Revert data-function buttons `fx`-bound to `SELECTEDVALUE([scenario])` → UDF flips policy in Cosmos → report updates. *Ruled out (evidenced): per-card HTML button → UDF REST (sandbox strips scripts; null-origin CORS; no Entra token). Caveats: Service-only, DirectQuery; the current translytical button blocker is a **transient product bug** (per owner, fix ≈ mid-Aug 2026), **not** a tenant flag — Console is the always-works fallback.* |
| B19 | **Business-outcome linkage** (stamp a correlation key on the domain outcome) | **Built (2026-08-01); live verify pending** | Spike `analytics/spikes/b19_outcome_linkage.py` proved the join needs `sessionId`. **Now wired:** `session_id` threaded through the identity injection → `create_new_trip` (MCP) → `create_trip`, which persists `sessionId` on the Trip. All files py_compile clean. Remaining: verify a runtime-created trip carries `sessionId` and the session-grain cost-per-outcome join against Cosmos. |
| B20 | **Fabric built-in engine-LLM viability on F2** | Spike (largely verified — MS Learn `ai-services/ai-services-overview`, 2026-06-10) | **Verified:** built-in "Prebuilt AI models in Fabric" (public **preview**), Fabric-auth, **CU-billed**, via SynapseML/AI-functions/REST/SDK; current language models **`gpt-5.1`** (336 CU-sec/1K out) and **`gpt-5-mini`** (67) — `gpt-5`/`gpt-4.1`/`gpt-4.1-mini` retiring ~Jun 2026; embeddings `text-embedding-ada-002`. F64 minimum removed Apr 2025 → runs on **F2**. **BYOK** is the documented path to use the app's / a separate Azure model. **Residual caveats to confirm on the live workspace:** (a) preview→GA timing; (b) region gate (West US **is** supported ✓); (c) F2 = 2 CU/s ⇒ `gpt-5.1` only in small pre-baked batches, prefer `gpt-5-mini`. Catalog-quality risk is **resolved** (current-gen). |
| B21 | **F2 capacity throttling under our workload** | Spike + design | Test the workshop/solution end-to-end on **F2** (mirror + in-notebook engine LLM + report) and find where it throttles (429). Design: (a) **429 retry + exponential backoff** on engine-LLM / capacity-bound calls; and/or (b) **default to a larger capacity** for the live/at-volume path, with **sizing guidance** for adopters. Exit: a known-good config (SKU + batch size + retry policy) that runs the demo without failures, plus documented sizing guidance. |
| B22 | **Entra-only (keyless) engine-LLM auth** | Spike (verify before implementing) | Requirement: **no key/secret auth** (Entra-only). **Built-in path already satisfies it** (Fabric-managed auth). **External/BYOK is the risk:** Fabric notebooks **don't expose a managed identity / IMDS**, so `DefaultAzureCredential()` MI **fails** — must obtain an Entra token another way (running **user's token** via `notebookutils.credentials.getToken` for `https://cognitiveservices.azure.com`, or **workspace identity**) and pass it as `azure_ad_token_provider`, with the **Cognitive Services OpenAI User** data-plane role — and **avoid client secrets** too. Exit: notebook calls external Azure OpenAI **keyless** end-to-end. |

### C. Human-in-the-loop steps — each needs a dry-run usability check

| # | Human step | Exit criterion |
|---|---|---|
| C1 | Deploy attestation + revert confirmation (Console) | A person completes deploy-attest and revert-confirm; state + timestamp recorded |
| C2 | Reviewing a staged diff | A person can read and act on the staged-diff format |
| C3 | Setting SLO / confidence / min-effect policy | A person sets these via UI with guidance; the engine consumes them |
| C4 | Approving an analyst recommendation card | A person approves/rejects; the decision is audited |
| C5 | Declaring a domain params schema (learner) | A learner declares one schema + read site from the guide; the app behaves |

## Consequences

- **Positive:** an honest picture of reality (a strong Grounded spine + a clearly-marked speculative
  frontier); a bias to **cut** what doesn't survive a spike; the guide stays clean while status is tracked
  here; P0–P4 become spike-gated so we never "rely on 'should work.'"
- **Negative / costs:** slower than big-design-up-front; requires discipline to write throwaway spikes and
  to kill elements; the ledger must be kept current.
- **Risks:** the biggest load-bearing unknown is **B7 (the LLM analyst)** — if it can't reliably produce
  bounded, cited cards, the "discovers issues" story narrows toward detectors + human triage. That is an
  acceptable fallback, and finding it early is the point.

## Open items to verify

- Confirm each **Grounded** row still runs on the current branch (a quick smoke pass) before building on it.
- Sequence the first spikes: **B1 (node grain)** unblocks B2/B6; **B7 (analyst)** is the highest-risk value
  test; **B13 (fixture harness)** is the tool that makes every other detector/analyst spike measurable.
- Decide per element the numeric tolerances/`N`/`X%` in the exit criteria (currently placeholders).

## References

- `../charter.md` (first principles); ADR-0010 (phases), ADR-0011 (migration); Solution Architecture Guide.
- Code cited inline in the ledger (Grounded rows).

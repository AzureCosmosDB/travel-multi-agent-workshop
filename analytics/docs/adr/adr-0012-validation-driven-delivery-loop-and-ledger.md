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
| B1 | **Agent-execution (node) grain** re-instrumentation | **Grounded — verified live end-to-end (2026-08-01)** | Wired into `travel_agents_api.py` (per-node capture) + `services/node_executions.py` (self-provisioning `NodeExecutions`). **Live-verified against `cosmos-f2tx5x7js4bwi` (keyless/Entra):** (1) node executions written to Cosmos and read back by the engine (`data/verify_live.py`); (2) **captured from a real agent turn** driven through `/completion/stream` (`data/verify_e2e_turn.py`) — 7 node records with correct **semantic per-agent attribution** `['find_places','itinerary','supervisor']`. Live verification surfaced that sub-agents run nested under the supervisor's ReAct `tools` node, so attribution now prefers the `sub_agent` metadata tag over the raw `langgraph_node`. |
| B2 | **Agent Scorecard** (agent × dimension rollup) | **Grounded — verified live (2026-08-01)** | `engine/scorecard/` (registry-extensible `DIMENSIONS`) rolls node-grain into one `AgentScorecard` per agent, scored across the dimensions node-grain can measure (cost efficiency, model selection, workflow efficiency); the other 5 canonical dimensions are listed with the signal each still needs (no fabrication). Rendered by `data/agent_scorecard.py` (`--simulate` / `--from-cosmos`). **Verified live against `cosmos-f2tx5x7js4bwi`:** loaded real `NodeExecutions`, flagged the supervisor's premium-on-trivial model-selection opportunity. Self-test covers it. |
| B3 | **Structural detectors** (repeated node, superseded-recalled) | **Grounded (repeated_node); superseded-recalled deferred** | `structural.repeated_node` fires on a back-to-back same-agent turn; **fixture-proved in the self-test** (fires on an injected positive, silent on a clean negative). The memory-side `structural.superseded_recalled` is documented but **deferred** — it needs per-recall memory identity + supersession state (a MemoryEvent grain node-grain doesn't carry). |
| B4 | **Counterfactual detector**, generalized beyond model-selection | Spike (model-sel. version grounded) | Recovers an injected saving within tolerance |
| B5 | **Statistical detectors** + derived thresholds + min-sample/sequential verdict | **Grounded (spike passed 2026-08-01)** | `detectors/statistical.cost_regression`: fires only when an agent's recent output-token mean is a **statistically significant** (z≥3 off its own baseline), **practically material** (≥20% effect), and **stable/consistent** shift — with a **min-sample gate** (suppressed before N). Fixture-proved in the self-test: suppressed before N, silent on a stationary baseline, **not tripped by a single outlier**, fires on a consistent material regression; and it stays silent on the stationary simulator (no pipeline false positive). |
| B6 | **Measured realized-complexity** signal (replace keyword tier) | **Grounded (spike passed 2026-08-01)** | `engine/complexity/` makes realized complexity (measured node-grain output tokens) a first-class primitive next to a faithful stdlib mirror of the app's keyword classifier. `compare_coverage` proves the measured signal has **higher recall of truly-trivial turns** (catches ≥2 extra downgrade opportunities the conservative keyword tier misses) with **zero false-downgrades** of truly-substantive turns. Fixture-proved in the self-test. |
| B7 | **LLM analyst** (grounded, cited, seam-bounded cards) | **Grounded — safety + quality verified live (2026-08-01)** | Safety half: `analytics/spikes/b7_analyst_guardrails.py` (guardrails reject/override deterministically). **Quality half verified LIVE against Azure OpenAI** (`data/verify_analyst_live.py`): the real model produced **bounded, cited, correctly-seamed** cards for both opportunities (2/2 accepted; chose `config/model-selection` and `prompt/supervisor.prompty`), and **hallucinated dollar savings ($900, $120) which the engine caught and overrode** to the computed values ($52.66, $0). "LLM proposes, engine disposes" proven on real hallucinated output. |
| B8 | **Projection functions** generalized + **What-If** view | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b8_projection_whatif.py`: projected saving matches analytic ground truth (61% reduction); **usage-scaling** projects onto future volume (~\$12.4k/mo @ 5000 turns/day); **price-only** → cost/outcome projectable & lower (1.62→0.63); **behavior-changing** → conversion NOT projected (measured only). |
| B9 | **Quality signal**: reference-free + per-agent rubrics + calibration | **Grounded — verified live (2026-08-01)** | `engine/quality/`: reference-free judge (LLM injected as an `invoke` callable so the engine stays import-clean), per-agent `RUBRICS` (supervisor/find_places/itinerary, each different), all mapped to the pluggable `EvaluationResult` primitive; `calibrate()` reports agreement/precision/recall vs human labels. Self-test calibrates the deterministic baseline within tolerance. **Live-verified** (`data/verify_quality_live.py`): the REAL Azure OpenAI reference-free judge agreed with a per-agent labeled set at **agreement 1.0 / precision 1.0 / recall 1.0**. |
| B10 | **Policy manifest + binding SDK** (typed params, validate/clamp, discovery, versioning, fail-closed) | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b10_policy_binding_sdk.py`: params is a typed, bounded, validated contract — clamps out-of-range; **rejects an unknown model** (runtime-bound value domain); enforces a cross-field invariant; **fails closed** to current behavior on missing/invalid/unknown-version; discovery manifest advertises the action space. |
| B11 | **Seam registry** (config-from-manifest, prompt-from-registry, recipe catalog) | **Grounded (spike passed 2026-08-01)** | `engine/seams/` registers the app's seams (1 config domain, 2 prompt files, 1 code recipe); `surface()` returns the exact declared-surface shape the analyst guardrails consume (the reverse-ETL producer now sources it here, removing the duplicate). `render_recipe()` renders a concrete instance: the config seam binds params through the domain SDK to a **fail-closed policy doc** (auto/L4); prompt/code render **staged, human-attested** changes. Self-test covers listing + recipe render + fail-closed. |
| B12 | **Code-context provider** (read-only retrieval; optional) | **Grounded (spike passed 2026-08-01)** | `engine/codecontext/`: a **read-only** retrieval interface (no write path) with two impls — `InMemoryProvider` (testable) and `FileBackedProvider` (strict allowlist). `scaffold_diff` turns retrieved snippets into a grounded, staged (human-reviewed) diff skeleton. **Verified against the real repo:** `FileBackedProvider` retrieved `select_deployment_for_turn`/`classify_turn_tier` from `travel_agents.py`, refused a non-allowlisted file, and drafted a diff anchored to real file/line context. Self-test covers it. |
| B13 | **Detector-fixture harness** (synthetic injection, pos/neg, magnitude) | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b13_fixture_harness.py` — constructed-ground-truth harness. Structural repeated-node: precision (clean = 0) + recall (17/17 injected). Counterfactual model-fit: recall (597/597), **magnitude recovered** (58.653406 vs 58.653406 @ 1e-6), precision (no-opportunity → 0). Pure stdlib, deterministic. Proves detectors are measurable with synthetic ground truth → promote into the real harness. |
| B14 | **Rediscovery acceptance** (engine rediscovers a SCEN end-to-end) | **Grounded (spike passed 2026-08-01)** | `pipeline.rediscovered_scenarios` maps discovered opportunities to catalogued SCEN ids (analytics/docs/optimization-scenarios/). Self-test acceptance: the full pipeline run over data rediscovers **SCEN-007** (model selection on trivial turns) end-to-end from telemetry (detect → project → propose → guardrail → rank → SCEN id). Prereqs B3/B7 also Grounded; extends as B4/other detectors land. |
| B15 | **Outcome ledger + feedback-as-evidence** (re-rank underperformers) | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b15_outcome_ledger.py`: re-ranks candidates by track record (reliable pattern 100 vs unreliable 10 at equal raw prediction); **deterministic calibration** corrects an over-optimistic prediction toward the realized ratio; new patterns use a neutral prior; high-revert patterns down-ranked. No fine-tuning. |
| B16 | **Autonomy guard** (measure → auto-revert for config) | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b16_autonomy_guard.py`: confirmed→keep; **adverse/insufficient→auto-revert (config) with audit**; below min-sample→observing (no premature verdict); **non-config adverse→flagged, NOT auto-reverted** (human-governed). |
| B17 | **Node-grain golden fixture + agent-structured simulator** | **Grounded** (spike passed 2026-08-01) | `analytics/spikes/b17_node_grain_simulator.py`: fabricates agent-structured node executions with **0% missing agent structure** (fixes the ~36% gap), path mix within ±2% of configured weights, per-agent token means within ±10%, reproducible (seeded), no LLM. |
| B18 | **Power BI Option-A surface** (HTML card gallery + selection-bound translytical Apply/Revert) | Spike (every link evidenced; end-to-end build pending) | Assemble one page: recommendation rows as HTML-Content cards (Granularity role) → select a card → shared Apply/Revert data-function buttons `fx`-bound to `SELECTEDVALUE([scenario])` → UDF flips policy in Cosmos → report updates. *Ruled out (evidenced): per-card HTML button → UDF REST (sandbox strips scripts; null-origin CORS; no Entra token). Caveats: Service-only, DirectQuery; the current translytical button blocker is a **transient product bug** (per owner, fix ≈ mid-Aug 2026), **not** a tenant flag — Console is the always-works fallback.* |
| B19 | **Business-outcome linkage** (stamp a correlation key on the domain outcome) | **Grounded — verified live end-to-end (2026-08-01)** | `session_id` threaded through identity injection → `create_new_trip` → `create_trip` persists `sessionId`. **Live-verified against `cosmos-f2tx5x7js4bwi`:** (1) `create_trip(session_id=…)` persists/reads `sessionId` (`data/verify_live.py`); (2) **a real agent turn** (`data/verify_e2e_turn.py`) had the itinerary agent call `create_new_trip`, producing a Paris Trip stamped with the driving session key. |
| B20 | **Fabric built-in engine-LLM viability on F2** | **Grounded — verified live on F2 (2026-08-01)** | **Verified live** on capacity `fabf2tx5x7js4bwi` (F2, West Central US): the Fabric **built-in** `gpt-5-mini` ran from a notebook job via **SynapseML `OpenAIPrompt`** (keyless, capacity-billed) and returned a real completion (`data/../analytics/fabric/verify_engine_on_fabric.py`). Docs context: built-in "Prebuilt AI models in Fabric" (preview), CU-billed; catalog `gpt-5.1`/`gpt-5-mini`; F64 min removed Apr 2025 → F2 works. **Infra finding:** `%pip` fails in non-interactive RunNotebook jobs — use **pre-installed SynapseML + `requests`** (no `openai` package). |
| B21 | **F2 capacity throttling under our workload** | **Grounded — verified live on F2 (2026-08-01)** | **Verified live:** a burst of **20** built-in-model calls on F2 completed **20/20 with no surfaced throttling** in 6.3s (`verify_engine_on_fabric.py`). Throttle-resilience mechanism: **SynapseML applies internal exponential-backoff retries on 429**, so batch inference absorbs bursts. Known-good config for the workshop/demo scale: **F2 + SynapseML batched calls + `gpt-5-mini`**. Sizing guidance for adopters: for higher volumes, increase batch size / concurrency (SynapseML retries) or size up the capacity — F2 = 2 CU/s. (No 429 reached at demo scale, which is the intended outcome.) |
| B22 | **Entra-only (keyless) engine-LLM auth** | **Grounded — verified live on F2 (2026-08-01)** | **Verified live — the previously-open risk is retired.** From a Fabric notebook job, `notebookutils.credentials.getToken("https://cognitiveservices.azure.com")` returned an Entra token (the running user's), and a **keyless** REST call to the app's external Azure OpenAI (`foundry-f2tx5x7js4bwi`, `gpt-5.1`) returned **200 OK** — no keys/secrets, no `DefaultAzureCredential`/IMDS (`verify_engine_on_fabric.py`). The deploying user has data-plane access (same identity that runs the local live checks). Both the built-in path (Fabric-managed) and the external/BYOK path are keyless. |

### C. Human-in-the-loop steps — each needs a dry-run usability check

| # | Human step | Exit criterion | Status |
|---|---|---|---|
| C1 | Deploy attestation + revert confirmation (Console) | A person completes deploy-attest and revert-confirm; state + timestamp recorded | **Grounded — verified live** (Console `Attest deploy` / `Confirm revert` → `POST /agent/{tenant}/decision`; audited in `OptimizationGovernance` with by+timestamp; opportunity `governed_state` reflects it) |
| C2 | Reviewing a staged diff | A person can read and act on the staged-diff format | **Grounded — verified live** (Console `Review diff` → `GET /agent/{tenant}/opportunity/{id}/diff`; config renders the fail-closed policy doc, prompt/code render a staged human-attested change via seams/codecontext) |
| C3 | Setting SLO / confidence / min-effect policy | A person sets these via UI with guidance; the engine consumes them | **Grounded — verified live** (Console SLO form → `POST /agent/{tenant}/slo`; raising `min_effect` to 0.30 flipped `clears_slo` false for a 0.271-effect opportunity — the engine consumes it) |
| C4 | Approving an analyst recommendation card | A person approves/rejects; the decision is audited | **Grounded — verified live** (Console `Approve`/`Reject` → `POST /agent/{tenant}/decision`; recorded in the audit trail) |
| C5 | Declaring a domain params schema (learner) | A learner declares one schema + read site from the guide; the app behaves | **Grounded — verified live** (Console schema form → `POST /agent/{tenant}/schema`; the engine binds it through the fail-closed SDK — clamped `ttl_days` 9999→365 — and returns the discovery manifest) |

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

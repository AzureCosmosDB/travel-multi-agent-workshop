# ADR-0008: Optimization apply-loop — live, policy-driven capability-tiered model selection (SCEN-007)

- **Status:** Accepted
- **Date:** 2026-07-09
- **Deciders:** @markjbrown (mjbrown)
- **Related:** ADR-0001 (optimization-loop surface), ADR-0006 (v2 baseline), ADR-0007 (Debug-first instrumentation), SCEN-007, SCEN-003

> **Note (superseded figures):** the baseline numbers below (100% `gpt-4.1-mini`, 48% trivial) reflect the original pre-modernization dataset. The workshop now defaults to `gpt-5.1` and measures trivial via the classifier's `complexity_tier == "trivial"` (~23% in the current sample data). This ADR is kept as a historical record; see SCEN-007 for current figures.

## Context

The analytics vision requires not just *observing* agent behavior but **closing the loop**:
`instrument → detect → recommend → apply → verify`, with lower-risk optimizations applied
autonomously (maturity Level 4/5). SCEN-007 (capability-tiered model selection) was chosen as the
first end-to-end apply-loop because it is a **lower-risk, reversible policy** (not a prompt/code
change) and is the canonical "system tunes itself" example.

A prerequisite reality (ADR-0007 data): the app runs a **single model** for every turn
(100% `gpt-4.1-mini`), and 48% of turns are trivial. So "model selection" is an *opportunity*, and
realizing it needs (a) more than one deployment and (b) a mechanism to route per turn and prove the
effect from data.

## Decision drivers

- **Genuinely reversible + auditable** apply — no code edits at apply time (that is what makes L4/L5
  safe). Prompt/workflow changes stay human-governed (ceiling L3) and are explicitly *out of scope*.
- **Safe by default** — with no active policy the app behaves exactly as before.
- **Empirically verifiable** — the effect must be measurable from signal we already capture (ADR-0007
  Debug turn logs), because estimated savings can mislead (reasoning models bill reasoning tokens).
- Minimal blast radius on v2's single prebuilt-supervisor request path.

## Options considered

### Write-back target
- **A. Cosmos policy document the app reads at request time (chosen).** Versioned, reversible,
  auditable; apply/revert = a status flip. Matches the Cosmos-native analytics stack.
- **B. Prompt/code write-back (edit `.prompty` / open a PR).** Rejected for the *autonomous* loop —
  code changes are higher-risk and human-governed (L3); belongs to a different, gated flow.

### Per-turn model routing mechanism
- **A. Pre-turn heuristic classifier → per-tier prebuilt supervisor (chosen).** Classify the latest
  user message (trivial/routine/complex), select a supervisor built against that tier's deployment.
  Reliable across LangGraph versions; supervisors share tools + checkpointer.
- **B. A custom "routing" chat model proxying to per-tier models via ContextVar.** Rejected —
  implementing a correct `BaseChatModel` proxy (sync/async/stream/`bind_tools`) is error-prone;
  reliability beats elegance for the request path.

### Model tiers
- Chosen **later-gen models with free GlobalStandard quota**: `gpt-5-nano` (trivial), keep
  `gpt-4.1-mini` (routine), `gpt-5.1` (complex). The requested `gpt-5.4`/`gpt-5.4-nano` were **fully
  quota-allocated subscription-wide** (identical `used==limit` across every region), with no trimmable
  in-subscription consumer, so a quota-increase request would be required — avoided.

## Evidence (verified live on `TravelAssistant`)

- Deployed `gpt-5-nano` + `gpt-5.1` to `openai-kfpokdh52vbec`; smoke-tested both (need
  `max_completion_tokens`, reject non-default `temperature`, api `2025-04-01-preview`).
- Full loop proven with real turns (tenant `aptest`), each Debug turn recording `complexity_tier` +
  `model_deployment`, and `model_name` independently confirming the serving model:

  | tier | deployment | model_name (actual) | total tokens | est $ |
  |---|---|---|---|---|
  | trivial | gpt-5-nano | gpt-5-nano-2025-08-07 | 3,828 | 0.00036 |
  | routine | gpt-4.1-mini | gpt-4.1-mini | 15,946 | 0.00686 |
  | complex | gpt-5.1 | gpt-5.1 | 32,616 | 0.05563 |

- **Reasoning-token honesty:** `gpt-5-nano` spent 493 output tokens on "hi", but at its $0.05 input
  price the trivial turn is still **~4× cheaper** than mini — settled by the measured verify, not the
  estimate.
- `apply` → tiers route live; `revert` → next turn records `tier=default, deployment=gpt-4.1-mini`.

## Decision

Implement Option A + A. Specifically:
- `services/optimization_policy.py` — self-provisioning `OptimizationPolicies` Cosmos container;
  `proposed/active/reverted` with version + audit; short-TTL cache. Only `active` + `params.enabled`
  changes runtime behavior.
- `services/azure_open_ai.get_chat_model(deployment)` — cached per-deployment model factory;
  reasoning deployments (`gpt-5*`/o-series) omit temperature and use `2025-04-01-preview`.
- `travel_agents.py` — `classify_complexity_tier` heuristic + `get_supervisor_for_turn` (per-tier prebuilt
  supervisor, shared tools/checkpointer; default deployment when no active policy).
- `travel_agents_api.py` — select the tiered supervisor per turn; record `complexity_tier`/
  `model_deployment` on the Debug turn log.
- `services/optimization_recommendations.py` + `optimization_api.py` — `/optimizations` REST surface
  (recommend card, propose/apply/revert). Prices are labeled **estimates**.
- `analytics/scripts/optimization_mining.py --verify` — per-tier token + estimated-cost report from Debug.

## Consequences

- **Positive:** a real, reversible, audited apply-loop closing detect→apply→verify; sets the template
  for other lower-risk policy scenarios (SCEN-004 retention, SCEN-002 retrieval weighting) and for the
  Fabric/reverse-ETL apply path (ADR-0001).
- **Negative / costs:** the pre-turn classifier is a heuristic (input-only), so triviality is
  approximate; a turn's true cost is known only after it runs. Estimated savings can mislead — the
  verify step is authoritative and gating must be enforced before autonomous apply.
- **Risks:** reasoning models change per-turn economics (reasoning tokens) and latency; the complex
  tier (`gpt-5.1`) is ~8× a supervisor turn, so its value must be judged on **cost per outcome**
  (SCEN-003), not per-turn cost. Two new deployments consume (small) quota.

## Open items to verify

- Wire a **quality gate** (e2e/answer-quality evaluator) into `apply` so an optimization that lowers
  helpfulness auto-reverts — today apply is unconditional.
- Cost-per-outcome (SCEN-003) before/after across a full persona run, not just per-turn cost.
- Decide whether the **complex** tier should upgrade the itinerary *sub-agent* model too (currently
  only the supervisor turn is tiered).
- Surface the recommend/apply/revert card in the Angular dashboard (currently REST-only).

## References

- Implementation: `02_completed/python/src/app/services/optimization_policy.py`,
  `services/optimization_recommendations.py`, `optimization_api.py`,
  `services/azure_open_ai.py` (`get_chat_model`), `travel_agents.py`
  (`classify_complexity_tier`, `get_supervisor_for_turn`), `travel_agents_api.py`
  (tier selection + Debug recording), `analytics/scripts/optimization_mining.py` (`--verify`).
- SCEN-007 (`docs/solution-architecture-guide.md`), ADR-0001, ADR-0007.

# SCEN-007 — Full model used for trivial turns (model-selection policy)

- **Status:** Documented (data-validated on the `v2_analytics` baseline)
- **Category:** Model selection / cost efficiency
- **Vision questions it serves:** *"Which models drive the highest costs?"*, *"What is the cost per successful outcome?"*, *"Which optimizations can be automated safely?"*
- **Optimization dimensions:** model selection · cost efficiency
- **Fix seam:** model-selection **policy** (config) once the routing seam exists → **lower-risk**
- **Maturity ceiling:** **L4/L5 (Autonomous / Adaptive)** — model-selection policy is a vision-listed lower-risk domain; the ongoing tuning can run unattended (bounded, reversible, measurable)
- **Related:** ADR-0001 (optimization-loop surface), ADR-0003 (Open Agent Analytics Schema), [baseline-findings](baseline-findings.md)

## Symptom

Every turn — trivial or complex — runs on the same full chat model. Greetings, acknowledgements,
and one-line clarifications cost the same model as a multi-tool itinerary build.

## Evidence (baseline, tenant `v2_analytics`)

- **All 291 turns** ran on `gpt-4.1-mini` — there is **no task-based model selection**.
- **140/291 turns (48%)** were **trivial**: no sub-agent delegation (`handoff_count = 0`) **and**
  `< 60 output tokens`. Nearly half of all turns are cheap-to-serve yet use the full model.
- Prompt caching is already doing its job (**86% cache-hit** on input tokens), so the remaining
  lever is **not** more caching — it is **routing trivial turns to a smaller/cheaper model**.

## Detection (from data we already capture — ADR-0007 Debug)

Signal is entirely in the `Debug` log: `model_name`, `handoff_count`, `output_tokens`,
`total_tokens`. A turn is a **model-downgrade candidate** when it did not delegate and produced a
short response.

```sql
-- share of turns that are trivial yet run on the full model
SELECT
  COUNT(*)                                                   AS total_turns,
  SUM(CASE WHEN handoff_count = 0 AND output_tokens < 60
           THEN 1 ELSE 0 END)                                AS downgrade_candidates,
  SUM(CASE WHEN handoff_count = 0 AND output_tokens < 60
           THEN total_tokens ELSE 0 END)                     AS candidate_tokens
FROM Debug
WHERE tenantId = 'v2_analytics';
```

The dashboard turns `candidate_tokens × (full_price − cheap_price)` into a projected monthly saving.

## Candidate-optimization card (dashboard)

> **48% of turns are trivial but run on the full model.**
> 140 turns · projected saving *≈ $X/mo* at current volume.
> **Proposed policy:** route turns predicted trivial (greeting / acknowledgement / clarification,
> no tool need) to `gpt-4.1-nano`/a smaller model; keep the full model for delegating turns.
> **[Apply policy]** · **[Enable auto-tune]**

## The fix — and why it reaches L4/L5

This scenario is a clean example of the **two-step path to autonomy**:

1. **Enable the seam (one-time, human-governed / L3).** The app currently exposes a single shared
   `model` (`services/azure_open_ai.py`). Introducing a small **model router** (pick the model per
   turn from a difficulty signal) is a **code** change → higher-risk, human-reviewed, deployed once.
2. **Tune the policy (ongoing, autonomous / L4→L5).** Once the router exists, *which* turn classes
   map to *which* model — and the confidence threshold — is a **policy** (config/data), a
   vision-listed **lower-risk** domain. The platform can adjust it automatically, measure quality
   and cost, and roll back if quality dips. This is exactly the *"model selection policy"* the
   vision names for autonomous optimization, and the canonical **self-adapting Level 5** loop.

> Contrast with SCEN-001, whose fix is a **prompt** (higher-risk) and therefore caps at **L3
> assisted**. SCEN-007's *policy* fix is what lets a domain climb to **L4/L5** — the two scenarios
> together teach the whole maturity ladder.

## Guardrails (so autonomy stays safe)

- **Quality gate:** the auto-tuner may only downgrade a turn class if the evaluation score
  (Pillar 5 / e2e judge) stays within a set tolerance; any regression auto-reverts.
- **Bounded & reversible:** policy changes are parameter edits with a recorded prior value.
- **Auditable:** every automated change is logged with before/after cost and quality.

## Close the loop (before/after)

After enabling the policy, recompute `candidate_tokens` and the blended cost per successful outcome
(SCEN-003), and watch the evaluation score hold. Expected: large drop in trivial-turn cost with no
quality regression — the self-improving result the vision targets.

## Lab exercise framing

- **A (data-first):** compute the trivial-turn share and projected saving from `Debug`.
- **B (assisted, L3):** review the proposed model-router change + impact analysis; deploy the seam.
- **C (autonomous, L4/L5):** enable auto-tuning of the model-selection policy behind the quality
  gate; watch it self-adjust and hold quality.

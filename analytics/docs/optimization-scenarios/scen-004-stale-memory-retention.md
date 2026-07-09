# SCEN-004 — Stale/superseded memories accumulate (retention & salience policy)

- **Status:** Documented (data-validated on the `v2_analytics` baseline)
- **Category:** Memory effectiveness / lifecycle
- **Vision questions it serves:** *"Which memories are stale or ineffective?"*, *"Which memories should be consolidated or removed?"*, *"What is the effective half-life of memory?"*
- **Optimization dimensions:** memory effectiveness · cost efficiency
- **Fix seam:** memory **retention + salience policy** (existing toolkit knobs) → **lower-risk**
- **Maturity ceiling:** **L4/L5 (Autonomous / Adaptive)** — "memory salience tuning" and "memory retention policies" are the vision's *first-named* lower-risk autonomous domains
- **Related:** ADR-0001 (optimization-loop surface), Memory Intelligence (Pillar 4), [baseline-findings](baseline-findings.md)

## Symptom

As users change their minds, the memory store fills with **superseded** facts (old dietary
restriction, old hotel preference, old budget). They remain in the container, can be retrieved, and
add cost and noise to personalization — without contributing to outcomes.

## Evidence (baseline, tenant `v2_analytics`)

- **509 of 760 memories (67%)** are **superseded** (`superseded_by` set) — the preference-conflict
  conversations drive heavy churn.
- `salience` is populated on **610** memories (mean **0.82**, range 0.5–0.95) — so salience-based
  policy is directly actionable.
- `recall_memories` ran on **52/291 turns (18%)**: recall is active (post-fix), which makes the
  quality of *what* is recallable matter — a 67% stale ratio is a large prune/consolidate signal.

## Detection (from data we already capture)

The `memories` container already carries lifecycle fields (`type`, `salience`, `superseded_by`,
`supersede_reason`, `created_at`, `updated_at`). No new instrumentation.

```sql
-- staleness + low-salience load per user
SELECT m.user_id,
       COUNT(*)                                              AS total,
       SUM(CASE WHEN IS_DEFINED(m.superseded_by) THEN 1 ELSE 0 END) AS superseded,
       AVG(m.salience)                                       AS avg_salience
FROM memories m
GROUP BY m.user_id;
```

Pillar-4 metrics extend this: retrieval frequency, reuse frequency, memory aging/decay, and
**memory effectiveness** (does recall of a memory precede a successful outcome?).

## Candidate-optimization card (dashboard)

> **67% of stored memories are superseded (stale).**
> 509 stale memories across N users · adds retrieval noise + cost.
> **Proposed policy:** (a) exclude `superseded_by`-set memories from retrieval; (b) apply a decay to
> `salience` by age; (c) set a retention TTL on superseded facts. **[Apply policy]** · **[Enable auto-tune]**

## The fix — knobs already exist (why this is a clean L4/L5)

Unlike SCEN-007, **no new code seam is needed** — the Agent Memory Toolkit already exposes the policy
surface, so this domain is autonomous-ready today:

- **Retention / TTL:** `memories_turns` already carries a 30-day TTL; superseded facts in `memories`
  can be given a bounded TTL (they are currently `defaultTtl: -1`).
- **Salience:** decay `salience` with age and de-prioritize low-salience memories in retrieval.
- **Cadence:** `FACT_EXTRACTION_EVERY_N`, `DEDUP_EVERY_N`, `THREAD_SUMMARY_EVERY_N`,
  `USER_SUMMARY_EVERY_N` tune how aggressively memories are formed/deduped/summarized.

All of these are **parameters/policies** — the vision's lower-risk class — so the platform can adjust
them, measure effect, and roll back automatically. This is the memory-intelligence embodiment of the
**self-adapting Level 5** loop.

## Guardrails

- **Never hard-delete on autopilot:** prefer retrieval-exclusion + TTL over destructive deletes;
  keep an audit of what was pruned and why.
- **Quality gate:** a retention/salience change may only stand if personalization quality
  (evaluation score) and recall-precision hold; regressions auto-revert.
- **Bounded & reversible:** TTL/salience/cadence are numeric knobs with recorded prior values.

## Close the loop (before/after)

After applying, recompute the stale ratio, retrieval noise, and memory-driven outcome rate (does
recall still precede confirmed trips as well or better?), plus token cost of the recall path.
Expected: stale ratio and retrieval cost fall while outcome contribution holds or improves.

## Lab exercise framing

- **A (data-first):** compute per-user staleness and salience load from `memories`.
- **B (assisted, L3):** review the proposed retention/salience policy + impact analysis.
- **C (autonomous, L4/L5):** enable auto-tuning of retention TTL + salience decay behind the quality
  gate; watch the stale ratio self-correct over successive runs.

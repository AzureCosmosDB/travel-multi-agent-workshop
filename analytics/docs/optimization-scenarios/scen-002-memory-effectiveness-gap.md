# SCEN-002 — Memory-effectiveness gap (which memories actually improve outcomes?)

- **Status:** Documented (candidate) — **partially measurable today; requires an instrumentation add to close**
- **Category:** Memory effectiveness
- **Vision questions it serves:** *"Which memories improve success rates?"*, *"Which memories are stale or ineffective?"*
- **Optimization dimensions:** memory effectiveness · agent quality · cost efficiency
- **Fix seam:** retrieval weighting + salience/retention policy → **lower-risk (autonomous L4/L5)**
- **Maturity ceiling:** **L4–L5** once measurable (memory policies are a lower-risk domain)
- **Related:** SCEN-004 (stale-retention — the *supply* side), Memory Analytics (Pillar 3), [baseline-findings](baseline-findings.md)

## The question

SCEN-004 asks *"which memories are stale?"* (67% superseded). SCEN-002 asks the harder,
higher-value question: **"which memories actually improve outcomes when recalled?"** — so we can
**weight retrieval toward memories that help** and prune/deprioritize memories that are recalled but
never move a result. This is the memory analog of feature importance.

## Honest measurement caveat (verification discipline)

We can measure **recall volume** today, but we **cannot yet attribute outcome lift to a specific
memory** with the data we currently capture:

- ✅ We know **how often** recall happens: `recall_memories` appeared on **52/291 turns (18%)** in the
  baseline (post the recall-tool fix).
- ✅ We know **which** memories exist, their `type`, `salience` (mean 0.82), and `superseded_by`.
- ❌ We do **not** persist, per turn, **which memory IDs were retrieved** and **whether that turn
  advanced the outcome** (e.g., led toward a confirmed trip). Without that join we cannot compute a
  per-memory "improves success rate" score.

> **Do not** claim a memory-effectiveness number from the current baseline — it isn't in the data.
> This card is promoted as a *candidate with a defined instrumentation gap*, not a data-validated
> finding like SCEN-003/004/005/007/008.

## Detection — what we can show now vs. what's needed

**Now (recall volume + stale supply, already captured):**

```sql
-- how often recall fires
SELECT COUNT(*) FROM Debug d
WHERE d.tenantId='v2_analytics' AND CONTAINS(d.tool_calls, 'recall_memories');
```

**To close the gap (small instrumentation add):** persist, per turn, the **retrieved memory IDs**
alongside the existing Debug turn record, then join to the session outcome:

```
Debug turn  → retrieved_memory_ids: ["mem_123","mem_456"]
Session     → outcome: confirmed | abandoned
=> per-memory:  recalled_count, recalled_in_won_sessions, lift = won_rate(recalled) - baseline
```

This reuses signal the retrieval layer *already has at recall time* — it just isn't written down yet.
It is a **capture change, not a schema redesign** (extends the same Debug turn document).

## Candidate-optimization card (dashboard) — *after* instrumentation

> **Memories ranked by outcome lift.** Top memories → boost retrieval weight; zero/negative-lift
> memories that are frequently recalled → deprioritize or retire.
> **Proposed fix:** (L4/L5) adjust **retrieval weighting** and **salience** from measured lift, behind
> a quality gate — a lower-risk, autonomous memory policy. **[Apply weighting]**

## The fix & maturity

- **Retrieval weighting + salience (L4/L5, lower-risk):** memory policies (salience, retention,
  retrieval weight) are the autonomous domain from the risk model — once lift is measurable, this is
  the Level-5 "system tunes its own memory" example, complementing SCEN-004's retention side.

## Guardrails

- Requires the instrumentation add **first** — don't ship weighting changes off an unmeasured proxy.
- Gate weighting changes on the outcome/quality evaluator; auto-revert on regression.
- Never let weighting fully *exclude* a memory type (e.g., safety/procedural) — bound the down-weight.

## Close the loop

Two-step scenario: **(1)** land the retrieved-memory-ID capture, regenerate/observe; **(2)** once
per-memory lift is real in the data, promote to a fully data-validated L4/L5 worked scenario and wire
the weighting apply-loop. Until step 1 lands, this stays a *candidate*.

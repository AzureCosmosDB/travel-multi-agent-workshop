# Baseline findings — mining the `v2_analytics` dataset

First **data-first** pass (discovery method #1) over the generated baseline in
`TravelAssistantV2` / tenant `v2_analytics`. These numbers validate (or weaken) the
candidate scenarios in the [catalog](README.md) with real signal from data we already capture.

> **Caveat:** this is **generated** data (12 personas via the data generator), not production
> traffic. The numbers are illustrative of *what the analytics layer surfaces*, not a claim about
> real users. Re-run after regeneration; magnitudes will shift, the patterns should hold.

**Corpus:** Debug=291 turns · Messages=582 · Trips=11 · Memories=760 · Sessions=32.

## Findings by candidate

### ✅ SCEN-003 — cost per successful outcome (STRONG)
- Total tokens **1,536,032** across 32 sessions for **7** confirmed/completed trips →
  **~219,433 tokens per confirmed outcome**.
- **44% of all tokens (671,168)** were spent in sessions whose user **never confirmed a trip** —
  a concrete "wasted spend" signal and the headline *cost-per-outcome* metric.

### ✅ SCEN-007 — full model used for trivial turns (STRONG; **L4/L5 autonomous**)
- **All 291 turns** ran on `gpt-4.1-mini` (single model — no task-based selection).
- **140/291 turns (48%)** were **trivial** (no delegation, <60 output tokens: greetings,
  acknowledgements, clarifications) yet used the full model.
- Cache-hit ratio is already high (**86%**: 1,291,520 cached / 1,500,920 input tokens), so the
  remaining lever is **model-selection policy** (route trivial turns to a cheaper model) — a
  lower-risk domain that can reach autonomous L4/L5.

### ✅ SCEN-004 — stale/superseded memories accumulate (STRONG; **L4/L5 autonomous**)
- **509 of 760 memories (67%)** are **superseded** (stale) — heavy churn from the
  preference-conflict conversations. `salience` is populated on 610 memories (mean 0.82,
  range 0.5–0.95), so **salience/retention policies are actionable**.
- `recall_memories` appeared in tool_calls on **52/291 turns (18%)** (post the recall fix) —
  recall is happening, but a 67% stale ratio is a clear **retention/pruning** opportunity.

### ✅ SCEN-005 — cost concentrated in a few agent_paths (STRONG)
| agent_path | turns | total tokens | avg/turn |
|---|---|---|---|
| `supervisor` | 262 | 978,316 | 3,734 |
| `supervisor,find_places,create_or_update_itinerary` | 11 | 339,457 | **30,859** |
| `supervisor,find_places` | 17 | 201,832 | 11,872 |
| `supervisor,find_places,find_places` | 1 | 16,427 | 16,427 |
- The itinerary path costs **~8×** a plain supervisor turn. Also a **`find_places,find_places`
  double-call** anomaly (redundant tool invocation) — a *tool-utilization* inefficiency (SCEN-008).

### ✅ SCEN-001 / SCEN-008 — supervisor rarely delegates on place intent (STRONG)
- In sessions with clear place/hotel/dining intent, **252/281 turns (90%)** had **no delegation**
  (`handoff_count=0`) — the supervisor answered/clarified instead of calling `find_places`.
  This is the fleet-wide version of the Amsterdam/Krasnapolsky gap (SCEN-001) and the
  answer-from-knowledge pattern (SCEN-008).

### ⚠️ SCEN-006 — context-bloat drift (WEAK in this data)
- Average tokens per turn index are **flat**, not creeping: turn0≈3,280, turn1≈5,297, turn3≈5,575,
  turn7≈3,832. Sessions are short (~10 turns), so no monotonic drift is visible here.
- **Verdict:** not supported by the current baseline. Keep as a *candidate* to re-test on longer
  sessions / longitudinal data; do **not** promote to a worked scenario yet.

## What gets promoted

Based on strength **and** maturity coverage (we want both an L3-prompt and L4/L5-policy worked
example), the priority promotions are:

1. **SCEN-007** (model-selection policy) — strong signal, **lower-risk → reaches autonomous L4/L5**;
   the canonical *self-adapting* example the vision's Level 5 calls for.
2. **SCEN-004** (memory retention/salience policy) — strong signal, also **L4/L5**.
3. SCEN-003 / SCEN-005 / SCEN-008 — strong, promote next.
4. **SCEN-006** — parked (data does not support it yet).

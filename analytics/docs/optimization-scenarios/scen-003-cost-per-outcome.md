# SCEN-003 — Cost per successful outcome (the north-star KPI)

- **Status:** Documented (data-validated on the `v2_analytics` baseline)
- **Category:** Cost intelligence / business outcomes
- **Vision questions it serves:** *"What is the cost per successful outcome?"*, *"Which workflows are most expensive?"*, *"Which agents deliver the highest ROI?"*
- **Optimization dimensions:** cost efficiency · business outcomes
- **Fix seam:** *composite* — this is the **metric** the other scenarios move, not a single fix
- **Maturity ceiling:** this is a **KPI**, not an optimization; it is the yardstick by which L2–L5 changes are judged
- **Related:** ADR-0001, Cost Intelligence (Pillar 3), Workflow Intelligence (Pillar 6), [baseline-findings](baseline-findings.md)

## Why this one is different

SCEN-003 is not a bug or a single prompt/policy fix — it is the **north-star business metric** that
the other scenarios roll up into. It answers the vision's core question directly: *what does it cost
to produce a successful outcome?* Every other scenario (avoidable clarifications, trivial-turn model
cost, stale-memory retrieval cost, expensive agent paths) is ultimately justified by whether it moves
**this** number.

## Evidence (baseline, tenant `v2_analytics`)

- Total spend **1,536,032 tokens** across **32 sessions** produced **7** confirmed/completed trips →
  **≈219,433 tokens per successful outcome**.
- **44% of all tokens (671,168)** were spent in sessions whose user **never confirmed a trip** —
  spend that produced no business outcome.

## Detection (from data we already capture)

Join per-session/user token spend (`Debug.total_tokens`) to the outcome anchor (`Trips.status`):

```sql
-- cost per successful outcome, and spend that produced no outcome
WITH spend AS (
  SELECT d.userId, d.sessionId, SUM(d.total_tokens) AS tokens
  FROM Debug d WHERE d.tenantId = 'v2_analytics'
  GROUP BY d.userId, d.sessionId
)
SELECT
  SUM(s.tokens)                                                        AS total_tokens,
  (SELECT COUNT(*) FROM Trips t
     WHERE t.status IN ('confirmed','completed'))                      AS outcomes,
  SUM(s.tokens) / NULLIF((SELECT COUNT(*) FROM Trips t
     WHERE t.status IN ('confirmed','completed')),0)                   AS tokens_per_outcome
FROM spend s;
```

Slice `tokens_per_outcome` by workflow (`agent_path`), by agent, by user segment, and over time —
that is Pillar 3 (Cost Intelligence) × Pillar 6 (Workflow Intelligence).

## Dashboard framing (KPI, not a card)

> **Cost per successful outcome: 219k tokens** · **44% of spend produced no booking.**
> Trend this monthly; attribute by workflow and agent; set a target. Each applied optimization
> (SCEN-001/004/005/007/008) is measured by its movement of this KPI.

## How it improves (composite)

There is no single "apply" button for SCEN-003. It improves when the **contributing** scenarios are
applied and validated:

| Contributing scenario | Lever on cost/outcome |
|---|---|
| SCEN-001 | fewer avoidable clarification turns before a result |
| SCEN-007 | cheaper model on the 48% trivial turns |
| SCEN-004 | less stale-memory retrieval cost |
| SCEN-005 | trim the most expensive agent paths (+ the double-`find_places`) |
| SCEN-008 | ground place queries in `find_places` instead of re-asking |

So SCEN-003 is the **loop's scoreboard**: it is what the platform (and, at L4/L5, the autonomous
tuner) optimizes *for*, and what proves an optimization actually paid off.

## Close the loop

After any applied optimization, recompute `tokens_per_outcome` and the no-outcome spend share.
A successful optimization moves both down without reducing confirmed outcomes.

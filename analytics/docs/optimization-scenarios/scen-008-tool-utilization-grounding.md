# SCEN-008 — Supervisor under-uses `find_places` (answers from knowledge; redundant calls)

- **Status:** Documented (data-validated on the `v2_analytics` baseline)
- **Category:** Tool utilization / routing effectiveness
- **Vision questions it serves:** *"Which routing decisions increase cost?"*, *"Which collaboration patterns produce the best outcomes?"*, *"Which patterns correlate with business success?"*
- **Optimization dimensions:** tool utilization · routing effectiveness · agent quality
- **Fix seam:** tool-selection policy + `supervisor.prompty` guidance → **mixed** (policy portion lower-risk)
- **Maturity ceiling:** **L3–L4** (prompt guidance = L3; a tool-need/threshold policy = L4)
- **Related:** ADR-0001, Agent Collaboration Analytics (Pillar 2), SCEN-001, [baseline-findings](baseline-findings.md)

## Symptom

Two related tool-utilization problems:

1. **Under-delegation:** the supervisor frequently answers place/hotel/dining questions **from its own
   model knowledge** instead of calling `find_places` — so results aren't grounded in the seeded
   `Places` data (vector/hybrid search), and quality is inconsistent.
2. **Redundant delegation:** occasionally it calls `find_places` **twice in one turn** for the same
   request — paying for a tool round-trip that adds nothing.

## Evidence (baseline, tenant `v2_analytics`)

- In sessions with clear place intent, **252/281 turns (90%)** had **no delegation**
  (`handoff_count = 0`) — the supervisor answered/clarified rather than searching.
- One turn shows `agent_path = supervisor,find_places,find_places` — a **double `find_places`**
  invocation (16,427 tokens) for a single request.

> Under-delegation overlaps SCEN-001 (the specific "city already known" case); SCEN-008 is the broader
> *"answer-from-knowledge instead of grounding in the tool"* + *redundant-call* pattern.

## Detection (from data we already capture)

`Debug.agent_path` / `handoff_count` + `Messages` intent:

```sql
-- (a) under-delegation on place intent
SELECT COUNT(*) AS place_turns,
       SUM(CASE WHEN handoff_count = 0 THEN 1 ELSE 0 END) AS no_delegation
FROM Debug d
JOIN Messages m ON m.sessionId = d.sessionId AND m.role='user'
WHERE d.tenantId='v2_analytics'
  AND m.content LIKE '%hotel%';   -- or restaurant/activity/attraction

-- (b) redundant tool calls: same tool repeated within one agent_path
--     detect agent_path containing 'find_places,find_places'
SELECT d.sessionId, d.agent_path, d.total_tokens
FROM Debug d
WHERE d.tenantId='v2_analytics'
  AND CONTAINS(d.agent_path, 'find_places,find_places');
```

## Candidate-optimization card (dashboard)

> **90% of place-intent turns don't call `find_places`; some turns call it twice.**
> Under-grounded answers + redundant tool cost.
> **Proposed fix:** (L3) `supervisor.prompty` rule — *always ground place/hotel/dining/activity
> requests in `find_places`; never answer from prior knowledge; call it at most once per request*;
> (L4) a lightweight **tool-need policy/threshold** that classifies whether a turn needs a search.
> **[Apply prompt]** · **[Apply policy]**

## The fix & maturity

- **Prompt guidance (L3, human-governed):** tighten `supervisor.prompty` to force grounding and forbid
  duplicate `find_places` calls per request.
- **Tool-selection policy (L4, lower-risk):** a bounded classifier/threshold deciding "does this turn
  need a place search?" is a policy knob that, once the seam exists, can be tuned autonomously behind
  a quality gate — the same L4/L5 pattern as SCEN-007.

## Guardrails

- Grounding must not *reduce* quality: gate on the e2e/answer-quality evaluator; a change that
  lowers helpfulness auto-reverts.
- De-duplication is safe/bounded (never issue an identical `find_places` call twice in one turn).

## Close the loop

After applying: expect the no-delegation rate on place intent to fall, zero `find_places,find_places`
turns, and answer-grounding (and ideally conversion) to improve — while cost per outcome (SCEN-003)
holds or drops.

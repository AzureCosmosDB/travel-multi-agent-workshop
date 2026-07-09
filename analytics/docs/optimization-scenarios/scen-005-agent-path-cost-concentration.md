# SCEN-005 — Cost concentrated in a few expensive `agent_path`s

- **Status:** Documented (data-validated on the `v2_analytics` baseline)
- **Category:** Cost efficiency / workflow efficiency
- **Vision questions it serves:** *"Which workflows should be optimized?"*, *"Which routing decisions increase cost?"*, *"What is the cost per successful outcome?"*
- **Optimization dimensions:** cost efficiency · workflow efficiency · routing effectiveness
- **Fix seam:** workflow/prompt shaping + routing policy → **mixed**
- **Maturity ceiling:** **L3–L4** (workflow/prompt reshaping = L3; a cost-aware routing threshold = L4)
- **Related:** SCEN-003 (the KPI this moves), SCEN-008 (double-call anomaly), [baseline-findings](baseline-findings.md)

## Symptom

Spend is not uniform across turns — it concentrates in a small number of **expensive agent paths**.
The itinerary path in particular costs **~8×** a plain supervisor turn, so a handful of turns dominate
the token bill. Optimizing the *cheap, common* path barely moves cost; optimizing the *rare, expensive*
path moves it a lot. This scenario is about **knowing where the money actually goes** so L2–L5
optimizations target the right workflow.

## Evidence (baseline, tenant `v2_analytics`)

| agent_path | turns | total tokens | avg/turn |
|---|---|---|---|
| `supervisor` | 262 | 978,316 | 3,734 |
| `supervisor,find_places,create_or_update_itinerary` | 11 | 339,457 | **30,859** |
| `supervisor,find_places` | 17 | 201,832 | 11,872 |
| `supervisor,find_places,find_places` | 1 | 16,427 | 16,427 |

- The **itinerary path (11 turns)** is only ~4% of turns but **22% of tokens** — the classic
  fat-tail cost distribution.
- The `supervisor,find_places,find_places` row is the redundant double-call anomaly (owned by SCEN-008).

## Detection (from data we already capture)

`Debug.agent_path` + `Debug.total_tokens` — a straight group-by:

```sql
SELECT d.agent_path,
       COUNT(*)            AS turns,
       SUM(d.total_tokens) AS total_tokens,
       AVG(d.total_tokens) AS avg_per_turn
FROM Debug d
WHERE d.tenantId = 'v2_analytics'
GROUP BY d.agent_path
ORDER BY total_tokens DESC;
```

The dashboard ranks paths by **total** tokens (where the money is) and by **avg/turn** (which paths
are individually expensive) — the two together tell you whether to attack *volume* or *unit cost*.

## Candidate-optimization card (dashboard)

> **The itinerary path costs ~8× a supervisor turn and consumes 22% of tokens from 4% of turns.**
> **Proposed fix:** (L3) reshape `create_or_update_itinerary` to a **single-call** generation with a
> tighter prompt/output contract (already partly done in the trip-identity fix); (L4) a **cost-aware
> routing threshold** that only enters the expensive path when the request genuinely needs a full
> itinerary. **[Apply workflow]** · **[Apply routing policy]**

## The fix & maturity

- **Workflow/prompt reshaping (L3, human-governed):** collapse multi-call itinerary generation,
  tighten the output contract, trim context carried into the expensive path.
- **Cost-aware routing (L4, lower-risk):** once the seam exists, a threshold/policy deciding
  "does this turn warrant the itinerary path?" is a bounded knob tunable behind a quality gate.

## Guardrails

- Gate any reshaping on the itinerary-quality evaluator — cheaper must not mean worse itineraries.
- Cost-aware routing must never *block* a legitimate itinerary request; it only avoids entering the
  expensive path for turns that don't need it, and auto-reverts if conversion drops.

## Close the loop

This scenario has no standalone KPI — it **feeds SCEN-003**. Success = the cost-per-outcome number
falls because the fat-tail path got cheaper or is entered less often, with trip quality held constant.

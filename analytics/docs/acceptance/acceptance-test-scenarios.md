# Acceptance-test scenarios — proving analytics value on generated data

**Date:** 2026-07-07  •  **Status:** For later execution (needs generated data + some instrumentation)
**Related:** `./data-generation-analysis.md` (§4 seams, §6 gaps), ADR-0002/0003, the six pillars in the vision doc.

## How to use this
Each scenario is a concrete, checkable acceptance test we run **once we have a real baseline** (post-upgrade). Each lists: **Pillar**, **Data prereq** (what the generator/enricher must contain), **Instrumentation prereq** (must be built), **Measure** (how), and **Pass criteria**. "Optimization" scenarios are **before/after** tests: measure → apply an app change (usually a `.prompty`/config edit) → regenerate a sample → re-measure → expect improvement with quality held.

Legend: ✅ ready today · ⚠️ needs a data addition · ⛔ blocked on instrumentation.

---

## Visibility scenarios (does the data *show* the value?)

### AT-P2-1 — Hand-off path visibility ✅
- **Pillar:** 2 (Collaboration/Routing). **Data:** any generated sessions. **Instrumentation:** done (`agent_path`, `handoff_count`, `transfer_success`).
- **Measure:** aggregate `Debug.agent_path` / `handoff_count` across turns.
- **Pass:** `agent_path` populated for ≥95% of turns; distribution spans hotel/activity/dining/itinerary; `handoff_count` matches the path; zero `Unknown`/`false`-everywhere.

### AT-P3-1 — Cost per turn / agent / model ✅
- **Pillar:** 3 (Cost). **Data:** any. **Instrumentation:** done (real tokens).
- **Measure:** sum/avg `input/output/total_tokens` grouped by `agent_selected`, `model_name`, user, session.
- **Pass:** non-zero tokens on ≥95% of turns; cost-per-workflow and cost-per-agent are computable and non-trivial.

### AT-P4-1 — Memory creation, conflict & supersession ✅
- **Pillar:** 4 (Memory). **Data:** conflict conversations (generator "Updating preferences" + enricher). **Instrumentation:** done.
- **Measure:** `Memories` count, `supersededBy` set on superseded records, `salience`/`ttl` present; conflict pairs (e.g. vegan→pescatarian).
- **Pass:** ≥1 superseded chain per conflicting user; salience & TTL populated; conflicts traceable old→new.

### AT-P4-2 — Memory write:read imbalance ("never-used memories") ✅
- **Pillar:** 4 + 3. **Data:** any. **Instrumentation:** done enough (tool-call counts); better with `MemoryEvent`.
- **Measure:** ratio of extraction/store calls to `recall_memories`; count memories never returned by any recall.
- **Pass:** the imbalance is quantifiable and surfaced (e.g. "N memories created, M never read"). *(Baseline observed ~27:1 write:read.)*

### AT-P6-1 — Workflow completion vs abandonment ⚠️
- **Pillar:** 6 (Workflow). **Data prereq:** add a minority of **abandoned/failed** conversations (see analysis §5.3) — today every conversation completes. **Instrumentation:** session-outcome labeling.
- **Measure:** completion rate = sessions reaching an itinerary/trip vs. those abandoned.
- **Pass:** completion rate is **< 100%** and abandoned vs completed is separable, with cost/outcome comparable across the two.

### AT-P1-1 — Per-agent latency ⛔
- **Pillar:** 1. **Instrumentation prereq:** wall-clock per-turn/agent timing (streaming hides `latency_checkpoint`).
- **Pass:** latency captured per turn/agent; a bottleneck agent is identifiable; latency trends over time.

### AT-P5-1 — Response quality scores ⛔
- **Pillar:** 5. **Instrumentation prereq:** persist `EvaluationResult` to Cosmos from the eval harness.
- **Pass:** relevance/groundedness/helpfulness scores per response; low-quality turns identifiable; quality comparable across agents.

---

## Optimization scenarios (before/after — the headline demos)

### AT-OPT-A — Gate memory extraction → cost drop  *(primary demo; app-applicable now)*
- **Pillars:** 3 + 4. **Data:** any (esp. simple, non-preference turns like "find a hotel"). **Instrumentation:** done.
- **Seam:** `extract_preferences → resolve_conflicts → store` runs on ~every message even when no preference is stated.
- **App change:** gate the extraction pipeline to preference-bearing turns (heuristic/classifier or prompt change) in `orchestrator.prompty` / `preference_extraction.prompty` / the memory path.
- **Measure:** avg tokens/turn, memory-pipeline call rate, memories created — before vs after, on the same scripted conversations.
- **Pass:** ≥ **30%** reduction in avg tokens/turn (and a large drop in redundant extraction/store calls) with **no regression** in recommendation quality (spot-check, and AT-P5 once available).

### AT-OPT-B — Prompt trimming → input-token drop  *(app-applicable now)*
- **Pillar:** 3. **Data:** any. **Instrumentation:** done.
- **Seam:** ~41:1 input:output; large system prompts re-sent every turn.
- **App change:** trim/condition system prompts in the `.prompty` files; summarize older context sooner.
- **Measure:** avg input tokens/turn before/after.
- **Pass:** measurable input-token reduction with unchanged output quality.

### AT-OPT-C — Memory recall effectiveness  *(flagship narrative; gated)*
- **Pillar:** 4. **Data prereq:** cross-conversation reuse (state a preference early, rely on recall later **without restating** — analysis §5.1). **Instrumentation prereq:** `MemoryEvent` on `recall_memories` (which memories, query, used?).
- **App change:** ensure specialists recall + apply relevant memories before recommending (specialist `.prompty`).
- **Measure:** for a turn whose recommendation should be constrained by an earlier preference: did a recall occur, did it return the right memory, did the recommendation honor it?
- **Pass:** "before" shows a stored preference **not** applied (recall missing/ignored); "after" shows the recall event + a recommendation that honors the preference.

### AT-OPT-D — Routing quality  *(optional; needs data)*
- **Pillar:** 2. **Data prereq:** a few **ambiguous** requests that tempt mis-routing (analysis §5.4).
- **App change:** sharpen routing rules in `orchestrator.prompty`.
- **Measure:** rate of mis-routes / extra hand-offs before vs after.
- **Pass:** fewer wasted hand-offs on the ambiguous set, equal outcomes. *(Skip if we keep P2 as visibility-only.)*

---

## Prerequisite matrix

| Scenario | Data addition needed | Instrumentation needed |
|---|---|---|
| AT-P2-1, AT-P3-1, AT-P4-1, AT-P4-2, AT-OPT-A, AT-OPT-B | none | none (done) |
| AT-P6-1 | abandoned/failed conversations | session-outcome labeling |
| AT-OPT-C, AT-P4-2 (rich) | cross-conversation reuse | `MemoryEvent` (retrieval) |
| AT-P1-1 | none | wall-clock latency |
| AT-P5-1 | none | `EvaluationResult` persistence |
| AT-OPT-D | ambiguous routing prompts | none |

## Execution note
Run these **after** the dependency upgrade and the generator/enricher additions, against a freshly generated `analytics_demo` baseline, so results reflect the final app. Lead with **AT-OPT-A/B** (real, immediately actionable cost wins) and **AT-P4-1/2** (memory), then layer P1/P5/P4-effectiveness as their instrumentation lands.

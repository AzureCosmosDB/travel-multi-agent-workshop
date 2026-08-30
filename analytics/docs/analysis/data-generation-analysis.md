# Analysis — Data generator & enricher as a foundation for demonstrating analytics value

**Date:** 2026-07-07  •  **Author:** Mark Brown (with agent)  •  **Status:** For review
**Inputs:** `analytics/data_generator.py`, `analytics/data_enricher.py`, the six pillars in the vision doc, and a **live sample** of freshly generated `analytics_demo` data (post-instrumentation-fixes).

## Purpose
Assess whether the generated data (a) best **demonstrates** the value of the six analytics pillars, and (b) creates natural **optimization seams** we can act on and apply back into the app (prompty files or config) as visible before/after wins. Honest about where the app is already fine or where a seam needs instrumentation we haven't built yet.

---

## 1. What the data currently is

**`data_generator.py`** — 12 personas, 32 conversations, ~292 user messages. Personas are diverse and realistic:
budget backpacker/vegan (Maya), luxury honeymoon (James), family (Sarah), business traveler (David),
adventure (Elena), slow-travel/cruise (Robert), spring-break group (Jordan), foodie/allergies (Priya),
digital nomad (Alex), art (Isabelle), wellness (Aisha), architecture (Marco). Most conversations are ~10 messages
and end by asking for an itinerary. Four personas include an explicit **"Updating preferences"** conversation that
contradicts an earlier preference (Maya vegan→pescatarian + peanut allergy; James luxury→boutique; Priya shellfish
allergy; Alex work-style change) → triggers **memory supersession**. A post-pass (`_update_trip_statuses`, seed=42)
marks some trips `confirmed`/`completed`.

**`data_enricher.py`** — adds preference-conflict conversations for **6 additional** users (sarah, david, elena,
jordan, alex, isabelle) to trigger more memory supersession.

**Design intent:** rich preferences + deliberate conflicts (great for **memory** analytics), broad destination/agent
coverage (good for **routing/cost**), and trip-status variety (a proxy for **workflow outcomes**).

---

## 2. Grounded findings from the live sample (real generated data)

Measured from the `Debug` container for `analytics_demo` (a partial run; numbers are directional):

| Signal | Observed | Read |
|---|---|---|
| **Token split** | avg **8,156 input : 196 output** per turn (**41:1**) | Heavily prompt-bound; output is tiny relative to context. |
| **Tool-call mix** | `extract_preferences` 293, `store_resolved_preferences` 235, `resolve_memory_conflicts` 233; **`discover_places` 14**; **`recall_memories` 11** | The **memory-write pipeline dominates**; the actual travel search (`discover_places`) and memory **reads** are rare. |
| **Memory write:read** | ~**27:1** (extractions vs recalls) | Memories are created constantly and read almost never. |
| **Hand-offs** | `agent_path` clean, mostly `orchestrator,<specialist>` (handoff_count=1); some `orchestrator` only | One hand-off per turn is the norm (agents interrupt to `human`). |
| **Summaries** | firing (auto ~every 10 msgs) | Summarizer works post-fix. |

> Caveat: `Debug.tool_calls` stores the **accumulated** tool calls visible in the turn's messages (LangGraph state accumulates), so absolute counts are inflated; the **ratios and dominance** are the reliable signal.

---

## 3. Pillar-by-pillar coverage

| Pillar | Demonstrable today? | Notes |
|---|---|---|
| **P1 — Performance/Latency** | ❌ **No** | No per-turn latency is captured (streaming drops `latency_checkpoint`). Needs wall-clock instrumentation. |
| **P2 — Collaboration/Routing** | ⚠️ **Partial** | `agent_path`/`handoff_count`/`transfer_success` are captured, but conversations rarely produce multi-hop or cyclic routing (each turn interrupts after one specialist), so "cyclic routing / bad hand-offs" is under-exercised. |
| **P3 — Cost Intelligence** | ✅ **Yes, strong** | Real tokens per turn/agent/model. The 41:1 ratio + memory-pipeline dominance are a compelling cost story. |
| **P4 — Memory Intelligence (flagship)** | ⚠️ **Creation yes, effectiveness no** | Creation, conflict, supersession, salience, TTL are all exercised. But **retrieval/reuse/effectiveness** events aren't logged as first-class `MemoryEvent`s, and the write:read imbalance suggests memory may be created-but-unused. |
| **P5 — Evaluation Intelligence** | ❌ **No** | No `EvaluationResult` is persisted to Cosmos (the eval harness exists in `01_exercises/evaluation` but doesn't write results). |
| **P6 — Workflow Intelligence** | ⚠️ **Partial** | Trip `confirmed/completed` gives an outcome proxy, but **every** conversation succeeds and ends in an itinerary — there are **no abandoned/failed workflows** to contrast against. |

---

## 4. Optimization seams (the valuable part)

Ranked by strength and by how cleanly they map to an app change we can show a before/after for.

### Seam A — Memory over-extraction & write/read imbalance  *(strongest; app-applicable now)*
**Evidence:** the memory pipeline (`extract_preferences_from_message` → `resolve_memory_conflicts` → `store_resolved_preferences`) runs on **essentially every user message**, even simple ones ("find a hotel"), while `recall_memories` fires ~27× less often. Memories are written far more than read.
**Pillars:** P3 (cost) + P4 (memory effectiveness — flagship).
**App change (visible before/after):** gate extraction so it runs only when the message actually asserts a preference (a cheap classifier/heuristic, or a prompt change in the orchestrator/memory path), and/or strengthen `recall_memories` usage in the specialist prompts so stored preferences actually influence recommendations. **Mechanism:** `prompts/orchestrator.prompty`, `prompts/preference_extraction.prompty`, and the specialist `.prompty` files.
**Demo:** "before" = 761 memory-pipeline calls, 41:1 tokens, memories rarely used; "after" = extraction only on preference turns → large token/cost drop with equal or better recommendations.

### Seam B — Prompt-bound cost (41:1 input:output)  *(strong; app-applicable now)*
**Evidence:** avg 8,156 input tokens/turn. Every specialist re-processes the full history + a large system prompt.
**Pillars:** P3.
**App change:** trim/condition system prompts (`.prompty`), rely on the summarizer to compress older context sooner, avoid re-sending redundant instructions. **Demo:** token-per-turn reduction with unchanged output quality (tie to P5 once evaluators persist).

### Seam C — Memory recall effectiveness  *(flagship P4; needs a scenario + light instrumentation)*
**Evidence:** low `recall_memories` usage; whether a stated preference (e.g., "I'm vegan") actually shapes a later dining recommendation is currently unmeasured.
**App change:** ensure specialists recall + apply relevant memories before recommending. **Demo:** a conversation where a preference stated in turn 2 should constrain a recommendation in turn 8; show the app missing it → fix the specialist prompt → show it honored. **Requires:** a `MemoryEvent` (retrieval) signal to measure it cleanly (ADR-0002 open item).

### Seam D — Routing quality  *(weaker today)*
**Evidence:** routing is mostly clean single hops; little cyclic/mis-routing to optimize.
**To make it a seam:** add deliberately **ambiguous** requests that tempt the orchestrator to mis-route (e.g., "somewhere nice for dinner with a view" → could go hotel vs dining), then improve `orchestrator.prompty` routing rules. Otherwise, leave P2 as a visibility story rather than an optimization one.

---

## 5. Recommendations for the generator/enricher redesign

To maximize demonstrable value **and** create honest before/after seams, evolve the data (not a rewrite — targeted additions):

1. **Cross-conversation memory reuse (P4 flagship).** Ensure a preference stated in an early conversation is *relevant* to a later one for the same user, so retrieval/effectiveness is exercised (e.g., Maya states "vegan" in Bangkok; her Tokyo dining requests should surface it). Add explicit "did it remember?" style follow-ups ("recommend dinner" without restating the diet).
2. **Keep and slightly expand the conflict/supersession set (P4).** This is already the strongest asset. Ensure conflicts span salience/TTL edge cases.
3. **Introduce a minority of imperfect workflows (P6).** A few conversations that **abandon** before an itinerary, or that **fail** to get a usable result, to contrast with successful ones — otherwise completion-rate analytics are trivially 100%.
4. **Add a few ambiguous routing prompts (P2)** *only if* we want P2 to be an optimization story (Seam D).
5. **Vary volume/persona mix knobs** so a small "demo" run and a larger "baseline" run are both possible cheaply.
6. **Do NOT over-engineer now:** the generator drives the real app, so its value is bounded by what the app instruments. Some seams (P1 latency, P5 evaluation, P4 retrieval events) are **gated on instrumentation** we haven't built — see §6.

---

## 6. Instrumentation gaps that gate certain pillars (mostly deferred/post-upgrade)

- **P1 latency** — capture wall-clock per-agent/turn timing (streaming hides server latency).
- **P4 retrieval** — emit a `MemoryEvent` on `recall_memories` (which memories, query, similarity, used-or-not) to measure reuse/effectiveness.
- **P5 evaluation** — persist evaluator outputs (`EvaluationResult`) to Cosmos from the eval harness.
- **`Debug.tool_calls`** — store only the turn's *new* tool calls (currently accumulates), so counts are exact.

These are consistent with ADR-0002's open items and are natural to fold into the **dependency-modernization** work (the graph/instrumentation is touched there anyway).

---

## 7. Honest caveats

- The single **clearest, real, app-applicable** seam today is **memory over-extraction + write/read imbalance (Seam A/B)** — it's grounded in live data (41:1 tokens; 27:1 write:read) and fixable via `.prompty`/pipeline changes with a dramatic cost before/after.
- The **flagship memory-effectiveness** demo (Seam C) is the most compelling narrative but needs a retrieval `MemoryEvent` signal to measure rigorously.
- P1/P5 optimization demos are **blocked on instrumentation** and should not be promised from the current data.
- The app is not egregiously unoptimized elsewhere; forcing artificial seams (beyond the real memory/cost one) risks looking contrived. Prefer the **real** cost/memory story.

## Recommended next step
Fold the **generator/enricher additions (§5.1–5.3)** and the **instrumentation gaps (§6)** into the post-upgrade analytics build, and lead the demo with **Seam A/B (memory-extraction cost)** since it is real and immediately actionable via prompty changes. Generate the full baseline **after** the upgrade + these additions, so the baseline reflects the final app and carries the seams we intend to showcase.

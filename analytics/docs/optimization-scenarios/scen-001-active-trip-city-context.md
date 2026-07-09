# SCEN-001 — Supervisor re-asks for a city it could infer from the active trip

- **Status:** Documented (behavior intentionally left unfixed as a lab exercise)
- **Discovered:** 2026-07-08, by naive frontend use (Tony Stark profile, Amsterdam trip)
- **Category:** Context-passing gap (agent asks for information the session already has)
- **Vision questions it serves:** *"What is the cost per successful outcome?"*, *"Which workflows should be optimized?"*, *"Which optimizations can be automated safely?"*
- **Related:** ADR-0001 (optimization-loop surface), ADR-0002 (Open Agent Analytics Schema), ADR-0007 (Debug capture)

## Symptom (what the user sees)

1. Select a destination city on the trip/explore page (e.g. **Amsterdam**); the hotel-results page loads Amsterdam hotels.
2. Open the chat and ask about a hotel.
3. The supervisor asks for preferences; the user answers with a **hotel name** ("Krasnapolsky").
4. The supervisor then asks **"which city is it in?"** — even though Amsterdam is the active trip city and is already displayed.

The agent asks for context the session already has. It also does **not** fall back to a name-based vector search on "Krasnapolsky" (a well-known Amsterdam hotel).

## Root cause (evidence)

Two independent facts combine:

1. **The chat never receives the selected city.** The frontend chat sends only the raw message text:
   `frontend/src/app/components/explore/explore.component.ts` → `streamChatMessage()` posts `body: JSON.stringify(userMessage)` to `/completion/stream`. The `selectedCity` state (localStorage + `travel-api.service.ts`) drives the **results page** but is never injected into the chat request or the agent config. So in the conversation the supervisor has no city unless the user typed one.
2. **The supervisor prompt only searches "in a city".** `python/src/app/prompts/supervisor.prompty` rule 4: *"When the user asks for hotels … in a city, call `find_places`."* There is **no rule to infer the city from the active trip**, and `find_places(city, aspects, constraints)` takes a **required** `city` (the `Places` container is partitioned by `geoScopeId`). With no city in context, the supervisor asks instead of delegating.

Confirmed in the live logs: the "Krasnapolsky" turn stored a Debug log with `agent_selected=supervisor`, `handoff_count=0`, `agent_path=supervisor` — i.e. **no delegation to `find_places`** — while the page's Amsterdam hotel results came from a separate direct filtered-places call (`SIMPLE FILTERED SEARCH … City: amsterdam … Found 10 places`).

> This is **not** a regression from the analytics work; it is pre-existing v2 design. It is preserved here on purpose as a canonical optimization scenario.

## Detection (how analytics flags it — no new instrumentation)

All required signal is already captured (ADR-0007 Debug re-wire + Messages + Trips):

- **Debug** (`propertyBag`): `agent_selected`, `agent_path`, `handoff_count`, `total_tokens`.
- **Messages**: user text (place/hotel intent) and the assistant reply (a clarifying question).
- **Trips**: the user's active trip `destination` (the city that *was* known).

**Metric — "avoidable clarification rate on place-intent turns":** the fraction of turns where the user message shows place/hotel/dining/activity intent **and** `handoff_count = 0` (no `find_places` delegation) **and** the assistant reply is a question, **while** the user has an active trip with a `destination`. A stronger variant detects the **round-trip**: such a turn immediately followed by a user turn that supplies a city, after which `find_places` finally fires — with the wasted tokens/latency of the extra turn attributed to the gap. This is a direct instance of *cost per successful outcome*: turns spent without moving toward a booking.

Sketch (over the mirrored Cosmos data / SQL endpoint):

```sql
-- avoidable clarification turns: place intent, no delegation, city was known
SELECT COUNT(*) AS avoidable_clarifications
FROM Debug d
JOIN Messages m   ON m.sessionId = d.sessionId AND m.role = 'user'
JOIN Trips  t     ON t.userId = d.userId AND t.status IN ('planning','confirmed')
WHERE d.handoff_count = 0
  AND d.agent_selected = 'supervisor'
  AND m.content LIKE '%hotel%'          -- place/hotel/dining/activity intent
  AND t.destination IS NOT NULL;        -- the city existed but wasn't used
```
(Exact shapes depend on the Power BI model; the point is every field is already present.)

## Candidate-optimization card (dashboard)

> **Supervisor asks for a city it could infer from the active trip.**
> *N* turns across *M* sessions · ~*X* wasted tokens · ~*Y*s added latency.
> **Proposed fix:** add a rule to `supervisor.prompty` to use the active trip's destination for `find_places` instead of asking. **[Apply]**

## The fix (hot-swappable, one-click-safe)

Prompts are **data** (`.prompty` files) loaded at runtime via `load_prompt(...)`, so the fix needs no code change or redeploy. Add a rule to `supervisor.prompty`, e.g.:

> *If the active trip or the conversation already establishes a destination city, use that city for `find_places` — do not ask the user to repeat it. Only ask for a city when none is known from the trip or the conversation.*

(A complementary option, out of scope for the minimal fix: let `find_places` do a name-based vector lookup across cities when no city is given, so a bare hotel name resolves directly.)

Because the change is a prompt, the ADR-0001 apply-loop can write the revised `.prompty` (from a Cosmos-stored override or a file write) when the user clicks **Apply** — a safe-to-automate class of optimization.

## Close the loop (before/after)

Re-run the generator (or let live traffic accumulate) after applying, then recompute the metric. Expected: the avoidable-clarification rate drops toward zero; fewer turns-to-first-result; lower tokens/latency per booking. That before/after is the demo payoff.

## Lab exercise framing

- **Exercise A (data-first):** query the baseline, compute the avoidable-clarification metric, identify the pattern.
- **Exercise B (reproduce-in-UI):** reproduce the exact Amsterdam/Krasnapolsky round-trip in the frontend.
- **Exercise C (apply):** accept the dashboard recommendation, apply the prompt patch, and verify the metric improves.

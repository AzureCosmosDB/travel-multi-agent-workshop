# Module 08 - Agent Optimization (Apply & Autonomy)

**[< Agent Analytics](./Module-07.md#module-07---agent-analytics-visibility-insight)** - **[Fabric Analytics & Reverse-ETL >](./Module-09.md#module-09---fabric-analytics-reverse-etl)**

## Introduction

In Module 07 you made your agent's behavior **visible**: you instrumented every turn, explored a signal in the web analytics portal, detected the model-selection opportunity. That's the first half of the loop:

> **instrument → detect → recommend →** *apply → verify*

This module closes it. You'll **apply** the recommended optimization with one click, **verify** it from data, then climb the maturity ladder: contrast a **lower-risk autonomous** change (model selection) with a **higher-risk human-governed** one (a prompt fix), and finally wire an **automated quality gate** so the system can safely optimize *itself*.

> Still additive — you'll implement one decision function and a few small hooks. **No changes to Modules 01–05.** The model tiers (`gpt-5-nano`, `gpt-5.1`) and containers are already provisioned by `azd up`.

## Learning Objectives and Activities

- Understand why **policies** are the safe surface for automated optimization, and how apply/revert stay reversible
- Understand and test the reusable decision that classifies each turn (trivial / routine / complex)
- **Apply** two reversible policies (L4/L5) — model selection and memory retention — and **verify** their effect from data
- Contrast it with a **human-governed L3** optimization (a prompt fix) — the risk model in practice

## Module Exercises

1. [Activity 1: The Apply-Loop and the Safe Surface](#activity-1-the-apply-loop-and-the-safe-surface)
2. [Activity 2: Understand the Decision (`classify_complexity_tier`)](#activity-2-understand-the-decision-classify_complexity_tier)
3. [Activity 3: Wire the Two Integration Seams](#activity-3-wire-the-two-integration-seams)
4. [Activity 4: Apply the Autonomous Optimizations](#activity-4-apply-the-autonomous-optimizations)
5. [Activity 5: A Different Risk Level — Insights and the Governed Path](#activity-5-a-different-risk-level--insights-and-the-governed-path)

---

## Activity 1: The Apply-Loop and the Safe Surface

Applying an optimization means **changing how the running system behaves**. The critical question is: *how do we do that safely — and how autonomously?*

The answer is the **risk model** from Module 07:

- **Policies are the safe surface.** Model selection, memory retention, routing thresholds, tool selection — these are bounded knobs. Changing one is a small, **reversible**, audited data change, not a code edit. Because it's reversible and bounded, it can be applied **autonomously** (L4/L5) behind a quality gate.
- **Prompts, workflows, and code are human-governed.** They change behavior in hard-to-bound ways, so they go through review/PR and cap at **assisted** (L3).

The provided `optimization.py` implements policies as documents in the `OptimizationPolicies` container:

- status flows `proposed → active → reverted`;
- only an **active + enabled** policy changes behavior — so the default is always safe;
- **apply** and **revert** are one call each, versioned, with an audit trail.

You'll use this machinery for two reversible policies now — model selection and memory retention — and see the *contrast* with a human-governed prompt change in Activity 5.

---

## Activity 2: Understand the Decision (`classify_complexity_tier`)

The reusable optimization logic lives in `01_exercises/python/src/app/services/optimization.py`, not in the application graph. This separation is intentional: you can copy or package the optimization service for another LangGraph application without copying this workshop's agents, prompts, or API.

Open `optimization.py` and find these three functions:

- `classify_complexity_tier(text, classifier)` — the conservative trivial / routine / complex decision;
- `select_deployment_for_turn(messages)` — reads the active policy and maps the tier to a deployment;
- `get_chat_model_for_turn(messages)` — returns the selected model for a LangGraph model hook.

Read `classify_complexity_tier`. Complex planning patterns are checked first. A trivial turn must be both short and greeting-like, so `"hotels in Amsterdam"` remains `routine`. When in doubt, the classifier preserves quality by choosing `routine`.

The service accepts normal LangChain messages **or** dictionaries with `role` and `content`. That small contract is the portability seam: your application only needs to supply its current message list.

### Self-check

Verify your classifier before wiring it in. Open a terminal, activate the venv, and change into the `python` folder (so the `src.app...` import resolves):

```powershell
# from the 01_exercises folder
.\.venv-travel\Scripts\Activate.ps1
cd python
```

Run this one command. It prints the tier your classifier assigns to a spread of example inputs, so you can **see the decision boundary** — greetings → `trivial`, a single fact/search → `routine`, planning → `complex`.

```powershell
python -c "import logging; logging.disable(logging.WARNING); from src.app.services.optimization import classify_complexity_tier as c; cases=[('hi','trivial'),('thanks!','trivial'),('hotels in Amsterdam','routine'),('What is the Krasnapolsky?','routine'),('please build me an itinerary for 3 days in Paris','complex'),('plan my trip to Tokyo','complex')]; [print(f'{t[:48]:<48} -> {c(t):<8} (expected {e})') for t,e in cases]; ok=sum(c(t)==e for t,e in cases); print(); print(f'{ok}/{len(cases)} tiers classified as expected')"
```

Expected output:

```
hi                                               -> trivial  (expected trivial)
thanks!                                          -> trivial  (expected trivial)
hotels in Amsterdam                              -> routine  (expected routine)
What is the Krasnapolsky?                        -> routine  (expected routine)
please build me an itinerary for 3 days in Paris -> complex  (expected complex)
plan my trip to Tokyo                            -> complex  (expected complex)

6/6 tiers classified as expected
```

Read the middle column — that's *your* classifier's decision for each input. Any row where it differs from `(expected …)` is a misroute.

---

## Activity 3: Wire the Two Integration Seams

The optimization service is framework-independent. This workshop connects it through two deliberately small adapters:

1. a **LangGraph model hook** that chooses the supervisor model;
2. a **Cosmos telemetry hook** that records the chosen tier with the token usage your completion path already captures.

This allows it to be pluggable with minimal disruption to other multi-agent applications built on Langraph that use Cosmos Agent Memory Tooklkit.

#### Step 1 — add the LangGraph model hook

Open `01_exercises/python/src/app/travel_agents.py`. Near the Azure OpenAI import, add:

```python
from src.app.services import optimization
```

Then scroll into `def setup_agents` and search for `supervisor_model = (`. 

```python
    # Reasoning (gpt-5 / o-series) deployments don't reliably accept
    # parallel_tool_calls, so only request it for standard chat models.
    supervisor_model = (
        model
        if _is_reasoning_deployment(AZURE_OPENAI_DEPLOYMENT)
        else _bind_parallel_tool_calls(model)
    )
    supervisor_agent = _create_agent(
        supervisor_model,
        tools=supervisor_tools,
        prompt_text=SUPERVISOR_BASE_PROMPT,
        checkpointer=supervisor_checkpointer,
    )
```

Comment out that entire block of code and paste this code below. The result should look like this:

```python
    # Reasoning (gpt-5 / o-series) deployments don't reliably accept
    # parallel_tool_calls, so only request it for standard chat models.
    # supervisor_model = (
    #     model
    #     if _is_reasoning_deployment(AZURE_OPENAI_DEPLOYMENT)
    #     else _bind_parallel_tool_calls(model)
    # )
    # supervisor_agent = _create_agent(
    #     supervisor_model,
    #     tools=supervisor_tools,
    #     prompt_text=SUPERVISOR_BASE_PROMPT,
    #     checkpointer=supervisor_checkpointer,
    # )

    def _select_supervisor_model(state, runtime):
        # LangGraph doesn't auto-bind tools for a dynamic (callable) model —
        # bind them here or the supervisor can never call its tools.
        return optimization.get_chat_model_for_turn(state.get("messages")).bind_tools(supervisor_tools)

    supervisor_agent = _create_agent(
        _select_supervisor_model,
        tools=supervisor_tools,
        prompt_text=SUPERVISOR_BASE_PROMPT,
        checkpointer=supervisor_checkpointer,
    )
```

That is the entire application-routing change. `create_react_agent` accepts a `(state, runtime) -> model` callable and invokes it per turn. With no active policy, the optimization service returns the existing default model.

> **Adapting this to another LangGraph app:** use the same callable wherever your graph or agent factory accepts a dynamic model. If your framework wrapper only accepts a fixed model, call `optimization.select_deployment_for_turn(messages)` at your request boundary and construct or retrieve the corresponding model there.

#### Step 2 — add the Cosmos telemetry hook

The Cosmos memory toolkit and `OptimizationTurns` need the selected tier alongside token usage. The reusable helper `optimization.record_optimization_turn_for_message(...)` accepts only framework-neutral values: identity, user text, usage, model name, and handoff count.

In this workshop, the existing Module 07 telemetry seam is `store_debug_log_from_response` in `01_exercises/python/src/app/travel_agents_api.py`. Open that file now.

Then **(a)** **Search for `def store_debug_log_from_response`** and add a `user_message_text` parameter to its signature with a str type and empty string default. The new function should look like this:

```python
def store_debug_log_from_response(sessionId: str, tenantId: str, userId: str, response_data: List[Dict], debug_log_id: Optional[str] = None, user_message_text: str = "") -> str:
```

Inside that function, comment out the existing Module 07 `record_optimization_turn(...)` call, then paste this new code below it. It should look like this:

```python
        # Module 07 — record this turn for optimization analytics.
        # Every turn runs on the default model for now, so record complexity tier "default".
        # optimization.record_optimization_turn(
        #     tenant_id=tenantId, user_id=userId, session_id=sessionId,
        #     complexity_tier="default", deployment=AZURE_OPENAI_DEPLOYMENT,
        #     usage={"input_tokens": input_tokens, "output_tokens": output_tokens,
        #            "total_tokens": total_tokens, "cached_tokens": cached_tokens},
        #     model_name=model_name,
        # )

        optimization.record_optimization_turn_for_message(
            tenant_id=tenantId, user_id=userId, session_id=sessionId,
            user_message=user_message_text,
            usage={"input_tokens": input_tokens, "output_tokens": output_tokens,
                   "total_tokens": total_tokens, "cached_tokens": cached_tokens},
            model_name=model_name,
            handoff_count=handoff_count,
        )
```

Finally, locate the function `_post_response_background`. In the `asyncio.to_thread()` call we are going to add a new argument, `user_message_text` to that function call.

Comment out the original call and add this new version below so it looks like this:

```python
        # await asyncio.to_thread(
        #     store_debug_log_from_response,
        #     sessionId,
        #     tenantId,
        #     userId,
        #     response_data,
        #     debug_log_id=debug_log_id,
        # )
        
        await asyncio.to_thread(
            store_debug_log_from_response,
            sessionId,
            tenantId,
            userId,
            response_data,
            debug_log_id=debug_log_id,
            user_message_text=user_message_text,
        )
```

> **Adapting this to another Cosmos memory toolkit app:** call the same helper after the turn completes, from whichever middleware, callback, event stream, or background worker already has the user text and model usage. The optimization layer does not depend on this workshop's FastAPI endpoint or debug-log function.

## Activity 4: Apply the Autonomous Optimizations

The web analytics portal surfaces two **reversible policies** in the marvel dataset — **model selection** and **memory retention**. Both are the *safe surface* from Activity 1: bounded, audited, one-click-reversible data changes, so both are **autonomous-capable (L4/L5)**. You'll apply each one here and leave them on.

### Apply model selection

You already have the **web analytics portal** open from [Module 07, Activity 3](./Module-07.md#module-07---agent-analytics-visibility-insight) (<http://localhost:8060>). Keep **Dataset → marvel** and **Source → Live (recompute)** so the portal reads the current raw turns, then on the **model-selection** card click **Apply**. The card's status flips to `active` and the supervisor immediately starts choosing a model per turn — no restart needed.

> **One click, fully reversible.** Apply/Revert are single, audited state changes on the `OptimizationPolicies` container — which is exactly why they're safe to make from a button. The same card carries a **Revert** button to undo it. Remember the policy is **app-wide (global)**: it takes effect across every dataset at once. *(These buttons call `POST /optimizations/model-selection/apply` and `/revert` under the hood — that's the seam to automate later — but for this workshop, use the portal.)*

### Generate new traffic from the web app

Now generate traffic **from the travel web app** so the live supervisor classifies and routes each turn:

1. Open the travel web app at **<http://localhost:4200>** in your browser. (If it isn't running, start it in a terminal with `cd frontend; npm start`.)
2. On the **Cosmos Voyager** login screen, choose a profile under **Select Your Profile** (for example **tony**) and click **Login**. (The app uses the **marvel** tenant by default.)
3. Click the **Chat with Assistant** button (bottom-right of the Explore page) to open the chat panel — this starts a new session.
4. Type each of these three messages into the **"Ask for recommendations…"** box and press **Send** (or hit Enter) **one at a time**, waiting for the assistant's reply before sending the next:
   - `hi` → complexity tier `trivial` → `gpt-5-nano`
   - `hotels in amsterdam` → complexity tier `routine` → `gpt-5-mini`
   - `please build me an itinerary for 3 days in amsterdam` → complexity tier `complex` → `gpt-5.1`
5. Switch back to the **web analytics portal** (<http://localhost:8060>), confirm **Source → Live (recompute)**, and refresh. The model-selection card and **Model Selection** tab now show the per-turn breakdown with `gpt-5-nano` and `gpt-5-mini` usage alongside `gpt-5.1`. *(You can also confirm in the API logs or by querying the `OptimizationTurns` container directly.)*

### Read the results in the portal

On the **Model Selection** tab, the **Cost by tier** view now shows one row per complexity tier — deployment, turns, tokens, and estimated cost — and the **Cost / outcome** KPI tile updates up top. This is the same `OptimizationTurns` data the app just wrote; each turn records the complexity tier and the *actual* serving model — for example:

```
tier      deployment    model_name              total_tokens
trivial   gpt-5-nano    gpt-5-nano-2025-08-07          3,828
routine   gpt-5-mini    gpt-5-mini-2025-08-07         15,946
complex   gpt-5.1       gpt-5.1-2025-11-13            32,616
```

The `model_name` (reported by the model itself) is your independent proof that the policy actually changed which model ran — not just what you intended.

Two honest lessons as you read the numbers:

1. **The reasoning-token caveat.** `gpt-5-nano` is a *reasoning* model — it can spend a few hundred hidden "reasoning" output tokens even on "hi". A naive "cheaper model saves money" projection ignores that. In practice nano's very low **input** price still makes the trivial turn cheaper — but you only *know* from the measured result. **Always verify; never ship an estimate as a result.**
2. **Cost per outcome.** The `complex` tier (`gpt-5.1`) is *more* expensive per turn. Whether it's worth it depends on whether better itineraries raise **conversion** — lowering cost per *confirmed trip*, not per turn. Judge the optimization on the outcome metric, not the token bill — which is exactly what the **Cost / outcome** tile tracks.

### Apply memory retention

The second autonomous policy is on a *different dimension* — memory hygiene, not model cost. As users chat, the memory subsystem extracts preferences and **supersedes** older ones when they change (you built this in the memory modules). Over time the superseded entries pile up, and each recall would feed the agent stale preferences it then pays **context tokens** to read. The **memory-retention** card reads that signal: `total_memories`, how many are `superseded`, and the stale share (`superseded_pct`).

Applying it **soft-prunes** those superseded memories — it stamps `retention_status = "pruned"` on each Cosmos memory doc. At runtime the **`recall_memories` MCP tool drops any `pruned` hit before it returns results to the agent** (`mcp_server/mcp_http_server.py`), so stale preferences never reach the agent's context — cleaner, higher-signal recall, and fewer context tokens per turn.

**First, make the saving measurable — call the optimization hook from `recall_memories`.** Dropping the pruned hits is invisible unless we *measure* it (the same "measure it, don't estimate it" rule you applied to model selection). Instead of growing the MCP tool, the provided **`optimization`** service exposes a thin **`prune_and_measure_recall`** hook — the same *"hook into `optimization.py`"* pattern you used for capability-tiered model selection in `travel_agents.py`. It does the prune **and** records the input tokens each drop avoids. It's already in `python/src/app/services/optimization.py` (shown here so you understand it — and can lift it into your own app):

```python
# provided in python/src/app/services/optimization.py — you don't paste this, you call it
def prune_and_measure_recall(records, user_id, thread_id=None, query="", top_k=10):
    """Recall hook: drop pruned memories and record the input tokens each drop avoids."""
    kept, excluded, avoided = [], 0, 0
    for d in records:
        if d.get("retention_status") == "pruned":
            excluded += 1
            avoided += _count_tokens(str(d.get("content") or ""))   # tiktoken cl100k_base
        else:
            kept.append(d)
    if excluded:  # one best-effort ApiEvent under the global _global_memory partition
        cosmos.record_api_event(
            session_id=thread_id or "unknown", tenant_id="_global_memory",
            provider="memory", operation="recall_pruned_avoided",
            request={"user_id": user_id, "thread_id": thread_id, "query": query, "top_k": top_k},
            response={"returned": len(kept), "excluded_pruned": excluded,
                      "avoided_input_tokens": avoided},
            keywords=["memory-retention", "avoided-tokens"])
    return kept
```

Your only change is to **call it from the recall tool** — one import plus a two-line swap.

**1 — import the hook.** Open **`mcp_server/mcp_http_server.py`** and add this next to the other `from src.app...` imports near the top:

```python
from src.app.services.optimization import prune_and_measure_recall
```

**2 — hand recall's hits to the hook.** Scroll to `recall_memories` and **comment out** its final `return` block:

```python
    # hits = await _maybe_await(client.search_cosmos(**kwargs))
    # # Exclude memories soft-pruned by the memory-retention policy (best-effort:
    # # applies where the memory client surfaces the retention_status field).
    # return [
    #     d for hit in hits
    #     if (d := _memory_to_dict(hit)).get("retention_status") != "pruned"
    # ]
```

…then paste this in its place — the **same prune**, now measured:

```python
    hits = await _maybe_await(client.search_cosmos(**kwargs))
    # Hand the recall hits to the optimization service's hook: it drops pruned memories
    # AND records the input tokens each drop avoids (the memory-retention measurement).
    records = [_memory_to_dict(hit) for hit in hits]
    return prune_and_measure_recall(records, user_id, thread_id, query, top_k)
```

**Restart the MCP server** (Terminal 1) so the change loads — unlike the API, `mcp_http_server.py` doesn't auto-reload. *(The provided `optimization` service already aggregates these events into the memory-retention card's saving — nothing else to change.)*

Now apply the policy and watch it pay off:

1. On the **memory-retention** card, click **Apply**.
2. The status flips to `active` and the card reports how many memories were pruned (for example *"pruned 15 superseded memories"*).
3. **See the saving accrue — re-run the model-selection prompts.** Back in the travel app (still logged in as **tony**), send the **same three messages** from the model-selection demo again, one at a time (`hi` → `hotels in amsterdam` → `please build me an itinerary for 3 days in amsterdam`). The `hotels in amsterdam` and itinerary turns recall Tony's travel preferences — and his now-`pruned` superseded 5-star-hotel/luxury entries are dropped, so `recall_memories` records the avoided input tokens. Refresh the **web analytics portal** with **Source → Live (recompute)**: the **memory-retention** card now shows a **measured saving** — the same three prompts prove **both** optimizations at once (model tiering *and* leaner recall). *(It reads $0 until you do this post-apply run — it's measured from real recalls, never a pre-apply estimate.)*

> **Where the filter runs — be precise.** The prune is only a *mark* on the memory doc; in this exercise the exclusion happens in the **`recall_memories` MCP tool**, which filters `pruned` hits *after* the Cosmos memory toolkit's vector search returns them. Filtering *here* (rather than in the query) is deliberate: the `prune_and_measure_recall` hook can only **measure** the avoided tokens for hits it actually sees, so the post-filter is what keeps the saving observable — at the **agent's context** (stale memories aren't injected into the prompt → fewer tokens per turn), *not* at the vector-search layer, which still scans the pruned docs.

> **Going further — push the filter into the query (what the reference solution does).** The Cosmos memory toolkit already lets you exclude memories *inside* the vector search via `search_cosmos(exclude_tags=[...])` (which emits `NOT ARRAY_CONTAINS(c.tags, @tag)`), so **no toolkit change is needed**. The reference solution (`02_completed`) takes this route: it soft-prunes by adding a reversible **`sys:retention-pruned`** tag to the memory's `tags` (a partial PATCH that never rewrites the embedding) and passes `exclude_tags=["sys:retention-pruned"]` at recall — so pruned memories are dropped **in the query**, cutting **retrieval** cost too, not just context tokens. This is the approach suggested on [AzureCosmosDB/AgentMemoryToolkit#36](https://github.com/AzureCosmosDB/AgentMemoryToolkit/issues/36). The trade-off is the mirror image of the note above: because the toolkit removes the pruned rows *before* they ever reach the recall hook, the in-app avoided-token *measurement* no longer fires — which is exactly why this exercise keeps the post-filter, so you can see the saving end-to-end.

> **Measured in Fabric from mirrored telemetry.** The avoided-token telemetry lives in `ApiEvents`, a **high-volume** container — so it's **mirrored to Fabric** and the memory-retention saving is aggregated at scale in the reverse-ETL **notebook** (Section 4b, the `memory-retention` `optimization_result` row, `method = "telemetry"`, [Module 09](./Module-09.md)), right alongside the memory **health** it computes from the mirrored `memories` table. The maintainer app-plane script `analytics/fabric/compute_insights.py` emits the **identical** row (idempotent by id) as its reference twin, so notebook == portal == optional report either way.

It's the **same class** as model selection: the prune is a **reversible mark**, not a delete — the embedding vector is never rewritten, and **Revert** un-marks every pruned memory (restoring it on the next recall). A bounded, audited, one-click-reversible data change → **autonomous-capable (L4/L5)**.

> **Global signal, not tenant-scoped.** Memory is keyed by *user*, not tenant, so this card reads the same across datasets — applying it is a global memory-hygiene action.

### Reversible at any time — but leave them on

You *don't* need to revert either policy here. **Leave both capability-tiered model selection and memory retention active for the rest of the workshop** — they're the optimizations you just applied and measured, and there's no reason to switch a working optimization back off. Reverting now would only undo it with nothing left to measure afterward.

What matters is knowing the **escape hatch exists**: each card carries a **Revert** button — one click restores `complexity_tier=default, deployment=gpt-5.1` (model selection) or un-prunes every marked memory (retention) on the very next turn/recall. **That reversibility — a single, audited state change on the `OptimizationPolicies` container — is exactly what makes these policies safe to automate.** In [Module 09](./Module-09.md), the notebook writes the reverse-ETL snapshot that the portal's **Reverse-ETL (notebook)** source reads; Power BI remains an optional report, but the portal is the recommended place to apply and revert policies in this workshop.

You've now completed the loop for two **lower-risk, autonomous-capable** optimizations (maturity L3 today — you approved them). Reaching **L4/L5** means letting an automated quality gate approve or auto-revert them *without* a human — the autonomous step we build toward once the analytical substrate is in place ([Module 09](./Module-09.md)) and close on in **Module 10**.

---

## Activity 5: A Different Risk Level — Insights and the Governed Path

Activity 4 applied two **reversible policies**. Not every finding is a policy knob, though. Some are read-only **insights** and **diagnostic lenses** — the portal *detects* and *shows* them, but you act on them through a **human-governed** path (review, PR), never a one-click toggle. Let's start with the lens that tells you *where your tokens actually go*.

### Read the agent-path cost concentration lens

1. Keep the **Dataset** dropdown on **marvel** and **Source → Live (recompute)** (no switch needed) and click **Refresh**.
2. Open the **Agents** tab and find the **Agent-path cost concentration** table (dimension *cost efficiency · routing*, badged **insight**).

Each row is one distinct **`agent_path`** — the ordered chain of nodes and tools a turn ran through (e.g. `supervisor → find_places → create_or_update_itinerary`), read straight from `Debug` telemetry — drawn as a **pill chain** with a **bar sized by the total tokens** that shape consumed. Read two signals:

- The **longest bars** are where total spend concentrates — often the frequent, individually-cheap `supervisor` turns.
- A high **/turn** figure flags the *per-turn* expensive shapes — typically the full itinerary path, many times the cost of a plain supervisor turn.

Notice what this card is *not*: it has **no Apply button**. It doesn't change anything — it *tells you which paths to target* with the actions you already have: **tier** the expensive paths via model selection (Activity 4), and **trim redundant tool calls** on them. A lens points; the policies act.

> **You'll also see a *Cost per outcome & conversion funnel* card** — another read-only lens, on the business-impact dimension (where sessions leak between engaged → searched → planned → confirmed). Same idea: it names *where* value is lost; acting on it is a product decision, not a toggle.

### The governed path

Some findings point past a policy knob to a **prompt or code** change — the higher-risk, **human-governed** class. The canonical example is a **redundant tool-call** pattern: the same agent/tool invoked back-to-back within one turn, visible in `agent_path`. Here's the first principle behind how the platform handles it:

- **Detecting** the pattern is *operational* — a live rollup of Debug telemetry, which the platform already does.
- **Proposing** a specific prompt edit, and **measuring** whether it actually helps, is *analytical* work — reading the flagged turns *and* the agent's prompt, drafting a candidate revision, and scoring it against held-out turns **before** anything is proposed.

That analytical half is **not built in this workshop** — the point here is the *governance rule*, not an implementation. A prompt or code fix is never hand-authored in the app and never auto-applied: whatever produces it must surface a *measured* before/after `{file, diff}` that a human reviews and merges via **PR**. That's **maturity L3 — assisted** by design, and the harder frontier we return to in **[Module 10](./Module-10.md)**.

This is the **risk model in practice**:

| | Autonomous policy (Activity 4) | Governed prompt/code fix |
|---|---|---|
| Surface | policy (data) | prompt (code) |
| How it applies | one-click, reversible toggle | staged diff → human review / PR |
| In this module | applied live (model selection, memory retention) | explained as a concept — not built here |
| Max autonomy | L4/L5 | L3 (assisted) |

The same analytics loop surfaces both — but the **apply** step respects each one's risk. A reversible policy is safe to toggle from a button; a prompt or code change is only ever *proposed* by grounded analysis, then human-governed.

---

## Test Your Work

- [ ] `classify_complexity_tier` passes the Activity 2 self-check.
- [ ] With the model-selection policy **applied**, `hi` / `hotels in amsterdam` / an itinerary request route to `gpt-5-nano` / `gpt-5-mini` / `gpt-5.1` (visible in `OptimizationTurns`).
- [ ] The portal's **Model Selection** tab shows the per-complexity-tier cost breakdown; you can explain the reasoning-token caveat and cost-per-outcome.
- [ ] You **applied memory retention** and can explain it soft-prunes superseded memories (a reversible mark) for cheaper, higher-signal recall.
- [ ] You **instrumented `recall_memories`** to record the input tokens each prune avoids, and after re-running the three prompts you saw a **measured** memory-retention saving in the portal (not an estimate — $0 until applied and recalled).
- [ ] You can point to the **Revert** button on either policy and explain what one click restores — but you **leave both active** for the rest of the workshop (nothing is measured after a revert).
- [ ] You can read the **agent-path cost concentration** lens (where tokens concentrate vs. per-turn cost) and name the action it points to (tiering, trimming redundant calls).
- [ ] You can contrast an **autonomous policy** (one-click, reversible) vs a **governed prompt/code fix** (*proposed* and measured offline, then human-reviewed via PR) and say why each maxes out at a different maturity level.

## Troubleshooting

- **Supervisor answers but never calls tools** (e.g. it *describes* looking up places, or says it "can't access place-finding tools", instead of returning real results). LangGraph only auto-binds `tools` for a *static* model; a dynamic `(state, runtime) -> model` callable must bind them itself. Make sure `_select_supervisor_model` ends with `.bind_tools(supervisor_tools)`.
- **Turns still all run `gpt-5.1` after apply.** Check that (1) the policy is `active` (`GET /optimizations/model-selection/policy`), (2) in `setup_agents` you replaced the fixed `supervisor_model` with the `_select_supervisor_model` selector (so `_create_agent` receives the *callable*, not a fixed model), and (3) `optimization.select_deployment_for_turn` reads `complexity_tiers` from the policy's `params`. The policy cache also has a ~15s TTL — wait a few seconds after apply.
- **`gpt-5-nano`/`gpt-5.1` calls error.** These are reasoning models — the provided `optimization.get_chat_model` omits `temperature` and uses a newer API version for them. If you built the model yourself, don't pass `temperature`. Confirm both deployments exist (`az cognitiveservices account deployment list ...`); if quota blocked one, point the policy's tier at an available model.
- **`classify_complexity_tier` misroutes.** Run the Activity 2 self-check. A common bug is checking trivial *before* complex, or not requiring *both* short length and a greeting pattern for trivial.
- **Revert didn't take effect.** Same ~15s cache TTL; the *next* turn after it expires uses the default.

## What You Learned

You closed the optimization loop: you **built** the decision, **applied** two reversible policies — model selection and memory retention — with one click each, and **verified** the results honestly (measuring, not guessing). You saw why *policies* — not prompts or code — are the safe surface for automation, and contrasted an autonomous change with a human-governed one. What still keeps today's applies at **L3 (assisted)** is that *you* judged them; reaching **L4/L5 (autonomous, self-correcting)** means an automated **quality gate** approves or auto-reverts each change without a human — the step we build toward once the analytical substrate is in place in **Module 09 (Fabric Analytics & Reverse-ETL)**, and close on in **Module 10**.

### Return to **[Home](./Home.md#build-a-multi-agent-workshop)**

**[< Agent Analytics](./Module-07.md#module-07---agent-analytics-visibility-insight)** - **[Fabric Analytics & Reverse-ETL >](./Module-09.md#module-09---fabric-analytics-reverse-etl)**

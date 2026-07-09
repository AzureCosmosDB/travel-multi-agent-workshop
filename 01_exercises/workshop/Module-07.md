# Module 07 - Analytics & Optimization

**[< Evaluating Your Multi-Agent Application](./Module-06.md)** - **[Lessons Learned & The Future >](./Module-08.md)**

## Introduction

In Module 05 you made your travel assistant **observable** (LangSmith traces), and in Module 06 you learned to **evaluate** it (LLM-as-judge quality scores). Observability tells you *what happened*; evaluation tells you *how good it was*. This module closes the loop: turning that signal into **optimizations you can apply and verify** — and, ultimately, that the system can apply to *itself*.

Every turn your app runs today uses the **same model** (`gpt-4.1-mini`) — whether the user typed "hi" or "plan me a 5-day itinerary for Tokyo." Roughly **half of all turns are trivial** (greetings, acknowledgements, short clarifications) yet pay for the full model, while the highest-value turns (itinerary generation) could benefit from a *more* capable model. That mismatch is a concrete, data-visible **optimization opportunity**.

In this module you'll work the full **optimization loop**:

> **instrument → detect → recommend → apply → verify**

You'll add lightweight instrumentation, detect the opportunity from your own data, build the decision that classifies each turn, apply a **capability-tiered model-selection** policy with one click, and verify the effect. Finally, you'll wire your Module 06 evaluator in as an **automated quality gate**, so an optimization that hurts quality **reverts itself** — the mechanism that makes optimization *autonomous* and safe.

> **This module is additive.** It bolts onto the app you already built with a small number of hooks and two provided files. **You will not modify Modules 01–05.** The two model tiers and two Cosmos containers it uses are provisioned for you by `azd up` (Bicep) — you only write code.

## Learning Objectives and Activities

- Explain the optimization loop and the 5-level **maturity model** (Visibility → Recommendations → Assisted → Autonomous → Adaptive)
- Understand the **risk model**: prompt/workflow/code changes are human-governed; memory/routing/**model-selection**/tool *policies* are lower-risk and can be automated
- **Instrument** your app to capture per-turn tier + token signal
- **Detect** the opportunity from that signal and read the **recommendation card**
- **Build the decision layer** — classify each turn as trivial / routine / complex
- **Apply** a model-selection policy (one click) and observe live per-turn routing
- **Verify** the effect from data, reasoning about **cost per successful outcome**
- **(Stretch)** Tier the itinerary **sub-agent** (the worker), not just the supervisor turn
- **(Capstone)** Wire your evaluator as an **automated quality gate** for autonomous, self-reverting optimization

## Module Exercises

1. [Activity 1: The Optimization Loop, Maturity & Risk](#activity-1-the-optimization-loop-maturity--risk)
2. [Activity 2: Confirm Your Model Tiers (provisioned by Bicep)](#activity-2-confirm-your-model-tiers-provisioned-by-bicep)
3. [Activity 3: Tour the Provided Optimization Layer](#activity-3-tour-the-provided-optimization-layer)
4. [Activity 4: Wire the Optimization Layer into Your App](#activity-4-wire-the-optimization-layer-into-your-app)
5. [Activity 5: Detect the Opportunity in Your Data](#activity-5-detect-the-opportunity-in-your-data)
6. [Activity 6: Build the Decision Layer (`classify_turn_tier`)](#activity-6-build-the-decision-layer-classify_turn_tier)
7. [Activity 7: Apply the Policy and Watch It Route](#activity-7-apply-the-policy-and-watch-it-route)
8. [Activity 8: Verify from Data](#activity-8-verify-from-data)
9. [Activity 9 (Stretch): Tier the Itinerary Sub-Agent](#activity-9-stretch-tier-the-itinerary-sub-agent)
10. [Activity 10 (Capstone): An Automated Quality Gate](#activity-10-capstone-an-automated-quality-gate)

---

## Activity 1: The Optimization Loop, Maturity & Risk

### The loop

Optimizing an agent system is a repeatable loop:

1. **Instrument** — capture per-turn signal (tokens, model, tier).
2. **Detect** — mine that signal for waste or opportunity.
3. **Recommend** — turn a finding into a concrete, proposed change (a "candidate card").
4. **Apply** — enact the change, ideally with one click and fully reversible.
5. **Verify** — measure before/after from data to confirm it helped (and didn't hurt quality).

### The maturity model

How *autonomous* the "apply" step can be defines a 5-level maturity model:

| Level | Name | Who applies the change |
|-------|------|------------------------|
| L1 | Visibility | Humans read dashboards |
| L2 | Recommendations | System suggests; humans decide |
| L3 | Assisted | System applies with human approval |
| L4 | Autonomous | System applies within guardrails |
| L5 | Adaptive | System continuously self-tunes |

### The risk model (the key idea)

**Not every optimization is equally safe to automate.**

- **Higher-risk (human-governed, ceiling ~L3):** changes to **prompts, workflows, or code** — these change behavior in hard-to-bound ways and belong in code review / PRs.
- **Lower-risk (can reach L4/L5):** changes to **policies** — memory salience/retention, retrieval weighting, routing thresholds, **model selection**, tool-selection. These are bounded knobs, are reversible, and can be governed by an automated quality gate.

Model selection is a **lower-risk policy**, which is why it's our first end-to-end autonomous example. You'll route each turn to a model sized to the turn's value:

- **trivial** turns → a cheap model (`gpt-5-nano`)
- **routine** turns → the default (`gpt-4.1-mini`)
- **complex** turns → a capable model (`gpt-5.1`)

---

## Activity 2: Confirm Your Model Tiers (provisioned by Bicep)

Capability-tiering needs a cheap tier and a capable tier. **These are already deployed** — the Module 00 `azd up` provisioning (Bicep) creates `gpt-5-nano` and `gpt-5.1` alongside your `gpt-4.1-mini`, and creates the `OptimizationPolicies` and `OptimizationTurns` Cosmos containers. Confirm they exist:

```powershell
az cognitiveservices account deployment list -n <your-openai-account> -g <your-resource-group> -o table
```

You should see `gpt-4.1-mini`, `text-embedding-3-small`, **`gpt-5-nano`**, and **`gpt-5.1`**.

> **Quota note:** newer models share a **subscription-level** GlobalStandard quota per region. If
> provisioning didn't create a tier (quota), the model factory falls back gracefully; you can also
> point the policy at any available cheap/capable pair — it is model-agnostic.
>
> **Reasoning models:** `gpt-5-nano` and `gpt-5.1` are *reasoning* models — they reject a custom
> `temperature` and need a newer API version. The provided model factory already handles this. It's
> why nano can spend a few hundred "reasoning" output tokens on a one-word reply (this matters in
> Activity 8).

---

## Activity 3: Tour the Provided Optimization Layer

Two files are provided so you can focus on the *decision* and the *wiring*, not re-implement infrastructure:

**`python/src/app/services/optimization.py`** — the engine:

| Piece | What it does |
|-------|--------------|
| policy store (`get_active_policy`, `apply_policy`, `revert_policy`, …) | A Cosmos-backed, **versioned, reversible** policy in `OptimizationPolicies`. Status is `proposed → active → reverted`. **Applying/reverting is a status flip + audit — never a code edit.** Only an `active` + `enabled` policy changes behavior, so the default is always safe. |
| `get_chat_model(deployment)` | A cached, per-deployment model factory (reasoning-aware). |
| `select_deployment_for_turn(messages)` | Reads the active policy and returns `(deployment, tier)` for a turn. |
| `get_supervisor_for_turn(messages, default_graph)` | Returns the tier's supervisor (built from a factory you register), or your default graph when no policy is active. |
| `record_optimization_turn(...)` | Writes one turn's tier + tokens to `OptimizationTurns` (the *instrument* step). |
| `build_recommendations(tenant)` | Mines `OptimizationTurns` into a candidate card (the *recommend* step). |
| `classify_turn_tier(...)` | **The one function you implement** (Activity 6). |

**`python/src/app/optimization_api.py`** — the `/optimizations` REST surface (recommend, propose, **apply**, **revert**).

---

## Activity 4: Wire the Optimization Layer into Your App

Four small hooks connect the layer to the app you built. All are in code you already own.

**(a) Mount the REST surface.** In `travel_agents_api.py`, next to your other routers/middleware:

```python
from src.app.optimization_api import router as optimization_router
app.include_router(optimization_router)
```

**(b) Make your supervisor buildable with any model.** In `travel_agents.py`, if your supervisor is
constructed inline, extract that construction into a function that takes a chat model, e.g.:

```python
def create_supervisor(chat_model):
    return create_react_agent(chat_model, tools=[...], prompt=..., checkpointer=...)
```

Then register it once at startup (e.g. in `setup_agents`) so the optimization layer can build a
supervisor per tier:

```python
from src.app.services import optimization
optimization.register_supervisor_factory(create_supervisor)
```

**(c) Select the tier's supervisor per turn.** In your completion handler, where you currently do
`workflow = build_agent_graph()`, use the tiered selector instead (it returns your default graph when
no policy is active, so this is safe to add now):

```python
workflow, deployment, tier = optimization.get_supervisor_for_turn(
    messages, default_graph=build_agent_graph()
)
```

**(d) Record each turn (the *instrument* step).** After you invoke the graph and extract token usage
(you already do this), record it:

```python
optimization.record_optimization_turn(
    tenant_id=tenantId, user_id=userId, session_id=sessionId,
    tier=tier, deployment=deployment,
    usage={"input_tokens": input_tokens, "output_tokens": output_tokens,
           "total_tokens": total_tokens, "cached_tokens": cached_tokens},
    model_name=model_name,
)
```

Restart your API. Nothing behaves differently yet (no policy is active) — but every turn is now
captured to `OptimizationTurns`.

---

## Activity 5: Detect the Opportunity in Your Data

Generate a little traffic (use the frontend or the completion endpoint): a few greetings, a few place queries, and an itinerary request. Then read the **recommendation card** mined from your captured turns:

```powershell
Invoke-RestMethod "http://localhost:8000/optimizations/<yourTenant>" | ConvertTo-Json -Depth 6
```

Look at the evidence: **one model** serving every turn, and a meaningful share of **trivial turns** (short answers). The card includes an **estimated** saving (labeled as an estimate — Activity 8 explains why the *measured* result is what counts) and the proposed tiered policy.

---

## Activity 6: Build the Decision Layer (`classify_turn_tier`)

Open `python/src/app/services/optimization.py` and find the `classify_turn_tier` stub:

```python
def classify_turn_tier(text: str, classifier: dict | None = None) -> str:
    ...
    classifier = classifier or {}
    # TODO: replace this with your implementation.
    return "routine"
```

Implement it. The intent is **conservative**: when in doubt, `routine` (the default model) — you never want a substantive place query silently downgraded. Reference solution:

```python
def classify_turn_tier(text: str, classifier: dict | None = None) -> str:
    classifier = classifier or {}
    trivial_max = int(classifier.get("trivial_max_words", _DEFAULT_TRIVIAL_MAX_WORDS))
    trivial_patterns = classifier.get("trivial_patterns", _DEFAULT_TRIVIAL_PATTERNS)
    complex_patterns = classifier.get("complex_patterns", _DEFAULT_COMPLEX_PATTERNS)

    t = (text or "").strip().lower()
    if not t:
        return "routine"
    for p in complex_patterns:          # explicit planning asks first
        if re.search(p, t):
            return "complex"
    words = re.findall(r"[a-z0-9']+", t)
    if len(words) <= trivial_max and any(re.search(p, t) for p in trivial_patterns):
        return "trivial"                # short AND greeting-like
    return "routine"
```

The default pattern lists and word cap are defined just above the stub. Note the ordering: **complex first**, then trivial requires *both* short length *and* a greeting-like pattern — so "hotels in Amsterdam" (3 words, no greeting) correctly stays `routine`.

### Self-check

```python
from src.app.services.optimization import classify_turn_tier
assert classify_turn_tier("hi") == "trivial"
assert classify_turn_tier("thanks!") == "trivial"
assert classify_turn_tier("hotels in Amsterdam") == "routine"
assert classify_turn_tier("What is the Krasnapolsky?") == "routine"
assert classify_turn_tier("please build me an itinerary for 3 days in Paris") == "complex"
assert classify_turn_tier("plan my trip to Tokyo") == "complex"
```

---

## Activity 7: Apply the Policy and Watch It Route

**Apply** the model-selection policy — one call, reversible (it auto-seeds the proposed policy if needed):

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/optimizations/model-selection/apply" -ContentType "application/json" -Body '{}'
```

Now send three turns and watch which model serves each (via your API logs and the `OptimizationTurns` records):

- `hi` → tier `trivial` → `gpt-5-nano`
- `hotels in amsterdam` → tier `routine` → `gpt-4.1-mini`
- `please build me an itinerary for 3 days in amsterdam` → tier `complex` → `gpt-5.1`

Roll back just as easily — fully:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/optimizations/model-selection/revert" -ContentType "application/json" -Body '{}'
```

After revert, the next turn is recorded as `tier=default, deployment=gpt-4.1-mini` — the app is back to its original behavior. **This reversibility is exactly what makes a policy safe to automate.**

---

## Activity 8: Verify from Data

Estimates can lie — especially with reasoning models. Measure the real effect from your captured turns:

```powershell
python analytics/optimization_mining.py --tenant <yourTenant> --verify --container OptimizationTurns
```

You'll get a per-tier token + estimated-cost breakdown. Two honest observations to reason about:

1. **The reasoning-token caveat.** `gpt-5-nano` can spend a few hundred output tokens on "hi" (reasoning tokens you can't see). A naive "cheaper model saves money" projection ignores this. In practice nano's very low **input** price still makes the trivial turn cheaper — but you only *know* that from the measured result, not the estimate. **Always verify.**
2. **Cost per outcome, not per turn.** The `complex` tier (`gpt-5.1`) is *more* expensive per turn. Whether it's worth it depends on whether the better itinerary raises **conversion** — i.e., lowers cost per *confirmed trip*, not per turn. That is the north-star metric this optimization ultimately serves.

---

## Activity 9 (Stretch): Tier the Itinerary Sub-Agent

In Activity 7, a `complex` turn runs the **supervisor** on `gpt-5.1` — but the supervisor then calls the itinerary **sub-agent**, which still uses the default model. So the capable model is doing the *routing*, while the cheap model does the actual **itinerary generation** — arguably backwards.

**The higher-value pattern is to tier the worker.** Where your itinerary sub-agent is constructed with the default `model`, build it instead with `optimization.get_chat_model("gpt-5.1")` (or rebuild it per-invocation from the active policy's `complex` tier). Then weigh the trade-offs you now understand: **quality** (the capable model where creativity matters) vs **latency** (reasoning models are slower) and **attribution** (a turn's "tier" is less clean when supervisor and sub-agent differ). Measure it the same way (Activity 8) and judge it on **cost per outcome**.

---

## Activity 10 (Capstone): An Automated Quality Gate

So far *you* decided whether the optimization was good (Activity 8). To reach **autonomous** (L4/L5), the *system* must decide — safely. The mechanism is a **quality gate**: after applying an optimization, run your **Module 06 evaluator**; keep the policy active only if quality holds above a threshold, otherwise **auto-revert**.

```python
# pseudo-code — wire in your Module 06 eval harness
from src.app.services import optimization
optimization.apply_policy("model-selection")           # enact the change
score = run_quality_eval(sample_conversations)         # your LLM-as-judge from Module 06
policy = optimization.get_policy("model-selection")
if score < policy["gate"]["threshold"]:
    optimization.revert_policy("model-selection")      # self-revert on regression
    print("optimization reverted: quality gate not met")
```

This is the dividing line in the maturity model:

- **L3 Assisted** — a human reads the verify report and approves.
- **L4/L5 Autonomous** — the gate approves/reverts automatically, so the system can safely tune *itself*.

With a gate in place, a cost optimization that quietly degrades answers can never stick — which is precisely what makes "let the system optimize itself" trustworthy.

---

## Test Your Work

- [ ] The four hooks (Activity 4) are wired; your app still runs normally with no active policy.
- [ ] `classify_turn_tier` passes the Activity 6 self-check.
- [ ] `GET /optimizations/<tenant>` returns a recommendation card built from your captured turns.
- [ ] With the policy **applied**, `hi` / `hotels in amsterdam` / an itinerary request route to `gpt-5-nano` / `gpt-4.1-mini` / `gpt-5.1` (visible in `OptimizationTurns`).
- [ ] `--verify` shows the per-tier cost breakdown, and you can explain the reasoning-token caveat and cost-per-outcome.
- [ ] **revert** returns the app to `default` / `gpt-4.1-mini`.
- [ ] (Stretch) The itinerary sub-agent runs on the capable tier.
- [ ] (Capstone) You can describe how the Module 06 evaluator serves as an auto-revert quality gate, and why that unlocks autonomous optimization.

## What You Learned

You closed the optimization loop: you **instrumented** your app, **detected** waste in your own data, **built** the decision that classifies each turn, **applied** a reversible model-selection policy with one click, and **verified** the result honestly (measuring, not guessing). You saw why *policies* — not prompts or code — are the safe surface for automation, and how an evaluation **quality gate** turns an assisted optimization into an autonomous, self-correcting one. This is the foundation of agent systems that **continuously improve themselves**.

### Return to **[Home](./Home.md)**

**[< Evaluating Your Multi-Agent Application](./Module-06.md)** - **[Lessons Learned & The Future >](./Module-08.md)**

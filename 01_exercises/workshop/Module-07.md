# Module 07 - Analytics & Optimization

**[< Evaluating Your Multi-Agent Application](./Module-06.md)** - **[Lessons Learned & The Future >](./Module-08.md)**

## Introduction

In Module 05 you made your travel assistant **observable** (LangSmith traces), and in Module 06 you learned to **evaluate** it (LLM-as-judge quality scores). Observability tells you *what happened*; evaluation tells you *how good it was*. This module closes the loop: turning that signal into **optimizations you can apply and verify** — and, ultimately, that the system can apply to *itself*.

> **Prerequisite — analytics signal.** This module builds on the per-turn **`Debug`** signal (tokens,
> model, tool calls, `agent_path`/`handoff_count`) captured in the completion path. Your app must be on
> the **v2 analytics baseline** (the `chat_event_generator` Debug re-wire) for the detect/verify steps
> to have data. If your exercise app predates that, complete the analytics-instrumentation setup first
> (see the `analytics/` reference and `02_completed`), then return here. The reference implementation
> lives in `02_completed`.

Every turn your app runs today uses the **same model** (`gpt-4.1-mini`) — whether the user typed "hi" or "plan me a 5-day itinerary for Tokyo." Your captured `Debug` data shows that roughly **half of all turns are trivial** (greetings, acknowledgements, short clarifications) yet pay for the full model, while the highest-value turns (itinerary generation) could benefit from a *more* capable model. That mismatch is a concrete, data-visible **optimization opportunity**.

In this module you'll work the full **optimization loop**:

> **instrument → detect → recommend → apply → verify**

You'll detect the opportunity from your own data, build the decision that classifies each turn, apply a **capability-tiered model-selection** policy with one click, and verify the effect. Finally, you'll wire your Module 06 evaluator in as an **automated quality gate**, so an optimization that hurts quality **reverts itself** — the mechanism that makes optimization *autonomous* and safe.

## Learning Objectives and Activities

- Explain the optimization loop and the 5-level **maturity model** (Visibility → Recommendations → Assisted → Autonomous → Adaptive)
- Understand the **risk model**: prompt/workflow/code changes are human-governed; memory/routing/**model-selection**/tool *policies* are lower-risk and can be automated
- **Detect** an optimization from data you already capture (`Debug` turn logs)
- **Build the decision layer** — classify each turn as trivial / routine / complex
- **Apply** a model-selection policy (one click) and observe live per-turn routing
- **Verify** the effect from data, reasoning about **cost per successful outcome**
- **(Stretch)** Tier the itinerary **sub-agent** (the worker), not just the supervisor turn
- **(Capstone)** Wire your evaluator as an **automated quality gate** for autonomous, self-reverting optimization

## Module Exercises

1. [Activity 1: The Optimization Loop, Maturity & Risk](#activity-1-the-optimization-loop-maturity--risk)
2. [Activity 2: Add the Model Tiers to Your Deployment](#activity-2-add-the-model-tiers-to-your-deployment)
3. [Activity 3: Detect the Opportunity in Your Data](#activity-3-detect-the-opportunity-in-your-data)
4. [Activity 4: Tour the Pre-Built Apply-Loop Plumbing](#activity-4-tour-the-pre-built-apply-loop-plumbing)
5. [Activity 5: Build the Decision Layer (`classify_turn_tier`)](#activity-5-build-the-decision-layer-classify_turn_tier)
6. [Activity 6: Apply the Policy and Watch It Route](#activity-6-apply-the-policy-and-watch-it-route)
7. [Activity 7: Verify from Data](#activity-7-verify-from-data)
8. [Activity 8 (Stretch): Tier the Itinerary Sub-Agent](#activity-8-stretch-tier-the-itinerary-sub-agent)
9. [Activity 9 (Capstone): An Automated Quality Gate](#activity-9-capstone-an-automated-quality-gate)

---

## Activity 1: The Optimization Loop, Maturity & Risk

### The loop

Optimizing an agent system is a repeatable loop over signal you already capture:

1. **Instrument** — capture per-turn signal (you did this: the `Debug` container records tokens, model, tool calls, agent path).
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

### The risk model (this is the key idea)

**Not every optimization is equally safe to automate.**

- **Higher-risk (human-governed, ceiling ~L3):** changes to **prompts, workflows, or code**. These change behavior in hard-to-bound ways and belong in code review / PRs.
- **Lower-risk (can reach L4/L5):** changes to **policies** — memory salience/retention, retrieval weighting, routing thresholds, **model selection**, tool-selection. These are bounded knobs, are reversible, and can be governed by an automated quality gate.

Model selection is a **lower-risk policy**, which is why it's our first end-to-end autonomous example. You'll route each turn to a model sized to the turn's value:

- **trivial** turns → a cheap model (`gpt-5-nano`)
- **routine** turns → the default (`gpt-4.1-mini`)
- **complex** turns → a capable model (`gpt-5.1`)

---

## Activity 2: Add the Model Tiers to Your Deployment

Your app currently has one chat deployment (`gpt-4.1-mini`). Capability-tiering needs a cheap tier and a capable tier. Add two deployments to your Azure OpenAI account.

> Find your account name and resource group (from Module 00's provisioning), then:

```powershell
$acct = "<your-openai-account>"      # e.g. openai-xxxxxxxx
$rg   = "<your-resource-group>"

# Cheap tier for trivial turns
az cognitiveservices account deployment create -n $acct -g $rg `
  --deployment-name "gpt-5-nano" `
  --model-name "gpt-5-nano" --model-version "2025-08-07" --model-format OpenAI `
  --sku-name "GlobalStandard" --sku-capacity 50

# Capable tier for complex turns
az cognitiveservices account deployment create -n $acct -g $rg `
  --deployment-name "gpt-5.1" `
  --model-name "gpt-5.1" --model-version "2025-11-13" --model-format OpenAI `
  --sku-name "GlobalStandard" --sku-capacity 30
```

> **Quota note:** newer models share a **subscription-level** GlobalStandard quota per region. If a
> create fails with a quota error, either request an increase or pick another available cheap/capable
> pair (e.g. `gpt-5-mini`, `gpt-4o-mini`) — the policy is model-agnostic. Check availability with
> `az cognitiveservices account list-models -n $acct -g $rg`.

> **Reasoning models:** `gpt-5-nano` and `gpt-5.1` are *reasoning* models. They reject a custom
> `temperature` and require a recent API version. The pre-built model factory already handles this
> (Activity 4) — you don't need to change anything, but it's worth knowing why nano can spend a few
> hundred "reasoning" output tokens even on a one-word reply (this matters in Activity 7).

---

## Activity 3: Detect the Opportunity in Your Data

The repository ships a **data-first discovery tool**, `analytics/optimization_mining.py`, that reads only the `Debug` signal your app already captures. Run it against your tenant:

```powershell
python analytics/optimization_mining.py --tenant <yourTenant>
```

Look at the **SCEN-007** section of the output:

```
=== SCEN-007 model / cache ===
  models={'gpt-4.1-mini-...': N}  cache_hit=..%  trivial_turns=<X>/<N>
```

You'll see **one model** serving every turn, and a large share of **trivial turns** (turns with no delegation and a very short response). That share — commonly ~48% — is turns paying full price for near-zero work. This is the opportunity the model-selection policy targets.

You can also fetch the same finding as a **recommendation card** from the running API:

```powershell
Invoke-RestMethod "http://localhost:8000/optimizations/<yourTenant>" | ConvertTo-Json -Depth 6
```

The card includes the evidence, an **estimated** saving (labeled as an estimate — see Activity 7 for why the *measured* result is what counts), and the proposed policy.

---

## Activity 4: Tour the Pre-Built Apply-Loop Plumbing

So you can focus on the *decision*, the reversible infrastructure is provided. Skim these — you won't edit them:

| File | What it does |
|------|--------------|
| `services/optimization_policy.py` | A Cosmos-backed, **versioned, reversible** policy store (`OptimizationPolicies`). Status is `proposed → active → reverted`. **Applying/reverting is a status flip + audit entry — never a code edit.** Only an `active` + `enabled` policy changes runtime behavior, so the default is always safe. |
| `services/azure_open_ai.py` → `get_chat_model(deployment)` | A cached, per-deployment model factory. Reasoning deployments (`gpt-5*`) automatically omit `temperature` and use a compatible API version. |
| `travel_agents.py` → `get_supervisor_for_turn()` / `_build_supervisor()` | Builds and caches one supervisor per deployment (sharing tools + checkpointer), and selects one per turn. |
| `travel_agents_api.py` | Calls `get_supervisor_for_turn()` for each turn and records `model_tier` + `model_deployment` on the `Debug` log. |
| `optimization_api.py` | The `/optimizations` REST surface: recommend, propose, **apply**, **revert**. |

The one thing this plumbing needs from **you** is the decision: *given a user message, which tier is this turn?* That is `classify_turn_tier`, and it's your job in the next activity.

---

## Activity 5: Build the Decision Layer (`classify_turn_tier`)

Open `python/src/app/travel_agents.py`. Find the `classify_turn_tier` stub:

```python
def classify_turn_tier(text: str, classifier: dict | None = None) -> str:
    """Classify a turn as 'trivial', 'complex', or 'routine' from the user text.

    - 'complex'  : explicit planning / itinerary requests -> capable model
    - 'trivial'  : short greetings / acknowledgements       -> cheap model
    - 'routine'  : everything else (incl. place queries)    -> default model

    TODO (Module 07): implement the classification. Use the default pattern
    lists and word cap below. Be CONSERVATIVE: only clearly trivial greetings
    become 'trivial', and only explicit planning asks become 'complex', so that
    real place queries never lose quality on the cheap model.
    """
    classifier = classifier or {}
    # TODO: return "complex" | "trivial" | "routine"
    return "routine"
```

Implement it. The design intent is **conservative**: when in doubt, `routine` (the default model) — you never want a substantive place query silently downgraded. Reference solution:

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

The default pattern lists (`_DEFAULT_TRIVIAL_PATTERNS`, `_DEFAULT_COMPLEX_PATTERNS`) and `_DEFAULT_TRIVIAL_MAX_WORDS` are already defined above the stub. Note the ordering: **complex is checked first**, then trivial requires *both* a short length *and* a greeting-like pattern — so "hotels in Amsterdam" (3 words, no greeting) correctly stays `routine`.

### Self-check

```python
assert classify_turn_tier("hi") == "trivial"
assert classify_turn_tier("thanks!") == "trivial"
assert classify_turn_tier("hotels in Amsterdam") == "routine"
assert classify_turn_tier("What is the Krasnapolsky?") == "routine"
assert classify_turn_tier("please build me an itinerary for 3 days in Paris") == "complex"
assert classify_turn_tier("plan my trip to Tokyo") == "complex"
```

---

## Activity 6: Apply the Policy and Watch It Route

Make sure your MCP server and API are running (Module 00). Then **apply** the model-selection policy — one call, reversible:

```powershell
# Apply (auto-seeds the proposed policy if needed) — this is the "one-click apply"
Invoke-RestMethod -Method Post "http://localhost:8000/optimizations/model-selection/apply" -ContentType "application/json" -Body '{}'
```

Now send three turns (via the frontend, or the completion endpoint) and watch the API log:

- `hi` → `Model tier 'trivial' -> deployment 'gpt-5-nano'`
- `hotels in amsterdam` → `Model tier 'routine' -> deployment 'gpt-4.1-mini'`
- `please build me an itinerary for 3 days in amsterdam` → `Model tier 'complex' -> deployment 'gpt-5.1'`

Each turn's `Debug` document now records `model_tier` and `model_deployment`, and its `model_name` independently confirms which model actually served the turn.

To roll back — just as easily, and fully:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/optimizations/model-selection/revert" -ContentType "application/json" -Body '{}'
```

After revert, the next turn records `tier=default, deployment=gpt-4.1-mini` — the app is back to its original behavior. **This reversibility is exactly what makes a policy safe to automate.**

---

## Activity 7: Verify from Data

Estimates can lie — especially with reasoning models. Measure the real effect:

```powershell
python analytics/optimization_mining.py --tenant <yourTenant> --verify
```

You'll get a per-tier token + estimated-cost breakdown, e.g.:

```
tier (deployment)                 turns     in    out   total    est $
complex (gpt-5.1)                     1  30918   1698   32616  0.05563
routine (gpt-4.1-mini)                1  15543    403   15946  0.00686
trivial (gpt-5-nano)                  1   3335    493    3828  0.00036
```

Two honest observations to reason about:

1. **The reasoning-token caveat.** `gpt-5-nano` spent ~493 output tokens on "hi" (reasoning tokens you can't see). A naive "cheaper model saves money" projection ignores this. Here, nano's very low **input** price still makes the trivial turn ~4× cheaper than mini — but you only *know* that from the measured result, not the estimate. **Always verify.**
2. **Cost per outcome, not per turn.** The `complex` tier (`gpt-5.1`) is *more* expensive per turn. Whether it's worth it depends on whether the better itinerary raises **conversion** — i.e., lowers cost per *confirmed trip*, not cost per turn. That is the north-star metric this optimization ultimately serves.

---

## Activity 8 (Stretch): Tier the Itinerary Sub-Agent

In Activity 6, a `complex` turn runs the **supervisor** on `gpt-5.1` — but the supervisor then calls the itinerary **sub-agent** (`create_or_update_itinerary`), which still uses the default model. So the capable model is doing the *routing*, while the cheap model does the actual **itinerary generation** — arguably backwards.

**The higher-value pattern is to tier the worker.** In `travel_agents.py`, the itinerary sub-agent is built with `_create_agent(model, ...)`. As a stretch:

- Build the itinerary sub-agent with `get_chat_model(<complex-tier-deployment>)` instead of the default `model`, or rebuild it per invocation from the active policy's `complex` tier.
- Consider the trade-offs you now understand: **quality** (the capable model where creativity matters) vs **latency** (reasoning models are slower) and **attribution** (a turn's "tier" is less clean when supervisor and sub-agent differ).

Measure it the same way (Activity 7), and judge it on **cost per outcome**.

---

## Activity 9 (Capstone): An Automated Quality Gate

So far *you* decided whether the optimization was good (Activity 7). To reach **autonomous** (L4/L5), the *system* must decide — safely. The mechanism is a **quality gate**: after applying an optimization, run your **Module 06 evaluator**; keep the policy active only if quality holds above a threshold, otherwise **auto-revert**.

Sketch:

```python
# pseudo-code — wire your Module 06 eval harness in
apply_policy("model-selection")                 # enact the change
score = run_quality_eval(sample_conversations)  # your LLM-as-judge from Module 06
if score < policy["gate"]["threshold"]:
    revert_policy("model-selection")            # self-revert on regression
    log("optimization reverted: quality gate not met")
```

This is the dividing line in the maturity model:

- **L3 Assisted** — a human reads the verify report and approves.
- **L4/L5 Autonomous** — the gate approves/reverts automatically, so the system can safely tune *itself*.

With a gate in place, a cost optimization that quietly degrades answers can never stick — which is precisely what makes "let the system optimize itself" trustworthy.

---

## Test Your Work

- [ ] `classify_turn_tier` passes the Activity 5 self-check.
- [ ] With the policy **applied**, `hi` / `hotels in amsterdam` / an itinerary request route to `gpt-5-nano` / `gpt-4.1-mini` / `gpt-5.1` respectively (API log + `Debug` `model_tier`).
- [ ] `--verify` shows the per-tier cost breakdown, and you can explain the reasoning-token caveat and cost-per-outcome.
- [ ] **revert** returns the app to `default` / `gpt-4.1-mini`.
- [ ] (Stretch) The itinerary sub-agent runs on the capable tier.
- [ ] (Capstone) You can describe how the Module 06 evaluator serves as an auto-revert quality gate, and why that unlocks autonomous optimization.

## What You Learned

You closed the optimization loop: you **detected** waste in your own data, **built** the decision that classifies each turn, **applied** a reversible model-selection policy with one click, and **verified** the result honestly (measuring, not guessing). You saw why *policies* — not prompts or code — are the safe surface for automation, and how an evaluation **quality gate** turns an assisted optimization into an autonomous, self-correcting one. This is the foundation of agent systems that **continuously improve themselves**.

### Return to **[Home](./Home.md)**

**[< Evaluating Your Multi-Agent Application](./Module-06.md)** - **[Lessons Learned & The Future >](./Module-08.md)**

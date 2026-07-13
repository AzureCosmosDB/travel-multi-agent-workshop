# Module 08 - Agent Optimization (Apply & Autonomy)

**[< Agent Analytics](./Module-07.md)** - **[Lessons Learned & The Future >](./Module-09.md)**

## Introduction

In Module 07 you made your agent's behavior **visible**: you instrumented every turn, explored the signal in the Optimization Console and Power BI, detected the model-selection opportunity, and set a cost-per-outcome baseline. That's the first half of the loop:

> **instrument → detect → recommend →** *apply → verify*

This module closes it. You'll **apply** the recommended optimization with one click, **verify** it from data, then climb the maturity ladder: contrast a **lower-risk autonomous** change (model selection) with a **higher-risk human-governed** one (a prompt fix), and finally wire an **automated quality gate** so the system can safely optimize *itself*.

> Still additive — you'll implement one decision function and a few small hooks. **No changes to Modules 01–05.** The model tiers (`gpt-5-nano`, `gpt-5.1`) and containers are already provisioned by `azd up`.

## Learning Objectives and Activities

- Understand why **policies** are the safe surface for automated optimization, and how apply/revert stay reversible
- **Build the decision** that classifies each turn (trivial / routine / complex)
- **Apply** a model-selection policy (L4/L5) and **verify** its effect from data
- Contrast it with a **human-governed L3** optimization (a prompt fix) — the risk model in practice
- **(Stretch)** Tier the itinerary sub-agent (the worker), the higher-value pattern
- **(Capstone)** Wire your Module 06 evaluator as an **automated quality gate** that auto-reverts regressions — reaching **autonomous** optimization

## Module Exercises

1. [Activity 1: The Apply-Loop and the Safe Surface](#activity-1-the-apply-loop-and-the-safe-surface)
2. [Activity 2: Build the Decision (`classify_turn_tier`)](#activity-2-build-the-decision-classify_turn_tier)
3. [Activity 3: Apply and Watch It Route](#activity-3-apply-and-watch-it-route)
4. [Activity 4: Verify from Data](#activity-4-verify-from-data)
5. [Activity 5: A Different Risk Level — a Human-Governed Optimization](#activity-5-a-different-risk-level--a-human-governed-optimization)
6. [Activity 6 (Stretch): Tier the Itinerary Sub-Agent](#activity-6-stretch-tier-the-itinerary-sub-agent)
7. [Activity 7 (Capstone): An Automated Quality Gate](#activity-7-capstone-an-automated-quality-gate)

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

You'll use this machinery for model selection now, and see the *contrast* with a prompt change in Activity 5.

---

## Activity 2: Build the Decision (`classify_turn_tier`)

The policy routes each turn to a model tier, but *what tier is this turn?* is a judgment the provided engine leaves to **you**. Open `python/src/app/services/optimization.py` and find the stub:

```python
def classify_turn_tier(text: str, classifier: dict | None = None) -> str:
    ...
    classifier = classifier or {}
    # TODO: replace this with your implementation.
    return "routine"
```

Implement it. Be **conservative** — when in doubt, `routine` (the default model); never silently downgrade a real place query. Reference solution:

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

The default pattern lists and word cap sit just above the stub. Note the order — **complex first**, then trivial requires *both* short length *and* a greeting-like pattern — so "hotels in Amsterdam" (3 words, no greeting) correctly stays `routine`.

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

## Activity 3: Apply and Watch It Route

### Wire the enforcement hooks

Two small hooks let the policy actually pick a model per turn.

**Hook A — make your supervisor buildable with any model.** If your supervisor is constructed inline, extract that into a function taking a chat model, then register it once at startup so the layer can build a supervisor per tier:

```python
def create_supervisor(chat_model):
    return create_react_agent(chat_model, tools=[...], prompt=..., checkpointer=...)

# once, e.g. in setup_agents:
from src.app.services import optimization
optimization.register_supervisor_factory(create_supervisor)
```

**Hook B — select the tier's supervisor per turn.** Where you currently do `workflow = build_agent_graph()`, use the tiered selector (it returns your default graph when no policy is active, so this is safe):

```python
workflow, deployment, tier = optimization.get_supervisor_for_turn(
    messages, default_graph=build_agent_graph()
)
```

Then update your Module 07 record hook to log the **real** tier/deployment instead of `"default"`:

```python
optimization.record_optimization_turn(
    tenant_id=tenantId, user_id=userId, session_id=sessionId,
    tier=tier, deployment=deployment,
    usage={...}, model_name=model_name,
)
```

### Apply the policy

One click — from the **Optimization Console** (the "Apply" button on the model-selection card) or via REST:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/optimizations/model-selection/apply" -ContentType "application/json" -Body '{}'
```

Now send three turns and watch which model serves each (API logs + `OptimizationTurns`):

- `hi` → tier `trivial` → `gpt-5-nano`
- `hotels in amsterdam` → tier `routine` → `gpt-5-mini`
- `please build me an itinerary for 3 days in amsterdam` → tier `complex` → `gpt-5.1`

In `OptimizationTurns` you'll see the tier and the *actual* serving model recorded per turn — for example:

```
tier      deployment    model_name              total_tokens
trivial   gpt-5-nano    gpt-5-nano-2025-08-07          3,828
routine   gpt-5-mini    gpt-5-mini-2025-08-07         15,946
complex   gpt-5.1       gpt-5.1-2025-11-13            32,616
```

The `model_name` (reported by the model itself) is your independent proof that the policy actually changed which model ran — not just what you intended.

### Revert — just as easily

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/optimizations/model-selection/revert" -ContentType "application/json" -Body '{}'
```

After revert, the next turn records `tier=default, deployment=gpt-5.1`. **That reversibility is exactly what makes this policy safe to automate.**

---

## Activity 4: Verify from Data

Re-drive some traffic with the policy applied, then measure:

```powershell
python analytics/optimization_mining.py --tenant <yourTenant> --verify --container OptimizationTurns
```

Compare against your Module 07 baseline. You'll see a per-tier breakdown like:

```
tier (deployment)            turns     in    out   total    est $
complex (gpt-5.1)                1  30918   1698   32616  0.05563
routine (gpt-5-mini)             1  15543    403   15946  0.00469
trivial (gpt-5-nano)             1   3335    493    3828  0.00036
```

Two honest lessons:

1. **The reasoning-token caveat.** `gpt-5-nano` is a *reasoning* model — it can spend a few hundred hidden "reasoning" output tokens even on "hi". A naive "cheaper model saves money" projection ignores that. In practice nano's very low **input** price still makes the trivial turn cheaper — but you only *know* from the measured result. **Always verify; never ship an estimate as a result.**
2. **Cost per outcome.** The `complex` tier (`gpt-5.1`) is *more* expensive per turn. Whether it's worth it depends on whether better itineraries raise **conversion** — lowering cost per *confirmed trip*, not per turn. Judge the optimization on the outcome metric, not the token bill.

You've now completed the loop for a **lower-risk, autonomous-capable** optimization (maturity L3 today — you approved it; L4/L5 after Activity 7).

---

## Activity 5: A Different Risk Level — a Human-Governed Optimization

Not every optimization is a policy knob. Recall the assistant asking which city a hotel is in even when a city was already chosen — a **prompt** problem (the supervisor prompt doesn't assert the active trip's city). Analytics can *detect* and *recommend* this too, but **applying** it is different.

Open the recommendation for the **active-trip-city-context** scenario (Console or `GET /optimizations/<tenant>`). Notice how it differs from the model-selection card:

- It's the **agent-quality / prompt** dimension, `apply_mode: "staged_change"`, maturity **L3**.
- Its evidence is the count of **city re-asks** detected in your conversations (reproduce it first: start a trip for Amsterdam, then ask about a hotel by name *without* the city — the supervisor re-asks which city).
- Its recommended fix is a **prompt change**, so it **cannot be applied at runtime**.

Try to apply it like a policy — it's refused:

```powershell
# 400: human-governed prompt change; use /stage instead
Invoke-RestMethod -Method Post "http://localhost:8000/optimizations/active-trip-city-context/apply" -ContentType "application/json" -Body '{}'
```

Instead, **stage** it (the Console's "Stage for review" button, or `/stage`). Staging records a reviewable proposal — the exact prompt edit and file — for a human to merge via PR. It does **not** change runtime:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/optimizations/active-trip-city-context/stage" -ContentType "application/json" -Body '{}'
# -> { "status": "staged", "proposed_change": { "file": "...supervisor.prompty", "add": "..." } }
```

This is the **risk model in practice**:

| | Model selection (Activity 3) | Prompt fix (this activity) |
|---|---|---|
| Surface | policy (data) | prompt (code) |
| Apply | live toggle, reversible | staged diff → human review / PR |
| Max autonomy | L4/L5 | L3 (assisted) |

The same analytics loop surfaces both — but the **apply** step respects each one's risk. Never wire a prompt/workflow/code change to auto-apply the way you did the policy.

> **These two aren't the only cards.** The Console surfaces the whole set, and each falls into one of three action-types:
> - **Apply-able policies** (like model selection): also **memory retention** (SCEN-004) — applying it soft-prunes stale/superseded memories (reversible), the same one-click pattern on a different dimension.
> - **Staged changes** (like city-context): also **redundant tool calls** (SCEN-008) — a prompt fix to stop re-calling the same tool.
> - **Diagnostic lenses** (SCEN-003 cost-per-outcome & conversion funnel, SCEN-005 agent-path): no apply button. SCEN-003 is the **business-impact** lens — a funnel (engaged → searched → planned → confirmed) that shows *where* sessions leak and *why*, and points at the fix (e.g. "biggest leak: city friction → SCEN-001"). They show *where* the waste is; you act via the policies/staged fixes above. Be honest in a demo — a dashboard can flag "these sessions never convert" and even *name the likely cause*, but converting them is a product problem, not a toggle.

---

## Activity 6 (Stretch): Tier the Itinerary Sub-Agent

In Activity 3, a `complex` turn runs the **supervisor** on `gpt-5.1` — but the supervisor then calls the itinerary **sub-agent**, which still uses the default model. So the capable model does the *routing* while the cheap model does the actual **itinerary generation** — arguably backwards.

**The higher-value pattern is to tier the worker.** Where your itinerary sub-agent is built with the default `model`, build it instead with `optimization.get_chat_model("gpt-5.1")` (or rebuild it per-invocation from the active policy's `complex` tier). Then weigh the trade-offs you now understand: **quality** (capable model where creativity matters) vs **latency** (reasoning models are slower) and **attribution** (a turn's tier is less clean when supervisor and sub-agent differ). Measure it the same way and judge it on **cost per outcome**.

---

## Activity 7 (Capstone): An Automated Quality Gate

So far *you* decided whether an optimization was good (Activity 4). That's **L3 — assisted**. To reach **L4/L5 — autonomous**, the *system* must decide, safely. The mechanism is a **quality gate**: after applying, run your **Module 06 evaluator**; keep the policy active only if quality holds above a threshold, else **auto-revert**.

```python
# pseudo-code — wire in your Module 06 eval harness
from src.app.services import optimization

optimization.apply_policy("model-selection")            # enact the change
score = run_quality_eval(sample_conversations)          # your LLM-as-judge from Module 06
policy = optimization.get_policy("model-selection")
if score < policy["gate"]["threshold"]:
    optimization.revert_policy("model-selection")       # self-revert on regression
    print("optimization reverted: quality gate not met")
else:
    print("optimization retained: quality gate passed")
```

This is the dividing line in the maturity model:

- **L3 Assisted** — a human reads the verify report and approves.
- **L4/L5 Autonomous** — the gate approves/reverts automatically, so the system can safely tune *itself*, continuously.

With a gate in place, a cost optimization that quietly degrades answers can never stick — which is what makes "let the system optimize itself" trustworthy. That is the foundation of **adaptive** (L5) agent systems.

---

## Test Your Work

- [ ] `classify_turn_tier` passes the Activity 2 self-check.
- [ ] With the policy **applied**, `hi` / `hotels in amsterdam` / an itinerary request route to `gpt-5-nano` / `gpt-5-mini` / `gpt-5.1` (visible in `OptimizationTurns`).
- [ ] `--verify` shows the per-tier cost breakdown; you can explain the reasoning-token caveat and cost-per-outcome.
- [ ] **revert** returns the app to `default` / `gpt-5.1`.
- [ ] You can contrast the **policy** (auto-apply, reversible) vs the **prompt fix** (staged, human-governed) and say why each maxes out at a different maturity level.
- [ ] (Stretch) The itinerary sub-agent runs on the capable tier.
- [ ] (Capstone) You can describe — or wire — the Module 06 evaluator as an auto-revert quality gate, and explain why that unlocks autonomous optimization.

## Troubleshooting

- **Turns still all run `gpt-5.1` after apply.** Check that (1) the policy is `active` (`GET /optimizations/model-selection/policy`), (2) you registered the supervisor factory at startup, and (3) your completion handler calls `get_supervisor_for_turn` (not `build_agent_graph` directly). The policy cache also has a ~15s TTL — wait a few seconds after apply.
- **`gpt-5-nano`/`gpt-5.1` calls error.** These are reasoning models — the provided `get_chat_model` omits `temperature` and uses a newer API version for them. If you built the model yourself, don't pass `temperature`. Confirm both deployments exist (`az cognitiveservices account deployment list ...`); if quota blocked one, point the policy's tier at an available model.
- **`classify_turn_tier` misroutes.** Run the Activity 2 self-check. A common bug is checking trivial *before* complex, or not requiring *both* short length and a greeting pattern for trivial.
- **Revert didn't take effect.** Same ~15s cache TTL; the *next* turn after it expires uses the default.

## What You Learned

You closed the optimization loop: you **built** the decision, **applied** a reversible model-selection policy with one click, and **verified** the result honestly (measuring, not guessing). You saw why *policies* — not prompts or code — are the safe surface for automation, contrasted an autonomous change with a human-governed one, and learned how an evaluation **quality gate** turns an assisted optimization into an autonomous, self-correcting one. This is the foundation of agent systems that **continuously improve themselves** — the theme we close on in Module 09.

### Return to **[Home](./Home.md)**

**[< Agent Analytics](./Module-07.md)** - **[Lessons Learned & The Future >](./Module-09.md)**

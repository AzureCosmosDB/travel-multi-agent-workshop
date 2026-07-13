# Demo script — Agent Analytics & Optimization (60-minute session)

A presenter's talk track for demonstrating the **model-selection optimization** (SCEN-007)
end to end, without generating a mountain of data live. The design: pre-baked data carries
the at-scale story, and one small live moment makes it real.

The loop this demonstrates is the one the workshop teaches:
**instrument → detect → recommend → apply → verify.**

---

## Why the "before" looks the way it does

In the seed, most turns have `model_tier = "default"` — i.e. one premium model (gpt-5.1)
served *everything*, trivial or complex. That's not a bug to hide; it's the hook: **this is a
real agent app before anyone optimized it.** The optimization tiers trivial turns down to a
nano model, routine to a mini model, and keeps the premium model for the hard work.

You don't need a temporal before/after. You have two better devices:
1. A pre-baked **A/B** (two tenants, identical workload, one un-tiered and one tiered) for a
   guaranteed apples-to-apples comparison.
2. A **few live turns** through the real app to prove the routing happens for real.

---

## Pre-session setup (do once, off-stage)

1. **Build the A/B dataset** (paired before/after, ~28% lower cost on the tiered side):
   ```powershell
   python analytics/ab_demo_seed.py
   ```
   Writes `before_demo` (240 turns, all on gpt-5.1, `model_tier="default"`) and `after_demo`
   (the *identical* 240-turn workload, tiered to nano/mini/gpt-5.1). Only the model routing
   differs, so the cost delta is the pure saving. Deterministic (seed 42) and re-runnable.

2. **Build the conversion-funnel dataset** (the business-impact story):
   ```powershell
   python analytics/funnel_seed.py
   ```
   Writes `funnel_demo` — ~120 sessions that encode real **abandonment causes**, so the
   SCEN-003 diagnostic can show *why* sessions don't convert (not just how much they cost).

3. **Report:** open the `.pbit`, point it at your mirror, and (Power BI guide Step 5) add a
   **tenant slicer** and a report-level filter defaulting to `analytics_demo`.

4. **Confirm the app + policy:** make sure the app is reachable and the **model-selection
   policy is NOT yet applied** (you'll apply it on stage). Have the API endpoint handy — the
   web app URL + `/api` (find it via `azd env get-value FRONTEND_URI`, then append `/api`).

5. **Dry-run the live turns once** (so you trust them on stage) — see "Live turns" below.

---

## The talk track (~15–20 min of demo)

**1. Baseline — "the before" (Page 1).**
*Show:* Total Turns, Est Cost, Trivial %, model usage at ~100% one model.
> "This is a week of production traffic for our travel agent. Every turn — a 'hi', a
> thank-you, or a full 5-day itinerary — runs on our best, most expensive model. And look:
> a large share of turns are trivial, yet they cost exactly what the hard ones do."

**2. Quantify the waste (Page 2, Cost by Tier).**
> "That giant 'default' slice is spend on a premium model for near-zero-work turns. Nobody
> had to guess this — the app instrumented every turn: tokens, model, handoffs."

**3. The recommendation (the "aha").**
*Show:* the SCEN-007 card in the Optimization Console — evidence from *their* data + projected saving.
> "The system didn't just log it; it *detected* the pattern and *recommends* a fix — route
> trivial turns to a nano model, routine to mini, keep the premium model for the hard stuff.
> Here's the projected saving."

**4. Apply — the live moment (one click).**
*Do:* click **Apply** on the model-selection policy in the Console.
> "Applying it is a reversible policy flip — not a code change, not a redeploy. That's what
> makes this safe to automate."

**5a. Prove it — the A/B (bullet-proof).**
*Do:* flip the **tenant slicer** from `before_demo` to `after_demo`.
> "Same workload, same turns. Before: everything on the premium model. After: tiered. Est cost
> drops ~28% and trivial turns now show up as their own tier — with zero change to the user
> experience."

**5b. Prove it's live — a few real turns (optional flourish).**
*Do:* run the live-turns helper (or type them by hand — see below), then **Refresh** the report
filtered to `demo_live`.
> "And here it is happening for real: watch these new turns land — the greeting routed to nano,
> the itinerary to the premium model."

**6. The business-impact turn — from cost to conversion (the part that lands).**
*Do:* switch the tenant slicer / Console to `funnel_demo` and open the **Cost per outcome & conversion funnel** (SCEN-003) card.
> "Everything so far cut *cost*. But the real question a business asks is: are we *converting*?
> This funnel shows it — 120 sessions engaged, 106 searched, 71 got a plan, only 56 booked. And
> it doesn't leave you hanging on 'why': the biggest addressable leak is **city friction** — 29
> sessions where the agent kept re-asking which city instead of using the active trip. That's not
> a model-cost problem; it's a *conversion* problem, and it points straight at the same
> active-trip-city-context prompt fix — now justified by revenue, not just tokens."

This is the uplevel: mechanical cost optimizations are table stakes; the analytics also surface **where the business is losing customers and why**. A dashboard can't auto-fix conversion — but it can name the cause and hand you the lever.

**7. Close — verify & govern.**
> "The measured before/after is the truth, not the projection — reasoning models bill hidden
> tokens, so we always confirm with real numbers. And every change here is audited and
> reversible."

---

## Live turns — automated

Fires one turn per tier through the **real** app, then derives them into `OptimizationTurns`
so they appear in the report (on 02_completed the app writes `Debug` telemetry and
`OptimizationTurns` is derived from it — the helper does that derive for just its turns).

```powershell
# hosted app (web URL + /api; the API container app is internal-only):
python analytics/demo_live_turns.py --endpoint https://<web-app>.azurecontainerapps.io/api

# local dev app:
python analytics/demo_live_turns.py --endpoint http://localhost:8000
```

Prints how each turn was routed, e.g.:
```
trivial  -> gpt-5-nano   (out=128)
trivial  -> gpt-5-nano   (out=119)
routine  -> gpt-5-mini   (out=704)
complex  -> gpt-5.1      (out=4227)
```
Then **Refresh** the report with the tenant slicer on `demo_live`.

> The model-selection policy must be **active** first (step 4), or the turns record as
> `default`. The helper warns you if that's the case.

---

## Live turns — manual (type these in the app UI)

If you'd rather do it by hand in the chat UI (or the network blocks the script), open the app,
start a new chat, and send these — one per tier, so the routing is obvious:

| Type this | Expected tier | Expected model |
|---|---|---|
| `hi` | trivial | gpt-5-nano |
| `thanks, that's perfect!` | trivial | gpt-5-nano |
| `what are some good hotels in Amsterdam near the centre?` | routine | gpt-5-mini |
| `plan me a detailed 3-day itinerary for Tokyo with hotels, activities, and places to eat` | complex | gpt-5.1 |

Then, to surface them in the report (02_completed derives `OptimizationTurns` from `Debug`):

```powershell
cd 02_completed/python
python data/export_conversations.py --no-write   # derive only, don't overwrite the golden JSON
```

> `--no-write` still upserts derived turns into `OptimizationTurns`; it just skips rewriting the
> committed `data/*.json`. (For a live demo the automated helper is cleaner — it derives only the
> turns it sent.) **Refresh** the report afterward.

---

## What to avoid (the "insane" list)
- Generating hundreds of turns live (slow, flaky, dead air).
- Rebuilding the mirror / semantic model / report on stage.
- Relying **only** on live traffic with no pre-baked fallback — always have the A/B ready.
- Presenting the projected saving as measured — call it a projection; the A/B and the live
  per-turn routing are the proof.

---

## Numbers (built-in A/B, seed 42, 240 turns)
- `before_demo` est cost ≈ **$6.90**, `after_demo` ≈ **$4.95** → **~28% lower**.
- Split of the tiered side ≈ trivial 9% / routine 57% / complex 34% (matched trips both sides,
  so cost-per-outcome is comparable).
- These are list-price *estimates* (from the Cosmos `Configuration` pricing rows); the report
  shows them live. Exact figures depend on the seed/size args.

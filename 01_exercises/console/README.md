# Optimization Console

A small, provided web dashboard for the **Analytics & Optimization** modules (07–08). It reads the
per-turn signal your app captures (`OptimizationTurns`) and the recommendation cards from the
`/optimizations` REST API, and lets you **apply / revert** optimizations with one click.

It is a **teaching surface** — in the workshop you write the loop *logic*, not this UI.

## Run it

The console is a single static file. Serve it on its own port (kept separate from the `:4200` travel
app and the `:8000` API):

```powershell
# from the repository's 01_exercises folder
python -m http.server 8050 --directory console
```

Then open <http://localhost:8050>. In the top bar:

- **API** — your Travel API base URL (default `http://localhost:8000`).
- **Tenant** — the tenant/user you drove traffic with.

Click **Refresh** (or press Enter in the Tenant box).

## What it shows

- **Visibility KPIs** — turns, estimated spend, trivial-turn %, models in use, and **cost per outcome**,
  each with a one-line "why this matters".
- **Model usage** — the model distribution (a single model at 100% is the opportunity).
- **Cost by tier** — spend grouped by the tier that served each turn.
- **Recommendation cards** — detected opportunities with **Apply / Revert** buttons (lower-risk
  policies only; higher-risk prompt/code changes are staged for human review).

## Requirements

- The Travel API must be running with the optimization router mounted
  (`app.include_router(optimization_router)` — Module 07) and permissive CORS (the provided API
  already allows all origins).
- The `OptimizationTurns` / `OptimizationPolicies` Cosmos containers exist (provisioned by `azd up`).

## Endpoints it calls

- `GET /optimizations/{tenant}/metrics` — aggregate KPIs
- `GET /optimizations/{tenant}` — recommendation cards
- `GET /optimizations/policies` — policy status
- `POST /optimizations/{scenario}/apply` · `POST /optimizations/{scenario}/revert`

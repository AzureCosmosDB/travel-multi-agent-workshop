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
- **Analytics infrastructure — Fabric capacity** *(shown only when a capacity is wired up)* — the
  Fabric F-capacity that powers the analytics, with **Pause / Resume** buttons and a **mirror sync**
  indicator. The capacity bills while it is running, so you resume it to refresh the analytics and
  pause it when done to stop the meter. Because pausing/resuming a capacity does **not** auto-manage
  Cosmos mirroring, Resume also restarts mirroring and Pause stops it; the indicator reports whether
  the mirror is **caught up** (all tables past their initial snapshot) and the last sync time, so you
  know when the analytics are current and safe to pause.

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
- `GET /optimizations/fabric/capacity` — Fabric capacity state + mirror sync status
- `POST /optimizations/fabric/capacity/resume` — resume the capacity + restart mirroring
- `POST /optimizations/fabric/capacity/suspend` — stop mirroring + pause the capacity

The Fabric endpoints return `{"configured": false}` (and the console hides the control) unless
`FABRIC_CAPACITY_NAME`, `AZURE_SUBSCRIPTION_ID`, and `AZURE_RESOURCE_GROUP` are set — the
`azd up` post-provision hook writes them to `python/.env` when `deployAnalytics=true`, and
`analytics/fabric/provision_fabric.py` adds `FABRIC_WORKSPACE_ID` / `FABRIC_MIRROR_ID` once the
mirror exists. Locally the API acts as your `az login` identity (the capacity admin), so no extra
RBAC is needed.
